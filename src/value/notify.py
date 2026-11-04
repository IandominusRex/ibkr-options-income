"""The value book's Telegram messages (spec §9.7): plain lines for fills, funding requests and
tap replies (``send``), and cards with buttons (``send_cards``, Part 6). Sends to
``TELEGRAM_THREAD_VALUE`` (the main chat when it is empty). Never raises; every message is logged
whether or not it is sent. Imports nothing from ``src.notify``."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.common.config import get_config

if TYPE_CHECKING:
    from src.value.cards import Card

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


async def send_cards(cards: list[Card]) -> list[str]:
    """Post each card (an inline keyboard of one row when it has buttons). Returns the keys that
    were sent, in order; a card that fails is left out, so the outbox posts it again next tick."""
    s = get_config().secrets
    for c in cards:
        log.info("value card %s: %s", c.key, c.text.replace("\n", " | "))
    if not cards or not s.telegram_bot_token or not s.telegram_chat_id:
        return []
    thread = (s.telegram_thread_value or "").strip()
    sent: list[str] = []
    try:
        from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

        async with Bot(token=s.telegram_bot_token) as bot:
            for c in cards:
                markup = (
                    InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(label, callback_data=data)
                                for label, data in c.buttons
                            ]
                        ]
                    )
                    if c.buttons
                    else None
                )
                await bot.send_message(
                    chat_id=s.telegram_chat_id,
                    text=c.text,
                    message_thread_id=int(thread) if thread.isdigit() else None,
                    reply_markup=markup,
                )
                sent.append(c.key)
    except Exception:  # noqa: BLE001 - a failed card is retried at the next tick
        log.exception("value card send failed")
    return sent
