"""scripts/value_feed.py: the plain data the value process hands to src/value/ (value book spec
§6.6). ``scripts/run_value.py`` itself is never imported: it is compiled only."""

from __future__ import annotations

import py_compile
from datetime import date

import src.common.value_inputs as vi
from scripts import value_feed
from src.common.value_types import MarketFacts


def test_the_entrypoint_compiles() -> None:
    py_compile.compile("scripts/run_value.py", doraise=True)
    py_compile.compile("scripts/value_feed.py", doraise=True)


def test_earnings_come_from_news_db_earliest_first(news_db) -> None:
    from src.news.store.models import EarningsEventRow
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(EarningsEventRow(symbol="MU", report_date=date(2026, 12, 17)))
        s.add(EarningsEventRow(symbol="MU", report_date=date(2027, 3, 20)))
        s.add(EarningsEventRow(symbol="BAC", report_date=date(2026, 10, 14)))  # already past
        s.add(EarningsEventRow(symbol="FAR", report_date=date(2027, 8, 1)))  # beyond 180 days
    assert value_feed.earnings_dates(date(2026, 11, 2)) == {"MU": date(2026, 12, 17)}


def test_an_unreadable_news_db_means_no_dates_not_a_crash() -> None:
    assert value_feed.earnings_dates(date(2026, 11, 2)) == {}  # conftest points at no file


def test_market_facts_are_fetched_per_name(monkeypatch) -> None:
    monkeypatch.setattr(vi, "fetch_market_facts", lambda s: MarketFacts(market_cap=len(s) * 1e9))
    assert value_feed.market_facts(["MU", "GOOGL"], 2) == {
        "MU": MarketFacts(market_cap=2e9),
        "GOOGL": MarketFacts(market_cap=5e9),
    }
