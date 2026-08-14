"""Tests for AI review, pattern detection, candidate generation, validation."""
import numpy as np
import pytest

from trading_bot.ai.generator import CandidateGenerator
from trading_bot.ai.pattern import PatternDetector
from trading_bot.ai.review import AITradeReviewer, RuleCompliance
from trading_bot.core.enums import ExitReason, Side
from trading_bot.core.models import TradeRecord
from trading_bot.strategy.base import create_strategy
from trading_bot.validation.pipeline import (
    PromotionGate,
    monte_carlo,
    run_walk_forward,
    time_split,
)


def _trade(r, zone="order_block", confluence="low", side=Side.BUY, conf="engulfing"):
    return TradeRecord(
        trade_id=f"t{abs(hash((r, zone)))}",
        strategy="smc_crt",
        strategy_version="v1.0",
        side=side,
        pnl=r * 100,
        r=r,
        rr=2.0,
        sl=1.0,
        tp=1.02,
        exit_reason=ExitReason.TP if r > 0 else ExitReason.SL,
        zone_type=zone,
        confluence_level=confluence,
        confirmation_type=conf,
        session="london",
        day_of_week=3,
        htf_bias="buy",
        duration_seconds=3600,
    )


def _series(rs):
    return [_trade(r) for r in rs]


class TestPatternDetector:
    def test_segment_stats(self):
        recs = _series([0.5, -1.0, 0.5, -1.0, 0.5, -1.0, 0.5, -1.0, 0.5, -1.0])
        det = PatternDetector(min_sample=2)
        stats = det.segment_stats(recs)
        assert stats
        zs = [s for s in stats if s.dimension == "zone_type" and s.value == "order_block"]
        assert zs and zs[0].n == 10 and zs[0].wins == 5

    def test_detect_outperformance(self):
        recs = _series([0.5, -1.0, -1.0, 0.5, -1.0, 0.8, 0.9, 0.7, 0.8, 0.6])
        # high-confluence segment: all wins (100% WR) vs baseline ~50%
        for i in range(5, 10):
            recs[i].confluence_level = "high"
        det = PatternDetector(min_sample=3, win_rate_delta=15.0)
        pats = det.detect(recs)
        assert any(p.dimension == "confluence_level" and p.direction == "outperform" for p in pats)


class TestRuleCompliance:
    def test_all_clean(self):
        recs = _series([0.5, -1.0])
        comp = RuleCompliance().compute(recs, [])
        assert all(v["violations"] == 0 for v in comp.values())

    def test_min_rr_violation(self):
        rec = _trade(0.5)
        rec.rr = 0.8
        comp = RuleCompliance().compute([rec], [])
        assert comp["min_rr"]["violations"] == 1


class TestReviewer:
    def test_review_creates_record(self):
        recs = _series([0.5, -1.0, 0.6, -0.8, 1.2, -1.0, 0.4, 0.7, -0.5, 0.9])
        rev = AITradeReviewer().review(recs, strategy="smc_crt", strategy_version="v1.0", rules=["x"])
        assert rev.n_trades == 10
        assert rev.hypothesis
        assert rev.patterns is not None

    def test_review_empty(self):
        rev = AITradeReviewer().review([], strategy="s", strategy_version="v0")
        assert rev.n_trades == 0


class TestCandidateGenerator:
    def test_generates_candidates(self):
        base = create_strategy("smc_crt", params={"min_rr": 2.0})
        det = PatternDetector(min_sample=3)
        recs = _series([0.5, -1.0, -1.0, 0.5, -1.0, 0.8, 0.9, 0.7, 0.8, 0.6])
        for i in range(5, 10):
            recs[i].confluence_level = "high"
        pats = det.detect(recs)
        cands = CandidateGenerator(version_prefix="v1.1").generate(base, pats, "hyp")
        assert cands
        for c in cands:
            assert c.version.startswith("v1.1")
            assert c.parent_version == base.version
            # never mutates the base strategy params
            assert base.get_params()["min_rr"] == 2.0

    def test_fallback_candidate_when_no_patterns(self):
        base = create_strategy("smc_crt", params={"min_rr": 2.0})
        cands = CandidateGenerator().generate(base, [], "no patterns")
        assert len(cands) >= 1


class TestValidation:
    def test_time_split(self):
        s = time_split(0, 1000, 0.6, 0.2)
        assert s.train_end == 600
        assert s.val_end == 800
        assert s.test_end == 1000

    def test_monte_carlo_deterministic(self):
        rs = [0.5, -1.0, 0.5, -1.0, 0.6, 0.7]
        a = monte_carlo(rs, n_sims=500, seed=1)
        b = monte_carlo(rs, n_sims=500, seed=1)
        assert a == b
        assert "median_final_equity" in a
        assert "risk_of_ruin_pct" in a

    def test_monte_carlo_distribution_and_paths(self):
        rs = [0.5, -1.0, 0.5, -1.0, 0.6, 0.7]
        mc = monte_carlo(rs, n_sims=300, seed=1, return_paths=True, n_paths=25)
        assert "pass_rate" in mc
        assert 0.0 <= mc["pass_rate"] <= 100.0
        assert "median_return_pct" in mc
        assert mc["ci_low_pct"] <= mc["median_return_pct"] <= mc["ci_high_pct"]
        assert len(mc["distribution"]) == 40
        assert all("bin" in b and "count" in b for b in mc["distribution"])
        assert sum(b["count"] for b in mc["distribution"]) == 300
        assert len(mc["equity_paths"]) == 25
        assert all(len(p) > 1 for p in mc["equity_paths"])

    def test_monte_carlo_empty_series(self):
        mc = monte_carlo([], return_paths=True)
        assert mc["distribution"] == []
        assert mc["equity_paths"] == []
        assert mc["median_final_equity"] == 10000.0


class TestLLMConfig:
    def test_chat_endpoint_building(self):
        from trading_bot.ai.llm import _chat_endpoint

        assert _chat_endpoint("http://localhost:11434") == "http://localhost:11434/v1/chat/completions"
        assert _chat_endpoint("http://localhost:11434/v1") == "http://localhost:11434/v1/chat/completions"
        assert _chat_endpoint("https://api.openai.com/v1") == "https://api.openai.com/v1/chat/completions"
        assert _chat_endpoint("https://x.example/chat/completions") == "https://x.example/chat/completions"
        assert _chat_endpoint("") == ""

    def test_llm_from_config(self):
        from trading_bot.ai.llm import llm_from_config
        from trading_bot.storage.interfaces import ModelConfigRecord

        # local ollama needs no key
        llm = llm_from_config(ModelConfigRecord(provider="ollama", model="llama3.1:8b"))
        assert llm is not None
        assert llm.base_url == "http://localhost:11434"
        assert llm.api_key == ""

        # online provider without a key -> unusable (fail-closed)
        assert llm_from_config(ModelConfigRecord(provider="openai", model="gpt-4o")) is None

        # online provider with a key -> usable
        llm2 = llm_from_config(ModelConfigRecord(provider="openai", api_key="sk-test", model="gpt-4o"))
        assert llm2 is not None and llm2.api_key == "sk-test"

    def test_model_record_masking(self):
        from trading_bot.storage.interfaces import ModelConfigRecord

        rec = ModelConfigRecord(api_key="sk-proj-1234567890abcdef")
        assert rec.masked_key() == "sk-pro••••••••cdef"
        assert "api_key" not in rec.to_dict()
        assert rec.to_dict(include_key=True)["api_key"] == "sk-proj-1234567890abcdef"

    def test_synthetic_resample(self):
        from trading_bot.core.enums import Timeframe
        from trading_bot.core.time_utils import utc_ts
        from trading_bot.data.base import MarketDataQuery
        from trading_bot.data.synthetic import SyntheticDataProvider

        p = SyntheticDataProvider(
            symbol="EURUSD", seed=5,
            start=utc_ts(2023, 1, 1), end=utc_ts(2023, 2, 28, 23, 59),
            tf=Timeframe.M5, initial_price=1.1, volatility=0.0005,
        )
        coarse = p.resample(Timeframe.H1)
        assert coarse is not p
        bars = coarse.load_candles(MarketDataQuery(symbol="EURUSD", timeframe=Timeframe.H1))
        assert len(bars) > 0

    def test_monte_carlo_ruin_low_for_positive_series(self):
        rs = [0.5, 0.5, 0.6, 0.4, 0.7, 0.5]
        mc = monte_carlo(rs, n_sims=1000, seed=3)
        assert mc["risk_of_ruin_pct"] < 5.0

    def test_promotion_gate_strong_candidate(self):
        from trading_bot.backtest.runner import BacktestResult

        res = BacktestResult(
            symbol="EURUSD", n_trades=50,
            trades=[_trade(0.5), _trade(-1.0), _trade(0.5)],
            metrics={
                "n_trades": 50, "profit_factor": 1.6, "max_drawdown_pct": 8.0,
                "expectancy_r": 0.15, "win_rate": 55.0,
                "initial_equity": 10000.0,
            },
        )
        gate = PromotionGate()
        pr = gate.evaluate(res, seed=0)
        assert pr.passed

    def test_promotion_gate_rejects_weak(self):
        from trading_bot.backtest.runner import BacktestResult

        res = BacktestResult(
            symbol="EURUSD", n_trades=5,
            trades=[_trade(-1.0), _trade(-1.0), _trade(-1.0)],
            metrics={
                "n_trades": 5, "profit_factor": 0.2, "max_drawdown_pct": 40.0,
                "expectancy_r": -0.4, "win_rate": 20.0,
                "initial_equity": 10000.0,
            },
        )
        gate = PromotionGate()
        pr = gate.evaluate(res, seed=0)
        assert not pr.passed
        assert any("insufficient trades" in r for r in pr.reasons)


class TestWalkForward:
    def test_walk_forward_runs(self):
        from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
        from trading_bot.core.enums import Timeframe
        from trading_bot.core.time_utils import utc_ts
        from trading_bot.data.synthetic import SyntheticDataProvider

        p = SyntheticDataProvider(
            symbol="EURUSD", seed=5,
            start=utc_ts(2023, 1, 1), end=utc_ts(2023, 2, 28, 23, 59),
            tf=Timeframe.M5, initial_price=1.1, volatility=0.0005,
        )
        runner = BacktestRunner(p)
        params = {
            "htf": "4h", "zone_tf": "4h", "ltf": "5m",
            "zone_lookback": 100, "bias_lookback": 100,
        }
        cfg = BacktestConfig(
            symbol="EURUSD", timeframe=Timeframe.M5,
            start=utc_ts(2023, 1, 1), end=utc_ts(2023, 2, 28, 23, 59),
            initial_cash=10000.0, seed=1,
        )
        wf = run_walk_forward(runner, "smc_crt", params, "v1.0", cfg, n_windows=4)
        assert len(wf.windows) == 4
        assert len(wf.val_expectancy_r) == 4
        # every window must have a train and val result
        assert all(w.train is not None and w.val is not None for w in wf.windows)
