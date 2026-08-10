"""End-to-end demo: data -> backtest -> journal -> review -> candidates ->
validation -> promotion decision.

This is the full self-improvement loop in one script. It runs entirely on
synthetic/demo data and never touches a broker.
"""
from __future__ import annotations

import time
from typing import Optional

from trading_bot.ai.generator import CandidateGenerator
from trading_bot.ai.review import AITradeReviewer
from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
from trading_bot.core.enums import StrategyStatus, Timeframe
from trading_bot.core.time_utils import utc_ts
from trading_bot.data.synthetic import SyntheticDataProvider
from trading_bot.journal.journal import Journal
from trading_bot.storage.interfaces import StrategyVersionRecord, utcnow_iso
from trading_bot.storage.memory import MemoryStore
from trading_bot.strategy.base import create_strategy
from trading_bot.validation.pipeline import (
    PromotionGate,
    run_walk_forward,
    time_split,
)


def build_demo_context(seed: int = 7, months: int = 6, start_year: int = 2023, start_month: int = 1):
    """Build provider + store + baseline strategy for a demo run."""
    provider = SyntheticDataProvider(
        symbol="EURUSD",
        seed=seed,
        start=utc_ts(start_year, start_month, 1),
        end=utc_ts(start_year, start_month + months, 1) - 1,
        tf=Timeframe.M5,
        initial_price=1.1000,
        volatility=0.0004,
        trend_cycles=8,
    )
    store = MemoryStore()
    strategy = create_strategy(
        "smc_crt",
        params={"htf": "4h", "zone_tf": "4h", "ltf": "5m", "zone_lookback": 150, "bias_lookback": 150},
    )
    return provider, store, strategy


def run_demo(seed: int = 7, months: int = 6, n_mc_sims: int = 500, verbose: bool = True):
    t0 = time.time()
    provider, store, baseline = build_demo_context(seed=seed, months=months)

    # 1. Backtest baseline on the full window
    journal = Journal(store=store.trades, strategy_name=baseline.name, strategy_version=baseline.version)
    runner = BacktestRunner(provider, journal=journal)
    bars = provider.load_candles(__import__(
        "trading_bot.data.base", fromlist=["MarketDataQuery"]).MarketDataQuery(symbol="EURUSD", timeframe=Timeframe.M5))
    start_ts, end_ts = bars[0].time, bars[-1].time
    cfg = BacktestConfig(symbol="EURUSD", timeframe=Timeframe.M5, start=start_ts, end=end_ts, initial_cash=10_000.0, seed=seed)
    base_result = runner.run(baseline, cfg)

    # 2. Persist baseline version record
    store.strategies.create(StrategyVersionRecord(
        name=baseline.name, version=baseline.version,
        params=baseline.get_params(), rules=list(baseline.rules),
        status=StrategyStatus.CANDIDATE.value,
        test_results=base_result.metrics,
        created_at=utcnow_iso(),
    ))

    # 3. AI review of the journaled trades
    reviewer = AITradeReviewer()
    rev = reviewer.review(
        journal.records(), strategy=baseline.name, strategy_version=baseline.version,
        rules=list(baseline.rules), window_start=start_ts, window_end=end_ts,
    )
    store.reviews.insert(rev)

    # 4. Generate candidate versions (never mutate baseline)
    gen = CandidateGenerator(version_prefix="v1.1")
    candidates = gen.generate(baseline, rev.patterns, rev.hypothesis, seed=seed)

    # 5. Validate candidates: split, walk-forward, promotion gate
    split = time_split(start_ts, end_ts, 0.6, 0.2)
    gate = PromotionGate()
    candidate_results = []
    for cand in candidates:
        cand_cfg = BacktestConfig(symbol="EURUSD", timeframe=Timeframe.M5, start=split.test_start, end=split.test_end, initial_cash=10_000.0, seed=seed)
        cand_strat = create_strategy(cand.name, params=cand.params, version=cand.version)
        cand_result = runner.run(cand_strat, cand_cfg)
        wf = run_walk_forward(runner, cand.name, cand.params, cand.version, cand_cfg, n_windows=4)
        decision = gate.evaluate(cand_result, baseline=base_result, wf=wf, seed=seed)
        candidate_results.append((cand, cand_result, decision))
        store.strategies.create(StrategyVersionRecord(
            name=cand.name, version=cand.version, parent_version=cand.parent_version,
            params=cand.params, rules=cand.rules,
            status=(StrategyStatus.PROMOTED.value if decision.passed else StrategyStatus.REJECTED.value),
            change_reason=cand.change_reason, ai_hypothesis=cand.hypothesis,
            test_results={"val": cand_result.metrics, "decision": decision.to_dict()},
            created_at=utcnow_iso(),
        ))

    if verbose:
        print(f"demo completed in {time.time() - t0:.1f}s")
        print(f"baseline: {base_result.n_trades} trades, "
              f"WR {base_result.metrics['win_rate']:.1f}%, "
              f"PF {base_result.metrics['profit_factor']:.2f}, "
              f"expectancy {base_result.metrics['expectancy_r']:.3f}R, "
              f"equity {base_result.final_equity:.2f}")
        print(f"review: {rev.n_trades} trades, {len(rev.patterns)} patterns")
        print(f"hypothesis: {rev.hypothesis[:160]}...")
        print(f"candidates generated: {len(candidates)}")
        for cand, cres, dec in candidate_results:
            flag = "PASS" if dec.passed else "FAIL"
            print(f"  {cand.version}: {cres.n_trades} trades, PF {cres.metrics['profit_factor']:.2f}, "
                  f"expectancy {cres.metrics['expectancy_r']:.3f}R -> {flag} "
                  f"({' '.join(dec.reasons[:2])})")

    return {
        "provider": provider,
        "store": store,
        "baseline": baseline,
        "base_result": base_result,
        "review": rev,
        "candidates": candidate_results,
    }


if __name__ == "__main__":
    run_demo()
