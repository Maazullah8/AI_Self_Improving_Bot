"""End-to-end integration test: the full self-improvement loop on demo data."""
import pytest

from demo.run_demo import run_demo
from trading_bot.core.enums import StrategyStatus


@pytest.mark.slow
class TestDemo:
    def test_full_loop(self):
        result = run_demo(seed=7, months=3, n_mc_sims=200, verbose=False)
        assert result["base_result"].n_trades > 0
        # store accumulates baseline + candidate validation trades
        assert result["store"].trades.count() >= result["base_result"].n_trades
        assert result["review"].n_trades == result["base_result"].n_trades
        assert result["review"].hypothesis
        assert result["candidates"]
        # baseline never mutated
        assert result["baseline"].get_params()["min_rr"] == 2.0
        # strategy versions persisted, candidates are rejected or promoted (not live)
        versions = result["store"].strategies.list("smc_crt")
        statuses = {v.status for v in versions}
        assert not (statuses & {StrategyStatus.LIVE.value})

    def test_candidates_never_match_baseline_params(self):
        result = run_demo(seed=3, months=2, n_mc_sims=100, verbose=False)
        base_params = result["baseline"].get_params()
        for cand, _cres, _dec in result["candidates"]:
            assert cand.params != base_params
            assert cand.parent_version == result["baseline"].version
