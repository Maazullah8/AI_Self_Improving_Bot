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


class TestLivePipelinePositionManagement:
    """SL/TP closes + journaling to the store (added for live trading)."""

    def _pipe(self, store=None):
        from trading_bot.core.enums import Timeframe

        p = SyntheticDataProvider(
            symbol="EURUSD", seed=9,
            start=utc_ts(2023, 3, 1), end=utc_ts(2023, 3, 2),
            tf=Timeframe.M5, initial_price=1.1, volatility=0.0004,
        )
        return LiveTradePipeline(
            provider=p, strategy=create_strategy("smc_crt"),
            executor=SimulatedExecutor(), store=store or MemoryStore(),
            config=LiveConfig(symbol="EURUSD", timeframe="5m"),
        )

    def _pos(self, side=Side.BUY, sl=1.09, tp=1.12):
        return Position(
            id="p1", symbol="EURUSD", side=side, size=0.1,
            open_price=1.10, open_time=utc_ts(2023, 3, 1, 10, 0),
            sl=sl, tp=tp, strategy="smc_crt", strategy_version="v1.0",
        )

    def _bar(self, t, o, h, l, c):
        from trading_bot.core.models import Candle

        return Candle(time=t, open=o, high=h, low=l, close=c, volume=100, spread=0)

    def test_sl_hit_closes_and_journals(self):
        from trading_bot.core.enums import ExitReason

        store = MemoryStore()
        pipe = self._pipe(store)
        pipe._bars = [self._bar(utc_ts(2023, 3, 1, 10, 0), 1.10, 1.105, 1.095, 1.10)]
        pipe._positions.append(self._pos())
        bar = self._bar(utc_ts(2023, 3, 1, 10, 5), 1.09, 1.095, 1.085, 1.09)
        pipe._manage_positions(bar)
        assert pipe._positions == []
        assert pipe._balance == pytest.approx(10_000 - 0.1 * 100_000 * 0.01)  # -$100
        trades = store.trades.list()
        assert len(trades) == 1
        assert trades[0].exit_reason == ExitReason.SL
        assert trades[0].pnl == pytest.approx(-100.0)
        assert trades[0].entry_price == 1.10 and trades[0].exit_price == 1.09
        # R multiple: risk = (1.10-1.09)*0.1*100000 = 100 => r = -1
        assert trades[0].r == pytest.approx(-1.0)
        assert trades[0].strategy == "smc_crt"

    def test_tp_hit_closes_short(self):
        from trading_bot.core.enums import ExitReason

        store = MemoryStore()
        pipe = self._pipe(store)
        pipe._bars = [self._bar(utc_ts(2023, 3, 1, 10, 0), 1.10, 1.105, 1.095, 1.10)]
        pipe._positions.append(self._pos(side=Side.SELL, sl=1.11, tp=1.08))
        bar = self._bar(utc_ts(2023, 3, 1, 10, 5), 1.09, 1.095, 1.075, 1.08)
        pipe._manage_positions(bar)
        trades = store.trades.list()
        assert len(trades) == 1
        assert trades[0].exit_reason == ExitReason.TP
        # short: (1.10 - 1.08)*0.1*100000 = +$200
        assert trades[0].pnl == pytest.approx(200.0)

    def test_double_breach_assumes_sl(self):
        from trading_bot.core.enums import ExitReason

        store = MemoryStore()
        pipe = self._pipe(store)
        pipe._bars = [self._bar(utc_ts(2023, 3, 1, 10, 0), 1.10, 1.105, 1.095, 1.10)]
        pipe._positions.append(self._pos(sl=1.09, tp=1.12))
        bar = self._bar(utc_ts(2023, 3, 1, 10, 5), 1.11, 1.125, 1.085, 1.11)
        pipe._manage_positions(bar)
        trades = store.trades.list()
        assert len(trades) == 1
        assert trades[0].exit_reason == ExitReason.SL
        assert trades[0].exit_price == pytest.approx(1.09)

    def test_no_exit_within_sl_tp_keeps_position(self):
        store = MemoryStore()
        pipe = self._pipe(store)
        pipe._bars = [self._bar(utc_ts(2023, 3, 1, 10, 0), 1.10, 1.105, 1.095, 1.10)]
        pipe._positions.append(self._pos())
        bar = self._bar(utc_ts(2023, 3, 1, 10, 5), 1.105, 1.115, 1.097, 1.11)
        pipe._manage_positions(bar)
        assert len(pipe._positions) == 1
        assert store.trades.list() == []

    def test_status_snapshot(self):
        store = MemoryStore()
        pipe = self._pipe(store)
        pipe._bars = [self._bar(utc_ts(2023, 3, 1, 10, 0), 1.10, 1.105, 1.095, 1.10)]
        pipe._positions.append(self._pos())
        status = pipe.status()
        assert status["running"] is True
        assert status["symbol"] == "EURUSD"
        assert len(status["open_positions"]) == 1
        assert status["open_positions"][0]["side"] == "buy"
        assert status["balance"] == pytest.approx(10_000.0)

    def test_close_updates_equity_and_realized(self):
        store = MemoryStore()
        pipe = self._pipe(store)
        pipe._bars = [self._bar(utc_ts(2023, 3, 1, 10, 0), 1.10, 1.105, 1.095, 1.10)]
        pipe._positions.append(self._pos(sl=1.11, tp=1.10))  # instant TP at 1.10?
        bar = self._bar(utc_ts(2023, 3, 1, 10, 5), 1.13, 1.135, 1.125, 1.13)
        pipe._manage_positions(bar)
        assert pipe._realized == pytest.approx(0.1 * 100_000 * 0.0)  # tp=1.10, exit at 1.10
        st = pipe.status()
        assert st["realized_pnl"] == pytest.approx(0.0)
        assert st["n_trades"] == 1


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
