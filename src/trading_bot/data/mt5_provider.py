"""MetaTrader 5 data provider adapter.

Imports MetaTrader5 lazily so the package works without the MT5 terminal.
The adapter is read-only on the data side: it NEVER places orders.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

from trading_bot.core.enums import DataSource, Timeframe
from trading_bot.core.models import Candle, Tick, point_size_for_digits
from trading_bot.data.base import DataProvider, MarketDataQuery, SymbolInfo

MT5_TF_MAP = {
    Timeframe.M1: "TIMEFRAME_M1",
    Timeframe.M5: "TIMEFRAME_M5",
    Timeframe.M15: "TIMEFRAME_M15",
    Timeframe.M30: "TIMEFRAME_M30",
    Timeframe.H1: "TIMEFRAME_H1",
    Timeframe.H4: "TIMEFRAME_H4",
    Timeframe.D1: "TIMEFRAME_D1",
    Timeframe.W1: "TIMEFRAME_W1",
    Timeframe.MN: "TIMEFRAME_MN1",
}
MT5_TF_REV = {v: k for k, v in MT5_TF_MAP.items()}


def mt5_available() -> bool:
    try:
        import MetaTrader5  # noqa: F401

        return True
    except ImportError:
        return False


class MT5DataProvider(DataProvider):
    """Pulls bars from a running MT5 terminal.

    If MetaTrader5 is not installed or the terminal is not running,
    all data calls raise RuntimeError — callers must handle this (fail closed).
    """

    name = "mt5"

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self._connected = False
        self._info_cache: dict[str, SymbolInfo] = {}
        self._mt5 = None

    def _ensure(self):
        if self._connected:
            return self._mt5
        if not mt5_available():
            raise RuntimeError("MetaTrader5 package not installed")
        import MetaTrader5 as mt5

        if self.port and self.host:
            ok = mt5.initialize(login=None, server=None, path=None, portable=True)
        else:
            ok = mt5.initialize()
        if not ok:
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        self._mt5 = mt5
        self._connected = True
        return mt5

    def shutdown(self):
        if self._connected and self._mt5 is not None:
            try:
                self._mt5.shutdown()
            except Exception:
                pass
        self._connected = False

    def available_symbols(self) -> Sequence[str]:
        mt = self._ensure()
        return [s.name for s in mt.symbols_get()]

    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        mt = self._ensure()
        tf_name = MT5_TF_MAP[query.timeframe]
        tf = getattr(mt, tf_name)
        rate = mt.copy_rates_range(query.symbol, tf, query.start, query.end)
        if rate is None or len(rate) == 0:
            return []
        bars = []
        for row in rate:
            bars.append(
                Candle(
                    time=int(row["time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["tick_volume"]),
                    spread=float(row["spread"]) if "spread" in row.dtype.names else 0.0,
                )
            )
        return bars

    def load_ticks(self, query: MarketDataQuery) -> Sequence[Tick]:
        mt = self._ensure()
        ticks = mt.copy_ticks_range(query.symbol, query.start, query.end)
        if ticks is None or len(ticks) == 0:
            return []
        out = []
        for row in ticks:
            out.append(
                Tick(
                    time=int(row["time"]),
                    bid=float(row["bid"]),
                    ask=float(row["ask"]),
                    volume=float(row["volume"]) if "volume" in row.dtype.names else 0.0,
                )
            )
        return out

    def symbol_info(self, symbol: str) -> SymbolInfo:
        if symbol in self._info_cache:
            return self._info_cache[symbol]
        mt = self._ensure()
        info = mt.symbol_info(symbol)
        if info is None:
            raise KeyError(f"Unknown symbol {symbol}")
        digits = int(info.digits)
        pt = point_size_for_digits(digits)
        si = SymbolInfo(
            symbol=symbol,
            digits=digits,
            tick_size=float(info.trade_tick_size or pt),
            point_size=pt,
            contract_size=int(info.trade_contract_size or 100_000),
            lot_min=float(info.volume_min or 0.01),
            lot_max=float(info.volume_max or 100.0),
            lot_step=float(info.volume_step or 0.01),
        )
        self._info_cache[symbol] = si
        return si


def normalize_candle_timeframe_bars(bars: Sequence[Candle], digits: int) -> list[Candle]:
    """Normalize raw MT5 bars (already in unified Candle) — identity for now,
    kept as an explicit normalization point for future provider quirks."""
    return list(bars)
