# Architecture

This document describes the runtime and data flow of the autonomous trading
bot. Everything is written so the system can run unattended 24/7 while a human
retains final control over anything that touches real money.

## Data flow

```
                    ┌──────────────────────────────────────────────────────┐
                    │  DATA (normalized: ts, OHLC, volume, spread, ticks)  │
                    │  synthetic | CSV | Parquet | .bi5 | MT5(lazy)        │
                    └───────────────────────┬──────────────────────────────┘
                                            │ candles
                                            ▼
   strategy.on_bar(ctx) ──bars 0..i──▶ ReplayEngine / LivePipeline
      (zero lookahead)                        │ signal
                                            ▼
                                     RiskManager.approve()
                                       (RiskDecision)
                                            │ approved + size
                                            ▼
                          ReplayEngine.open_position (backtest)
                          Executor.submit_order (live/demo)
                                            │ fills / exits
                                            ▼
                                     Journal.record_trade()
                              (full setup context persisted)
                                            │ batch of TradeRecords
                                            ▼
                                 AI review + PatternDetector
                                            │ patterns + compliance
                                            ▼
                              CandidateGenerator (never mutates live)
                                            │ candidate versions
                                            ▼
                       Validation: splits, walk-forward, Monte Carlo
                                            │ PromotionGate
                                            ▼
                                PROMOTED → demo → live (supervised)
```

## Key invariants

1. **Zero lookahead**: a strategy sees only closed bars `0..i`; entry fills at
   the signal bar close (+ spread + slippage); same-bar SL+TP breach is assumed
   SL-first unless `optimistic_intrabar`.
2. **Determinism**: identical inputs + config ⇒ identical output. Randomness
   only via an explicit `seed`.
3. **Fail-closed**: every component that can be "unknown" (data stale, broker
   down, strategy raised, risk rejected, executor unhealthy) results in no trade.
4. **Versioning**: strategies are append-only; a candidate is a new version with
   a parent pointer. Rejected versions are kept. The live strategy is never
   mutated in place.
5. **Separation of powers**: the AI proposes (hypotheses, candidates) but never
   executes; risk controls are code, not suggestions.

## Modules

### `core`
Frozen dataclasses for `Candle`, `Tick`, `Order`, `Position`, `TradeRecord`;
enums (`Side`, `Timeframe`, `ExitReason`, `StrategyStatus`, ...); time utilities
(UTC epoch seconds, calendar-aligned W1/MN bars, market sessions).

### `data`
`DataProvider` ABC + `MarketDataQuery` + `SymbolInfo`. Implementations:
`SyntheticDataProvider` (seeded, realistic regimes), `FileDataProvider`
(CSV/Parquet, MT5-style timestamps), `Bi5DataProvider` (Dukascopy .bi5),
`MT5DataProvider` (lazy import, raises if terminal absent). `resample.py`
provides tick→candle aggregation and `IncrementalResampler` for streaming HTF
bars (used by the strategy to avoid O(n²) re-aggregation).

### `replay`
`ReplayEngine` is the deterministic simulator used by backtests. Tracks MFE/MAE,
partial exits, break-even and trailing stops, commissions and slippage. It never
imports `MetaTrader5`. `Context` exposes only the closed-bar history.

### `strategy`
`BaseStrategy` + `StrategyRegistry` (`create_strategy("smc_crt")`). The SMC/ICT/CRT
confluence strategy enforces its rules in code (no confirmation ⇒ no trade,
min 1:2 RR or reject, max 2 attempts per level, no chasing). It uses confirmed
fractal swings (lag is intentional, not lookahead) and incremental HTF state.

### `risk`
`RiskManager.approve(signal, bar, equity, positions) -> RiskDecision`. Checks:
emergency stop, equity sanity, max drawdown, daily loss, max positions/trades,
consecutive-loss cool-down, sessions, spread limit, SL/TP validity. Sizing is
risk-per-trade% converted to lots via contract size.

### `backtest` + `journal`
`BacktestRunner` wires provider → engine → strategy → risk, then builds
`TradeRecord`s and `compute_metrics` (win rate, expectancy, PF, Sharpe, Sortino,
drawdown, recovery, streaks, monthly returns, exit reasons). The `Journal`
attaches the full setup context captured at signal time.

### `ai`
`PatternDetector` segments trades by setup dimension and flags significant
over/under-performers. `AITradeReviewer` computes rule compliance and produces a
`ReviewRecord` with a hypothesis (deterministic template; optional LLM hook).
`CandidateGenerator` turns evidence into new param versions.

### `validation`
`time_split`, `run_walk_forward` (rolling train→validate with fresh strategy
instances), `monte_carlo` (seeded resampling of the R series: final equity
percentiles, drawdown tail, risk of ruin), and `PromotionGate` (every gate must
pass; candidate must beat baseline).

### `execution` + `live`
`SimulatedExecutor` (paper) and `MT5Executor` (demo, fail-closed when the
terminal is unavailable). `LiveTradePipeline` is the stateful live loop:
fetch fresh closed bars → strategy → risk → executor, with heartbeats and
signal recording. `PipelineSupervisor` is the watchdog (heartbeat timeout,
bounded restart with backoff, health checks).

### `storage` + `api`
`Store` protocols (strategies, trades, signals, heartbeats, reviews) with
`MemoryStore` (tests/dev) and `PostgresStore`/Supabase (production).
`api.app` is a FastAPI app: read-only metrics/trades/versions/reviews plus
explicit backtest/review actions. `dashboard/` is a Next.js app that proxies
`/api` to the backend.

## Configuration
- Backtest/risk knobs live in `BacktestConfig` / `RiskConfig` dataclasses.
- Strategy parameters live in `SMCParams` and drive versioning.
- `pyproject.toml` declares dependencies and pytest configuration.
