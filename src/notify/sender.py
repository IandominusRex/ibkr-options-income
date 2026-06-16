"""Stateless Telegram send — called by the 15-min daemon loop and on-demand /scan.

Sends one message per candidate with inline Approve/Reject buttons, then
persists ApprovalRow records (status='pending') to SQLite so the approval
service can handle button callbacks.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from src.common.config import get_config
from src.common.schemas import (
    AccountSnapshot,
    ApprovalStatus,
    BuyCandidate,
    ClaudeReview,
    OrderState,
    PositionSnapshot,
    TradeCandidate,
)
from src.notify.formatters import (
    format_account_snapshot,
    format_auto_trade_notification,
    format_buy_list,
    format_candidate,
    format_screen_empty,
    format_screen_unchanged,
    format_unchanged_cards_digest,
)
from src.storage.db import session_scope
from src.storage.models import ApprovalRow, OrderRow
from src.storage.orders import has_active_order
from src.storage.system_settings import get_setting, is_automated_mode, is_halted, set_setting

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# system_settings keys for buy-list output suppression (intraday loop only).
_BUY_LIST_HASH_KEY = "last_buy_list_hash"
_BUY_LIST_TIME_KEY = "last_buy_list_time"


def _score_band(score: float | None) -> int:
    """Bucket a 0-100 blended score into 5-point bands, so a re-send only fires on a
    materially different score (not float jitter between cycles)."""
    return int((score or 0.0) // 5)


def _et_hhmm(dt: datetime | None = None) -> str:
    """Current (or *dt*'s) wall-clock time as HH:MM in US/Eastern, for 'since HH:MM' digests."""
    if dt is None:
        dt = datetime.now(UTC)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)  # stored DB timestamps are naive-UTC
    return dt.astimezone(_ET).strftime("%H:%M")


def thread_id(raw: str) -> int | None:
    """Parse a configured thread-ID string into an int, or None if unset."""
    return int(raw) if raw else None


def _screen_hash(keys: list[tuple]) -> str:
    """Content hash for any screen keyed on caller-provided (symbol/id, score-band) tuples."""
    return hashlib.sha256(json.dumps(sorted(keys)).encode()).hexdigest()


async def send_candidates(
    candidates: list[TradeCandidate],
    reviews: list[ClaudeReview],
    *,
    thread_id: int | None,
    label: str,
    icon: str,
    hash_key: str,
    time_key: str,
    empty_reason: str | None = None,
    noun: str = "candidate",
    session: Session | None = None,
    suppress_unchanged: bool = False,
) -> bool:
    """Send one Telegram message per candidate; persist the message_id to DB.

    In AUTOMATED mode: skips approval buttons, directly creates APPROVED ApprovalRows
    and QUEUED OrderRows, then sends a single summary notification. The existing
    _order_poll_loop picks up the QUEUED orders and executes them normally (including
    the second live-quote re-validation gate).

    In MANUAL mode (default): sends one Approve/Reject message per candidate.

    Empty candidates: sends a diagnostic ``format_screen_empty`` message to the thread so the
    operator can always see *something* per cycle (not silent on slow markets / gate rejections).

    ``suppress_unchanged`` (set by the 15-min intraday loop, never by manual /scan) first
    checks if the overall screen hash is unchanged; if so and every candidate
    already has a live same-band pending card, emits one compact ``format_screen_unchanged``
    message instead of re-spamming the full screen. Per-candidate suppression still applies inside
    the full-send path. On a fresh full send the hash+time are stored for future cycle comparisons.

    Returns ``True`` if any Telegram message was sent, ``False`` if nothing went out — the
    intraday loop uses this to decide whether the cycle warrants a quiet-cycle heartbeat (S6).
    """
    cfg = get_config()
    token = cfg.secrets.telegram_bot_token
    chat_id = cfg.secrets.telegram_chat_id

    if not token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping send")
        return False

    # Empty screen: always send a diagnostic message so the thread is never silently empty.
    if not candidates:
        reason = empty_reason or "no candidates this cycle"
        try:
            async with Bot(token=token) as bot:
                await bot.send_message(
                    chat_id=str(chat_id),
                    message_thread_id=thread_id,
                    text=format_screen_empty(icon, label, reason),
                    parse_mode="MarkdownV2",
                )
            logger.info("%s screen: no candidates — sent empty diagnostic", label)
        except Exception:
            logger.exception("Failed to send empty-screen diagnostic for %s", label)
        return True

    # Hash-based unchanged check: if the screen content hasn't changed and every candidate
    # still has a live same-band pending card, send a compact digest instead of re-spamming.
    current_hash = _screen_hash(
        [(c.candidate_id, _score_band(c.blended_score)) for c in candidates]
    )
    if suppress_unchanged and get_setting(hash_key) == current_hash:

        def _all_suppressed(sess: Session) -> bool:
            return all(_live_pending_approval(sess, c) is not None for c in candidates)

        suppressed: bool
        if session is not None:
            suppressed = _all_suppressed(session)
        else:
            with session_scope() as tmp:
                suppressed = _all_suppressed(tmp)

        if suppressed:
            since = get_setting(time_key) or "earlier"
            try:
                async with Bot(token=token) as bot:
                    await bot.send_message(
                        chat_id=str(chat_id),
                        message_thread_id=thread_id,
                        text=format_screen_unchanged(icon, label, len(candidates), since, noun),
                        parse_mode="MarkdownV2",
                    )
                logger.info(
                    "%s screen: %d candidate(s) unchanged since %s — sent compact digest",
                    label,
                    len(candidates),
                    since,
                )
            except Exception:
                logger.exception("Failed to send unchanged digest for %s", label)
            return True

    if is_automated_mode():
        sent = await _auto_queue_candidates(candidates, cfg, token, str(chat_id), thread_id)
    elif session is not None:
        sent = await _send_with_session(
            session,
            candidates,
            reviews,
            cfg,
            token,
            str(chat_id),
            thread_id,
            suppress_unchanged,
        )
    else:
        with session_scope() as own_session:
            sent = await _send_with_session(
                own_session,
                candidates,
                reviews,
                cfg,
                token,
                str(chat_id),
                thread_id,
                suppress_unchanged,
            )

    if sent:
        set_setting(hash_key, current_hash)
        set_setting(time_key, _et_hhmm())
    return sent


async def _auto_queue_candidates(
    candidates: list[TradeCandidate],
    cfg: object,
    token: str,
    chat_id: str,
    thread_id: int | None,
) -> bool:
    """Automated mode: persist APPROVED approvals + QUEUED orders, send summary notification.

    Returns ``True`` if a summary notification was sent (candidates were queued), ``False``
    otherwise (halted, or nothing new to queue this cycle).
    """
    # Kill switch: never auto-open new positions while halted (SYSTEM_REVIEW Phase 2).
    # The daily trade-count cap is enforced at the execution chokepoint (process_queued_orders).
    if is_halted():
        logger.warning("Auto-queue skipped — execution halted (kill switch engaged)")
        return False

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
                # Freeze the exact payload being approved (N2a): execution consumes this
                # snapshot, so a later re-scan that mutates contracts/premium can't change
                # the size this auto-approval committed to.
                snapshot = candidate.model_dump(mode="json")
                with s.begin_nested():
                    approval = ApprovalRow(
                        candidate_id=candidate.candidate_id,
                        status=ApprovalStatus.APPROVED,
                        chat_id=chat_id,
                        decided_at=datetime.now(UTC),
                        expires_at=expires_at,
                        snapshot=snapshot,
                    )
                    s.add(approval)
                    s.flush()
                    order = OrderRow(
                        candidate_id=candidate.candidate_id,
                        approval_id=approval.id,
                        state=OrderState.QUEUED,
                        snapshot=snapshot,
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
        return False

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
    return True


def _live_pending_approval(session: Session, candidate: TradeCandidate) -> ApprovalRow | None:
    """Return a still-pending, unexpired approval for *candidate* whose displayed score is in the
    same band — i.e. an actionable card the user has already been shown (S6). None otherwise."""
    now = datetime.now(UTC)
    existing = (
        session.query(ApprovalRow)
        .filter(
            ApprovalRow.candidate_id == candidate.candidate_id,
            ApprovalRow.status == ApprovalStatus.PENDING,
            ApprovalRow.expires_at > now,
        )
        .order_by(ApprovalRow.id.desc())
        .first()
    )
    if existing is None:
        return None
    prior_score = (existing.snapshot or {}).get("blended_score")
    if _score_band(prior_score) != _score_band(candidate.blended_score):
        return None  # score moved a band → treat as changed, send a fresh card
    return existing


async def _send_with_session(
    session: Session,
    candidates: list[TradeCandidate],
    reviews: list[ClaudeReview],
    cfg: object,
    token: str,
    chat_id: str,
    thread_id: int | None = None,
    suppress_unchanged: bool = False,
) -> bool:
    review_map = {r.candidate_id: r for r in reviews}
    ttl = cfg.approval.ttl_minutes  # type: ignore[attr-defined]
    sent_any = False

    # S6: split off candidates that already have a live, same-band pending card. They keep their
    # original (actionable) message; we replace the re-send with one compact digest line each.
    to_send = candidates
    suppressed: list[tuple[TradeCandidate, str]] = []
    if suppress_unchanged:
        to_send = []
        for candidate in candidates:
            existing = _live_pending_approval(session, candidate)
            if existing is not None:
                suppressed.append((candidate, _et_hhmm(existing.created_at)))
            else:
                to_send.append(candidate)

    # One Bot for the whole batch (avoids opening/closing an HTTP session per candidate).
    async with Bot(token=token) as bot:
        for candidate in to_send:
            # Compute TTL per candidate so a slow multi-candidate review session
            # doesn't leave the last candidate with only a few minutes of runway.
            expires_at = datetime.now(UTC) + timedelta(minutes=ttl)

            # Insert approval row first to get the integer ID for callback_data.
            # Freeze the candidate payload the human is about to see (N2a) — copied onto the
            # OrderRow at approval time so execution runs exactly what was displayed.
            approval = ApprovalRow(
                candidate_id=candidate.candidate_id,
                status=ApprovalStatus.PENDING,
                chat_id=chat_id,
                expires_at=expires_at,
                snapshot=candidate.model_dump(mode="json"),
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
                sent_any = True
                logger.info(
                    "Sent candidate %s (message_id=%s)", candidate.candidate_id, msg.message_id
                )
            except Exception:
                # The approval row is already in the session. Mark it EXPIRED so it
                # doesn't sit as a phantom PENDING that will never be executed.
                logger.exception("Failed to send Telegram message for %s", candidate.candidate_id)
                approval.status = ApprovalStatus.EXPIRED
                session.flush()

        # S6: one compact digest for everything we held back (no new approval rows created).
        if suppressed:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                    text=format_unchanged_cards_digest(suppressed),
                    parse_mode="MarkdownV2",
                )
                sent_any = True
                logger.info("Sent unchanged-candidate digest (%d suppressed)", len(suppressed))
            except Exception:
                logger.exception("Failed to send unchanged-candidate digest")

    return sent_any


async def send_buy_list(
    candidates: list[BuyCandidate],
    bot: object,
    chat_id: str,
    *,
    suppress_unchanged: bool = False,
) -> bool:
    """Send an informational Telegram message listing buy-to-own recommendations.

    No Approve/Reject buttons — these are stock purchase suggestions, not option orders.

    Empty candidates: sends a diagnostic message to thread 56 so the thread is never silent.

    ``suppress_unchanged`` (intraday loop only) replaces the full screen with a one-line
    "unchanged since HH:MM" digest when the (symbol, score-band) set is identical to the last
    full send, cutting ~26 near-identical buy-list blasts/day. Manual /scan and the morning
    cron always send the full list.

    Returns ``True`` if any Telegram message (the full screen or the unchanged digest) was sent,
    ``False`` otherwise — feeds the intraday quiet-cycle heartbeat decision (S6).
    """
    cfg = get_config()
    token = cfg.secrets.telegram_bot_token
    if not token or not chat_id:
        logger.warning("TELEGRAM credentials not set — skipping buy list send")
        return False

    thread_id_val = thread_id(cfg.secrets.telegram_thread_buy)

    if not candidates:
        try:
            from telegram import Bot as TelegramBot

            async with TelegramBot(token=token) as tbot:
                await tbot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id_val,
                    text=format_screen_empty(
                        "🟢", "Buy-to-Own", "0 would_own names cleared the buy screen this cycle"
                    ),
                    parse_mode="MarkdownV2",
                )
            logger.info("Buy list: no candidates — sent empty diagnostic")
        except Exception:
            logger.exception("Failed to send buy-list empty diagnostic to Telegram")
        return True

    current_hash = _screen_hash([(c.symbol, _score_band(c.score)) for c in candidates])

    # S6: unchanged since the last full send → compact digest instead of the full screen.
    if suppress_unchanged and get_setting(_BUY_LIST_HASH_KEY) == current_hash:
        since = get_setting(_BUY_LIST_TIME_KEY) or "earlier"
        try:
            from telegram import Bot as TelegramBot

            async with TelegramBot(token=token) as tbot:
                await tbot.send_message(
                    chat_id=chat_id,
                    message_thread_id=thread_id_val,
                    text=format_screen_unchanged(
                        "🟢", "Buy-to-Own", len(candidates), since, "name"
                    ),
                    parse_mode="MarkdownV2",
                )
            logger.info("Buy list unchanged since %s — sent compact digest (S6)", since)
            return True
        except Exception:
            logger.exception("Failed to send buy-list digest to Telegram")
            return False

    text = format_buy_list(candidates)
    if not text:
        return False

    try:
        from telegram import Bot as TelegramBot

        async with TelegramBot(token=token) as tbot:
            await tbot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id_val,
                text=text,
                parse_mode="MarkdownV2",
            )
        logger.info("Sent buy list (%d candidates)", len(candidates))
        # Record the content + time so the next cycle can suppress an unchanged repeat (S6).
        set_setting(_BUY_LIST_HASH_KEY, current_hash)
        set_setting(_BUY_LIST_TIME_KEY, _et_hhmm())
        return True
    except Exception:
        logger.exception("Failed to send buy list to Telegram")
        return False


async def send_account_snapshot(
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
) -> bool:
    """Send (or edit-in-place) an account snapshot to the dedicated Telegram thread.

    On the first call each ET calendar day a new message is sent and its message_id is stored.
    Subsequent calls on the same day edit that message in place (updating the "last updated"
    footer), so the thread stays tidy. If the stored message can't be edited (deleted, >48h old)
    a fresh send is issued and the stored id/date are overwritten.

    Best-effort: logs and returns ``False`` on any failure; never raises.
    """
    cfg = get_config()
    token = cfg.secrets.telegram_bot_token
    chat_id = cfg.secrets.telegram_chat_id
    if not token or not chat_id:
        logger.warning("TELEGRAM credentials not set — skipping account snapshot")
        return False

    thread_id_val = thread_id(cfg.secrets.telegram_thread_account)
    text = format_account_snapshot(account, positions, _et_hhmm())
    today = datetime.now(_ET).date().isoformat()
    stored_date = get_setting("account_snapshot_date")
    stored_msg_id = get_setting("account_snapshot_message_id")

    try:
        async with Bot(token=token) as bot:
            if stored_date == today and stored_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=str(chat_id),
                        message_id=int(stored_msg_id),
                        text=text,
                        parse_mode="MarkdownV2",
                    )
                    logger.info("Edited account snapshot (message_id=%s)", stored_msg_id)
                    return True
                except Exception:
                    logger.warning(
                        "Account snapshot edit failed — sending fresh message", exc_info=True
                    )

            msg = await bot.send_message(
                chat_id=str(chat_id),
                message_thread_id=thread_id_val,
                text=text,
                parse_mode="MarkdownV2",
            )
            set_setting("account_snapshot_message_id", str(msg.message_id))
            set_setting("account_snapshot_date", today)
            logger.info("Sent account snapshot (message_id=%s)", msg.message_id)
            return True
    except Exception:
        logger.exception("Failed to send account snapshot")
        return False
