"""Tests for storage layer (in-memory)."""
from trading_bot.core.enums import ExitReason, Side
from trading_bot.core.models import TradeRecord
from trading_bot.storage.memory import MemoryStore
from trading_bot.storage.interfaces import StrategyVersionRecord


def _mk_trade(i: int) -> TradeRecord:
    return TradeRecord(
        trade_id=f"t{i}",
        strategy="smc_crt",
        strategy_version="v1.0",
        symbol="EURUSD",
        side=Side.BUY,
        entry_time=1000 + i,
        exit_time=2000 + i,
        entry_price=1.10,
        exit_price=1.11,
        size=0.1,
        sl=1.09,
        tp=1.13,
        rr=3.0,
        pnl=10.0,
        r=1.0,
        exit_reason=ExitReason.TP,
    )


def test_memory_trade_store():
    store = MemoryStore()
    store.trades.insert(_mk_trade(1))
    store.trades.insert(_mk_trade(2))
    assert store.trades.count() == 2
    rows = store.trades.list(strategy="smc_crt")
    assert len(rows) == 2
    assert rows[0].entry_time == 1001


def test_memory_strategy_version_store():
    store = MemoryStore()
    store.strategies.create(
        StrategyVersionRecord(
            name="smc_crt", version="v1.0", params={"risk_pct": 0.01},
            rules=["no_confirmation_no_trade"], status="live",
        )
    )
    store.strategies.create(
        StrategyVersionRecord(
            name="smc_crt", version="v1.1", params={"risk_pct": 0.01},
            parent_version="v1.0", status="candidate",
        )
    )
    latest = store.strategies.latest("smc_crt")
    assert latest.version == "v1.1"
    v = store.strategies.get("smc_crt", "v1.0")
    assert v is not None and v.status == "live"
    store.strategies.update("smc_crt", "v1.1", status="promoted")
    assert store.strategies.get("smc_crt", "v1.1").status == "promoted"


def test_strategy_trade_dict_roundtrip():
    t = _mk_trade(9)
    d = t.to_dict()
    assert d["side"] == "buy"
    assert d["exit_reason"] == "tp"
