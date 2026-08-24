"""Confirmation candle patterns (LTF entry trigger).

Patterns are evaluated on the just-closed bar (never a running candle).
Each detector returns a Confirmation carrying:
  - the pattern type,
  - the entry reference (close of the confirmation bar),
  - ``sl_reference``: the pattern's opposite extreme wick used for stop-loss
    placement (Section 9: never on the raw wick; the strategy adds a
    spread + volatility buffer and always uses the FURTHEST-BACK extreme
    when several confirmation candles sit in the same cluster).

Rules implemented here (Confluence Framework v1.0, Section 7 Step 6):
  - Engulfing: body fully covers prior body AND closes near its extreme in
    the trade direction (minimal wick on the trend side).
  - Hammer: small body, maximum wick opposite the trade direction.
  - Hammer+Engulfing combo.
  - Mother/Baby: counts ONLY once a candle's BODY closes beyond the mother
    candle's high/low. Engulfing a small 'baby' candle inside a bigger range
    does NOT count.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from trading_bot.core.enums import Side
from trading_bot.core.models import Candle


@dataclass
class Confirmation:
    type: str  # 'engulfing' | 'hammer' | 'hammer_engulfing' | 'mother_baby'
    side: Side
    bar_index: int
    price_ref: float  # entry reference (close of confirmation bar)
    strength: float = 1.0
    sl_reference: float = 0.0  # opposite extreme of the pattern (SL anchor)
    extra: dict = None  # type: ignore[assignment]


def _body_ratio(c: Candle) -> float:
    return abs(c.body) / c.range if c.range > 0 else 0.0


def is_engulfing(prev: Candle, cur: Candle) -> bool:
    """Current bar's body fully engulfs the previous bar's body."""
    if prev.range <= 0:
        return False
    prev_body_top = max(prev.open, prev.close)
    prev_body_bot = min(prev.open, prev.close)
    cur_body_top = max(cur.open, cur.close)
    cur_body_bot = min(cur.open, cur.close)
    return cur_body_top > prev_body_top and cur_body_bot < prev_body_bot


def is_bullish_engulfing(
    prev: Candle, cur: Candle, max_trend_wick_ratio: float = 0.25
) -> bool:
    """Bullish engulfing: body engulfs prev body, bullish close, and minimal
    wick on the trend side (lower wick small => closing near the extreme)."""
    if not (is_engulfing(prev, cur) and cur.is_bullish and prev.is_bearish):
        return False
    if cur.range <= 0:
        return False
    return cur.lower_wick <= max_trend_wick_ratio * cur.range


def is_bearish_engulfing(
    prev: Candle, cur: Candle, max_trend_wick_ratio: float = 0.25
) -> bool:
    """Bearish engulfing: body engulfs prev body, bearish close, minimal wick
    on the trend side (upper wick small => closing near the extreme)."""
    if not (is_engulfing(prev, cur) and cur.is_bearish and prev.is_bullish):
        return False
    if cur.range <= 0:
        return False
    return cur.upper_wick <= max_trend_wick_ratio * cur.range


def is_hammer(c: Candle, min_wick_ratio: float = 1.5, body_max_ratio: float = 0.4) -> bool:
    """Bullish hammer: long lower wick (opposite the buy direction), small body,
    small upper wick — a rejection candle."""
    if c.range <= 0:
        return False
    lower = c.lower_wick
    upper = c.upper_wick
    return (
        lower >= min_wick_ratio * max(c.body, 0.0001)
        and upper <= 0.4 * lower
        and _body_ratio(c) <= body_max_ratio
    )


def is_bearish_shooting_star(c: Candle, min_wick_ratio: float = 1.5) -> bool:
    """Bearish 'hammer' equivalent: long upper wick opposite the sell
    direction, small body."""
    if c.range <= 0:
        return False
    upper = c.upper_wick
    lower = c.lower_wick
    return upper >= min_wick_ratio * max(c.body, 0.0001) and lower <= 0.4 * upper


def find_mother_break(
    bars: Sequence[Candle],
    bar_index: int,
    side: Side,
    min_body_ratio: float = 0.6,
    max_mother_lookback: int = 4,
) -> Optional[Candle]:
    """Rulebook mother/baby confirmation.

    A candle counts ONLY once its BODY closes beyond the mother candle's
    high (buy) / low (sell), where:
      - the 'mother' is a strong-range candle,
      - every candle between the mother and the break candle is a 'baby'
        fully contained inside the mother's range.
    Engulfing a small baby INSIDE the bigger range does NOT count.

    Returns the mother Candle when a valid break exists at ``bar_index``,
    else None.
    """
    i = bar_index
    if i < 1 or i >= len(bars):
        return None
    cur = bars[i]
    for m in range(i - 1, max(0, i - max_mother_lookback) - 1, -1):
        mother = bars[m]
        if mother.range <= 0:
            return None
        # every intervening bar must be a baby inside the mother's range
        if any(
            bars[j].high > mother.high or bars[j].low < mother.low
            for j in range(m + 1, i)
        ):
            return None
        if _body_ratio(mother) < min_body_ratio:
            # contained but weak body; keep scanning further back for the
            # true start of the containment chain
            continue
        if side is Side.BUY:
            if cur.is_bullish and cur.close > mother.high:
                return mother
        else:
            if cur.is_bearish and cur.close < mother.low:
                return mother
        return None
    return None


def detect_confirmation(
    bars: Sequence[Candle],
    side: Side,
    bar_index: Optional[int] = None,
    min_wick_ratio: float = 1.5,
    use_hammer: bool = True,
    use_engulfing: bool = True,
    use_hammer_engulfing: bool = True,
    use_mother_baby: bool = True,
) -> Optional[Confirmation]:
    """Detect a confirmation candle on the final (or given) CLOSED bar.

    Returns a Confirmation whose ``sl_reference`` is the FURTHEST-BACK extreme
    of the pattern cluster (Section 9 gap rule): for buys the lowest low of
    all candles involved in the pattern; for sells the highest high.
    """
    n = len(bars)
    if bar_index is None:
        bar_index = n - 1
    if bar_index <= 0 or bar_index >= n:
        return None
    cur = bars[bar_index]
    prev = bars[bar_index - 1]

    def _mk(type_: str, extremes: Sequence[Candle]) -> Confirmation:
        if side is Side.BUY:
            ref = min(b.low for b in extremes)
        else:
            ref = max(b.high for b in extremes)
        return Confirmation(type_, side, bar_index, cur.close, sl_reference=ref)

    if side is Side.BUY:
        engulf_ok = use_engulfing and is_bullish_engulfing(prev, cur)
        hammer_ok = use_hammer and is_hammer(cur, min_wick_ratio=min_wick_ratio)
        if engulf_ok and hammer_ok and use_hammer_engulfing:
            return _mk("hammer_engulfing", [prev, cur])
        if engulf_ok:
            return _mk("engulfing", [prev, cur])
        if hammer_ok:
            return _mk("hammer", [cur])
        if use_mother_baby:
            mother = find_mother_break(bars, bar_index, Side.BUY)
            if mother is not None:
                conf = _mk("mother_baby", [mother])
                conf.extra = {"mother_high": mother.high, "mother_low": mother.low}
                return conf
    else:
        engulf_ok = use_engulfing and is_bearish_engulfing(prev, cur)
        star_ok = is_bearish_shooting_star(cur, min_wick_ratio=min_wick_ratio)
        if engulf_ok and star_ok and use_hammer_engulfing:
            return _mk("hammer_engulfing", [prev, cur])
        if engulf_ok:
            return _mk("engulfing", [prev, cur])
        if star_ok and use_hammer:
            return _mk("shooting_star", [cur])
        if use_mother_baby:
            mother = find_mother_break(bars, bar_index, Side.SELL)
            if mother is not None:
                conf = _mk("mother_baby", [mother])
                conf.extra = {"mother_high": mother.high, "mother_low": mother.low}
                return conf
    return None


__all__ = [
    "Confirmation",
    "is_engulfing",
    "is_bullish_engulfing",
    "is_bearish_engulfing",
    "is_hammer",
    "is_bearish_shooting_star",
    "find_mother_break",
    "detect_confirmation",
]
