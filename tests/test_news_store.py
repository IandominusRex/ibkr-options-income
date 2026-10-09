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
