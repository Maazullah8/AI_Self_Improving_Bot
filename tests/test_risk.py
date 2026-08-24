"""Tests for the risk manager."""
import pytest

from trading_bot.core.enums import Side
from trading_bot.core.models import Candle, Position, PositionStatus
from trading_bot.core.time_utils import utc_ts
from trading_bot.data.base import SymbolInfo
from trading_bot.replay.engine import Signal
from trading_bot.risk.manager import RiskConfig, RiskManager


def _sym():
    return SymbolInfo(
        symbol="EURUSD", digits=5, tick_size=1e-5, point_size=1e-5,
        lot_min=0.01, lot_max=2000.0, lot_step=0.01,
    )


def _bar(time=None, spread=1e-4):
    return Candle(
        time=time or utc_ts(2024, 1, 2, 10, 0, 0),
        open=1.10, high=1.101, low=1.099, close=1.1005, volume=10, spread=spread,
    )


def _signal(sl=1.098, tp=1.106, entry=1.1005, side=Side.BUY):
    return Signal(side=side, entry=entry, sl=sl, tp=tp, size=0.0, bar_index=0, bar_time=0)


def _open_pos(n=0):
    if n == 0:
        return []
    return [
        Position(id=f"p{i}", symbol="EURUSD", side=Side.BUY, size=0.1,
                 open_price=1.10, open_time=0, sl=1.09, tp=1.12, status=PositionStatus.OPEN)
        for i in range(n)
    ]


class TestBasicApprove:
    def test_approve_sizes_position(self):
        rm = RiskManager(RiskConfig(risk_per_trade_pct=0.01), symbol_info=_sym())
        dec = rm.approve(_signal(), _bar(), 10_000, [])
        assert dec.approved
        # risk = 0.0025 (1.1005-1.098), 1% of 10k = 100 -> units = 40000
        # lots = 40000 / contract(100000) = 0.4
        assert dec.size == pytest.approx(0.4)
        assert dec.reason == "ok"

    def test_lot_normalized(self):
        rm = RiskManager(RiskConfig(risk_per_trade_pct=0.01), symbol_info=_sym())
        dec = rm.approve(_signal(sl=1.0995, tp=1.106), _bar(), 10_000, [])
        assert dec.approved
        assert dec.size >= 0.01

    def test_reject_zero_risk(self):
        rm = RiskManager(RiskConfig(), symbol_info=_sym())
        dec = rm.approve(_signal(sl=1.1005), _bar(), 10_000, [])
        assert not dec.approved
        assert dec.reason == "zero_risk"

    def test_reject_spread_too_wide(self):
        cfg = RiskConfig(max_spread_points=5)  # 5e-5 max
        rm = RiskManager(cfg, symbol_info=_sym())
        dec = rm.approve(_signal(), _bar(spread=2e-4), 10_000, [])
        assert not dec.approved
        assert dec.reason == "spread_too_wide"


class TestLimits:
    def test_max_positions(self):
        rm = RiskManager(RiskConfig(max_positions=1), symbol_info=_sym())
        dec = rm.approve(_signal(), _bar(), 10_000, _open_pos(1))
        assert not dec.approved
        assert dec.reason == "max_positions_reached"

    def test_max_drawdown(self):
        cfg = RiskConfig(max_relative_drawdown_pct=0.10)
        rm = RiskManager(cfg, symbol_info=_sym())
        # start at 10k, peak later at 12k, then equity drops to 10.5k -> dd = 12.5%
        rm.on_bar_end(_bar(time=utc_ts(2024, 1, 2, 9, 0)), 10_000, [])
        rm.on_bar_end(_bar(time=utc_ts(2024, 1, 2, 9, 30)), 12_000, [])
        dec = rm.approve(_signal(), _bar(), 10_500, [])
        assert not dec.approved
        assert dec.reason == "max_drawdown_reached"

    def test_daily_loss_limit(self):
        cfg = RiskConfig(daily_loss_limit_pct=0.02)
        rm = RiskManager(cfg, symbol_info=_sym())
        rm.on_bar_end(_bar(time=utc_ts(2024, 1, 2, 9, 0)), 10_000, [])
        dec = rm.approve(_signal(), _bar(), 9_800, [])
        assert not dec.approved
        assert dec.reason == "daily_loss_limit_reached"

    def test_consecutive_losses(self):
        cfg = RiskConfig(max_consecutive_losses=3)
        rm = RiskManager(cfg, symbol_info=_sym())
        rm.on_trade_close(-1.0)
        rm.on_trade_close(-1.0)
        rm.on_trade_close(-1.0)
        dec = rm.approve(_signal(), _bar(), 10_000, [])
        assert not dec.approved
        assert dec.reason == "consecutive_losses_limit_reached"

    def test_session_not_allowed(self):
        cfg = RiskConfig(allowed_sessions=["asia"])
        rm = RiskManager(cfg, symbol_info=_sym())
        bar = _bar(time=utc_ts(2024, 1, 2, 15, 0))  # London
        dec = rm.approve(_signal(), bar, 10_000, [])
        assert not dec.approved
        assert "session_not_allowed" in dec.reason

    def test_emergency_stop(self):
        cfg = RiskConfig(emergency_stop=True)
        rm = RiskManager(cfg, symbol_info=_sym())
        dec = rm.approve(_signal(), _bar(), 10_000, [])
        assert not dec.approved
        assert dec.reason == "emergency_stop_active"

    def test_daily_trade_limit(self):
        cfg = RiskConfig(max_daily_trades=2)
        rm = RiskManager(cfg, symbol_info=_sym())
        rm.on_trade_close(1.0)
        rm.on_trade_close(1.0)
        dec = rm.approve(_signal(), _bar(), 10_000, [])
        assert not dec.approved
        assert dec.reason == "daily_trade_limit_reached"

    def test_consecutive_wins_reset(self):
        cfg = RiskConfig(max_consecutive_losses=2)
        rm = RiskManager(cfg, symbol_info=_sym())
        rm.on_trade_close(-1.0)
        rm.on_trade_close(1.0)
        dec = rm.approve(_signal(), _bar(), 10_000, [])
        assert dec.approved

    def test_fail_closed_invalid_equity(self):
        cfg = RiskConfig(require_valid_equity=True)
        rm = RiskManager(cfg, symbol_info=_sym())
        dec = rm.approve(_signal(), _bar(), 0, [])
        assert not dec.approved
        assert dec.reason == "invalid_equity"
