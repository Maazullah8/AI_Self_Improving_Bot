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

    def test_review_endpoint(self, client):
        r = client.post("/api/review", json={
            "strategy": "smc_crt", "strategy_version": "v1.0",
        })
        assert r.status_code == 200
        body = r.json()
        assert "hypothesis" in body
