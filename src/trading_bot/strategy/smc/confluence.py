"""Confluence scoring for SMC setups.

Confluence is computed BEFORE confirmation and BEFORE entry. Each factor adds
1 point. 1 = low, 2 = medium, 3+ = high. The score is journaled so the AI
can statistically test whether confluence actually improves performance.

Factors counted:
  - Bias alignment (HTF bias side matches trade side)
  - Structure alignment (BOS/CHoCH momentum agrees)
  - Premium/discount agreement
  - Zone quality (multiple zone types stacked near the same price)
  - Liquidity draw (a resting liquidity pool the price is headed toward)
  - Volatility/spread conditions are checked separately (not confluence)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from trading_bot.core.enums import ConfluenceLevel, Side
from trading_bot.core.models import Candle
from trading_bot.strategy.smc.bias import BiasResult
from trading_bot.strategy.smc.zones import Zone


@dataclass
class ConfluenceResult:
    score: int = 0
    level: ConfluenceLevel = ConfluenceLevel.NONE
    factors: list[str] = field(default_factory=list)
    # --- Section 6 confluence stacking: distinct level TYPES in one tight zone
    stack_count: int = 0
    stack_kinds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "level": self.level.value,
            "factors": self.factors,
            "stack_count": self.stack_count,
            "stack_kinds": self.stack_kinds,
        }


def count_stacked_levels(
    zones: Sequence[Zone],
    entry_price: float,
    side: Side,
    zone_stack_threshold: float = 0.3,
) -> tuple[int, list[str]]:
    """Section 6 'Confluence Stacking Rule': count how many DISTINCT level types
    (rejection_block, order_block, fvg, breaker) sit inside the SAME tight
    price cluster around ``entry_price``. Liquidity pools are counted too when
    they overlap the cluster (they qualify as the swept-liquidity component).

    Returns (distinct_kind_count, sorted kind names)."""
    want = "bullish" if side is Side.BUY else "bearish"
    kinds: set[str] = set()
    for z in zones:
        if z.direction != want:
            continue
        tol = max(z.depth, 1e-9) * zone_stack_threshold
        if z.contains(entry_price, tolerance=tol):
            kinds.add(z.kind)
    return len(kinds), sorted(kinds)


def compute_confluence(
    side: Side,
    bias: Optional[BiasResult],
    zones: Sequence[Zone],
    entry_price: float,
    liquidity_zones: Sequence[Zone] = (),
    bias_weight: int = 1,
    structure_weight: int = 1,
    premium_discount_weight: int = 1,
    zone_stack_threshold: float = 0.3,  # fraction of depth to consider "stacked"
    min_confluence: int = 1,
) -> ConfluenceResult:
    """Compute confluence score for a proposed trade at ``entry_price``."""
    score = 0
    factors: list[str] = []

    # 1. Bias alignment
    if bias is not None and bias.side == side:
        score += bias_weight
        factors.append(f"bias:{bias.source}")

    # 2. Structure/Momentum alignment
    if bias is not None and bias.votes.get("momentum") == (1 if side is Side.BUY else -1):
        score += structure_weight
        factors.append("momentum_choch")

    # 3. Premium / Discount agreement
    if bias is not None:
        pd = bias.premium_discount
        if side is Side.BUY and pd == "discount":
            score += premium_discount_weight
            factors.append("buy_discount")
        elif side is Side.SELL and pd == "premium":
            score += premium_discount_weight
            factors.append("sell_premium")

    # 4. Zone stacking: count distinct zone kinds near entry
    near_zones = [
        z for z in zones
        if z.direction == ("bullish" if side is Side.BUY else "bearish")
        and z.contains(entry_price, tolerance=z.depth * zone_stack_threshold)
    ]
    if near_zones:
        score += 1
        factors.append(f"zone:{','.join(sorted({z.kind for z in near_zones}))}")

    # 5. Liquidity draw: target resting liquidity pools ahead in trade direction
    if liquidity_zones:
        for lz in liquidity_zones:
            lz_side = lz.extra.get("side")
            # BUY setup targets buy-side liquidity ABOVE price
            if side is Side.BUY and lz_side == "above":
                score += 1
                factors.append("liquidity_above")
                break
            # SELL setup targets sell-side liquidity BELOW price
            elif side is Side.SELL and lz_side == "below":
                score += 1
                factors.append("liquidity_below")
                break

    # Determine Confluence Level based on minimum threshold
    if score < min_confluence:
        stack_count, stack_kinds = count_stacked_levels(
            zones, entry_price, side, zone_stack_threshold
        )
        return ConfluenceResult(
            score=score,
            level=ConfluenceLevel.NONE,
            factors=factors,
            stack_count=stack_count,
            stack_kinds=stack_kinds,
        )

    stack_count, stack_kinds = count_stacked_levels(
        zones, entry_price, side, zone_stack_threshold
    )
    return ConfluenceResult(
        score=score,
        level=ConfluenceLevel.from_score(score),
        factors=factors,
        stack_count=stack_count,
        stack_kinds=stack_kinds,
    )