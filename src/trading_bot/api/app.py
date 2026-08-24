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

import threading
import uuid

from trading_bot.storage.memory import MemoryStore

# In-memory registry of running/finished backtest jobs (the dashboard
# polls progress, watches live equity and can cancel long runs).
_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


def _json_safe(obj):
    """Recursively replace inf/nan floats with None.

    Metrics such as profit_factor become ``inf`` when a strategy has no
    losing trades; strict JSON cannot represent them, which crashed the
    job-status endpoint with a 500.
    """
    import math

    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
        return None
    return obj
# Risk-rejection audit trail of the most recent backtest run (Section 11).
_LAST_RISK_REJECTIONS: list = []


class BacktestRequest(BaseModel):
    symbol: str = "XAUUSD"
    timeframe: str = "5m"
    start: int = 0
    end: int = 0
    initial_cash: float = 10_000.0
    strategy: str = "smc_crt"
    params: dict = {}
    seed: Optional[int] = 42
    # Only used when the active data source is the synthetic feed.
    initial_price: float = 0.0


class ReviewRequest(BaseModel):
    strategy: str = "smc_crt"
    strategy_version: str = "v1.0"
    window_start: int = 0
    window_end: int = 0


class ExperimentCreate(BaseModel):
    """Open a new experiment: one proposed change under investigation."""

    strategy: str = "smc_crt"
    parent_version: str = ""          # baseline being questioned
    candidate_version: str = ""       # filled when a candidate exists
    hypothesis: str = ""
    reason: str = ""                  # observed weakness
    change_description: str = ""      # exact rule/parameter changed
    expected_effect: str = ""
    dataset_start: int = 0             # overfitting guard (Section 16)
    dataset_end: int = 0


class ExperimentDecision(BaseModel):
    decision: str  # promoted | rejected | rolled_back | running
    reason: str = ""
    actual_effect: str = ""
    candidate_version: str = ""
    backtest_results: dict = {}
    walk_forward_results: dict = {}
    monte_carlo_results: dict = {}
    comparison_results: dict = {}


class ExperimentCompareRequest(BaseModel):
    """Range used to run baseline vs candidate head-to-head."""

    symbol: str = "XAUUSD"
    timeframe: str = "5m"
    start: int = 0
    end: int = 0
    initial_cash: float = 10_000.0
    seed: Optional[int] = 42
    # optional explicit params when no stored candidate version exists yet
    candidate_params: dict = {}


class ExperimentRollbackRequest(BaseModel):
    reason: str = ""


class PaperStartRequest(BaseModel):
    """Paper/demo validation plan for a promoted candidate (Section 13)."""

    expected_win_rate: Optional[float] = None  # from the backtest
    min_trades: int = 10
    max_win_rate_dev_pct: float = 15.0
    min_expectancy_r: float = 0.0
    max_avg_spread_points: Optional[float] = None
    point_size: float = 0.0001


class PaperEvaluateRequest(BaseModel):
    auto_rollback: bool = True  # failed paper => candidate rolled back


class OptimizeRunRequest(BaseModel):
    """One AI-optimizer cycle over a dataset window (Section 15/16)."""

    strategy: str = "smc_crt"
    symbol: str = "XAUUSD"
    timeframe: str = "5m"
    dataset_start: int = 0
    dataset_end: int = 0
    initial_cash: float = 10_000.0
    seed: int = 42
    min_trades: int = 20
    auto_backtest: bool = True


class ModelConfigRequest(BaseModel):
    provider: str = "openai"  # ollama|openai|openrouter|groq|anthropic|gemini|custom
    label: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    is_active: bool = False


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

    @app.get("/api/regimes")
    def regimes(limit: int = 5000):
        """Strategy performance grouped by market regime (Section 7).

        Shows where the strategy performs well or poorly. Finding here is an
        OBSERVATION only — acting on it requires a validated experiment.
        """
        from collections import defaultdict

        trades = store.trades.list(limit=limit)
        groups: dict = defaultdict(list)
        for t in trades:
            groups[(t.regime or "unknown").strip() or "unknown"].append(t)

        out = []
        for regime in sorted(groups):
            ts = groups[regime]
            n = len(ts)
            wins = sum(1 for t in ts if t.pnl > 0)
            gross_w = sum(t.pnl for t in ts if t.pnl > 0)
            gross_l = -sum(t.pnl for t in ts if t.pnl < 0)
            out.append({
                "regime": regime,
                "trades": n,
                "win_rate": round(100.0 * wins / n, 1) if n else 0.0,
                "avg_r": round(sum(t.r for t in ts) / n, 3) if n else 0.0,
                "total_pnl": round(sum(t.pnl for t in ts), 2),
                "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else None,
            })
        return {"regimes": out}

    @app.get("/api/experiments")
    def experiments_list(
        strategy: Optional[str] = None,
        limit: int = Query(100, ge=1, le=1000),
    ):
        """Permanent experiment history (Section 3) — newest first."""
        rows = store.experiments.list(strategy=strategy, limit=limit)
        return [r.to_dict() for r in reversed(rows)]

    @app.post("/api/experiments")
    def experiments_create(req: ExperimentCreate):
        n = len(store.experiments.list(limit=100000))
        rec_id = f"EXP-{n + 1}"
        from trading_bot.storage.interfaces import ExperimentRecord, utcnow_iso

        rec = store.experiments.create(
            ExperimentRecord(
                id=rec_id,
                strategy=req.strategy,
                parent_version=req.parent_version,
                candidate_version=req.candidate_version,
                hypothesis=req.hypothesis,
                reason=req.reason,
                change_description=req.change_description,
                expected_effect=req.expected_effect,
                dataset_start=req.dataset_start,
                dataset_end=req.dataset_end,
            )
        )
        # Section 16 overfitting guard: flag repeated optimisation against
        # the same dataset period from the same baseline.
        same_dataset = [
            e
            for e in store.experiments.list(strategy=req.strategy)
            if e.id != rec.id
            and e.parent_version == req.parent_version
            and e.dataset_start == req.dataset_start
            and e.dataset_end == req.dataset_end
        ]
        resp = rec.to_dict()
        if len(same_dataset) >= 2:
            resp["overfit_warning"] = (
                f"{len(same_dataset)} prior experiments already target the "
                "same dataset period from this baseline. Prefer fresh "
                "out-of-sample evidence before another change."
            )
        return resp

    @app.get("/api/experiments/{experiment_id}")
    def experiments_get(experiment_id: str):
        rec = store.experiments.get(experiment_id)
        if rec is None:
            raise HTTPException(404, "experiment not found")
        return rec.to_dict()

    @app.post("/api/experiments/{experiment_id}/decision")
    def experiments_decision(experiment_id: str, req: ExperimentDecision):
        """Record the final decision with its evidence (Section 12)."""
        allowed = {"promoted", "rejected", "rolled_back", "running"}
        if req.decision not in allowed:
            raise HTTPException(422, f"decision must be one of {sorted(allowed)}")
        fields = {
            "decision": req.decision,
            "decision_reason": req.reason,
            "actual_effect": req.actual_effect,
        }
        if req.candidate_version:
            fields["candidate_version"] = req.candidate_version
        for key, val in (
            ("backtest_results", req.backtest_results),
            ("walk_forward_results", req.walk_forward_results),
            ("monte_carlo_results", req.monte_carlo_results),
            ("comparison_results", req.comparison_results),
        ):
            if val:
                fields[key] = val
        updated = store.experiments.update(experiment_id, **fields)
        if updated is None:
            raise HTTPException(404, "experiment not found")
        return updated.to_dict()

    @app.post("/api/experiments/{experiment_id}/compare")
    def experiments_compare(experiment_id: str, req: ExperimentCompareRequest):
        """Run CURRENT (parent) vs CANDIDATE head-to-head over one range and
        store the evidence on the experiment (Section 9)."""
        from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
        from trading_bot.core.enums import StrategyStatus, Timeframe
        from trading_bot.strategy.base import create_strategy
        from trading_bot.validation.pipeline import PromotionGate, compare_results

        exp = store.experiments.get(experiment_id)
        if exp is None:
            raise HTTPException(404, "experiment not found")

        parent_rec = store.strategies.get(exp.strategy, exp.parent_version)
        cand_rec = (
            store.strategies.get(exp.strategy, exp.candidate_version)
            if exp.candidate_version
            else None
        )
        parent_params = parent_rec.params if parent_rec else {}
        cand_params = (
            cand_rec.params if cand_rec is not None else (req.candidate_params or {})
        )
        if not cand_params:
            raise HTTPException(
                422,
                "no candidate parameters available (create a candidate version "
                "or pass candidate_params)",
            )

        tf = Timeframe(req.timeframe)
        runner = BacktestRunner(provider.resample(tf))
        cfg = BacktestConfig(
            symbol=req.symbol,
            timeframe=tf,
            start=req.start,
            end=req.end,
            initial_cash=req.initial_cash,
            seed=req.seed,
        )
        baseline_res = runner.run(
            create_strategy(exp.strategy, params=dict(parent_params),
                            version=exp.parent_version or "baseline"),
            cfg,
        )
        candidate_res = runner.run(
            create_strategy(exp.strategy, params=dict(cand_params),
                            version=exp.candidate_version or "candidate"),
            cfg,
        )
        comparison = compare_results(baseline_res, candidate_res)

        # Independent promotion-gate verdict for visibility (NOT applied here).
        gate = PromotionGate().evaluate(candidate_res, baseline_res, seed=req.seed or 0)
        comparison["promotion_gate"] = gate.to_dict()

        update_fields = {
            "backtest_results": {
                "baseline": {
                    "n_trades": baseline_res.n_trades,
                    "final_equity": round(baseline_res.final_equity, 2),
                },
                "candidate": {
                    "n_trades": candidate_res.n_trades,
                    "final_equity": round(candidate_res.final_equity, 2),
                },
            },
        }
        if exp.candidate_version:
            update_fields["candidate_version"] = exp.candidate_version
        elif req.candidate_params:
            update_fields["candidate_version"] = "candidate(params)"
        update_fields["comparison_results"] = _json_safe(comparison)
        store.experiments.update(experiment_id, **update_fields)
        return {
            "experiment_id": experiment_id,
            "comparison": _json_safe(comparison),
        }

    @app.post("/api/experiments/{experiment_id}/rollback")
    def experiments_rollback(experiment_id: str, req: ExperimentRollbackRequest):
        """Roll a promoted candidate back to its baseline (Section 14).

        Both versions keep their full history; the reason is recorded on the
        experiment. The AI can never do this silently.
        """
        from trading_bot.core.enums import StrategyStatus

        exp = store.experiments.get(experiment_id)
        if exp is None:
            raise HTTPException(404, "experiment not found")
        if exp.decision != "promoted":
            raise HTTPException(
                422,
                f"only promoted experiments can be rolled back "
                f"(current decision: {exp.decision})",
            )
        if not exp.candidate_version:
            raise HTTPException(422, "experiment has no candidate version to roll back")

        cand = store.strategies.get(exp.strategy, exp.candidate_version)
        if cand is None:
            raise HTTPException(
                404, f"candidate version {exp.candidate_version} not found"
            )
        cand = store.strategies.update(
            exp.strategy, exp.candidate_version,
            status=StrategyStatus.ROLLED_BACK.value,
        )
        baseline_status = None
        baseline = store.strategies.get(exp.strategy, exp.parent_version)
        if baseline is not None:
            baseline = store.strategies.update(
                exp.strategy, exp.parent_version,
                status=StrategyStatus.LIVE.value,
            )
            baseline_status = baseline.status

        updated = store.experiments.update(
            experiment_id,
            decision="rolled_back",
            decision_reason=req.reason
            or f"Rolled back {exp.candidate_version} to {exp.parent_version}",
        )
        return {
            "experiment": updated.to_dict(),
            "candidate_status": cand.status,
            "baseline_status": baseline_status,
        }

    @app.post("/api/experiments/{experiment_id}/paper/start")
    def paper_start(experiment_id: str, req: PaperStartRequest):
        """Move a validated candidate into PAPER/DEMO stage (Section 13).

        Records the expectations it must meet in forward operation. The
        candidate is NOT live yet — its strategy version status becomes 'demo'.
        """
        from trading_bot.core.enums import StrategyStatus

        exp = store.experiments.get(experiment_id)
        if exp is None:
            raise HTTPException(404, "experiment not found")
        if exp.decision == "promoted":
            raise HTTPException(422, "experiment already promoted")
        if not exp.candidate_version:
            raise HTTPException(422, "experiment has no candidate version")
        cand = store.strategies.get(exp.strategy, exp.candidate_version)
        if cand is None:
            raise HTTPException(
                404, f"candidate version {exp.candidate_version} not found"
            )

        expected = {}
        if req.expected_win_rate is not None:
            expected["win_rate"] = req.expected_win_rate
        cand_test_results = dict(cand.test_results or {})
        cand_test_results["paper"] = {
            "expected": expected,
            "min_trades": req.min_trades,
            "max_win_rate_dev_pct": req.max_win_rate_dev_pct,
            "min_expectancy_r": req.min_expectancy_r,
            "max_avg_spread_points": req.max_avg_spread_points,
            "point_size": req.point_size,
        }
        store.strategies.update(
            exp.strategy, exp.candidate_version,
            status=StrategyStatus.DEMO.value,
            test_results=cand_test_results,
        )
        updated = store.experiments.update(
            experiment_id,
            decision_reason=f"entered paper/demo validation ({req.min_trades} trades min)",
        )
        return {
            "experiment": updated.to_dict(),
            "candidate_status": StrategyStatus.DEMO.value,
        }

    @app.get("/api/experiments/{experiment_id}/paper")
    def paper_status(experiment_id: str):
        """Current paper/demo report: expectation vs realised so far."""
        from trading_bot.core.enums import StrategyStatus
        from trading_bot.validation.pipeline import evaluate_paper

        exp = store.experiments.get(experiment_id)
        if exp is None:
            raise HTTPException(404, "experiment not found")
        cand = store.strategies.get(exp.strategy, exp.candidate_version)
        plan = (cand.test_results or {}).get("paper", {}) if cand else {}
        demo_trades = [
            t for t in store.trades.list(strategy=exp.strategy, limit=5000)
            if t.strategy_version == exp.candidate_version
        ]
        report = (
            evaluate_paper(
                demo_trades,
                expected=plan.get("expected", {}),
                min_trades=plan.get("min_trades", 10),
                max_win_rate_dev_pct=plan.get("max_win_rate_dev_pct", 15.0),
                min_expectancy_r=plan.get("min_expectancy_r", 0.0),
                max_avg_spread_points=plan.get("max_avg_spread_points"),
                point_size=plan.get("point_size", 0.0001),
            )
            if plan
            else {"passed": False, "checks": {}, "actual": {}}
        )
        return {
            "experiment_id": experiment_id,
            "candidate_version": exp.candidate_version,
            "candidate_status": cand.status if cand else "",
            "in_paper": bool(cand and cand.status == StrategyStatus.DEMO.value),
            "report": report,
        }

    @app.post("/api/experiments/{experiment_id}/paper/evaluate")
    def paper_evaluate(experiment_id: str, req: PaperEvaluateRequest):
        """Final paper-stage decision: promote to LIVE or roll back (Section 13)."""
        from trading_bot.core.enums import StrategyStatus
        from trading_bot.validation.pipeline import evaluate_paper

        exp = store.experiments.get(experiment_id)
        if exp is None:
            raise HTTPException(404, "experiment not found")
        cand = store.strategies.get(exp.strategy, exp.candidate_version)
        if cand is None:
            raise HTTPException(404, f"candidate version {exp.candidate_version} not found")

        plan = (cand.test_results or {}).get("paper", {})
        if not plan:
            raise HTTPException(
                422, "paper stage was never started for this experiment"
            )

        demo_trades = [
            t for t in store.trades.list(strategy=exp.strategy, limit=5000)
            if t.strategy_version == exp.candidate_version
        ]
        report = evaluate_paper(
            demo_trades,
            expected=plan.get("expected", {}),
            min_trades=plan.get("min_trades", 10),
            max_win_rate_dev_pct=plan.get("max_win_rate_dev_pct", 15.0),
            min_expectancy_r=plan.get("min_expectancy_r", 0.0),
            max_avg_spread_points=plan.get("max_avg_spread_points"),
            point_size=plan.get("point_size", 0.0001),
        )

        baseline = store.strategies.get(exp.strategy, exp.parent_version)
        new_test_results = {**cand.test_results, "paper_result": report}
        if report["passed"]:
            cand = store.strategies.update(
                exp.strategy, exp.candidate_version,
                status=StrategyStatus.LIVE.value,
                test_results=new_test_results,
            )
            if baseline is not None:
                store.strategies.update(
                    exp.strategy, exp.parent_version,
                    status=StrategyStatus.PROMOTED.value,
                )
            updated = store.experiments.update(
                experiment_id,
                decision="promoted",
                decision_reason="passed paper/demo validation",
                actual_effect=str(report["actual"]),
            )
            new_status = StrategyStatus.LIVE.value
        else:
            cand = store.strategies.update(
                exp.strategy, exp.candidate_version,
                status=(
                    StrategyStatus.ROLLED_BACK.value
                    if req.auto_rollback
                    else StrategyStatus.REJECTED.value
                ),
                test_results=new_test_results,
            )
            baseline = store.strategies.get(exp.strategy, exp.parent_version)
            if baseline is not None:
                store.strategies.update(
                    exp.strategy, exp.parent_version,
                    status=StrategyStatus.LIVE.value,
                )
            updated = store.experiments.update(
                experiment_id,
                decision="rolled_back" if req.auto_rollback else "rejected",
                decision_reason=f"failed paper/demo validation: {report['checks']}",
                actual_effect=str(report["actual"]),
            )
            new_status = cand.status

        return {
            "report": report,
            "decision": updated.decision,
            "decision_reason": updated.decision_reason,
            "candidate_status": new_status,
            "baseline_status": (
                baseline.status if baseline is not None else None
            ),
        }

    @app.get("/api/risk/rejections")
    def risk_rejections(limit: int = Query(100, ge=1, le=500)):
        """Risk-rejection audit trail of the most recent backtest run."""
        return {
            "count": len(_LAST_RISK_REJECTIONS),
            "rejections": list(reversed(_LAST_RISK_REJECTIONS[-limit:])),
        }

    @app.post("/api/optimize/run")
    def optimize_run(req: OptimizeRunRequest):
        """One self-improvement cycle: review trades -> detect weakness ->
        propose minimal change -> candidate version + experiment -> optional
        head-to-head backtest. NEVER activates anything (Section 15/24)."""
        from trading_bot.ai.optimizer import run_optimizer_cycle

        if req.auto_backtest and provider is None:
            raise HTTPException(503, "no data provider configured")
        summary = run_optimizer_cycle(
            store,
            provider,
            strategy=req.strategy,
            dataset_start=req.dataset_start,
            dataset_end=req.dataset_end,
            symbol=req.symbol,
            timeframe=req.timeframe,
            initial_cash=req.initial_cash,
            seed=req.seed,
            min_trades=req.min_trades,
            auto_backtest=req.auto_backtest,
        )
        return _json_safe(summary)

    @app.get("/api/data-range")
    def data_range(symbol: str = "XAUUSD", timeframe: str = "5m"):
        """The provider's available date span for the requested symbol/timeframe."""
        if provider is None:
            raise HTTPException(503, "no data provider configured")
        from trading_bot.core.enums import Timeframe
        from trading_bot.data.base import MarketDataQuery

        tf = Timeframe(timeframe)
        try:
            bars = provider.resample(tf).load_candles(
                MarketDataQuery(symbol=symbol, timeframe=tf)
            )
        except Exception as e:
            raise HTTPException(503, f"provider error: {e}")
        if not bars:
            return {"symbol": symbol, "timeframe": timeframe, "start": 0, "end": 0, "n_bars": 0}
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "start": bars[0].time,
            "end": bars[-1].time,
            "n_bars": len(bars),
        }

    @app.get("/api/data-source")
    def data_source(symbol: str = "XAUUSD", timeframe: str = "5m"):
        """Where backtest data comes from: provider chain, file paths / table
        URLs, health and the covered date range. Powers the Data Source card
        on the dashboard's Backtesting page."""
        if provider is None:
            raise HTTPException(503, "no data provider configured")

        from pathlib import Path as _Path

        def describe(p):
            info = {"name": getattr(p, "name", type(p).__name__)}
            path = getattr(p, "path", None)
            if path is not None:
                info["path"] = str(path)
                info["folder"] = str(_Path(path).parent)
            url = getattr(p, "url", None)
            if url:
                info["url"] = url
                info["table"] = getattr(p, "table", "")
                info["configured"] = bool(getattr(p, "configured", True))
            label = getattr(p, "source_label", None)
            if isinstance(label, str):
                info["source_label"] = label
            try:
                h = p.health()
                for k in ("ok", "source_label", "count", "latest_time", "error"):
                    if k in h:
                        info[k] = h[k]
            except Exception as e:
                info["health_error"] = str(e)
            return info

        chain = list(getattr(provider, "providers", None) or [provider])
        try:
            active = getattr(provider, "active_provider", lambda: None)()
        except Exception:
            active = None
        try:
            rng = data_range(symbol=symbol, timeframe=timeframe)
        except Exception:
            rng = {"symbol": symbol, "timeframe": timeframe, "start": 0, "end": 0, "n_bars": 0}

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "active": active,
            "providers": [describe(p) for p in chain],
            "range": rng,
        }

    @app.get("/api/models")
    def models_list():
        return [m.to_dict() for m in store.models.list()]

    @app.post("/api/models")
    def models_upsert(req: ModelConfigRequest):
        from trading_bot.storage.interfaces import ModelConfigRecord

        rec = store.models.upsert(
            ModelConfigRecord(
                provider=req.provider,
                label=req.label or req.provider,
                base_url=req.base_url,
                api_key=req.api_key,
                model=req.model,
                is_active=req.is_active,
            )
        )
        return rec.to_dict()

    @app.delete("/api/models/{model_id}")
    def models_delete(model_id: str):
        if not store.models.delete(model_id):
            raise HTTPException(404, "model not found")
        return {"ok": True}

    @app.post("/api/models/{model_id}/activate")
    def models_activate(model_id: str):
        rec = store.models.set_active(model_id)
        if rec is None:
            raise HTTPException(404, "model not found")
        return rec.to_dict()

    @app.post("/api/models/{model_id}/test")
    def models_test(model_id: str):
        """Probe the model server (Ollama or an online API key endpoint)."""
        from trading_bot.ai.llm import llm_from_config

        rec = store.models.get(model_id)
        if rec is None:
            raise HTTPException(404, "model not found")
        llm = llm_from_config(rec)
        if llm is None:
            return {"ok": False, "error": "model is not configured (missing API key / model name)"}
        return llm.ping()

    def _execute_backtest(req: BacktestRequest, cancel_check=None, on_progress=None):
        """Shared execution used by /api/backtest and the async job runner."""
        from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
        from trading_bot.core.enums import Timeframe
        from trading_bot.journal.journal import Journal
        from trading_bot.strategy.base import create_strategy
        from trading_bot.validation.pipeline import monte_carlo

        prov = provider
        # Allow overriding the starting price on the synthetic feed.
        if req.initial_price > 0 and type(prov).__name__ == "SyntheticDataProvider":
            from trading_bot.data.synthetic import SyntheticDataProvider

            prov = SyntheticDataProvider(
                symbol=req.symbol,
                seed=prov.seed,
                start=prov.start,
                end=prov.end,
                tf=Timeframe(req.timeframe),
                initial_price=req.initial_price,
                volatility=prov.volatility,
                trend_cycles=prov.trend_cycles,
            )

        strategy = create_strategy(req.strategy, params=req.params)
        journal = Journal(store=store.trades, strategy_name=strategy.name, strategy_version=strategy.version)
        tf = Timeframe(req.timeframe)
        # Honor the requested timeframe: multi-timeframe providers return self,
        # single-timeframe providers (synthetic) resample to the target bars.
        runner = BacktestRunner(prov.resample(tf), journal=journal)
        cfg = BacktestConfig(
            symbol=req.symbol,
            timeframe=tf,
            start=req.start,
            end=req.end,
            initial_cash=req.initial_cash,
            seed=req.seed,
        )
        result = runner.run(
            strategy, cfg, cancel_check=cancel_check, on_progress=on_progress
        )
        global _LAST_RISK_REJECTIONS
        _LAST_RISK_REJECTIONS = list(result.meta.get("risk_rejections", []))
        out = result.to_dict()
        cancelled = bool(result.meta.get("cancelled"))
        out["cancelled"] = cancelled
        if not cancelled:
            r_series = [t.r for t in result.trades]
            out["monte_carlo"] = monte_carlo(
                r_series,
                seed=req.seed or 0,
                initial_cash=req.initial_cash,
                return_paths=True,
            )
            # Walk-forward analytics must never take the endpoint down.
            try:
                out["walk_forward"] = _run_walk_forward(
                    prov, strategy.name, strategy.get_params(), strategy.version, cfg, result.start, result.end
                )
            except Exception as exc:
                print(f"walk-forward failed (ignored): {exc}", flush=True)
                out["walk_forward"] = None
        else:
            # Cancelled run: return everything up to the cancellation point.
            out["monte_carlo"] = None
            out["walk_forward"] = None
        return out

    @app.post("/api/backtest")
    def backtest(req: BacktestRequest):
        if provider is None:
            raise HTTPException(503, "no data provider configured")
        return _json_safe(_execute_backtest(req))

    @app.post("/api/backtest/async")
    def backtest_async(req: BacktestRequest):
        """Start a backtest in a background thread; the dashboard polls the
        returned job id for live equity/progress and can cancel any time."""
        if provider is None:
            raise HTTPException(503, "no data provider configured")
        job_id = uuid.uuid4().hex[:12]
        cancel_event = threading.Event()
        state = {
            "job_id": job_id,
            "status": "running",
            "progress": {},
            "result": None,
            "error": None,
            "cancel": cancel_event,
        }
        with _JOBS_LOCK:
            _JOBS[job_id] = state

        def worker():
            try:
                result = _execute_backtest(
                    req,
                    cancel_check=cancel_event.is_set,
                    on_progress=lambda snap: state.update(progress=snap),
                )
                state["result"] = _json_safe(result)
                state["progress"] = {}
                state["status"] = "cancelled" if result.get("cancelled") else "done"
            except Exception as exc:
                state["status"] = "error"
                state["error"] = f"{type(exc).__name__}: {exc}"

        threading.Thread(target=worker, name=f"backtest-{job_id}", daemon=True).start()
        return {"job_id": job_id}

    @app.get("/api/backtest/job/{job_id}")
    def backtest_job_status(job_id: str):
        state = _JOBS.get(job_id)
        if state is None:
            raise HTTPException(404, "unknown job id")
        finished = state["status"] in ("done", "cancelled", "error")
        return {
            "job_id": job_id,
            "status": state["status"],
            "progress": state["progress"],
            "error": state["error"],
            # payload only attached once finished so polling stays cheap
            # (_json_safe defends against results stored by older workers)
            "result": _json_safe(state["result"]) if finished else None,
        }

    @app.post("/api/backtest/job/{job_id}/cancel")
    def backtest_job_cancel(job_id: str):
        state = _JOBS.get(job_id)
        if state is None:
            raise HTTPException(404, "unknown job id")
        if state["status"] == "running":
            state["cancel"].set()
        return {"ok": True, "job_id": job_id, "status": state["status"]}

    @app.post("/api/review")
    def review(req: ReviewRequest):
        from trading_bot.ai.llm import llm_from_config
        from trading_bot.ai.review import AITradeReviewer

        trades = store.trades.list(strategy=req.strategy, limit=5000)
        active = store.models.active()
        llm = llm_from_config(active) if active is not None else None
        rev = AITradeReviewer(llm=llm).review(
            trades, strategy=req.strategy, strategy_version=req.strategy_version,
            window_start=req.window_start, window_end=req.window_end,
        )
        if llm is not None:
            rev.summary = f"[LLM:{active.label or active.provider}] {rev.summary}"
        store.reviews.insert(rev)
        return rev.__dict__

    return app


def _run_walk_forward(provider, strategy_name, params, version, base_cfg, res_start, res_end):
    """Run walk-forward analysis and shape it for the dashboard.

    For large ranges the walk-forward is executed on the coarsest timeframe
    that keeps the bar count bounded (4 rolling windows), so a 5-year run does
    not take minutes. Falls back to None when the data range cannot support
    multiple windows or the run fails (fail-closed: caller omits the field).
    """
    from datetime import datetime, timezone

    from trading_bot.backtest.runner import BacktestConfig, BacktestRunner
    from trading_bot.core.enums import Timeframe
    from trading_bot.data.base import MarketDataQuery
    from trading_bot.validation.pipeline import run_walk_forward

    start = base_cfg.start if base_cfg.start > 0 else res_start
    end = base_cfg.end if base_cfg.end > 0 else res_end
    if start <= 0 or end <= 0 or end - start < 2 * 86400:
        return None

    # Choose a timeframe for the walk-forward. If the requested timeframe would
    # produce too many bars, coarsen so the analysis stays interactive.
    max_bars = 18_000
    chain = [Timeframe.M5, Timeframe.M15, Timeframe.M30, Timeframe.H1, Timeframe.H4, Timeframe.D1]
    try:
        start_idx = chain.index(base_cfg.timeframe)
    except ValueError:
        start_idx = 0
    wf_tf = base_cfg.timeframe
    wf_provider = provider
    for tf in chain[start_idx:]:
        current = provider if tf == base_cfg.timeframe else provider.resample(tf)
        try:
            bars = current.load_candles(
                MarketDataQuery(symbol=base_cfg.symbol, timeframe=tf, start=start, end=end)
            )
        except Exception as exc:
            print(f"walk-forward: {tf.value} unavailable ({exc})", flush=True)
            continue
        if len(bars) <= max_bars:
            wf_tf = tf
            wf_provider = current
            break

    base = BacktestConfig(
        symbol=base_cfg.symbol, timeframe=wf_tf, start=start, end=end,
        initial_cash=base_cfg.initial_cash, seed=base_cfg.seed,
    )
    wf_runner = BacktestRunner(wf_provider)
    try:
        wf = run_walk_forward(wf_runner, strategy_name, dict(params), version, base, n_windows=4)
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
        "timeframe": wf_tf.value,
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
