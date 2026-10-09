from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from src.common.config import get_config
from src.news import reaction as R

REL = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)  # 08:30 ET (pre-market)


def _bars(start: datetime, n: int, f) -> pd.DataFrame:
    idx = pd.DatetimeIndex([start + timedelta(minutes=i) for i in range(n)])
    return pd.DataFrame({"Close": [f(i) for i in range(n)]}, index=idx)


class P:
    def __init__(self, frames):
        self.frames = frames

    def get_intraday(self, symbol, *, interval="1m", days=1):
        return self.frames.get(symbol, pd.DataFrame())


def test_premarket_release_uses_futures_and_windows_on_bar_time() -> None:
    cfg = get_config().news.reaction
    assert R.instruments_for(REL, cfg)["stocks"] == "ES=F"
    start = REL - timedelta(minutes=5)
    frames = {
        "ES=F": _bars(start, 30, lambda i: 6000.0 if i < 5 else 5928.0),  # −1.2%
        "ZN=F": _bars(start, 30, lambda i: 110.0 if i < 5 else 109.5),
    }
    r = R.measure_reaction(REL, cfg=cfg, provider=P(frames))
    stocks = next(m for m in r.moves if m.asset == "stocks")
    assert round(stocks.move, 2) == -1.2 and stocks.arrow == "🔴"
    assert r.complete is False  # dollar/gold/oil frames missing


def test_delayed_data_is_incomplete_not_wrong() -> None:
    cfg = get_config().news.reaction
    frames = {
        "ES=F": _bars(REL - timedelta(minutes=5), 10, lambda i: 6000.0)
    }  # ends before release+15
    r = R.measure_reaction(REL, cfg=cfg, provider=P(frames))
    assert next(m for m in r.moves if m.asset == "stocks").move is None


def test_rth_yield_reported_in_bp_with_inverted_arrow() -> None:
    cfg = get_config().news.reaction
    rel = datetime(2026, 10, 14, 18, 0, tzinfo=UTC)  # 14:00 ET
    assert R.instruments_for(rel, cfg)["bonds"] == "^TNX"
    frames = {"^TNX": _bars(rel - timedelta(minutes=3), 25, lambda i: 42.0 if i < 3 else 42.9)}
    bonds = next(
        m for m in R.measure_reaction(rel, cfg=cfg, provider=P(frames)).moves if m.asset == "bonds"
    )
    assert bonds.unit == "bp" and round(bonds.move) == 9 and bonds.arrow == "🔴"


def test_waited_too_long() -> None:
    cfg = get_config().news.reaction
    assert not R.waited_too_long(REL, REL + timedelta(minutes=20), cfg)
    assert R.waited_too_long(REL, REL + timedelta(minutes=36), cfg)
