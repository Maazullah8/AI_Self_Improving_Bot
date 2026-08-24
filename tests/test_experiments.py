"""Tests for experiment tracking (Section 3) — store + API lifecycle."""
import pytest

from trading_bot.storage.interfaces import ExperimentRecord
from trading_bot.storage.memory import MemoryExperimentStore, MemoryStore


class TestMemoryExperimentStore:
    def test_create_get_list(self):
        store = MemoryExperimentStore()
        rec = store.create(ExperimentRecord(
            id="EXP-1", strategy="smc_crt",
            parent_version="v1.1", hypothesis="test hypothesis",
        ))
        assert rec.created_at != ""
        assert store.get("EXP-1") is rec
        assert len(store.list()) == 1

    def test_duplicate_id_rejected(self):
        store = MemoryExperimentStore()
        store.create(ExperimentRecord(id="EXP-1"))
        with pytest.raises(ValueError):
            store.create(ExperimentRecord(id="EXP-1"))

    def test_update_changes_fields_and_updated_at(self):
        store = MemoryExperimentStore()
        rec = store.create(ExperimentRecord(id="EXP-2"))
        before = rec.updated_at
        updated = store.update(
            "EXP-2", decision="rejected", decision_reason="walk-forward degraded"
        )
        assert updated.decision == "rejected"
        assert "degraded" in updated.decision_reason
        assert updated.updated_at >= before

    def test_list_filters_by_strategy(self):
        store = MemoryExperimentStore()
        store.create(ExperimentRecord(id="A", strategy="smc_crt"))
        store.create(ExperimentRecord(id="B", strategy="other"))
        ids = [r.id for r in store.list(strategy="smc_crt")]
        assert ids == ["A"]

    def test_store_facade_exposes_experiments(self):
        store = MemoryStore()
        assert hasattr(store, "experiments")
        store.experiments.create(ExperimentRecord(id="EXP-9"))
        assert store.experiments.get("EXP-9") is not None


class TestExperimentsApi:
    def _client(self):
        from fastapi.testclient import TestClient

        from trading_bot.api.app import make_app
        from trading_bot.storage.memory import MemoryStore

        return TestClient(make_app(store=MemoryStore()))

    def _create(self, client, **overrides):
        body = {
            "strategy": "smc_crt",
            "parent_version": "v1.1",
            "hypothesis": "Removing low-confluence FVG-only setups may improve "
                          "performance during ranging conditions.",
            "reason": "FVG-only setups show negative expectancy in ranging regime",
            "change_description": "Reject FVG setups without 2+ stacked levels",
            "expected_effect": "Higher win rate in ranging regimes",
            "dataset_start": 1704067200,
            "dataset_end": 1725062399,
        }
        body.update(overrides)
        return client.post("/api/experiments", json=body)

    def test_full_lifecycle(self):
        client = self._client()
        # create
        r = self._create(client)
        assert r.status_code == 200
        exp = r.json()
        assert exp["id"] == "EXP-1"
        assert exp["decision"] == "running"
        # list (newest first)
        lst = client.get("/api/experiments").json()
        assert lst[0]["id"] == "EXP-1"
        # get one
        got = client.get("/api/experiments/EXP-1").json()
        assert got["hypothesis"].startswith("Removing low-confluence")
        # record a rejection with evidence
        d = client.post("/api/experiments/EXP-1/decision", json={
            "decision": "rejected",
            "reason": "Walk-forward degraded; Monte Carlo drawdown exceeded limit",
            "actual_effect": "Win rate improved but max DD doubled out-of-sample",
            "comparison_results": {"return_delta": "+3%", "max_dd_delta": "+18%"},
        })
        assert d.status_code == 200
        assert d.json()["decision"] == "rejected"
        assert "exceeded" in d.json()["decision_reason"]
        assert "doubled" in d.json()["actual_effect"]
        # history is permanent and auditable
        final = client.get("/api/experiments/EXP-1").json()
        assert final["comparison_results"]["return_delta"] == "+3%"

    def test_invalid_decision_rejected(self):
        client = self._client()
        self._create(client)
        r = client.post("/api/experiments/EXP-1/decision", json={
            "decision": "make_it_rich",  # not an allowed value
        })
        assert r.status_code == 422

    def test_overfit_warning_on_same_dataset(self):
        client = self._client()
        for _ in range(3):
            self._create(client)  # same parent + same dataset range
        resp = self._create(client).json()
        assert "overfit_warning" in resp
        assert "same dataset period" in resp["overfit_warning"]

    def test_get_unknown_returns_404(self):
        client = self._client()
        assert client.get("/api/experiments/EXP-999").status_code == 404