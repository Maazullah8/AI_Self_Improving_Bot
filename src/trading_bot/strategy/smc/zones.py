"""SMC zones: Order Blocks, FVGs, Rejection Blocks, Breakers, Liquidity Pools.

Zones are geometric (price) regions with a direction bias and a "used"
flag. Detection is deterministic and only ever uses past/current bars.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from trading_bot.core.models import Candle


@dataclass
class Zone:
    kind: str  # 'order_block' | 'fvg' | 'rejection_block' | 'breaker' | 'liquidity'
    top: float
    bottom: float
    direction: str  # 'bullish' | 'bearish'
    created_index: int = -1
    created_time: int = 0
    strength: float = 1.0  # quality score
    filled: bool = False
    mitigation_index: int = -1
    mit_time: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def mid(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def depth(self) -> float:
        return self.top - self.bottom

    def contains(self, price: float, tolerance: float = 0.0) -> bool:
        return (self.bottom - tolerance) <= price <= (self.top + tolerance)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "top": self.top,
            "bottom": self.bottom,
            "direction": self.direction,
            "created_index": self.created_index,
            "created_time": self.created_time,
            "strength": self.strength,
            "filled": self.filled,
            "extra": self.extra,
        }


def _body_high(c: Candle) -> float:
    return max(c.open, c.close)


def _body_low(c: Candle) -> float:
    return min(c.open, c.close)


def find_order_blocks(
    bars: Sequence[Candle],
    lookback: int = 200,
    min_body_ratio: float = 0.5,
    max_age_bars: Optional[int] = None,
) -> list[Zone]:
    """Classic OB detection: last opposing (or same-direction) candle before a
    strong move. We use the last down-close candle before an up-move for a
    bullish OB, and vice versa."""
    out: list[Zone] = []
    n = len(bars)
    start = max(0, n - lookback)
    for i in range(start, n - 1):
        move = bars[i + 1].close - bars[i].close
        body_ratio_i = abs(bars[i].body) / bars[i].range if bars[i].range > 0 else 0
        # up move after a bearish candle => bullish OB
        if move > 0 and bars[i].is_bearish and body_ratio_i >= min_body_ratio:
            out.append(
                Zone(
                    kind="order_block",
                    top=_body_high(bars[i]),
                    bottom=_body_low(bars[i]),
                    direction="bullish",
                    created_index=i,
                    created_time=bars[i].time,
                    strength=abs(move) / bars[i].range if bars[i].range > 0 else 1.0,
                )
            )
        # down move after a bullish candle => bearish OB
        elif move < 0 and bars[i].is_bullish and body_ratio_i >= min_body_ratio:
            out.append(
                Zone(
                    kind="order_block",
                    top=_body_high(bars[i]),
                    bottom=_body_low(bars[i]),
                    direction="bearish",
                    created_index=i,
                    created_time=bars[i].time,
                    strength=abs(move) / bars[i].range if bars[i].range > 0 else 1.0,
                )
            )
    if max_age_bars is not None and out:
        out = [z for z in out if n - 1 - z.created_index <= max_age_bars]
    return out


def find_fvgs(
    bars: Sequence[Candle],
    lookback: int = 200,
    max_age_bars: Optional[int] = None,
) -> list[Zone]:
    """Fair value gaps: the space between candle i's wick extreme and candle
    i+2's body extreme when candle i+2's body does not overlap candle i."""
    out: list[Zone] = []
    n = len(bars)
    start = max(0, n - lookback)
    for i in range(start, n - 2):
        a, b, c = bars[i], bars[i + 1], bars[i + 2]
        if c.body > 0:  # bullish candle
            gap_low = a.high
            gap_high = c.low
            if gap_high > gap_low:
                out.append(
                    Zone(
                        kind="fvg",
                        top=gap_high,
                        bottom=gap_low,
                        direction="bullish",
                        created_index=i,
                        created_time=a.time,
                        strength=c.body / c.range if c.range > 0 else 1.0,
                    )
                )
        elif c.body < 0:  # bearish candle
            gap_low = c.high
            gap_high = a.low
            if gap_high > gap_low:
                out.append(
                    Zone(
                        kind="fvg",
                        top=gap_high,
                        bottom=gap_low,
                        direction="bearish",
                        created_index=i,
                        created_time=a.time,
                        strength=abs(c.body) / c.range if c.range > 0 else 1.0,
                    )
                )
    if max_age_bars is not None and out:
        out = [z for z in out if n - 1 - z.created_index <= max_age_bars]
    return out


def find_rejection_blocks(
    bars: Sequence[Candle],
    lookback: int = 200,
    min_wick_ratio: float = 1.5,
) -> list[Zone]:
    """Rejection blocks: a candle with a large wick against the move direction,
    signaling a reversal area. A long lower wick => bullish zone (support)."""
    out: list[Zone] = []
    n = len(bars)
    start = max(0, n - lookback)
    for i in range(start, n):
        c = bars[i]
        if c.range <= 0:
            continue
        lower_ratio = c.lower_wick / c.range
        upper_ratio = c.upper_wick / c.range
        if lower_ratio >= min_wick_ratio / (1 + min_wick_ratio) and c.close > c.midpoint:
            out.append(
                Zone(
                    kind="rejection_block",
                    top=_body_high(c),
                    bottom=_body_low(c),
                    direction="bullish",
                    created_index=i,
                    created_time=c.time,
                    strength=lower_ratio,
                )
            )
        elif upper_ratio >= min_wick_ratio / (1 + min_wick_ratio) and c.close < c.midpoint:
            out.append(
                Zone(
                    kind="rejection_block",
                    top=_body_high(c),
                    bottom=_body_low(c),
                    direction="bearish",
                    created_index=i,
                    created_time=c.time,
                    strength=upper_ratio,
                )
            )
    return out


def find_liquidity_pools(
    bars: Sequence[Candle],
    lookback: int = 300,
    min_touches: int = 2,
    window_bars: int = 50,
) -> list[Zone]:
    """Liquidity pools: levels where price has touched multiple times
    (equal highs/lows = resting stop liquidity)."""
    out: list[Zone] = []
    n = len(bars)
    start = max(0, n - lookback)
    highs: dict[float, int] = {}
    lows: dict[float, int] = {}
    last_high_ts: dict[float, int] = {}
    last_low_ts: dict[float, int] = {}
    for i in range(start, n):
        h = round(bars[i].high, 6)
        l = round(bars[i].low, 6)
        highs[h] = highs.get(h, 0) + 1
        last_high_ts[h] = i
        lows[l] = lows.get(l, 0) + 1
        last_low_ts[l] = i
    tol = (bars[-1].range if bars[-1].range > 0 else 0.0001) * 0.5
    for price, cnt in highs.items():
        if cnt >= min_touches and n - 1 - last_high_ts.get(price, n) <= window_bars:
            out.append(
                Zone(
                    kind="liquidity",
                    top=price + tol,
                    bottom=price - tol,
                    direction="bearish",  # liquidity above acts as sell target
                    created_index=last_high_ts.get(price, 0),
                    created_time=0,
                    strength=float(cnt),
                    extra={"side": "above", "touches": cnt},
                )
            )
    for price, cnt in lows.items():
        if cnt >= min_touches and n - 1 - last_low_ts.get(price, n) <= window_bars:
            out.append(
                Zone(
                    kind="liquidity",
                    top=price + tol,
                    bottom=price - tol,
                    direction="bullish",  # liquidity below acts as buy target
                    created_index=last_low_ts.get(price, 0),
                    created_time=0,
                    strength=float(cnt),
                    extra={"side": "below", "touches": cnt},
                )
            )
    return out


def find_breakers(
    bars: Sequence[Candle],
    lookback: int = 300,
    ob_min_body_ratio: float = 0.5,
) -> list[Zone]:
    """Breakers: an order block that failed (got swept) and flipped polarity.
    Simplified: a swing low that was broken to the downside then reclaimed."""
    out: list[Zone] = []
    n = len(bars)
    start = max(1, n - lookback)
    for i in range(start, n - 1):
        # swing low at i, broken at i+1, reclaimed (close back above) within a few bars
        swing_low = bars[i].low
        if bars[i + 1].close < swing_low:
            for j in range(i + 2, min(n, i + 6)):
                if bars[j].close > swing_low:
                    out.append(
                        Zone(
                            kind="breaker",
                            top=max(bars[i].open, bars[i].close),
                            bottom=swing_low,
                            direction="bullish",
                            created_index=i,
                            created_time=bars[i].time,
                            strength=1.0,
                        )
                    )
                    break
    return out


def find_all_zones(
    bars: Sequence[Candle],
    lookback: int = 200,
    include_fvg: bool = True,
    include_ob: bool = True,
    include_rejection: bool = True,
    include_breaker: bool = True,
    include_liquidity: bool = True,
    min_body_ratio: float = 0.5,
) -> list[Zone]:
    out: list[Zone] = []
    if include_ob:
        out.extend(find_order_blocks(bars, lookback=lookback, min_body_ratio=min_body_ratio))
    if include_fvg:
        out.extend(find_fvgs(bars, lookback=lookback))
    if include_rejection:
        out.extend(find_rejection_blocks(bars, lookback=lookback))
    if include_breaker:
        out.extend(find_breakers(bars, lookback=lookback))
    if include_liquidity:
        out.extend(find_liquidity_pools(bars, lookback=lookback))
    return out
