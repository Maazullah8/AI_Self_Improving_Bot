"""Tests for SMC structure, zones, bias, confluence, confirmation candles."""
import numpy as np
import pytest

from trading_bot.core.enums import Side, Timeframe
from trading_bot.core.models import Candle
from trading_bot.core.time_utils import utc_ts
from trading_bot.strategy.smc.bias import BiasEngine
from trading_bot.strategy.smc.candles import (
    is_bullish_engulfing,
    is_hammer,
    is_mother_baby,
)
from trading_bot.strategy.smc.confluence import compute_confluence
from trading_bot.strategy.smc.structure import (
    StructureDetector,
    detect_bos,
    detect_choch,
    find_swings,
)
from trading_bot.strategy.smc.zones import (
    find_fvgs,
    find_liquidity_pools,
    find_order_blocks,
    find_rejection_blocks,
)


def _c(i, o, h, l, c, spread=1e-5):
    return Candle(time=utc_ts(2024, 1, 1, 8, 0) + i * 3600, open=o, high=h, low=l, close=c, volume=10, spread=spread)


def _series(prices, lo=None, hi=None, step=1):
    lo = lo or [p - 1e-4 for p in prices]
    hi = hi or [p + 1e-4 for p in prices]
    return [_c(i, p, hi[i], lo[i], p) for i, p in enumerate(prices)]


def _zigzag(levels):
    """Build a bar series that produces explicit swings at left=2,right=2.

    Each tuple (kind, price) alternates low/high swings. Bars are constructed
    so each swing level is a strict fractal extremum with neighbors set well
    inside, guaranteeing detection.
    """
    bars = []
    n = len(levels)
    for i, (kind, price) in enumerate(levels):
        # neighbors of the swing are pulled 2 steps away from price so the
        # fractal window is clean
        base = price
        o = base
        if kind == "low":
            c = base + 0.001
            h = c + 0.0005
            l = base
        else:
            c = base - 0.001
            l = c - 0.0005
            h = base
        bars.append(_c(i, o, h, l, c))
    # pad in-between bars so fractal windows exist
    padded = []
    t = 0
    for i, (kind, price) in enumerate(levels):
        if i > 0:
            mid = (levels[i - 1][1] + price) / 2
            padded.append(_c(t, mid, mid + 0.0004, mid - 0.0004, mid))
            t += 1
        padded.append(_c(t, price, bars[i].high, bars[i].low, bars[i].close))
        t += 1
    return padded


class TestSwings:
    def test_swing_high_detected(self):
        prices = [1.0, 1.01, 1.02, 1.015, 1.005, 1.0]
        bars = _series(prices)
        sw = find_swings(bars, left=2, right=2)
        highs = [s for s in sw if s.kind == "high"]
        assert len(highs) == 1
        assert highs[0].price == pytest.approx(bars[2].high)

    def test_no_swing_at_edges(self):
        prices = [1.0] * 10
        assert find_swings(_series(prices), left=2, right=2) == []


class TestStructure:
    def test_bullish_structure(self):
        # HH: 1.05 -> 1.08 ; HL: 1.00 -> 1.03
        bars = [
            _c(0, 1.02, 1.025, 1.015, 1.024),
            _c(1, 1.024, 1.030, 1.022, 1.028),
            _c(2, 1.028, 1.050, 1.027, 1.048),   # swing high 1.05
            _c(3, 1.048, 1.049, 1.000, 1.002),   # swing low 1.00
            _c(4, 1.002, 1.010, 1.001, 1.009),
            _c(5, 1.009, 1.015, 1.008, 1.014),
            _c(6, 1.014, 1.030, 1.013, 1.029),   # swing low 1.03 (HL)
            _c(7, 1.029, 1.035, 1.028, 1.034),
            _c(8, 1.034, 1.080, 1.033, 1.078),   # swing high 1.08 (HH)
            _c(9, 1.078, 1.079, 1.077, 1.0775),
            _c(10, 1.0775, 1.078, 1.0765, 1.077),
        ]
        det = StructureDetector(left=2, right=2)
        state = det.update(bars)
        assert state.structure == "bullish"

    def test_bearish_structure(self):
        # LL: 1.07 -> 1.04 ; LH: 1.05 -> 1.03 (wait, lower highs 1.09->1.06)
        bars = [
            _c(0, 1.08, 1.085, 1.075, 1.084),
            _c(1, 1.084, 1.090, 1.082, 1.088),   # swing high 1.09
            _c(2, 1.088, 1.089, 1.070, 1.072),   # swing low 1.07
            _c(3, 1.072, 1.078, 1.071, 1.077),
            _c(4, 1.077, 1.060, 1.075, 1.058),   # swing high 1.06 (LH)
            _c(5, 1.058, 1.059, 1.040, 1.042),   # swing low 1.04 (LL)
            _c(6, 1.042, 1.050, 1.041, 1.049),
            _c(7, 1.049, 1.052, 1.048, 1.051),
            _c(8, 1.051, 1.053, 1.050, 1.0515),
        ]
        det = StructureDetector(left=2, right=2)
        state = det.update(bars)
        assert state.structure == "bearish"

    def test_bos_detected(self):
        # swing high 1.05 at idx2, then close breaks above it
        bars = [
            _c(0, 1.02, 1.025, 1.015, 1.024),
            _c(1, 1.024, 1.030, 1.022, 1.028),
            _c(2, 1.028, 1.050, 1.027, 1.048),   # swing high 1.05
            _c(3, 1.048, 1.049, 1.040, 1.042),
            _c(4, 1.042, 1.046, 1.041, 1.045),
            _c(5, 1.045, 1.046, 1.044, 1.045),
            _c(6, 1.045, 1.060, 1.044, 1.058),   # breaks 1.05 -> BOS
        ]
        bos = detect_bos(bars, left=2, right=2)
        assert bos is not None
        assert bos["kind"] == "high"

    def test_choch_detected_bearish_shift(self):
        # bullish structure: low 1.00 -> 1.02 (HL), highs 1.05 -> 1.07 (HH)
        # then a bar closes below the HL (1.02) => CHoCH on the final bar
        bars = [
            _c(0, 1.02, 1.025, 1.015, 1.024),
            _c(1, 1.024, 1.030, 1.022, 1.028),
            _c(2, 1.028, 1.050, 1.027, 1.048),   # swing high 1.05
            _c(3, 1.048, 1.049, 1.000, 1.002),   # swing low 1.00
            _c(4, 1.002, 1.010, 1.001, 1.009),
            _c(5, 1.009, 1.015, 1.008, 1.014),
            _c(6, 1.014, 1.020, 1.013, 1.019),
            _c(7, 1.019, 1.030, 1.028, 1.029),   # keep lows elevated for HL fractal
            _c(8, 1.029, 1.070, 1.030, 1.068),   # swing high 1.07 (HH)
            _c(9, 1.068, 1.030, 1.020, 1.022),   # swing low 1.02 (HL)
            _c(10, 1.022, 1.030, 1.024, 1.029),
            _c(11, 1.029, 1.032, 1.028, 1.031),
            _c(12, 1.031, 1.025, 1.010, 1.012),  # closes below 1.02 -> CHoCH
        ]
        choch = detect_choch(bars, left=2, right=2)
        assert choch is not None
        assert choch["kind"] == "low"

    def test_choch_fires_once(self):
        bars = [
            _c(0, 1.02, 1.025, 1.015, 1.024),
            _c(1, 1.024, 1.030, 1.022, 1.028),
            _c(2, 1.028, 1.050, 1.027, 1.048),
            _c(3, 1.048, 1.049, 1.000, 1.002),
            _c(4, 1.002, 1.010, 1.001, 1.009),
            _c(5, 1.009, 1.015, 1.008, 1.014),
            _c(6, 1.014, 1.020, 1.013, 1.019),
            _c(7, 1.019, 1.030, 1.028, 1.029),
            _c(8, 1.029, 1.070, 1.030, 1.068),
            _c(9, 1.068, 1.030, 1.020, 1.022),
            _c(10, 1.022, 1.030, 1.024, 1.029),
            _c(11, 1.029, 1.032, 1.028, 1.031),
            _c(12, 1.031, 1.025, 1.010, 1.012),   # CHoCH on bar 12
            _c(13, 1.012, 1.013, 1.009, 1.010),     # further down, no new CHoCH
        ]
        det = StructureDetector(left=2, right=2)
        hits = []
        last_event = None
        for i in range(len(bars)):
            st = det.update(bars[: i + 1])
            evt = st.last_choch
            if evt is not None and evt != last_event:
                hits.append(i)
                last_event = evt
        assert len(hits) == 1
        assert hits[0] == 12


class TestZones:
    def test_order_blocks(self):
        # down candle then big up move -> bullish OB
        bars = [
            _c(0, 1.10, 1.101, 1.099, 1.1005),  # small bearish
            _c(1, 1.1005, 1.1006, 1.0994, 1.0995),  # bearish body (OB)
            _c(2, 1.0995, 1.105, 1.0990, 1.1045),  # strong up move
        ]
        obs = find_order_blocks(bars)
        assert any(z.direction == "bullish" for z in obs)

    def test_fvg(self):
        bars = [
            _c(0, 1.10, 1.101, 1.099, 1.100),      # high = 1.101
            _c(1, 1.100, 1.1005, 1.0998, 1.1003),   # small
            _c(2, 1.1003, 1.105, 1.1020, 1.104),    # bullish, low 1.102 > 1.101
        ]
        fvgs = find_fvgs(bars)
        assert any(z.direction == "bullish" for z in fvgs)

    def test_rejection_blocks(self):
        # long lower wick with close near top
        bars = [_c(0, 1.10, 1.101, 1.095, 1.1005)]
        rbs = find_rejection_blocks(bars)
        assert any(z.direction == "bullish" for z in rbs)

    def test_liquidity_pools(self):
        bars = []
        for i in range(30):
            bars.append(_c(i, 1.10 + i * 1e-4, 1.1001 + i * 1e-4, 1.0999 + i * 1e-4, 1.10005 + i * 1e-4))
        # create repeated lows at 1.099
        for i in [3, 8, 13, 18]:
            bars[i] = _c(i, 1.10, 1.1002, 1.0990, 1.0995)
        lp = find_liquidity_pools(bars, min_touches=2, window_bars=20)
        assert any(z.direction == "bullish" and z.bottom <= 1.0991 for z in lp)


class TestBias:
    def test_bullish_bias_in_premium(self):
        prices = [1.0, 1.02, 1.04, 1.02, 1.06, 1.03, 1.07, 1.05, 1.08, 1.09]
        be = BiasEngine()
        res = be.compute(_series(prices))
        assert res.side == Side.BUY

    def test_bias_bearish_below_mid(self):
        prices = [1.10, 1.08, 1.06, 1.09, 1.05, 1.04, 1.07, 1.03, 1.02, 1.01]
        be = BiasEngine()
        res = be.compute(_series(prices))
        assert res.side == Side.SELL


class TestCandles:
    def test_bullish_engulfing(self):
        prev = _c(0, 1.10, 1.101, 1.099, 1.0998)  # bearish body 1.0998-1.10
        cur = _c(1, 1.0995, 1.103, 1.0992, 1.1025)  # bullish body engulfs
        assert is_bullish_engulfing(prev, cur)

    def test_not_engulfing_when_inside(self):
        prev = _c(0, 1.10, 1.101, 1.099, 1.0995)
        cur = _c(1, 1.0997, 1.1005, 1.0994, 1.1002)
        assert not is_bullish_engulfing(prev, cur)

    def test_hammer(self):
        c = _c(0, 1.10, 1.1005, 1.095, 1.1002)  # long lower wick, small body
        assert is_hammer(c, min_wick_ratio=1.5)

    def test_mother_baby(self):
        mother = _c(1, 1.1005, 1.104, 1.100, 1.1035)  # strong bull body 1.1005-1.1035
        baby = _c(2, 1.1024, 1.1030, 1.1022, 1.1026)  # small doji inside mother
        assert is_mother_baby(None, mother, baby)


class TestConfluence:
    def _bias(self, side):
        return BiasEngine().compute([_c(i, 1.0, 1.01, 0.99, 1.005) for i in range(20)])

    def test_confluence_bias_only_is_low(self):
        from trading_bot.strategy.smc.bias import BiasResult
        from trading_bot.core.enums import ConfluenceLevel

        bias = BiasResult(side=Side.BUY, source="structure", structure="bullish", votes={"structure": 1})
        res = compute_confluence(Side.BUY, bias, zones=[], entry_price=1.0)
        assert res.score == 1
        assert res.level == ConfluenceLevel.LOW

    def test_confluence_high(self):
        from trading_bot.core.enums import ConfluenceLevel
        from trading_bot.strategy.smc.bias import BiasResult
        from trading_bot.strategy.smc.zones import Zone

        bias = BiasResult(
            side=Side.BUY, source="crt_momentum", structure="bullish",
            premium_discount="discount", votes={"structure": 1, "premium_discount": 1, "momentum": 1},
        )
        zones = [Zone(kind="order_block", top=1.005, bottom=0.995, direction="bullish")]
        liquidity = [Zone(kind="liquidity", top=0.9901, bottom=0.9899, direction="bullish", extra={"side": "below"})]
        res = compute_confluence(
            Side.BUY, bias, zones=zones, entry_price=1.0,
            liquidity_zones=liquidity,
        )
        assert res.score >= 3
        assert res.level == ConfluenceLevel.HIGH
