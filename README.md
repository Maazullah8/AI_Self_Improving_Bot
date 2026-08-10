# Autonomous Self-Improving Trading Bot

A production-grade research framework for an autonomous 24/7 AI self-improving
trading bot. It covers the full loop: **data → replay → strategy → risk →
execution → journal → AI review → pattern detection → hypothesis →
candidate strategy → backtest → validation → walk-forward → Monte Carlo →
promotion → demo → live → monitoring → learning**.

> **Warning**: This is a research system. The SMC strategy is a *hypothesis*,
> not a guarantee of profitability. Nothing here is financial advice, and no
> component trades real money without explicit, reviewed promotion.

## Principles (enforced in code)

| Priority | Principle |
|---|---|
| 1 | **Correctness** — deterministic, data-source-agnostic; normalized format = `timestamp, OHLC, volume, spread, ticks` |
| 2 | **Safety** — fail-closed: stale data, unhealthy broker, invalid strategy/AI, or unknown state ⇒ **no trade** |
| 3 | **Testing** — every layer unit-tested; no claiming something works without running it |
| 4 | **Reproducibility** — seeded randomness, versioned strategies, immutable trade records |
| 5 | **Risk** — AI can propose candidates but can never override risk controls |
| 6 | **Reliability** — supervisor/heartbeat/watchdog keeps the pipeline alive |
| 7 | **Intelligence** — evidence-based hypotheses from batched pattern detection |
| 8 | **Automation** — the full loop runs unattended |

Zero-lookahead guarantees: a strategy at bar `i` sees only bars `0..i`; entries
fill at the signal bar's close (with spread + slippage); a same-bar SL+TP
breach is conservatively assumed SL-first.

## Quick start

```bash
# run the full test suite (Python 3.10+)
PYTHONPATH=src python3 -m pytest tests/ -q

# run the end-to-end self-improvement demo (synthetic data, no broker)
PYTHONPATH=src python3 -m demo.run_demo

# run the dashboard API server (FastAPI)
PYTHONPATH=src python3 -m trading_bot.api.run
# then, in another terminal:
cd dashboard && npm install && npm run dev
```

The Next.js dev server proxies `/api/*` to the FastAPI backend on `:8000`
(see `dashboard/next.config.js`). The dashboard shows performance metrics,
recent trades, strategy versions and AI reviews.

## Architecture

```
src/trading_bot/
  core/        domain models, enums, time/session utilities (dependency-free)
  data/        providers: synthetic, CSV/Parquet, Dukascopy .bi5, MT5 (lazy, fail-closed)
               + tick→candle aggregation, incremental resampling
  strategy/    base classes + registry + SMC/ICT/CRT confluence strategy (smc_crt v1.0)
  replay/      deterministic, zero-lookahead backtest engine (never imports MT5)
  risk/        risk manager: per-trade size, daily loss, drawdown, sessions,
               spread/slippage limits, emergency stop; returns RiskDecision
  backtest/    runner (provider→engine→strategy→risk) + performance metrics
  journal/     trade journal: full setup context persisted per trade
  ai/          pattern detection (batched), AI review, candidate generation
  validation/  time splits, walk-forward, Monte Carlo, promotion gates
  execution/   simulated + MT5 (demo) executors, fail-closed
  live/        live pipeline (stateful strategy + risk + executor) + supervisor
  storage/     store protocols + in-memory + PostgreSQL/Supabase implementations
  api/         FastAPI application + run entry point

dashboard/     Next.js monitoring frontend (proxies /api to the backend)
demo/          end-to-end demo: backtest → review → candidates → validation
```

## The self-improvement loop

1. **Backtest** a strategy version over historical data (replay engine + risk).
2. **Journal** every trade with the full setup context (bias, zone, confluence,
   confirmation, CHoCH/CSD, entry/SL/TP, spread, volatility, session, MFE/MAE).
3. **Review** the batch deterministically: rule compliance + segment patterns.
4. **Hypothesize** (template-based; optional LLM hook, never a hard dependency).
5. **Generate candidates** — new parameter versions. The live strategy is never
   mutated; rejected versions are kept for reference.
6. **Validate**: train/validation/final-test time splits, walk-forward
   consistency, seeded Monte Carlo (drawdown, streaks, risk of ruin).
7. **Promote** only if every gate passes (trade count, PF, expectancy, win rate,
   drawdown, MC tails, beats baseline).
8. **Run** the promoted version in demo → live via the supervisor, journaling
   continues, so the loop repeats.

## Fail-closed rules

- No data / stale data ⇒ no signal.
- Strategy raises ⇒ no trade (error is recorded).
- Risk manager rejects ⇒ no trade.
- Executor/broker unhealthy ⇒ order rejected.
- MT5 unavailable ⇒ `MT5DataProvider`/`MT5Executor` refuse to operate.

## Strategy rules enforced in code

- No confirmation ⇒ no trade.
- Minimum 1:2 risk:reward; reject if the geometry cannot yield it (no fake TP).
- Max 2 attempts per level; attempt 2 needs a genuine sweep + fresh confirmation.
- Never chase a missed setup.
- Missing any mandatory condition ⇒ no trade.

## Data formats

Normalized candle: `time (epoch s), open, high, low, close, volume, spread`.
Tick: `time, bid, ask, volume`. Providers (CSV, Parquet, .bi5, MT5, synthetic)
all normalize into these; backtests are data-source agnostic.

## Development

```bash
PYTHONPATH=src python3 -m pytest tests/ -q          # all tests
PYTHONPATH=src python3 -m pytest tests/test_demo.py # E2E loop (slow mark)
```

Optional extras: `pip install fastapi uvicorn` (API), `psycopg`/`supabase` (DB),
`MetaTrader5` (live/demo execution).
