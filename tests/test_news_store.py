from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import inspect


def test_schema_has_every_table(news_db) -> None:
    from src.news.store.session import get_news_engine

    names = set(inspect(get_news_engine()).get_table_names())
    assert {
        "news_items",
        "news_clusters",
        "econ_events",
        "earnings_events",
        "feed_state",
        "news_posts",
        "alert_state",
        "news_requests",
        "news_state",
        "ticker_aliases",
    } <= names


def test_news_base_is_not_the_trading_base() -> None:
    from src.news.store.models import NewsBase
    from src.storage.models import Base

    assert NewsBase.metadata is not Base.metadata
    assert "news_items" not in Base.metadata.tables


def test_state_round_trip_and_llm_counter(news_db) -> None:
    from src.news.store import state

    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    state.touch_heartbeat(now)
    assert state.get_state(state.HEARTBEAT_KEY) == now.isoformat()
    d = date(2026, 10, 9)
    assert state.llm_calls(d) == 0
    assert state.incr_llm_calls(d) == 1
    assert state.incr_llm_calls(d) == 2
    assert state.llm_calls(date(2026, 10, 10)) == 0


def test_readonly_session_yields_none_when_db_missing(tmp_path, monkeypatch) -> None:
    from src.news.store import readonly

    readonly.reset_engine()
    monkeypatch.setattr(readonly, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    with readonly.read_only_session() as s:
        assert s is None


def test_readonly_session_cannot_write(news_db) -> None:
    import pytest
    from sqlalchemy.exc import OperationalError

    from src.news.store import readonly
    from src.news.store.models import NewsStateRow

    with readonly.read_only_session() as s:
        assert s is not None
        s.add(NewsStateRow(key="x", value="y", updated_at=datetime(2026, 1, 1)))
        with pytest.raises(OperationalError):
            s.flush()


def test_clusters_since_finds_a_low_source_ticker_cluster_behind_busier_ones(news_db) -> None:
    """Final review: the symbol filter ran after a source_count-ordered LIMIT, so a ticker's own
    single-source story behind 20+ busier macro clusters was never found (cards said "no
    identifiable catalyst", briefs had no headlines)."""
    from datetime import UTC, datetime, timedelta

    from src.news.store.models import NewsClusterRow
    from src.news.store.queries import clusters_since, naive_utc
    from src.news.store.session import news_session

    now = datetime(2026, 10, 14, 15, tzinfo=UTC)
    with news_session() as s:
        for i in range(30):
            s.add(
                NewsClusterRow(
                    headline=f"macro story {i}",
                    category="macro",
                    first_seen=naive_utc(now - timedelta(hours=1)),
                    last_seen=naive_utc(now - timedelta(hours=1)),
                    source_domains=["a.com", "b.com", "c.com"],
                    source_count=3,
                    tickers=[],
                    tags=[],
                    title_tokens=[],
                )
            )
        s.add(
            NewsClusterRow(
                headline="Nvidia wins a contract",
                category="ticker",
                first_seen=naive_utc(now - timedelta(hours=2)),
                last_seen=naive_utc(now - timedelta(hours=2)),
                source_domains=["x.com"],
                source_count=1,
                tickers=["NVDA"],
                tags=[],
                title_tokens=[],
            )
        )
    with news_session() as s:
        got = clusters_since(s, now - timedelta(hours=24), symbol="nvda", limit=5)
    assert [c.headline for c in got] == ["Nvidia wins a contract"]
