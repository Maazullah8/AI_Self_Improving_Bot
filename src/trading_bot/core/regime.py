"""Market-regime classification (deterministic, zero lookahead).

Classifies the most recent closed bars into one of the ``core.enums.Regime``
states using only information available at classification time:

    TRENDING_UP / TRENDING_DOWN  price drifting directionally vs volatility
    RANGING                      no directional drift
    HIGH_VOLATILITY              recent ATR far above its slower baseline
    LOW_VOLATILITY               recent ATR far below its slower baseline

Pure functions over closed candles — used by the replay engine to tag every
trade with the regime active at entry so performance can later be analysed
per regime. Volatility is checked FIRST because a regime label is meaningless
when the market is in shock regardless of direction.
"""
from __future__ import annotations

from typing import Sequence

from trading_bot.core.enums import Regime
from trading_bot.core.models import Candle


def _atr(bars: Sequence[Candle], period: int) -> float:
    """Simple mean true range over the last ``period`` bars."""
    if len(bars) < 2:
        return 0.0
    period = min(period, len(bars) - 1)
    trs = []
    for i in range(len(bars) - period, len(bars)):
        cur = bars[i]
        prev = bars[i - 1]
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return sum(trs) / len(trs) if trs else 0.0


def _drift_per_bar(bars: Sequence[Candle]) -> float:
    """Mean close-to-close change over the window (signed drift per bar)."""
    closes = [b.close for b in bars]
    if len(closes) < 2:
        return 0.0
    return (closes[-1] - closes[0]) / (len(closes) - 1)


def detect_regime(
    bars: Sequence[Candle],
    lookback: int = 50,
    fast_atr: int = 14,
    slow_atr: int = 50,
    high_vol_ratio: float = 1.8,
    low_vol_ratio: float = 0.55,
    trend_threshold: float = 0.10,
) -> str:
    """Classify the regime of the last ``lookback`` closed bars.

    Returns the *value* of :class:`trading_bot.core.enums.Regime`
    ('trending_up', 'trending_down', 'ranging', 'high_volatility',
    'low_volatility') so it can be stored directly on trade records.

    All thresholds are configuration, not hard-coded opinions:
      - ``high/low_vol_ratio``: recent ATR(fast) vs baseline ATR(slow).
      - ``trend_threshold``: |drift per bar| as a fraction of recent ATR
        required to call a trend.
    """
    if not bars:
        return Regime.RANGING.value
    window = bars[-lookback:] if len(bars) > lookback else bars
    if len(window) < 10:
        # not enough history for a meaningful label
        return Regime.RANGING.value

    atr_fast = _atr(window, fast_atr)
    atr_slow = _atr(window, slow_atr)
    if atr_fast <= 0 or atr_slow <= 0:
        return Regime.RANGING.value

    vol_ratio = atr_fast / atr_slow
    if vol_ratio >= high_vol_ratio:
        return Regime.HIGH_VOLATILITY.value
    if vol_ratio <= low_vol_ratio:
        return Regime.LOW_VOLATILITY.value

    drift = _drift_per_bar(window)
    norm = drift / atr_fast  # signed drift in "ATRs per bar"
    if norm >= trend_threshold:
        return Regime.TRENDING_UP.value
    if norm <= -trend_threshold:
        return Regime.TRENDING_DOWN.value
    return Regime.RANGING.value


__all__ = ["detect_regime"]