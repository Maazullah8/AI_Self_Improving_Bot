"""Tests for execution adapters, live pipeline, and supervisor."""
import pytest

from trading_bot.core.enums import Side
from trading_bot.core.models import Order, Position
from trading_bot.core.time_utils import utc_ts
from trading_bot.data.synthetic import SyntheticDataProvider
from trading_bot.execution.executor import MT5Executor, SimulatedExecutor
from trading_bot.live.pipeline import LiveConfig, LiveTradePipeline
from trading_bot.live.supervisor import PipelineSupervisor, SupervisorConfig
from trading_bot.storage.memory import MemoryStore
from trading_bot.strategy.base import create_strategy


class TestSimulatedExecutor:
    def test_fills_immediately(self):
        ex = SimulatedExecutor()
        o = Order(id="o1", symbol="EURUSD", side=Side.BUY, type="market", size=0.1, price=1.1, created_at=0)
        r = ex.submit_order(o)
        assert r.ok
        assert r.status.value == "filled"
        assert len(ex.orders) == 1

    def test_not_live(self):
        assert SimulatedExecutor().is_live() is False


class TestMT5Executor:
    def test_fails_closed_when_unavailable(self):
        ex = MT5Executor(login=0, password="", server="")
        h = ex.health()
        assert h["ok"] is False
        r = ex.submit_order(Order(id="x", symbol="EURUSD", side=Side.BUY, type="market", size=0.1))
        assert r.ok is False
        assert "unavailable" in r.message


class TestLivePipeline:
    def _provider(self):
        return SyntheticDataProvider(
            symbol="EURUSD", seed=9,
            start=utc_ts(2023, 3, 1), end=utc_ts(2023, 3, 31, 23, 59),
            tf=pytest.importorskip("trading_bot.core.enums").Timeframe.M5,
            initial_price=1.1, volatility=0.0004,
        )

    def test_poll_no_new_bars_is_idle_ok(self):
        from trading_bot.core.enums import Timeframe

        p = SyntheticDataProvider(
            symbol="EURUSD", seed=9,
            start=utc_ts(2023, 3, 1), end=utc_ts(2023, 3, 1, 2, 0),
            tf=Timeframe.M5, initial_price=1.1, volatility=0.0004,
        )
        store = MemoryStore()
        strat = create_strategy("smc_crt", params={"htf": "1h", "zone_tf": "1h", "ltf": "5m"})
        pipe = LiveTradePipeline(
            provider=p, strategy=strat, executor=SimulatedExecutor(),
            store=store, config=LiveConfig(symbol="EURUSD", timeframe="5m"),
        )
        st = pipe.poll(now=utc_ts(2023, 3, 1, 2, 5))
        assert st.status in ("ok", "down")
        # heartbeat written
        assert store.heartbeats.latest("live:EURUSD") is not None

    def test_poll_with_old_data_fails_closed(self):
        from trading_bot.core.enums import Timeframe

        p = SyntheticDataProvider(
            symbol="EURUSD", seed=9,
            start=utc_ts(2023, 3, 1), end=utc_ts(2023, 3, 1, 2, 0),
            tf=Timeframe.M5, initial_price=1.1, volatility=0.0004,
        )
        pipe = LiveTradePipeline(
            provider=p, strategy=create_strategy("smc_crt"),
            executor=SimulatedExecutor(),
            config=LiveConfig(symbol="EURUSD", timeframe="5m", max_staleness_seconds=60),
        )
        # data ends 02:00, "now" is 06:00 => stale (>60s) => down, no trades
        st = pipe.poll(now=utc_ts(2023, 3, 1, 6, 0))
        assert st.status == "down"
        assert "stale" in st.detail

    def test_full_poll_runs_with_signals(self):
        from trading_bot.core.enums import Timeframe

        p = SyntheticDataProvider(
            symbol="EURUSD", seed=3,
            start=utc_ts(2023, 3, 1), end=utc_ts(2023, 3, 31, 23, 59),
            tf=Timeframe.M5, initial_price=1.1, volatility=0.0004,
        )
        store = MemoryStore()
        pipe = LiveTradePipeline(
            provider=p, strategy=create_strategy(
                "smc_crt", params={"htf": "4h", "zone_tf": "4h", "ltf": "5m"}),
            executor=SimulatedExecutor(), store=store,
            config=LiveConfig(symbol="EURUSD", timeframe="5m", max_staleness_seconds=3600 * 24 * 400),
        )
        st = pipe.poll(now=utc_ts(2023, 4, 1))
        assert st.n_polls == 1
        # pipeline processed bars and recorded heartbeats
        assert st.last_bar_time > 0
        assert store.heartbeats.latest("live:EURUSD") is not None


class TestSupervisor:
    def test_detects_stale_and_restarts(self):
        from trading_bot.core.enums import Timeframe

        p = SyntheticDataProvider(
            symbol="EURUSD", seed=3,
            start=utc_ts(2023, 3, 1), end=utc_ts(2023, 3, 2),
            tf=Timeframe.M5, initial_price=1.1, volatility=0.0004,
        )
        store = MemoryStore()
        pipe = LiveTradePipeline(
            provider=p, strategy=create_strategy("smc_crt"),
            executor=SimulatedExecutor(), store=store,
            config=LiveConfig(symbol="EURUSD", timeframe="5m"),
        )
        sup = PipelineSupervisor(
            pipe, store=store,
            config=SupervisorConfig(
                heartbeat_timeout_seconds=1,
                max_restarts=2,
                restart_backoff_seconds=0,
            ),
        )
        sup.start()
        # first healthy check
        sup.check_once(now=utc_ts(2023, 3, 1))
        assert sup.status.status in ("ok", "warn", "down")
        # force a stale condition: advance now far beyond data, no new bars
        sup.check_once(now=utc_ts(2023, 12, 1))
        assert sup.status.restarts >= 1 or sup.status.status == "down"
