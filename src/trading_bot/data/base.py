"""Data layer: unified data access.

All providers normalize into `Candle`/`Tick` objects. Strategies and the
replay engine never import a concrete provider — they consume this interface.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

from trading_bot.core.enums import Timeframe
from trading_bot.core.models import Candle, Tick


@dataclass(frozen=True)
class MarketDataQuery:
    symbol: str
    timeframe: Timeframe
    start: int = 0
    end: int = 0  # inclusive; 0 = unlimited
    with_spread: bool = True
    adjust: bool = True  # apply broker adjustments if applicable


@dataclass(frozen=True)
class SymbolInfo:
    """Static symbol metadata required by risk/execution."""

    symbol: str
    digits: int
    tick_size: float
    point_size: float
    contract_size: int = 100_000  # units of base per 1.0 lot
    lot_min: float = 0.01
    lot_max: float = 200.0
    lot_step: float = 0.01
    currency: str = ""
    margin_rate: float = 0.0
    pip_digits: int = 1  # pips per point grouping


class DataProvider(ABC):
    """Interface all data sources implement. Data-source agnostic by design."""

    name: str = "base"

    @abstractmethod
    def available_symbols(self) -> Sequence[str]:
        ...

    @abstractmethod
    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        ...

    @abstractmethod
    def load_ticks(self, query: MarketDataQuery) -> Sequence[Tick]:
        """May return empty list if ticks are not available."""

    @abstractmethod
    def symbol_info(self, symbol: str) -> SymbolInfo:
        ...

    def resample(self, timeframe: Timeframe) -> "DataProvider":
        """Return a provider serving bars at ``timeframe``.

        Default: a provider that is already multi-timeframe returns ``self``.
        Single-timeframe providers (e.g. synthetic) build a fresh instance.
        Used by walk-forward analysis to keep large-range runs bounded.
        """
        return self


class CachedDataProvider(DataProvider):
    """Wrapper that caches loaded bars in memory for repeated access."""

    def __init__(self, inner: DataProvider, cache_candles: bool = True, cache_ticks: bool = True):
        self._inner = inner
        self._candles: dict[tuple[str, Timeframe, int, int], Sequence[Candle]] = {}
        self._ticks: dict[tuple[str, int, int], Sequence[Tick]] = {}
        self._candle_cache = cache_candles
        self._tick_cache = cache_ticks

    @property
    def name(self) -> str:
        return f"cached:{self._inner.name}"

    def available_symbols(self) -> Sequence[str]:
        return self._inner.available_symbols()

    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        key = (query.symbol, query.timeframe, query.start, query.end)
        if self._candle_cache and key in self._candles:
            return self._candles[key]
        bars = self._inner.load_candles(query)
        if self._candle_cache:
            self._candles[key] = bars
        return bars

    def load_ticks(self, query: MarketDataQuery) -> Sequence[Tick]:
        key = (query.symbol, query.start, query.end)
        if self._tick_cache and key in self._ticks:
            return self._ticks[key]
        ticks = self._inner.load_ticks(query)
        if self._tick_cache:
            self._ticks[key] = ticks
        return ticks

    def symbol_info(self, symbol: str) -> SymbolInfo:
        return self._inner.symbol_info(symbol)

    def clear(self) -> None:
        self._candles.clear()
        self._ticks.clear()


class CompositeDataProvider(DataProvider):
    """Merge multiple providers with a priority order.

    Primary provider wins for a symbol/timeframe; fallbacks are used only if
    the higher-priority provider returns no data.
    """

    def __init__(self, providers: Sequence[DataProvider]):
        self.providers = list(providers)

    @property
    def name(self) -> str:
        return "composite:" + "+".join(p.name for p in self.providers)

    def available_symbols(self) -> Sequence[str]:
        seen: list[str] = []
        for p in self.providers:
            for s in p.available_symbols():
                if s not in seen:
                    seen.append(s)
        return seen

    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        for p in self.providers:
            bars = p.load_candles(query)
            if bars:
                return bars
        return []

    def load_ticks(self, query: MarketDataQuery) -> Sequence[Tick]:
        for p in self.providers:
            ticks = p.load_ticks(query)
            if ticks:
                return ticks
        return []

    def symbol_info(self, symbol: str) -> SymbolInfo:
        for p in self.providers:
            try:
                info = p.symbol_info(symbol)
                if info is not None:
                    return info
            except Exception:
                continue
        raise KeyError(f"No provider has symbol info for {symbol}")
