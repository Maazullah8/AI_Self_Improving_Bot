"""End-to-end tests: synthetic data -> BacktestRunner -> journal -> metrics."""
import pytest

from trading_bot.backtest.metrics import compute_metrics
from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
from trading_bot.core.enums import Timeframe
from trading_bot.core.time_utils import utc_ts
from trading_bot.data.synthetic import SyntheticDataProvider
from trading_bot.journal.journal import Journal
from trading_bot.strategy.base import create_strategy
from trading_bot.strategy.smc.strategy import SMCParams  # noqa: F401


def _provider():
    return SyntheticDataProvider(
        symbol="EURUSD",
        seed=7,
        start=utc_ts(2023, 1, 1),
        end=utc_ts(2023, 3, 31, 23, 59),
        tf=Timeframe.M5,
        initial_price=1.1000,
        volatility=0.0004,
        drift=0.0,
        trend_cycles=8,
    )


class TestBacktestRunner:
    def test_full_run(self):
        provider = _provider()
        journal = Journal()
        runner = BacktestRunner(provider, journal=journal)
        strat = create_strategy(
            "smc_crt",
            params={
                "htf": "4h", "zone_tf": "4h", "ltf": "5m",
                "zone_lookback": 150, "bias_lookback": 150,
            },
        )
        cfg = BacktestConfig(
            symbol="EURUSD",
            timeframe=Timeframe.M5,
            initial_cash=10_000.0,
            seed=42,
        )
        res = runner.run(strat, cfg)

        assert res.n_bars > 0
        assert res.n_bars == len(provider.load_candles(
            __import__("trading_bot.data.base", fromlist=["MarketDataQuery"]).MarketDataQuery(
                symbol="EURUSD", timeframe=Timeframe.M5
            )
        ))
        assert res.strategy_version == strat.version
        assert res.final_equity > 0
        assert isinstance(res.metrics, dict)
        assert "win_rate" in res.metrics
        assert res.metrics["n_trades"] == res.n_trades
        assert res.equity_curve
        # equity curve points count equals bars processed
        assert len(res.equity_curve) == res.n_bars

    def test_journal_records_match_trades(self):
        provider = _provider()
        journal = Journal()
        runner = BacktestRunner(provider, journal=journal)
        strat = create_strategy(
            "smc_crt",
            params={
                "htf": "4h", "zone_tf": "4h", "ltf": "5m",
                "zone_lookback": 150, "bias_lookback": 150,
            },
        )
        cfg = BacktestConfig(symbol="EURUSD", timeframe=Timeframe.M5, seed=42)
        res = runner.run(strat, cfg)
        assert len(journal.records()) == res.n_trades
        for rec in journal.records():
            assert rec.strategy_version == strat.version
            assert rec.symbol == "EURUSD"
            assert rec.entry_time < rec.exit_time
            # setup context populated by SMC strategy
            assert rec.zone_type != ""


class TestMetrics:
    def test_empty(self):
        m = compute_metrics([{"time": 0, "equity": 1000}], [])
        assert m["n_trades"] == 0
        assert m["win_rate"] == 0.0
        assert m["total_return"] == 0.0

    def test_known_numbers(self):
        from trading_bot.core.enums import ExitReason
        from trading_bot.core.models import TradeRecord

        eq = [
            {"time": utc_ts(2024, 1, 1), "equity": 1000},
            {"time": utc_ts(2024, 1, 2), "equity": 1050},
            {"time": utc_ts(2024, 1, 3), "equity": 1010},
        ]
        trades = [
            TradeRecord(pnl=50, r=0.5, exit_reason=ExitReason.TP, duration_seconds=3600),
            TradeRecord(pnl=-40, r=-1.0, exit_reason=ExitReason.SL, duration_seconds=7200),
        ]
        m = compute_metrics(eq, trades)
        assert m["n_trades"] == 2
        assert m["win_rate"] == 50.0
        assert m["profit_factor"] == pytest.approx(1.25)
        assert m["expectancy_r"] == pytest.approx(-0.25)
        assert m["max_drawdown_currency"] == pytest.approx(40.0)
        assert m["max_drawdown_pct"] == pytest.approx(40 / 1050 * 100, rel=1e-3)
        assert m["total_return"] == pytest.approx(10.0)
        assert m["exit_reason_counts"] == {"tp": 1, "sl": 1}

    def test_recovery_factor(self):
        from trading_bot.core.enums import ExitReason
        from trading_bot.core.models import TradeRecord

        eq = [
            {"time": 0, "equity": 1000},
            {"time": 1, "equity": 900},
            {"time": 2, "equity": 1100},
        ]
        m = compute_metrics(eq, [TradeRecord(pnl=100, r=1.0, exit_reason=ExitReason.TP, duration_seconds=1)])
        assert m["max_drawdown_currency"] == pytest.approx(100.0)
        assert m["recovery_factor"] == pytest.approx(1.0)
