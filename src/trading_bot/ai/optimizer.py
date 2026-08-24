"""AI optimizer loop: evidence-driven, one minimal change at a time (Section 15).

Chain executed per cycle:
  trade history -> pattern detection -> weakness selection -> hypothesis ->
  candidate version (NEVER activated) -> experiment record -> optional
  head-to-head backtest comparison.

Safety properties:
  - The live/approved strategy is never modified.
  - New experiments always start as "running"; promotion happens only through
    the validation/paper pipeline.
  - Repeated optimisation against the same dataset period is flagged by the
    experiments API (overfitting guard, Section 16).
  - "Insufficient evidence" is a valid outcome and is returned as such.
"""
from __future__ import annotations

import re
from typing import Optional

from trading_bot.ai.generator import CandidateGenerator
from trading_bot.ai.pattern import PatternDetector
from trading_bot.storage.interfaces import (
    ExperimentRecord,
    StrategyVersionRecord,
)


def _next_candidate_version(parent_version: str, store, strategy: str) -> str:
    """Bump the minor number of 'vX.Y' and guarantee uniqueness."""
    m = re.match(r"^v(\d+)\.(\d+)$", parent_version or "")
    candidate = (
        f"v{m.group(1)}.{int(m.group(2)) + 1}" if m else f"{parent_version or 'v0'}.1"
    )
    while store.strategies.get(strategy, candidate) is not None:
        m2 = re.match(r"^v(\d+)\.(\d+)$", candidate)
        candidate = f"v{m2.group(1)}.{int(m2.group(2)) + 1}"
    return candidate


def _pick_weakness(patterns):
    """Most severe underperforming pattern (high > medium > low, then n)."""
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    weak = [
        p for p in patterns
        if getattr(p, "direction", "") == "underperform"
        and int(getattr(p, "n", 0)) >= 3
    ]
    if not weak:
        return None
    return sorted(
        weak,
        key=lambda p: (sev_rank.get(getattr(p, "severity", "low"), 3), -int(p.n)),
    )[0]


def run_optimizer_cycle(
    store,
    provider=None,
    *,
    strategy: str = "smc_crt",
    dataset_start: int = 0,
    dataset_end: int = 0,
    symbol: str = "XAUUSD",
    timeframe: str = "5m",
    initial_cash: float = 10_000.0,
    seed: int = 42,
    min_trades: int = 20,
    auto_backtest: bool = True,
) -> dict:
    """Run one optimizer cycle. Returns a summary describing what happened
    (or why nothing was proposed — e.g. insufficient evidence)."""
    from trading_bot.ai.review import template_hypothesis
    from trading_bot.strategy.base import create_strategy

    latest = store.strategies.latest(strategy)
    if latest is None:
        return {"status": "no_strategy", "detail": f"no versions stored for {strategy}"}

    trades = store.trades.list(strategy=strategy, limit=5000)
    if dataset_start or dataset_end:
        trades = [
            t for t in trades
            if (t.entry_time >= dataset_start if dataset_start else True)
            and (t.entry_time <= dataset_end if dataset_end else True)
        ]
    if len(trades) < min_trades:
        return {
            "status": "insufficient_evidence",
            "detail": (
                f"only {len(trades)} trades available; need at least "
                f"{min_trades} before proposing changes"
            ),
            "n_trades": len(trades),
        }

    # weakness identification via deterministic pattern detection
    patterns = PatternDetector(min_sample=5).detect(trades)
    weakness = _pick_weakness(patterns)
    if weakness is None:
        return {
            "status": "no_actionable_weakness",
            "detail": "no underperforming segment met the evidence threshold",
            "patterns_considered": len(patterns),
        }

    hypothesis = template_hypothesis([weakness], len(trades), {})
    reason = (
        f"Weakness: segment {weakness.dimension}={weakness.value} underperforms "
        f"(WR {weakness.win_rate:.0f}% vs baseline "
        f"{weakness.baseline_win_rate:.0f}%, avg R {weakness.avg_r:.2f} vs "
        f"{weakness.baseline_avg_r:.2f}, n={weakness.n})"
    )

    base = create_strategy(
        strategy, params=dict(latest.params), version=latest.version
    )
    prefix_match = re.match(r"^(v\d+)\.", latest.version)
    gen = CandidateGenerator(
        version_prefix=prefix_match.group(1) if prefix_match else "v1"
    )
    candidates = gen.generate(base, [weakness], hypothesis, seed=seed)
    cand = candidates[0]
    cand.version = _next_candidate_version(latest.version, store, strategy)

    cand_rec = store.strategies.create(
        StrategyVersionRecord(
            name=strategy,
            version=cand.version,
            parent_version=latest.version,
            params=dict(cand.params),
            rules=list(cand.rules),
            status="candidate",
            change_reason=cand.change_reason,
            ai_hypothesis=cand.hypothesis,
        )
    )

    n_exp = len(store.experiments.list(limit=100000))
    exp_id = f"EXP-{n_exp + 1}"
    proposals_desc = "; ".join(
        f"{pr.param}: {pr.from_value} -> {pr.to_value}" for pr in cand.proposals
    )
    store.experiments.create(
        ExperimentRecord(
            id=exp_id,
            strategy=strategy,
            parent_version=latest.version,
            candidate_version=cand_rec.version,
            hypothesis=cand.hypothesis,
            reason=reason,
            change_description=proposals_desc,
            expected_effect=(
                f"Improve expectancy of trades in {weakness.dimension}="
                f"{weakness.value} without degrading other segments"
            ),
            dataset_start=dataset_start,
            dataset_end=dataset_end,
        )
    )

    summary = {
        "status": "proposed",
        "experiment_id": exp_id,
        "candidate_version": cand_rec.version,
        "parent_version": latest.version,
        "pattern": weakness.to_dict(),
        "proposal": cand.proposals[0].to_dict() if cand.proposals else {},
        "backtest_ran": False,
    }

    # optional head-to-head backtest: EVIDENCE ONLY — the experiment stays
    # "running"; promotion still requires walk-forward/MC/paper downstream.
    if auto_backtest and provider is not None and dataset_end > dataset_start:
        try:
            from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
            from trading_bot.core.enums import Timeframe
            from trading_bot.validation.pipeline import (
                PromotionGate,
                compare_results,
            )

            tf = Timeframe(timeframe)
            runner = BacktestRunner(provider.resample(tf))
            cfg = BacktestConfig(
                symbol=symbol, timeframe=tf, start=dataset_start,
                end=dataset_end, initial_cash=initial_cash, seed=seed,
            )
            base_res = runner.run(
                create_strategy(strategy, params=dict(latest.params),
                                version=latest.version),
                cfg,
            )
            cand_res = runner.run(
                create_strategy(strategy, params=dict(cand.params),
                                version=cand_rec.version),
                cfg,
            )
            comparison = compare_results(base_res, cand_res)
            gate = PromotionGate().evaluate(cand_res, base_res, seed=seed)
            comparison["promotion_gate"] = gate.to_dict()
            store.experiments.update(
                exp_id,
                backtest_results={
                    "baseline": {"n_trades": base_res.n_trades,
                                 "final_equity": round(base_res.final_equity, 2)},
                    "candidate": {"n_trades": cand_res.n_trades,
                                  "final_equity": round(cand_res.final_equity, 2)},
                },
                comparison_results=comparison,
                actual_effect=(
                    f"Candidate return delta "
                    f"{comparison['headline']['total_return_pct']['delta']:+.2f}%"
                ),
            )
            summary["backtest_ran"] = True
            summary["comparison_headline"] = comparison["headline"]
        except Exception as exc:
            summary["backtest_error"] = f"{type(exc).__name__}: {exc}"

    return summary