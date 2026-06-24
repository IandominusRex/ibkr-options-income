"""Tests for the single-ticker sector/market backdrop (src/analytics/sector_context.py).

yfinance and the OHLCV store are mocked — no network or DB needed.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from src.analytics import sector_context as sectx
from src.analytics.sector_context import get_sector_context, render_sector_context
from src.common.schemas import SectorContext


def _frame(last: float, ago_1mo: float, ago_5d: float) -> pd.DataFrame:
    """A 30-row Close series where index -22 == ago_1mo and -6 == ago_5d, -1 == last."""
    closes = [100.0] * 30
    closes[-1] = last
    closes[-1 - 21] = ago_1mo  # 1mo lookback = 21 sessions
    closes[-1 - 5] = ago_5d  # 5d lookback
    return pd.DataFrame({"Close": closes})


def test_get_sector_context_maps_sector_to_etf_and_computes_returns():
    def fake_ohlcv(sym: str) -> pd.DataFrame:
        return {
            "XLK": _frame(110.0, 100.0, 105.0),  # +10% 1mo, ~+4.76% 5d
            "SPY": _frame(102.0, 100.0, 101.0),  # +2% 1mo
            "NVDA": _frame(120.0, 100.0, 110.0),  # +20% 1mo
        }[sym]

    with patch.object(sectx, "_sector_industry", return_value=("Technology", "Semiconductors")):
        with patch.object(sectx, "get_ohlcv", side_effect=fake_ohlcv):
            sc = get_sector_context("nvda")

    assert sc.symbol == "NVDA"
    assert sc.sector == "Technology"
    assert sc.industry == "Semiconductors"
    assert sc.sector_etf == "XLK"
    assert sc.sector_ret_1mo_pct == 10.0
    assert sc.spy_ret_1mo_pct == 2.0
    assert sc.symbol_ret_1mo_pct == 20.0
    # relative strength = symbol - sector = 20 - 10
    assert sc.rel_strength_1mo_pct == 10.0


def test_get_sector_context_etf_has_no_sector_but_still_returns_spy():
    """ETFs/indices return (None, None) from the lookup — no sector ETF, SPY still computed."""
    with patch.object(sectx, "_sector_industry", return_value=(None, None)):
        with patch.object(sectx, "get_ohlcv", return_value=_frame(101.0, 100.0, 100.5)):
            sc = get_sector_context("SPY")

    assert sc.sector is None
    assert sc.sector_etf is None
    assert sc.sector_ret_1mo_pct is None
    assert sc.spy_ret_1mo_pct == 1.0
    assert sc.rel_strength_1mo_pct is None  # needs both symbol and sector


def test_get_sector_context_fail_soft_on_ohlcv_error():
    with patch.object(sectx, "_sector_industry", return_value=("Energy", "Oil & Gas")):
        with patch.object(sectx, "get_ohlcv", side_effect=RuntimeError("boom")):
            sc = get_sector_context("XOM")

    assert sc.symbol == "XOM"
    assert sc.sector == "Energy"
    assert sc.sector_etf == "XLE"
    # All returns degrade to None rather than raising.
    assert sc.sector_ret_1mo_pct is None
    assert sc.spy_ret_1mo_pct is None


def test_get_sector_context_short_history_returns_none():
    """A frame with fewer rows than the lookback yields None, not an IndexError."""
    short = pd.DataFrame({"Close": [100.0, 101.0, 102.0]})  # < 21 rows
    with patch.object(sectx, "_sector_industry", return_value=("Technology", None)):
        with patch.object(sectx, "get_ohlcv", return_value=short):
            sc = get_sector_context("AAPL")
    assert sc.sector_ret_1mo_pct is None


def test_render_sector_context_empty_when_no_data():
    assert render_sector_context(SectorContext(symbol="X")) == ""
    assert render_sector_context(None) == ""


def test_render_sector_context_includes_label_and_returns():
    sc = SectorContext(
        symbol="NVDA",
        sector="Technology",
        industry="Semiconductors",
        sector_etf="XLK",
        sector_ret_1mo_pct=3.2,
        spy_ret_1mo_pct=1.4,
        symbol_ret_1mo_pct=6.1,
        rel_strength_1mo_pct=2.9,
    )
    block = render_sector_context(sc)
    assert "SECTOR & MARKET BACKDROP" in block
    assert "Technology / Semiconductors" in block
    assert "XLK" in block
    assert "outperforming" in block
