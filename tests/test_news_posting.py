# tests/test_news_posting.py
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

from src.common.config import get_config
from src.news.posting import post_card, update_post
from src.news.schemas import CardPayload

NOW = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)  # 01:00 SGT → quiet


class FakePub:
    def __init__(self):
        self.send = AsyncMock(return_value=101)
        self.edit = AsyncMock(return_value=True)
        self.send_photo = AsyncMock(return_value=102)


async def test_post_card_stores_payload_silences_and_attaches_chart(
    news_db, tmp_path, monkeypatch
) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    cfg = get_config()
    monkeypatch.setattr(cfg.news, "charts_dir", str(tmp_path / "charts"))
    pub = FakePub()
    p = CardPayload(
        kind="ticker_move", subject="PLTR", title="PLTR -9.0%", emoji="📉", when=NOW, critical=False
    )
    pid = await post_card(p, publisher=pub, cfg=cfg, now=NOW, chart=b"\x89PNG")
    assert pub.send.await_args.kwargs["silent"] is True
    assert pub.send_photo.await_args.kwargs["reply_to"] == 101
    with news_session() as s:
        row = s.get(NewsPostRow, pid)
    assert row.telegram_message_id == 101 and row.chart_message_id == 102 and row.silent is True
    assert row.payload["title"] == "PLTR -9.0%" and row.chart_path.endswith(f"{pid}.png")


async def test_critical_breaks_quiet_and_no_publisher_still_stores(news_db) -> None:
    cfg = get_config()
    pub = FakePub()
    p = CardPayload(kind="macro_print", title="CPI", emoji="🔴", when=NOW, critical=True)
    await post_card(p, publisher=pub, cfg=cfg, now=NOW)
    assert pub.send.await_args.kwargs["silent"] is False
    assert await post_card(p, publisher=None, cfg=cfg, now=NOW) > 0


async def test_update_post_edits_and_counts(news_db) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    cfg = get_config()
    pub = FakePub()
    p = CardPayload(kind="breaking", title="x", emoji="•", when=NOW, critical=True)
    pid = await post_card(p, publisher=pub, cfg=cfg, now=NOW)
    ok = await update_post(
        pid,
        p.model_copy(update={"updates": ["🔄 Update"]}),
        publisher=pub,
        stage="explained",
        llm_backend="cli",
    )
    assert ok
    with news_session() as s:
        row = s.get(NewsPostRow, pid)
    assert row.edits == 1 and row.stage == "explained" and row.llm_backend == "cli"
    assert pub.edit.await_args.args[0] == 101


async def test_update_reposts_when_message_gone(news_db) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    pub = FakePub()
    p = CardPayload(kind="breaking", title="x", emoji="•", when=NOW, critical=True)
    pid = await post_card(p, publisher=pub, cfg=get_config(), now=NOW)
    pub.edit = AsyncMock(return_value=False)
    pub.send = AsyncMock(return_value=555)
    assert await update_post(pid, p, publisher=pub)
    with news_session() as s:
        assert s.get(NewsPostRow, pid).telegram_message_id == 555


async def test_reply_threads_under_the_existing_card(news_db) -> None:
    pub = FakePub()
    p = CardPayload(kind="breaking", title="x", emoji="•", when=NOW, critical=True)
    await post_card(p, publisher=pub, cfg=get_config(), now=NOW, reply_to=77)
    assert pub.send.await_args.kwargs["reply_to"] == 77


async def test_update_never_reposts_on_a_transient_edit_failure(news_db) -> None:
    """Publisher.edit -> None means the edit never got through (network, 5xx): the card is
    probably still there, so a fresh copy would duplicate it."""
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    pub = FakePub()
    p = CardPayload(kind="breaking", title="x", emoji="•", when=NOW, critical=True)
    pid = await post_card(p, publisher=pub, cfg=get_config(), now=NOW)
    pub.edit = AsyncMock(return_value=None)
    pub.send = AsyncMock(return_value=555)
    p2 = p.model_copy(update={"title": "y"})
    assert await update_post(pid, p2, publisher=pub) is False
    pub.send.assert_not_awaited()
    with news_session() as s:
        row = s.get(NewsPostRow, pid)
        assert row.telegram_message_id == 101 and row.payload["title"] == "y"
