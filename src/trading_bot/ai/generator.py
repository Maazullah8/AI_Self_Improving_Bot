"""Strategy candidate generation from review evidence.

The generator NEVER mutates a live/approved strategy. It only proposes new
parameter sets (candidate versions) which must pass the validation pipeline
before promotion. Everything is deterministic so the same review evidence
always produces the same candidates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from trading_bot.ai.pattern import Pattern
from trading_bot.strategy.base import BaseStrategy


def _as_pattern(p) -> Pattern:
    if isinstance(p, Pattern):
        return p
    if isinstance(p, dict):
        return Pattern(
            dimension=p.get("dimension", ""),
            value=p.get("value", ""),
            n=int(p.get("n", 0) or 0),
            win_rate=float(p.get("win_rate", 0.0) or 0.0),
            avg_r=float(p.get("avg_r", 0.0) or 0.0),
            baseline_win_rate=float(p.get("baseline_win_rate", 0.0) or 0.0),
            baseline_avg_r=float(p.get("baseline_avg_r", 0.0) or 0.0),
            direction=p.get("direction", "outperform"),
            severity=p.get("severity", "low"),
            note=p.get("note", ""),
        )
    raise TypeError(f"cannot coerce {type(p)} to Pattern")


@dataclass
class CandidateProposal:
    """A concrete, review-motivated parameter change."""

    param: str
    from_value: object
    to_value: object
    rationale: str = ""
    severity: str = "medium"

    def to_dict(self) -> dict:
        return {
            "param": self.param,
            "from": self.from_value,
            "to": self.to_value,
            "rationale": self.rationale,
            "severity": self.severity,
        }


@dataclass
class CandidateVersion:
    name: str
    version: str
    parent_version: str
    params: dict = field(default_factory=dict)
    rules: list[str] = field(default_factory=list)
    change_reason: str = ""
    hypothesis: str = ""
    proposals: list[CandidateProposal] = field(default_factory=list)
    seed: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "parent_version": self.parent_version,
            "params": self.params,
            "rules": list(self.rules),
            "change_reason": self.change_reason,
            "hypothesis": self.hypothesis,
            "proposals": [p.to_dict() for p in self.proposals],
        }


# dimension -> (param, value_direction) mapping used to translate a pattern
# into a concrete, safe parameter adjustment.
_DIMENSION_PARAM = {
    "confluence_level": ("min_confluence", +1),
    "confirmation_type": ("require_confirmation", None),
    "zone_type": ("min_ob_body_ratio", +0.1),
    "side": ("min_rr", +0.5),
    "session": ("require_confirmation", None),
    "day_of_week": ("require_confirmation", None),
}


class CandidateGenerator:
    """Generates candidate versions from base strategy + review patterns.

    ``version_prefix`` seeds the candidate numbering (e.g. "v1.1", "v1.2").
    """

    def __init__(self, version_prefix: str = "v1", max_candidates: int = 3):
        self.version_prefix = version_prefix
        self.max_candidates = max_candidates

    def generate(
        self,
        base: BaseStrategy,
        patterns: list,
        hypothesis: str,
        seed: int = 0,
    ) -> list[CandidateVersion]:
        patterns = [_as_pattern(p) for p in patterns]
        candidates: list[CandidateVersion] = []
        base_params = base.get_params()
        base_rules = list(getattr(base, "rules", []))

        # Primary candidates: one per strong/medium pattern, translated to a
        # parameter change that counteracts the bias.
        actionable = [p for p in patterns if p.severity in ("high", "medium")]
        for i, pat in enumerate(actionable[: self.max_candidates]):
            mapping = _DIMENSION_PARAM.get(pat.dimension)
            if mapping is None:
                continue
            param, adjust = mapping
            params = dict(base_params)
            proposal = self._proposal(pat, param, adjust, params)
            if proposal is None:
                continue
            params[proposal.param] = proposal.to_value
            reason = (
                f"Filter the underperforming segment "
                f"{pat.dimension}={pat.value} (WR {pat.win_rate:.0f}% vs baseline "
                f"{pat.baseline_win_rate:.0f}%, n={pat.n})"
            )
            candidates.append(
                CandidateVersion(
                    name=base.name,
                    version=f"{self.version_prefix}.{i + 1}",
                    parent_version=base.version,
                    params=params,
                    rules=base_rules,
                    change_reason=reason,
                    hypothesis=hypothesis,
                    proposals=[proposal],
                    seed=seed + i,
                )
            )

        # Fallback: conservative grid candidate so there is always at least one
        # testable version even with no actionable patterns.
        if not candidates:
            params = dict(base_params)
            cur = float(base_params.get("min_rr", 2.0))
            params["min_rr"] = round(cur + 0.25, 2)
            candidates.append(
                CandidateVersion(
                    name=base.name,
                    version=f"{self.version_prefix}.1",
                    parent_version=base.version,
                    params=params,
                    rules=base_rules,
                    change_reason="No strong patterns; conservative RR floor bump.",
                    hypothesis=hypothesis,
                    proposals=[
                        CandidateProposal(
                            param="min_rr",
                            from_value=cur,
                            to_value=round(cur + 0.25, 2),
                            rationale="Raise minimum reward multiple to reduce marginal setups.",
                            severity="low",
                        )
                    ],
                    seed=seed,
                )
            )
        return candidates

    def _proposal(self, pat: Pattern, param: str, adjust, params: dict) -> Optional[CandidateProposal]:
        if param == "require_confirmation":
            if pat.direction == "underperform" and not params.get("require_confirmation", False):
                return CandidateProposal(
                    param="require_confirmation",
                    from_value=False,
                    to_value=True,
                    rationale=f"Segment {pat.dimension}={pat.value} underperforms; require confirmation.",
                    severity=pat.severity,
                )
            return None
        if param not in params:
            return None
        cur = params[param]
        if isinstance(cur, bool):
            return None
        delta = adjust if pat.direction == "underperform" else -adjust
        new_val = round(float(cur) + delta, 3) if isinstance(cur, (int, float)) else cur
        if new_val <= 0:
            return None
        return CandidateProposal(
            param=param,
            from_value=cur,
            to_value=new_val,
            rationale=f"Counter underperformance in {pat.dimension}={pat.value} "
            f"(WR {pat.win_rate:.0f}% vs {pat.baseline_win_rate:.0f}%).",
            severity=pat.severity,
        )
