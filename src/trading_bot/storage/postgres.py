"""PostgreSQL storage implementation (works with Supabase Postgres).

Uses psycopg3. All data written as JSON-compatible structures so the same
code works with a plain Postgres server or Supabase's hosted Postgres.
"""
from __future__ import annotations

import json
from typing import Optional

import psycopg
from psycopg.rows import dict_row

from trading_bot.core.models import TradeRecord
from trading_bot.storage.interfaces import (
    ExperimentRecord,
    HeartbeatRecord,
    ReviewRecord,
    SignalRecord,
    StrategyVersionRecord,
    utcnow_iso,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS strategy_versions (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    parent_version TEXT,
    params JSONB NOT NULL DEFAULT '{}',
    rules JSONB NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'hypothesis',
    change_reason TEXT NOT NULL DEFAULT '',
    ai_hypothesis TEXT NOT NULL DEFAULT '',
    test_results JSONB NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    extra JSONB NOT NULL DEFAULT '{}',
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS trades (
    id BIGSERIAL PRIMARY KEY,
    trade_id TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    strategy TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    entry_time BIGINT NOT NULL,
    exit_time BIGINT NOT NULL,
    side TEXT NOT NULL,
    pnl REAL NOT NULL,
    r REAL NOT NULL,
    exit_reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_entry ON trades (entry_time);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades (strategy, strategy_version);

CREATE TABLE IF NOT EXISTS signals (
    id BIGSERIAL PRIMARY KEY,
    signal_id TEXT NOT NULL UNIQUE,
    time BIGINT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry REAL NOT NULL,
    sl REAL NOT NULL,
    tp REAL NOT NULL,
    confluence_level TEXT NOT NULL,
    confluence_score INT NOT NULL DEFAULT 0,
    risk_check TEXT NOT NULL DEFAULT 'pass',
    reject_reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    payload JSONB NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS heartbeats (
    id BIGSERIAL PRIMARY KEY,
    component TEXT NOT NULL,
    ts BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_heartbeats_comp ON heartbeats (component, ts);

CREATE TABLE IF NOT EXISTS reviews (
    id BIGSERIAL PRIMARY KEY,
    review_id TEXT NOT NULL UNIQUE,
    strategy TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    window_start BIGINT NOT NULL,
    window_end BIGINT NOT NULL,
    n_trades INT NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    rule_compliance JSONB NOT NULL DEFAULT '{}',
    patterns JSONB NOT NULL DEFAULT '[]',
    hypothesis TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
    id BIGSERIAL PRIMARY KEY,
    experiment_id TEXT NOT NULL UNIQUE,
    strategy TEXT NOT NULL,
    parent_version TEXT NOT NULL DEFAULT '',
    candidate_version TEXT NOT NULL DEFAULT '',
    hypothesis TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    change_description TEXT NOT NULL DEFAULT '',
    expected_effect TEXT NOT NULL DEFAULT '',
    actual_effect TEXT NOT NULL DEFAULT '',
    backtest_results JSONB NOT NULL DEFAULT '{}',
    walk_forward_results JSONB NOT NULL DEFAULT '{}',
    monte_carlo_results JSONB NOT NULL DEFAULT '{}',
    comparison_results JSONB NOT NULL DEFAULT '{}',
    dataset_start BIGINT NOT NULL DEFAULT 0,
    dataset_end BIGINT NOT NULL DEFAULT 0,
    decision TEXT NOT NULL DEFAULT 'running',
    decision_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experiments_strategy ON experiments (strategy, created_at);
"""


class PostgresStore:
    """Thin, transaction-safe Postgres store.

    The optional `schema` param lets callers point at a different table
    prefix (e.g. Supabase). Construct via `PostgresStore.from_dsn(dsn)`.
    """

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn
        self.strategies = _PGStrategyVersionStore(conn)
        self.trades = _PGTradeStore(conn)
        self.signals = _PGSignalStore(conn)
        self.heartbeats = _PGHeartbeatStore(conn)
        self.reviews = _PGReviewStore(conn)
        self.experiments = _PGExperimentStore(conn)

    @classmethod
    def from_dsn(cls, dsn: str) -> "PostgresStore":
        conn = psycopg.connect(dsn, row_factory=dict_row)
        return cls(conn)

    @classmethod
    def from_supabase_env(cls) -> "PostgresStore":
        """Build from SUPABASE_* env vars (host/password/service role)."""
        import os

        host = os.environ.get("SUPABASE_DB_HOST")
        password = os.environ.get("SUPABASE_DB_PASSWORD")
        port = os.environ.get("SUPABASE_DB_PORT", "5432")
        user = os.environ.get("SUPABASE_DB_USER", "postgres")
        db = os.environ.get("SUPABASE_DB_NAME", "postgres")
        if not host or not password:
            raise RuntimeError("SUPABASE_DB_HOST / SUPABASE_DB_PASSWORD not set")
        dsn = f"host={host} port={port} user={user} password={password} dbname={db} sslmode=require"
        return cls.from_dsn(dsn)

    def init_schema(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class _PGStrategyVersionStore:
    def __init__(self, conn):
        self._conn = conn

    def create(self, rec: StrategyVersionRecord) -> StrategyVersionRecord:
        if not rec.created_at:
            rec.created_at = utcnow_iso()
        rec.updated_at = utcnow_iso()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO strategy_versions
                  (name, version, parent_version, params, rules, status,
                   change_reason, ai_hypothesis, test_results, created_at, updated_at, extra)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (name, version) DO UPDATE SET
                  params=EXCLUDED.params, rules=EXCLUDED.rules, status=EXCLUDED.status,
                  change_reason=EXCLUDED.change_reason, ai_hypothesis=EXCLUDED.ai_hypothesis,
                  test_results=EXCLUDED.test_results, updated_at=EXCLUDED.updated_at,
                  extra=EXCLUDED.extra
                """,
                (
                    rec.name,
                    rec.version,
                    rec.parent_version,
                    json.dumps(rec.params),
                    json.dumps(rec.rules),
                    rec.status,
                    rec.change_reason,
                    rec.ai_hypothesis,
                    json.dumps(rec.test_results),
                    rec.created_at,
                    rec.updated_at,
                    json.dumps(rec.extra),
                ),
            )
        self._conn.commit()
        return rec

    def get(self, name: str, version: str) -> Optional[StrategyVersionRecord]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM strategy_versions WHERE name=%s AND version=%s",
                (name, version),
            )
            row = cur.fetchone()
        return _row_to_strategy(row) if row else None

    def list(self, name: Optional[str] = None) -> list[StrategyVersionRecord]:
        with self._conn.cursor() as cur:
            if name:
                cur.execute(
                    "SELECT * FROM strategy_versions WHERE name=%s ORDER BY created_at",
                    (name,),
                )
            else:
                cur.execute("SELECT * FROM strategy_versions ORDER BY created_at")
            rows = cur.fetchall()
        return [_row_to_strategy(r) for r in rows]

    def update(self, name: str, version: str, **fields) -> Optional[StrategyVersionRecord]:
        allowed = {
            "status", "params", "rules", "change_reason", "ai_hypothesis",
            "test_results", "extra", "updated_at",
        }
        sets = [k for k in fields if k in allowed]
        if not sets:
            return self.get(name, version)
        set_sql = ", ".join(f"{k}=%s" for k in sets) + ", updated_at=%s"
        vals = [json.dumps(fields[k]) if isinstance(fields[k], (dict, list)) else fields[k] for k in sets]
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE strategy_versions SET {set_sql} WHERE name=%s AND version=%s",
                (*vals, utcnow_iso(), name, version),
            )
        self._conn.commit()
        return self.get(name, version)

    def latest(self, name: str) -> Optional[StrategyVersionRecord]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM strategy_versions WHERE name=%s ORDER BY created_at DESC LIMIT 1",
                (name,),
            )
            row = cur.fetchone()
        return _row_to_strategy(row) if row else None


def _row_to_strategy(row) -> StrategyVersionRecord:
    return StrategyVersionRecord(
        name=row["name"],
        version=row["version"],
        parent_version=row["parent_version"],
        params=row["params"] or {},
        rules=row["rules"] or [],
        status=row["status"],
        change_reason=row["change_reason"] or "",
        ai_hypothesis=row["ai_hypothesis"] or "",
        test_results=row["test_results"] or {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        extra=row["extra"] or {},
    )


class _PGTradeStore:
    def __init__(self, conn):
        self._conn = conn

    def insert(self, trade: TradeRecord) -> TradeRecord:
        payload = trade.to_dict()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trades
                  (trade_id, payload, strategy, strategy_version, symbol,
                   entry_time, exit_time, side, pnl, r, exit_reason, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (trade_id) DO NOTHING
                """,
                (
                    trade.trade_id,
                    json.dumps(payload, default=str),
                    trade.strategy,
                    trade.strategy_version,
                    trade.symbol,
                    trade.entry_time,
                    trade.exit_time,
                    trade.side.value,
                    trade.pnl,
                    trade.r,
                    trade.exit_reason.value,
                    utcnow_iso(),
                ),
            )
        self._conn.commit()
        return trade

    def list(self, strategy: Optional[str] = None, limit: int = 1000) -> list[TradeRecord]:
        with self._conn.cursor() as cur:
            if strategy:
                cur.execute(
                    "SELECT payload FROM trades WHERE strategy=%s ORDER BY entry_time LIMIT %s",
                    (strategy, limit),
                )
            else:
                cur.execute("SELECT payload FROM trades ORDER BY entry_time LIMIT %s", (limit,))
            rows = cur.fetchall()
        return [_payload_to_trade(r["payload"]) for r in rows]

    def range(self, start: int, end: int) -> list[TradeRecord]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM trades WHERE entry_time>=%s AND entry_time<=%s ORDER BY entry_time",
                (start, end),
            )
            rows = cur.fetchall()
        return [_payload_to_trade(r["payload"]) for r in rows]

    def count(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM trades")
            return int(cur.fetchone()["count"])


def _payload_to_trade(payload: dict) -> TradeRecord:
    from trading_bot.core.enums import ExitReason, Side

    t = TradeRecord()
    for k, v in payload.items():
        if k == "side" and isinstance(v, str):
            setattr(t, "side", Side(v))
        elif k == "exit_reason" and isinstance(v, str):
            setattr(t, "exit_reason", ExitReason(v))
        elif hasattr(t, k):
            setattr(t, k, v)
    return t


class _PGSignalStore:
    def __init__(self, conn):
        self._conn = conn

    def insert(self, sig: SignalRecord) -> SignalRecord:
        if not sig.created_at:
            sig.created_at = utcnow_iso()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO signals
                  (signal_id, time, symbol, strategy, strategy_version, direction,
                   entry, sl, tp, confluence_level, confluence_score, risk_check,
                   reject_reason, status, payload, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (signal_id) DO NOTHING
                """,
                (
                    sig.id, sig.time, sig.symbol, sig.strategy, sig.strategy_version,
                    sig.direction, sig.entry, sig.sl, sig.tp, sig.confluence_level,
                    sig.confluence_score, sig.risk_check, sig.reject_reason, sig.status,
                    json.dumps({}), sig.created_at,
                ),
            )
        self._conn.commit()
        return sig

    def list(self, strategy: Optional[str] = None, limit: int = 500) -> list[SignalRecord]:
        with self._conn.cursor() as cur:
            if strategy:
                cur.execute(
                    "SELECT * FROM signals WHERE strategy=%s ORDER BY time LIMIT %s",
                    (strategy, limit),
                )
            else:
                cur.execute("SELECT * FROM signals ORDER BY time LIMIT %s", (limit,))
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append(
                SignalRecord(
                    id=r["signal_id"], time=r["time"], symbol=r["symbol"],
                    strategy=r["strategy"], strategy_version=r["strategy_version"],
                    direction=r["direction"], entry=r["entry"], sl=r["sl"], tp=r["tp"],
                    confluence_level=r["confluence_level"], confluence_score=r["confluence_score"],
                    risk_check=r["risk_check"], reject_reason=r["reject_reason"],
                    status=r["status"], created_at=r["created_at"],
                )
            )
        return out


class _PGHeartbeatStore:
    def __init__(self, conn):
        self._conn = conn

    def insert(self, hb: HeartbeatRecord) -> HeartbeatRecord:
        if not hb.created_at:
            hb.created_at = utcnow_iso()
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO heartbeats (component, ts, status, detail, created_at) VALUES (%s,%s,%s,%s,%s)",
                (hb.component, hb.ts, hb.status, hb.detail, hb.created_at),
            )
        self._conn.commit()
        return hb

    def latest(self, component: str) -> Optional[HeartbeatRecord]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM heartbeats WHERE component=%s ORDER BY ts DESC LIMIT 1",
                (component,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return HeartbeatRecord(
            component=row["component"], ts=row["ts"], status=row["status"],
            detail=row["detail"], created_at=row["created_at"],
        )


class _PGReviewStore:
    def __init__(self, conn):
        self._conn = conn

    def insert(self, rec: ReviewRecord) -> ReviewRecord:
        if not rec.created_at:
            rec.created_at = utcnow_iso()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO reviews
                  (review_id, strategy, strategy_version, window_start, window_end,
                   n_trades, summary, rule_compliance, patterns, hypothesis, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (review_id) DO NOTHING
                """,
                (
                    rec.id, rec.strategy, rec.strategy_version, rec.window_start,
                    rec.window_end, rec.n_trades, rec.summary,
                    json.dumps(rec.rule_compliance), json.dumps(rec.patterns),
                    rec.hypothesis, rec.created_at,
                ),
            )
        self._conn.commit()
        return rec

    def list(self, strategy: Optional[str] = None, limit: int = 100) -> list[ReviewRecord]:
        with self._conn.cursor() as cur:
            if strategy:
                cur.execute(
                    "SELECT * FROM reviews WHERE strategy=%s ORDER BY created_at LIMIT %s",
                    (strategy, limit),
                )
            else:
                cur.execute("SELECT * FROM reviews ORDER BY created_at LIMIT %s", (limit,))
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append(
                ReviewRecord(
                    id=r["review_id"], strategy=r["strategy"],
                    strategy_version=r["strategy_version"],
                    window_start=r["window_start"], window_end=r["window_end"],
                    n_trades=r["n_trades"], summary=r["summary"],
                    rule_compliance=r["rule_compliance"] or {},
                    patterns=r["patterns"] or [], hypothesis=r["hypothesis"],
                    created_at=r["created_at"],
                )
            )
        return out


class _PGExperimentStore:
    """Append-only experiment history (Section 3)."""

    _ALLOWED_UPDATE = {
        "candidate_version", "actual_effect", "backtest_results",
        "walk_forward_results", "monte_carlo_results", "comparison_results",
        "decision", "decision_reason", "updated_at",
    }

    def __init__(self, conn):
        self._conn = conn

    @staticmethod
    def _row_to_experiment(row) -> ExperimentRecord:
        return ExperimentRecord(
            id=row["experiment_id"],
            strategy=row["strategy"],
            parent_version=row["parent_version"] or "",
            candidate_version=row["candidate_version"] or "",
            hypothesis=row["hypothesis"] or "",
            reason=row["reason"] or "",
            change_description=row["change_description"] or "",
            expected_effect=row["expected_effect"] or "",
            actual_effect=row["actual_effect"] or "",
            backtest_results=row.get("backtest_results") or {},
            walk_forward_results=row.get("walk_forward_results") or {},
            monte_carlo_results=row.get("monte_carlo_results") or {},
            comparison_results=row.get("comparison_results") or {},
            dataset_start=int(row.get("dataset_start") or 0),
            dataset_end=int(row.get("dataset_end") or 0),
            decision=row["decision"] or "running",
            decision_reason=row["decision_reason"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create(self, rec: ExperimentRecord) -> ExperimentRecord:
        if not rec.created_at:
            rec.created_at = utcnow_iso()
        rec.updated_at = utcnow_iso()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO experiments
                  (experiment_id, strategy, parent_version, candidate_version,
                   hypothesis, reason, change_description, expected_effect,
                   actual_effect, backtest_results, walk_forward_results,
                   monte_carlo_results, comparison_results, dataset_start,
                   dataset_end, decision, decision_reason, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (experiment_id) DO NOTHING
                """,
                (
                    rec.id,
                    rec.strategy,
                    rec.parent_version,
                    rec.candidate_version,
                    rec.hypothesis,
                    rec.reason,
                    rec.change_description,
                    rec.expected_effect,
                    rec.actual_effect,
                    json.dumps(rec.backtest_results),
                    json.dumps(rec.walk_forward_results),
                    json.dumps(rec.monte_carlo_results),
                    json.dumps(rec.comparison_results),
                    rec.dataset_start,
                    rec.dataset_end,
                    rec.decision,
                    rec.decision_reason,
                    rec.created_at,
                    rec.updated_at,
                ),
            )
        self._conn.commit()
        return rec

    def get(self, experiment_id: str) -> Optional[ExperimentRecord]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM experiments WHERE experiment_id=%s",
                (experiment_id,),
            )
            row = cur.fetchone()
        return self._row_to_experiment(row) if row else None

    def list(
        self,
        strategy: Optional[str] = None,
        limit: int = 500,
    ) -> list[ExperimentRecord]:
        with self._conn.cursor() as cur:
            if strategy:
                cur.execute(
                    "SELECT * FROM experiments WHERE strategy=%s ORDER BY created_at",
                    (strategy,),
                )
            else:
                cur.execute("SELECT * FROM experiments ORDER BY created_at")
            rows = cur.fetchall()
        return [self._row_to_experiment(r) for r in rows][-limit:]

    def update(self, experiment_id: str, **fields) -> Optional[ExperimentRecord]:
        sets = [k for k in fields if k in self._ALLOWED_UPDATE]
        if not sets:
            return self.get(experiment_id)
        set_sql = ", ".join(f"{k}=%s" for k in sets) + ", updated_at=%s"
        vals = [
            json.dumps(fields[k]) if isinstance(fields[k], (dict, list)) else fields[k]
            for k in sets
        ]
        with self._conn.cursor() as cur:
            cur.execute(
                f"UPDATE experiments SET {set_sql} WHERE experiment_id=%s",
                (*vals, utcnow_iso(), experiment_id),
            )
        self._conn.commit()
        return self.get(experiment_id)
