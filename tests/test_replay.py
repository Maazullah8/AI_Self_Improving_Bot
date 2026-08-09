"""Tests for the replay engine: zero-lookahead, SL/TP, slippage, determinism."""
import pytest

from trading_bot.core.enums import ExitReason, OrderType, Side, Timeframe
from trading_bot.core.models import Candle
from trading_bot.core.time_utils import utc_ts
from trading_bot.data.base import SymbolInfo
from trading_bot.replay.engine import (
    Context,
    DummyRiskManager,
    ExecutionConfig,
    ReplayConfig,
    ReplayEngine,
    Signal,
)


def _sym(digits=5):
    return SymbolInfo(
        symbol="EURUSD", digits=digits, tick_size=1e-5, point_size=1e-5,
        contract_size=100_000, lot_min=0.01, lot_max=100.0, lot_step=0.01,
    )


def _bars(closes, opens=None, highs=None, lows=None, spread=1e-4):
    opens = opens or closes
    out = []
    t = utc_ts(2024, 1, 1, 8, 0, 0)
    for i, c in enumerate(closes):
        o = opens[i] if isinstance(opens, list) else opens
        h = highs[i] if highs else max(o, c) + 1e-4
        l = lows[i] if lows else min(o, c) - 1e-4
        out.append(Candle(time=t + i * 60, open=o, high=h, low=l, close=c, volume=10, spread=spread))
    return out


class _LongStrategy:
    """Buys on first bar at its close, SL/TP fixed."""

    def __init__(self, entry_idx=0, sl=0.0, tp=0.0, size=1.0):
        self.entry_idx = entry_idx
        self.sl = sl
        self.tp = tp
        self.size = size

    def on_bar(self, ctx: Context):
        if ctx.index == self.entry_idx:
            bar = ctx.current
            return ctx.signal(
                side=Side.BUY, entry=bar.close, sl=self.sl or bar.close - 0.001,
                tp=self.tp or bar.close + 0.002, size=self.size,
            )
        return None


class _ShortStrategy:
    def on_bar(self, ctx: Context):
        if ctx.index == 0:
            bar = ctx.current
            return ctx.signal(
                side=Side.SELL, entry=bar.close, sl=bar.close + 0.001,
                tp=bar.close - 0.002, size=1.0,
            )
        return None


class _NeverTrade:
    def on_bar(self, ctx: Context):
        return None


def _run(bars, strategy, **cfg):
    rc = ReplayConfig(symbol_info=_sym(), execution=ExecutionConfig(**cfg))
    eng = ReplayEngine(bars, rc, risk_manager=DummyRiskManager())
    return eng.run(strategy), eng


class TestZeroLookahead:
    def test_strategy_sees_only_past(self):
        bars = _bars([1.10, 1.11, 1.12, 1.13])
        seen = {}

        class Spy:
            def on_bar(self, ctx):
                seen[ctx.index] = [b.close for b in ctx.bars]
                return None

        _run(bars, Spy())
        assert seen[0] == [1.10]
        assert seen[1] == [1.10, 1.11]
        assert seen[3] == [1.10, 1.11, 1.12, 1.13]

    def test_strategy_cannot_see_future_bars(self):
        bars = _bars([1.10, 1.11, 1.12, 1.13])
        max_seen = {}

        class Spy:
            def on_bar(self, ctx):
                max_seen[ctx.index] = len(ctx.bars)
                return None

        _run(bars, Spy())
        for i in range(4):
            assert max_seen[i] == i + 1


class TestFills:
    def test_buy_fill_at_ask_with_spread(self):
        bars = _bars([1.10], spread=1e-4)
        res, eng = _run(bars, _LongStrategy(0), slippage_points=0)
        fill = eng.fills[0]
        assert fill.price == pytest.approx(1.10 + 1e-4 / 2)  # ask = mid + half spread

    def test_sell_fill_at_bid(self):
        bars = _bars([1.10], spread=1e-4)
        res, eng = _run(bars, _ShortStrategy(), slippage_points=0)
        assert eng.fills[0].price == pytest.approx(1.10 - 1e-4 / 2)

    def test_slippage_against_buyer(self):
        bars = _bars([1.10], spread=1e-4)
        res, eng = _run(bars, _LongStrategy(0), slippage_points=3)  # 3 points = 3e-5
        assert eng.fills[0].price > 1.10 + 1e-4 / 2

    def test_slippage_deterministic_with_seed(self):
        bars = _bars([1.10] * 3, spread=1e-4)
        prices = []
        for seed in (42, 42):
            rc = ReplayConfig(
                symbol_info=_sym(),
                execution=ExecutionConfig(slippage_points=5),
                seed=seed,
            )
            eng = ReplayEngine(bars, rc, risk_manager=DummyRiskManager())
            eng.run(_LongStrategy(0))
            prices.append(eng.fills[0].price)
        assert prices[0] == prices[1]


class TestSLTP:
    def test_long_sl_hit(self):
        # bar1 goes below SL
        bars = _bars(
            closes=[1.10, 1.095],
            lows=[1.099, 1.091],  # below SL 1.099
            highs=[1.101, 1.097],
        )
        res, _ = _run(bars, _LongStrategy(0, sl=1.099, tp=1.12))
        assert len(res.trades) == 1
        t = res.trades[0]
        assert t.exit_reason == ExitReason.SL
        assert t.exit_price == pytest.approx(1.099)
        assert t.r < 0

    def test_long_tp_hit(self):
        bars = _bars(closes=[1.10, 1.125], highs=[1.101, 1.126], lows=[1.099, 1.120])
        res, _ = _run(bars, _LongStrategy(0, sl=1.09, tp=1.12))
        t = res.trades[0]
        assert t.exit_reason == ExitReason.TP
        assert t.exit_price == pytest.approx(1.12)
        assert t.r > 0

    def test_same_bar_sl_tp_conservative_first(self):
        # bar hits both SL and TP; conservative => SL first
        bars = _bars(closes=[1.10, 1.10], lows=[1.099, 1.08], highs=[1.101, 1.15])
        res, _ = _run(bars, _LongStrategy(0, sl=1.09, tp=1.14))
        assert res.trades[0].exit_reason == ExitReason.SL

    def test_same_bar_optimistic(self):
        bars = _bars(closes=[1.10, 1.10], lows=[1.099, 1.08], highs=[1.101, 1.15])
        res, _ = _run(bars, _LongStrategy(0, sl=1.09, tp=1.14), optimistic_intrabar=True)
        assert res.trades[0].exit_reason == ExitReason.TP

    def test_short_sl_hit(self):
        bars = _bars(closes=[1.10, 1.11], lows=[1.099, 1.105], highs=[1.101, 1.115])
        res, _ = _run(bars, _ShortStrategy())
        assert res.trades[0].exit_reason == ExitReason.SL

    def test_short_tp_hit(self):
        bars = _bars(closes=[1.10, 1.085], lows=[1.099, 1.08], highs=[1.101, 1.09])
        res, _ = _run(bars, _ShortStrategy())
        assert res.trades[0].exit_reason == ExitReason.TP


class TestDeterminism:
    def test_identical_runs_identical(self):
        bars = _bars([1.10, 1.11, 1.09, 1.12, 1.08, 1.13], spread=1e-4)

        def run():
            rc = ReplayConfig(symbol_info=_sym(), execution=ExecutionConfig(slippage_points=2))
            eng = ReplayEngine(bars, rc, risk_manager=DummyRiskManager())
            res = eng.run(_LongStrategy(0, sl=1.09, tp=1.13))
            return [(t.exit_price, t.r) for t in res.trades]

        assert run() == run()

    def test_no_trades_when_no_signal(self):
        bars = _bars([1.10, 1.11])
        res, _ = _run(bars, _NeverTrade())
        assert len(res.trades) == 0


class TestEquity:
    def test_initial_equity(self):
        bars = _bars([1.10, 1.11, 1.12, 1.13])
        res, _ = _run(bars, _LongStrategy(0, sl=1.09, tp=1.12))
        assert res.equity_curve[0].equity == pytest.approx(10_000.0)

    def test_final_equity_reflects_pnl(self):
        bars = _bars(closes=[1.10, 1.125], highs=[1.101, 1.126], lows=[1.099, 1.120])
        res, _ = _run(bars, _LongStrategy(0, sl=1.09, tp=1.12))
        # TP at 1.12 from entry ~1.10005, size 1.0 => ~+0.02
        assert res.final_equity == pytest.approx(10_000.0 + (1.12 - 1.10005), abs=1e-3)


class TestNoBrokerAccess:
    def test_engine_never_imports_mt5(self):
        import sys

        assert "MetaTrader5" not in sys.modules or not sys.modules["MetaTrader5"]
        bars = _bars([1.10, 1.11])
        _run(bars, _NeverTrade())
