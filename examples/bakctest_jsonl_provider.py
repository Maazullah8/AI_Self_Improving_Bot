"""Backtest the smc_crt strategy on real market data pulled from a Jsonl_provider file in src/trading/data/jsonl_provider.

Requirements
------------
* No requirments it is in the repo itself

Usage
-----
    python -m examples.bakctest_jsonl_provider \
        --start 2023-01-01 --end 2023-12-31 --initial-cash 10000

The Jsonl provider is READ-ONLY: this script only copies bars; it never places
orders. JSONLDataProvider raises if the terminal isn't available (fail-closed).
Run a backtest using the JSONL data provider.

This script demonstrates how to run a backtest using:
- JSONLDataProvider for historical XAUUSD 5m data
- BacktestRunner to execute the strategy
- SimpleMovingAverageStrategy as an example strategy
"""

import argparse
from datetime import datetime
from pathlib import Path

from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
from trading_bot.core.enums import Timeframe
from trading_bot.core.time_utils import utc_ts
from trading_bot.data.jsonl_provider import JSONLDataProvider
from trading_bot.strategy.base import create_strategy

TF_MAP = {tf.value: tf for tf in Timeframe}

def parse_date(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d").timestamp())

def main():
    ap = argparse.ArgumentParser(description="Backtest smc_crt on MT5 data")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--timeframe", default="5m", choices=[tf.value for tf in Timeframe])
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2023-12-31")
    ap.add_argument("--initial-cash", type=float, default=10_000.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--htf", default="4h", help="HTF bias timeframe (e.g. 4h)")
    ap.add_argument("--zone-tf", default="4h", help="Zone timeframe (e.g. 4h)")
    ap.add_argument("--ltf", default="5m", help="LTF confirmation timeframe (e.g. 5m)")
    args = ap.parse_args()

    # Initialize the JSONL data provider
    
    provider = JSONLDataProvider(
        symbol="XAUUSD",    
        timeframe=Timeframe.M5,
    )

    # Check provider health
    health = provider.health()
    print(f"Data Provider Health: {health}")

    if not health.get("ok"):
        print(f"Error: Data provider failed to load: {health.get('error')}")
        return

    # Get data range
    data_range = provider.data_range()
    print(f"\nData Range:")
    print(f"  Symbol: {data_range['symbol']}")
    print(f"  Timeframe: {data_range['timeframe']}")
    print(f"  Bars: {data_range['n_bars']}")

    # Create strategy
    strategy = create_strategy(
        "smc_crt",
        params={"htf": args.htf, "zone_tf": args.zone_tf, "ltf": args.ltf},
    )

    # Configure backtest
    cfg = BacktestConfig(
        symbol=args.symbol,
        timeframe=TF_MAP[args.timeframe],
        start=parse_date(args.start),
        end=parse_date(args.end),
        initial_cash=args.initial_cash,
        seed=args.seed,
    )

    # Run backtest
    print("\nRunning backtest...")
    runner = BacktestRunner(provider=provider)
    result = runner.run(strategy, cfg)

    # Print results
    print("\n=== STRATEGY DIAGNOSTICS ===")

    if hasattr(strategy, "diagnostics"):
        d = strategy.diagnostics()

        print(f"Total rejection records: {d['total_rejections']}")

        for reason, count in sorted(
            d["rejections"].items(),
            key=lambda x: x[1],
            reverse=True
            ):
            print(f"{reason:25} {count}")

    m = result.metrics
    if "error" in m:
        print(f"Backtest failed: {m['error']}")
        return

    print(f"\n=== {args.symbol} {args.timeframe} · {args.start} → {args.end} ===")
    print(f"Bars analyzed : {result.n_bars}")
    print(f"Trades        : {m['n_trades']}")
    print(f"Win rate      : {m['win_rate']:.1f}%")
    print(f"Profit factor : {m['profit_factor']:.2f}")
    print(f"Net profit    : ${m['total_pnl']:.2f}")
    print(f"Max drawdown  : {m['max_drawdown_pct']:.2f}%")
    print(f"Sharpe (R)    : {m['sharpe_r']:.2f}")
    print(f"Final equity  : ${result.final_equity:.2f}")

    provider.shutdown()


if __name__ == "__main__":
    main()
