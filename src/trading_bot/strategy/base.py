"""Strategy base classes and parameter models.

A Strategy is a pure function of historical bars -> optional Signal. It
must be deterministic: given the same bar history it returns the same
result. Strategies never talk to the broker directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from typing import Any, Optional, Type

from trading_bot.replay.engine import Context, Signal


class BaseParams:
    """Marker base for strategy parameter dataclasses.

    Subclasses should define fields with defaults so strategies are
    fully configurable and versionable (params dict drives versioning).
    """

    def to_dict(self) -> dict[str, Any]:
        out = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, BaseParams):
                out[f.name] = v.to_dict()
            else:
                out[f.name] = v
        return out

    @classmethod
    def from_dict(cls: Type["BaseParams"], data: dict[str, Any]) -> "BaseParams":
        kwargs = {}
        known = {f.name: f for f in fields(cls)}
        for k, v in data.items():
            if k in known:
                f = known[k]
                if isinstance(f.type, type) and issubclass(f.type, BaseParams) and isinstance(v, dict):
                    kwargs[k] = f.type.from_dict(v)
                else:
                    kwargs[k] = v
        return cls(**kwargs)

    def diff(self, other: "BaseParams") -> dict[str, Any]:
        a, b = self.to_dict(), other.to_dict()
        return {k: v for k, v in a.items() if k in b and b[k] != v}


@dataclass
class StrategyMeta:
    name: str
    version: str
    description: str = ""
    parent_version: Optional[str] = None
    params: dict = field(default_factory=dict)
    rules: list[str] = field(default_factory=list)


class BaseStrategy(ABC):
    """Base class for all trading strategies."""

    name: str = "base"
    version: str = "v0.0"
    description: str = ""
    parent_version: Optional[str] = None
    rules: list[str] = []
    timeframe: Optional[Any] = None  # primary signal timeframe (Timeframe)

    def __init__(self, params: Optional[dict] = None):
        self._params: dict = {}
        self.set_params(params or {})

    # ------------------------------------------------------------------ API
    def set_params(self, params: dict) -> None:
        """Set/overwrite parameters. Subclasses may validate here."""
        self._params.update(params)

    def get_params(self) -> dict:
        return dict(self._params)

    @abstractmethod
    def on_bar(self, ctx: Context) -> Optional[Signal]:
        """Called once per closed bar. Return a Signal or None."""

    def setup_context(self, ctx: Context) -> dict:
        """Optional extra journal context merged into each trade."""
        return {}

    def version_info(self) -> StrategyMeta:
        return StrategyMeta(
            name=self.name,
            version=self.version,
            description=self.description,
            parent_version=self.parent_version,
            params=self.get_params(),
            rules=list(self.rules),
        )

    def on_position_close(self, outcome) -> None:
        """Hook called after a position closes (replay journaling)."""

    # ----------------------------------------------------------- validation
    def validate_params(self) -> list[str]:
        """Return list of param validation errors (empty = valid)."""
        return []

    def clone_with_params(self, new_params: dict, version: str) -> "BaseStrategy":
        merged = dict(self.get_params())
        merged.update(new_params)
        clone = self.__class__(params=merged)
        clone.version = version
        clone.parent_version = self.version
        return clone


class StrategyRegistry:
    """Registry mapping strategy names to classes."""

    def __init__(self):
        self._registry: dict[str, type] = {}

    def register(self, cls: type) -> type:
        name = getattr(cls, "name", None)
        if not name or name == "base":
            raise ValueError(f"Strategy {cls.__name__} must define a non-default name")
        self._registry[name] = cls
        return cls

    def get(self, name: str) -> type:
        if name not in self._registry:
            raise KeyError(f"Unknown strategy '{name}'. Known: {sorted(self._registry)}")
        return self._registry[name]

    def names(self) -> list[str]:
        return sorted(self._registry)

    def create(self, name: str, params: Optional[dict] = None, version: Optional[str] = None) -> BaseStrategy:
        cls = self.get(name)
        inst = cls(params=params)
        if version:
            inst.version = version
        return inst

    def all(self) -> dict[str, type]:
        return dict(self._registry)


registry = StrategyRegistry()


def register(cls):
    """Decorator: register a strategy class."""
    return registry.register(cls)


def create_strategy(name: str, params: Optional[dict] = None, version: Optional[str] = None) -> BaseStrategy:
    return registry.create(name, params=params, version=version)
