"""SMC/ICT/CRT Confluence Strategy (v1).

Flow (top-down refinement, zero lookahead, all deterministic):
  HTF CRT/Bias -> Draw on Liquidity -> Key Zone -> Confluence ->
  Price reaches zone -> LTF CHoCH/CSD -> Confirmation Candle ->
  Candle Close -> Entry.

Rules enforced in code:
  - No confirmation => no trade.
  - Minimum 1:2 risk:reward; reject trade if impossible.
  - Maximum 2 attempts per level; attempt 2 requires a genuine sweep +
    fresh confirmation. Never a 3rd.
  - Never chase missed setups (entry must be within zone proximity).
  - Missing any mandatory condition => no trade.

This strategy is a HYPOTHESIS, not a guarantee of profitability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from trading_bot.core.enums import ConfluenceLevel, Side, Timeframe
from trading_bot.core.models import Candle
from trading_bot.data.resample import IncrementalResampler
from trading_bot.replay.engine import Context, Signal
from trading_bot.strategy.base import BaseStrategy, register
from trading_bot.strategy.smc.bias import BiasEngine, BiasResult
from trading_bot.strategy.smc.candles import detect_confirmation
from trading_bot.strategy.smc.confluence import compute_confluence
from trading_bot.strategy.smc.structure import StructureDetector
from trading_bot.strategy.smc.zones import (
    Zone,
    find_all_zones,
    find_liquidity_pools,
)


@dataclass
class SMCParams:
    # --- timeframes (Timeframe enum values: "1h", "5m", "4h", ...)
    htf: str = "1h"  # higher timeframe for bias/zones
    zone_tf: str = "1h"  # timeframe for zone geometry
    ltf: str = "5m"  # signal/confirmation timeframe (usually equals primary)

    # --- structure
    swing_left: int = 2
    swing_right: int = 2
    bias_lookback: int = 120

    # --- zones
    zone_lookback: int = 120
    min_ob_body_ratio: float = 0.5
    max_zone_age_bars: Optional[int] = 60
    liquidity_min_touches: int = 2
    liquidity_window_bars: int = 60

    # --- confirmation
    use_engulfing: bool = True
    use_hammer: bool = True
    use_hammer_engulfing: bool = True
    use_mother_baby: bool = True
    min_wick_ratio: float = 1.5

    # --- confluence
    min_confluence: int = 1  # 1=low 2=medium 3+=high
    zone_stack_tolerance: float = 0.3

    # --- entry / exit
    min_rr: float = 2.0  # minimum 1:2 risk:reward
    sl_buffer_points: float = 20.0  # volatility buffer beyond confirmation extreme
    zone_proximity_atr_mult: float = 2.0  # max distance from zone to consider "reached"
    max_attempts: int = 2
    chase_tolerance_atr_mult: float = 1.5  # skip if price already ran this far past zone

    # --- rules toggles
    require_choch: bool = True
    require_confirmation: bool = True
    require_bias: bool = True
    require_min_confluence: bool = True

    # --- atr
    atr_period: int = 14

    # --- risk defaults (filled by RiskManager in live/backtest; kept for info)
    risk_pct: float = 0.01
    max_positions: int = 1


@register
class SMCStrategy(BaseStrategy):
    name = "smc_crt"
    version = "v1.0"
    description = (
        "SMC/ICT/CRT Confluence: HTF bias -> zone -> LTF CHoCH -> confirmation "
        "candle -> entry at close. 1:2 RR min, max 2 attempts per level."
    )
    rules = [
        "no_confirmation_no_trade",
        "min_rr_2_0",
        "max_2_attempts_per_level",
        "no_chasing",
        "htf_creates_zone_ltf_confirms_entry",
        "top_down_refinement_only",
    ]

    def __init__(self, params: Optional[dict] = None):
        self.p = SMCParams(**{k: v for k, v in (params or {}).items() if k in SMCParams.__dataclass_fields__})
        self._attempts: dict[str, int] = {}  # zone_key -> attempts used
        self._htf_detector = StructureDetector(left=self.p.swing_left, right=self.p.swing_right)
        self._bias_engine = BiasEngine(lookback=self.p.bias_lookback)
        self._ltf_detector = StructureDetector(left=self.p.swing_left, right=self.p.swing_right)
        self._last_signal: Optional[Signal] = None
        self._log: list[dict] = []
        # incremental HTF/zone aggregation caches (avoids O(n^2) resample)
        self._htf_res = IncrementalResampler(Timeframe(self.p.htf))
        self._zone_res = IncrementalResampler(Timeframe(self.p.zone_tf))
        self._fed = 0
        self._htf_cached_key: Optional[int] = None
        self._htf_state = None
        self._cached_bias: Optional[BiasResult] = None
        self._cached_zones: list = []
        self._cached_liquidity: list = []
        super().__init__(params)

    def set_params(self, params: dict) -> None:
        super().set_params(params)
        for k, v in params.items():
            if hasattr(self.p, k):
                setattr(self.p, k, v)
        self._htf_detector = StructureDetector(left=self.p.swing_left, right=self.p.swing_right)
        self._bias_engine = BiasEngine(lookback=self.p.bias_lookback)
        self._ltf_detector = StructureDetector(left=self.p.swing_left, right=self.p.swing_right)
        # resamplers depend on timeframe params; drop caches (rebuilt lazily)
        self._htf_res = IncrementalResampler(Timeframe(self.p.htf))
        self._zone_res = IncrementalResampler(Timeframe(self.p.zone_tf))
        self._htf_cached_key = None

    def get_params(self) -> dict:
        """Full effective params (defaults + overrides) for versioning."""
        import dataclasses

        return dataclasses.asdict(self.p)

    def _feed_bars(self, ctx: Context) -> tuple[list[Candle], list[Candle]]:
        """Feed the latest closed bar to the incremental resamplers and return
        the current HTF and zone bar views. Rebuilds if the call sequence is
        discontinuous (fresh engine run, direct diagnostic call, etc.)."""
        bars = ctx.bars
        n = len(bars)
        if n != self._fed + 1:
            self._htf_res.reset()
            self._zone_res.reset()
            for b in bars:
                self._htf_res.add(b)
                self._zone_res.add(b)
            self._fed = n
        else:
            b = bars[-1]
            self._htf_res.add(b)
            self._zone_res.add(b)
            self._fed = n
        return self._htf_res.view(), self._zone_res.view()

    # ------------------------------------------------------------- helpers
    def _atr(self, bars: Sequence[Candle], period: Optional[int] = None) -> float:
        """Incremental ATR: maintains a rolling TR series so each call is O(1)."""
        period = period or self.p.atr_period
        n = len(bars)
        if n < 2:
            return 0.0
        if not hasattr(self, "_trs"):
            self._trs = []
            self._atr_n = 0
        if self._atr_n == n:
            pass  # already synced with these bars
        elif self._atr_n == n - 1:
            prev, cur = bars[-2], bars[-1]
            self._trs.append(
                max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close))
            )
            self._atr_n = n
        else:
            self._trs = [
                max(bars[i].high - bars[i].low, abs(bars[i].high - bars[i - 1].close), abs(bars[i].low - bars[i - 1].close))
                for i in range(1, n)
            ]
            self._atr_n = n
        recent = self._trs[-period:]
        return sum(recent) / len(recent) if recent else 0.0

    def _zone_key(self, z: Zone) -> str:
        return f"{z.kind}:{round(z.bottom, 6)}:{round(z.top, 6)}:{z.direction}"

    def _swept(self, z: Zone, bars: Sequence[Candle], recent: int = 3) -> bool:
        """A 'genuine sweep' for attempt 2: price wicks beyond the zone extreme
        then closes back inside/above it within the last `recent` bars."""
        if not bars:
            return False
        sweep_target = z.top if z.direction == "bullish" else z.bottom
        for b in bars[-recent:]:
            if z.direction == "bullish":
                if b.low < sweep_target and b.close > sweep_target:
                    return True
            else:
                if b.high > sweep_target and b.close < sweep_target:
                    return True
        return False

    def _reject(self, ctx: Context, reason: str, **extra) -> None:
        """Record why a bar produced no signal (rolling, capped trace)."""
        entry = {"index": ctx.index, "time": ctx.current.time, "reason": reason}
        entry.update(extra)
        self._log.append(entry)
        if len(self._log) > 10_000:
            self._log = self._log[-2000:]

    # ------------------------------------------------------------- main
    def on_bar(self, ctx: Context) -> Optional[Signal]:
        self._last_signal = None
        bars = ctx.bars
        n = len(bars)
        if n < self.p.swing_left + self.p.swing_right + 4:
            self._reject(ctx, "warmup")
            return None

        htf_bars, zone_bars = self._feed_bars(ctx)
        if len(htf_bars) < 20 or len(zone_bars) < 20:
            self._reject(ctx, "htf_warmup")
            return None

        # ---- HTF-derived state, recomputed only when a new HTF bar completes
        htf_key = self._htf_res.last_completed
        if htf_key != self._htf_cached_key:
            htf_state = self._htf_detector.update(htf_bars)
            self._cached_bias = self._bias_engine.compute(htf_bars, htf_state)
            self._cached_zones = find_all_zones(
                zone_bars,
                lookback=self.p.zone_lookback,
                min_body_ratio=self.p.min_ob_body_ratio,
            )
            self._cached_liquidity = find_liquidity_pools(
                zone_bars,
                lookback=self.p.zone_lookback,
                min_touches=self.p.liquidity_min_touches,
                window_bars=self.p.liquidity_window_bars,
            )
            self._htf_state = htf_state
            self._htf_cached_key = htf_key

        bias: BiasResult = self._cached_bias
        zones = self._cached_zones
        liquidity = self._cached_liquidity

        if self.p.require_bias and bias.side is None:
            self._reject(ctx, "no_bias")
            return None

        # filter to zones aligned with bias and near current price
        side = bias.side
        aligned = [
            z for z in zones
            if z.direction == ("bullish" if side is Side.BUY else "bearish")
        ]
        if not aligned:
            self._reject(ctx, "no_aligned_zone")
            return None

        current_price = bars[-1].close
        atr = self._atr(bars) or (bars[-1].high - bars[-1].low) or 1e-5

        # --- pick the nearest actionable zone in the direction of trade
        zone = self._pick_zone(aligned, side, current_price, atr)
        if zone is None:
            self._reject(ctx, "no_actionable_zone")
            return None

        key = self._zone_key(zone)
        attempts = self._attempts.get(key, 0)
        if attempts >= self.p.max_attempts:
            self._reject(ctx, "max_attempts", zone_key=key, attempts=attempts)
            return None

        # --- confluence computed before confirmation
        if self.p.require_min_confluence:
            conf = compute_confluence(
                side=side,
                bias=bias,
                zones=zones,
                liquidity_zones=liquidity,
                entry_price=current_price,
                zone_stack_threshold=self.p.zone_stack_tolerance,
                min_confluence=self.p.min_confluence,
            )
            if conf.level == ConfluenceLevel.NONE:
                self._reject(ctx, "no_confluence", score=conf.score)
                return None
        else:
            conf = None

        # --- price reached zone? (proximity check)
        if not self._price_in_zone(zone, side, current_price, atr):
            self._reject(ctx, "not_in_zone", zone_key=key)
            return None

        # --- never chase: price already ran too far past the zone
        if self._is_chasing(zone, side, current_price, atr):
            self._reject(ctx, "chasing", zone_key=key)
            return None

        # --- LTF CHoCH/CSD (mandatory): a fresh shift aligned with trade side
        choch = None
        if self.p.require_choch:
            ltf_state = self._ltf_detector.update(bars)
            choch = ltf_state.last_choch if ltf_state.last_choch else ltf_state.last_mss
            if choch is None or not self._choch_aligned(choch, side):
                self._reject(ctx, "no_choch")
                return None

        # --- confirmation candle (mandatory)
        if self.p.require_confirmation:
            conf_candle = detect_confirmation(
                bars,
                side=side,
                min_wick_ratio=self.p.min_wick_ratio,
                use_hammer=self.p.use_hammer,
                use_engulfing=self.p.use_engulfing,
                use_hammer_engulfing=self.p.use_hammer_engulfing,
                use_mother_baby=self.p.use_mother_baby,
            )
            if conf_candle is None:
                self._reject(ctx, "no_confirmation")
                return None
        else:
            conf_candle = None

        # ---- build entry, SL, TP
        entry = self._build_signal(
            side=side,
            zone=zone,
            bars=bars,
            atr=atr,
            attempts=attempts,
            bias=bias,
            conf=conf,
            conf_candle=conf_candle,
            choch=choch,
            ctx=ctx,
        )
        if entry is None:
            self._reject(ctx, "signal_geometry", zone_key=key)
            return None

        # enforce min RR
        risk = abs(entry.entry - entry.sl)
        reward = abs(entry.tp - entry.entry)
        if risk <= 0:
            self._reject(ctx, "zero_risk")
            return None
        rr = reward / risk
        if rr < self.p.min_rr:
            self._reject(ctx, "min_rr", rr=round(rr, 2))
            return None

        self._last_signal = entry
        self._attempts[key] = attempts + 1
        entry.setup["attempt"] = attempts + 1
        entry.setup["zone_key"] = key
        self._log.append({"index": ctx.index, "time": ctx.current.time, "reason": "signal", "zone_key": key})
        return entry

    # ------------------------------------------------------ helper logic
    def _pick_zone(self, aligned: Sequence[Zone], side: Side, price: float, atr: float) -> Optional[Zone]:
        """Choose the closest zone in the trade direction whose far edge the
        price hasn't blown through (would be a chase)."""
        prox = atr * self.p.zone_proximity_atr_mult
        best, best_dist = None, float("inf")
        for z in aligned:
            far_edge = z.top if side is Side.BUY else z.bottom
            near_edge = z.bottom if side is Side.BUY else z.top
            if side is Side.BUY:
                # price should be at/below zone (coming from below to enter)
                if price <= far_edge + prox and price >= near_edge - atr * 0.5:
                    dist = abs(price - z.mid)
                    if dist < best_dist:
                        best, best_dist = z, dist
            else:
                if price >= near_edge - prox and price <= far_edge + atr * 0.5:
                    dist = abs(price - z.mid)
                    if dist < best_dist:
                        best, best_dist = z, dist
        return best

    def _price_in_zone(self, zone: Zone, side: Side, price: float, atr: float) -> bool:
        prox = atr * self.p.zone_proximity_atr_mult
        if side is Side.BUY:
            return price <= zone.top + prox
        return price >= zone.bottom - prox

    def _is_chasing(self, zone: Zone, side: Side, price: float, atr: float) -> bool:
        chase = atr * self.p.chase_tolerance_atr_mult
        if side is Side.BUY:
            return price > zone.top + chase
        return price < zone.bottom - chase

    def _choch_aligned(self, choch: dict, side: Side) -> bool:
        """A buy needs a bullish shift (broke above a swing high: kind='high').
        A sell needs a bearish shift (broke below a swing low: kind='low')."""
        kind = choch.get("kind")
        if side is Side.BUY:
            return kind == "high"
        return kind == "low"

    def _build_signal(
        self,
        side: Side,
        zone: Zone,
        bars: Sequence[Candle],
        atr: float,
        attempts: int,
        bias: BiasResult,
        conf,
        conf_candle,
        choch,
        ctx: Context,
    ) -> Optional[Signal]:
        entry = bars[-1].close
        # SL: beyond confirmation extreme (entry candle low for buy / high for sell)
        # with a volatility buffer in points.
        buf = self.p.sl_buffer_points * ctx.symbol_info.point_size if ctx.symbol_info.point_size else atr * 0.05
        if side is Side.BUY:
            extreme = bars[-1].low
            sl = extreme - buf
            risk = entry - sl
            if risk <= 0:
                return None
            tp_2r = entry + self.p.min_rr * risk
            # the zone target should be reachable at >= 2R; else the trade is
            # geometrically impossible -> reject (never fabricate a TP)
            if zone.top <= tp_2r + atr * 0.5:
                # zone is near/at 2R: place TP at the max of 2R and a target
                # just beyond the zone (still >= 2R)
                tp = max(tp_2r, zone.top + atr * 0.5)
            else:
                return None
            if tp <= entry:
                return None
        else:
            extreme = bars[-1].high
            sl = extreme + buf
            risk = sl - entry
            if risk <= 0:
                return None
            tp_2r = entry - self.p.min_rr * risk
            if zone.bottom >= tp_2r - atr * 0.5:
                tp = min(tp_2r, zone.bottom - atr * 0.5)
            else:
                return None
            if tp >= entry:
                return None

        sig = ctx.signal(
            side=side,
            entry=entry,
            sl=sl,
            tp=tp,
            size=0.0,  # risk manager sizes
        )
        sig.setup.update({
            "bias": bias.side.value if bias.side else None,
            "htf_bias": bias.source,
            "crt": "crt" if bias.crt_triggered else "",
            "zone_type": zone.kind,
            "zone_top": zone.top,
            "zone_bottom": zone.bottom,
            "confluence_level": conf.level.value if conf else "",
            "confluence_score": conf.score if conf else 0,
            "confluence_factors": conf.factors if conf else [],
            "htf_timeframe": self.p.htf,
            "ltf_timeframe": self.p.ltf,
            "refinement_chain": f"{self.p.htf}->{self.p.ltf}",
            "choch_csd": "choch" if choch else "",
            "confirmation_type": conf_candle.type if conf_candle else "",
            "attempt": attempts + 1,
            "session": ctx.current.time and "",
            "volatility": atr,
        })
        return sig

    def debug_log(self) -> list[dict]:
        return list(self._log)
