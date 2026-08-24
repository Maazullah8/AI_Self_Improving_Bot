"""Entry point for the dashboard API server.

Data provider defaults to yfinance (XAUUSD -> Yahoo "GC=F"). If yfinance is
not installed the server falls back to a deterministic synthetic feed so the
UI still works. Pass ``--live`` to start a paper (simulated) live pipeline;
it never touches real money and stays fail-closed.

Usage:
    PYTHONPATH=/workspace/src python -m trading_bot.api.run
    PYTHONPATH=/workspace/src python -m trading_bot.api.run --symbol XAUUSD --live
"""
from __future__ import annotations

from pathlib import Path

import argparse
import os
import threading
import time

import uvicorn

from trading_bot.api.app import make_app
from trading_bot.core.enums import Timeframe
from trading_bot.data.fallback_provider import FallbackDataProvider
from trading_bot.data.jsonl_provider import JSONLDataProvider
from trading_bot.data.supabase_provider import (
    SupabaseDataProvider,
    load_env_file,
)
from trading_bot.data import (
    DEFAULT_SYMBOL,
    YFinanceDataProvider,
    MT5DataProvider,
    SyntheticDataProvider,
    yfinance_available,
)
from trading_bot.execution.executor import MT5Executor, SimulatedExecutor
from trading_bot.live.pipeline import LiveConfig, LiveTradePipeline
from trading_bot.storage.memory import MemoryStore
from trading_bot.strategy.base import create_strategy
from trading_bot.data.mt5_provider import MT5DataProvider


<<<<<<< HEAD

_ENV = load_env_file()


def _build_mt5():
    """MT5 provider honouring .env / CLI terminal location + account."""
    import os

    return MT5DataProvider(
        path=os.environ.get("MT5_PATH") or _ENV.get("MT5_PATH") or None,
        login=os.environ.get("MT5_LOGIN") or _ENV.get("MT5_LOGIN"),
        password=os.environ.get("MT5_PASSWORD") or _ENV.get("MT5_PASSWORD"),
        server=os.environ.get("MT5_SERVER") or _ENV.get("MT5_SERVER"),
    )


def build_provider(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = "5m",
    mode: str = "auto",
):
    if mode == "mt5":
        mt5 = _build_mt5()
        mt5._ensure()

        jsonl = JSONLDataProvider()

        return FallbackDataProvider([
            mt5,
            jsonl,
        ])

    if mode == "jsonl":
        # Historical candles straight from the repo's data folder.
        return JSONLDataProvider(symbol=symbol)

    if mode == "supabase":
        sb = SupabaseDataProvider(symbol=symbol)
        if not sb.configured:
            raise SystemExit(
                "Supabase is not configured. Add SUPABASE_URL and SUPABASE_KEY "
                "to the .env file in the repository root "
                "(see src/trading_bot/data/supabase_provider.py)."
            )
        return sb

    if mode == "yfinance":
        if not yfinance_available():
            raise SystemExit(
                "yfinance is not installed. Run: pip install -e \".[yfinance]\""
            )
        return YFinanceDataProvider()

    if mode == "auto":
        # Priority: MT5 (running terminal) -> local data folder ->
        # Yahoo Finance -> Supabase -> synthetic. Each entry is skipped
        # gracefully when unavailable; FallbackDataProvider tries them
        # in order per request.
        chain = []
        try:
            mt5 = _build_mt5()
            mt5._ensure()
            chain.append(mt5)
        except Exception as exc:
            print(f"MT5 not available ({exc}); using next provider", flush=True)
        jl = JSONLDataProvider(symbol=symbol)
        if jl.path.exists():
            chain.append(jl)
        if yfinance_available():
            chain.append(YFinanceDataProvider())
        sb = SupabaseDataProvider(symbol=symbol)
        if sb.configured:
            chain.append(sb)
        if len(chain) == 1:
            return chain[0]
        if chain:
            return FallbackDataProvider(chain)
=======
def build_provider(
    symbol: str = DEFAULT_SYMBOL,
    timeframe: str = "5m",
    mode: str = "auto",
):
    """Return the requested market-data provider.

    mode:
        "mt5"       -> MetaTrader 5 live market data
        "yfinance"  -> Yahoo Finance
        "synthetic" -> deterministic demo feed
        "auto"      -> prefers MT5, then yfinance, then synthetic
    """

    if mode == "mt5":
        provider = MT5DataProvider()

        # Force the connection now so startup fails clearly if MT5
        # is unavailable instead of failing later inside the live thread.
        provider._ensure()

        return provider

    if mode == "yfinance" or (mode == "auto" and yfinance_available()):
        return YFinanceDataProvider()

    if mode == "yfinance":
        raise SystemExit(
            "yfinance is not installed. Run: pip install -e \".[yfinance]\""
        )
>>>>>>> 12a69025acd48a16f79df12ed494635d1fdcb5e9

    now = int(time.time())

    return SyntheticDataProvider(
        symbol=symbol,
        seed=7,
        start=now - 5 * 365 * 86400,
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
    start=now - 50 * 86400,
    end=now - 86400,
    initial_cash=10_000.0,
    seed=100,
    )
    result = runner.run(strategy, cfg)
    print(
    f"backtest source={getattr(provider, 'source', 'unknown')} "
    f"bars={result.n_bars} "
    f"trades={len(result.trades)} "
    f"final equity={result.final_equity:.2f}",
    flush=True,
    )

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
    if executor == "mt5":
        return MT5Executor(
            login=login,
            password=password,
            server=server,
            path=path,
        )

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
    exec_ = build_executor(
    executor,
    mt5_login,
    mt5_password,
    mt5_server,
    mt5_path
)
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
        "--provider",
<<<<<<< HEAD
        choices=["auto", "jsonl", "supabase", "mt5", "yfinance", "synthetic"],
        default="auto",
        help="data source: auto (local data folder -> supabase -> yahoo), jsonl, supabase, mt5, yfinance, synthetic",
=======
        choices=["auto","mt5", "yfinance", "synthetic"],
        default="auto",
        help="data source: mt5 (live MT5), yfinance (Yahoo), synthetic (demo), auto",
>>>>>>> 12a69025acd48a16f79df12ed494635d1fdcb5e9
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

    # Persistent storage: Supabase Postgres when credentials are present
    # (.env / env), otherwise in-memory (dashboard still fully functional).
    store = MemoryStore()
    if os.environ.get("SUPABASE_DB_HOST") and os.environ.get("SUPABASE_DB_PASSWORD"):
        try:
            from trading_bot.storage.postgres import PostgresStore

            pg = PostgresStore.from_supabase_env()
            pg.init_schema()
            store = pg
            print("persistent store: Supabase Postgres", flush=True)
        except Exception as exc:
            print(
                f"Supabase store unavailable ({exc}); using in-memory store",
                flush=True,
            )
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
