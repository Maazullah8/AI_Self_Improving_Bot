"""Confirmation candle patterns (LTF entry trigger).

Patterns are evaluated on the just-closed bar. Each detector returns a bool
or a dict with the pattern type + a suggested entry reference price.
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
    price_ref: float  # entry reference (usually close of confirmation bar)
    strength: float = 1.0
    extra: dict = None  # type: ignore[assignment]


def _body_ratio(c: Candle) -> float:
    return abs(c.body) / c.range if c.range > 0 else 0.0


def is_engulfing(prev: Candle, cur: Candle) -> bool:
    """Current bar's body fully engulfs the previous bar's body, direction up."""
    if prev.range <= 0:
        return False
    prev_body_top = max(prev.open, prev.close)
    prev_body_bot = min(prev.open, prev.close)
    cur_body_top = max(cur.open, cur.close)
    cur_body_bot = min(cur.open, cur.close)
    return cur_body_top > prev_body_top and cur_body_bot < prev_body_bot


def is_bullish_engulfing(prev: Candle, cur: Candle) -> bool:
    return is_engulfing(prev, cur) and cur.is_bullish and prev.is_bearish


def is_bearish_engulfing(prev: Candle, cur: Candle) -> bool:
    return is_engulfing(prev, cur) and cur.is_bearish and prev.is_bullish


def is_hammer(c: Candle, min_wick_ratio: float = 1.5, body_max_ratio: float = 0.4) -> bool:
    """Bullish hammer: long lower wick, small body, small upper wick."""
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
    if c.range <= 0:
        return False
    upper = c.upper_wick
    lower = c.lower_wick
    return upper >= min_wick_ratio * max(c.body, 0.0001) and lower <= 0.4 * upper


def is_mother_baby(
    mother_prev: Candle,
    mother: Candle,
    baby: Candle,
    body_ratio_threshold: float = 0.6,
    baby_max_ratio: float = 0.4,
) -> bool:
    """Mother/baby (Natalia): a large range candle (mother) followed by a small
    candle (baby) that stays within the mother's body, then the move resumes.
    We detect the baby candle as the confirmation (after an inside bar)."""
    # mother must be a strong candle
    if _body_ratio(mother) < body_ratio_threshold:
        return False
    # baby is inside mother's body
    baby_inside = (
        baby.high <= max(mother.open, mother.close)
        and baby.low >= min(mother.open, mother.close)
        and _body_ratio(baby) <= baby_max_ratio
    )
    return baby_inside


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
    """Detect a confirmation candle on the final (or given) closed bar.

    Returns a Confirmation with the pattern name matching the side.
    """
    n = len(bars)
    if bar_index is None:
        bar_index = n - 1
    if bar_index <= 0 or bar_index >= n:
        return None
    cur = bars[bar_index]
    prev = bars[bar_index - 1]

    if side is Side.BUY:
        if use_engulfing and is_bullish_engulfing(prev, cur):
            return Confirmation("engulfing", side, bar_index, cur.close)
        if use_hammer and is_hammer(cur, min_wick_ratio=min_wick_ratio):
            return Confirmation("hammer", side, bar_index, cur.close)
        if use_hammer_engulfing and is_bullish_engulfing(prev, cur) and is_hammer(cur, min_wick_ratio=min_wick_ratio):
            return Confirmation("hammer_engulfing", side, bar_index, cur.close)
        if use_mother_baby and bar_index >= 2:
            if is_mother_baby(bars[bar_index - 2], prev, cur):
                # for buy, baby should be bullish or neutral close
                if cur.close >= cur.open or _body_ratio(cur) <= 0.3:
                    return Confirmation("mother_baby", side, bar_index, cur.close)
    else:
        if use_engulfing and is_bearish_engulfing(prev, cur):
            return Confirmation("engulfing", side, bar_index, cur.close)
        if use_shooting_star(cur, min_wick_ratio=min_wick_ratio):
            return Confirmation("shooting_star", side, bar_index, cur.close)
        if use_hammer_engulfing and is_bearish_engulfing(prev, cur) and use_shooting_star(cur, min_wick_ratio=min_wick_ratio):
            return Confirmation("hammer_engulfing", side, bar_index, cur.close)
        if use_mother_baby and bar_index >= 2:
            if is_mother_baby(bars[bar_index - 2], prev, cur):
                if cur.close <= cur.open or _body_ratio(cur) <= 0.3:
                    return Confirmation("mother_baby", side, bar_index, cur.close)
    return None


def use_shooting_star(c: Candle, min_wick_ratio: float = 1.5) -> bool:
    return is_bearish_shooting_star(c, min_wick_ratio=min_wick_ratio)


__all__ = [
    "Confirmation",
    "is_engulfing",
    "is_bullish_engulfing",
    "is_bearish_engulfing",
    "is_hammer",
    "is_bearish_shooting_star",
    "is_mother_baby",
    "detect_confirmation",
]
