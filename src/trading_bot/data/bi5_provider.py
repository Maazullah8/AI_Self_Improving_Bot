"""Tickstory/BI5 tick data loader.

BI5 files (Dukascopy/Tickstory format) are named like:
  2024/01/15/10h_ticks.bi5
and contain raw big-endian records of: bid[4] ask[4] bidVol[4] askVol[4],
scaled by the tick value (e.g. 1e5 for EURUSD with 5 digits).

This provider normalizes BI5 into our unified `Tick`/`Candle` format so the
rest of the pipeline never knows the original provider.
"""
from __future__ import annotations

import glob
import os
import struct
from collections.abc import Sequence
from typing import Optional

from trading_bot.core.enums import DataSource, Timeframe
from trading_bot.core.models import Candle, Tick
from trading_bot.core.time_utils import bar_open_time
from trading_bot.data.base import DataProvider, MarketDataQuery, SymbolInfo
from trading_bot.data.resample import build_candle_timeframe

DEFAULT_SCALE = 1.0 / 100_000.0  # 5-digit EURUSD


class BI5DataProvider(DataProvider):
    """Loads BI5 tick files from a Tickstory/Dukascopy directory tree."""

    name = "bi5"

    def __init__(
        self,
        root: str,
        symbol: str = "XAUUSD",
        digits: int = 5,
        scale: Optional[float] = None,
        cache_candles: bool = True,
    ):
        self.root = root
        self.symbol = symbol
        self.digits = digits
        self.scale = scale if scale is not None else DEFAULT_SCALE
        self.cache_candles = cache_candles
        self._candle_cache: dict[tuple[int, int], list[Candle]] = {}
        self._tick_cache: dict[tuple[int, int], list[Tick]] = {}

    def _file_for_day(self, ts: int) -> Optional[str]:
        dt = __import__("datetime", fromlist=["datetime"]).datetime.fromtimestamp(
            ts, tz=__import__("datetime", fromlist=["timezone"]).timezone.utc
        )
        year, month, day, hour = dt.year, dt.month, dt.day, dt.hour
        base = os.path.join(self.root, f"{year:04d}", f"{month:02d}", f"{day:02d}")
        pattern = os.path.join(base, f"{hour:02d}h_ticks.bi5")
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
        # try symbol subfolder
        pattern2 = os.path.join(self.root, self.symbol, f"{year:04d}", f"{month:02d}", f"{day:02d}", f"{hour:02d}h_ticks.bi5")
        matches2 = glob.glob(pattern2)
        return matches2[0] if matches2 else None

    @staticmethod
    def _parse_bi5_file(path: str, scale: float) -> list[tuple[int, float, float, float]]:
        """Parse a BI5 file into (time_offset_ms, bid, ask, bidvol)."""
        with open(path, "rb") as f:
            data = f.read()
        rec_size = 16
        n = len(data) // rec_size
        out: list[tuple[int, float, float, float]] = []
        for i in range(n):
            rec = struct.unpack(">iiii", data[i * rec_size : (i + 1) * rec_size])
            bid, ask, bidvol, askvol = rec
            out.append((i * 1000, bid * scale, ask * scale, float(bidvol)))
        return out

    def _load_hour(self, ts: int) -> list[Tick]:
        path = self._file_for_day(ts)
        if not path:
            return []
        parsed = self._parse_bi5_file(path, self.scale)
        hour_open = bar_open_time(ts, Timeframe.H1)
        ticks = []
        for offset_ms, bid, ask, vol in parsed:
            ticks.append(Tick(time=hour_open + int(offset_ms / 1000), bid=bid, ask=ask, volume=vol))
        return ticks

    def available_symbols(self) -> Sequence[str]:
        # derive from directory tree
        if os.path.isdir(self.root):
            sub = os.path.join(self.root, self.symbol)
            if os.path.isdir(sub):
                return [self.symbol]
            return [self.symbol]
        return [self.symbol]

    def load_ticks(self, query: MarketDataQuery) -> Sequence[Tick]:
        key = (query.start, query.end)
        if key in self._tick_cache:
            return self._tick_cache[key]
        ticks: list[Tick] = []
        hour = query.start
        while hour <= query.end:
            hour_aligned = bar_open_time(hour, Timeframe.H1)
            ticks.extend(self._load_hour(hour_aligned))
            hour = hour_aligned + 3600
            if len(ticks) > 5_000_000:  # safety cap
                break
        self._tick_cache[key] = ticks
        return ticks

    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        key = (query.start, query.end)
        if self.cache_candles and key in self._candle_cache:
            return self._candle_cache[key]
        ticks = self.load_ticks(query)
        bars = build_candle_timeframe(ticks, query.timeframe)
        if self.cache_candles:
            self._candle_cache[key] = bars
        return bars

    def symbol_info(self, symbol: str) -> SymbolInfo:
        from trading_bot.core.models import point_size_for_digits

        if symbol != self.symbol:
            raise KeyError(f"Unknown symbol {symbol}")
        pt = point_size_for_digits(self.digits)
        return SymbolInfo(
            symbol=symbol,
            digits=self.digits,
            tick_size=pt,
            point_size=pt,
            contract_size=100_000,
            lot_min=0.01,
            lot_max=200.0,
            lot_step=0.01,
        )
