"""AI review of a batch of trades: rule compliance + hypothesis generation.

The review is primarily deterministic (rule compliance, pattern detection,
template-based hypothesis). An optional ``ReviewLLM`` interface can be plugged
in to produce richer prose, but the pipeline must never depend on it: if the
LLM is unavailable or errors, a deterministic hypothesis is always produced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol

from trading_bot.ai.pattern import Pattern, PatternDetector
from trading_bot.core.models import TradeRecord
from trading_bot.storage.interfaces import ReviewRecord, utcnow_iso


class ReviewLLM(Protocol):
    """Optional LLM hook. Must be safe to call and must not block the
    deterministic review if it fails."""

    def generate_hypothesis(self, prompt: str) -> str: ...


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


class RuleCompliance:
    """Checks that executed trades respected the strategy's hard rules."""

    # exit reasons that represent a clean, rule-respecting close
    ALLOWED_EXITS = {
        "tp", "sl", "break_even", "partial_tp", "trailing_stop",
        "strategy_exit", "flatten",
    }

    def compute(self, records: list[TradeRecord], rules: list[str]) -> dict:
        checks = {
            "min_rr": {"rule": "minimum 1:2 risk:reward", "ok": 0, "violations": 0, "detail": []},
            "valid_sltp": {"rule": "stop-loss/target valid at entry", "ok": 0, "violations": 0, "detail": []},
            "clean_exit": {"rule": "position closed by a rule-based exit", "ok": 0, "violations": 0, "detail": []},
        }
        for r in records:
            rr = r.rr if r.rr else abs(r.tp - r.entry_price) / abs(r.entry_price - r.sl) if r.sl != r.entry_price else 0.0
            if rr >= 1.5:
                checks["min_rr"]["ok"] += 1
            else:
                checks["min_rr"]["violations"] += 1
                checks["min_rr"]["detail"].append({"trade": r.trade_id, "rr": round(rr, 2)})

            if r.sl > 0 and r.tp > 0 and r.sl != r.entry_price:
                checks["valid_sltp"]["ok"] += 1
            else:
                checks["valid_sltp"]["violations"] += 1
                checks["valid_sltp"]["detail"].append({"trade": r.trade_id})

            reason = r.exit_reason.value if hasattr(r.exit_reason, "value") else str(r.exit_reason)
            if reason in self.ALLOWED_EXITS:
                checks["clean_exit"]["ok"] += 1
            else:
                checks["clean_exit"]["violations"] += 1
                checks["clean_exit"]["detail"].append({"trade": r.trade_id, "exit": reason})

        n = len(records)
        for k, v in checks.items():
            v["compliance_pct"] = round(v["ok"] / n * 100, 2) if n else 100.0
            v["detail"] = v["detail"][:10]  # cap detail for storage
        return checks


def template_hypothesis(patterns: list[Pattern], n_trades: int, compliance: dict) -> str:
    """Deterministic hypothesis generator based on detected patterns."""
    if n_trades == 0:
        return "Insufficient trade history to form a hypothesis."
    strong = [p for p in patterns if p.severity == "high"]
    medium = [p for p in patterns if p.severity == "medium"]

    lines = []
    if strong or medium:
        for p in (strong + medium)[:3]:
            verb = "amplify" if p.direction == "outperform" else "filter out"
            lines.append(
                f"Segment {p.dimension}={p.value} {p.direction}s by "
                f"{abs(p.win_rate - p.baseline_win_rate):.1f}pp WR "
                f"(n={p.n}, avg R {p.avg_r:+.2f}); consider tightening/relaxing "
                f"rules to {verb} this segment."
            )
    low_wr = [p for p in patterns if p.direction == "underperform" and p.n >= 10]
    if low_wr:
        worst = min(low_wr, key=lambda p: p.win_rate)
        lines.append(
            f"Worst segment: {worst.dimension}={worst.value} "
            f"(n={worst.n}, WR {worst.win_rate:.1f}%). Add a filter for this "
            "condition or lower its confluence weight."
        )
    if not lines:
        lines.append(
            "No statistically strong segments found; keep parameters stable "
            "and extend the sample before changing anything."
        )
    compliance_issues = [k for k, v in compliance.items() if v["violations"] > 0]
    if compliance_issues:
        lines.append(
            f"Rule compliance gaps on: {', '.join(compliance_issues)}. "
            "Fix enforcement before any parameter tuning."
        )
    return " ".join(lines)


class AITradeReviewer:
    """Builds a ReviewRecord from a batch of trades + strategy rules."""

    def __init__(self, llm: Optional[ReviewLLM] = None):
        self.llm = llm
        self.detector = PatternDetector()

    def review(
        self,
        records: list[TradeRecord],
        strategy: str = "",
        strategy_version: str = "",
        rules: Optional[list[str]] = None,
        window_start: int = 0,
        window_end: int = 0,
    ) -> ReviewRecord:
        compliance = RuleCompliance().compute(records, rules or [])
        patterns = self.detector.detect(records)
        hypothesis = template_hypothesis(patterns, len(records), compliance)

        if self.llm is not None:
            prompt = (
                f"Strategy {strategy} v{strategy_version}: {len(records)} trades reviewed.\n"
                f"Patterns: {[p.to_dict() for p in patterns[:6]]}\n"
                f"Compliance: {compliance}\n"
                "Propose one concrete, falsifiable hypothesis for the next "
                "strategy candidate version."
            )
            llm_out = _safe(lambda: self.llm.generate_hypothesis(prompt), None)
            if llm_out:
                hypothesis = llm_out

        summary = (
            f"{len(records)} trades reviewed for {strategy} v{strategy_version}; "
            f"{len(patterns)} significant segment patterns; "
            f"{sum(1 for c in compliance.values() if c['violations'] == 0)}/{len(compliance)} "
            "rule checks clean."
        )
        return ReviewRecord(
            id=f"rev_{strategy_version}_{window_start}_{len(records)}",
            strategy=strategy,
            strategy_version=strategy_version,
            window_start=window_start,
            window_end=window_end,
            n_trades=len(records),
            summary=summary,
            rule_compliance=compliance,
            patterns=[p.to_dict() for p in patterns],
            hypothesis=hypothesis,
            created_at=utcnow_iso(),
        )
