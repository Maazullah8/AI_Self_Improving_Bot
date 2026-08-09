"""Tests for the data layer: resampling, synthetic provider, file provider."""
import datetime as dt

import numpy as np
import pytest

from trading_bot.core.enums import Timeframe
from trading_bot.core.models import Candle, Tick
from trading_bot.core.time_utils import bar_open_time, utc_ts
from trading_bot.data.base import MarketDataQuery
from trading_bot.data.file_provider import FileDataProvider
from trading_bot.data.resample import aggregate_ticks_to_candles, resample_candles
from trading_bot.data.synthetic import SyntheticDataProvider, generate_csv


class TestResample:
    def test_aggregate_ticks_to_1m(self):
        base = utc_ts(2024, 1, 2, 10, 0, 0)
        ticks = [
            Tick(time=base, bid=1.1000, ask=1.1001),
            Tick(time=base + 1, bid=1.1002, ask=1.1003),
            Tick(time=base + 2, bid=1.1001, ask=1.1002),
            Tick(time=base + 60, bid=1.1004, ask=1.1005),
            Tick(time=base + 61, bid=1.1006, ask=1.1007),
        ]
        bars = aggregate_ticks_to_candles(ticks, Timeframe.M1)
        assert len(bars) == 2
        assert bars[0].open == pytest.approx(1.10005)
        assert bars[0].high == pytest.approx(1.10025)
        assert bars[0].low == pytest.approx(1.10005)
        assert bars[0].close == pytest.approx(1.10015)
        assert bars[1].open == pytest.approx(1.10045)
        assert bars[1].close == pytest.approx(1.10065)

    def test_resample_1m_to_5m(self):
        base = utc_ts(2024, 1, 2, 10, 0, 0)
        bars = [
            Candle(time=base, open=1.0, high=1.1, low=0.9, close=1.05),
            Candle(time=base + 60, open=1.05, high=1.15, low=1.0, close=1.12),
            Candle(time=base + 120, open=1.12, high=1.2, low=1.1, close=1.18),
            Candle(time=base + 180, open=1.18, high=1.25, low=1.15, close=1.22),
            Candle(time=base + 240, open=1.22, high=1.3, low=1.2, close=1.28),
        ]
        out = resample_candles(bars, Timeframe.M5)
        assert len(out) == 1
        assert out[0].time == base
        assert out[0].open == pytest.approx(1.0)
        assert out[0].high == pytest.approx(1.3)
        assert out[0].low == pytest.approx(0.9)
        assert out[0].close == pytest.approx(1.28)

    def test_resample_crosses_5m_boundary(self):
        base = utc_ts(2024, 1, 2, 10, 3, 0)
        bars = [
            Candle(time=base, open=1.0, high=1.1, low=0.9, close=1.05),
            Candle(time=base + 120, open=1.05, high=1.2, low=1.0, close=1.15),
        ]
        out = resample_candles(bars, Timeframe.M5)
        assert len(out) == 2  # one at 10:00, one at 10:05

    def test_weekly_alignment_monday(self):
        # 2024-01-03 is Wednesday -> weekly bar opens Monday 2024-01-01
        ts = utc_ts(2024, 1, 3, 15, 30)
        assert bar_open_time(ts, Timeframe.W1) == utc_ts(2024, 1, 1)

    def test_monthly_alignment(self):
        ts = utc_ts(2024, 3, 27, 15, 30)
        assert bar_open_time(ts, Timeframe.MN) == utc_ts(2024, 3, 1)


class TestSynthetic:
    def test_deterministic(self):
        a = SyntheticDataProvider(seed=7)
        b = SyntheticDataProvider(seed=7)
        ca = a.load_candles(MarketDataQuery(symbol="EURUSD", timeframe=Timeframe.H1))
        cb = b.load_candles(MarketDataQuery(symbol="EURUSD", timeframe=Timeframe.H1))
        assert [c.open for c in ca] == [c.open for c in cb]
        assert len(ca) > 100

    def test_ohlc_valid(self):
        p = SyntheticDataProvider(seed=1)
        bars = p.load_candles(MarketDataQuery(symbol="EURUSD", timeframe=Timeframe.H1))
        for b in bars:
            assert b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
            assert b.low <= b.high

    def test_ticks_within_bars(self):
        p = SyntheticDataProvider(seed=3)
        bars = p.load_candles(MarketDataQuery(symbol="EURUSD", timeframe=Timeframe.H1))
        ticks = p.load_ticks(MarketDataQuery(symbol="EURUSD", timeframe=Timeframe.H1))
        assert len(ticks) >= len(bars)


class TestFileProvider:
    def test_csv_roundtrip(self, tmp_path):
        import os

        p = tmp_path / "data"
        p.mkdir()
        csv_path = p / "EURUSD.csv"
        generate_csv(str(csv_path), seed=42, tf=Timeframe.H4)
        fp = FileDataProvider(str(p), symbol="EURUSD", timeframe=Timeframe.H4)
        bars = fp.load_candles(MarketDataQuery(symbol="EURUSD", timeframe=Timeframe.H4))
        assert len(bars) > 0
        for b in bars:
            assert b.low <= b.high
        info = fp.symbol_info("EURUSD")
        assert info.digits == 5
