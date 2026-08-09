"""Generic CSV/Parquet data provider.

The provider is column-name flexible: it will try a list of known column
aliases for each field so different exports (MT5, TradingView, Dukascopy,
Tickstory CSV, etc.) can be loaded without preprocessing.

Timestamp column conventions supported:
  - 'time' | 'datetime' | 'timestamp' | 'date' | 'ts': epoch seconds,
    ISO strings, or 'YYYY.MM.DD HH:MM:SS' MT5 style.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Optional

import numpy as np
import pandas as pd

from trading_bot.core.enums import Timeframe
from trading_bot.core.models import Candle, Tick, point_size_for_digits
from trading_bot.core.time_utils import bar_open_time
from trading_bot.data.base import DataProvider, MarketDataQuery, SymbolInfo

TIME_ALIASES = ["time", "datetime", "timestamp", "date", "ts", "t"]
OPEN_ALIASES = ["open", "o", "Open"]
HIGH_ALIASES = ["high", "h", "High"]
LOW_ALIASES = ["low", "l", "Low"]
CLOSE_ALIASES = ["close", "c", "Close"]
VOLUME_ALIASES = ["volume", "vol", "v", "Volume", "tick_volume"]
SPREAD_ALIASES = ["spread", "Spread", "sp"]
BID_ALIASES = ["bid", "Bid", "bid_price"]
ASK_ALIASES = ["ask", "Ask", "ask_price"]


def _find_column(df: pd.DataFrame, aliases: Sequence[str]) -> Optional[str]:
    for a in aliases:
        if a in df.columns:
            return a
    # case-insensitive fallback
    lower = {str(c).lower(): c for c in df.columns}
    for a in aliases:
        if a.lower() in lower:
            return lower[a.lower()]
    return None


def parse_ts_col(s: pd.Series) -> pd.Series:
    """Convert a timestamp column of mixed types to int epoch seconds."""
    s = s.astype(object)
    if s.dtype == object:
        sample = s.iloc[0] if len(s) else None
        if isinstance(sample, str) and "." in sample and sample.count(".") == 2:
            # MT5 style "2024.01.15 10:30:00"
            return s.apply(lambda v: int(pd.Timestamp(v).timestamp()))
        # try numeric float epoch
        coerced = pd.to_numeric(s, errors="coerce")
        if coerced.notna().all():
            # decide seconds vs ms by magnitude
            med = coerced.median()
            if np.isfinite(med) and med > 1e12:
                return (coerced / 1000).astype("int64")
            return coerced.astype("int64")
        return s.apply(lambda v: int(pd.Timestamp(v).timestamp()))
    if pd.api.types.is_datetime64_any_dtype(s):
        return s.astype("int64").floordiv(1_000_000_000)
    num = pd.to_numeric(s, errors="coerce")
    med = num.median()
    if np.isfinite(med) and med > 1e12:
        return (num / 1000).astype("int64")
    return num.astype("int64")


class FileDataProvider(DataProvider):
    """Loads candles/ticks from CSV or Parquet files on disk."""

    name = "file"

    def __init__(self, data_dir: str, symbol: str, timeframe: Timeframe, digits: int = 5):
        self.data_dir = data_dir
        self.symbol = symbol
        self.timeframe = timeframe
        self.digits = digits
        self._candles: Optional[list[Candle]] = None
        self._ticks: Optional[list[Tick]] = None
        self._candle_file = self._find_file("candles")
        self._tick_file = self._find_file("ticks")

    def _find_file(self, kind: str) -> Optional[str]:
        candidates = [
            f"{self.symbol}_{self.timeframe.value}.csv",
            f"{self.symbol}_{self.timeframe.value}.parquet",
            f"{self.symbol}.csv",
            f"{self.symbol}.parquet",
            f"{kind}_{self.symbol}_{self.timeframe.value}.csv",
            f"{kind}_{self.symbol}.csv",
        ]
        for c in candidates:
            p = os.path.join(self.data_dir, c)
            if os.path.exists(p):
                return p
        # any file matching pattern
        pat = f"{self.symbol}*"
        import fnmatch

        for f in sorted(os.listdir(self.data_dir)):
            if fnmatch.fnmatch(f, pat) and f.endswith((".csv", ".parquet")):
                return os.path.join(self.data_dir, f)
        return None

    def _read(self) -> pd.DataFrame:
        if not self._candle_file:
            raise FileNotFoundError(
                f"No data file for {self.symbol} in {self.data_dir}"
            )
        if self._candle_file.endswith(".parquet"):
            return pd.read_parquet(self._candle_file)
        return pd.read_csv(self._candle_file)

    def available_symbols(self) -> Sequence[str]:
        return [self.symbol]

    def _load_raw(self) -> pd.DataFrame:
        df = self._read()
        tcol = _find_column(df, TIME_ALIASES)
        if tcol is None:
            raise ValueError(f"No time column found in {self._candle_file}")
        df["_ts"] = parse_ts_col(df[tcol])
        df = df.sort_values("_ts").reset_index(drop=True)
        return df

    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        if self._candles is None:
            df = self._load_raw()
            ocol, hcol, lcol, ccol = (
                _find_column(df, OPEN_ALIASES),
                _find_column(df, HIGH_ALIASES),
                _find_column(df, LOW_ALIASES),
                _find_column(df, CLOSE_ALIASES),
            )
            has_ohlc = all(c is not None for c in (ocol, hcol, lcol, ccol))
            if not has_ohlc:
                # tick file -> aggregate into candles
                bcol, acol = _find_column(df, BID_ALIASES), _find_column(df, ASK_ALIASES)
                if bcol is None or acol is None:
                    raise ValueError(
                        f"File {self._candle_file} has neither OHLC nor bid/ask columns"
                    )
                ticks = []
                for _, r in df.iterrows():
                    ticks.append(Tick(time=int(r["_ts"]), bid=float(r[bcol]), ask=float(r[acol])))
                from trading_bot.data.resample import build_candle_timeframe

                self._candles = list(build_candle_timeframe(ticks, self.timeframe))
            else:
                vcol = _find_column(df, VOLUME_ALIASES)
                scol = _find_column(df, SPREAD_ALIASES)
                candles = []
                for _, r in df.iterrows():
                    candles.append(
                        Candle(
                            time=int(r["_ts"]),
                            open=float(r[ocol]),
                            high=float(r[hcol]),
                            low=float(r[lcol]),
                            close=float(r[ccol]),
                            volume=float(r[vcol]) if vcol else 0.0,
                            spread=float(r[scol]) if scol else 0.0,
                        )
                    )
                self._candles = candles
        return [
            c
            for c in self._candles
            if (query.start == 0 or c.time >= query.start)
            and (query.end == 0 or c.time <= query.end)
        ]

    def load_ticks(self, query: MarketDataQuery) -> Sequence[Tick]:
        df = self._load_raw()
        bcol, acol = _find_column(df, BID_ALIASES), _find_column(df, ASK_ALIASES)
        if bcol is None or acol is None:
            return []
        ticks = []
        for _, r in df.iterrows():
            t = int(r["_ts"])
            if query.start and t < query.start:
                continue
            if query.end and t > query.end:
                continue
            ticks.append(Tick(time=t, bid=float(r[bcol]), ask=float(r[acol])))
        return ticks

    def symbol_info(self, symbol: str) -> SymbolInfo:
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
            lot_max=100.0,
            lot_step=0.01,
        )
