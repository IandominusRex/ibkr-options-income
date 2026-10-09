from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, NetworkError

from src.common.config import NewsQuietCfg
from src.news import quiet
from src.news.publish import Publisher

Q = NewsQuietCfg()


@pytest.mark.parametrize(
    "utc, expected",
    [
        (datetime(2026, 10, 30, 15, 59, tzinfo=UTC), False),  # 23:59 SGT, before US DST end
        (datetime(2026, 10, 30, 16, 1, tzinfo=UTC), True),  # 00:01 SGT
        (datetime(2026, 11, 2, 22, 59, tzinfo=UTC), True),  # 06:59 SGT, after US DST end
        (datetime(2026, 11, 2, 23, 1, tzinfo=UTC), False),  # 07:01 SGT
    ],
)
def test_quiet_hours_across_us_dst_end(utc, expected) -> None:
    assert quiet.is_quiet(utc, Q) is expected


def test_window_crossing_midnight_and_critical() -> None:
    cfg = NewsQuietCfg(start="22:00", end="06:00")
    assert quiet.is_quiet(datetime(2026, 10, 9, 15, 0, tzinfo=UTC), cfg)  # 23:00 SGT
    assert not quiet.silent_for(datetime(2026, 10, 9, 15, 0, tzinfo=UTC), critical=True, cfg=cfg)
    assert quiet.silent_for(datetime(2026, 10, 9, 15, 0, tzinfo=UTC), critical=False, cfg=cfg)


async def test_send_splits_and_previews_first_chunk_only() -> None:
    bot = SimpleNamespace(
        send_message=AsyncMock(
            side_effect=[SimpleNamespace(message_id=11), SimpleNamespace(message_id=12)]
        )
    )
    pub = Publisher(bot, "-100", 4409)
    mid = await pub.send(
        "A" * 3000 + "\n\n" + "B" * 3000,
        silent=True,
        preview_url="https://img/x.png",
        show_above=True,
    )
    assert mid == 11
    first, second = bot.send_message.await_args_list
    assert (
        first.kwargs["message_thread_id"] == 4409 and first.kwargs["disable_notification"] is True
    )
    assert first.kwargs["link_preview_options"].url == "https://img/x.png"
    assert second.kwargs["link_preview_options"].is_disabled is True


async def test_retry_then_give_up_and_edit_gone() -> None:
    bot = SimpleNamespace(
        send_message=AsyncMock(side_effect=[NetworkError("x"), SimpleNamespace(message_id=5)]),
        edit_message_text=AsyncMock(side_effect=BadRequest("Message to edit not found")),
    )
    pub = Publisher(bot, "-100", None, backoff=(0, 0, 0))
    assert await pub.send("hi") == 5
    assert await pub.edit(5, "x") is False


async def test_edit_not_modified_is_success() -> None:
    bot = SimpleNamespace(
        edit_message_text=AsyncMock(side_effect=BadRequest("Message is not modified"))
    )
    assert await Publisher(bot, "-100", None, backoff=(0,)).edit(5, "x") is True


def _cfg(token: str = "t", chat: str = "-100", thread: str = "4409") -> SimpleNamespace:
    return SimpleNamespace(
        secrets=SimpleNamespace(
            telegram_bot_token=token, telegram_chat_id=chat, telegram_thread_news=thread
        )
    )


def test_from_config_unset_secrets_means_no_publisher() -> None:
    assert Publisher.from_config(_cfg(token="")) is None  # type: ignore[arg-type]
    assert Publisher.from_config(_cfg(chat="")) is None  # type: ignore[arg-type]


def test_from_config_uses_the_faked_bot_never_a_real_one() -> None:
    # conftest's autouse guard replaces src.news.publish.Bot; a real Bot here would hold the
    # operator's live token from .env.
    import src.news.publish as publish_mod

    pub = Publisher.from_config(_cfg())  # type: ignore[arg-type]
    assert pub is not None and pub.thread_id == 4409 and pub.chat_id == "-100"
    assert pub.bot is publish_mod.Bot.return_value
    assert Publisher.from_config(_cfg(thread="")).thread_id is None  # type: ignore[arg-type, union-attr]


async def test_send_photo_replies_in_thread_and_swallows_rejection() -> None:
    bot = SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(message_id=9)))
    pub = Publisher(bot, "-100", 4409)
    assert await pub.send_photo(b"\x89PNG", reply_to=11, silent=True, caption="c") == 9
    kw = bot.send_photo.await_args.kwargs
    assert kw["message_thread_id"] == 4409 and kw["disable_notification"] is True
    assert kw["reply_parameters"].message_id == 11

    bot.send_photo = AsyncMock(side_effect=BadRequest("wrong file"))
    assert await pub.send_photo(b"x", reply_to=None, silent=False) is None
