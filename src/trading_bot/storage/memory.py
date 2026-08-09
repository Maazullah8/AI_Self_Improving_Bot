"""In-memory storage implementation.

Deterministic, dependency-free. Used for unit tests, backtests and any
process that must not touch a database. Not safe for multi-process use.
"""
from __future__ import annotations

from typing import Optional

from trading_bot.core.models import TradeRecord
from trading_bot.storage.interfaces import (
    HeartbeatRecord,
    ReviewRecord,
    SignalRecord,
    StrategyVersionRecord,
    utcnow_iso,
)


class MemoryStrategyVersionStore:
    def __init__(self):
        self._rows: list[StrategyVersionRecord] = []

    def create(self, rec: StrategyVersionRecord) -> StrategyVersionRecord:
        if not rec.created_at:
            rec.created_at = utcnow_iso()
        rec.updated_at = utcnow_iso()
        self._rows.append(rec)
        return rec

    def get(self, name: str, version: str) -> Optional[StrategyVersionRecord]:
        for r in self._rows:
            if r.name == name and r.version == version:
                return r
        return None

    def list(self, name: Optional[str] = None) -> list[StrategyVersionRecord]:
        rows = [r for r in self._rows if name is None or r.name == name]
        return sorted(rows, key=lambda r: r.created_at)

    def update(self, name: str, version: str, **fields) -> Optional[StrategyVersionRecord]:
        rec = self.get(name, version)
        if rec is None:
            return None
        for k, v in fields.items():
            if hasattr(rec, k):
                setattr(rec, k, v)
        rec.updated_at = utcnow_iso()
        return rec

    def latest(self, name: str) -> Optional[StrategyVersionRecord]:
        rows = [r for r in self._rows if r.name == name]
        if not rows:
            return None
        return max(rows, key=lambda r: r.created_at)


class MemoryTradeStore:
    def __init__(self):
        self._rows: list[TradeRecord] = []

    def insert(self, trade: TradeRecord) -> TradeRecord:
        self._rows.append(trade)
        return trade

    def list(self, strategy: Optional[str] = None, limit: int = 1000) -> list[TradeRecord]:
        rows = [t for t in self._rows if strategy is None or t.strategy == strategy]
        rows.sort(key=lambda t: t.entry_time)
        return rows[-limit:]

    def range(self, start: int, end: int) -> list[TradeRecord]:
        return [t for t in self._rows if start <= t.entry_time <= end]

    def count(self) -> int:
        return len(self._rows)

    def clear(self) -> None:
        self._rows.clear()


class MemorySignalStore:
    def __init__(self):
        self._rows: list[SignalRecord] = []

    def insert(self, sig: SignalRecord) -> SignalRecord:
        if not sig.created_at:
            sig.created_at = utcnow_iso()
        self._rows.append(sig)
        return sig

    def list(self, strategy: Optional[str] = None, limit: int = 500) -> list[SignalRecord]:
        rows = [s for s in self._rows if strategy is None or s.strategy == strategy]
        rows.sort(key=lambda s: s.time)
        return rows[-limit:]


class MemoryHeartbeatStore:
    def __init__(self):
        self._rows: list[HeartbeatRecord] = []

    def insert(self, hb: HeartbeatRecord) -> HeartbeatRecord:
        self._rows.append(hb)
        return hb

    def latest(self, component: str) -> Optional[HeartbeatRecord]:
        rows = [h for h in self._rows if h.component == component]
        if not rows:
            return None
        return max(rows, key=lambda h: h.ts)


class MemoryReviewStore:
    def __init__(self):
        self._rows: list[ReviewRecord] = []

    def insert(self, rec: ReviewRecord) -> ReviewRecord:
        if not rec.created_at:
            rec.created_at = utcnow_iso()
        self._rows.append(rec)
        return rec

    def list(self, strategy: Optional[str] = None, limit: int = 100) -> list[ReviewRecord]:
        rows = [r for r in self._rows if strategy is None or r.strategy == strategy]
        rows.sort(key=lambda r: r.created_at)
        return rows[-limit:]


class MemoryStore:
    def __init__(self):
        self.strategies = MemoryStrategyVersionStore()
        self.trades = MemoryTradeStore()
        self.signals = MemorySignalStore()
        self.heartbeats = MemoryHeartbeatStore()
        self.reviews = MemoryReviewStore()
