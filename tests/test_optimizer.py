"""Tests for the AI optimizer loop (Section 15/16)."""
import pytest

from trading_bot.core.enums import ExitReason, Side
from trading_bot.core.models import TradeRecord
from trading_bot.core.time_utils import utc_ts
from trading_bot.storage.interfaces import StrategyVersionRecord
from trading_bot.storage.memory import MemoryStore


T0 = utc_ts(2024, 2, 1, 8, 0)


def _seed_trades(store, n_good=15, n_bad=10):
    """Create a history with a clearly underperforming low-confluence segment."""
    t0 = T0
    i = 0
    for _ in range(n_good):
        store.trades.insert(TradeRecord(
            trade_id=f"g{i}", strategy="smc_crt", strategy_version="v1.1",
            symbol="XAUUSD", side=Side.BUY,
            entry_time=t0 + i * 3600, exit_time=t0 + i * 3600 + 1800,
            pnl=150, r=1.5, confluence_level="high",
            exit_reason=ExitReason.TP, regime="trending_up",
        ))
        i += 1
    for j in range(n_bad):
        store.trades.insert(TradeRecord(
            trade_id=f"b{j}", strategy="smc_crt", strategy_version="v1.1",
            symbol="XAUUSD", side=Side.BUY,
            entry_time=t0 + (n_good + j) * 3600,
            exit_time=t0 + (n_good + j) * 3600 + 1800,
            pnl=-100, r=-1.0, confluence_level="low",
            exit_reason=ExitReason.SL, regime="ranging",
        ))


def _seed_version(store):
    store.strategies.create(StrategyVersionRecord(
        name="smc_crt", version="v1.1",
        params={"min_confluence": 1, "min_rr": 2.0},
        rules=["no_confirmation_no_trade"], status="live",
    ))


class TestOptimizerCycle:
    def test_insufficient_evidence(self):
        from trading_bot.ai.optimizer import run_optimizer_cycle

        store = MemoryStore()
        _seed_version(store)
        _seed_trades(store, n_good=3, n_bad=2)
        summary = run_optimizer_cycle(
            store, min_trades=20, auto_backtest=False
        )
        assert summary["status"] == "insufficient_evidence"

    def test_no_strategy(self):
        from trading_bot.ai.optimizer import run_optimizer_cycle

        summary = run_optimizer_cycle(MemoryStore(), min_trades=1)
        assert summary["status"] == "no_strategy"

    def test_full_cycle_creates_candidate_and_experiment(self):
        from trading_bot.ai.optimizer import run_optimizer_cycle

        store = MemoryStore()
        _seed_version(store)
        _seed_trades(store)
        summary = run_optimizer_cycle(store, auto_backtest=False)

        assert summary["status"] == "proposed"
        assert summary["pattern"]["direction"] == "underperform"
        assert summary["pattern"]["value"] == "low"

        # candidate version created as CANDIDATE, live untouched
        cand = store.strategies.get("smc_crt", summary["candidate_version"])
        assert cand is not None
        assert cand.status == "candidate"
        assert cand.parent_version == "v1.1"
        live = store.strategies.get("smc_crt", "v1.1")
        assert live.status == "live"
        # minimal change: min_confluence tightened by exactly one step
        assert cand.params["min_confluence"] == live.params["min_confluence"] + 1

        # experiment linked and still running (never auto-promoted)
        exp = store.experiments.get(summary["experiment_id"])
        assert exp.decision == "running"
        assert exp.candidate_version == cand.version
        assert "confluence" in exp.change_description.lower()

    def test_duplicate_weakness_gets_unique_versions(self):
        from trading_bot.ai.optimizer import run_optimizer_cycle

        store = MemoryStore()
        _seed_version(store)
        _seed_trades(store)
        s1 = run_optimizer_cycle(store, auto_backtest=False)
        s2 = run_optimizer_cycle(store, auto_backtest=False)
        assert s2["candidate_version"] != s1["candidate_version"]
        assert store.experiments.get(s2["experiment_id"]) is not None

    def test_api_endpoint_runs_cycle(self):
        from fastapi.testclient import TestClient

        from trading_bot.api.app import make_app

        store = MemoryStore()
        _seed_version(store)
        _seed_trades(store)
        client = TestClient(make_app(store=store))  # no provider -> backtest off
        r = client.post("/api/optimize/run", json={
            "strategy": "smc_crt", "auto_backtest": False, "min_trades": 20,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "proposed"
        assert body["backtest_ran"] is False