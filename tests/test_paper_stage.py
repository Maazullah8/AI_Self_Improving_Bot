"""Tests for the paper/demo stage (Section 13) and risk-rejection endpoint."""
import pytest

from trading_bot.core.enums import ExitReason, Side
from trading_bot.core.models import TradeRecord
from trading_bot.core.time_utils import utc_ts
from trading_bot.storage.interfaces import ExperimentRecord
from trading_bot.storage.memory import MemoryStore
from trading_bot.validation.pipeline import evaluate_paper


def _paper_trade(i, r, win=True):
    return TradeRecord(
        trade_id=f"pp{i}",
        strategy="smc_crt",
        strategy_version="v1.2",
        symbol="XAUUSD",
        side=Side.BUY,
        entry_time=utc_ts(2024, 3, 1) + i * 3600,
        exit_time=utc_ts(2024, 3, 1) + i * 3600 + 1800,
        entry_price=2000.0,
        exit_price=2010.0 if win else 1995.0,
        sl=1998.0,
        tp=2012.0,
        pnl=(120 if win else -60),
        r=r,
        spread_at_entry=0.25,
        slippage_paid=0.05,
        exit_reason=ExitReason.TP if win else ExitReason.SL,
    )


class TestEvaluatePaper:
    def test_passes_when_matching_expectations(self):
        trades = [_paper_trade(i, 1.5 if i % 3 else -1.0, win=(i % 3 != 0)) for i in range(12)]
        # 8 wins / 12 = 66.7% win rate
        report = evaluate_paper(
            trades, expected={"win_rate": 66.7},
            min_trades=10, max_win_rate_dev_pct=15.0, min_expectancy_r=0.0,
        )
        assert report["passed"] is True, report["checks"]
        assert report["actual"]["n_trades"] == 12

    def test_fails_on_insufficient_trades(self):
        trades = [_paper_trade(i, 1.0) for i in range(5)]
        report = evaluate_paper(trades, min_trades=10)
        assert report["passed"] is False
        assert report["checks"]["trade_count"]["pass"] is False

    def test_fails_on_win_rate_deviation(self):
        trades = [_paper_trade(i, 1.0, win=False) for i in range(12)]  # 0% WR
        report = evaluate_paper(
            trades, expected={"win_rate": 50.0}, min_trades=10,
            max_win_rate_dev_pct=15.0,
        )
        assert report["passed"] is False
        assert report["checks"]["win_rate_deviation"]["pass"] is False

    def test_no_expectation_skips_wr_check(self):
        trades = [_paper_trade(i, 1.0) for i in range(12)]
        report = evaluate_paper(trades, expected={}, min_trades=10)
        assert "win_rate_deviation" not in report["checks"]
        assert report["passed"] is True


def _seed(store, *, cand_status="demo", trades=None):
    from trading_bot.storage.interfaces import StrategyVersionRecord

    store.strategies.create(StrategyVersionRecord(
        name="smc_crt", version="v1.1",
        params={"min_rr": 2.0}, status="live",
    ))
    store.strategies.create(StrategyVersionRecord(
        name="smc_crt", version="v1.2",
        params={"min_rr": 2.5}, status=cand_status,
        test_results={
            "paper": {"expected": {"win_rate": 60.0}, "min_trades": 5,
                      "max_win_rate_dev_pct": 20.0, "min_expectancy_r": 0.0},
        },
    ))
    store.experiments.create(ExperimentRecord(
        id="EXP-1", strategy="smc_crt", parent_version="v1.1",
        candidate_version="v1.2", hypothesis="h", decision="running",
    ))
    for i, t in enumerate(trades or []):
        store.trades.insert(t)


class TestPaperApi:
    def _client(self, store):
        from fastapi.testclient import TestClient

        from trading_bot.api.app import make_app

        return TestClient(make_app(store=store))

    def test_start_sets_demo_status(self):
        store = MemoryStore()
        _seed(store)
        client = self._client(store)
        r = client.post("/api/experiments/EXP-1/paper/start", json={
            "expected_win_rate": 60.0, "min_trades": 5,
        })
        assert r.status_code == 200
        assert r.json()["candidate_status"] == "demo"
        assert store.strategies.get("smc_crt", "v1.2").status == "demo"

    def test_evaluate_promotes_when_passed(self):
        store = MemoryStore()
        _seed(store, cand_status="demo", trades=[
            _paper_trade(i, 1.5 if i % 2 else -1.0, win=(i % 2 == 0)) for i in range(6)
        ])  # 50% WR within ±20 of expected 60 -> pass
        client = self._client(store)
        client.post("/api/experiments/EXP-1/paper/start", json={"min_trades": 5})
        r = client.post("/api/experiments/EXP-1/paper/evaluate", json={})
        body = r.json()
        assert body["report"]["passed"] is True
        assert body["decision"] == "promoted"
        assert body["candidate_status"] == "live"
        assert body["baseline_status"] == "promoted"

    def test_evaluate_rolls_back_when_failed(self):
        store = MemoryStore()
        losing = [_paper_trade(i, -1.0, win=False) for i in range(6)]
        _seed(store, cand_status="demo", trades=losing)  # 0% WR vs expected 60
        client = self._client(store)
        client.post("/api/experiments/EXP-1/paper/start", json={"min_trades": 5})
        r = client.post("/api/experiments/EXP-1/paper/evaluate", json={"auto_rollback": True})
        body = r.json()
        assert body["report"]["passed"] is False
        assert body["decision"] == "rolled_back"
        assert body["candidate_status"] == "rolled_back"
        assert body["baseline_status"] == "live"


class TestRiskRejectionsEndpoint:
    def test_endpoint_shape(self):
        from fastapi.testclient import TestClient

        from trading_bot.api.app import make_app, _LAST_RISK_REJECTIONS

        app = make_app(store=MemoryStore())
        client = TestClient(app)
        r = client.get("/api/risk/rejections")
        assert r.status_code == 200
        body = r.json()
        assert "count" in body and "rejections" in body