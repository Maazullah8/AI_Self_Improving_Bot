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

    def to_dict(self) -> dict:
        return {"score": self.score, "level": self.level.value, "factors": self.factors}


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

    if bias is not None and bias.side == side:
        score += bias_weight
        factors.append(f"bias:{bias.source}")

    if bias is not None and bias.votes.get("momentum") == (1 if side is Side.BUY else -1):
        score += structure_weight
        factors.append("momentum_choch")

    if bias is not None:
        pd = bias.premium_discount
        if side is Side.BUY and pd == "discount":
            score += premium_discount_weight
            factors.append("buy_discount")
        elif side is Side.SELL and pd == "premium":
            score += premium_discount_weight
            factors.append("sell_premium")

    # zone stacking: count distinct zone kinds near entry
    near_zones = [
        z for z in zones
        if z.direction == ("bullish" if side is Side.BUY else "bearish")
        and z.contains(entry_price, tolerance=z.depth * zone_stack_threshold)
    ]
    if near_zones:
        score += 1
        factors.append(f"zone:{','.join(sorted({z.kind for z in near_zones}))}")

    # liquidity draw: a resting liquidity pool ahead in the trade direction
    if liquidity_zones:
        for lz in liquidity_zones:
            if side is Side.BUY and lz.extra.get("side") == "below":
                score += 1
                factors.append("liquidity_below")
                break
            if side is Side.SELL and lz.extra.get("side") == "above":
                score += 1
                factors.append("liquidity_above")
                break

    if score < min_confluence:
        return ConfluenceResult(0, ConfluenceLevel.NONE, factors)
    return ConfluenceResult(score, ConfluenceLevel.from_score(score), factors)
