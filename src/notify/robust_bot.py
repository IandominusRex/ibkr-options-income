"""The wheel's Telegram bot: sends retry on a transient failure and long text is split, not cut.

Every wheel process builds its bot from this class (``sender``, ``regime_notice``, ``eod_report``,
the monitor and the approval service's polling application), so no call site has to know either.

* **Retry.** A read timeout or a dropped connection is tried again (three attempts, short backoff),
  and a flood-control `RetryAfter` waits as long as Telegram asks. 2026-10-20..27: 11 roll alerts and
  3 auto-queue notices were lost to a single `TimedOut`, because the caller logged the failure and
  moved on. A `BadRequest` (a rejected parse, a missing message) is permanent and is raised at once.
  A timed-out send may already have been delivered, so a retry can post a duplicate; for an alert a
  duplicate beats a loss.
* **Splitting.** MarkdownV2 or plain text past ``LIMIT`` goes out as several messages cut at a
  paragraph or line boundary, each balanced on its own (see ``splitting.py``). Buttons ride on the
  last message of a send. An edit rewrites the target with the first chunk and posts the rest as
  replies to it, which keeps them in the same forum topic.
* **Timeouts.** The default 5 s read timeout is raised, which is what made the 21:45 SGT alert burst
  time out in the first place.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, TypeVar

from telegram import Message, ReplyParameters
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from telegram.ext import ExtBot
from telegram.request import HTTPXRequest

from src.notify.splitting import split_message

log = logging.getLogger(__name__)

T = TypeVar("T")

_ATTEMPTS = 3
_BACKOFF_SECONDS = (1.5, 4.0)
_MAX_RETRY_AFTER = 30.0
_MARKDOWN = "MarkdownV2"


def _seconds(retry_after: int | timedelta) -> float:
    secs = retry_after.total_seconds() if isinstance(retry_after, timedelta) else float(retry_after)
    return min(secs + 1.0, _MAX_RETRY_AFTER)


def _chunks(text: str, parse_mode: object) -> list[str]:
    """The text as Telegram-sized chunks; HTML and any other mode are left to their caller."""
    if parse_mode == _MARKDOWN:
        return split_message(text, markdown=True)
    if parse_mode is None:
        return split_message(text, markdown=False)
    return [text]


class RobustBot(ExtBot[None]):
    """``telegram.ext.ExtBot`` with retrying sends and split long text."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault(
            "request",
            HTTPXRequest(
                read_timeout=20.0, write_timeout=20.0, connect_timeout=10.0, pool_timeout=10.0
            ),
        )
        super().__init__(*args, **kwargs)

    async def _retrying(self, what: str, call: Callable[[], Awaitable[T]]) -> T:
        for attempt in range(_ATTEMPTS):
            last = attempt == _ATTEMPTS - 1
            try:
                return await call()
            except RetryAfter as exc:
                if last:
                    raise
                wait = _seconds(exc.retry_after)
                log.warning("telegram %s: flood control, retrying in %.0fs", what, wait)
                await asyncio.sleep(wait)
            except BadRequest:
                raise  # a subclass of NetworkError, but retrying cannot make it valid
            except (TimedOut, NetworkError) as exc:
                if last:
                    raise
                wait = _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
                log.warning(
                    "telegram %s failed (%s) — retry %d/%d in %.1fs",
                    what,
                    type(exc).__name__,
                    attempt + 1,
                    _ATTEMPTS - 1,
                    wait,
                )
                await asyncio.sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover

    async def send_message(self, chat_id: Any, text: str, *args: Any, **kwargs: Any) -> Message:
        # A positional parse_mode (never used in this repo) is sent whole rather than guessed at.
        parts = [text] if args else _chunks(text, kwargs.get("parse_mode"))
        if len(parts) == 1:
            return await self._retrying(
                "send", lambda: ExtBot.send_message(self, chat_id, text, *args, **kwargs)
            )
        markup = kwargs.pop("reply_markup", None)
        sent: Message | None = None
        for i, part in enumerate(parts):
            extra = dict(kwargs)
            if i == len(parts) - 1 and markup is not None:
                extra["reply_markup"] = markup
            if i:  # a reply target belongs to the first message only
                extra.pop("reply_to_message_id", None)
                extra.pop("reply_parameters", None)
            sent = await self._retrying(
                "send",
                lambda: ExtBot.send_message(self, chat_id, part, **extra),  # noqa: B023
            )
        assert sent is not None
        return sent

    async def edit_message_text(self, text: str, *args: Any, **kwargs: Any) -> Message | bool:
        parts = [text] if args else _chunks(text, kwargs.get("parse_mode"))
        chat_id, message_id = kwargs.get("chat_id"), kwargs.get("message_id")
        if message_id is None or chat_id is None:
            parts = parts[:1]  # an inline-message edit has nowhere to post the rest
            message_id = 0
        edited = await self._retrying(
            "edit", lambda: ExtBot.edit_message_text(self, parts[0], *args, **kwargs)
        )
        for part in parts[1:]:
            await self.send_message(  # retries on its own
                chat_id,
                part,
                parse_mode=kwargs.get("parse_mode"),
                reply_parameters=ReplyParameters(
                    message_id=int(message_id), allow_sending_without_reply=True
                ),
            )
        return edited
