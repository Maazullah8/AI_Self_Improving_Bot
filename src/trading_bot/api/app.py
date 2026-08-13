"""FastAPI application exposing the trading bot's state and controls.

Read-only by default (metrics, equity, journal, versions, reviews, signals,
heartbeats) plus a small set of explicit actions (run backtest, run review)
that operate on historical data only — never on live trading.
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from trading_bot.storage.memory import MemoryStore


class BacktestRequest(BaseModel):
    symbol: str = "XAUUSD"
    timeframe: str = "5m"
    start: int = 0
    end: int = 0
    initial_cash: float = 10_000.0
    strategy: str = "smc_crt"
    params: dict = {}
    seed: Optional[int] = 42


class ReviewRequest(BaseModel):
    strategy: str = "smc_crt"
    strategy_version: str = "v1.0"
    window_start: int = 0
    window_end: int = 0


def create_app(store: Optional[MemoryStore] = None, provider=None, live=None) -> FastAPI:
    store = store or MemoryStore()
    app = FastAPI(title="Autonomous Trading Bot", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "trading-bot"}

    @app.get("/api/live")
    def live_status():
        if live is None:
            return {"running": False, "detail": "live pipeline not enabled (start with --live)"}
        try:
            return live.status()
        except Exception as e:
            return {"running": True, "status": "down", "detail": f"status error: {e}"}

    @app.get("/api/metrics")
    def metrics():
        from trading_bot.backtest.metrics import compute_metrics

        trades = store.trades.list(limit=1000)
        # Reconstruct the equity curve from the journal: start at a nominal
        # initial balance and apply each trade's net P/L in exit-time order.
        initial = 10_000.0
        eq = [{"time": 0, "equity": initial}]
        running = initial
        for t in sorted(trades, key=lambda x: x.exit_time):
            running += t.pnl
            eq.append({"time": t.exit_time, "equity": running})
        return compute_metrics(eq, trades)

    @app.get("/api/trades")
    def trades(limit: int = Query(100, ge=1, le=5000)):
        return [t.to_dict() for t in store.trades.list(limit=limit)]

    @app.get("/api/signals")
    def signals(strategy: Optional[str] = None, limit: int = Query(100, ge=1, le=5000)):
        out = []
        for s in store.signals.list(strategy=strategy, limit=limit):
            d = dict(s.__dict__)
            out.append(d)
        return out

    @app.get("/api/heartbeats")
    def heartbeats(component: Optional[str] = None):
        if component:
            hb = store.heartbeats.latest(component)
            return hb.__dict__ if hb else {"error": "no heartbeat"}
        return []

    @app.get("/api/strategies")
    def strategies():
        return [s.to_dict() for s in store.strategies.list()]

    @app.get("/api/strategies/{name}/{version}")
    def strategy_get(name: str, version: str):
        rec = store.strategies.get(name, version)
        if rec is None:
            raise HTTPException(404, "strategy version not found")
        return rec.to_dict()

    @app.get("/api/reviews")
    def reviews(strategy: Optional[str] = None, limit: int = Query(50, ge=1, le=1000)):
        return [r.__dict__ for r in store.reviews.list(strategy=strategy, limit=limit)]

    @app.post("/api/backtest")
    def backtest(req: BacktestRequest):
        if provider is None:
            raise HTTPException(503, "no data provider configured")
        from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
        from trading_bot.core.enums import Timeframe
        from trading_bot.journal.journal import Journal
        from trading_bot.strategy.base import create_strategy
        from trading_bot.validation.pipeline import monte_carlo, run_walk_forward

        strategy = create_strategy(req.strategy, params=req.params)
        journal = Journal(store=store.trades, strategy_name=strategy.name, strategy_version=strategy.version)
        runner = BacktestRunner(provider, journal=journal)
        cfg = BacktestConfig(
            symbol=req.symbol,
            timeframe=Timeframe(req.timeframe),
            start=req.start,
            end=req.end,
            initial_cash=req.initial_cash,
            seed=req.seed,
        )
        result = runner.run(strategy, cfg)
        out = result.to_dict()
        # Monte Carlo resample of the trade R-distribution (deterministic for a
        # given trade series + seed).
        r_series = [t.r for t in result.trades]
        out["monte_carlo"] = monte_carlo(
            r_series,
            seed=req.seed or 0,
            initial_cash=req.initial_cash,
            return_paths=True,
        )
        out["walk_forward"] = _run_walk_forward(
            runner, strategy.name, strategy.get_params(), strategy.version, cfg, result.start, result.end
        )
        return out

    @app.post("/api/review")
    def review(req: ReviewRequest):
        from trading_bot.ai.review import AITradeReviewer

        trades = store.trades.list(strategy=req.strategy, limit=5000)
        rev = AITradeReviewer().review(
            trades, strategy=req.strategy, strategy_version=req.strategy_version,
            window_start=req.window_start, window_end=req.window_end,
        )
        store.reviews.insert(rev)
        return rev.__dict__

    return app


def _run_walk_forward(runner, strategy_name, params, version, base_cfg, res_start, res_end):
    """Run walk-forward analysis and shape it for the dashboard.

    Falls back to None when the data range cannot support multiple windows or
    the run fails (fail-closed: the caller simply omits the field).
    """
    from datetime import datetime, timezone

    from trading_bot.backtest.runner import BacktestConfig
    from trading_bot.validation.pipeline import run_walk_forward

    start = base_cfg.start if base_cfg.start > 0 else res_start
    end = base_cfg.end if base_cfg.end > 0 else res_end
    if start <= 0 or end <= 0 or end - start < 2 * 86400:
        return None
    base = BacktestConfig(
        symbol=base_cfg.symbol, timeframe=base_cfg.timeframe, start=start, end=end,
        initial_cash=base_cfg.initial_cash, seed=base_cfg.seed,
    )
    try:
        wf = run_walk_forward(runner, strategy_name, dict(params), version, base, n_windows=4)
    except Exception:
        return None
    if not wf.windows:
        return None

    def fmt(ts: int) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m")

    train_wr = wf.val_train_win_rate
    test_wr = wf.val_win_rate
    avg_test = (sum(test_wr) / len(test_wr)) if test_wr else 0.0
    positive = sum(1 for e in wf.val_expectancy_r if e > 0)
    consistency = 100.0 * positive / len(wf.val_expectancy_r) if wf.val_expectancy_r else 0.0
    generalization = round(min(max(avg_test, 0.0), 100.0), 1)
    return {
        "n_windows": len(wf.windows),
        "generalization_score": generalization,
        "consistency_pct": round(consistency, 1),
        "consistent": wf.consistent(),
        "segments": [
            {
                "segment": f"Segment {i + 1}",
                "range": f"{fmt(w.train_start)} to {fmt(w.train_end)}",
                "train_win_rate": round(train_wr[i], 1) if i < len(train_wr) else 0.0,
                "test_win_rate": round(test_wr[i], 1) if i < len(test_wr) else 0.0,
                "test_pf": round(wf.val_pf[i], 2) if i < len(wf.val_pf) else 0.0,
                "test_trades": wf.val_n_trades[i] if i < len(wf.val_n_trades) else 0,
            }
            for i, w in enumerate(wf.windows)
        ],
        "windows": {
            "training": f"{fmt(wf.windows[0].train_start)} to {fmt(wf.windows[-1].train_end)}",
            "validation": f"{fmt(wf.windows[0].val_start)} to {fmt(wf.windows[-1].val_end)}",
            "current_performance": f"{generalization}%",
        },
    }


def make_app(store: Optional[MemoryStore] = None, provider=None, live=None) -> FastAPI:
    return create_app(store=store, provider=provider, live=live)
