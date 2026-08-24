"""Tests for regime detection, complete trade-state logging and the
risk-rejection audit trail (self-improvement loop foundations)."""
import pytest

from trading_bot.core.enums import Side, Timeframe
from trading_bot.core.models import Candle, TradeRecord
from trading_bot.core.regime import detect_regime
from trading_bot.core.time_utils import utc_ts
from trading_bot.journal.journal import Journal
from trading_bot.risk.manager import RiskConfig, RiskManager
from trading_bot.replay.engine import Signal


def _sym():
    from trading_bot.data.base import SymbolInfo

    return SymbolInfo(
        symbol="EURUSD", digits=5, tick_size=1e-5, point_size=1e-5,
        contract_size=100_000, lot_min=0.01, lot_max=200.0, lot_step=0.01,
    )


def _mk(i, close, spread=0.0002, amp=0.001):
    o = close - 0.0002
    return Candle(
        time=utc_ts(2024, 1, 2, 8, 0) + i * 3600,
        open=o, high=max(o, close) + amp, low=min(o, close) - amp,
        close=close, volume=10, spread=spread,
    )


class TestRegimeDetection:
    def test_trending_up(self):
        bars = [_mk(i, 1.10 + i * 0.0004) for i in range(60)]
        assert detect_regime(bars) == "trending_up"

    def test_trending_down(self):
        bars = [_mk(i, 1.40 - i * 0.0004) for i in range(60)]
        assert detect_regime(bars) == "trending_down"

    def test_ranging(self):
        bars = [_mk(i, 1.10 + (0.0004 if i % 2 else -0.0004)) for i in range(60)]
        assert detect_regime(bars) == "ranging"

    def test_high_volatility(self):
        bars = [_mk(i, 1.10 + (i % 2) * 0.0004, amp=0.0008) for i in range(50)]
        # last 10 bars triple their range -> vol ratio spikes
        bars += [
            Candle(
                time=utc_ts(2024, 1, 2, 8, 0) + (50 + j) * 3600,
                open=1.101, high=1.101 + 0.006, low=1.099 - 0.006,
                close=1.1005, volume=10, spread=0.0002,
            )
            for j in range(10)
        ]
        assert detect_regime(bars) == "high_volatility"

    def test_short_history_defaults_to_ranging(self):
        bars = [_mk(i, 1.10 + i * 0.0004) for i in range(5)]
        assert detect_regime(bars) == "ranging"


class TestJournalTradeState:
    def _record(self):
        setup = {
            "bias": "buy", "htf_bias": "crt_dol", "dol": "high",
            "crt_high": 2400.0, "crt_low": 2350.0, "inside_bars": 3,
            "zone_type": "order_block", "confluence_level": "high",
            "confluence_score": 4, "stack_count": 3,
            "stack_kinds": ["fvg", "order_block", "rejection_block"],
            "choch_csd": "choch", "confirmation_type": "engulfing",
            "regime": "trending_up", "spread_at_entry": 0.25,
            "day_of_week": 2, "hour_of_day": 9,
            "volatility": 3.2,
            # unmapped keys must survive into raw for pattern discovery
            "tp1": 2380.0, "runner_target": 2400.0,
            "checklist": {"rr_min_met": True},
        }
        journal = Journal(strategy_name="smc_crt", strategy_version="v1.1")

        class FakeEngine:
            def setup_for(self, pos_id):
                return setup

        from trading_bot.core.enums import ExitReason
        pos = type("P", (), dict(
            id="p1", symbol="XAUUSD", side=Side.BUY, size=0.5,
            open_price=2360.0, open_time=1000, sl=2350.0, tp=2380.0,
            strategy="smc_crt", strategy_version="v1.1",
        ))()
        outcome = type("O", (), {})()
        outcome.position = pos
        outcome.exit_time = 2000
        outcome.exit_price = 2380.0
        outcome.pnl = 100.0
        outcome.pnl_points = 20.0
        outcome.r = 2.0
        outcome.mfe_r = 2.4
        outcome.mae_r = -0.3
        outcome.exit_reason = ExitReason.TP
        outcome.slippage_paid = 0.0
        outcome.commission_paid = 0.0
        outcome.partial_exits = []
        return journal.record_trade(outcome, FakeEngine())

    def test_confluence_state_persisted(self):
        rec = self._record()
        assert rec.draw_on_liquidity == "high"
        assert rec.crt_high == pytest.approx(2400.0)
        assert rec.crt_low == pytest.approx(2350.0)
        assert rec.inside_bars == 3
        assert rec.confluence_stack_count == 3
        assert set(rec.confluence_stack_kinds) == {"fvg", "order_block", "rejection_block"}

    def test_market_context_persisted(self):
        rec = self._record()
        assert rec.regime == "trending_up"
        assert rec.spread_at_entry == pytest.approx(0.25)
        assert rec.day_of_week == 2
        assert rec.hour_of_day == 9

    def test_unmapped_setup_keys_survive_in_raw(self):
        rec = self._record()
        assert rec.raw.get("tp1") == 2380.0
        assert rec.raw.get("runner_target") == 2400.0
        assert rec.raw["checklist"]["rr_min_met"] is True
        # mapped keys are not duplicated into raw
        assert "bias" not in rec.raw


class TestRiskRejectionLog:
    def test_rejections_recorded_with_state(self):
        rm = RiskManager(RiskConfig(emergency_stop=True), symbol_info=_sym())
        bar = Candle(time=utc_ts(2024, 1, 2, 9, 0), open=1.1, high=1.101,
                     low=1.099, close=1.1005, volume=10, spread=1e-5)
        sig = Signal(side=Side.BUY, entry=1.1005, sl=1.098, tp=1.106, size=0.0)
        dec = rm.approve(sig, bar, 10_000, [])
        assert not dec.approved
        assert len(rm.rejections) == 1
        rej = rm.rejections[0]
        assert rej["reason"] == "emergency_stop_active"
        assert rej["equity"] == 10_000
        assert rej["time"] == utc_ts(2024, 1, 2, 9, 0)

    def test_approvals_not_logged(self):
        rm = RiskManager(RiskConfig(), symbol_info=_sym())
        bar = Candle(time=utc_ts(2024, 1, 2, 9, 0), open=1.1, high=1.101,
                     low=1.099, close=1.1005, volume=10, spread=1e-5)
        sig = Signal(side=Side.BUY, entry=1.1005, sl=1.098, tp=1.106, size=0.0)
        rm.approve(sig, bar, 10_000, [])
        assert rm.rejections == []