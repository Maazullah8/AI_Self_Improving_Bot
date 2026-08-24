"""Data layer: providers, resampling, unified access."""
from trading_bot.data.base import (
    CachedDataProvider,
    CompositeDataProvider,
    DataProvider,
    MarketDataQuery,
    SymbolInfo,
)
from trading_bot.data.bi5_provider import BI5DataProvider
from trading_bot.data.file_provider import FileDataProvider
from trading_bot.data.mt5_provider import MT5DataProvider, mt5_available
from trading_bot.data.resample import (
    aggregate_ticks_to_candles,
    build_candle_timeframe,
    resample_candles,
)
from trading_bot.data.supabase_provider import (
    SupabaseDataProvider,
    load_env_file,
)
from trading_bot.data.synthetic import SyntheticDataProvider, generate_csv
from trading_bot.data.yahoo_provider import (
    DEFAULT_SYMBOL,
    YFinanceDataProvider,
    yfinance_available,
)

__all__ = [
    "DataProvider",
    "MarketDataQuery",
    "SymbolInfo",
    "CachedDataProvider",
    "CompositeDataProvider",
    "FileDataProvider",
    "BI5DataProvider",
    "MT5DataProvider",
    "mt5_available",
    "SupabaseDataProvider",
    "load_env_file",
    "SyntheticDataProvider",
    "generate_csv",
    "YFinanceDataProvider",
    "yfinance_available",
    "DEFAULT_SYMBOL",
    "aggregate_ticks_to_candles",
    "build_candle_timeframe",
    "resample_candles",
]
