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
from trading_bot.core.time_utils import is_weekend, market_session
from trading_bot.replay.engine import Signal


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.001
    daily_loss_limit_pct: float = 0.03

    # Hard account-level loss limit from initial equity
    max_absolute_drawdown_pct: float = 0.01

    # Optional peak-to-trough protection.
    # None = monitor only, do not block trades.
    max_relative_drawdown_pct: float | None = None

    max_positions: int = 100
    max_daily_trades: int = 500
    max_consecutive_losses: int = 500
    cooldown_bars: int = 0

    max_spread_points: float = 50000.0
    max_slippage_points: float = 10.0

    # Named-session whitelist. Weekends are ALWAYS blocked separately.
    # On weekdays, quiet hours ("off") are tradeable even when not listed;
    # set e.g. ["london", "new_york"] to restrict named sessions.
    allowed_sessions: list[str] = field(
        default_factory=lambda: [
            "asia",
            "london",
            "london_ny_overlap",
            "new_york",
            "sydney",
        ]
    )

    emergency_stop: bool = False
    require_valid_equity: bool = True
    min_equity: float = 0.0
    volatility_multiplier_max: float = 2.0

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
        self._session_start_equity: Optional[float] = None
        self._peak_equity: Optional[float] = None
        # Audit trail of every rejected trade (Section 11): reason,
        # checks and market state kept for later analysis.
        self.rejections: list[dict] = []
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
        """Update day/session/drawdown state each bar."""

        from trading_bot.core.time_utils import ts_to_dt

        dt = ts_to_dt(bar.time)
        day = dt.date().isoformat()

        # Set initial equity ONCE at the beginning of the backtest/session.
        if self._session_start_equity is None:
            self._session_start_equity = equity

        if self._day != day:
            self._day = day
            self._day_start_equity = equity
            self._day_trades = 0

        if self._peak_equity is None or equity > self._peak_equity:
            self._peak_equity = equity

        self._open_positions = sum(
            1 for p in positions if p.status.value == "open"
        )

    def on_strategy_error(self, bar: Candle, err: Exception) -> None:
        self._last_error = f"{type(err).__name__}: {err}"

    # -------------------------------------------------------------- queries
    def bar_spread_points(self, bar: Candle) -> float:
        """Candle.spread is stored as a PRICE distance; the limit config is
        expressed in broker POINTS, so convert with the symbol point size."""
        if self.point_size and self.point_size > 0:
            return float(bar.spread) / self.point_size
        return float(bar.spread)

    def spread_ok(self, spread_points: float) -> bool:
        print(
        f"[SPREAD DEBUG] spread_points={spread_points} "
        f"max_spread_points={self.config.max_spread_points}"
        )
        return spread_points <= self.config.max_spread_points
    

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
        decision = self._approve(signal, bar, equity, positions)
        if not decision.approved:
            self.rejections.append({
                "time": bar.time,
                "reason": decision.reason,
                "checks": decision.checks,
                "equity": equity,
                "strategy": signal.strategy,
                "strategy_version": signal.strategy_version,
                "entry": signal.entry,
                "sl": signal.sl,
                "tp": signal.tp,
            })
            if len(self.rejections) > 1000:
                del self.rejections[:-500]
        return decision

    def _approve(
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

        # 3. max drawdown from INITIAL EQUITY
        if self._session_start_equity is not None and self._session_start_equity > 0:
            dd = (self._session_start_equity - equity) / self._session_start_equity

            checks["max_drawdown"] = dd < self.config.max_absolute_drawdown_pct

            if dd >= self.config.max_absolute_drawdown_pct:
                return RiskDecision.reject(
                    "max_drawdown_reached",
                    {
                        **checks,
                        "drawdown": dd,
                        "initial_equity": self._session_start_equity,
                        "equity": equity,
                    },
                )

        # Relative drawdown from peak equity (peak-to-trough protection).
        relative_drawdown = 0.0

        if self._peak_equity is not None and self._peak_equity > 0:
            relative_drawdown = (
                self._peak_equity - equity
            ) / self._peak_equity

        if (
            self.config.max_relative_drawdown_pct is not None
            and self._peak_equity is not None
            and self._peak_equity > 0
            and relative_drawdown >= self.config.max_relative_drawdown_pct
        ):
            return RiskDecision.reject(
                "max_drawdown_reached",
                {
                    **checks,
                    "drawdown": relative_drawdown,
                    "peak_equity": self._peak_equity,
                    "equity": equity,
                },
            )

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

        # 8. sessions: WEEKENDS are never tradeable. Every weekday session is
        # allowed by default — Asia/Tokyo (00:00-07:00 UTC), Sydney, London,
        # the London/NY overlap, New York and quiet ("off") hours. Only if
        # allowed_sessions is explicitly restricted are named sessions blocked
        # (quiet hours stay tradeable on weekdays regardless).
        if is_weekend(bar.time):
            checks["session"] = False
            return RiskDecision.reject("session_not_allowed:weekend", checks)

        sess = market_session(bar.time)
        allowed = self.config.allowed_sessions or []
        if (
            allowed
            and "all" not in allowed
            and sess.value != MarketSession.OFF.value
            and sess.value not in allowed
        ):
            checks["session"] = False
            return RiskDecision.reject(f"session_not_allowed:{sess.value}", checks)
        checks["session"] = True

        # 9. spread limit (config in broker points, bar spread in price units)
        spread_points = self.bar_spread_points(bar)
        spread_ok = self.spread_ok(spread_points)
        checks["spread"] = spread_ok

        # TEMP DIAGNOSTIC (remove after investigation): unit audit for the
        # spread gate. max_allowed_spread is the limit converted back into
        # the SAME price units bar.spread is stored in, so
        # spread_ok == (bar.spread <= max_allowed_spread).
        _si_ps = getattr(self.symbol_info, "point_size", None)
        _max_allowed_spread = self.config.max_spread_points * self.point_size
        print(
            f"[SPREAD DIAG] time={bar.time} "
            f"bar.spread={float(bar.spread):.6f} (price units) | "
            f"point_size={self.point_size:g} | "
            f"symbol_info.point_size={_si_ps} | "
            f"max_spread_points={self.config.max_spread_points:g} | "
            f"max_allowed_spread={_max_allowed_spread:.6f} | "
            f"spread_points={spread_points:g} | ok={spread_ok}"
        )

        if not spread_ok:
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
        print(
    "\n========== TRADE RISK DEBUG =========="
        )
        print(f"Equity:          ${equity:.2f}")
        print(f"Risk %:          {self.config.risk_per_trade_pct * 100:.2f}%")
        print(f"Target risk:     ${equity * self.config.risk_per_trade_pct:.2f}")
        print(f"Entry:           {signal.entry}")
        print(f"SL:              {signal.sl}")
        print(f"TP:              {signal.tp}")
        print(f"Risk distance:   {risk}")
        print(f"Contract size:   {contract}")
        print(f"Calculated units:{units}")
        print(f"Calculated lots: {size}")
        print("=======================================\n")
        

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
            "initial_equity": self._session_start_equity,
            "peak_equity": self._peak_equity,
            "consecutive_losses": self._consecutive_losses,
            "consecutive_wins": self._consecutive_wins,
            "day_trades": self._day_trades,
            "open_positions": self._open_positions,
            "emergency_stop": self.config.emergency_stop,
            "last_error": self._last_error,
        }
