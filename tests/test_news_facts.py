from __future__ import annotations

import math
from datetime import date

import pandas as pd

from src.common.config import get_config
from src.common.schemas import IVStats, OptionRight, PositionSnapshot, SectorContext, TechnicalStats
from src.news import facts as F
from src.news.schemas import EarningsView
from src.news.tape import Quote

TODAY = date(2026, 10, 9)


def _an(*, chg=-6.2, iv=48.0, rsi=27.0, sma200=172.0, support=(170.0,), prev=180.0) -> F.Analytics:
    last = prev * (1 + chg / 100)
    quotes = {
        "NVDA": Quote(symbol="NVDA", last=last, prev_close=prev, change_pct=chg),
        "SPY": Quote(symbol="SPY", last=600, prev_close=606, change_pct=-1.0),
        "XLK": Quote(symbol="XLK", last=200, prev_close=204, change_pct=-2.0),
    }
    return F.Analytics(
        technicals=lambda s: TechnicalStats(
            symbol=s,
            price=last,
            rsi_14=rsi,
            atr_14=4.0,
            sma_50=178.0,
            sma_200=sma200,
            support_levels=list(support),
            resistance_levels=[190.0],
        ),
        iv=lambda s: IVStats(symbol=s, current_iv=iv, iv_rank=62.0, hv_30=40.0),
        sector=lambda s: SectorContext(symbol=s, sector="Technology", sector_etf="XLK"),
        quote=lambda s: quotes.get(s, Quote(symbol=s)),
        daily=lambda s: pd.DataFrame(),
        past_earnings=lambda s: [],
    )


def test_sigma_and_expected_move() -> None:
    assert round(F.sigma_move(-6.2, 48.0), 2) == round(6.2 / (48 / math.sqrt(252)), 2)
    assert F.sigma_move(1.0, None) is None and F.sigma_move(None, 30.0) is None
    assert round(F.expected_move(100.0, 40.0, 365), 2) == 40.0


def test_ticker_facts_numbered_and_book_aware() -> None:
    pos = [
        PositionSnapshot(
            symbol="NVDA",
            sec_type="OPT",
            position=-1,
            avg_cost=1.2,
            right=OptionRight.PUT,
            strike=165.0,
            expiry=date(2026, 10, 23),
            underlying="NVDA",
        )
    ]
    sheet = F.build_ticker_facts(
        "NVDA",
        an=_an(),
        positions=pos,
        lists=["actively_wheeling"],
        earnings=None,
        cluster_tags=set(),
        today=TODAY,
        cfg=get_config().news,
    )
    assert [f.id for f in sheet.facts] == [f"F{i}" for i in range(1, len(sheet.facts) + 1)]
    assert sheet.get("Move today").display == "-6.2%"
    assert sheet.get("Move vs SPY").value == -5.2
    assert sheet.get("Move vs XLK").value == -4.2
    book = next(f for f in sheet.facts if f.label.startswith("Position NVDA 165P"))
    assert "14 DTE" in book.display and "% OTM" in book.display and "exp. moves" in book.display
    assert "large_move_no_hard_news" in sheet.flags
    assert "oversold_at_support" in sheet.flags
    assert "sector_move" not in sheet.flags
    assert "F1" in sheet.render()


def test_sector_move_flag_and_rumor() -> None:
    an = _an(chg=-2.2)
    sheet = F.build_ticker_facts(
        "NVDA",
        an=an,
        positions=[],
        lists=[],
        earnings=None,
        cluster_tags={"rumor", "quantified"},
        today=TODAY,
        cfg=get_config().news,
    )
    assert "sector_move" in sheet.flags and "rumor_driven" in sheet.flags
    assert "large_move_no_hard_news" not in sheet.flags
    assert sheet.get("Universe").display == "not in universe"


def test_earnings_facts() -> None:
    e = EarningsView(
        symbol="NVDA",
        report_date=TODAY,
        timing="amc",
        eps_est=2.0,
        eps_actual=2.3,
        rev_est=40e9,
        rev_actual=42e9,
        status="released",
    )
    sheet = F.build_ticker_facts(
        "NVDA",
        an=_an(chg=-9.0),
        positions=[],
        lists=["watchlist"],
        earnings=e,
        cluster_tags=set(),
        today=TODAY,
        cfg=get_config().news,
    )
    assert sheet.get("EPS vs est").display == "EPS 2.30 vs 2.00 est"
    assert sheet.get("Revenue vs est").display == "Rev 42.0B vs 40.0B est"
    assert "earnings_outsized" in sheet.flags


def test_degrades_when_analytics_missing() -> None:
    an = F.Analytics(
        technicals=lambda s: None,
        iv=lambda s: None,
        sector=lambda s: None,
        quote=lambda s: Quote(symbol=s),
        daily=lambda s: pd.DataFrame(),
        past_earnings=lambda s: [],
    )
    sheet = F.build_ticker_facts(
        "ZZZ",
        an=an,
        positions=[],
        lists=[],
        earnings=None,
        cluster_tags=set(),
        today=TODAY,
        cfg=get_config().news,
    )
    assert sheet.get("Move today") is None and sheet.flags == {}


def test_post_earnings_moves() -> None:
    idx = pd.to_datetime(["2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"])
    df = pd.DataFrame({"Close": [100.0, 101.0, 91.0, 92.0]}, index=idx)
    assert [round(x, 2) for x in F.post_earnings_moves(df, [date(2026, 7, 29)])] == [-9.9]


def test_post_earnings_moves_before_open_report() -> None:
    # A before-open report reacts on the report day itself: 100 → 91 on 07-29, quiet after.
    idx = pd.to_datetime(["2026-07-28", "2026-07-29", "2026-07-30"])
    df = pd.DataFrame({"Close": [100.0, 91.0, 91.5]}, index=idx)
    assert [round(x, 2) for x in F.post_earnings_moves(df, [date(2026, 7, 29)])] == [-9.0]


def test_live_daily_returns_a_non_empty_frame(monkeypatch) -> None:
    import src.data.factory as factory

    df = pd.DataFrame({"Close": [1.0, 2.0]})
    provider = type("P", (), {"get_ohlcv": lambda self, s, lookback_days=365: df})()
    monkeypatch.setattr(factory, "get_price_provider", lambda: provider)
    assert F.Analytics.live().daily("NVDA") is df
