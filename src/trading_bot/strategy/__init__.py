"""Strategy layer."""
from trading_bot.strategy.base import (
    BaseParams,
    BaseStrategy,
    StrategyMeta,
    StrategyRegistry,
    create_strategy,
    register,
    registry,
)

# Importing concrete strategies registers them in the registry. This keeps
# create_strategy("smc_crt") working without requiring callers to import
# strategy modules first.
from trading_bot.strategy.smc import strategy as _smc  # noqa: F401

__all__ = [
    "BaseParams",
    "BaseStrategy",
    "StrategyMeta",
    "StrategyRegistry",
    "create_strategy",
    "register",
    "registry",
]
