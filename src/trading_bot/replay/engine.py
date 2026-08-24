"""Deterministic, zero-lookahead market simulation.

The replay engine consumes only historical candles (never the live broker)
and exposes an event-driven API to strategies. Key guarantees:

1. ZERO LOOKAHEAD: at bar index ``i`` the strategy may only see bars ``0..i``.
   Entry occurs at the close of the signal bar (its close is known) with
   slippage; SL/TP are evaluated on subsequent bars only.
2. DETERMINISM: same inputs + config => identical output. No randomness
   unless explicitly seeded via config.
3. CONSERVATIVENESS: when a single bar contains both SL and TP for a
   position, the adverse order is assumed (SL first for longs) unless
   ``optimistic_intrabar`` is enabled.

The engine never connects to MT5 and never places real orders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence, Union

from trading_bot.core.enums import ExitReason, OrderStatus, OrderType, PositionStatus, Side
from trading_bot.core.models import Candle, Order, Position, PriceLevel, Tick
from trading_bot.core.time_utils import ts_to_dt
from trading_bot.core.regime import detect_regime
from trading_bot.data.base import SymbolInfo


@dataclass(frozen=True)
class ExecutionConfig:
    slippage_points: float = 0.0  # slippage applied to market fills, in points
    slippage_bps: float = 0.0  # slippage as basis points of price (alternative)
    commission_per_lot: float = 0.0  # commission in account currency per 1.0 lot
    commission_percent: float = 0.0  # commission as fraction of notional
    optimistic_intrabar: bool = False  # False = SL first on same-bar SL+TP
    fill_at_signal_close: bool = True  # True = fill at signal bar close (+slippage)
    max_intrabar_path: str = "ohlc"  # reserved for tick-mode refinement
    partial_exit_at_r: Optional[float] = None  # e.g. 1.0 -> take half at +1R
    breakeven_at_r: Optional[float] = None  # e.g. 1.0 -> move SL to entry at +1R
    trailing_stop_at_r: Optional[float] = None  # e.g. 2.0 -> trail SL behind price
    max_duration_seconds: int = 0  # force-close positions older than this (0=off)


@dataclass(frozen=True)
class ReplayConfig:
    initial_cash: float = 10_000.0
    symbol_info: SymbolInfo = None
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    allow_multiple_positions: bool = False
    seed: Optional[int] = None
    fail_on_strategy_error: bool = False

@dataclass
class Signal:
    """A strategy's intent to trade. Risk manager approves or rejects."""

    side: Side
    entry: float  # reference price (usually signal bar close)
    sl: float
    tp: float
    size: float = 0.0  # 0 = risk manager computes from risk budget
    bar_index: int = 0
    bar_time: int = 0
    strategy: str = ""
    strategy_version: str = ""
    setup: dict = field(default_factory=dict)  # journal context (bias, confluence, etc.)
    attempt: int = 1
    symbol: str = ""


@dataclass
class Fill:
    order_id: str
    side: Side
    price: float
    size: float
    time: int
    slippage: float
    spread: float
    type: OrderType


@dataclass
class EquityPoint:
    time: int
    equity: float
    balance: float
    open_pnl: float
    n_positions: int


@dataclass
class TradeOutcome:
    position: Position
    exit_price: float
    exit_time: int
    exit_reason: ExitReason
    pnl: float
    pnl_points: float
    r: float
    mfe_points: float
    mae_points: float
    mfe_r: float
    mae_r: float
    partial_exits: list = field(default_factory=list)
    slippage_paid: float = 0.0
    commission_paid: float = 0.0


@dataclass
class ReplayResult:
    trades: list[TradeOutcome] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    final_equity: float = 0.0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    fills: list[Fill] = field(default_factory=list)


class ReplayEngine:
    """Drives a strategy over historical candles with realistic fills."""

    def __init__(
        self,
        candles: Sequence[Candle],
        config: ReplayConfig,
        risk_manager=None,
        journal=None,
    ):
        if not candles:
            raise ValueError("ReplayEngine requires at least one candle")
        self.candles = sorted(candles, key=lambda c: c.time)
        self.config = config
        self.sym = config.symbol_info or SymbolInfo(
            symbol="", digits=5, tick_size=1e-5, point_size=0.01
        )
        self.risk = risk_manager
        self.journal = journal
        self.positions: list[Position] = []
        self.trades: list[TradeOutcome] = []
        self.fills: list[Fill] = []
        self.equity_curve: list[EquityPoint] = []
        self._setups: dict[str, dict] = {}
        self._current_regime: str = ""
        self._cash = config.initial_cash
        self._seq = 0
        self._rng = None
        if config.seed is not None:
            import numpy as np

            self._rng = np.random.default_rng(config.seed)

    # ------------------------------------------------------------------ state
    @property
    def cash(self) -> float:
        return self._cash

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_{self._seq}"

    def _point_size(self) -> float:
        return self.sym.point_size or 1e-5

    def _apply_slippage(self, price: float, side: Side) -> float:
        """Market order slippage always moves price against the taker."""
        pt = self._point_size()
        slip = self.config.execution.slippage_points * pt
        if self.config.execution.slippage_bps:
            slip = price * self.config.execution.slippage_bps / 10_000.0
        if self._rng is not None:
            slip *= abs(float(self._rng.normal(1.0, 0.2)))
        if side is Side.BUY:
            return price + slip
        return price - slip

    def _spread_for_bar(self, bar: Candle) -> float:
        """Return spread as a PRICE distance.

        Convention across the whole pipeline: ``Candle.spread`` stores the
        spread in PRICE units (see ``core.models.Candle``). Providers that
        natively work in broker points (MT5) convert to price units at
        ingestion, so no further conversion happens here.

        Example for XAUUSD:
            spread = 1.62 (price distance)
            point_size = 0.01

        If a candle carries no spread info we fall back to one point so
        fills still model a minimal transaction cost.
        """
        if bar.spread and bar.spread > 0:
            return float(bar.spread)

        return self._point_size()

    def _fill_price(self, side: Side, ref_price: float, bar: Candle) -> float:
        """Market fill price at signal close, including spread + slippage.

        Buy fills at ask (mid + spread/2), sell at bid (mid - spread/2).
        """
        half = self._spread_for_bar(bar) / 2.0
        base = ref_price + half if side is Side.BUY else ref_price - half
        return self._apply_slippage(base, side)

    # ------------------------------------------------------------- execution
    def open_position(
        self,
        signal: Signal,
        size: float,
        bar: Candle,
        risk_comment: str = "",
    ) -> Optional[Position]:
        """Execute a market entry at the signal bar's close (zero lookahead:
        the close is known once the bar is complete)."""
        fill_price = self._fill_price(signal.side, signal.entry, bar)
        if fill_price <= 0:
            return None
        pos_id = self._next_id("pos")
        order_id = self._next_id("ord")
        size = max(self.sym.lot_min, size)
        if not self.config.allow_multiple_positions:
            if any(p.status == PositionStatus.OPEN for p in self.positions):
                return None
        pos = Position(
            id=pos_id,
            symbol=signal.symbol or self.sym.symbol,
            side=signal.side,
            size=size,
            open_price=fill_price,
            open_time=bar.time,
            sl=signal.sl,
            tp=signal.tp,
            status=PositionStatus.OPEN,
            strategy=signal.strategy,
            strategy_version=signal.strategy_version,
            order_id=order_id,
            broker_comment=risk_comment,
        )
        self.positions.append(pos)
        self._setups[pos.id] = dict(signal.setup or {})
        commission = self._commission_for(pos)
        self._cash -= commission
        self.fills.append(
            Fill(
                order_id=order_id,
                side=signal.side,
                price=fill_price,
                size=size,
                time=bar.time,
                slippage=abs(fill_price - signal.entry) - self._spread_for_bar(bar) / 2,
                spread=self._spread_for_bar(bar),
                type=OrderType.MARKET,
            )
        )
        print("\n========== EXECUTION DEBUG ==========")
        print(f"Signal entry:    {signal.entry}")
        print(f"Actual fill:     {fill_price}")
        print(f"Spread points:   {bar.spread}")
        print(f"Spread price:    {self._spread_for_bar(bar)}")
        print(f"Point size:      {self._point_size()}")
        print(f"SL:              {signal.sl}")
        print(f"TP:              {signal.tp}")
        print(f"Size/lots:       {size}")
        print(f"Contract size:   {self._contract_size()}")
        print("======================================")
        if self.risk is not None:
            self.risk.on_position_open(pos)
        return pos

    def _commission_for(self, pos: Position) -> float:
        exec_ = self.config.execution
        c = exec_.commission_per_lot * pos.size
        if exec_.commission_percent:
            c += pos.size * pos.open_price * exec_.commission_percent * 100
        return c

    def _contract_size(self) -> float:
        return self.sym.contract_size or 1.0

    def _notional(self, pos: Position, price: float) -> float:
        return pos.size * price * self._contract_size()

    def _pnl(self, pos: Position, exit_price: float) -> float:
        """P&L in account currency. size is in lots; P&L = price_diff *
        lots * contract_size."""
        if pos.side is Side.BUY:
            return (exit_price - pos.open_price) * pos.size * self._contract_size()
        return (pos.open_price - exit_price) * pos.size * self._contract_size()

    def _points(self, pos: Position) -> float:
        return self._point_size()

    # ----------------------------------------------------------- bar pipeline
    def run(
        self,
        strategy,
        cancel_check=None,
        on_progress=None,
        progress_every: int = 2000,
    ) -> ReplayResult:
        """Run the strategy over all bars. ``strategy`` must expose
        ``on_bar(ctx) -> Optional[Signal]`` where ctx is a Context with the
        closed-bar history.

        Optional cooperative cancellation / progress reporting (used by the
        dashboard so long backtests can be cancelled and watched live):
          - ``cancel_check``: zero-arg callable; when it returns True the run
            stops at the current bar, open positions are flattened at that
            bar's close and a PARTIAL result is returned (``self.cancelled``
            is set to True).
          - ``on_progress``: callable receiving a dict snapshot every
            ``progress_every`` bars (bar_index, n_bars, time, equity,
            n_trades).
        """
        self.cancelled = False
        n = len(self.candles)
        for i in range(n):
            if cancel_check is not None and cancel_check():
                self.cancelled = True
                last_bar = self.candles[i]
                self._close_all(
                    PositionStatus.FLATTENED, ExitReason.STRATEGY_EXIT, last_bar
                )
                break
            bar = self.candles[i]
            self._manage_positions(bar)
            # snapshot equity BEFORE new entries so signals can't leak fills
            self._snapshot_equity(bar)
            if self.risk is not None:
                self.risk.on_bar_end(bar, self._equity(), self.positions)
            if on_progress is not None and (i % max(1, progress_every) == 0):
                try:
                    on_progress({
                        "bar_index": i,
                        "n_bars": n,
                        "time": bar.time,
                        "equity": self._equity(),
                        "n_trades": len(self.trades),
                    })
                except Exception:
                    pass  # progress reporting must never break the run
            self._current_regime = detect_regime(self.candles[max(0, i - 59) : i + 1])
            ctx = Context(self, i)
            try:
                signal = strategy.on_bar(ctx)
            except Exception as e:  # fail-closed: strategy errors never trade
                if self.risk is not None:
                    self.risk.on_strategy_error(bar, e)
                    if self.config.fail_on_strategy_error:
                        raise
                signal = None
            if signal is not None:
                if not signal.strategy:
                    signal.strategy = getattr(strategy, "name", "") or ""
                if not signal.strategy_version:
                    signal.strategy_version = getattr(strategy, "version", "") or ""
                self._process_signal(signal, bar, i)
        self._close_all(PositionStatus.FLATTENED, ExitReason.FLATTEN, self.candles[-1])
        return self._result()

    def _process_signal(self, signal: Signal, bar: Candle, i: int) -> None:
        # Complete trade-state logging: make sure market-context fields
        # exist on every signal so the journal can persist them, whether
        # or not the strategy filled them in.
        setup = signal.setup
        setup.setdefault("regime", getattr(self, "_current_regime", ""))
        setup.setdefault("spread_at_entry", float(bar.spread or 0.0))
        dt = ts_to_dt(bar.time)
        setup.setdefault("day_of_week", dt.weekday())
        setup.setdefault("hour_of_day", dt.hour)
        size = signal.size
        if self.risk is not None:
            decision = self.risk.approve(signal, bar, self._equity(), self.positions)
            if not decision.approved:
                print(
                    f"[RISK REJECT] "
                    f"bar={i} "
                    f"reason={decision.reason} "
                    f"checks={decision.checks}"
                )
                return
            size = decision.size
            signal.size = size
            signal.setup["risk_comment"] = decision.reason
        elif size <= 0:
            return
        self.open_position(signal, size, bar)

    def _manage_positions(self, bar: Candle) -> None:
        """Evaluate SL/TP and management rules for all open positions on this
        bar. Only uses this bar's OHLC (no future info)."""
        exec_ = self.config.execution
        for pos in list(self.positions):
            if pos.status != PositionStatus.OPEN:
                continue
            self._update_extremes(pos, bar)
            self._apply_management(pos, bar)
            exit_price, reason = self._check_exit(pos, bar)
            if exit_price is not None:
                self._close_position(pos, exit_price, bar.time, reason)
            elif exec_.max_duration_seconds and (
                bar.time - pos.open_time >= exec_.max_duration_seconds
            ):
                self._close_position(pos, bar.close, bar.time, ExitReason.STRATEGY_EXIT)

    def _update_extremes(self, pos: Position, bar: Candle) -> None:
        """Track MFE/MAE (in points) for each open position using bar OHLC."""
        if not hasattr(self, "_extreme_tracker"):
            self._extreme_tracker = {}
        key = pos.id
        pts = self._points(pos)
        if pos.side is Side.BUY:
            fav = bar.high - pos.open_price
            adv = pos.open_price - bar.low
        else:
            fav = pos.open_price - bar.low
            adv = bar.high - pos.open_price
        prev_mfe, prev_mae = self._extreme_tracker.get(key, (0.0, 0.0))
        self._extreme_tracker[key] = (
            max(prev_mfe, fav / pts),
            max(prev_mae, adv / pts),
        )

    def _check_exit(self, pos: Position, bar: Candle) -> tuple[Optional[float], Optional[ExitReason]]:
        """Determine SL/TP hit given this bar. Conservative ordering: on the
        same bar where both SL and TP are breached, assume SL first unless
        ``optimistic_intrabar`` is set. Returns (price, reason)."""
        if pos.side is Side.BUY:
            sl_hit = pos.sl and bar.low <= pos.sl
            tp_hit = pos.tp and bar.high >= pos.tp
            if sl_hit and tp_hit:
                if self.config.execution.optimistic_intrabar:
                    return pos.tp, ExitReason.TP
                return pos.sl, ExitReason.SL
            if sl_hit:
                return pos.sl, ExitReason.SL
            if tp_hit:
                return pos.tp, ExitReason.TP
        else:
            sl_hit = pos.sl and bar.high >= pos.sl
            tp_hit = pos.tp and bar.low <= pos.tp
            if sl_hit and tp_hit:
                if self.config.execution.optimistic_intrabar:
                    return pos.tp, ExitReason.TP
                return pos.sl, ExitReason.SL
            if sl_hit:
                return pos.sl, ExitReason.SL
            if tp_hit:
                return pos.tp, ExitReason.TP
        return None, None

    def _apply_management(self, pos: Position, bar: Candle) -> None:
        """Partial take-profit, break-even and trailing logic.

        Mutates the position's sl/tp/size using immutable-replacement since
        Position is frozen. Only uses realised high/low up to this bar.
        """
        exec_ = self.config.execution
        if pos.status != PositionStatus.OPEN:
            return
        risk_points = abs(pos.open_price - pos.sl)
        if risk_points <= 0:
            return

        if pos.side is Side.BUY:
            fav = bar.high
        else:
            fav = bar.low

        # partial exit at +1R
        if exec_.partial_exit_at_r is not None and not pos.broker_comment.startswith("partial:"):
            target = pos.open_price + risk_points * exec_.partial_exit_at_r if pos.side is Side.BUY else pos.open_price - risk_points * exec_.partial_exit_at_r
            hit = fav >= target if pos.side is Side.BUY else fav <= target
            if hit:
                half = pos.size / 2.0
                if half > 0:
                    self._partial_exit(pos, target, bar.time, half, ExitReason.PARTIAL_TP)
                    pos = Position(
                        id=pos.id, symbol=pos.symbol, side=pos.side, size=half,
                        open_price=pos.open_price, open_time=pos.open_time,
                        sl=pos.sl, tp=pos.tp, status=pos.status,
                        close_price=pos.close_price, close_time=pos.close_time,
                        strategy=pos.strategy, strategy_version=pos.strategy_version,
                        order_id=pos.order_id, broker_comment="partial:1r",
                    )
                    self._replace_position(pos)

        # break-even move
        if exec_.breakeven_at_r is not None:
            target = pos.open_price + risk_points * exec_.breakeven_at_r if pos.side is Side.BUY else pos.open_price - risk_points * exec_.breakeven_at_r
            hit = fav >= target if pos.side is Side.BUY else fav <= target
            if hit and not pos.broker_comment.startswith("be:"):
                be_price = pos.open_price if pos.side is Side.BUY else pos.open_price
                pos = Position(
                    id=pos.id, symbol=pos.symbol, side=pos.side, size=pos.size,
                    open_price=pos.open_price, open_time=pos.open_time,
                    sl=be_price, tp=pos.tp, status=pos.status,
                    close_price=pos.close_price, close_time=pos.close_time,
                    strategy=pos.strategy, strategy_version=pos.strategy_version,
                    order_id=pos.order_id, broker_comment="be:1r",
                )
                self._replace_position(pos)

        # trailing stop
        if exec_.trailing_stop_at_r is not None and pos.broker_comment.startswith("be:"):
            trail_target = pos.open_price + risk_points * exec_.trailing_stop_at_r if pos.side is Side.BUY else pos.open_price - risk_points * exec_.trailing_stop_at_r
            hit = fav >= trail_target if pos.side is Side.BUY else fav <= trail_target
            if hit:
                new_sl = fav - risk_points if pos.side is Side.BUY else fav + risk_points
                if pos.side is Side.BUY:
                    new_sl = max(new_sl, pos.sl)
                else:
                    new_sl = min(new_sl, pos.sl)
                pos = Position(
                    id=pos.id, symbol=pos.symbol, side=pos.side, size=pos.size,
                    open_price=pos.open_price, open_time=pos.open_time,
                    sl=new_sl, tp=pos.tp, status=pos.status,
                    close_price=pos.close_price, close_time=pos.close_time,
                    strategy=pos.strategy, strategy_version=pos.strategy_version,
                    order_id=pos.order_id, broker_comment="trail",
                )
                self._replace_position(pos)

    def _replace_position(self, new_pos: Position) -> None:
        for i, p in enumerate(self.positions):
            if p.id == new_pos.id:
                self.positions[i] = new_pos
                return

    def _partial_exit(self, pos: Position, price: float, time: int, size: float, reason: ExitReason) -> None:
        # realize P&L on the partial portion
        partial_pnl = self._pnl(pos, price) * (size / pos.size) if pos.size else 0.0
        if not hasattr(self, "_realized_partial"):
            self._realized_partial = {}
        prev = self._realized_partial.get(pos.id, 0.0)
        self._realized_partial[pos.id] = prev + partial_pnl
        self._cash += partial_pnl
        # commission on the partial portion
        exec_ = self.config.execution
        c = exec_.commission_per_lot * size
        self._cash -= c
        # record partial exit event
        if not hasattr(self, "_partial_exits"):
            self._partial_exits = {}
        self._partial_exits.setdefault(pos.id, []).append(
            (time, price, size, reason.value)
        )

    def _close_position(self, pos: Position, exit_price: float, time: int, reason: ExitReason) -> None:
        # realized partial P&L accumulates into the trade's total P&L
        partial_pnl = 0.0
        if hasattr(self, "_realized_partial"):
            partial_pnl = self._realized_partial.get(pos.id, 0.0)
        pnl = self._pnl(pos, exit_price) + partial_pnl
        comm_close = self._commission_for(pos)
        self._cash += self._pnl(pos, exit_price)
        self._cash -= comm_close
        risk_points = abs(pos.open_price - pos.sl)
        pts = self._points(pos)
        mfe_points, mae_points = self._tracked_extremes(pos)
        risk_units = risk_points * pos.size * self._contract_size()
        r = pnl / risk_units if risk_units > 0 else 0.0
        risk_in_price = risk_points / pts if risk_points > 0 else 0.0
        mfe_r = (mfe_points * pts) / risk_points if risk_points > 0 else 0.0
        mae_r = (mae_points * pts) / risk_points if risk_points > 0 else 0.0
        closed = Position(
            id=pos.id, symbol=pos.symbol, side=pos.side, size=pos.size,
            open_price=pos.open_price, open_time=pos.open_time,
            sl=pos.sl, tp=pos.tp, status=PositionStatus.CLOSED,
            close_price=exit_price, close_time=time,
            strategy=pos.strategy, strategy_version=pos.strategy_version,
            order_id=pos.order_id, broker_comment=pos.broker_comment,
        )
        self._replace_position(closed)
        outcome = TradeOutcome(
            position=closed,
            exit_price=exit_price,
            exit_time=time,
            exit_reason=reason,
            pnl=pnl,
            pnl_points=(exit_price - pos.open_price) * (1 if pos.side is Side.BUY else -1),
            r=r,
            mfe_points=mfe_points,
            mae_points=mae_points,
            mfe_r=mfe_r,
            mae_r=mae_r,
            slippage_paid=0.0,
            commission_paid=comm_close + self._commission_for(pos),
            partial_exits=list(getattr(self, "_partial_exits", {}).get(pos.id, [])),
        )
        self.trades.append(outcome)

        if self.risk is not None:
            self.risk.on_trade_close(r)

        if self.journal is not None:
            self.journal.record_trade(outcome, self)

    def _tracked_extremes(self, pos: Position) -> tuple[float, float]:
        """MFE/MAE in points, computed from bars the position was open through."""
        if not hasattr(self, "_extreme_tracker"):
            self._extreme_tracker = {}
        return self._extreme_tracker.get(pos.id, (0.0, 0.0))

    def setup_for(self, pos_id: str) -> dict:
        return self._setups.get(pos_id, {})

    def _snapshot_equity(self, bar: Candle) -> None:
        open_pnl = sum(self._pnl(p, bar.close) for p in self.positions if p.status == PositionStatus.OPEN)
        equity = self._cash + open_pnl
        self.equity_curve.append(
            EquityPoint(
                time=bar.time,
                equity=equity,
                balance=self._cash,
                open_pnl=open_pnl,
                n_positions=sum(1 for p in self.positions if p.status == PositionStatus.OPEN),
            )
        )

    def _equity(self) -> float:
        if self.equity_curve:
            return self.equity_curve[-1].equity
        return self._cash

    def _close_all(self, status: PositionStatus, reason: ExitReason, bar: Candle) -> None:
        for pos in list(self.positions):
            if pos.status == PositionStatus.OPEN:
                self._close_position(pos, bar.close, bar.time, reason)

    def _result(self) -> ReplayResult:
        return ReplayResult(
            trades=self.trades,
            equity_curve=self.equity_curve,
            final_equity=self._cash,
            total_commission=sum(t.commission_paid for t in self.trades),
            total_slippage=sum(t.slippage_paid for t in self.trades),
            fills=self.fills,
        )


class Context:
    """Zero-lookahead view given to the strategy at each closed bar."""

    def __init__(self, engine: ReplayEngine, index: int):
        self._engine = engine
        self.index = index
        self.bars = engine.candles[: index + 1]  # only closed bars
        self.current = engine.candles[index]
        self.symbol_info = engine.sym

    @property
    def positions(self) -> Sequence[Position]:
        return tuple(p for p in self._engine.positions if p.status == PositionStatus.OPEN)

    def bars_before(self, n: int) -> Sequence[Candle]:
        return self.bars[: max(0, self.index + 1 - n)]

    def signal(self, **kwargs) -> Signal:
        return Signal(
            bar_index=self.index,
            bar_time=self.current.time,
            symbol=self.symbol_info.symbol,
            **kwargs,
        )


class DummyRiskManager:
    """No-op risk manager for replay-only tests."""

    def approve(self, signal, bar, equity, positions):
        from trading_bot.risk.manager import RiskDecision

        return RiskDecision.approve(signal.size or 1.0, {})

    def on_position_open(self, pos):
        pass

    def on_bar_end(self, bar, equity, positions):
        pass

    def on_strategy_error(self, bar, err):
        pass

    def on_trade_close(self, r):
        pass
