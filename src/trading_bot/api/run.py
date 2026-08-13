"""Entry point for the dashboard API server.

Data provider defaults to yfinance (XAUUSD -> Yahoo "GC=F"). If yfinance is
not installed the server falls back to a deterministic synthetic feed so the
UI still works. Pass ``--live`` to start a paper (simulated) live pipeline;
it never touches real money and stays fail-closed.

Usage:
    PYTHONPATH=/workspace/src python3 -m trading_bot.api.run
    PYTHONPATH=/workspace/src python3 -m trading_bot.api.run --symbol XAUUSD --live
"""
from __future__ import annotations

import argparse
import threading
import time

import uvicorn

from trading_bot.api.app import make_app
from trading_bot.core.enums import Timeframe
from trading_bot.data import (
    DEFAULT_SYMBOL,
    YFinanceDataProvider,
    SyntheticDataProvider,
    yfinance_available,
)
from trading_bot.execution.executor import MT5Executor, SimulatedExecutor
from trading_bot.live.pipeline import LiveConfig, LiveTradePipeline
from trading_bot.storage.memory import MemoryStore
from trading_bot.strategy.base import create_strategy


def build_provider(symbol: str = DEFAULT_SYMBOL, timeframe: str = "5m", mode: str = "auto"):
    """Return a data provider.

    mode: "yfinance" uses live Yahoo data (requires `pip install -e ".[yfinance]"`),
          "synthetic" uses the deterministic demo feed,
          "auto" prefers yfinance and falls back to synthetic.
    """
    if mode == "yfinance" or (mode == "auto" and yfinance_available()):
        return YFinanceDataProvider()
    if mode == "yfinance":
        raise SystemExit(
            "yfinance is not installed. Run: pip install -e \".[yfinance]\""
        )
    now = int(time.time())
    return SyntheticDataProvider(
        symbol=symbol,
        seed=7,
        start=now - 120 * 86400,
        end=now,
        tf=Timeframe(timeframe),
        initial_price=2050.0 if symbol == DEFAULT_SYMBOL else 1.1000,
        volatility=0.0004,
        trend_cycles=8,
    )


def seed_demo(store: MemoryStore, provider, symbol: str, timeframe: str) -> None:
    """Populate the journal with a backtest + AI review so the dashboard
    shows real data on first launch."""
    from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
    from trading_bot.journal.journal import Journal

    strategy = create_strategy("smc_crt")
    journal = Journal(store=store.trades, strategy_name=strategy.name, strategy_version=strategy.version)
    runner = BacktestRunner(provider, journal=journal)
    now = int(time.time())
    cfg = BacktestConfig(
        symbol=symbol,
        timeframe=Timeframe(timeframe),
        start=now - 90 * 86400,
        end=now - 86400,
        initial_cash=10_000.0,
        seed=42,
    )
    result = runner.run(strategy, cfg)
    print(f"seeded {len(result.trades)} backtest trades, final equity {result.final_equity:.2f}", flush=True)

    from trading_bot.ai.review import AITradeReviewer

    rev = AITradeReviewer().review(
        result.trades, strategy=strategy.name, strategy_version=strategy.version,
    )
    store.reviews.insert(rev)
    print(f"seeded review: {rev.summary}", flush=True)


def build_executor(
    executor: str,
    login: int = 0,
    password: str = "",
    server: str = "",
    path: str = "",
):
    """Executor for the live pipeline.

    ``simulated`` (default) is a paper executor — it never touches a broker.
    ``mt5`` sends real orders through a running MetaTrader 5 terminal. MT5
    fails closed: if the terminal is missing or unhealthy, orders are rejected.
    """
    if executor == "mt5":
        return MT5Executor(login=login, password=password, server=server, path=path)
    return SimulatedExecutor()


def start_live(
    store: MemoryStore,
    provider,
    symbol: str,
    timeframe: str,
    initial_cash: float,
    poll_seconds: int,
    executor: str = "simulated",
    mt5_login: int = 0,
    mt5_password: str = "",
    mt5_server: str = "",
    mt5_path: str = "",
):
    """Create and start a live pipeline in a background thread.

    Defaults to a simulated (paper) executor. Pass ``executor="mt5"`` to route
    orders to a running MetaTrader 5 terminal (demo account strongly advised).
    """
    strategy = create_strategy("smc_crt")
    exec_ = build_executor(executor, mt5_login, mt5_password, mt5_server, mt5_path)
    health = exec_.health()
    if executor == "mt5" and not health.get("ok"):
        raise SystemExit(
            f"MT5 is not ready (fail-closed): {health.get('error', 'unknown')}. "
            "Open the MT5 terminal and log in to your demo account first."
        )
    config = LiveConfig(
        symbol=symbol,
        timeframe=timeframe,
        poll_interval_seconds=poll_seconds,
        max_staleness_seconds=max(poll_seconds * 10, 300),
    )
    pipeline = LiveTradePipeline(
        provider=provider,
        strategy=strategy,
        executor=exec_,
        store=store,
        config=config,
        initial_cash=initial_cash,
    )

    def _loop():
        while True:
            try:
                pipeline.poll()
            except Exception as e:  # fail-closed: never let the loop die
                pipeline._fail(f"poll error: {e}")
            time.sleep(config.poll_interval_seconds)

    thread = threading.Thread(target=_loop, name="live-pipeline", daemon=True)
    thread.start()
    print(f"live pipeline started: {symbol} {timeframe} -> {health}", flush=True)
    return pipeline


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Trading dashboard API server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="e.g. XAUUSD, XAGUSD, EURUSD, BTCUSD")
    parser.add_argument("--timeframe", default="5m", choices=["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"])
    parser.add_argument(
        "--provider", choices=["auto", "yfinance", "synthetic"], default="auto",
        help="data source: yfinance (live Yahoo), synthetic (demo), auto (default)",
    )
    parser.add_argument("--seed-demo", action="store_true", help="run a backtest + AI review on startup")
    parser.add_argument(
        "--live", action="store_true",
        help="start the live pipeline (simulated/paper unless --executor mt5)",
    )
    parser.add_argument("--executor", choices=["simulated", "mt5"], default="simulated")
    parser.add_argument("--mt5-login", type=int, default=0, help="MT5 demo account login (with --executor mt5)")
    parser.add_argument("--mt5-password", default="", help="MT5 demo account password")
    parser.add_argument("--mt5-server", default="", help="MT5 broker server (e.g. 'ICMarkets-Demo')")
    parser.add_argument("--mt5-path", default="", help="path to terminal64.exe if not auto-detected")
    parser.add_argument("--initial-cash", type=float, default=10_000.0)
    parser.add_argument("--poll-seconds", type=int, default=15)
    args = parser.parse_args(argv)

    store = MemoryStore()
    provider = build_provider(symbol=args.symbol, timeframe=args.timeframe, mode=args.provider)
    print(f"provider: {type(provider).__name__} symbol={args.symbol} timeframe={args.timeframe}", flush=True)

    live = None
    if args.seed_demo:
        seed_demo(store, provider, args.symbol, args.timeframe)
    if args.live:
        live = start_live(
            store, provider, args.symbol, args.timeframe, args.initial_cash, args.poll_seconds,
            executor=args.executor,
            mt5_login=args.mt5_login, mt5_password=args.mt5_password,
            mt5_server=args.mt5_server, mt5_path=args.mt5_path,
        )

    app = make_app(store=store, provider=provider, live=live)
    print(f"API serving on http://{args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
