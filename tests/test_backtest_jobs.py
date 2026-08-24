"""Tests for cancellable backtests, live progress and async job API."""
import time

import pytest

from trading_bot.core.enums import Side, Timeframe
from trading_bot.core.time_utils import utc_ts
from trading_bot.data.synthetic import SyntheticDataProvider
from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
from trading_bot.replay.engine import ReplayConfig, ReplayEngine


def _sym():
    from trading_bot.data.base import SymbolInfo

    return SymbolInfo(
        symbol="EURUSD", digits=5, tick_size=1e-5, point_size=1e-5,
        contract_size=100_000, lot_min=0.01, lot_max=200.0, lot_step=0.01,
    )


def _bars(n=60):
    t0 = utc_ts(2024, 1, 2, 8, 0)
    return [
        Candle_i
        for Candle_i in (
            __import__("trading_bot.core.models", fromlist=["Candle"]).Candle(
                time=t0 + i * 300,
                open=1.10,
                high=1.101 + i * 1e-4,
                low=1.099,
                close=1.10 + i * 1e-4,
                volume=10,
                spread=1e-5,
            )
            for i in range(n)
        )
    ]


class _BuyOnce:
    name = "test_buy_once"
    version = "t1"

    @staticmethod
    def get_params():
        return {}

    def on_bar(self, ctx):
        if ctx.index == 1:
            bar = ctx.current
            return ctx.signal(
                side=Side.BUY, entry=bar.close,
                sl=round(bar.close * 0.999, 5),
                tp=round(bar.close * 1.002, 5),
                size=0,
            )
        return None


class TestEngineCancel:
    def test_cancel_stops_early_and_flattens(self):
        bars = _bars(60)
        eng = ReplayEngine(
            bars, ReplayConfig(symbol_info=_sym(), initial_cash=10_000)
        )
        calls = {"n": 0}

        def cancel_after_six():
            calls["n"] += 1
            return calls["n"] > 6

        res = eng.run(_BuyOnce(), cancel_check=cancel_after_six)
        assert eng.cancelled is True
        # partial run: fewer equity points than bars
        assert 0 < len(res.equity_curve) < len(bars)
        # all positions were flattened at cancellation
        assert all(p.status.value != "open" for p in eng.positions)

    def test_no_cancel_runs_everything(self):
        bars = _bars(40)
        eng = ReplayEngine(
            bars, ReplayConfig(symbol_info=_sym(), initial_cash=10_000)
        )
        res = eng.run(_BuyOnce())
        assert eng.cancelled is False
        assert len(res.equity_curve) == len(bars)


class TestRunnerProgressMeta:
    def test_progress_callback_and_meta(self):
        p = SyntheticDataProvider(
            symbol="EURUSD", seed=3,
            start=utc_ts(2023, 1, 1), end=utc_ts(2023, 1, 20, 23, 59),
            tf=Timeframe.M5, initial_price=1.10, volatility=0.0005,
        )
        runner = BacktestRunner(p)
        cfg = BacktestConfig(
            symbol="EURUSD", timeframe=Timeframe.M5,
            start=utc_ts(2023, 1, 1), end=utc_ts(2023, 1, 20, 23, 59),
            initial_cash=10_000.0, seed=1,
        )
        snaps = []
        res = runner.run(
            _BuyOnce(), cfg,
            on_progress=lambda s: snaps.append(s),
            progress_every=100,
        )
        assert len(snaps) > 0
        assert set(snaps[0].keys()) >= {"bar_index", "n_bars", "time", "equity", "n_trades"}
        assert res.meta.get("cancelled") is False


@pytest.mark.slow
class TestAsyncJobApi:
    def _client(self):
        from fastapi.testclient import TestClient

        from trading_bot.api.app import make_app
        from trading_bot.storage.memory import MemoryStore

        p = SyntheticDataProvider(
            symbol="EURUSD", seed=7,
            start=utc_ts(2023, 1, 1), end=utc_ts(2023, 1, 31, 23, 59),
            tf=Timeframe.M5, initial_price=1.10, volatility=0.0005,
        )
        app = make_app(store=MemoryStore(), provider=p)
        return TestClient(app)

    def test_async_job_completes(self):
        client = self._client()
        r = client.post("/api/backtest/async", json={
            "symbol": "EURUSD", "timeframe": "5m",
            "start": utc_ts(2023, 1, 1), "end": utc_ts(2023, 1, 31, 23, 59),
            "initial_cash": 10000.0, "strategy": "smc_crt",
            "params": {"htf": "4h", "zone_tf": "4h", "ltf": "5m"},
            "seed": 42,
        })
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        deadline = time.time() + 120
        status = None
        while time.time() < deadline:
            status = client.get(f"/api/backtest/job/{job_id}").json()
            if status["status"] != "running":
                break
            time.sleep(0.3)
        assert status["status"] == "done", status
        assert status["result"] is not None
        assert status["result"]["n_bars"] > 0

    def test_unknown_job_404(self):
        client = self._client()
        assert client.get("/api/backtest/job/nope").status_code == 404
        assert client.post("/api/backtest/job/nope/cancel").status_code == 404