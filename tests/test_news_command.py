from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture()
def upd(monkeypatch):
    import src.notify.approval_service as svc

    monkeypatch.setattr(svc, "_is_authorized", lambda u: True)
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(message=msg, effective_chat=SimpleNamespace(id=-1001234567890))


async def test_news_ticker_enqueues_and_replies(upd, monkeypatch) -> None:
    import src.notify.approval_service as svc

    seen = {}
    monkeypatch.setattr("src.news.briefs.service_note", lambda: None)
    monkeypatch.setattr(
        "src.news.briefs.enqueue_brief",
        lambda sym, origin: seen.update(sym=sym, origin=origin) or 5,
    )
    await svc.handle_news_command(upd, SimpleNamespace(args=["nvda"]))
    assert seen == {"sym": "nvda", "origin": "telegram"}
    reply = upd.message.reply_text.await_args.args[0]
    assert "NVDA" in reply and "News thread" in reply


async def test_news_ticker_says_so_when_the_news_service_is_down(upd, monkeypatch) -> None:
    import src.notify.approval_service as svc

    monkeypatch.setattr("src.news.briefs.enqueue_brief", lambda sym, origin: 5)
    monkeypatch.setattr("src.news.briefs.service_note", lambda: "The news service is not running.")
    await svc.handle_news_command(upd, SimpleNamespace(args=["nvda"]))
    reply = upd.message.reply_text.await_args.args[0]
    assert "Queued NVDA" in reply and "not running" in reply and "Building" not in reply


async def test_news_rejects_garbage(upd) -> None:
    import src.notify.approval_service as svc

    await svc.handle_news_command(upd, SimpleNamespace(args=["DROP;TABLE"]))
    assert "not a ticker" in upd.message.reply_text.await_args.args[0].lower()


async def test_news_without_args_links_latest_digest(upd, monkeypatch) -> None:
    import src.notify.approval_service as svc

    monkeypatch.setattr(
        "src.news.briefs.latest_digest_link", lambda chat, thread: "https://t.me/c/1/4409/77"
    )
    await svc.handle_news_command(upd, SimpleNamespace(args=[]))
    text = upd.message.reply_text.await_args.args[0]
    assert "https://t.me/c/1/4409/77" in text and "/news TICKER" in text


def test_help_lists_news() -> None:
    from src.notify.formatters import format_help

    assert "/news TICKER" in format_help()
