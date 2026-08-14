"""Storage interfaces (protocols) for all persisted domain objects.

The rest of the system depends on these interfaces, never on a concrete
storage backend. Implementations: InMemoryStore (tests/dev) and
PostgresStore / SupabaseStore (production).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Protocol

from trading_bot.core.models import TradeRecord


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StrategyVersionRecord:
    """A stored strategy version (never overwritten, append-only)."""

    version: str  # e.g. "v1.0"
    name: str  # strategy family, e.g. "smc_crt"
    parent_version: Optional[str] = None
    params: dict = field(default_factory=dict)
    rules: list[str] = field(default_factory=list)
    status: str = "hypothesis"  # StrategyStatus value
    change_reason: str = ""
    ai_hypothesis: str = ""
    test_results: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["params"] = dict(self.params)
        d["rules"] = list(self.rules)
        d["test_results"] = dict(self.test_results)
        d["extra"] = dict(self.extra)
        return d


@dataclass
class SignalRecord:
    id: str = ""
    time: int = 0
    symbol: str = ""
    strategy: str = ""
    strategy_version: str = ""
    direction: str = ""
    entry: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    confluence_level: str = ""
    confluence_score: int = 0
    risk_check: str = "pass"
    reject_reason: str = ""
    status: str = "pending"  # pending|executed|rejected|skipped
    created_at: str = ""


@dataclass
class HeartbeatRecord:
    component: str = ""
    ts: int = 0
    status: str = "ok"  # ok|warn|down
    detail: str = ""
    created_at: str = ""


@dataclass
class ReviewRecord:
    id: str = ""
    strategy: str = ""
    strategy_version: str = ""
    window_start: int = 0
    window_end: int = 0
    n_trades: int = 0
    summary: str = ""
    rule_compliance: dict = field(default_factory=dict)
    patterns: list[dict] = field(default_factory=list)
    hypothesis: str = ""
    created_at: str = ""


@dataclass
class ModelConfigRecord:
    """An AI model connection: local (Ollama) or online via API key.

    ``api_key`` is stored server-side and never returned by the API (only a
    masked display form is exposed).
    """

    id: str = ""
    provider: str = "openai"  # ollama | openai | openrouter | groq | anthropic | gemini | custom
    label: str = ""
    base_url: str = ""  # e.g. http://localhost:11434 for Ollama
    api_key: str = ""  # blank for local Ollama
    model: str = ""  # e.g. llama3.1:8b, gpt-4o
    is_active: bool = False
    created_at: str = ""
    updated_at: str = ""

    def masked_key(self) -> str:
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "••••"
        return f"{self.api_key[:6]}••••••••{self.api_key[-4:]}"

    def to_dict(self, include_key: bool = False) -> dict:
        d = {
            "id": self.id,
            "provider": self.provider,
            "label": self.label,
            "base_url": self.base_url,
            "model": self.model,
            "is_active": self.is_active,
            "masked_key": self.masked_key(),
            "has_key": bool(self.api_key),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_key:
            d["api_key"] = self.api_key
        return d


class StrategyVersionStore(Protocol):
    def create(self, rec: StrategyVersionRecord) -> StrategyVersionRecord: ...
    def get(self, name: str, version: str) -> Optional[StrategyVersionRecord]: ...
    def list(self, name: Optional[str] = None) -> list[StrategyVersionRecord]: ...
    def update(self, name: str, version: str, **fields) -> Optional[StrategyVersionRecord]: ...
    def latest(self, name: str) -> Optional[StrategyVersionRecord]: ...


class TradeStore(Protocol):
    def insert(self, trade: TradeRecord) -> TradeRecord: ...
    def list(self, strategy: Optional[str] = None, limit: int = 1000) -> list[TradeRecord]: ...
    def range(self, start: int, end: int) -> list[TradeRecord]: ...
    def count(self) -> int: ...


class SignalStore(Protocol):
    def insert(self, sig: SignalRecord) -> SignalRecord: ...
    def list(self, strategy: Optional[str] = None, limit: int = 500) -> list[SignalRecord]: ...


class HeartbeatStore(Protocol):
    def insert(self, hb: HeartbeatRecord) -> HeartbeatRecord: ...
    def latest(self, component: str) -> Optional[HeartbeatRecord]: ...


class ReviewStore(Protocol):
    def insert(self, rec: ReviewRecord) -> ReviewRecord: ...
    def list(self, strategy: Optional[str] = None, limit: int = 100) -> list[ReviewRecord]: ...


class ModelConfigStore(Protocol):
    def upsert(self, rec: ModelConfigRecord) -> ModelConfigRecord: ...
    def get(self, model_id: str) -> Optional[ModelConfigRecord]: ...
    def list(self) -> list[ModelConfigRecord]: ...
    def delete(self, model_id: str) -> bool: ...
    def set_active(self, model_id: str) -> Optional[ModelConfigRecord]: ...
    def active(self) -> Optional[ModelConfigRecord]: ...


class Store(Protocol):
    """Aggregate store facade used by the application."""

    strategies: StrategyVersionStore
    trades: TradeStore
    signals: SignalStore
    heartbeats: HeartbeatStore
    reviews: ReviewStore
    models: ModelConfigStore
