"""Yahoo Finance data provider (free, cross-platform market data).

Pulls OHLCV bars via the ``yfinance`` package and normalizes them into the
unified ``Candle`` format, so backtests and the live pipeline are
data-source agnostic. No MT5 terminal or Windows required.

Symbol mapping: XAUUSD -> "GC=F" (COMEX gold futures), which is the closest
freely-available series to spot gold. Any other symbol is passed through to
Yahoo (e.g. "EURUSD=X", "BTC-USD").

Fail-closed: if ``yfinance`` is not installed or returns no data, every data
call raises ``RuntimeError`` rather than fabricating bars.
"""
from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Optional

from trading_bot.core.enums import Timeframe
from trading_bot.core.models import Candle, Tick, point_size_for_digits
from trading_bot.data.base import DataProvider, MarketDataQuery, SymbolInfo
from trading_bot.data.resample import resample_candles

# Common symbols -> Yahoo ticker. XAUUSD has no spot ticker on Yahoo, so we
# use front-month COMEX gold futures.
DEFAULT_SYMBOL = "XAUUSD"
SYMBOL_TICKER = {
    "XAUUSD": "GC=F",
    "GOLD": "GC=F",
    "XAGUSD": "SI=F",
    "SILVER": "SI=F",
    "SPX": "^GSPC",
    "NAS100": "^NDX",
    "US500": "^GSPC",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
}

# Yahoo intervals we can request directly, keyed by our Timeframe.
YF_INTERVAL = {
    Timeframe.M1: "1m",
    Timeframe.M5: "5m",
    Timeframe.M15: "15m",
    Timeframe.M30: "30m",
    Timeframe.H1: "60m",
    Timeframe.D1: "1d",
    Timeframe.W1: "1wk",
    Timeframe.MN: "1mo",
}

# Timeframes that must be resampled from the next-finest available interval.
_RESAMPLE_FROM = {
    Timeframe.M3: Timeframe.M1,  # 3m <- 1m
    Timeframe.H4: Timeframe.H1,  # 4h <- 1h
}

_DIGITS = {
    "XAUUSD": 2,
    "XAGUSD": 3,
}


def yfinance_available() -> bool:
    try:
        import yfinance  # noqa: F401

        return True
    except ImportError:
        return False


class YFinanceDataProvider(DataProvider):
    """Read-only Yahoo Finance bars. Never places orders."""

    name = "yfinance"

    def __init__(self, ticker_map: Optional[dict[str, str]] = None):
        self._ticker_map = dict(SYMBOL_TICKER)
        if ticker_map:
            self._ticker_map.update(ticker_map)
        self._cache: dict[tuple[str, str], Sequence[Candle]] = {}

    # ------------------------------------------------------------ helpers
    def _ticker(self, symbol: str) -> str:
        return self._ticker_map.get(symbol, symbol)

    def _ensure_yf(self):
        if not yfinance_available():
            raise RuntimeError("yfinance is not installed: pip install yfinance")
        import yfinance  # local import so the package works without it

        return yfinance

    def _fetch(self, ticker: str, yf_interval: str, start: int, end: int) -> Sequence[Candle]:
        """Download bars and convert to Candle (UTC-aligned open times)."""
        import datetime as dt

        yf = self._ensure_yf()
        start_dt = dt.datetime.fromtimestamp(start, tz=dt.timezone.utc)
        end_dt = dt.datetime.fromtimestamp(end, tz=dt.timezone.utc)
        try:
            df = yf.download(
                ticker,
                start=start_dt,
                end=end_dt,
                interval=yf_interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception as e:
            raise RuntimeError(f"yfinance download failed for {ticker}: {e}") from e

        if df is None or df.empty:
            raise RuntimeError(f"no data returned for {ticker} ({yf_interval})")

        # Flatten MultiIndex columns when multiple tickers are requested.
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)

        bars: list[Candle] = []
        for ts, row in df.iterrows():
            o = float(row["Open"])
            h = float(row["High"])
            l = float(row["Low"])
            c = float(row["Close"])
            if not all(p == p for p in (o, h, l, c)):
                continue  # drop NaN rows
            ts_utc = ts.timestamp() if ts.tzinfo else ts.to_datetime().timestamp()
            bars.append(
                Candle(
                    time=int(ts_utc),
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=float(row["Volume"]) if "Volume" in df.columns else 0.0,
                    spread=0.0,
                )
            )
        if not bars:
            raise RuntimeError(f"no usable bars for {ticker} ({yf_interval})")
        bars.sort(key=lambda c: c.time)
        return bars

    # ------------------------------------------------------ DataProvider
    def available_symbols(self) -> Sequence[str]:
        return sorted(self._ticker_map.keys())

    def load_candles(self, query: MarketDataQuery) -> Sequence[Candle]:
        key = (query.symbol, query.timeframe.value)
        if key in self._cache:
            return self._cache[key]

        # Unspecified window (0/0): default to the trailing 365 days so naive
        # clients get useful data instead of trying to fetch from epoch 0.
        start = query.start
        end = query.end
        if end == 0:
            end = int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
        if start == 0:
            start = end - 365 * 86400

        tf = query.timeframe
        if tf in _RESAMPLE_FROM:
            src_tf = _RESAMPLE_FROM[tf]
            src_interval = YF_INTERVAL[src_tf]
            raw = self._fetch(self._ticker(query.symbol), src_interval, start, end)
            bars = resample_candles(raw, tf, source=src_tf)
        elif tf in YF_INTERVAL:
            bars = self._fetch(self._ticker(query.symbol), YF_INTERVAL[tf], start, end)
        else:
            raise RuntimeError(f"timeframe {tf.value} not supported by yfinance provider")

        # filter to the requested window (resampled buckets may spill outside)
        if start:
            bars = [b for b in bars if b.time >= start]
        if end:
            bars = [b for b in bars if b.time <= end]

        self._cache[key] = bars
        return bars

    def load_ticks(self, query: MarketDataQuery) -> Sequence[Tick]:
        raise RuntimeError("yfinance provider does not expose ticks")

    def symbol_info(self, symbol: str) -> SymbolInfo:
        digits = _DIGITS.get(symbol, 2)
        pt = point_size_for_digits(digits)
        return SymbolInfo(
            symbol=symbol,
            digits=digits,
            tick_size=pt,
            point_size=pt,
            contract_size=100 if symbol in ("XAUUSD", "XAGUSD") else 100_000,
            lot_min=0.01,
            lot_max=100.0,
            lot_step=0.01,
            currency="USD",
        )

    def clear(self) -> None:
        self._cache.clear()

    def resample(self, timeframe: Timeframe) -> "YFinanceDataProvider":
        """Yahoo is already multi-timeframe (cached per symbol/timeframe)."""
        return self
