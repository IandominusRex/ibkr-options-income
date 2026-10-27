"""Research touches: a /scan or a review of a name makes its dossier (and the picture) due early."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.news import briefs, picture, touches
from src.news import dossier as D
from src.news.store.models import DossierTouchRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from tests.test_dossier_build import (
    HOUR,
    NOW,
    FakeLlm,
    due,
    names_answer,
    one_name,
    seed,
    symbols,
)

__all__ = ["FakeLlm"]


def open_touches(symbol: str) -> list[DossierTouchRow]:
    with news_session() as s:
        rows = s.query(DossierTouchRow).filter(DossierTouchRow.symbol == symbol).all()
        s.expunge_all()
    return rows


def test_a_touch_after_the_last_prose_makes_the_name_due(news_db) -> None:
    seed("META", prose_ago=timedelta(hours=4))  # inside prose_min_interval_hours (6h): "waiting"
    assert due("META") == []
    briefs.note_researched("meta", "scan", now=NOW - HOUR)
    assert due("META") == ["researched"]


def test_a_touch_waits_out_researched_min_interval(news_db) -> None:
    seed("META", prose_ago=timedelta(hours=2))  # 120 min < the 180 min default
    briefs.note_researched("META", "scan", now=NOW - timedelta(minutes=5))
    assert due("META") == []


def test_a_touch_older_than_the_prose_is_not_news(news_db) -> None:
    seed("META", prose_ago=timedelta(hours=4))
    briefs.note_researched("META", "scan", now=NOW - timedelta(hours=5))
    assert due("META") == []


def test_one_open_touch_per_name_and_a_repeat_only_moves_its_time(news_db) -> None:
    briefs.note_researched("META", "scan", now=NOW - timedelta(hours=3))
    briefs.note_researched("META", "review", now=NOW - HOUR)
    rows = open_touches("META")
    assert len(rows) == 1 and rows[0].touched_at == naive_utc(NOW - HOUR)


def test_touch_enabled_false_ignores_every_touch(news_db, monkeypatch) -> None:
    from src.common.config import get_config

    monkeypatch.setattr(get_config().news.dossier, "touch_enabled", False)
    seed("META", prose_ago=timedelta(hours=4))
    briefs.note_researched("META", "scan", now=NOW - HOUR)
    assert open_touches("META") == [] and due("META") == []


def test_note_researched_never_raises(monkeypatch) -> None:
    def boom() -> None:
        raise RuntimeError("news.db is locked")

    monkeypatch.setattr(briefs, "init_news_db", boom)
    briefs.note_researched("META", "scan")  # no exception


def test_researched_names_come_after_held_and_before_the_rest(monkeypatch) -> None:
    monkeypatch.setattr(D, "held_underlyings", lambda: {"ZZZ"})
    items = [
        ("AAA", ["new", "profile"]),
        ("BBB", ["researched"]),
        ("ZZZ", ["news"]),
        ("CCC", ["news"]),
    ]
    assert [n for n, _ in D.order_due(items)] == ["ZZZ", "BBB", "AAA", "CCC"]


def test_a_rebuild_replaces_the_old_story_and_closes_the_touch(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META", prose_ago=timedelta(hours=4))
    briefs.note_researched("META", "scan", now=NOW - HOUR)
    fake.answer = names_answer(one_name("META"))  # the model has nothing grounded to say

    assert D.build_dossier_prose(NOW) == 1
    with news_session() as s:
        from src.news.store import queries

        got = queries.latest_dossier(s, "META")
    assert got is not None and "OLDSTORY" not in got.story  # last week's story is not kept
    assert all(t.consumed_at is not None for t in open_touches("META"))
    assert due("META") == []  # consumed: not due again


def test_headlines_are_pulled_once_per_touch(news_db) -> None:
    briefs.note_researched("META", "scan", now=NOW - HOUR)
    briefs.note_researched(None, "scan", now=NOW - HOUR)  # the market has no headlines to pull
    assert touches.due_for_collection(NOW) == ["META"]
    touches.mark_collected("META", NOW)
    assert touches.due_for_collection(NOW) == []
    briefs.note_researched("META", "scan", now=NOW + timedelta(minutes=2))
    assert touches.due_for_collection(NOW + timedelta(minutes=3)) == []  # too soon to pull again
    briefs.note_researched("META", "scan", now=NOW + timedelta(minutes=30))
    assert touches.due_for_collection(NOW + timedelta(minutes=31)) == ["META"]


def test_old_touches_are_pruned(news_db) -> None:
    briefs.note_researched("OLDX", "scan", now=NOW - timedelta(days=5))
    briefs.note_researched("NEWX", "scan", now=NOW - HOUR)
    touches.prune_touches(NOW)
    assert open_touches("OLDX") == [] and len(open_touches("NEWX")) == 1


def test_a_market_touch_rebuilds_an_old_picture_but_not_a_fresh_one(news_db, monkeypatch) -> None:
    from src.news.store.models import MarketPictureRow

    with news_session() as s:
        s.add(
            MarketPictureRow(
                built_at=naive_utc(NOW - timedelta(minutes=30)),
                version="v1",
                payload={},
                stale=False,
            )
        )
    briefs.note_researched(None, "scan", now=NOW - timedelta(minutes=5))
    assert picture.picture_due(NOW) is False  # 30 min old, under touch_min_age_min (90)
    assert picture.picture_due(NOW + timedelta(minutes=70)) is True  # 100 min old

    with news_session() as s:
        touches.consume(s, [touches.MARKET], NOW + timedelta(minutes=70))
    assert picture.picture_due(NOW + timedelta(minutes=70)) is False


@pytest.fixture()
def fake(monkeypatch) -> FakeLlm:
    f = FakeLlm()
    monkeypatch.setattr("src.news.explain.call_llm", f)
    monkeypatch.setattr(D, "latest_picture_text", lambda now: None)
    monkeypatch.setattr(D, "held_underlyings", lambda: set())
    return f
