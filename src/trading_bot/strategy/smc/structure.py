"""SMC structure detection: swings, BOS, CHoCH/MSS.

Implements deterministic market-structure primitives used by the strategy.
All functions are pure: they operate on a list of bars and return results
for the final (current) bar. No lookahead by construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from trading_bot.core.models import Candle


@dataclass
class Swing:
    """A fractal swing high/low point."""

    index: int
    price: float
    kind: str  # 'high' | 'low'
    time: int


@dataclass
class StructureState:
    last_swing_high: Optional[Swing] = None
    last_swing_low: Optional[Swing] = None
    prev_swing_high: Optional[Swing] = None
    prev_swing_low: Optional[Swing] = None
    # market structure: 'bullish' (higher highs + higher lows) or 'bearish'
    structure: str = "neutral"
    last_bos: Optional[dict] = None  # {'index','price','kind','time'}
    last_choch: Optional[dict] = None
    last_mss: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "structure": self.structure,
            "last_swing_high": self.last_swing_high.price if self.last_swing_high else None,
            "last_swing_low": self.last_swing_low.price if self.last_swing_low else None,
            "prev_swing_high": self.prev_swing_high.price if self.prev_swing_high else None,
            "prev_swing_low": self.prev_swing_low.price if self.prev_swing_low else None,
            "last_bos": self.last_bos,
            "last_choch": self.last_choch,
            "last_mss": self.last_mss,
        }


def find_swings(
    bars: Sequence[Candle],
    left: int = 2,
    right: int = 2,
) -> list[Swing]:
    """Find fractal swings. A bar at index i is a swing high if it is the
    highest high over the window [i-left, i+right] (inclusive of both sides
    with equal comparison -> strict). Using right>0 introduces a lag of
    `right` bars; this is intentional and is NOT lookahead because we only
    emit a swing after the right window has confirmed."""
    swings: list[Swing] = []
    n = len(bars)
    for i in range(left, n - right):
        h = bars[i].high
        l = bars[i].low
        is_high = all(bars[j].high <= h for j in range(i - left, i + right + 1)) and (
            h > bars[i - 1].high and h > bars[i + 1].high
        )
        is_low = all(bars[j].low >= l for j in range(i - left, i + right + 1)) and (
            l < bars[i - 1].low and l < bars[i + 1].low
        )
        if is_high:
            swings.append(Swing(index=i, price=h, kind="high", time=bars[i].time))
        elif is_low:
            swings.append(Swing(index=i, price=l, kind="low", time=bars[i].time))
    return swings


class StructureDetector:
    """Incremental market structure state machine.

    Feed closed bars one at a time via ``update(bars)`` with the full bar
    list (it maintains internal swing state for the confirmed portion).
    """

    def __init__(self, left: int = 2, right: int = 2):
        self.left = left
        self.right = right
        self.swings: list[Swing] = []
        self.state = StructureState()
        self._last_confirmed_index = -1

    def reset(self) -> None:
        self.swings = []
        self.state = StructureState()
        self._last_confirmed_index = -1

    def _commit_swings(self, bars: Sequence[Candle]) -> None:
        """Commit any newly confirmed swings given current bars.

        A swing at index i is confirmable once bar i+right exists (the right
        fractal window has closed). This is NOT lookahead: the swing is only
        emitted after that bar actually closes.
        """
        n = len(bars)
        # Highest index whose fractal window [i-left, i+right] is fully inside bars
        max_confirmable = n - self.right - 1
        start = max(self.left, self._last_confirmed_index + 1)
        for i in range(start, max_confirmable + 1):
            h = bars[i].high
            l = bars[i].low
            is_high = all(bars[j].high <= h for j in range(i - self.left, i + self.right + 1)) and (
                h > bars[i - 1].high and h > bars[i + 1].high
            )
            is_low = all(bars[j].low >= l for j in range(i - self.left, i + self.right + 1)) and (
                l < bars[i - 1].low and l < bars[i + 1].low
            )
            if is_high:
                self._add_swing(Swing(index=i, price=h, kind="high", time=bars[i].time))
            elif is_low:
                self._add_swing(Swing(index=i, price=l, kind="low", time=bars[i].time))
            self._last_confirmed_index = i

    def _add_swing(self, sw: Swing) -> None:
        self.swings.append(sw)
        st = self.state
        # maintain prev/last pairs per kind
        if sw.kind == "high":
            st.prev_swing_high = st.last_swing_high
            st.last_swing_high = sw
            if st.prev_swing_high is not None:
                if sw.price > st.prev_swing_high.price:
                    st.structure = "bullish"
                elif sw.price < st.prev_swing_high.price:
                    st.structure = "bearish"
        else:
            st.prev_swing_low = st.last_swing_low
            st.last_swing_low = sw
            if st.prev_swing_low is not None:
                if sw.price > st.prev_swing_low.price:
                    st.structure = "bullish"
                elif sw.price < st.prev_swing_low.price:
                    st.structure = "bearish"

    def _detect_bos_choch(self, bars: Sequence[Candle]) -> None:
        st = self.state
        n = len(bars)
        if n == 0:
            return
        current = bars[-1]
        # Track which swing levels we've already broken so each BOS/CHoCH
        # fires only on the bar that first breaks the level. BOS and CHoCH
        # keep separate markers so one does not suppress the other.
        for attr in ("_bos_high", "_bos_low", "_choch_high", "_choch_low"):
            if not hasattr(self, attr):
                setattr(self, attr, None)

        # BOS: bullish break above prior swing high, or bearish break below
        if st.last_swing_high is not None and current.close > st.last_swing_high.price:
            if self._bos_high != st.last_swing_high.price:
                self._bos_high = st.last_swing_high.price
                st.last_bos = {
                    "index": n - 1,
                    "price": st.last_swing_high.price,
                    "kind": "high",
                    "time": current.time,
                }
        if st.last_swing_low is not None and current.close < st.last_swing_low.price:
            if self._bos_low != st.last_swing_low.price:
                self._bos_low = st.last_swing_low.price
                st.last_bos = {
                    "index": n - 1,
                    "price": st.last_swing_low.price,
                    "kind": "low",
                    "time": current.time,
                }

        # CHoCH/MSS: change of character = break against the prevailing trend
        # structure. In a bullish structure, a close below the last higher
        # low is a CHoCH/MSS; in bearish structure, close above last higher high.
        if st.structure == "bullish" and st.last_swing_low is not None:
            if current.close < st.last_swing_low.price and self._choch_low != st.last_swing_low.price:
                self._choch_low = st.last_swing_low.price
                evt = {"index": n - 1, "price": st.last_swing_low.price, "kind": "low", "time": current.time}
                st.last_choch = evt
                st.last_mss = evt
        elif st.structure == "bearish" and st.last_swing_high is not None:
            if current.close > st.last_swing_high.price and self._choch_high != st.last_swing_high.price:
                self._choch_high = st.last_swing_high.price
                evt = {"index": n - 1, "price": st.last_swing_high.price, "kind": "high", "time": current.time}
                st.last_choch = evt
                st.last_mss = evt

    def update(self, bars: Sequence[Candle]) -> StructureState:
        self._commit_swings(bars)
        self._detect_bos_choch(bars)
        return self.state


def detect_choch(bars: Sequence[Candle], left: int = 2, right: int = 2) -> Optional[dict]:
    """One-shot: was there a CHoCH/MSS on the final bar of ``bars``?"""
    if len(bars) < left + right + 2:
        return None
    det = StructureDetector(left=left, right=right)
    det.update(bars[:-1])
    st = det.state
    before = dict(st.to_dict())
    det.update(bars)
    after = det.state
    if after.last_mss is not None and after.last_mss != before.get("last_mss"):
        return after.last_mss
    if after.last_choch is not None and after.last_choch != before.get("last_choch"):
        return after.last_choch
    return None


def detect_bos(bars: Sequence[Candle], left: int = 2, right: int = 2) -> Optional[dict]:
    """One-shot: was there a BOS on the final bar?"""
    if len(bars) < left + right + 2:
        return None
    det = StructureDetector(left=left, right=right)
    det.update(bars[:-1])
    before = det.state.last_bos
    det.update(bars)
    after = det.state.last_bos
    if after is not None and after != before:
        return after
    return None
