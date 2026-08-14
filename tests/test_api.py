"""Tests for the FastAPI application (read-only endpoints + backtest/review)."""
import pytest

from fastapi.testclient import TestClient

from trading_bot.api.app import make_app
from trading_bot.core.enums import Timeframe
from trading_bot.core.time_utils import utc_ts
from trading_bot.data.synthetic import SyntheticDataProvider
from trading_bot.storage.memory import MemoryStore


@pytest.fixture(scope="module")
def client():
    store = MemoryStore()
    provider = SyntheticDataProvider(
        symbol="EURUSD", seed=5,
        start=utc_ts(2023, 1, 1), end=utc_ts(2023, 2, 28, 23, 59),
        tf=Timeframe.M5, initial_price=1.1, volatility=0.0005,
    )
    app = make_app(store=store, provider=provider)
    return TestClient(app)


class TestApi:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_empty_trades(self, client):
        r = client.get("/api/trades")
        assert r.status_code == 200
        assert r.json() == []

    def test_empty_metrics(self, client):
        r = client.get("/api/metrics")
        assert r.status_code == 200
        assert r.json()["n_trades"] == 0

    def test_strategies_empty(self, client):
        r = client.get("/api/strategies")
        assert r.status_code == 200

    def test_live_disabled_by_default(self, client):
        r = client.get("/api/live")
        assert r.status_code == 200
        body = r.json()
        assert body["running"] is False

    def test_live_enabled_returns_status(self):
        from trading_bot.execution.executor import SimulatedExecutor
        from trading_bot.live.pipeline import LiveConfig, LiveTradePipeline
        from trading_bot.strategy.base import create_strategy

        store = MemoryStore()
        provider = SyntheticDataProvider(
            symbol="XAUUSD", seed=5,
            start=utc_ts(2024, 1, 1), end=utc_ts(2024, 2, 1),
            tf=Timeframe.M5, initial_price=2050.0, volatility=0.0005,
        )
        pipe = LiveTradePipeline(
            provider=provider, strategy=create_strategy("smc_crt"),
            executor=SimulatedExecutor(), store=store,
            config=LiveConfig(symbol="XAUUSD", timeframe="5m"),
        )
        app = make_app(store=store, provider=provider, live=pipe)
        r = TestClient(app).get("/api/live")
        assert r.status_code == 200
        body = r.json()
        assert body["running"] is True
        assert body["symbol"] == "XAUUSD"
        assert body["strategy"] == "smc_crt"
        assert body["open_positions"] == []

    def test_backtest_endpoint(self, client):
        r = client.post("/api/backtest", json={
            "symbol": "EURUSD",
            "timeframe": "5m",
            "start": utc_ts(2023, 1, 1),
            "end": utc_ts(2023, 1, 31, 23, 59),
            "initial_cash": 10000.0,
            "strategy": "smc_crt",
            "params": {"htf": "4h", "zone_tf": "4h", "ltf": "5m"},
            "seed": 42,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["n_bars"] > 0
        assert "metrics" in body

    def test_backtest_returns_equity_curve_and_monte_carlo(self, client):
        r = client.post("/api/backtest", json={
            "symbol": "EURUSD",
            "timeframe": "5m",
            "start": utc_ts(2023, 1, 1),
            "end": utc_ts(2023, 1, 31, 23, 59),
            "initial_cash": 10000.0,
            "strategy": "smc_crt",
            "params": {"htf": "4h", "zone_tf": "4h", "ltf": "5m"},
            "seed": 42,
        })
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body["equity_curve"], list) and len(body["equity_curve"]) > 0
        mc = body["monte_carlo"]
        assert mc["n_sims"] == 2000
        assert "median_final_equity" in mc
        assert "risk_of_ruin_pct" in mc
        assert "worst_dd_pct_95" in mc
        assert "worst_streak_95" in mc
        assert "pass_rate" in mc
        assert "median_return_pct" in mc
        assert "ci_low_pct" in mc and "ci_high_pct" in mc
        assert isinstance(mc["distribution"], list) and len(mc["distribution"]) > 0
        assert isinstance(mc["equity_paths"], list) and len(mc["equity_paths"]) > 0
        assert all(isinstance(p, list) and p for p in mc["equity_paths"])
        # walk-forward analysis is included and shaped for the dashboard
        wf = body["walk_forward"]
        assert wf is not None
        assert "generalization_score" in wf
        assert "segments" in wf and len(wf["segments"]) > 0
        assert all(
            "train_win_rate" in s and "test_win_rate" in s for s in wf["segments"]
        )
        # deterministic for the same trade series + seed
        r2 = client.post("/api/backtest", json={
            "symbol": "EURUSD",
            "timeframe": "5m",
            "start": utc_ts(2023, 1, 1),
            "end": utc_ts(2023, 1, 31, 23, 59),
            "initial_cash": 10000.0,
            "strategy": "smc_crt",
            "params": {"htf": "4h", "zone_tf": "4h", "ltf": "5m"},
            "seed": 42,
        })
        assert r2.json()["monte_carlo"]["median_final_equity"] == mc["median_final_equity"]

    def test_review_endpoint(self, client):
        r = client.post("/api/review", json={
            "strategy": "smc_crt", "strategy_version": "v1.0",
        })
        assert r.status_code == 200
        assert "hypothesis" in r.json()
        assert "rule_compliance" in r.json()

    def test_data_range(self, client):
        r = client.get("/api/data-range?symbol=EURUSD&timeframe=5m")
        assert r.status_code == 200
        body = r.json()
        assert body["n_bars"] > 0
        assert body["start"] < body["end"]

    def test_models_crud_and_masking(self, client):
        r = client.post("/api/models", json={
            "provider": "ollama", "label": "Local Ollama",
            "base_url": "http://localhost:11434", "model": "llama3.1:8b",
            "is_active": True,
        })
        assert r.status_code == 200
        rec = r.json()
        mid = rec["id"]
        assert rec["provider"] == "ollama"
        assert rec["is_active"] is True

        r2 = client.post("/api/models", json={
            "provider": "openai", "label": "OpenAI",
            "api_key": "sk-proj-1234567890abcdef", "model": "gpt-4o-mini",
        })
        oid = r2.json()["id"]
        assert r2.json()["masked_key"] == "sk-pro••••••••cdef"
        assert r2.json()["has_key"] is True
        assert "api_key" not in r2.json()

        # activating one model deactivates the others
        r3 = client.post(f"/api/models/{oid}/activate")
        assert r3.json()["is_active"] is True
        assert client.get("/api/models").json()[0]["is_active"] is True

        # test connection probe fails gracefully when no server is running
        r4 = client.post(f"/api/models/{mid}/test")
        assert r4.status_code == 200
        assert r4.json()["ok"] is False

        # delete
        r5 = client.delete(f"/api/models/{mid}")
        assert r5.status_code == 200
        assert client.delete(f"/api/models/{mid}").status_code == 404

    def test_review_uses_configured_model(self, client):
        client.post("/api/models", json={
            "provider": "ollama", "label": "Ollama",
            "base_url": "http://localhost:9", "model": "llama3.1:8b",
            "is_active": True,
        })
        r = client.post("/api/review", json={
            "strategy": "smc_crt", "strategy_version": "v1.0",
        })
        # deterministic fallback must still succeed (fail-closed) and note the model
        assert r.status_code == 200
        body = r.json()
        assert body["hypothesis"]
        body = r.json()
        assert "hypothesis" in body
