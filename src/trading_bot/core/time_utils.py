"""Time helpers: bar alignment, market sessions, epoch conversions.

All timestamps in the codebase are integer epoch SECONDS in UTC.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading_bot.core.enums import MarketSession, Timeframe

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def utc_ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    return int(datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc).timestamp())


def ts_to_dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def bar_open_time(ts: int, timeframe: Timeframe) -> int:
    """Align a timestamp to the bar open time for a given timeframe (UTC).

    Intraday timeframes align to UTC hour/minute boundaries. Weekly bars
    align to Monday 00:00 UTC; monthly bars align to the 1st of the month.
    """
    if timeframe is Timeframe.W1:
        dt = ts_to_dt(ts)
        days_since_monday = (dt.weekday()) % 7
        aligned = dt.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=days_since_monday
        )
        return int(aligned.timestamp())
    if timeframe is Timeframe.MN:
        dt = ts_to_dt(ts)
        return int(dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
    minutes = timeframe.minutes
    return int((ts // (minutes * 60)) * (minutes * 60))


def bar_open_time_minutes(ts: int, minutes: int) -> int:
    """Generic intraday alignment by minute count (no calendar awareness)."""
    return int((ts // (minutes * 60)) * (minutes * 60))


def next_bar_open_time(ts: int, timeframe: Timeframe) -> int:
    minutes = timeframe.minutes
    return int(((ts // (minutes * 60)) + 1) * (minutes * 60))


def weekday(ts: int) -> int:
    """ISO weekday: Monday=1 .. Sunday=7."""
    return ts_to_dt(ts).isoweekday()


def hour_of_day(ts: int) -> int:
    return ts_to_dt(ts).hour


def market_session(ts: int, utc_offset_hours: int = 0) -> MarketSession:
    """Classify the current time into a trading session (UTC by default).

    Rough market hours (using UTC, default broker offset 0):
      Asia          00:00-07:00
      London        07:00-12:00
      London/NY ovlp 12:00-16:00
      New York      13:00-21:00
      Off           otherwise (weekend or dead hours)
    Sessions are mutually exclusive, prioritized as listed.
    """
    hour = (hour_of_day(ts) + utc_offset_hours) % 24
    wd = weekday(ts)
    if wd >= 6:  # weekend
        return MarketSession.OFF
    if 0 <= hour < 7:
        return MarketSession.ASIA
    if 7 <= hour < 12:
        return MarketSession.LONDON
    if 12 <= hour < 16:
        return MarketSession.OVERLAP_LONDON_NY
    if 13 <= hour < 21:
        return MarketSession.NEW_YORK
    return MarketSession.OFF


def is_weekend(ts: int) -> bool:
    return weekday(ts) >= 6


__all__ = [
    "utc_ts",
    "ts_to_dt",
    "bar_open_time",
    "bar_open_time_minutes",
    "next_bar_open_time",
    "weekday",
    "hour_of_day",
    "market_session",
    "is_weekend",
    "EPOCH",
]
