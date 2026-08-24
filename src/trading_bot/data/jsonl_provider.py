"""JSONL historical market-data provider.

Reads historical OHLCV candles from a JSON Lines file and converts them
into the unified Candle model used throughout the trading bot.

Primary use:
    - Long-range backtesting
    - Historical fallback when MT5 does not have enough history

This provider is READ-ONLY.
It never connects to MT5 and never places orders.
"""

from __future__ import annotations

import bisect
from datetime import datetime, timezone 

import json
from pathlib import Path
from typing import Any, Sequence

from trading_bot.core.enums import Timeframe
from trading_bot.core.models import Candle
from trading_bot.data.base import DataProvider, MarketDataQuery, SymbolInfo
from trading_bot.data.resample import resample_candles


"""JSONL historical market-data provider.

Reads historical OHLCV candles from a JSON Lines file and converts them
into the unified Candle model used throughout the trading bot.

Primary use:
    - Long-range backtesting
    - Historical fallback when MT5 does not have enough history

This provider is READ-ONLY.
It never connects to MT5 and never places orders.
"""


class JSONLDataProvider(DataProvider):
    """Historical candle provider backed by a JSONL file.

    The file is expected to contain one JSON object per line.
    """

    name = "jsonl"

    def __init__(
        self,
        path: str | Path | None = None,
        symbol: str = "XAUUSD",
        timeframe: Timeframe = Timeframe.M5,
    ):
        if path is None:
            path = Path(__file__).with_name("XAU_5m_data.jsonl")

        self.path = Path(path)
        self.default_symbol = symbol
        self.default_timeframe = timeframe

        self._loaded = False
        self._bars: list[Candle] = []
        self._timestamps: list[int] = []
        self._symbol_info: SymbolInfo | None = None

    # ------------------------------------------------------------------
    # Loading & Diagnostic Health
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Check provider health status without blowing up execution."""
        try:
            self._ensure_loaded()
            return {
                "ok": True,
                "source": self.name,
                "source_label": f"JSONL ({self.path.name})",
                "count": len(self._bars),
            }
        except Exception as exc:
            return {
                "ok": False,
                "source": self.name,
                "source_label": f"JSONL ({self.path.name})",
                "error": str(exc),
            }

    def _ensure_loaded(self) -> None:
        """Load and validate the JSONL file once."""
        if self._loaded:
            return

        if not self.path.exists():
            raise FileNotFoundError(
                f"JSONL historical data file not found: {self.path}"
            )

        bars: list[Candle] = []

        with self.path.open("r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                line = line.strip()

                if not line:
                    continue

                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON on line {line_number}: {exc}"
                    ) from exc

                if not isinstance(row, dict):
                    raise ValueError(
                        f"JSONL line {line_number} must contain an object"
                    )

                # Normalize keys to lowercase to guarantee case-insensitive lookups
                normalized_row = {str(k).lower(): v for k, v in row.items()}

                # Skip header rows gracefully (e.g., if {"time": "time", "open": "open"})
                if str(normalized_row.get("time")).strip().lower() in ("time", "timestamp"):
                    continue

                try:
                    candle = self._parse_candle(normalized_row)
                except Exception as exc:
                    raise ValueError(
                        f"Invalid candle on JSONL line {line_number}: {exc}"
                    ) from exc

                bars.append(candle)

        if not bars:
            raise ValueError(
                f"JSONL file contains no candle data: {self.path}"
            )

        # Sort chronologically.
        bars.sort(key=lambda candle: candle.time)

        # Remove duplicate timestamps.
        deduped: list[Candle] = []
        seen: set[int] = set()

        for bar in bars:
            if bar.time in seen:
                continue
            seen.add(bar.time)
            deduped.append(bar)

        self._bars = deduped
        self._timestamps = [candle.time for candle in deduped]
        self._loaded = True

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _first_value(row: dict[str, Any], *keys: str) -> Any:
        """Return the first existing/non-null field."""
        for key in keys:
            if key in row and row[key] is not None:
                return row[key]
        return None

    @classmethod
    def _parse_timestamp(cls, row: dict[str, Any]) -> int:
        value = cls._first_value(
            row,
            "time",
            "timestamp",
            "ts",
            "datetime",
            "date",
            "t",
        )

        if value is None:
            present_keys = list(row.keys())
            raise ValueError(f"missing timestamp/time field. Present keys: {present_keys}")

        # Numeric timestamps (Seconds or Milliseconds)
        if isinstance(value, (int, float)):
            value = float(value)
            if value > 100_000_000_000:
                value /= 1000.0
            return int(value)

        # String datetime parsing
        if isinstance(value, str):
            value = value.strip()

            # Fallback if string contains a numeric value
            try:
                numeric = float(value)
                if numeric > 100_000_000_000:
                    numeric /= 1000.0
                return int(numeric)
            except ValueError:
                pass

            # FIX: Handle custom MT5 'YYYY.MM.DD HH:MM' format by changing dots to dashes
            # Converts '2004.06.11 07:15' -> '2004-06-11 07:15'
            normalized = value.replace(".", "-").replace("Z", "+00:00")
            
            dt = datetime.fromisoformat(normalized)

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            return int(dt.timestamp())

        raise ValueError(f"unsupported timestamp type: {type(value).__name__}")


    @classmethod
    def _parse_candle(cls, row: dict[str, Any]) -> Candle:
        timestamp = cls._parse_timestamp(row)

        open_price = cls._first_value(row, "open", "o")
        high_price = cls._first_value(row, "high", "h")
        low_price = cls._first_value(row, "low", "l")
        close_price = cls._first_value(row, "close", "c")

        if open_price is None:
            raise ValueError("missing open price")
        if high_price is None:
            raise ValueError("missing high price")
        if low_price is None:
            raise ValueError("missing low price")
        if close_price is None:
            raise ValueError("missing close price")

        volume = cls._first_value(row, "volume", "vol", "tick_volume", "v")
        spread = cls._first_value(row, "spread", "spread_points")

        return Candle(
            time=timestamp,
            open=float(open_price),
            high=float(high_price),
            low=float(low_price),
            close=float(close_price),
            volume=float(volume or 0.0),
            spread=float(spread or 0.0),
        )

    # ------------------------------------------------------------------
    # DataProvider interface
    # ------------------------------------------------------------------

    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        """Return candles inside requested window via O(log N) binary search."""
        self._ensure_loaded()

        if query.symbol != self.default_symbol:
            return []

        if query.timeframe != self.default_timeframe:
            raise ValueError(
                f"JSONL provider only contains {self.default_timeframe.value} "
                f"data; requested {query.timeframe.value}"
            )

        start_idx = bisect.bisect_left(self._timestamps, query.start) if query.start else 0
        end_idx = bisect.bisect_right(self._timestamps, query.end) if query.end else len(self._bars)

        return self._bars[start_idx:end_idx]

    def resample(self, timeframe: Timeframe) -> DataProvider:
        """Serve any HIGHER timeframe by resampling the stored bars.

        The file holds a single base timeframe (e.g. 5m); requests for
        15m/30m/1h/4h/... are aggregated on the fly. Requesting the base
        timeframe returns ``self``.
        """
        if timeframe == self.default_timeframe:
            return self
        if timeframe.minutes < self.default_timeframe.minutes:
            raise ValueError(
                f"cannot resample {self.default_timeframe.value} data down to "
                f"{timeframe.value}"
            )
        return _ResampledJSONLProvider(self, timeframe)

    def load_ticks(self, query: MarketDataQuery):
        raise RuntimeError("JSONLDataProvider contains candle data only; tick data unavailable")

    def available_symbols(self) -> Sequence[str]:
        self._ensure_loaded()
        return [self.default_symbol]

    def symbol_info(self, symbol: str) -> SymbolInfo:
        self._ensure_loaded()
        if symbol != self.default_symbol:
            raise ValueError(f"Symbol {symbol} is not tracked by this provider")

        if self._symbol_info is None:
            self._symbol_info = SymbolInfo(
                symbol=self.default_symbol,
                digits=2,
                point_size=0.01,
                tick_size=0.01,
                contract_size=100,
                lot_min=0.01,
                lot_max=200.0,
                lot_step=0.01,
            )
        return self._symbol_info


    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @property
    def source(self) -> str:
        return "jsonl"

    @property
    def source_label(self) -> str:
        return f"JSONL ({self.path.name})"

    @property
    def data_start(self) -> int:
        self._ensure_loaded()

        return self._bars[0].time

    @property
    def data_end(self) -> int:
        self._ensure_loaded()

        return self._bars[-1].time

    @property
    def n_bars(self) -> int:
        self._ensure_loaded()

        return len(self._bars)

    def health(self) -> dict:
        """Return provider health information for the dashboard."""

        try:
            self._ensure_loaded()

            return {
                "ok": True,
                "source": self.source,
                "source_label": self.source_label,
                "symbol": self.default_symbol,
                "timeframe": self.default_timeframe.value,
                "path": str(self.path),
                "n_bars": self.n_bars,
                "start": self.data_start,
                "end": self.data_end,
            }

        except Exception as exc:
            return {
                "ok": False,
                "source": self.source,
                "source_label": self.source_label,
                "error": str(exc),
            }

    def data_range(self) -> dict:
        """Return the available historical range."""

        self._ensure_loaded()

        return {
            "symbol": self.default_symbol,
            "timeframe": self.default_timeframe.value,
            "start": self.data_start,
            "end": self.data_end,
            "n_bars": self.n_bars,
            "source": self.source,
            "source_label": self.source_label,
        }


class _ResampledJSONLProvider(DataProvider):
    """Serves a HIGHER timeframe by aggregating the source JSONL bars.

    Wraps a :class:`JSONLDataProvider` (single base timeframe, e.g. 5m) and
    produces 15m/30m/1h/4h/... candles on demand with deterministic
    aggregation (``data.resample.resample_candles``). Read-only.
    """

    name = "jsonl_resampled"

    def __init__(self, inner: JSONLDataProvider, timeframe: Timeframe):
        self._inner = inner
        self.timeframe = timeframe

    @property
    def path(self) -> Path:
        return self._inner.path

    @property
    def source_label(self) -> str:
        return f"{self._inner.source_label} resampled -> {self.timeframe.value}"

    def available_symbols(self) -> Sequence[str]:
        return self._inner.available_symbols()

    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        if query.timeframe != self.timeframe:
            raise ValueError(
                f"resampled provider serves {self.timeframe.value}; "
                f"requested {query.timeframe.value}"
            )
        base_query = MarketDataQuery(
            symbol=query.symbol,
            timeframe=self._inner.default_timeframe,
            start=query.start,
            end=query.end,
        )
        base_bars = self._inner.load_candles(base_query)
        if not base_bars:
            return []
        return resample_candles(
            list(base_bars),
            self.timeframe,
            source=self._inner.default_timeframe,
        )

    def load_ticks(self, query: MarketDataQuery):
        return self._inner.load_ticks(query)

    def symbol_info(self, symbol: str) -> SymbolInfo:
        return self._inner.symbol_info(symbol)

    def health(self) -> dict:
        h = self._inner.health()
        h["source"] = f"{self._inner.source}->{self.timeframe.value}"
        h["source_label"] = self.source_label
        h["timeframe"] = self.timeframe.value
        return h

    def resample(self, timeframe: Timeframe) -> DataProvider:
        # delegate: the inner provider validates direction and caches nothing
        return self._inner.resample(timeframe)