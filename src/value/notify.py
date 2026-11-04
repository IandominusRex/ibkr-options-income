"""The value book's plain Telegram messages (spec §9.7), the minimum money needs: fills, a frozen
attribution, a funding request, a proposal waiting for a tap. Cards, buttons and digests are
Part 6. Sends to ``TELEGRAM_THREAD_VALUE`` (the main chat when it is empty). Never raises; every
message is logged whether or not it is sent. Imports nothing from ``src.notify``."""

from __future__ import annotations

import logging

from src.common.config import get_config

log = logging.getLogger(__name__)


async def send(messages: list[str]) -> int:
    """Post each message as plain text; returns how many were sent."""
    s = get_config().secrets
    for m in messages:
        log.info("value notify: %s", m)
    if not messages or not s.telegram_bot_token or not s.telegram_chat_id:
        return 0
    thread = (s.telegram_thread_value or "").strip()
    sent = 0
    try:
        from telegram import Bot

        async with Bot(token=s.telegram_bot_token) as bot:
            for m in messages:
                await bot.send_message(
                    chat_id=s.telegram_chat_id,
                    text=m,
                    message_thread_id=int(thread) if thread.isdigit() else None,
                )
                sent += 1
    except Exception:  # noqa: BLE001 - a failed message never stops the book
        log.exception("value notify failed")
    return sent
