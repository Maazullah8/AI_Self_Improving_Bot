"""Core domain enums and constants for the trading bot.

Everything in this package is dependency-free (pure Python) so it can be
imported from any layer without circular imports.
"""
from __future__ import annotations

from enum import Enum


class Timeframe(str, Enum):
    """Supported bar timeframes."""

    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"
    MN = "1mo"

    @property
    def minutes(self) -> int:
        return {
            Timeframe.M1: 1,
            Timeframe.M3: 3,
            Timeframe.M5: 5,
            Timeframe.M15: 15,
            Timeframe.M30: 30,
            Timeframe.H1: 60,
            Timeframe.H4: 240,
            Timeframe.D1: 1440,
            Timeframe.W1: 10080,
            Timeframe.MN: 43200,
        }[self]

    @staticmethod
    def from_minutes(minutes: int) -> "Timeframe":
        for tf in Timeframe:
            if tf.minutes == minutes:
                return tf
        raise ValueError(f"Unsupported timeframe minutes: {minutes}")


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    FLATTENED = "flattened"


class ExitReason(str, Enum):
    TP = "tp"
    SL = "sl"
    BE = "break_even"
    PARTIAL_TP = "partial_tp"
    TRAILING_STOP = "trailing_stop"
    SESSION_END = "session_end"
    RISK_DAILY_LIMIT = "risk_daily_limit"
    RISK_MAX_DRAWDOWN = "risk_max_drawdown"
    RISK_MANUAL = "risk_manual"
    EMERGENCY_SHUTDOWN = "emergency_shutdown"
    DATA_STALENESS = "data_staleness"
    STRATEGY_EXIT = "strategy_exit"
    FLATTEN = "flatten"
    UNKNOWN = "unknown"


class Regime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    UNKNOWN = "unknown"


class StrategyStatus(str, Enum):
    HYPOTHESIS = "hypothesis"
    CANDIDATE = "candidate"
    TRAINING = "training"
    VALIDATION = "validation"
    OOS = "out_of_sample"
    WALK_FORWARD = "walk_forward"
    MONTE_CARLO = "monte_carlo"
    DEMO = "demo"
    REJECTED = "rejected"
    PROMOTED = "promoted"
    LIVE = "live"
    DISABLED = "disabled"
    ROLLED_BACK = "rolled_back"


class ConfluenceLevel(str, Enum):
    """Encoded confluence strength used across the whole pipeline."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @staticmethod
    def from_score(score: int) -> "ConfluenceLevel":
        if score <= 0:
            return ConfluenceLevel.NONE
        if score == 1:
            return ConfluenceLevel.LOW
        if score == 2:
            return ConfluenceLevel.MEDIUM
        return ConfluenceLevel.HIGH


class MarketSession(str, Enum):
    ASIA = "asia"
    LONDON = "london"
    NEW_YORK = "new_york"
    OVERLAP_LONDON_NY = "london_ny_overlap"
    OFF = "off"


class DataSource(str, Enum):
    MT5 = "mt5"
    CSV = "csv"
    PARQUET = "parquet"
    BI5 = "bi5"
    DUCKDB = "duckdb"
    MEMORY = "memory"
