"""RobustBot: a transient Telegram failure is retried and long text is split, not cut."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from telegram.ext import ExtBot

from src.notify import robust_bot
from src.notify.robust_bot import RobustBot
from src.notify.splitting import LIMIT, _units

LONG = "\n".join(f"row {i:03d} " + "w" * 60 for i in range(200))  # ~14k characters


class _Wire:
    """Stands in for the network: records what ExtBot would have sent, fails on demand."""

    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = list(failures or [])
        self.sent: list[dict[str, Any]] = []
        self.edited: list[dict[str, Any]] = []
        self.sleeps: list[float] = []

    async def send_message(self, chat_id: Any, text: str, **kw: Any) -> Any:
        if self.failures:
            raise self.failures.pop(0)
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return SimpleNamespace(message_id=len(self.sent))

    async def edit_message_text(self, text: str, **kw: Any) -> Any:
        if self.failures:
            raise self.failures.pop(0)
        self.edited.append({"text": text, **kw})
        return SimpleNamespace(message_id=kw.get("message_id"))


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Wire:
    w = _Wire()
    monkeypatch.setattr(ExtBot, "send_message", lambda _bot, *a, **k: w.send_message(*a, **k))
    monkeypatch.setattr(
        ExtBot, "edit_message_text", lambda _bot, *a, **k: w.edit_message_text(*a, **k)
    )

    async def _sleep(seconds: float) -> None:
        w.sleeps.append(seconds)

    monkeypatch.setattr(robust_bot.asyncio, "sleep", _sleep)
    return w


def _bot() -> RobustBot:
    return RobustBot(token="123456:TEST")


async def test_a_timeout_is_retried_until_it_goes_through(wire: _Wire) -> None:
    wire.failures = [TimedOut(), NetworkError("reset")]
    msg = await _bot().send_message(chat_id=1, text="roll alert")
    assert msg.message_id == 1 and len(wire.sent) == 1
    assert len(wire.sleeps) == 2


async def test_it_gives_up_after_three_attempts(wire: _Wire) -> None:
    wire.failures = [TimedOut(), TimedOut(), TimedOut()]
    with pytest.raises(TimedOut):
        await _bot().send_message(chat_id=1, text="x")
    assert wire.sent == []


async def test_a_bad_request_is_never_retried(wire: _Wire) -> None:
    wire.failures = [BadRequest("Can't parse entities")]
    with pytest.raises(BadRequest):
        await _bot().send_message(chat_id=1, text="x")
    assert wire.sleeps == []


async def test_flood_control_waits_as_long_as_telegram_asks(wire: _Wire) -> None:
    wire.failures = [RetryAfter(7)]
    await _bot().send_message(chat_id=1, text="x")
    assert wire.sleeps == [8.0]


async def test_long_text_goes_out_in_pieces_with_buttons_on_the_last(wire: _Wire) -> None:
    msg = await _bot().send_message(
        chat_id=1,
        text=LONG,
        parse_mode="MarkdownV2",
        reply_markup="BUTTONS",
        message_thread_id=9,
        reply_to_message_id=5,
    )
    assert len(wire.sent) > 1
    assert all(_units(s["text"]) <= LIMIT for s in wire.sent)
    assert all(s["message_thread_id"] == 9 for s in wire.sent)
    assert [("reply_markup" in s) for s in wire.sent] == [False] * (len(wire.sent) - 1) + [True]
    assert "reply_to_message_id" in wire.sent[0] and "reply_to_message_id" not in wire.sent[1]
    assert msg.message_id == len(wire.sent)  # the last piece, the one carrying the buttons


async def test_html_text_is_left_to_its_caller(wire: _Wire) -> None:
    await _bot().send_message(chat_id=1, text=LONG, parse_mode="HTML")
    assert len(wire.sent) == 1


async def test_a_long_edit_rewrites_the_target_and_replies_with_the_rest(wire: _Wire) -> None:
    out = await _bot().edit_message_text(
        text=LONG, chat_id=1, message_id=77, parse_mode="MarkdownV2", reply_markup="KEEP"
    )
    assert out.message_id == 77
    assert len(wire.edited) == 1 and wire.edited[0]["reply_markup"] == "KEEP"
    assert _units(wire.edited[0]["text"]) <= LIMIT
    assert wire.sent  # the rest
    assert all(s["reply_parameters"].message_id == 77 for s in wire.sent)
    rebuilt = "\n".join([wire.edited[0]["text"], *(s["text"] for s in wire.sent)])
    assert rebuilt.count("row ") == 200  # nothing was cut
