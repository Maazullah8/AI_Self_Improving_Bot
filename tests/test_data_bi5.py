"""Tests for BI5 and MT5 data providers."""
import os
import struct

import pytest

from trading_bot.core.enums import Timeframe
from trading_bot.core.time_utils import utc_ts
from trading_bot.data.base import MarketDataQuery
from trading_bot.data.bi5_provider import BI5DataProvider


def _write_bi5(path, scale, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        for bid, ask, bidvol, askvol in records:
            f.write(struct.pack(">iiii", bid, ask, bidvol, askvol))


class TestBI5:
    def test_load_hour(self, tmp_path):
        root = str(tmp_path)
        ts = utc_ts(2024, 1, 15, 10, 30)
        dt = __import__("datetime", fromlist=["datetime"]).datetime.fromtimestamp(
            ts, tz=__import__("datetime", fromlist=["timezone"]).timezone.utc
        )
        rel = f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
        path = os.path.join(root, rel)
        scale = 1e-5
        # bid/ask in raw ints: e.g. 110000 -> 1.10000
        _write_bi5(path, scale, [(110000, 110010, 5, 5), (110005, 110015, 4, 4), (110002, 110012, 3, 3)])
        prov = BI5DataProvider(root, symbol="EURUSD")
        ticks = prov.load_ticks(
            MarketDataQuery(symbol="EURUSD", timeframe=Timeframe.M1, start=utc_ts(2024,1,15), end=utc_ts(2024,1,15,23,59))
        )
        assert len(ticks) == 3
        assert ticks[0].bid == pytest.approx(1.10)
        assert ticks[0].ask == pytest.approx(1.1001)
        assert ticks[1].time - ticks[0].time == 1

    def test_candles_from_bi5(self, tmp_path):
        root = str(tmp_path)
        ts = utc_ts(2024, 1, 15, 10, 30)
        dt = __import__("datetime", fromlist=["datetime"]).datetime.fromtimestamp(
            ts, tz=__import__("datetime", fromlist=["timezone"]).timezone.utc
        )
        rel = f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/{dt.hour:02d}h_ticks.bi5"
        path = os.path.join(root, rel)
        scale = 1e-5
        _write_bi5(path, scale, [(110000, 110010, 5, 5), (110010, 110020, 4, 4), (110020, 110030, 3, 3)])
        prov = BI5DataProvider(root, symbol="EURUSD")
        bars = prov.load_candles(
            MarketDataQuery(symbol="EURUSD", timeframe=Timeframe.M1, start=utc_ts(2024,1,15), end=utc_ts(2024,1,15,23,59))
        )
        assert len(bars) >= 1
        assert bars[0].low <= bars[0].high
