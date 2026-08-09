"""Deterministic bar aggregation from ticks or lower-timeframe bars.

Guarantees:
- Bar timestamps are aligned to UTC bar boundaries for the target timeframe.
- Aggregation uses only information within that bar (no lookahead).
- Volume and spread aggregation are deterministic.
"""
from __future__ import annotations

from collections.abc import Sequence

from trading_bot.core.enums import Timeframe
from trading_bot.core.models import Candle, Tick
from trading_bot.core.time_utils import bar_open_time, bar_open_time_minutes

def _bucket_of(ts: int, timeframe: Timeframe) -> int:
    if timeframe in (Timeframe.W1, Timeframe.MN):
        return bar_open_time(ts, timeframe)
    return bar_open_time_minutes(ts, timeframe.minutes)


def aggregate_ticks_to_candles(ticks: Sequence[Tick], timeframe: Timeframe) -> list[Candle]:
    """Aggregate a sorted tick stream into aligned candles."""
    if not ticks:
        return []

    result: list[Candle] = []
    cur_open_time = -1
    o = h = l = c = 0.0
    vol = 0.0
    spread_sum = 0.0
    spread_cnt = 0

    def flush() -> None:
        nonlocal cur_open_time, o, h, l, c, vol, spread_sum, spread_cnt
        if cur_open_time < 0:
            return
        avg_spread = spread_sum / spread_cnt if spread_cnt else 0.0
        result.append(
            Candle(
                time=cur_open_time,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=vol,
                spread=avg_spread,
            )
        )
        vol = 0.0
        spread_sum = 0.0
        spread_cnt = 0

    for t in ticks:
        bar = _bucket_of(t.time, timeframe)
        if bar != cur_open_time:
            flush()
            cur_open_time = bar
            o = h = l = c = t.mid
        c = t.mid
        h = max(h, t.mid)
        l = min(l, t.mid)
        vol += t.volume
        if t.volume is not None and t.volume > 0:
            spread_sum += t.spread
            spread_cnt += 1
    flush()
    return result


def resample_candles(
    candles: Sequence[Candle],
    target: Timeframe,
    source: Timeframe | None = None,
) -> list[Candle]:
    """Resample lower-timeframe candles into a higher timeframe.

    The input candles must already be aligned to their own timeframe bars.
    New candles are formed from contiguous target-timeframe windows.
    """
    if not candles:
        return []
    if source is not None and target.minutes <= source.minutes:
        # Aggregating to equal or lower resolution: return as-is (dedup by time)
        return list(candles)

    result: list[Candle] = []
    cur_open_time = -1
    o = h = l = c = 0.0
    vol = 0.0
    spread_sum = 0.0
    spread_cnt = 0

    def flush() -> None:
        nonlocal cur_open_time, o, h, l, c, vol, spread_sum, spread_cnt
        if cur_open_time < 0:
            return
        avg_spread = spread_sum / spread_cnt if spread_cnt else 0.0
        result.append(
            Candle(
                time=cur_open_time,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=vol,
                spread=avg_spread,
            )
        )
        vol = 0.0
        spread_sum = 0.0
        spread_cnt = 0

    for bar in candles:
        bucket = _bucket_of(bar.time, target)
        if bucket != cur_open_time:
            flush()
            cur_open_time = bucket
            o = h = l = c = bar.open
        c = bar.close
        h = max(h, bar.high)
        l = min(l, bar.low)
        vol += bar.volume
        if bar.spread is not None and bar.spread > 0:
            spread_sum += bar.spread
            spread_cnt += 1
    flush()
    return result


def build_candle_timeframe(
    ticks: Sequence[Tick],
    timeframe: Timeframe,
) -> list[Candle]:
    """One-stop helper: ticks -> candles at any timeframe."""
    return aggregate_ticks_to_candles(ticks, timeframe)
