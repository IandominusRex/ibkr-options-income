from __future__ import annotations

from datetime import UTC, date, datetime

from src.data.protocols import EconActualItem, EconScheduleItem, FeedFetch, NewsItem


class FakeFeeds:
    def fetch(self, url, *, etag=None, last_modified=None, limit=50):
        if etag == "e1":
            return FeedFetch(items=[], etag="e1", not_modified=True)
        return FeedFetch(
            items=[NewsItem(title="Fed holds rates steady", url="https://fed.gov/a")], etag="e1"
        )


class FakeSearch:
    def search(self, query, *, days=7, limit=10):
        return [NewsItem(title=f"{query} headline", url=f"https://g.com/{abs(hash(query))}")]


def _patch(monkeypatch, *, schedule=(), actuals=()):
    import src.news.collectors as c

    monkeypatch.setattr(c, "get_feed_provider", lambda: FakeFeeds())
    monkeypatch.setattr(c, "get_news_search_provider", lambda: FakeSearch())
    monkeypatch.setattr(
        c,
        "get_news_provider",
        lambda: type("Y", (), {"get_headlines": lambda self, s, limit=50: []})(),
    )
    monkeypatch.setattr(c, "get_finnhub_client", lambda: None)
    monkeypatch.setattr(c, "watch_symbols", lambda: ["NVDA", "AAPL"])
    monkeypatch.setattr(c, "load_aliases", lambda symbols, overrides, now: {"NVDA": ["Nvidia"]})
    monkeypatch.setattr(
        c,
        "get_econ_schedule_provider",
        lambda: type("S", (), {"this_week": lambda self: list(schedule)})(),
    )
    monkeypatch.setattr(
        c,
        "get_econ_actuals_provider",
        lambda: type("A", (), {"actuals": lambda self, d: list(actuals)})(),
    )


NOW = datetime(2026, 10, 8, 12, 31, tzinfo=UTC)  # 08:31 ET


def test_rss_uses_conditional_get_state(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news.collectors import Collector

    _patch(monkeypatch)
    col = Collector(get_config().news)
    assert col.collect_rss(NOW) >= 1
    assert col.collect_rss(NOW) == 0  # second poll sends the stored ETag and gets 304


def test_ticker_batch_round_robins(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news.collectors import Collector

    _patch(monkeypatch)
    col = Collector(get_config().news)
    col.collect_ticker_batch(NOW, batch=1)
    col.collect_ticker_batch(NOW, batch=1)
    from src.news.store.models import NewsItemRow
    from src.news.store.session import news_session

    with news_session() as s:
        titles = {r.title for r in s.query(NewsItemRow)}
    assert {"NVDA headline", "AAPL headline"} <= titles


def test_econ_schedule_then_actual_matched_by_playbook_and_time(news_db, monkeypatch) -> None:
    from zoneinfo import ZoneInfo

    from src.common.config import get_config
    from src.news.collectors import Collector

    et = ZoneInfo("America/New_York")
    sched = [
        EconScheduleItem(
            title="Unemployment Claims",
            country="USD",
            scheduled_at=datetime(2026, 10, 8, 8, 30, tzinfo=et),
            impact="Medium",
            forecast="210K",
            previous="197K",
        ),
        EconScheduleItem(
            title="German IP",
            country="EUR",
            scheduled_at=datetime(2026, 10, 8, 2, 0, tzinfo=et),
            impact="High",
        ),
    ]
    acts = [
        EconActualItem(
            title="Initial Jobless Claims",
            et_day=date(2026, 10, 8),
            et_time="08:30",
            actual="197K",
            consensus="200K",
            previous="199K",
        ),
        EconActualItem(
            title="Continuing Jobless Claims",
            et_day=date(2026, 10, 8),
            et_time="08:30",
            actual="1,716K",
        ),
    ]
    _patch(monkeypatch, schedule=sched, actuals=acts)
    col = Collector(get_config().news)
    assert col.refresh_econ_schedule(NOW) == 1  # USD only
    released = col.refresh_econ_actuals(NOW)
    assert len(released) == 1
    from src.news.store.models import EconEventRow
    from src.news.store.session import news_session

    with news_session() as s:
        row = s.query(EconEventRow).one()
    # 13K fewer claims than forecast clears the playbook's 8K tolerance; inverse key, so "hot"
    assert (
        row.actual == "197K" and row.playbook_key == "jobless_claims" and row.surprise_dir == "hot"
    )
    assert col.refresh_econ_actuals(NOW) == []  # reported once


def test_fast_window(news_db, monkeypatch) -> None:
    from zoneinfo import ZoneInfo

    from src.common.config import get_config
    from src.news.collectors import Collector

    et = ZoneInfo("America/New_York")
    _patch(
        monkeypatch,
        schedule=[
            EconScheduleItem(
                title="CPI m/m",
                country="USD",
                scheduled_at=datetime(2026, 10, 8, 8, 30, tzinfo=et),
                impact="High",
                forecast="0.3%",
            )
        ],
    )
    col = Collector(get_config().news)
    col.refresh_econ_schedule(NOW)
    assert col.in_fast_econ_window(datetime(2026, 10, 8, 12, 29, tzinfo=UTC))
    assert not col.in_fast_econ_window(datetime(2026, 10, 8, 13, 0, tzinfo=UTC))


def test_clean_company_name() -> None:
    from src.news.aliases import clean_company_name

    assert clean_company_name("NVIDIA Corporation") == "NVIDIA"
    assert clean_company_name("Alphabet Inc. Class A") == "Alphabet"
    assert clean_company_name("ProShares UltraPro QQQ") is None  # fund names are not useful aliases
