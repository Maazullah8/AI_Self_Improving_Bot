"""Tests for the session filter (weekends only) and data resampling fixes."""
import json

import pytest

from trading_bot.core.enums import Side, Timeframe
from trading_bot.core.time_utils import utc_ts
from trading_bot.core.models import Candle
from trading_bot.data.base import MarketDataQuery
from trading_bot.data.fallback_provider import FallbackDataProvider
from trading_bot.data.jsonl_provider import JSONLDataProvider
from trading_bot.risk.manager import RiskConfig, RiskManager
from trading_bot.replay.engine import Signal


def _sym():
    from trading_bot.data.base import SymbolInfo

    return SymbolInfo(
        symbol="XAUUSD", digits=2, tick_size=0.01, point_size=0.01,
        contract_size=100, lot_min=0.01, lot_max=200.0, lot_step=0.01,
    )


def _bar(ts):
    return Candle(time=ts, open=1.10, high=1.101, low=1.099, close=1.1005,
                  volume=10, spread=1e-5)


def _signal():
    return Signal(side=Side.BUY, entry=1.1005, sl=1.098, tp=1.106, size=0.0)


class TestSessionFilter:
    def test_weekend_rejected(self):
        rm = RiskManager(RiskConfig(), symbol_info=_sym())
        sat = utc_ts(2024, 1, 6, 12, 0)  # Saturday UTC
        dec = rm.approve(_signal(), _bar(sat), 10_000, [])
        assert not dec.approved
        assert dec.reason == "session_not_allowed:weekend"

    def test_off_hours_weekday_allowed(self):
        rm = RiskManager(RiskConfig(), symbol_info=_sym())
        tue_night = utc_ts(2024, 1, 2, 22, 0)  # Tuesday 22:00 UTC -> "off"
        dec = rm.approve(_signal(), _bar(tue_night), 10_000, [])
        assert dec.approved, dec.reason

    def test_tokyo_asia_session_allowed(self):
        rm = RiskManager(RiskConfig(), symbol_info=_sym())
        tue_am = utc_ts(2024, 1, 2, 3, 0)  # Tuesday 03:00 UTC -> Asia/Tokyo
        dec = rm.approve(_signal(), _bar(tue_am), 10_000, [])
        assert dec.approved, dec.reason

    def test_explicit_restriction_still_blocks_named_sessions(self):
        rm = RiskManager(RiskConfig(allowed_sessions=["asia"]), symbol_info=_sym())
        tue_ldn = utc_ts(2024, 1, 2, 9, 0)  # Tuesday 09:00 UTC -> London
        dec = rm.approve(_signal(), _bar(tue_ldn), 10_000, [])
        assert not dec.approved
        assert "session_not_allowed" in dec.reason


def _write_jsonl(path, bars):
    with open(path, "w", encoding="utf-8") as f:
        for b in bars:
            f.write(json.dumps({
                "time": b["time"], "open": b["open"], "high": b["high"],
                "low": b["low"], "close": b["close"], "volume": b.get("volume", 10),
            }) + "\n")


@pytest.fixture
def jsonl_provider(tmp_path):
    t0 = utc_ts(2024, 1, 2, 8, 0)
    bars = [
        {"time": t0 + i * 300, "open": 1.0 + i * 0.001, "high": 1.002 + i * 0.001,
         "low": 0.998 + i * 0.001, "close": 1.001 + i * 0.001}
        for i in range(6)  # 30 minutes of 5m bars
    ]
    path = tmp_path / "XAU_5m_test.jsonl"
    _write_jsonl(path, bars)
    return JSONLDataProvider(path=path, symbol="XAUUSD", timeframe=Timeframe.M5)


class TestJsonlResample:
    def test_base_tf_returns_self(self, jsonl_provider):
        assert jsonl_provider.resample(Timeframe.M5) is jsonl_provider

    def test_resampled_15m_aggregates_three_bars(self, jsonl_provider):
        p15 = jsonl_provider.resample(Timeframe.M15)
        bars = p15.load_candles(
            MarketDataQuery(symbol="XAUUSD", timeframe=Timeframe.M15)
        )
        assert len(bars) == 2  # 30 min of 5m bars -> two 15m candles
        first = bars[0]
        base = jsonl_provider.load_candles(
            MarketDataQuery(symbol="XAUUSD", timeframe=Timeframe.M5)
        )
        assert first.open == pytest.approx(base[0].open)
        assert first.high == pytest.approx(max(b.high for b in base[:3]))
        assert first.low == pytest.approx(min(b.low for b in base[:3]))
        assert first.close == pytest.approx(base[2].close)

    def test_cannot_resample_down(self, jsonl_provider):
        with pytest.raises(ValueError):
            jsonl_provider.resample(Timeframe.M1)

    def test_fallback_chain_resamples(self, jsonl_provider):
        fb = FallbackDataProvider([jsonl_provider])
        r15 = fb.resample(Timeframe.M15)
        bars = r15.load_candles(
            MarketDataQuery(symbol="XAUUSD", timeframe=Timeframe.M15)
        )
        assert len(bars) == 2