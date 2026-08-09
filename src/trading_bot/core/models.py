"""Core domain models: candles, ticks, orders, positions, trades.

All models are frozen dataclasses (immutable) for deterministic behaviour.
The schema here IS the unified data format the whole pipeline depends on.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from trading_bot.core.enums import (
    ExitReason,
    OrderStatus,
    OrderType,
    PositionStatus,
    Side,
)


@dataclass(frozen=True)
class Candle:
    """A single OHLCV bar in the unified format."""

    time: int  # epoch seconds (UTC), bar open time
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    spread: float = 0.0  # average/representative spread in price units (points*point_size)

    @property
    def body(self) -> float:
        return self.close - self.open

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2.0


@dataclass(frozen=True)
class Tick:
    """A single price tick."""

    time: int
    bid: float
    ask: float
    volume: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid


@dataclass(frozen=True)
class Order:
    """A broker order. Replay/live use the same model."""

    id: str
    symbol: str
    side: Side
    type: OrderType
    size: float
    price: float = 0.0  # limit/stop price (0 for market)
    sl: float = 0.0
    tp: float = 0.0
    created_at: int = 0
    status: OrderStatus = OrderStatus.PENDING
    filled_price: float = 0.0
    filled_time: int = 0
    comment: str = ""
    strategy: str = ""
    strategy_version: str = ""


@dataclass(frozen=True)
class Position:
    """A held position."""

    id: str
    symbol: str
    side: Side
    size: float
    open_price: float
    open_time: int
    sl: float
    tp: float
    status: PositionStatus = PositionStatus.OPEN
    close_price: float = 0.0
    close_time: int = 0
    strategy: str = ""
    strategy_version: str = ""
    order_id: str = ""
    broker_comment: str = ""


@dataclass
class PriceLevel:
    """A price level with a label, used for SL/TP/zone geometry."""

    price: float
    label: str = ""
    source: str = ""  # e.g. 'candle_extreme', 'zone', 'htf_swing'


@dataclass
class PartialExit:
    time: int
    price: float
    size: float
    reason: ExitReason


@dataclass
class TradeRecord:
    """The canonical, immutable record of a completed trade."""

    # Identity
    trade_id: str = ""
    strategy: str = ""
    strategy_version: str = ""
    symbol: str = ""
    side: Side = Side.BUY

    # Timing
    entry_time: int = 0
    exit_time: int = 0
    duration_seconds: int = 0

    # Prices & sizes
    entry_price: float = 0.0
    exit_price: float = 0.0
    size: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    rr: float = 0.0  # configured risk:reward at entry

    # P&L
    pnl: float = 0.0  # net P/L in account currency
    pnl_points: float = 0.0
    r: float = 0.0  # realized R multiple
    mfe: float = 0.0  # max favorable excursion (R)
    mae: float = 0.0  # max adverse excursion (R)
    exit_reason: ExitReason = ExitReason.UNKNOWN
    partial_exits: list[PartialExit] = field(default_factory=list)

    # Fees/slippage
    spread_paid: float = 0.0
    slippage_paid: float = 0.0
    commission: float = 0.0

    # Setup context (from strategy) — journaled for AI review
    bias: str = ""
    htf_bias: str = ""
    crt: str = ""
    liquidity_target: str = ""
    zone_type: str = ""
    zone_top: float = 0.0
    zone_bottom: float = 0.0
    confluence_level: str = ""
    confluence_score: int = 0
    confluence_factors: list[str] = field(default_factory=list)
    htf_timeframe: str = ""
    ltf_timeframe: str = ""
    refinement_chain: str = ""
    choch_csd: str = ""
    confirmation_type: str = ""
    attempt: int = 1
    session: str = ""
    regime: str = ""
    volatility: float = 0.0  # ATR at entry (price units)
    spread_at_entry: float = 0.0
    volume_profile: str = ""
    day_of_week: int = 0
    hour_of_day: int = 0
    alignment: str = ""  # HTF/LTF alignment summary
    entry_tf_close_bias: str = ""  # entry candle body direction
    notes: str = ""
    raw: dict = field(default_factory=dict)  # opaque extras for debugging

    def to_dict(self) -> dict:
        return {
            k: (v.value if isinstance(v, (Side, ExitReason)) else v)
            for k, v in self.__dict__.items()
            if k != "raw"
        } | {"raw": self.raw}


def point_size_for_digits(digits: int) -> float:
    """Return the pip/point size (price value of one point) for a digit count.

    e.g. digits=5 -> point = 1e-5 ; digits=3 -> point = 1e-3
    """
    if digits <= 0:
        raise ValueError("digits must be positive")
    return 10 ** (-digits)


def pip_size_for_digits(digits: int, pip_digits: int = 1) -> float:
    """Return the pip size; by default a pip = 10 points (MT5 standard)."""
    return point_size_for_digits(digits) * 10 ** pip_digits


def round_to_tick(price: float, tick_size: float) -> float:
    """Round a price to the nearest valid tick."""
    if tick_size <= 0:
        return price
    return round(price / tick_size) * tick_size


def price_is_in_range(price: float, lo: float, hi: float) -> bool:
    return lo <= price <= hi


def midpoint(a: float, b: float) -> float:
    return (a + b) / 2.0


def np_float(v: float) -> float:
    """Convert numpy scalar to native float for JSON-safe serialization."""
    return float(v)


__all__ = [
    "Candle",
    "Tick",
    "Order",
    "Position",
    "PartialExit",
    "TradeRecord",
    "PriceLevel",
    "point_size_for_digits",
    "pip_size_for_digits",
    "round_to_tick",
    "price_is_in_range",
    "midpoint",
    "np_float",
]
