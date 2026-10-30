"""scripts/value_feed.py: the plain data the value process hands to src/value/ (value book spec
§6.6, §7.1). ``scripts/run_value.py`` itself is never imported: it is compiled only."""

from __future__ import annotations

import py_compile
from datetime import UTC, date, datetime, timedelta

import src.common.value_inputs as vi
from scripts import value_feed
from src.common.value_types import MarketFacts, NewsVolume


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
    assert value_feed.recent_earnings(date(2026, 11, 2), {"MU"}) == {}
    assert value_feed.news_volume(["MU"]) == {}


def test_recent_report_dates_are_the_fortnight_up_to_the_session(news_db) -> None:
    from src.news.store.models import EarningsEventRow
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(EarningsEventRow(symbol="MU", report_date=date(2026, 10, 29)))
        s.add(EarningsEventRow(symbol="MU", report_date=date(2026, 12, 17)))  # still ahead
        s.add(EarningsEventRow(symbol="BAC", report_date=date(2026, 10, 14)))  # 19 days back
        s.add(EarningsEventRow(symbol="AMD", report_date=date(2026, 11, 2)))  # not a position
    assert value_feed.recent_earnings(date(2026, 11, 2), {"MU", "BAC"}) == {
        "MU": [date(2026, 10, 29)]
    }
    assert value_feed.recent_earnings(date(2026, 11, 2), set()) == {}


def test_news_volume_counts_the_last_day_against_the_monthly_daily_median(news_db) -> None:
    """Trigger 5's inputs: 6 items in the last 24 hours; over the 30 days before, one item on each
    of 20 days and none on 10: a daily median of 1."""
    from src.news.store.models import NewsItemRow
    from src.news.store.session import news_session

    now = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
    stamps = [now - timedelta(hours=h) for h in (1, 2, 3, 5, 8, 20)]
    stamps += [now - timedelta(days=d, hours=2) for d in range(1, 21)]
    stamps += [now - timedelta(days=40)]  # outside the window
    with news_session() as s:
        for i, ts in enumerate(stamps):
            s.add(
                NewsItemRow(
                    url_hash=f"u{i}",
                    title_hash=f"t{i}",
                    title=f"MU item {i}",
                    category="ticker",
                    origin="rss",
                    published_at=ts.replace(tzinfo=None),
                    fetched_at=ts.replace(tzinfo=None),
                    tickers=["MU"],
                    det_sentiment=0.1,
                )
            )
        s.add(
            NewsItemRow(
                url_hash="x",
                title_hash="x",
                title="no score",
                category="ticker",
                origin="rss",
                published_at=(now - timedelta(hours=1)).replace(tzinfo=None),
                fetched_at=(now - timedelta(hours=1)).replace(tzinfo=None),
                tickers=["MU"],
                det_sentiment=None,  # the sentiment rule reads scored items only
            )
        )
    assert value_feed.news_volume(["MU", "BAC"], now) == {
        "MU": NewsVolume(last_24h=6, daily_median_30d=1.0),
        "BAC": NewsVolume(last_24h=0, daily_median_30d=0.0),
    }


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_failed_night_is_retried_at_most_once_an_hour_per_session() -> None:
    """Review I2: a failure that repeats every night must not refetch ~1,000 names every poll."""
    clock = Clock()
    retry = value_feed.NightRetry(clock=clock, retry_seconds=3600.0, critical_after=3)
    d1, d2 = date(2026, 11, 2), date(2026, 11, 3)
    assert retry.ready(d1)  # nothing has failed yet
    assert retry.failed(d1) == 1
    clock.now += 600  # the next 10-minute poll
    assert not retry.ready(d1)
    clock.now += 3000  # 3,600 s since the failure
    assert retry.ready(d1)
    assert retry.failed(d1) == 2
    assert not retry.ready(d1)
    clock.now += 3600
    assert retry.failed(d1) == 3  # three failures for one session: the caller logs CRITICAL
    assert retry.ready(d2)  # a newer session starts fresh
    assert retry.failed(d2) == 1
    retry.succeeded()
    assert retry.ready(d2) and retry.failed(d2) == 1


def test_market_facts_are_fetched_once_per_session_across_retries() -> None:
    calls: list[list[str]] = []

    def fetch(names: list[str], workers: int) -> dict[str, MarketFacts]:
        calls.append(list(names))
        return {n: MarketFacts(market_cap=1e9) for n in names}

    cache = value_feed.FactsCache(fetch)
    d1, d2 = date(2026, 11, 2), date(2026, 11, 3)
    first = cache.get(d1, ["MU", "GOOGL"], 4)
    assert cache.get(d1, ["MU", "GOOGL"], 4) == first  # a retry does not refetch
    assert calls == [["MU", "GOOGL"]]
    cache.get(d1, ["MU", "NEW"], 4)  # only the name it lacks
    assert calls[-1] == ["NEW"]
    cache.get(d2, ["MU"], 4)  # a new session drops the old facts
    assert calls[-1] == ["MU"]


def test_a_name_whose_fetch_came_back_empty_is_fetched_again_on_the_retry() -> None:
    state = {"empty": True}

    def fetch(names: list[str], workers: int) -> dict[str, MarketFacts]:
        return {n: MarketFacts() if state["empty"] else MarketFacts(market_cap=1e9) for n in names}

    cache = value_feed.FactsCache(fetch)
    day = date(2026, 11, 2)
    assert cache.get(day, ["MU"], 1) == {"MU": MarketFacts()}
    state["empty"] = False
    assert cache.get(day, ["MU"], 1) == {"MU": MarketFacts(market_cap=1e9)}


def test_market_facts_are_fetched_per_name(monkeypatch) -> None:
    monkeypatch.setattr(vi, "fetch_market_facts", lambda s: MarketFacts(market_cap=len(s) * 1e9))
    assert value_feed.market_facts(["MU", "GOOGL"], 2) == {
        "MU": MarketFacts(market_cap=2e9),
        "GOOGL": MarketFacts(market_cap=5e9),
    }
