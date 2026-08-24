"""Trade journal: converts replay outcomes + signal setup context into the
canonical TradeRecord and persists them to a TradeStore.

The full setup context (bias, confluence, confirmation, zones, etc.) is
captured at signal time in ``Signal.setup`` and attached by the engine, so the
journal can record exactly what the strategy saw when it decided to trade.
"""
from __future__ import annotations

from typing import Protocol, Optional

from trading_bot.core.enums import ExitReason, Side
from trading_bot.core.models import TradeRecord, PartialExit
from trading_bot.replay.engine import ReplayEngine, TradeOutcome


class TradeJournal(Protocol):
    def record_trade(self, outcome: TradeOutcome, engine: ReplayEngine) -> TradeRecord: ...
    def records(self) -> list[TradeRecord]: ...


_CONSUMED_SETUP_KEYS = {
    "bias", "htf_bias", "crt", "liquidity_target", "zone_type",
    "zone_top", "zone_bottom", "confluence_level", "confluence_score",
    "confluence_factors", "htf_timeframe", "ltf_timeframe",
    "refinement_chain", "choch_csd", "confirmation_type", "attempt",
    "session", "regime", "volatility", "spread_at_entry",
    "volume_profile", "day_of_week", "hour_of_day", "alignment",
    "entry_tf_close_bias", "notes", "raw", "dol", "crt_high",
    "crt_low", "inside_bars", "stack_count", "stack_kinds",
}


class Journal:
    """In-memory + optionally persisted journal of completed trades."""

    def __init__(self, store=None, strategy_name: str = "", strategy_version: str = ""):
        self.store = store
        self.strategy_name = strategy_name
        self.strategy_version = strategy_version
        self._records: list[TradeRecord] = []

    def record_trade(self, outcome: TradeOutcome, engine: ReplayEngine) -> TradeRecord:
        pos = outcome.position
        setup = engine.setup_for(pos.id)
        rec = TradeRecord(
            trade_id=pos.id,
            strategy=pos.strategy or self.strategy_name,
            strategy_version=pos.strategy_version or self.strategy_version,
            symbol=pos.symbol,
            side=pos.side,
            entry_time=pos.open_time,
            exit_time=outcome.exit_time,
            duration_seconds=outcome.exit_time - pos.open_time,
            entry_price=pos.open_price,
            exit_price=outcome.exit_price,
            size=pos.size,
            sl=pos.sl,
            tp=pos.tp,
            rr=abs(pos.tp - pos.open_price) / abs(pos.sl - pos.open_price)
            if pos.sl != pos.open_price
            else 0.0,
            pnl=outcome.pnl,
            pnl_points=outcome.pnl_points,
            r=outcome.r,
            mfe=outcome.mfe_r,
            mae=outcome.mae_r,
            exit_reason=outcome.exit_reason,
            partial_exits=[
                PartialExit(time=t, price=p, size=s, reason=ExitReason(r))
                for (t, p, s, r) in outcome.partial_exits
            ],
            spread_paid=0.0,
            slippage_paid=outcome.slippage_paid,
            commission=outcome.commission_paid,
            bias=setup.get("bias", ""),
            htf_bias=setup.get("htf_bias", ""),
            crt=setup.get("crt", ""),
            liquidity_target=setup.get("liquidity_target", ""),
            zone_type=setup.get("zone_type", ""),
            zone_top=float(setup.get("zone_top", 0.0) or 0.0),
            zone_bottom=float(setup.get("zone_bottom", 0.0) or 0.0),
            confluence_level=setup.get("confluence_level", ""),
            confluence_score=int(setup.get("confluence_score", 0) or 0),
            confluence_factors=list(setup.get("confluence_factors", []) or []),
            draw_on_liquidity=str(setup.get("dol") or ""),
            crt_high=float(setup.get("crt_high", 0.0) or 0.0),
            crt_low=float(setup.get("crt_low", 0.0) or 0.0),
            inside_bars=int(setup.get("inside_bars", 0) or 0),
            confluence_stack_count=int(setup.get("stack_count", 0) or 0),
            confluence_stack_kinds=list(setup.get("stack_kinds", []) or []),
            htf_timeframe=setup.get("htf_timeframe", ""),
            ltf_timeframe=setup.get("ltf_timeframe", ""),
            refinement_chain=setup.get("refinement_chain", ""),
            choch_csd=setup.get("choch_csd", ""),
            confirmation_type=setup.get("confirmation_type", ""),
            attempt=int(setup.get("attempt", 1) or 1),
            session=setup.get("session", ""),
            regime=setup.get("regime", ""),
            volatility=float(setup.get("volatility", 0.0) or 0.0),
            spread_at_entry=float(setup.get("spread_at_entry", 0.0) or 0.0),
            volume_profile=setup.get("volume_profile", ""),
            day_of_week=int(setup.get("day_of_week", 0) or 0),
            hour_of_day=int(setup.get("hour_of_day", 0) or 0),
            alignment=setup.get("alignment", ""),
            entry_tf_close_bias=setup.get("entry_tf_close_bias", ""),
            notes=setup.get("notes", ""),
            raw={
                # anything journaled without a dedicated column (tp1,
                # runner_target, checklist, ...) stays available for
                # pattern discovery instead of being dropped.
                **{
                    k: v
                    for k, v in setup.items()
                    if k not in _CONSUMED_SETUP_KEYS
                },
                **(setup.get("raw") or {}),
            },
        )
        self._records.append(rec)
        if self.store is not None:
            self.store.insert(rec)
        return rec

    def records(self) -> list[TradeRecord]:
        return list(self._records)

    def clear(self) -> None:
        self._records.clear()
