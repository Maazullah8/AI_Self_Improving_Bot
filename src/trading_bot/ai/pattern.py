"""Batch pattern detection across completed trades.

Deterministic, statistics-only analysis (no LLM dependency): segments the
trade history by setup dimensions and flags over/under-performing segments.
Used as the evidence base for AI hypothesis generation and strategy tuning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from trading_bot.core.models import TradeRecord

# Segment dimensions extracted from the journaled setup context.
SEGMENT_DIMENSIONS = [
    "zone_type",
    "confluence_level",
    "session",
    "day_of_week",
    "htf_bias",
    "side",
    "confirmation_type",
    "choch_csd",
    "crt",
    "regime",
]


@dataclass
class SegmentStats:
    dimension: str
    value: str
    n: int
    wins: int
    losses: int
    win_rate: float  # 0..100
    avg_r: float
    total_r: float
    expectancy: float

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "value": self.value,
            "n": self.n,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 2),
            "avg_r": round(self.avg_r, 3),
            "total_r": round(self.total_r, 3),
            "expectancy": round(self.expectancy, 4),
        }


@dataclass
class Pattern:
    dimension: str
    value: str
    n: int
    win_rate: float
    avg_r: float
    baseline_win_rate: float
    baseline_avg_r: float
    direction: str  # "outperform" | "underperform"
    severity: str  # "low" | "medium" | "high"
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "value": self.value,
            "n": self.n,
            "win_rate": round(self.win_rate, 2),
            "avg_r": round(self.avg_r, 3),
            "baseline_win_rate": round(self.baseline_win_rate, 2),
            "baseline_avg_r": round(self.baseline_avg_r, 3),
            "direction": self.direction,
            "severity": self.severity,
            "note": self.note,
        }


def _get(rec: TradeRecord, dim: str):
    return {
        "zone_type": rec.zone_type,
        "confluence_level": rec.confluence_level,
        "session": rec.session,
        "day_of_week": rec.day_of_week,
        "htf_bias": rec.htf_bias,
        "side": rec.side.value if rec.side else "",
        "confirmation_type": rec.confirmation_type,
        "choch_csd": rec.choch_csd,
        "crt": rec.crt,
        "regime": rec.regime,
    }[dim]


class PatternDetector:
    """Detects over/under-performing segments in a batch of trades."""

    def __init__(self, min_sample: int = 5, win_rate_delta: float = 15.0):
        self.min_sample = min_sample
        self.win_rate_delta = win_rate_delta

    def segment_stats(self, records: list[TradeRecord]) -> list[SegmentStats]:
        if not records:
            return []
        out: list[SegmentStats] = []
        for dim in SEGMENT_DIMENSIONS:
            buckets: dict[str, list[TradeRecord]] = {}
            for r in records:
                val = _get(r, dim)
                if val == "" or val is None:
                    continue
                buckets.setdefault(str(val), []).append(r)
            for val, group in buckets.items():
                wins = sum(1 for r in group if r.r > 0)
                n = len(group)
                out.append(
                    SegmentStats(
                        dimension=dim,
                        value=val,
                        n=n,
                        wins=wins,
                        losses=n - wins,
                        win_rate=wins / n * 100 if n else 0.0,
                        avg_r=sum(r.r for r in group) / n if n else 0.0,
                        total_r=sum(r.r for r in group),
                        expectancy=sum(r.r for r in group) / n if n else 0.0,
                    )
                )
        out.sort(key=lambda s: -s.n)
        return out

    def detect(self, records: list[TradeRecord]) -> list[Pattern]:
        if not records:
            return []
        n = len(records)
        baseline_wr = sum(1 for r in records if r.r > 0) / n * 100
        baseline_avg_r = sum(r.r for r in records) / n
        patterns: list[Pattern] = []
        for s in self.segment_stats(records):
            if s.n < self.min_sample:
                continue
            wr_delta = s.win_rate - baseline_wr
            if abs(wr_delta) < self.win_rate_delta and abs(s.avg_r - baseline_avg_r) < 0.1:
                continue
            direction = "outperform" if wr_delta > 0 else "underperform"
            severity = "low"
            if s.n >= self.min_sample * 3 and abs(wr_delta) >= self.win_rate_delta * 2:
                severity = "high"
            elif s.n >= self.min_sample * 2 and abs(wr_delta) >= self.win_rate_delta * 1.5:
                severity = "medium"
            note = (
                f"{direction}s the baseline by {abs(wr_delta):.1f}pp WR "
                f"(avg R {s.avg_r:+.2f} vs baseline {baseline_avg_r:+.2f})"
            )
            patterns.append(
                Pattern(
                    dimension=s.dimension,
                    value=s.value,
                    n=s.n,
                    win_rate=s.win_rate,
                    avg_r=s.avg_r,
                    baseline_win_rate=baseline_wr,
                    baseline_avg_r=baseline_avg_r,
                    direction=direction,
                    severity=severity,
                    note=note,
                )
            )
        patterns.sort(key=lambda p: (p.severity != "high", p.severity != "medium", -p.n))
        return patterns
