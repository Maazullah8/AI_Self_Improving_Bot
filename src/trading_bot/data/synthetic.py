"""Deterministic synthetic market data generator for testing.

Produces realistic-but-seeded candles/ticks with trend/range regimes and
clean liquidity levels, so the whole pipeline (replay, strategy, backtest,
metrics) can be exercised without any broker connection.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Optional

import numpy as np

from trading_bot.core.enums import Timeframe
from trading_bot.core.models import Candle, Tick, point_size_for_digits
from trading_bot.core.time_utils import bar_open_time, utc_ts
from trading_bot.data.base import DataProvider, MarketDataQuery, SymbolInfo

DEFAULT_START = utc_ts(2020, 1, 1)
DEFAULT_END = utc_ts(2020, 12, 31, 23, 59)


class SyntheticDataProvider(DataProvider):
    """Generates a random-walk OHLC stream with a reproducible seed."""

    name = "synthetic"

    def __init__(
        self,
        symbol: str = "EURUSD",
        seed: int = 42,
        digits: int = 5,
        start: int = DEFAULT_START,
        end: int = DEFAULT_END,
        tf: Timeframe = Timeframe.H1,
        initial_price: float = 1.1000,
        volatility: float = 0.0008,  # per-bar stddev in price units
        drift: float = 0.0,
        trend_cycles: int = 6,
        intraday_vol_boost: float = 1.0,
        volume_per_bar: float = 100.0,
        spread_points: int = 12,  # in points
    ):
        self.symbol = symbol
        self.seed = seed
        self.digits = digits
        self.start = start
        self.end = end
        self.tf = tf
        self.initial_price = initial_price
        self.volatility = volatility
        self.drift = drift
        self.trend_cycles = trend_cycles
        self.intraday_vol_boost = intraday_vol_boost
        self.volume_per_bar = volume_per_bar
        self.spread_points = spread_points
        self._bars: Optional[list[Candle]] = None

    def _generate(self) -> list[Candle]:
        rng = np.random.default_rng(self.seed)
        pt = point_size_for_digits(self.digits)
        spread = pt * self.spread_points

        # Build bar timestamps aligned to tf, skipping weekends
        times: list[int] = []
        t = self.start
        while t <= self.end:
            from trading_bot.core.time_utils import is_weekend

            if not is_weekend(t):
                times.append(t)
            t = bar_open_time(t, self.tf) + self.tf.minutes * 60
        # Re-align after weekend gaps
        times = [bar_open_time(x, self.tf) for x in times]

        n = len(times)
        price = self.initial_price
        bars: list[Candle] = []
        regime = np.zeros(n)
        cycle_len = max(10, n // (self.trend_cycles * 2))
        for i in range(n):
            # regime: -1 down-trend, 0 range, +1 up-trend, switching every cycle_len
            cycle = (i // cycle_len) % 4
            reg = 0.0
            if cycle == 0:
                reg = 1.0
            elif cycle == 1:
                reg = -1.0
            elif cycle == 2:
                reg = 0.0
            else:
                reg = 0.5
            regime[i] = reg
            hour_boost = 1.0 + 0.4 * abs((i % 24) - 12) / 12.0
            vol = self.volatility * self.intraday_vol_boost * hour_boost
            mu = self.drift + reg * self.volatility * 0.6
            o = price
            c = o * (1.0 + rng.normal(mu, vol))
            h = max(o, c) * (1.0 + abs(rng.normal(0, vol * 0.35)))
            l = min(o, c) * (1.0 - abs(rng.normal(0, vol * 0.35)))
            bars.append(
                Candle(
                    time=times[i],
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=self.volume_per_bar * (1.0 + abs(rng.normal(0, 0.2))),
                    spread=spread,
                )
            )
            price = c
        return bars

    def available_symbols(self) -> Sequence[str]:
        return [self.symbol]

    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        if self._bars is None:
            self._bars = self._generate()
        return [
            c
            for c in self._bars
            if (query.start == 0 or c.time >= query.start)
            and (query.end == 0 or c.time <= query.end)
        ]

    def load_ticks(self, query: MarketDataQuery) -> Sequence[Tick]:
        bars = self.load_candles(query)
        rng = np.random.default_rng(self.seed + 99)
        ticks: list[Tick] = []
        for b in bars:
            n_ticks = 10
            for k in range(n_ticks):
                frac = (k + 1) / n_ticks
                # simple linear interpolation between open and close with noise
                base = b.open + (b.close - b.open) * frac
                jitter = rng.normal(0, (b.high - b.low) * 0.2)
                mid = base + jitter
                mid = min(max(mid, b.low), b.high)
                half = b.spread / 2.0
                ticks.append(
                    Tick(
                        time=b.time + k,
                        bid=round(mid - half, self.digits),
                        ask=round(mid + half, self.digits),
                        volume=1.0,
                    )
                )
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


def generate_csv(
    path: str,
    symbol: str = "EURUSD",
    seed: int = 42,
    start: int = DEFAULT_START,
    end: int = DEFAULT_END,
    tf: Timeframe = Timeframe.H1,
    initial_price: float = 1.1000,
    volatility: float = 0.0008,
) -> None:
    """Write a CSV in MT5-like format for testing the file provider."""
    import pandas as pd

    provider = SyntheticDataProvider(
        symbol=symbol, seed=seed, start=start, end=end, tf=tf,
        initial_price=initial_price, volatility=volatility,
    )
    bars = provider.load_candles(MarketDataQuery(symbol=symbol, timeframe=tf))
    import datetime as _dt

    rows = []
    for b in bars:
        dt = _dt.datetime.fromtimestamp(b.time, tz=_dt.timezone.utc)
        rows.append(
            {
                "time": dt.strftime("%Y.%m.%d %H:%M:%S"),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "tick_volume": b.volume,
                "spread": b.spread,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)
