"""Tests for JSON-safe API responses (inf/nan crash fix)."""
import math

from fastapi.testclient import TestClient

from trading_bot.api import app as app_module
from trading_bot.api.app import _json_safe, make_app
from trading_bot.storage.memory import MemoryStore


class TestJsonSafe:
    def test_converts_inf_and_nan(self):
        obj = {
            "pf": float("inf"),
            "neg": float("-inf"),
            "nan": float("nan"),
            "ok": 1.5,
            "nested": {"a": [float("inf"), 2]},
        }
        out = _json_safe(obj)
        assert out["pf"] is None
        assert out["neg"] is None
        assert out["nan"] is None
        assert out["ok"] == 1.5
        assert out["nested"]["a"][0] is None
        assert out["nested"]["a"][1] == 2

    def test_non_float_untouched(self):
        obj = {"s": "inf", "b": True, "i": 3, "l": ["x"]}
        assert _json_safe(obj) == obj


class TestJobStatusInfResult:
    def test_job_with_inf_metrics_serializes(self):
        store = MemoryStore()
        app = make_app(store=store)
        client = TestClient(app, raise_server_exceptions=False)

        job_id = "testjob1"
        app_module._JOBS[job_id] = {
            "job_id": job_id,
            "status": "done",
            "progress": {},
            # simulate a result whose profit_factor hit inf (no losing trades)
            "result": {"metrics": {"profit_factor": float("inf"),
                                   "win_rate": 100.0},
                       "cancelled": False},
            "error": None,
            "cancel": None,
        }
        r = client.get(f"/api/backtest/job/{job_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "done"
        # inf was sanitized to null so JSON serialization succeeds
        assert body["result"]["metrics"]["profit_factor"] is None