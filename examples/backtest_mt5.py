"""Backtest the smc_crt strategy on real market data pulled from a running
MetaTrader 5 terminal.

Requirements
------------
* Windows (the MT5 terminal only runs on Windows)
* MetaTrader 5 terminal installed and logged into an account (demo is fine)
* ``pip install MetaTrader5``
* At least one symbol in Market Watch (e.g. EURUSD) with history downloaded

Usage
-----
    python -m examples.backtest_mt5 --symbol XAUUSD --timeframe H1 \
        --start 2023-01-01 --end 2023-12-31 --initial-cash 10000

The MT5 provider is READ-ONLY: this script only copies bars; it never places
orders. MT5DataProvider raises if the terminal isn't available (fail-closed).
"""
from __future__ import annotations

import argparse
from datetime import datetime

from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
from trading_bot.core.enums import Timeframe
from trading_bot.core.time_utils import utc_ts
from trading_bot.data.mt5_provider import MT5DataProvider
from trading_bot.strategy.base import create_strategy

TF_MAP = {tf.value: tf for tf in Timeframe}


def parse_date(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d").timestamp())


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest smc_crt on MT5 data")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--timeframe", default="M5", choices=[tf.value for tf in Timeframe])
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2023-12-31")
    ap.add_argument("--initial-cash", type=float, default=10_000.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--htf", default="4h", help="HTF bias timeframe (e.g. 4h)")
    ap.add_argument("--zone-tf", default="4h", help="Zone timeframe (e.g. 4h)")
    ap.add_argument("--ltf", default="5m", help="LTF confirmation timeframe (e.g. 5m)")
    args = ap.parse_args()

    provider = MT5DataProvider()

    strategy = create_strategy(
        "smc_crt",
        params={"htf": args.htf, "zone_tf": args.zone_tf, "ltf": args.ltf},
    )

    cfg = BacktestConfig(
        symbol=args.symbol,
        timeframe=TF_MAP[args.timeframe],
        start=parse_date(args.start),
        end=parse_date(args.end),
        initial_cash=args.initial_cash,
        seed=args.seed,
    )

    runner = BacktestRunner(provider)
    result = runner.run(strategy, cfg)

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
