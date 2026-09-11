"""Warm-tier refreshes: quotes, nightly bars, and nightly news."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.research.ingest.quotes import (
    refresh_quotes,
    refresh_warm_bars,
    refresh_warm_news,
    refresh_warm_tier,
    warm_symbols,
)
from src.research.store.models import (
    DailyBarRow,
    NewsItemRow,
    QuoteRow,
    RecentlyViewedRow,
    WatchlistItemRow,
    WatchlistRow,
)
from src.research.store.session import init_research_db, research_session


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


def test_warm_set_is_empty_by_default(db) -> None:
    assert warm_symbols() == []


def test_watchlisted_symbols_are_warm(db) -> None:
    with research_session() as s:
        s.add(WatchlistRow(id=1, user_id="owner", name="Default"))
        s.flush()  # parent must land before the FK child (no relationship() declared)
        s.add(WatchlistItemRow(watchlist_id=1, symbol="NVDA", added_at=datetime.now(UTC)))
    assert warm_symbols() == ["NVDA"]


def test_recently_viewed_symbols_are_warm(db) -> None:
    with research_session() as s:
        s.add(RecentlyViewedRow(user_id="owner", symbol="META", viewed_at=datetime.now(UTC)))
    assert warm_symbols() == ["META"]


def test_stale_views_fall_out_of_the_warm_set(db) -> None:
    with research_session() as s:
        s.add(
            RecentlyViewedRow(
                user_id="owner",
                symbol="OLD",
                viewed_at=datetime.now(UTC) - timedelta(days=30),
            )
        )
    assert warm_symbols() == []


def test_refresh_writes_a_quote(db, monkeypatch) -> None:
    with research_session() as s:
        s.add(RecentlyViewedRow(user_id="owner", symbol="AAPL", viewed_at=datetime.now(UTC)))
    monkeypatch.setattr("src.research.ingest.quotes.is_rth", lambda: True)
    monkeypatch.setattr(
        "src.research.ingest.quotes.get_price_provider",
        lambda: type("P", (), {"get_last_price": staticmethod(lambda sym: 221.4)})(),
    )
    assert refresh_quotes() == 1
    with research_session() as s:
        assert s.get(QuoteRow, "AAPL").price == 221.4


def test_a_missing_quote_does_not_write_a_row(db, monkeypatch) -> None:
    """No quote is not the same as a price of zero."""
    with research_session() as s:
        s.add(RecentlyViewedRow(user_id="owner", symbol="AAPL", viewed_at=datetime.now(UTC)))
    monkeypatch.setattr("src.research.ingest.quotes.is_rth", lambda: True)
    monkeypatch.setattr(
        "src.research.ingest.quotes.get_price_provider",
        lambda: type("P", (), {"get_last_price": staticmethod(lambda sym: None)})(),
    )
    assert refresh_quotes() == 0
    with research_session() as s:
        assert s.get(QuoteRow, "AAPL") is None


def test_refresh_is_a_noop_outside_rth(db, monkeypatch) -> None:
    """The RTH guard means a manual call outside market hours writes nothing."""
    with research_session() as s:
        s.add(RecentlyViewedRow(user_id="owner", symbol="AAPL", viewed_at=datetime.now(UTC)))
    monkeypatch.setattr("src.research.ingest.quotes.is_rth", lambda: False)
    monkeypatch.setattr(
        "src.research.ingest.quotes.get_price_provider",
        lambda: type("P", (), {"get_last_price": staticmethod(lambda sym: 221.4)})(),
    )
    assert refresh_quotes() == 0


# --- Nightly warm-tier refresh (bars + news) ---


def _seed_warm(symbols: list[str]) -> None:
    with research_session() as s:
        s.add(WatchlistRow(id=1, user_id="owner", name="Default"))
        s.flush()
        for sym in symbols:
            s.add(RecentlyViewedRow(user_id="owner", symbol=sym, viewed_at=datetime.now(UTC)))


def test_refresh_warm_bars_ingests_every_warm_symbol(db, monkeypatch) -> None:
    _seed_warm(["AAPL", "NVDA"])
    monkeypatch.setattr(
        "src.research.ingest.quotes.ingest_daily_bars",
        lambda sym: {"AAPL": 250, "NVDA": 300}[sym],
    )
    assert refresh_warm_bars() == 550


def test_refresh_warm_bars_isolates_a_failing_symbol(db, monkeypatch) -> None:
    """One symbol's outage must not stop the rest of the nightly pass."""
    _seed_warm(["BAD", "OK"])

    def fake_ingest(symbol: str) -> int:
        if symbol == "BAD":
            raise RuntimeError("provider down")
        return 10

    monkeypatch.setattr("src.research.ingest.quotes.ingest_daily_bars", fake_ingest)
    assert refresh_warm_bars() == 10


def test_refresh_warm_news_ingests_every_warm_symbol(db, monkeypatch) -> None:
    _seed_warm(["AAPL"])
    monkeypatch.setattr("src.research.ingest.quotes.ingest_news", lambda sym, **_: 3)
    assert refresh_warm_news() == 3


def test_refresh_warm_news_isolates_a_failing_symbol(db, monkeypatch) -> None:
    _seed_warm(["BAD", "OK"])

    def fake_ingest(symbol: str, **_: object) -> int:
        if symbol == "BAD":
            raise RuntimeError("provider down")
        return 2

    monkeypatch.setattr("src.research.ingest.quotes.ingest_news", fake_ingest)
    assert refresh_warm_news() == 2


def test_refresh_warm_tier_runs_both_parts_and_never_raises(db, monkeypatch) -> None:
    _seed_warm(["AAPL"])
    monkeypatch.setattr("src.research.ingest.quotes.ingest_daily_bars", lambda sym: 5)
    monkeypatch.setattr("src.research.ingest.quotes.ingest_news", lambda sym, **_: 2)
    out = refresh_warm_tier()
    assert out == {"symbols": 1, "bars": 5, "news": 2}


def test_refresh_warm_tier_survives_a_total_part_failure(db, monkeypatch) -> None:
    """Even a part that raises for every symbol must not take the job down."""
    _seed_warm(["AAPL"])

    def boom(symbol: str) -> int:
        raise RuntimeError("provider down")

    monkeypatch.setattr("src.research.ingest.quotes.ingest_daily_bars", boom)
    monkeypatch.setattr("src.research.ingest.quotes.ingest_news", boom)
    out = refresh_warm_tier()
    assert out == {"symbols": 1, "bars": 0, "news": 0}


def test_refresh_warm_bars_writes_real_rows(db, monkeypatch) -> None:
    """Integration: the nightly job populates daily_bars end to end (the gap this closes)."""
    import pandas as pd

    _seed_warm(["AAPL"])
    idx = pd.DatetimeIndex(["2026-09-07", "2026-09-08"], name="Date")
    frame = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Volume": [1000.0, 1100.0],
        },
        index=idx,
    )
    monkeypatch.setattr(
        "src.research.ingest.prices.get_bulk_price_provider",
        lambda: type("P", (), {"get_daily_bars": staticmethod(lambda sym: frame)})(),
    )
    assert refresh_warm_bars() == 2
    with research_session() as s:
        rows = s.query(DailyBarRow).filter_by(symbol="AAPL").all()
        assert len(rows) == 2
        assert rows[0].close == 101.0


def test_refresh_warm_news_writes_real_rows(db, monkeypatch) -> None:
    """Integration: the nightly job populates news_items end to end."""
    _seed_warm(["AAPL"])
    monkeypatch.setattr(
        "src.research.ingest.news.get_news_provider",
        lambda: type(
            "N",
            (),
            {
                "get_headlines": staticmethod(
                    lambda sym, limit=25: [
                        {"title": "Apple beats estimates", "link": "https://x.test/1"}
                    ]
                )
            },
        )(),
    )
    assert refresh_warm_news() == 1
    with research_session() as s:
        rows = s.query(NewsItemRow).filter_by(symbol="AAPL").all()
        assert len(rows) == 1
        assert rows[0].title == "Apple beats estimates"


def test_scheduler_registers_the_nightly_warm_refresh() -> None:
    """The nightly warm-tier job exists and honours warm_refresh_hour_et (regression:
    the job was promised in the P0-P1 design but never registered, leaving
    daily_bars empty for every symbol except the manually seeded AAPL)."""
    from src.research.ingest.jobs import build_scheduler

    sched = build_scheduler()
    try:
        job_ids = {job.id for job in sched.get_jobs()}
        assert "warm_refresh" in job_ids
        assert "refresh_quotes" in job_ids
        assert "drain_ingest_jobs" in job_ids
        assert "symbol_directory" in job_ids
        trigger = next(j for j in sched.get_jobs() if j.id == "warm_refresh").trigger
        assert "hour='4'" in str(trigger)  # warm_refresh_hour_et default
    finally:
        if sched.running:
            sched.shutdown(wait=False)


def test_scheduler_honours_a_custom_warm_refresh_hour(monkeypatch) -> None:
    from src.common.config import get_config
    from src.research.ingest.jobs import build_scheduler

    monkeypatch.setattr(get_config().research.tiers, "warm_refresh_hour_et", 2, raising=False)
    sched = build_scheduler()
    try:
        trigger = next(j for j in sched.get_jobs() if j.id == "warm_refresh").trigger
        assert "hour='2'" in str(trigger)
    finally:
        if sched.running:
            sched.shutdown(wait=False)


def test_a_job_discovered_days_late_still_runs_instead_of_misfiring(db) -> None:
    """Regression: 2026-09-08 to 2026-09-11 the worker sat frozen through a macOS sleep and
    never resumed on its own. APScheduler's own default (misfire_grace_time=1s) silently
    drops any run discovered more than a second late instead of executing it — after a
    multi-day sleep every job is always "late", so nothing ever ran again until a human
    noticed and restarted the process by hand. build_scheduler() sets
    misfire_grace_time=None precisely so a job found days overdue still executes the moment
    the process next gets CPU time, rather than being dropped forever."""
    from apscheduler.events import EVENT_JOB_MISSED
    from apscheduler.executors.base import run_job as execute_due_job

    from src.research.ingest.jobs import build_scheduler, read_heartbeat

    assert read_heartbeat() is None  # nothing has run yet in this temp DB

    sched = build_scheduler()
    try:
        # misfire_grace_time from job_defaults is only merged onto a job once the scheduler
        # actually adds it to a jobstore, which happens on start() — an unstarted scheduler's
        # pending job hasn't resolved the attribute yet.
        sched.start()
        job = next(j for j in sched.get_jobs() if j.id == "drain_ingest_jobs")
        assert job.misfire_grace_time is None
        three_days_overdue = datetime.now(UTC) - timedelta(days=3)
        events = execute_due_job(
            job, job._jobstore_alias, [three_days_overdue], "apscheduler.executors.default"
        )
        assert not any(e.code == EVENT_JOB_MISSED for e in events)
        assert read_heartbeat() is not None  # the job's func actually ran, not just skipped
    finally:
        if sched.running:
            sched.shutdown(wait=False)
