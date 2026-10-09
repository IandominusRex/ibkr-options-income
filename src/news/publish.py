"""Telegram output for the news thread — its own Bot, no src.notify import (the spreads pattern).

Best effort: failures are retried with backoff and then logged; nothing raises into a loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from telegram import Bot, LinkPreviewOptions, ReplyParameters
from telegram.error import BadRequest, RetryAfter, TelegramError

from src.common.config import Config
from src.news.render import split_message

log = logging.getLogger(__name__)


class Publisher:
    def __init__(
        self,
        bot: Any,
        chat_id: str,
        thread_id: int | None,
        *,
        backoff: tuple[float, ...] = (0.5, 1.0, 2.0),
    ) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.backoff = backoff

    @classmethod
    def from_config(cls, cfg: Config) -> Publisher | None:
        s = cfg.secrets
        if not s.telegram_bot_token or not s.telegram_chat_id:
            log.warning("news: TELEGRAM_BOT_TOKEN/CHAT_ID unset — posts are stored, not sent")
            return None
        thread = int(s.telegram_thread_news) if s.telegram_thread_news else None
        return cls(Bot(s.telegram_bot_token), s.telegram_chat_id, thread)

    async def _retry(self, op: Callable[[], Awaitable[Any]]) -> Any:
        last: Exception | None = None
        for delay in (*self.backoff, None):
            try:
                return await op()
            except BadRequest:
                raise
            except RetryAfter as exc:
                last = exc
                await asyncio.sleep(float(getattr(exc, "retry_after", 1)))
            except TelegramError as exc:
                last = exc
                if delay is None:
                    break
                await asyncio.sleep(delay)
        log.warning("news: telegram op failed after retries: %s", last)
        return None

    def _preview(self, url: str | None, above: bool) -> LinkPreviewOptions:
        if not url:
            return LinkPreviewOptions(is_disabled=True)
        return LinkPreviewOptions(url=url, prefer_large_media=True, show_above_text=above)

    async def send(
        self,
        text: str,
        *,
        silent: bool = False,
        preview_url: str | None = None,
        show_above: bool = False,
    ) -> int | None:
        first_id: int | None = None
        for i, chunk in enumerate(split_message(text)):
            preview = self._preview(preview_url if i == 0 else None, show_above)
            try:
                msg = await self._retry(
                    partial(
                        self.bot.send_message,
                        chat_id=self.chat_id,
                        text=chunk,
                        parse_mode="HTML",
                        message_thread_id=self.thread_id,
                        disable_notification=silent,
                        link_preview_options=preview,
                    )
                )
            except BadRequest as exc:
                log.warning("news: send rejected: %s", exc)
                return first_id
            if msg is not None and first_id is None:
                first_id = msg.message_id
        return first_id

    async def edit(
        self,
        message_id: int,
        text: str,
        *,
        preview_url: str | None = None,
        show_above: bool = False,
    ) -> bool:
        chunk = split_message(text)[0]
        try:
            res = await self._retry(
                lambda: self.bot.edit_message_text(
                    text=chunk,
                    chat_id=self.chat_id,
                    message_id=message_id,
                    parse_mode="HTML",
                    link_preview_options=self._preview(preview_url, show_above),
                )
            )
        except BadRequest as exc:
            msg = str(exc).lower()
            if "not modified" in msg:
                return True
            log.info("news: edit of %s failed: %s", message_id, exc)
            return False
        return res is not None

    async def send_photo(
        self, png: bytes, *, reply_to: int | None, silent: bool, caption: str | None = None
    ) -> int | None:
        reply = (
            ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)
            if reply_to
            else None
        )
        try:
            msg = await self._retry(
                lambda: self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=png,
                    caption=caption,
                    parse_mode="HTML",
                    message_thread_id=self.thread_id,
                    disable_notification=silent,
                    reply_parameters=reply,
                )
            )
        except BadRequest as exc:
            log.warning("news: photo rejected: %s", exc)
            return None
        return None if msg is None else msg.message_id
