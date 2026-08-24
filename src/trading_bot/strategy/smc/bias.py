"""
HTF bias: CRT (Change in the State of Delivery / Premium-Discount) + structure.
Bias sources combined into a directional vote:
- Market structure (bullish/bearish from StructureDetector)
- Premium/discount: price below the 50% range midpoint => bullish bias zone
- Recent BOS/CHoCH momentum
- CRT: the 'state of delivery' flips when price sweeps a liquidity level and 
  reclaims the midpoint (simplified ICT 'Judas swing').
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
    # --- CRT range (Section 7 Step 1): last completed HTF candle's range
    crt_high: float = 0.0
    crt_low: float = 0.0
    crt_time: int = 0
    inside_bars: int = 0  # more inside bars => higher-quality range
    swept_side: Optional[str] = None  # 'high' | 'low' | None (purged side)
    dol: Optional[str] = None  # draw on liquidity: opposite end ('high'|'low')

    @property
    def crt_valid(self) -> bool:
        return self.crt_high > self.crt_low

    def to_dict(self) -> dict:
        return {
            "side": self.side.value if self.side else None,
            "source": self.source,
            "structure": self.structure,
            "premium_discount": self.premium_discount,
            "crt_triggered": self.crt_triggered,
            "votes": self.votes,
            "crt_high": self.crt_high,
            "crt_low": self.crt_low,
            "inside_bars": self.inside_bars,
            "swept_side": self.swept_side,
            "dol": self.dol,
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
    if n == 0:
        return None
    start = max(0, n - lookback)
    window = bars[start:]
    highs = [b.high for b in window]
    lows = [b.low for b in window]
    
    max_high = max(highs)
    min_low = min(lows)
    
    return RangeBounds(
        high=max_high,
        low=min_low,
        high_index=highs.index(max_high) + start,
        low_index=lows.index(min_low) + start,
    )

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

    @staticmethod
    def _crt_range(
        bars: Sequence[Candle], completed_only: bool = True
    ) -> tuple[Optional[Candle], int, Optional[str]]:
        """Section 7 Step 1/2: mark the HTF CRT range and detect purges.

        Returns (crt_candle, inside_bars, swept_side).
          - ``crt_candle`` is the last COMPLETED HTF candle (``bars[-2]`` when
            ``completed_only`` and a newer bar exists) — never the running one.
          - ``inside_bars`` counts the candles immediately PRECEDING the CRT
            candle that sit fully inside its range (more inside bars =
            higher-quality range / accumulated interest before expansion).
          - ``swept_side`` is 'high'/'low' when one side of the range has been
            purged by a later bar (the latest purge wins if both were hit).
        """
        if not bars:
            return None, 0, None
        if completed_only and len(bars) >= 2:
            crt_idx = len(bars) - 2
        else:
            crt_idx = len(bars) - 1
        crt = bars[crt_idx]
        # accumulation before expansion: contiguous prior candles inside the range
        inside = 0
        j = crt_idx - 1
        while j >= 0 and bars[j].high <= crt.high and bars[j].low >= crt.low:
            inside += 1
            j -= 1
        swept = None
        for b in bars[crt_idx + 1 :]:
            if b.high > crt.high:
                swept = "high"
            if b.low < crt.low:
                swept = "low"
        return crt, inside, swept

    def compute(
        self,
        bars: Sequence[Candle],
        structure: Optional[StructureState] = None,
        completed_only: bool = False,
    ) -> BiasResult:
        n = len(bars)
        if n == 0:
            return BiasResult(side=None, source="no_data")

        price = bars[-1].close
        votes = {}

        # 0. CRT range (Section 7 Step 1) + sweep -> Draw on Liquidity (Step 2)
        crt_candle, inside_bars, swept_side = self._crt_range(bars, completed_only)
        dol: Optional[str] = None
        if swept_side == "high":
            dol = "low"  # buy-side purged -> draw toward opposite end (CRT low)
        elif swept_side == "low":
            dol = "high"  # sell-side purged -> draw toward CRT high
        
        # 1. Market Structure / Trend Vote (Section 7 Step 2: HH/HL = bullish,
        # LH/LL = bearish). Uses the structure detector when provided, else a
        # deterministic half-window high/low comparison.
        struct_side = None
        if structure is not None and structure.structure in ("bullish", "bearish"):
            struct_side = Side.BUY if structure.structure == "bullish" else Side.SELL
            votes["trend"] = 2 if struct_side is Side.BUY else -2
        else:
            half = max(2, n // 2)
            older, newer = bars[: n - half], bars[n - half :]
            if older and newer:
                oh = max(b.high for b in older)
                ol = min(b.low for b in older)
                nh = max(b.high for b in newer)
                nl = min(b.low for b in newer)
                if nh > oh and nl > ol:
                    votes["trend"] = 2
                elif nh < oh and nl < ol:
                    votes["trend"] = -2

        # 2. Premium / Discount Vote (Corrected Logic)
        pd_label = "equilibrium"
        rb = last_swing_range(bars, self.lookback)
        if rb is not None and rb.high > rb.low:
            mid = rb.mid
            if price < mid:
                # Below 50% midpoint = Discount Zone = Bullish Bias
                votes["premium_discount"] = 1
                pd_label = "discount"
            elif price > mid:
                # Above 50% midpoint = Premium Zone = Bearish Bias
                votes["premium_discount"] = -1
                pd_label = "premium"

        # 3. Momentum from Recent MSS / CHoCH
        crt_triggered = False
        if structure is not None and structure.last_mss is not None:
            kind = structure.last_mss.get("kind")
            # Breaking old high = Bullish Shift, Breaking old low = Bearish Shift
            if kind == "high":
                votes["momentum"] = 1
                crt_triggered = True
            elif kind == "low":
                votes["momentum"] = -1
                crt_triggered = True

        # 4. Local Swing Position Vote
        if rb is not None and rb.high > rb.low:
            recent_len = min(n, 10)
            recent = bars[-recent_len:]
            rhi = max(b.high for b in recent)
            rlo = min(b.low for b in recent)
            if rhi > rlo:
                pos = (price - rlo) / (rhi - rlo)
                if pos > 0.7:
                    votes["swing_position"] = 1
                elif pos < 0.3:
                    votes["swing_position"] = -1

        # Tally Voting System
        score = sum(votes.values())
        side = None
        if score > 0:
            side = Side.BUY
        elif score < 0:
            side = Side.SELL

        # Structure Constraint Guard
        if self.require_structure and struct_side is None:
            side = None

        # Section 7 Step 2 override: if one side of the HTF CRT range has been
        # purged (swept), bias points toward the OPPOSITE end of the range —
        # that end IS the Draw on Liquidity.
        if dol == "high":
            side, source_override = Side.BUY, "crt_dol"
        elif dol == "low":
            side, source_override = Side.SELL, "crt_dol"
        else:
            source_override = None

        # Resolve Primary Bias Source Safely
        source = "equilibrium"
        if side is not None and source_override is None:
            target_vote = 1 if side is Side.BUY else -1
            if votes.get("momentum") == target_vote:
                source = "crt_momentum"
            elif votes.get("trend", 0) * target_vote > 0:
                source = "trend_structure"
            elif votes.get("premium_discount") == target_vote:
                source = "premium_discount"
            else:
                source = "mixed"
        elif source_override is not None:
            source = source_override

        return BiasResult(
            side=side,
            source=source,
            structure=structure.structure if structure else "neutral",
            premium_discount=pd_label,
            crt_triggered=crt_triggered,
            votes=votes,
            crt_high=crt_candle.high if crt_candle else 0.0,
            crt_low=crt_candle.low if crt_candle else 0.0,
            crt_time=crt_candle.time if crt_candle else 0,
            inside_bars=inside_bars,
            swept_side=swept_side,
            dol=dol,
        )
