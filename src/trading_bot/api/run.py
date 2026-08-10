"""Entry point for the dashboard API server.

Usage:
    PYTHONPATH=/workspace/src python3 -m trading_bot.api.run
"""
from __future__ import annotations

import uvicorn

from trading_bot.api.app import make_app
from trading_bot.core.enums import Timeframe
from trading_bot.core.time_utils import utc_ts
from trading_bot.data.synthetic import SyntheticDataProvider
from trading_bot.storage.memory import MemoryStore


def build_provider():
    return SyntheticDataProvider(
        symbol="EURUSD",
        seed=7,
        start=utc_ts(2023, 1, 1),
        end=utc_ts(2023, 12, 31, 23, 59),
        tf=Timeframe.M5,
        initial_price=1.1000,
        volatility=0.0004,
        trend_cycles=8,
    )


def main(host: str = "0.0.0.0", port: int = 8000) -> None:
    store = MemoryStore()
    provider = build_provider()
    app = make_app(store=store, provider=provider)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
