"""Tests for the yfinance (Yahoo Finance) data provider.

The yfinance package itself is not required: ``yf.download`` is mocked.
"""
import sys

import pandas as pd
import pytest

from trading_bot.core.enums import Timeframe
from trading_bot.data.base import MarketDataQuery
from trading_bot.data.yahoo_provider import DEFAULT_SYMBOL, YFinanceDataProvider


def _df():
    # timestamps relative to "now" so defaulted windows (trailing 365d) cover them
    now = pd.Timestamp.now(tz="UTC").floor("min")
    idx = pd.DatetimeIndex([now - pd.Timedelta(minutes=10), now - pd.Timedelta(minutes=5)])
    return pd.DataFrame(
        {
            "Open": [2050.0, 2051.0],
            "High": [2052.0, 2052.5],
            "Low": [2049.0, 2050.0],
            "Close": [2051.0, 2051.5],
            "Volume": [1000, 1200],
        },
        index=idx,
    )


class _FakeYF:
    def __init__(self, df):
        self._df = df
        self.last_args = None
        self.last_kwargs = None

    def download(self, *args, **kwargs):
        self.last_args = args
        self.last_kwargs = kwargs
        return self._df


@pytest.fixture
def fake_yf(monkeypatch):
    fake = _FakeYF(_df())
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    return fake


class TestYFinanceProvider:
    def _win(self, df):
        ts = [int(t.timestamp()) for t in df.index]
        return min(ts) - 60, max(ts) + 60

    def test_maps_xauusd_to_gc_f(self, fake_yf):
        p = YFinanceDataProvider()
        start, end = self._win(fake_yf._df)
        bars = p.load_candles(
            MarketDataQuery(
                symbol="XAUUSD", timeframe=Timeframe.M5,
                start=start, end=end,
            )
        )
        assert fake_yf.last_args[0] == "GC=F"
        assert fake_yf.last_kwargs["interval"] == "5m"
        assert len(bars) == 2
        b = bars[0]
        assert b.open == pytest.approx(2050.0)
        assert b.close == pytest.approx(2051.0)

    def test_raises_on_empty_data(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "yfinance", _FakeYF(pd.DataFrame()))
        p = YFinanceDataProvider()
        with pytest.raises(RuntimeError):
            p.load_candles(
                MarketDataQuery(symbol="XAUUSD", timeframe=Timeframe.M5)
            )

    def test_symbol_info_contract_sizes(self):
        p = YFinanceDataProvider()
        gold = p.symbol_info("XAUUSD")
        fx = p.symbol_info("EURUSD")
        assert gold.contract_size == 100
        assert gold.digits == 2
        assert fx.contract_size == 100_000

    def test_h4_resamples_from_1h(self, monkeypatch):
        # hourly bars spanning ~10h so a full 4h bucket can form
        now = pd.Timestamp.now(tz="UTC").floor("h")
        idx = pd.DatetimeIndex([now - pd.Timedelta(hours=10 - i) for i in range(10)])
        df = pd.DataFrame(
            {
                "Open": [2050.0 + i for i in range(10)],
                "High": [2052.0 + i for i in range(10)],
                "Low": [2049.0 + i for i in range(10)],
                "Close": [2051.0 + i for i in range(10)],
                "Volume": [1000] * 10,
            },
            index=idx,
        )
        fake = _FakeYF(df)
        monkeypatch.setitem(sys.modules, "yfinance", fake)
        p = YFinanceDataProvider()
        start, end = self._win(df)
        bars = p.load_candles(
            MarketDataQuery(
                symbol="XAUUSD", timeframe=Timeframe.H4,
                start=start, end=end,
            )
        )
        assert fake.last_kwargs["interval"] == "60m"  # 4h <- 1h ("60m" on Yahoo)
        assert 2 <= len(bars) <= 3  # ~10h of 1h bars -> ~2 full 4h buckets
        # buckets are 4h apart
        for a, b in zip(bars, bars[1:]):
            assert b.time - a.time == 4 * 3600

    def test_zero_window_defaults_to_trailing_year(self, fake_yf):
        p = YFinanceDataProvider()
        # start=0/end=0 must resolve to a sane trailing window instead of epoch 0
        bars = p.load_candles(
            MarketDataQuery(symbol="XAUUSD", timeframe=Timeframe.M5)
        )
        assert len(bars) == 2
        assert fake_yf.last_kwargs["start"] is not None

    def test_cached_bars(self, fake_yf):
        p = YFinanceDataProvider()
        q = MarketDataQuery(symbol="XAUUSD", timeframe=Timeframe.M5)
        p.load_candles(q)
        p.load_candles(q)
        assert fake_yf.last_kwargs  # second call served from cache
        assert len(p._cache) == 1

    def test_clear_invalidates_cache(self, fake_yf):
        p = YFinanceDataProvider()
        q = MarketDataQuery(symbol="XAUUSD", timeframe=Timeframe.M5)
        p.load_candles(q)
        p.clear()
        assert p._cache == {}

    def test_default_symbol(self):
        assert DEFAULT_SYMBOL == "XAUUSD"
