"""Stateless Telegram send — called once by the morning_scan one-shot.

Sends one message per candidate with inline Approve/Reject buttons, then
persists ApprovalRow records (status='pending') to SQLite so the approval
service can handle button callbacks.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from src.common.config import get_config
from src.common.schemas import (
    ApprovalStatus,
    BuyCandidate,
    ClaudeReview,
    OrderState,
    TradeCandidate,
)
from src.notify.formatters import format_auto_trade_notification, format_candidate
from src.storage.db import session_scope
from src.storage.models import ApprovalRow, OrderRow
from src.storage.orders import has_active_order
from src.storage.system_settings import is_automated_mode

logger = logging.getLogger(__name__)


async def send_candidates(
    candidates: list[TradeCandidate],
    reviews: list[ClaudeReview],
    session: Session | None = None,
) -> None:
    """Send one Telegram message per candidate; persist the message_id to DB.

    In AUTOMATED mode: skips approval buttons, directly creates APPROVED ApprovalRows
    and QUEUED OrderRows, then sends a single summary notification. The existing
    _order_poll_loop picks up the QUEUED orders and executes them normally (including
    the second live-quote re-validation gate).

    In MANUAL mode (default): sends one Approve/Reject message per candidate.

    Safe to call with an empty list — no API calls are made.
    """
    if not candidates:
        return

    cfg = get_config()
    token = cfg.secrets.telegram_bot_token
    chat_id = cfg.secrets.telegram_chat_id

    if not token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping send")
        return

    thread_id = int(cfg.secrets.telegram_thread_id) if cfg.secrets.telegram_thread_id else None

    if is_automated_mode():
        await _auto_queue_candidates(candidates, cfg, token, str(chat_id), thread_id)
        return

    if session is not None:
        await _send_with_session(session, candidates, reviews, cfg, token, str(chat_id), thread_id)
        return

    with session_scope() as own_session:
        await _send_with_session(
            own_session, candidates, reviews, cfg, token, str(chat_id), thread_id
        )


async def _auto_queue_candidates(
    candidates: list[TradeCandidate],
    cfg: object,
    token: str,
    chat_id: str,
    thread_id: int | None,
) -> None:
    """Automated mode: persist APPROVED approvals + QUEUED orders, send summary notification."""
    ttl = cfg.approval.ttl_minutes  # type: ignore[attr-defined]
    queued: list[TradeCandidate] = []

    with session_scope() as s:
        for candidate in candidates:
            # Idempotency: the deterministic candidate_id means the 15-min loop
            # regenerates this exact candidate every cycle. Skip if an order is
            # already working or filled for it — otherwise we stack duplicate
            # positions (naked calls for CCs, which bypass the exposure gates).
            if has_active_order(s, candidate.candidate_id):
                logger.info(
                    "Auto-queue skip — active order already exists for %s",
                    candidate.candidate_id,
                )
                continue
            expires_at = datetime.now(UTC) + timedelta(minutes=ttl)
            # Per-candidate SAVEPOINT so a race (the partial unique index firing because a
            # concurrent writer queued the same candidate) rolls back only this candidate,
            # not the whole batch.
            try:
                with s.begin_nested():
                    approval = ApprovalRow(
                        candidate_id=candidate.candidate_id,
                        status=ApprovalStatus.APPROVED,
                        chat_id=chat_id,
                        decided_at=datetime.now(UTC),
                        expires_at=expires_at,
                    )
                    s.add(approval)
                    s.flush()
                    order = OrderRow(
                        candidate_id=candidate.candidate_id,
                        approval_id=approval.id,
                        state=OrderState.QUEUED,
                    )
                    s.add(order)
            except IntegrityError:
                logger.info(
                    "Auto-queue race — active order appeared for %s; skipping",
                    candidate.candidate_id,
                )
                continue
            queued.append(candidate)
            logger.info(
                "Auto-queued candidate %s (approval_id=%s)", candidate.candidate_id, approval.id
            )

    if not queued:
        return

    text = format_auto_trade_notification(queued)
    try:
        async with Bot(token=token) as bot:
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=text,
                parse_mode="MarkdownV2",
            )
    except Exception:
        logger.exception("Failed to send auto-queue notification")


async def _send_with_session(
    session: Session,
    candidates: list[TradeCandidate],
    reviews: list[ClaudeReview],
    cfg: object,
    token: str,
    chat_id: str,
    thread_id: int | None = None,
) -> None:
    review_map = {r.candidate_id: r for r in reviews}
    ttl = cfg.approval.ttl_minutes  # type: ignore[attr-defined]

    # One Bot for the whole batch (avoids opening/closing an HTTP session per candidate).
    async with Bot(token=token) as bot:
        for candidate in candidates:
            # Compute TTL per candidate so a slow multi-candidate review session
            # doesn't leave the last candidate with only a few minutes of runway.
            expires_at = datetime.now(UTC) + timedelta(minutes=ttl)

            # Insert approval row first to get the integer ID for callback_data.
            approval = ApprovalRow(
                candidate_id=candidate.candidate_id,
                status=ApprovalStatus.PENDING,
                chat_id=chat_id,
                expires_at=expires_at,
            )
            session.add(approval)
            session.flush()  # populate approval.id

            review = review_map.get(candidate.candidate_id)
            text = format_candidate(candidate, review)
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{approval.id}"),
                        InlineKeyboardButton("❌ Reject", callback_data=f"reject:{approval.id}"),
                    ]
                ]
            )

            try:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    text=text,
                    parse_mode="MarkdownV2",
                    reply_markup=keyboard,
                )
                approval.telegram_message_id = msg.message_id
                session.flush()
                logger.info(
                    "Sent candidate %s (message_id=%s)", candidate.candidate_id, msg.message_id
                )
            except Exception:
                # The approval row is already in the session. Mark it EXPIRED so it
                # doesn't sit as a phantom PENDING that will never be executed.
                logger.exception("Failed to send Telegram message for %s", candidate.candidate_id)
                approval.status = ApprovalStatus.EXPIRED
                session.flush()


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

        thread_id = int(cfg.secrets.telegram_thread_id) if cfg.secrets.telegram_thread_id else None
        async with TelegramBot(token=token) as tbot:
            await tbot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=text,
                parse_mode="MarkdownV2",
            )
        logger.info("Sent buy list (%d candidates)", len(candidates))
    except Exception:
        logger.exception("Failed to send buy list to Telegram")
