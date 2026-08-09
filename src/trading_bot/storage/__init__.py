"""Storage: interfaces, in-memory and PostgreSQL implementations."""
from trading_bot.storage.interfaces import (
    HeartbeatRecord,
    ReviewRecord,
    SignalRecord,
    StrategyVersionRecord,
    utcnow_iso,
)
from trading_bot.storage.memory import (
    MemoryHeartbeatStore,
    MemoryReviewStore,
    MemorySignalStore,
    MemoryStore,
    MemoryStrategyVersionStore,
    MemoryTradeStore,
)

__all__ = [
    "StrategyVersionRecord",
    "SignalRecord",
    "HeartbeatRecord",
    "ReviewRecord",
    "utcnow_iso",
    "MemoryStore",
    "MemoryStrategyVersionStore",
    "MemoryTradeStore",
    "MemorySignalStore",
    "MemoryHeartbeatStore",
    "MemoryReviewStore",
]


def get_store(backend: str = "memory", **kwargs):
    """Factory: 'memory' or 'postgres'/'supabase'."""
    backend = (backend or "memory").lower()
    if backend in ("memory", "inmemory", "in-memory"):
        return MemoryStore()
    if backend in ("postgres", "postgresql", "supabase"):
        from trading_bot.storage.postgres import PostgresStore

        if backend == "supabase":
            store = PostgresStore.from_supabase_env()
        else:
            dsn = kwargs.get("dsn")
            if not dsn:
                import os

                dsn = os.environ.get("DATABASE_URL", "")
            if not dsn:
                raise ValueError("Postgres backend requires dsn or DATABASE_URL")
            store = PostgresStore.from_dsn(dsn)
        if kwargs.get("init_schema", True):
            store.init_schema()
        return store
    raise ValueError(f"Unknown storage backend: {backend}")
