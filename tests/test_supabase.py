"""Tests for the Supabase data provider (no network required)."""
from pathlib import Path

import pytest

from trading_bot.core.enums import Timeframe
from trading_bot.data.base import MarketDataQuery
from trading_bot.data.supabase_provider import (
    SupabaseDataProvider,
    load_env_file,
)


class TestEnvFile:
    def test_parses_key_values(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text(
            "# comment\n"
            "SUPABASE_URL=https://abc.supabase.co\n"
            "\n"
            "SUPABASE_KEY='secret-key'\n",
            encoding="utf-8",
        )
        out = load_env_file(env)
        assert out["SUPABASE_URL"] == "https://abc.supabase.co"
        assert out["SUPABASE_KEY"] == "secret-key"

    def test_missing_file_is_empty(self, tmp_path: Path):
        assert load_env_file(tmp_path / "nope.env") == {}


class TestSupabaseProvider:
    def test_not_configured_without_credentials(self, tmp_path: Path):
        p = SupabaseDataProvider(env_file=tmp_path / ".env")
        assert not p.configured
        h = p.health()
        assert not h["ok"]
        assert "not configured" in h["error"].lower() or "SUPABASE_URL" in h["error"]

    def test_load_candles_requires_configuration(self, tmp_path: Path):
        p = SupabaseDataProvider(env_file=tmp_path / ".env")
        with pytest.raises(RuntimeError):
            p.load_candles(
                MarketDataQuery(symbol="XAUUSD", timeframe=Timeframe.M5)
            )

    def test_configured_from_explicit_args(self):
        p = SupabaseDataProvider(url="https://abc.supabase.co/", key="k3y")
        assert p.configured
        assert p.url == "https://abc.supabase.co"  # trailing slash stripped

    def test_query_filters_built(self, monkeypatch):
        p = SupabaseDataProvider(url="https://abc.supabase.co", key="k")
        captured = {}

        def fake_get(params):
            captured.update(params)
            return [
                {
                    "symbol": "XAUUSD",
                    "timeframe": "5m",
                    "time": 1000,
                    "open": 1.0,
                    "high": 2.0,
                    "low": 0.5,
                    "close": 1.5,
                    "volume": 10,
                    "spread": 0.01,
                }
            ]

        monkeypatch.setattr(p, "_get", fake_get)
        bars = p.load_candles(
            MarketDataQuery(symbol="XAUUSD", timeframe=Timeframe.M5, start=100, end=200)
        )
        # filters + ordering
        assert captured["symbol"] == "eq.XAUUSD"
        assert captured["timeframe"] == "eq.5m"
        assert captured["order"] == "time.asc"
        assert "gte.100" in captured["time"] and "lte.200" in captured["time"]
        # candle mapping
        assert bars[0].time == 1000
        assert bars[0].open == pytest.approx(1.0)
        assert bars[0].spread == pytest.approx(0.01)

    def test_resample_returns_self(self):
        p = SupabaseDataProvider(url="https://abc.supabase.co", key="k")
        assert p.resample(Timeframe.H4) is p