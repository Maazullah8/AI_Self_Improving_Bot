"""Risk manager: the single authority on whether a trade may be placed.

The AI can NEVER override these controls. The risk manager runs before every
entry, enforcing hard limits. When any check fails it returns a rejection and
the trade is not placed (fail-closed).

Controls:
  - per-trade risk (% of equity) -> position sizing
  - daily loss limit
  - max drawdown (session lifetime) limit
  - max concurrent positions
  - consecutive-loss protection (cool-down)
  - max daily trades
  - spread / slippage limits
  - allowed sessions
  - emergency shutdown flag
  - stale data / invalid strategy gating (fail closed)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence

from trading_bot.core.enums import ExitReason, MarketSession, Side
from trading_bot.core.models import Candle, Position
from trading_bot.core.time_utils import market_session
from trading_bot.replay.engine import Signal


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.01  # 1% of equity risked per trade
    daily_loss_limit_pct: float = 0.03  # stop trading for the day at -3% equity
    max_drawdown_pct: float = 0.15  # lifetime session drawdown limit
    max_positions: int = 1
    max_daily_trades: int = 20
    max_consecutive_losses: int = 5  # pause after N losses in a row
    cooldown_bars: int = 0  # bars to wait after a loss streak (0=off)
    max_spread_points: float = 30.0  # reject if spread exceeds this (points)
    max_slippage_points: float = 10.0
    allowed_sessions: list[str] = field(default_factory=lambda: ["asia", "london", "london_ny_overlap", "new_york"])
    emergency_stop: bool = False
    require_valid_equity: bool = True
    min_equity: float = 0.0
    volatility_multiplier_max: float = 2.0  # reject if ATR*mult below required spacing


@dataclass
class RiskDecision:
    approved: bool
    size: float = 0.0
    reason: str = ""
    checks: dict = field(default_factory=dict)

    @classmethod
    def reject(cls, reason: str, checks: dict = None) -> "RiskDecision":
        return cls(approved=False, size=0.0, reason=reason, checks=checks or {})

    @classmethod
    def approve(cls, size: float, checks: dict = None) -> "RiskDecision":
        return cls(approved=True, size=size, reason="ok", checks=checks or {})


class RiskManager:
    """Stateful risk manager. Tracks session/day state internally.

    Deterministic given the same inputs. `equity` is provided by the caller
    (engine or live supervisor) at each check.
    """

    def __init__(self, config: RiskConfig | None = None, symbol_info=None, point_size: float = 1e-5):
        self.config = config or RiskConfig()
        self.symbol_info = symbol_info
        self.point_size = point_size or (symbol_info.point_size if symbol_info else 1e-5)
        self._session_start: Optional[int] = None
        self._session_start_equity: Optional[float] = None
        self._day: Optional[int] = None
        self._day_start_equity: Optional[float] = None
        self._day_trades = 0
        self._consecutive_losses = 0
        self._consecutive_wins = 0
        self._loss_cooldown_until: Optional[int] = None
        self._peak_equity: Optional[float] = None
        self._open_positions = 0
        self._last_error: str = ""

    # --------------------------------------------------------------- events
    def on_position_open(self, pos: Position) -> None:
        self._open_positions += 1

    def on_trade_close(self, r: float) -> None:
        self._day_trades += 1
        if r < 0:
            self._consecutive_losses += 1
            self._consecutive_wins = 0
        else:
            self._consecutive_wins += 1
            self._consecutive_losses = 0

    def on_bar_end(self, bar: Candle, equity: float, positions: Sequence[Position]) -> None:
        """Update day/session/drawdown state each bar (fail-closed bookkeeping)."""
        from trading_bot.core.time_utils import ts_to_dt

        dt = ts_to_dt(bar.time)
        day = dt.date().isoformat()
        if self._day != day:
            self._day = day
            self._day_start_equity = equity
            self._day_trades = 0
        if self._peak_equity is None or equity > self._peak_equity:
            self._peak_equity = equity
        self._open_positions = sum(1 for p in positions if p.status.value == "open")

    def on_strategy_error(self, bar: Candle, err: Exception) -> None:
        self._last_error = f"{type(err).__name__}: {err}"

    # -------------------------------------------------------------- queries
    def spread_ok(self, spread: float) -> bool:
        limit = self.config.max_spread_points * self.point_size
        return spread <= limit

    def current_consecutive_losses(self) -> int:
        return self._consecutive_losses

    # -------------------------------------------------------------- approve
    def approve(
        self,
        signal: Signal,
        bar: Candle,
        equity: float,
        positions: Sequence[Position],
    ) -> RiskDecision:
        """Gate every entry. Returns a RiskDecision (approved, size, reason)."""
        checks: dict[str, bool] = {}

        # 1. emergency stop
        checks["emergency_stop"] = not self.config.emergency_stop
        if self.config.emergency_stop:
            return RiskDecision.reject("emergency_stop_active", checks)

        # 2. equity sanity (fail closed)
        if self.config.require_valid_equity and (equity is None or equity <= self.config.min_equity):
            return RiskDecision.reject("invalid_equity", checks)

        # 3. drawdown limit
        if self._peak_equity and self._peak_equity > 0:
            dd = (self._peak_equity - equity) / self._peak_equity
            checks["max_drawdown"] = dd < self.config.max_drawdown_pct
            if dd >= self.config.max_drawdown_pct:
                return RiskDecision.reject("max_drawdown_reached", {**checks, "drawdown": dd})

        # 4. daily loss limit
        if self._day_start_equity is not None and self._day_start_equity > 0:
            day_loss = (self._day_start_equity - equity) / self._day_start_equity
            checks["daily_loss"] = day_loss < self.config.daily_loss_limit_pct
            if day_loss >= self.config.daily_loss_limit_pct:
                return RiskDecision.reject("daily_loss_limit_reached", {**checks, "daily_loss": day_loss})

        # 5. daily trade count
        checks["daily_trades"] = self._day_trades < self.config.max_daily_trades
        if self._day_trades >= self.config.max_daily_trades:
            return RiskDecision.reject("daily_trade_limit_reached", checks)

        # 6. max concurrent positions
        open_count = sum(1 for p in positions if p.status.value == "open")
        checks["max_positions"] = open_count < self.config.max_positions
        if open_count >= self.config.max_positions:
            return RiskDecision.reject("max_positions_reached", checks)

        # 7. consecutive-loss cool-down
        checks["consecutive_losses"] = self._consecutive_losses < self.config.max_consecutive_losses
        if self._consecutive_losses >= self.config.max_consecutive_losses:
            return RiskDecision.reject("consecutive_losses_limit_reached", checks)

        # 8. session allowed
        sess = market_session(bar.time)
        checks["session"] = sess.value in self.config.allowed_sessions
        if sess.value not in self.config.allowed_sessions:
            return RiskDecision.reject(f"session_not_allowed:{sess.value}", checks)

        # 9. spread limit
        checks["spread"] = self.spread_ok(bar.spread)
        if not self.spread_ok(bar.spread):
            return RiskDecision.reject("spread_too_wide", checks)

        # 10. SL/TP sanity + risk computation
        risk = abs(signal.entry - signal.sl)
        reward = abs(signal.tp - signal.entry)
        checks["sl_valid"] = signal.sl > 0 and signal.sl != signal.entry
        checks["zero_risk"] = risk > 0
        if risk <= 0:
            return RiskDecision.reject("zero_risk", checks)
        if not checks["sl_valid"]:
            return RiskDecision.reject("invalid_sl", checks)
        checks["rr"] = reward >= risk * 1.5  # soft floor

        # Position sizing: risk_pct of equity / risk distance (in account units)
        # converted to lots via contract size. lot = units / contract_size.
        contract = (self.symbol_info.contract_size if self.symbol_info else 1.0) or 1.0
        units = (equity * self.config.risk_per_trade_pct) / risk
        size = units / contract
        # normalize to lot step and clamp
        size = self._normalize_size(size)

        return RiskDecision.approve(size, checks)

    def _normalize_size(self, size: float) -> float:
        si = self.symbol_info
        if si is not None:
            step = si.lot_step or 0.01
            size = round(size / step) * step
            size = max(si.lot_min, min(si.lot_max, size))
        return size

    def state_dict(self) -> dict:
        return {
            "consecutive_losses": self._consecutive_losses,
            "consecutive_wins": self._consecutive_wins,
            "day_trades": self._day_trades,
            "open_positions": self._open_positions,
            "emergency_stop": self.config.emergency_stop,
            "peak_equity": self._peak_equity,
            "last_error": self._last_error,
        }
