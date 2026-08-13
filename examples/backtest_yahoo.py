"""Backtest the smc_crt strategy on free Yahoo Finance data via yfinance.

Cross-platform (Windows / macOS / Linux), no MT5 terminal required.

Requirements
------------
    pip install yfinance      # or: pip install -e ".[yfinance]"

Usage
-----
    python -m examples.backtest_yahoo --symbol XAUUSD --timeframe H1 \
        --start 2024-01-01 --end 2024-06-30 --initial-cash 10000

XAUUSD maps to Yahoo ticker "GC=F" (COMEX gold futures) because Yahoo has no
spot-gold ticker. The provider is READ-ONLY and fail-closed: it raises a
RuntimeError if yfinance is missing or returns no data.
"""
from __future__ import annotations

import argparse
from datetime import datetime

from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
from trading_bot.core.enums import Timeframe
from trading_bot.core.time_utils import utc_ts
from trading_bot.data import YFinanceDataProvider
from trading_bot.strategy.base import create_strategy

TF_MAP = {tf.value: tf for tf in Timeframe}


def parse_date(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d").timestamp())


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest smc_crt on Yahoo Finance data")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--timeframe", default="1h", choices=[tf.value for tf in Timeframe])
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2024-06-30")
    ap.add_argument("--initial-cash", type=float, default=10_000.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--htf", default="4h", help="HTF bias timeframe (e.g. 4h)")
    ap.add_argument("--zone-tf", default="4h", help="Zone timeframe (e.g. 4h)")
    ap.add_argument("--ltf", default="1h", help="LTF confirmation timeframe (e.g. 1h)")
    args = ap.parse_args()

    provider = YFinanceDataProvider()

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


if __name__ == "__main__":
    main()
