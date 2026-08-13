"""Live trading pipeline.

Feeds the latest closed bars to the (stateful) strategy, approves signals
through the risk manager, and executes via an Executor. Fail-closed rules:
- No new bars / stale data  => no signal, no trade.
- Strategy error            => no trade.
- Risk rejection            => no trade.
- Executor / broker unhealthy => no trade.
- Unknown state             => no trade.

Everything is journaled (signals, heartbeats, trades) via the stores.
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Optional, Sequence

from trading_bot.core.enums import ExitReason, PositionStatus, Side
from trading_bot.core.models import Candle, Order, Position, TradeRecord
from trading_bot.core.time_utils import utcnow_ts
from trading_bot.data.base import DataProvider, MarketDataQuery, SymbolInfo
from trading_bot.execution.executor import Executor
from trading_bot.replay.engine import Signal
from trading_bot.risk.manager import RiskManager
from trading_bot.strategy.base import BaseStrategy


class LiveContext:
    """Minimal Context shim satisfying the strategy's expected API."""

    def __init__(self, bars: Sequence[Candle], index: int, symbol_info: SymbolInfo, positions=()):
        self.bars = bars
        self.index = index
        self.current = bars[index]
        self.symbol_info = symbol_info
        self._positions = tuple(positions)

    @property
    def positions(self):
        return self._positions

    def signal(self, **kwargs) -> Signal:
        return Signal(
            bar_index=self.index,
            bar_time=self.current.time,
            symbol=self.symbol_info.symbol,
            **kwargs,
        )


@dataclass
class LiveConfig:
    symbol: str = "EURUSD"
    timeframe: str = "5m"
    lookback_bars: int = 300
    max_staleness_seconds: int = 120
    poll_interval_seconds: int = 5
    min_new_bars: int = 1


@dataclass
class LiveState:
    last_bar_time: int = 0
    last_poll: int = 0
    last_heartbeat: int = 0
    n_polls: int = 0
    n_signals: int = 0
    n_orders: int = 0
    n_rejections: int = 0
    n_errors: int = 0
    status: str = "idle"  # idle|ok|warn|down
    detail: str = ""


class LiveTradePipeline:
    def __init__(
        self,
        provider: DataProvider,
        strategy: BaseStrategy,
        executor: Executor,
        risk: Optional[RiskManager] = None,
        store=None,
        config: Optional[LiveConfig] = None,
        initial_cash: float = 10_000.0,
    ):
        self.provider = provider
        self.strategy = strategy
        self.executor = executor
        self.risk = risk
        self.store = store
        self.config = config or LiveConfig()
        self.state = LiveState()
        self._bars: list[Candle] = []
        self._positions: list[Position] = []
        self._closed: list[TradeRecord] = []
        self._balance = initial_cash
        self._realized = 0.0
        self._extremes: dict[str, tuple[float, float]] = {}

    # ------------------------------------------------------------- poll
    def poll(self, now: Optional[int] = None) -> LiveState:
        now = now or utcnow_ts()
        self.state.last_poll = now
        self.state.n_polls += 1

        # 1. data freshness / availability
        bars = self._fetch_bars(now)
        if not bars:
            self._fail("no data from provider")
            return self.state
        latest = bars[-1].time
        if now - latest > self.config.max_staleness_seconds:
            self._fail(f"stale data (latest bar {latest}, now {now})")
            return self.state

        # 2. feed newly closed bars to the strategy
        new_bars = [b for b in bars if b.time > self.state.last_bar_time]
        if len(new_bars) < self.config.min_new_bars:
            self.state.status = "ok"
            self.state.detail = "no new bars"
            self._heartbeat("ok", "no new bars")
            return self.state

        sym = self.provider.symbol_info(self.config.symbol)
        for bar in new_bars:
            self._bars.append(bar)
            self.state.last_bar_time = bar.time
            self._manage_positions(bar)
            ctx = LiveContext(
                self._bars,
                len(self._bars) - 1,
                sym,
                positions=self._positions,
            )
            try:
                signal = self.strategy.on_bar(ctx)
            except Exception as e:  # fail-closed
                self.state.n_errors += 1
                self._fail(f"strategy error: {e}")
                continue
            if signal is not None:
                self.state.n_signals += 1
                self._handle_signal(signal, ctx, now)

        self.state.status = "ok"
        self.state.detail = f"processed {len(new_bars)} bars"
        self._heartbeat("ok", self.state.detail)
        return self.state

    def _fetch_bars(self, now: int) -> list[Candle]:
        from trading_bot.core.enums import Timeframe

        try:
            tf = Timeframe(self.config.timeframe)
        except ValueError:
            self.state.n_errors += 1
            return []
        start = now - self.config.lookback_bars * tf.minutes * 60
        query = MarketDataQuery(
            symbol=self.config.symbol,
            timeframe=tf,
            start=start,
            end=now,
        )
        try:
            bars = list(self.provider.load_candles(query))
        except Exception:
            self.state.n_errors += 1
            return []
        bars.sort(key=lambda c: c.time)
        # keep only closed bars (a live bar isn't complete until the next opens)
        closed = [b for b in bars if b.time < _bar_end(b.time, tf)]
        return closed

    # ------------------------------------------------------------ signal
    def _handle_signal(self, signal: Signal, ctx: LiveContext, now: int) -> None:
        if self.risk is None:
            self._record_signal(signal, "approved", "")
            self._execute(signal, size=signal.size or 0.01)
            return

        equity = self._equity()
        decision = self.risk.approve(signal, ctx.current, equity, self._positions)
        if not decision.approved:
            self.state.n_rejections += 1
            self._record_signal(signal, "rejected", decision.reason)
            return
        self._record_signal(signal, "executed", decision.reason)
        self._execute(signal, size=decision.size)

    def _execute(self, signal: Signal, size: float) -> None:
        if not self.executor.health().get("ok"):
            self.state.n_rejections += 1
            self.state.n_errors += 1
            self._fail("executor unhealthy; order rejected")
            return
        order = Order(
            id=f"live_{utcnow_ts()}_{self.state.n_orders}",
            symbol=signal.symbol or self.config.symbol,
            side=signal.side,
            type="market",
            size=size,
            price=signal.entry,
            sl=signal.sl,
            tp=signal.tp,
            created_at=signal.bar_time,
            strategy=signal.strategy or self.strategy.name,
            strategy_version=signal.strategy_version or self.strategy.version,
            comment=signal.setup.get("risk_comment", ""),
        )
        result = self.executor.submit_order(order)
        if result.ok:
            self.state.n_orders += 1
            self._positions.append(
                Position(
                    id=result.order_id or order.id,
                    symbol=order.symbol,
                    side=order.side,
                    size=order.size,
                    open_price=result.filled_price or order.price,
                    open_time=result.filled_time or order.created_at,
                    sl=order.sl,
                    tp=order.tp,
                    strategy=order.strategy,
                    strategy_version=order.strategy_version,
                    order_id=result.order_id or order.id,
                )
            )
        else:
            self.state.n_rejections += 1
            self.state.n_errors += 1

    def _equity(self) -> float:
        open_pnl = sum(self._pnl(p, self._last_close()) for p in self._positions if p.status == PositionStatus.OPEN)
        return self._balance + open_pnl

    def _last_close(self) -> float:
        return self._bars[-1].close if self._bars else 0.0

    def _contract_size(self) -> float:
        try:
            return self.provider.symbol_info(self.config.symbol).contract_size or 1.0
        except Exception:
            return 1.0

    def _pnl(self, pos: Position, price: float) -> float:
        if pos.side is Side.BUY:
            return (price - pos.open_price) * pos.size * self._contract_size()
        return (pos.open_price - price) * pos.size * self._contract_size()

    # ------------------------------------------------------ position mgmt
    def _check_exit(self, pos: Position, bar: Candle) -> tuple[Optional[float], Optional[ExitReason]]:
        """Conservative SL/TP: on a same-bar double breach assume SL first."""
        if pos.side is Side.BUY:
            sl_hit = pos.sl and bar.low <= pos.sl
            tp_hit = pos.tp and bar.high >= pos.tp
            if sl_hit and tp_hit:
                return pos.sl, ExitReason.SL
            if sl_hit:
                return pos.sl, ExitReason.SL
            if tp_hit:
                return pos.tp, ExitReason.TP
        else:
            sl_hit = pos.sl and bar.high >= pos.sl
            tp_hit = pos.tp and bar.low <= pos.tp
            if sl_hit and tp_hit:
                return pos.sl, ExitReason.SL
            if sl_hit:
                return pos.sl, ExitReason.SL
            if tp_hit:
                return pos.tp, ExitReason.TP
        return None, None

    def _track_extremes(self, pos: Position, bar: Candle) -> None:
        best, worst = self._extremes.get(pos.id, (pos.open_price, pos.open_price))
        if pos.side is Side.BUY:
            best = max(best, bar.high)
            worst = min(worst, bar.low)
        else:
            best = min(best, bar.low)
            worst = max(worst, bar.high)
        self._extremes[pos.id] = (best, worst)

    def _manage_positions(self, bar: Candle) -> None:
        for pos in list(self._positions):
            if pos.status != PositionStatus.OPEN:
                continue
            self._track_extremes(pos, bar)
            exit_price, reason = self._check_exit(pos, bar)
            if exit_price is not None:
                self._close_position(pos, exit_price, bar.time, reason)

    def _close_position(self, pos: Position, exit_price: float, exit_time: int, reason: ExitReason) -> None:
        self.executor.close_position(pos)
        pnl = self._pnl(pos, exit_price)
        self._realized += pnl
        self._balance += pnl
        self._positions = [p for p in self._positions if p.id != pos.id]
        rec = self._journal_trade(pos, exit_price, exit_time, reason, pnl)
        self._closed.append(rec)
        if self.store is not None and hasattr(self.store, "trades"):
            try:
                self.store.trades.insert(rec)
            except Exception:
                pass

    def _journal_trade(self, pos: Position, exit_price: float, exit_time: int, reason: ExitReason, pnl: float) -> TradeRecord:
        risk_points = abs(pos.open_price - pos.sl)
        risk_units = risk_points * pos.size * self._contract_size() if risk_points > 0 else 0.0
        r = pnl / risk_units if risk_units > 0 else 0.0
        best, worst = self._extremes.get(pos.id, (pos.open_price, pos.open_price))
        mfe = (best - pos.open_price) if pos.side is Side.BUY else (pos.open_price - best)
        mae = (pos.open_price - worst) if pos.side is Side.BUY else (worst - pos.open_price)
        mfe_r = mfe / risk_points if risk_points > 0 else 0.0
        mae_r = mae / risk_points if risk_points > 0 else 0.0
        rr = 0.0
        if pos.sl != pos.open_price:
            rr = abs(pos.tp - pos.open_price) / abs(pos.sl - pos.open_price) if pos.tp else 0.0
        return TradeRecord(
            trade_id=pos.id,
            strategy=pos.strategy or self.strategy.name,
            strategy_version=pos.strategy_version or self.strategy.version,
            symbol=pos.symbol,
            side=pos.side,
            entry_time=pos.open_time,
            exit_time=exit_time,
            duration_seconds=max(exit_time - pos.open_time, 0),
            entry_price=pos.open_price,
            exit_price=exit_price,
            size=pos.size,
            sl=pos.sl,
            tp=pos.tp,
            rr=rr,
            pnl=pnl,
            pnl_points=(exit_price - pos.open_price) * (1 if pos.side is Side.BUY else -1),
            r=r,
            mfe=mfe_r,
            mae=mae_r,
            exit_reason=reason,
        )

    # ----------------------------------------------------------- status
    def status(self) -> dict:
        """Snapshot for the dashboard (open positions, equity, counters)."""
        sym = self.provider.symbol_info(self.config.symbol)
        open_positions = []
        last = self._last_close()
        for p in self._positions:
            if p.status != PositionStatus.OPEN:
                continue
            open_positions.append(
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "side": p.side.value,
                    "entry_price": p.open_price,
                    "current_price": last,
                    "sl": p.sl,
                    "tp": p.tp,
                    "size": p.size,
                    "open_time": p.open_time,
                    "unrealized_pnl": self._pnl(p, last),
                }
            )
        return {
            "running": True,
            "symbol": self.config.symbol,
            "timeframe": self.config.timeframe,
            "strategy": self.strategy.name,
            "strategy_version": self.strategy.version,
            "status": self.state.status,
            "detail": self.state.detail,
            "balance": round(self._balance, 2),
            "equity": round(self._equity(), 2),
            "realized_pnl": round(self._realized, 2),
            "open_positions": open_positions,
            "last_price": last,
            "n_trades": len(self._closed),
            "n_signals": self.state.n_signals,
            "n_polls": self.state.n_polls,
            "n_rejections": self.state.n_rejections,
            "last_bar_time": self.state.last_bar_time,
            "digits": sym.digits,
            "point_size": sym.point_size,
        }

    # -------------------------------------------------------------- store
    def _record_signal(self, signal: Signal, status: str, reject_reason: str) -> None:
        if self.store is None or not hasattr(self.store, "signals"):
            return
        from trading_bot.storage.interfaces import SignalRecord, utcnow_iso

        rec = SignalRecord(
            id=f"sig_{signal.bar_time}_{self.state.n_signals}",
            time=signal.bar_time,
            symbol=signal.symbol or self.config.symbol,
            strategy=signal.strategy or self.strategy.name,
            strategy_version=signal.strategy_version or self.strategy.version,
            direction=signal.side.value if signal.side else "",
            entry=signal.entry,
            sl=signal.sl,
            tp=signal.tp,
            confluence_level=signal.setup.get("confluence_level", ""),
            confluence_score=signal.setup.get("confluence_score", 0),
            risk_check="pass" if status == "executed" else "reject",
            reject_reason=reject_reason,
            status=status,
            created_at=utcnow_iso(),
        )
        self.store.signals.insert(rec)

    def _heartbeat(self, status: str, detail: str) -> None:
        self.state.status = status
        self.state.detail = detail
        self.state.last_heartbeat = utcnow_ts()
        if self.store is None or not hasattr(self.store, "heartbeats"):
            return
        from trading_bot.storage.interfaces import HeartbeatRecord, utcnow_iso

        self.store.heartbeats.insert(
            HeartbeatRecord(
                component=f"live:{self.config.symbol}",
                ts=self.state.last_heartbeat,
                status=status,
                detail=detail,
                created_at=utcnow_iso(),
            )
        )

    def _fail(self, msg: str) -> None:
        self.state.status = "down"
        self.state.detail = msg
        self._heartbeat("down", msg)

    def shutdown(self) -> None:
        self._heartbeat("down", "pipeline stopped")


def _bar_end(t: int, tf) -> int:
    from trading_bot.core.time_utils import bar_open_time

    return bar_open_time(t, tf) + tf.minutes * 60
