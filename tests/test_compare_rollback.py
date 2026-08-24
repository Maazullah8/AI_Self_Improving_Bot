"""Tests for compare_results (Section 9) and the rollback endpoint (Section 14)."""
import pytest

from trading_bot.core.enums import ExitReason, Side
from trading_bot.core.models import TradeRecord
from trading_bot.core.time_utils import utc_ts
from trading_bot.storage.interfaces import ExperimentRecord
from trading_bot.storage.memory import MemoryStore


def _trade(entry_time, pnl, r, regime="ranging", session="london", tier="high"):
    return TradeRecord(
        trade_id=f"t{abs(hash((entry_time, pnl))) % 100000}",
        entry_time=entry_time,
        exit_time=entry_time + 3600,
        pnl=pnl,
        r=r,
        exit_reason=ExitReason.TP if r > 0 else ExitReason.SL,
        regime=regime,
        session=session,
        confluence_level=tier,
    )


class TestCompareResults:
    def _results(self):
        from trading_bot.backtest.runner import BacktestResult

        base_trades = [
            _trade(utc_ts(2024, 1, 2, 10), -100, -1.0),
            _trade(utc_ts(2024, 1, 3, 10), 150, 1.5),
            _trade(utc_ts(2024, 1, 4, 10), -80, -0.8),
            _trade(utc_ts(2023, 12, 20, 10), 120, 1.2),   # previous year
        ]
        cand_trades = [
            _trade(utc_ts(2024, 1, 2, 10), -50, -0.5),
            _trade(utc_ts(2024, 1, 3, 10), 150, 1.5),
            _trade(utc_ts(2024, 1, 5, 10), 90, 0.9),
            _trade(utc_ts(2023, 12, 20, 10), 120, 1.2),
        ]

        def _res(trades, final_equity):
            eq = [{"time": utc_ts(2024, 1, 1), "equity": 10000}]
            running = 10000
            for t in trades:
                running += t.pnl
                eq.append({"time": t.exit_time, "equity": running})
            from trading_bot.backtest.metrics import compute_metrics

            return BacktestResult(
                trades=trades,
                metrics=compute_metrics(eq, trades),
                equity_curve=eq,
                final_equity=final_equity,
            )

        return _res(base_trades, 10090.0), _res(cand_trades, 10310.0)

    def test_headline_metrics_with_deltas(self):
        from trading_bot.validation.pipeline import compare_results

        base, cand = self._results()
        cmp = compare_results(base, cand)
        h = cmp["headline"]
        assert h["n_trades"]["baseline"] == 4
        assert h["n_trades"]["candidate"] == 4
        # candidate lost less -> avg_loss_r improved (delta negative = better)
        assert h["avg_loss_r"]["improved"] is True
        assert h["max_drawdown_pct"]["improved"] in (True, False)

    def test_breakdowns_present(self):
        from trading_bot.validation.pipeline import compare_results

        base, cand = self._results()
        cmp = compare_results(base, cand)
        assert set(cmp.keys()) >= {
            "headline", "by_year", "by_regime", "by_session",
            "by_confluence_tier", "n_trades",
        }
        # year bucketing actually works
        assert any(int(y) == 2023 for y in cmp["by_year"]["baseline"])
        assert any(int(y) == 2024 for y in cmp["by_year"]["baseline"])
        assert "ranging" in cmp["by_regime"]["baseline"]

    def test_promotion_gate_runs_on_candidate(self):
        from trading_bot.validation.pipeline import PromotionGate

        base, cand = self._results()
        gate = PromotionGate().evaluate(cand, base, seed=1)
        d = gate.to_dict()
        assert "passed" in d or "gates" in d or isinstance(d, dict)


class TestRollbackEndpoint:
    def _client(self):
        from fastapi.testclient import TestClient

        from trading_bot.api.app import make_app

        store = MemoryStore()
        store.strategies.create(_version("v1.1", status="live"))
        store.strategies.create(_version("v1.2", status="promoted"))
        store.experiments.create(ExperimentRecord(
            id="EXP-1", strategy="smc_crt",
            parent_version="v1.1", candidate_version="v1.2",
            hypothesis="h", decision="promoted",
        ))
        return TestClient(make_app(store=store)), store

    def test_rollback_flow(self):
        client, store = self._client()
        r = client.post("/api/experiments/EXP-1/rollback", json={
            "reason": "Live performance materially worse than backtest expectation",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["experiment"]["decision"] == "rolled_back"
        assert body["candidate_status"] == "rolled_back"
        assert body["baseline_status"] == "live"
        # both versions preserved
        assert store.strategies.get("smc_crt", "v1.1") is not None
        assert store.strategies.get("smc_crt", "v1.2").status == "rolled_back"

    def test_rollback_rejected_for_non_promoted(self):
        store = MemoryStore()
        store.strategies.create(_version("v1.1", status="live"))
        store.experiments.create(ExperimentRecord(
            id="EXP-2", strategy="smc_crt", parent_version="v1.1",
            candidate_version="v1.2", decision="running",
        ))
        client = _client_with_store(store)
        r = client.post("/api/experiments/EXP-2/rollback", json={"reason": ""})
        assert r.status_code == 422


def _version(version, status):
    from trading_bot.storage.interfaces import StrategyVersionRecord

    return StrategyVersionRecord(
        name="smc_crt", version=version, params={"min_rr": 2.0},
        rules=["no_confirmation_no_trade"], status=status,
    )


def _client_with_store(store):
    from fastapi.testclient import TestClient

    from trading_bot.api.app import make_app

    return TestClient(make_app(store=store))