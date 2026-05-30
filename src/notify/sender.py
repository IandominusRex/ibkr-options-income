"""Stateless Telegram send — called once by the morning_scan one-shot.

Sends one message per candidate with inline Approve/Reject buttons, then
persists ApprovalRow records (status='pending') to SQLite so the approval
service can handle button callbacks.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from src.common.config import get_config
from src.common.schemas import ApprovalStatus, BuyCandidate, ClaudeReview, TradeCandidate
from src.notify.formatters import format_candidate
from src.storage.models import ApprovalRow

logger = logging.getLogger(__name__)


async def send_candidates(
    candidates: list[TradeCandidate],
    reviews: list[ClaudeReview],
    session: Session,
) -> None:
    """Send one Telegram message per candidate; persist the message_id to DB.

    Safe to call with an empty list — no API calls are made.
    If Telegram credentials are missing, logs a warning and returns early.
    """
    if not candidates:
        return

    cfg = get_config()
    token = cfg.secrets.telegram_bot_token
    chat_id = cfg.secrets.telegram_chat_id

    if not token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping send")
        return

    review_map = {r.candidate_id: r for r in reviews}
    ttl = cfg.approval.ttl_minutes
    expires_at = datetime.now(UTC) + timedelta(minutes=ttl)

    for candidate in candidates:
        # Insert approval row first to get the integer ID for callback_data.
        approval = ApprovalRow(
            candidate_id=candidate.candidate_id,
            status=ApprovalStatus.PENDING,
            chat_id=str(chat_id),
            expires_at=expires_at,
        )
        session.add(approval)
        session.flush()  # populate approval.id

        review = review_map.get(candidate.candidate_id)
        text = format_candidate(candidate, review)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Approve", callback_data=f"approve:{approval.id}"),
                    InlineKeyboardButton("Reject", callback_data=f"reject:{approval.id}"),
                ]
            ]
        )

        try:
            async with Bot(token=token) as bot:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="MarkdownV2",
                    reply_markup=keyboard,
                )
            approval.telegram_message_id = msg.message_id
            session.flush()
            logger.info("Sent candidate %s (message_id=%s)", candidate.candidate_id, msg.message_id)
        except Exception:
            logger.exception("Failed to send Telegram message for %s", candidate.candidate_id)


async def send_buy_list(
    candidates: list[BuyCandidate],
    bot: object,
    chat_id: str,
) -> None:
    """Send an informational Telegram message listing buy-to-own recommendations.

    No Approve/Reject buttons — these are stock purchase suggestions, not option orders.
    """
    if not candidates:
        return

    cfg = get_config()
    token = cfg.secrets.telegram_bot_token
    if not token or not chat_id:
        logger.warning("TELEGRAM credentials not set — skipping buy list send")
        return

    lines = ["*Buy\\-to\\-Own Candidates*", "_Stocks worth acquiring for future covered calls_", ""]
    for i, c in enumerate(candidates[:10], 1):
        regime = c.technical_regime or "unknown"
        iv_str = f"{c.iv_rank:.0f}" if c.iv_rank is not None else "?"
        quality = "✓" if c.quality_flag else "?"
        lines.append(
            f"{i}\\. *{c.symbol}* — score {c.score:.0f}/100 | IV rank {iv_str} | regime {regime} | quality {quality}"
        )
        if c.rationale:
            lines.append(f"   _{c.rationale[:100]}_")

    text = "\n".join(lines)[:4000]

    try:
        from telegram import Bot as TelegramBot
        async with TelegramBot(token=token) as tbot:
            await tbot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
        logger.info("Sent buy list (%d candidates)", len(candidates))
    except Exception:
        logger.exception("Failed to send buy list to Telegram")
