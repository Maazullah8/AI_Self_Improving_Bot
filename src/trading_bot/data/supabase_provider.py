"""Supabase historical market-data provider.

Reads OHLCV candles from a Supabase table over the auto-generated REST API
(PostgREST). Zero extra dependencies: plain HTTP via ``urllib``.

--------------------------------------------------------------------------------
WHERE TO PUT YOUR SUPABASE LINK (credentials)
--------------------------------------------------------------------------------
Option 1 (recommended): create a ``.env`` file in the repository root:

    SUPABASE_URL=https://YOUR-PROJECT-ref.supabase.co
    SUPABASE_KEY=your-service-or-anon-key
    SUPABASE_TABLE=candles            # optional, default "candles"

Option 2: environment variables with the same names before starting the API:

    set SUPABASE_URL=https://YOUR-PROJECT-ref.supabase.co
    set SUPABASE_KEY=your-key

You find both values in the Supabase dashboard under Project Settings -> API
("Project URL" and keys). Use the anon key for read-only access.

Expected table schema (run in the Supabase SQL editor):

    create table if not exists candles (
        symbol    text        not null,
        timeframe text        not null,   -- e.g. '5m', '1h', '4h'
        time      bigint      not null,   -- epoch seconds UTC (bar open)
        open      double precision not null,
        high      double precision not null,
        low       double precision not null,
        close     double precision not null,
        volume    double precision default 0,
        spread    double precision default 0,  -- PRICE distance, see core.models
        primary key (symbol, timeframe, time)
    );

This provider is READ-ONLY. It never places orders.
"""
from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trading_bot.core.enums import Timeframe
from trading_bot.core.models import Candle, Tick, point_size_for_digits
from trading_bot.data.base import DataProvider, MarketDataQuery, SymbolInfo

_REPO_ROOT = Path(__file__).resolve().parents[3]

_DEFAULT_DIGITS = {
    "XAUUSD": 2,
    "XAGUSD": 3,
}


def load_env_file(path: Optional[Path] = None) -> dict[str, str]:
    """Load a simple KEY=VALUE .env file (no dependency on python-dotenv).

    Values may be wrapped in single/double quotes; comments (#) and blank
    lines are ignored. Already-set environment variables always win.
    """
    out: dict[str, str] = {}
    env_path = Path(path) if path else _REPO_ROOT / ".env"
    if not env_path.exists():
        return out
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                out[key] = value
    except OSError:
        return {}
    return out


class SupabaseDataProvider(DataProvider):
    """Read-only candle provider backed by a Supabase table."""

    name = "supabase"

    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        table: str = "candles",
        symbol: str = "XAUUSD",
        timeframe: Timeframe = Timeframe.M5,
        env_file: Optional[Path] = None,
    ):
        env = load_env_file(env_file)
        self.url = (
            url
            or os.environ.get("SUPABASE_URL")
            or env.get("SUPABASE_URL")
            or ""
        ).rstrip("/")
        self.key = (
            key
            or os.environ.get("SUPABASE_KEY")
            or env.get("SUPABASE_KEY")
            or ""
        )
        self.table = (
            os.environ.get("SUPABASE_TABLE")
            or env.get("SUPABASE_TABLE")
            or table
        )
        self.default_symbol = symbol
        self.default_timeframe = timeframe
        self.configured = bool(self.url and self.key)

    # ------------------------------------------------------------ transport
    @property
    def source_label(self) -> str:
        if not self.configured:
            return "Supabase (not configured)"
        # never leak the key into the UI/logs
        return f"Supabase ({self.url})"

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Accept": "application/json",
        }

    def _get(self, params: dict[str, str]) -> list[dict[str, Any]]:
        if not self.configured:
            raise RuntimeError(
                "Supabase is not configured. Add SUPABASE_URL and SUPABASE_KEY "
                "to your .env file (see src/trading_bot/data/supabase_provider.py)"
            )
        qs = urlencode(params)
        req = Request(
            f"{self.url}/rest/v1/{self.table}?{qs}",
            headers=self._headers(),
        )
        with urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if not isinstance(payload, list):
            raise RuntimeError("unexpected Supabase response (expected a JSON array)")
        return payload

    # ------------------------------------------------------------------ ETL
    @staticmethod
    def _row_to_candle(row: dict[str, Any]) -> Candle:
        t = row.get("time", row.get("ts", 0))
        try:
            t = int(float(t))
        except (TypeError, ValueError):
            t = 0
        return Candle(
            time=t,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume") or 0.0),
            spread=float(row.get("spread") or 0.0),
        )

    # ------------------------------------------------------- DataProvider
    def available_symbols(self) -> Sequence[str]:
        rows = self._get({"select": "symbol", "limit": "1000"})
        seen: list[str] = []
        for r in rows:
            s = str(r.get("symbol", ""))
            if s and s not in seen:
                seen.append(s)
        return sorted(seen)

    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        params: dict[str, str] = {
            "select": "symbol,timeframe,time,open,high,low,close,volume,spread",
            "symbol": f"eq.{query.symbol}",
            "timeframe": f"eq.{query.timeframe.value}",
            "order": "time.asc",
            "limit": "500000",
        }
        if query.start and query.end:
            # PostgREST 'and' syntax for two filters on the same column
            params["time"] = f"gte.{query.start}.AND.time.lte.{query.end}"
        elif query.start:
            params["time"] = f"gte.{query.start}"
        elif query.end:
            params["time"] = f"lte.{query.end}"
        rows = self._get(params)
        return [self._row_to_candle(r) for r in rows]

    def load_ticks(self, query: MarketDataQuery) -> Sequence[Tick]:
        return []  # candle-level history only

    def symbol_info(self, symbol: str) -> SymbolInfo:
        digits = _DEFAULT_DIGITS.get(symbol.upper(), 5)
        pt = point_size_for_digits(digits)
        return SymbolInfo(
            symbol=symbol,
            digits=digits,
            tick_size=pt,
            point_size=pt,
            contract_size=100 if symbol.upper() in ("XAUUSD", "XAGUSD") else 100_000,
            lot_min=0.01,
            lot_max=200.0,
            lot_step=0.01,
            currency="USD",
        )

    def resample(self, timeframe: Timeframe) -> "SupabaseDataProvider":
        # The table stores any timeframe explicitly, so this provider is
        # already multi-timeframe.
        return self

    def clear(self) -> None:
        pass  # stateless

    # ------------------------------------------------------------- health
    def health(self) -> dict[str, Any]:
        label = self.source_label
        if not self.configured:
            return {
                "ok": False,
                "source": self.name,
                "source_label": label,
                "error": "SUPABASE_URL / SUPABASE_KEY not set (.env)",
            }
        try:
            rows = self._get({
                "select": "time",
                "symbol": f"eq.{self.default_symbol}",
                "timeframe": f"eq.{self.default_timeframe.value}",
                "order": "time.desc",
                "limit": "1",
            })
            return {
                "ok": True,
                "source": self.name,
                "source_label": label,
                "latest_time": int(rows[0]["time"]) if rows else 0,
            }
        except Exception as exc:
            return {
                "ok": False,
                "source": self.name,
                "source_label": label,
                "error": str(exc),
            }