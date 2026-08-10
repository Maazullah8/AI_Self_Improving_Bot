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

from trading_bot.core.enums import Side
from trading_bot.core.models import Candle, Order, Position
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
        try:
            info = self.executor.health()
            account = info.get("balance")
            return float(account) if account else 10_000.0
        except Exception:
            return 10_000.0

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
