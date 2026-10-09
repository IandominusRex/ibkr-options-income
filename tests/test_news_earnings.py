from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from src.data.nasdaq_backend import parse_nasdaq_earnings
from src.data.protocols import EarningsItem

FIX = Path(__file__).parent / "fixtures" / "news"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_nasdaq_earnings_timing_and_money() -> None:
    rows = {
        r.symbol: r
        for r in parse_nasdaq_earnings(
            json.loads((FIX / "nasdaq_earnings_2026-10-14.json").read_text()), date(2026, 10, 14)
        )
    }
    assert rows["BAC"].timing == "bmo" and rows["BAC"].eps_est == 1.12
    assert rows["LOSS"].timing == "amc" and rows["LOSS"].eps_est == -0.12
    assert rows["NOTIME"].timing == "unknown" and rows["NOTIME"].eps_est is None


def test_merge_prefers_finnhub_actuals_and_nasdaq_timing() -> None:
    from src.news.earnings import merge_earnings

    nd = [
        EarningsItem(
            symbol="BAC",
            report_date=date(2026, 10, 14),
            timing="bmo",
            eps_est=1.12,
            source="nasdaq",
        )
    ]
    fh = [
        EarningsItem(
            symbol="BAC",
            report_date=date(2026, 10, 14),
            timing="unknown",
            eps_est=1.10,
            eps_actual=1.20,
            rev_est=27e9,
            rev_actual=27.5e9,
            source="finnhub",
        )
    ]
    merged = {
        (m.symbol, m.report_date): m for m in merge_earnings(nd, fh, {"NVDA": date(2026, 11, 18)})
    }
    bac = merged[("BAC", date(2026, 10, 14))]
    assert (
        bac.timing == "bmo"
        and bac.eps_est == 1.12
        and bac.eps_actual == 1.20
        and bac.rev_actual == 27.5e9
    )
    assert ("NVDA", date(2026, 11, 18)) in merged


def test_upsert_reports_each_release_once(news_db) -> None:
    from src.news.earnings import upsert_earnings

    sched = EarningsItem(symbol="BAC", report_date=date(2026, 10, 14), timing="bmo", eps_est=1.12)
    assert upsert_earnings([sched], now=NOW) == []
    released = sched.model_copy(update={"eps_actual": 1.2})
    assert upsert_earnings([released], now=NOW) == [("BAC", date(2026, 10, 14))]
    assert upsert_earnings([released], now=NOW) == []
