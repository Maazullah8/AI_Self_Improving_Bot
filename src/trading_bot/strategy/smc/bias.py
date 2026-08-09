"""HTF bias: CRT (Change in the State of Delivery / Premium-Discount) + structure.

Bias sources combined into a directional vote:
  - Market structure (bullish/bearish from StructureDetector)
  - Premium/discount: price below the 50% range midpoint => bullish bias zone
  - Recent BOS/CHoCH momentum
  - CRT: the 'state of delivery' flips when price sweeps a liquidity level
    and reclaims the midpoint (simplified ICT 'Judas swing').

The result is a bias: Side.BUY, Side.SELL, or None (no clean bias).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from trading_bot.core.enums import Side
from trading_bot.core.models import Candle
from trading_bot.strategy.smc.structure import StructureState


@dataclass
class BiasResult:
    side: Optional[Side]
    source: str  # primary driver
    structure: str = "neutral"
    premium_discount: str = "equilibrium"
    crt_triggered: bool = False
    votes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "side": self.side.value if self.side else None,
            "source": self.source,
            "structure": self.structure,
            "premium_discount": self.premium_discount,
            "crt_triggered": self.crt_triggered,
            "votes": self.votes,
        }


@dataclass
class RangeBounds:
    high: float = 0.0
    low: float = 0.0
    high_index: int = 0
    low_index: int = 0

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2.0


def last_swing_range(bars: Sequence[Candle], lookback: int = 100) -> Optional[RangeBounds]:
    """The last clean swing-high/swing-low range (both defined)."""
    n = len(bars)
    start = max(0, n - lookback)
    window = bars[start:]
    highs = [b.high for b in window]
    lows = [b.low for b in window]
    return RangeBounds(
        high=max(highs),
        low=min(lows),
        high_index=highs.index(max(highs)) + start,
        low_index=lows.index(min(lows)) + start,
    )


def price_in_premium(bars: Sequence[Candle], price: float, lookback: int = 100) -> Optional[bool]:
    """True if price is in premium (above 50% midpoint), False in discount,
    None if range is degenerate."""
    rb = last_swing_range(bars, lookback)
    if rb is None or rb.high <= rb.low:
        return None
    mid = rb.mid
    return price > mid


class BiasEngine:
    """Incremental HTF bias computation from structure + range geometry."""

    def __init__(
        self,
        lookback: int = 100,
        require_structure: bool = False,
        min_struct_votes: int = 1,
    ):
        self.lookback = lookback
        self.require_structure = require_structure
        self.min_struct_votes = min_struct_votes

    def compute(self, bars: Sequence[Candle], structure: Optional[StructureState] = None) -> BiasResult:
        n = len(bars)
        if n == 0:
            return BiasResult(side=None, source="no_data")
        price = bars[-1].close
        votes = {}

        struct_side = None
        if structure is not None and structure.structure in ("bullish", "bearish"):
            struct_side = Side.BUY if structure.structure == "bullish" else Side.SELL
            votes["structure"] = 1 if struct_side is Side.BUY else -1

        pd_side = None
        pd_label = "equilibrium"
        rb = last_swing_range(bars, self.lookback)
        if rb is not None and rb.high > rb.low:
            mid = rb.mid
            if price > mid:
                pd_side = Side.BUY  # already above mid -> bullish bias
                pd_label = "premium"
            elif price < mid:
                pd_side = Side.SELL
                pd_label = "discount"
            votes["premium_discount"] = 1 if pd_side is Side.BUY else -1

        # Momentum from recent BOS (if provided via structure)
        crt_triggered = False
        momentum_side = None
        if structure is not None and structure.last_mss is not None:
            kind = structure.last_mss.get("kind")
            if kind == "low":  # broke a low => bearish shift
                momentum_side = Side.SELL
            elif kind == "high":
                momentum_side = Side.BUY
            votes["momentum"] = 1 if momentum_side is Side.BUY else -1
            crt_triggered = True

        # Simple swing-low/high imbalance as an extra vote
        swing_vote = 0
        if rb is not None and rb.high > rb.low and n >= 2:
            recent = bars[-min(n, 10):]
            # if close is near the high of recent range, buy
            rhi = max(b.high for b in recent)
            rlo = min(b.low for b in recent)
            if rhi > rlo:
                pos = (price - rlo) / (rhi - rlo)
                if pos > 0.7:
                    swing_vote = 1
                    votes["swing_position"] = 1
                elif pos < 0.3:
                    swing_vote = -1
                    votes["swing_position"] = -1

        # Tally
        score = sum(votes.values())
        side = None
        if score > 0:
            side = Side.BUY
        elif score < 0:
            side = Side.SELL

        if self.require_structure and struct_side is None:
            side = None

        source = "equilibrium"
        if side is not None:
            if votes.get("momentum") == (1 if side is Side.BUY else -1):
                source = "crt_momentum"
            elif votes.get("premium_discount") == (1 if side is Side.BUY else -1):
                source = "premium_discount"
            else:
                source = "structure" if votes.get("structure") == (1 if side is Side.BUY else -1) else "mixed"

        return BiasResult(
            side=side,
            source=source,
            structure=structure.structure if structure else "neutral",
            premium_discount=pd_label,
            crt_triggered=crt_triggered,
            votes=votes,
        )
