from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)


def test_normalize_symbol() -> None:
    from src.news.briefs import InvalidSymbol, normalize_symbol

    assert normalize_symbol("$nvda") == "NVDA" and normalize_symbol("brk.b") == "BRK.B"
    for bad in ("", "123", "NVDA;DROP", "A" * 11, "nv da"):
        with pytest.raises(InvalidSymbol):
            normalize_symbol(bad)


def test_enqueue_dedupes_and_claims(news_db) -> None:
    from src.news.briefs import claim_next, enqueue_brief, finish

    a = enqueue_brief("nvda", "telegram", now=NOW)
    assert enqueue_brief("NVDA", "web", now=NOW + timedelta(minutes=1)) == a
    assert claim_next(NOW) == (a, "NVDA")
    assert claim_next(NOW) is None
    finish(a, now=NOW + timedelta(minutes=2), post_id=9)
    assert (
        enqueue_brief("NVDA", "web", now=NOW + timedelta(minutes=5)) == a
    )  # just finished → reuse
    assert enqueue_brief("NVDA", "web", now=NOW + timedelta(minutes=30)) != a


def test_enqueue_creates_schema_when_db_absent(tmp_path, monkeypatch) -> None:
    import src.news.store.session as rw
    from src.news.briefs import enqueue_brief

    monkeypatch.setattr(rw, "_engine", None)
    monkeypatch.setattr(rw, "_SessionLocal", None)
    monkeypatch.setattr(rw, "_resolve_url", lambda: f"sqlite:///{tmp_path / 'fresh.db'}")
    assert enqueue_brief("AAPL", "telegram", now=NOW) == 1


def test_latest_digest_link(news_db) -> None:
    from src.news.briefs import latest_digest_link
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    assert latest_digest_link("-1001234567890", "4409") is None
    with news_session() as s:
        s.add(
            NewsPostRow(
                kind="digest_close",
                telegram_message_id=77,
                posted_at=naive_utc(NOW),
                payload={},
                cluster_ids=[],
                silent=False,
                critical=False,
                edits=0,
                stage="explained",
            )
        )
    assert latest_digest_link("-1001234567890", "4409") == "https://t.me/c/1234567890/4409/77"


async def test_build_brief_posts_and_explains(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news import brief_builder as BB
    from src.news.schemas import CardPayload
    from src.news.service import NewsService

    svc = NewsService(get_config())
    svc.publisher = None
    monkeypatch.setattr(svc.collector, "collect_symbol", lambda sym, now: None)
    monkeypatch.setattr(svc, "_alert_ctx", lambda now, tape_now=None: None)
    monkeypatch.setattr(
        BB,
        "ticker_card",
        lambda c, ctx, kind: CardPayload(
            kind="brief", subject="TSM", title="TSM brief", emoji="📰", when=NOW
        ),
    )
    monkeypatch.setattr(BB, "ticker_chart", lambda *a, **k: None)
    explained = []

    async def fake_complete(pid, payload, **kw):
        explained.append(pid)
        return True

    monkeypatch.setattr(BB, "complete_post", fake_complete)
    pid = await BB.build_brief("TSM", svc=svc, now=NOW)
    assert explained == [pid]


def _svc(monkeypatch):
    from src.common.config import get_config
    from src.news.service import NewsService

    svc = NewsService(get_config(), clock=lambda: NOW)
    svc.publisher = None
    return svc


def _status(req_id: int) -> tuple[str, int | None, str | None]:
    from src.news.store.models import NewsRequestRow
    from src.news.store.session import news_session

    with news_session() as s:
        row = s.get(NewsRequestRow, req_id)
        assert row is not None
        return row.status, row.post_id, row.error


def test_service_runs_a_briefs_loop(news_db, monkeypatch) -> None:
    svc = _svc(monkeypatch)
    names = [n for n, _i, _f in svc.loops()]
    assert "briefs" in names
    interval = next(i for n, i, _f in svc.loops() if n == "briefs")
    assert interval == svc.ncfg.briefs.poll_seconds


async def test_briefs_loop_builds_each_claimed_request(news_db, monkeypatch) -> None:
    from src.news import brief_builder as BB
    from src.news.briefs import enqueue_brief

    svc = _svc(monkeypatch)
    a = enqueue_brief("NVDA", "telegram", now=NOW)
    b = enqueue_brief("AAPL", "web", now=NOW)
    built: list[str] = []

    async def fake_build(symbol, *, svc, now):
        built.append(symbol)
        return {"NVDA": 11, "AAPL": 12}[symbol]

    monkeypatch.setattr(BB, "build_brief", fake_build)
    await svc._briefs(NOW)
    assert built == ["NVDA", "AAPL"]  # one tick drains the whole queue, oldest first
    assert _status(a) == ("done", 11, None) and _status(b) == ("done", 12, None)


async def test_a_failing_brief_is_marked_failed_and_the_queue_continues(
    news_db, monkeypatch
) -> None:
    from src.news import brief_builder as BB
    from src.news.briefs import enqueue_brief

    svc = _svc(monkeypatch)
    a = enqueue_brief("NVDA", "telegram", now=NOW)
    b = enqueue_brief("AAPL", "telegram", now=NOW)

    async def fake_build(symbol, *, svc, now):
        if symbol == "NVDA":
            raise RuntimeError("yfinance down")
        return 7

    monkeypatch.setattr(BB, "build_brief", fake_build)
    await svc._briefs(NOW)
    assert _status(a) == ("failed", None, "yfinance down")
    assert _status(b) == ("done", 7, None)


async def test_start_requeues_briefs_a_crash_left_running(news_db) -> None:
    import asyncio

    from src.common.config import get_config
    from src.news.briefs import claim_next, enqueue_brief
    from src.news.service import NewsService

    a = enqueue_brief("NVDA", "telegram", now=NOW)
    assert claim_next(NOW) == (a, "NVDA") and _status(a)[0] == "running"
    svc = NewsService(get_config(), clock=lambda: NOW)
    svc.publisher = None
    stop = asyncio.Event()
    stop.set()
    await svc.run(stop)
    assert _status(a)[0] == "pending"
    assert claim_next(NOW) == (a, "NVDA")


def test_latest_digest_link_when_db_absent(tmp_path, monkeypatch) -> None:
    """`/news` before the news service ever ran: no schema yet must read as "no digest", not raise."""
    import src.news.store.session as rw
    from src.news.briefs import latest_digest_link

    monkeypatch.setattr(rw, "_engine", None)
    monkeypatch.setattr(rw, "_SessionLocal", None)
    monkeypatch.setattr(rw, "_resolve_url", lambda: f"sqlite:///{tmp_path / 'fresh.db'}")
    assert latest_digest_link("-1001234567890", "4409") is None


async def test_brief_whose_explanation_fails_is_done_not_failed(news_db, monkeypatch) -> None:
    """complete_post raising after the card posted must not mark the request failed: a retry
    would post a second card. The post is left at the deterministic stage as a fallback."""
    from src.common.config import get_config
    from src.news import brief_builder as BB
    from src.news.briefs import claim_next, enqueue_brief
    from src.news.schemas import CardPayload
    from src.news.service import NewsService
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    svc = NewsService(get_config(), clock=lambda: NOW)
    svc.publisher = None
    monkeypatch.setattr(svc.collector, "collect_symbol", lambda sym, now: None)
    monkeypatch.setattr(svc, "_alert_ctx", lambda now, tape_now=None: None)
    monkeypatch.setattr(
        BB,
        "ticker_card",
        lambda c, ctx, kind: CardPayload(
            kind="brief", subject="TSM", title="TSM brief", emoji="📰", when=NOW
        ),
    )
    monkeypatch.setattr(BB, "ticker_chart", lambda *a, **k: None)

    async def boom(*a, **k):
        raise RuntimeError("llm exploded")

    monkeypatch.setattr(BB, "complete_post", boom)
    rid = enqueue_brief("TSM", "telegram", now=NOW)
    await svc._briefs(NOW)
    assert claim_next(NOW) is None
    status, post_id, error = _status(rid)
    assert status == "done" and post_id is not None and error is None
    with news_session() as s:
        posts = list(s.query(NewsPostRow))
    assert len(posts) == 1 and posts[0].stage == "fallback"


def test_service_note_reports_a_missing_stale_or_disabled_service(news_db, monkeypatch) -> None:
    from datetime import timedelta

    from src.common.config import get_config
    from src.news import briefs
    from src.news.store.state import touch_heartbeat

    assert "not running" in (briefs.service_note(NOW) or "")  # never beat
    touch_heartbeat(NOW - timedelta(hours=2))
    assert "not running" in (briefs.service_note(NOW) or "")  # stale
    touch_heartbeat(NOW - timedelta(minutes=1))
    assert briefs.service_note(NOW) is None  # alive
    cfg = get_config()
    off = cfg.model_copy(update={"news": cfg.news.model_copy(update={"enabled": False})})
    monkeypatch.setattr(briefs, "get_config", lambda: off)
    assert "disabled" in (briefs.service_note(NOW) or "")
