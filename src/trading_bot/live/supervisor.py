"""24/7 supervisor: health checks, heartbeats, watchdog, restart with backoff.

The supervisor does not make trading decisions; it keeps the pipeline alive
and surfaces unhealthy states. Fail-closed at the supervision level: if the
pipeline stops heartbeating, the supervisor marks the component DOWN and
attempts a bounded restart.
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Callable, Optional

from trading_bot.core.time_utils import utcnow_ts
from trading_bot.live.pipeline import LiveTradePipeline


@dataclass
class SupervisorConfig:
    heartbeat_timeout_seconds: int = 60
    max_restarts: int = 5
    restart_backoff_seconds: int = 30
    health_check_interval_seconds: int = 15


@dataclass
class ComponentStatus:
    name: str = ""
    status: str = "unknown"  # ok|warn|down|stopped
    last_heartbeat: int = 0
    detail: str = ""
    restarts: int = 0
    last_error: str = ""
    checked_at: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "last_heartbeat": self.last_heartbeat,
            "detail": self.detail,
            "restarts": self.restarts,
            "last_error": self.last_error,
            "checked_at": self.checked_at,
        }


class PipelineSupervisor:
    """Watchdog around a LiveTradePipeline with heartbeat-based health."""

    def __init__(
        self,
        pipeline: LiveTradePipeline,
        store=None,
        config: Optional[SupervisorConfig] = None,
    ):
        self.pipeline = pipeline
        self.store = store
        self.config = config or SupervisorConfig()
        self.status = ComponentStatus(name="live_pipeline")
        self._started = 0.0

    # ------------------------------------------------------------- control
    def start(self) -> None:
        self._started = _time.time()
        self.status.status = "ok"
        self.status.detail = "started"

    def run_loop(self, iterations: int = 0) -> None:
        """Blocking loop. ``iterations=0`` runs forever."""
        n = 0
        while iterations == 0 or n < iterations:
            n += 1
            self.check_once()
            _time.sleep(self.config.health_check_interval_seconds)

    def check_once(self, now: Optional[int] = None) -> ComponentStatus:
        now = now or utcnow_ts()
        self.status.checked_at = now

        hb = self._latest_heartbeat()
        if hb is not None:
            self.status.last_heartbeat = hb.ts
        stale = hb is not None and (now - hb.ts) > self.config.heartbeat_timeout_seconds

        if stale:
            self._handle_stale(now)
        else:
            try:
                self.pipeline.poll(now=now)
                self.status.status = self.pipeline.state.status or "ok"
                self.status.detail = self.pipeline.state.detail
            except Exception as e:  # fail-closed: unexpected error
                self.status.status = "down"
                self.status.last_error = str(e)
                self._handle_stale(now)
        return self.status

    def _handle_stale(self, now: int) -> None:
        if self.status.restarts >= self.config.max_restarts:
            self.status.status = "down"
            self.status.detail = f"exceeded {self.config.max_restarts} restarts; waiting for manual intervention"
            self._emit_heartbeat("down", self.status.detail)
            return
        self.status.restarts += 1
        self.status.status = "warn"
        self.status.detail = f"stale heartbeat; restarting ({self.status.restarts}/{self.config.max_restarts})"
        self._emit_heartbeat("warn", self.status.detail)
        _time.sleep(self.config.restart_backoff_seconds)
        try:
            self.pipeline.shutdown()
            # fresh poll after restart re-establishes state
            self.pipeline.poll(now=now)
            self.status.status = "ok"
            self.status.detail = "restarted"
            self._emit_heartbeat("ok", "restarted")
        except Exception as e:
            self.status.last_error = str(e)
            self.status.status = "down"

    def _latest_heartbeat(self):
        if self.store is None or not hasattr(self.store, "heartbeats"):
            return None
        try:
            return self.store.heartbeats.latest("live:EURUSD")
        except Exception:
            return None

    def _emit_heartbeat(self, status: str, detail: str) -> None:
        if self.store is None or not hasattr(self.store, "heartbeats"):
            return
        from trading_bot.storage.interfaces import HeartbeatRecord, utcnow_iso

        self.store.heartbeats.insert(
            HeartbeatRecord(
                component="supervisor",
                ts=utcnow_ts(),
                status=status,
                detail=detail,
                created_at=utcnow_iso(),
            )
        )
