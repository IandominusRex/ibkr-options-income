"""Long-running Telegram polling daemon — handles button callbacks, command queries,
and order execution.

Responsibilities:
  • Receives Approve/Reject inline-keyboard callbacks, writes ApprovalRow +
    enqueues QUEUED OrderRow (handle_button — synchronous DB work only).
  • Holds the exec TWS connection (clientId 14) in the same asyncio event loop as
    the Telegram Application, and polls for QUEUED orders every
    execution.poll_interval_seconds via a background asyncio task.
  • Provides interactive query commands:
      /scan      — run full pipeline scan
      /positions — live portfolio positions
      /account   — account balances
      /health    — system health check
      /status    — combined overview
      /pending   — list pending approvals
      /fills     — recent fills (last 7 days)
      /expire    — expire all pending approvals
      /help      — command list

Only the configured TELEGRAM_CHAT_ID can trigger any command or approval.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import UTC, datetime, timedelta

from ib_async import IB
from sqlalchemy.exc import IntegrityError
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from src.claude.memory import USER_REJECTED, record_outcome
from src.common.config import get_config
from src.common.schemas import ApprovalStatus, OrderState
from src.execution.approval import process_queued_orders
from src.execution.executor import resolve_live_confirm
from src.ibkr.connection import AutoReconnect
from src.storage.db import init_db, session_scope
from src.storage.models import ApprovalRow, CandidateRow, FillRow, OrderRow

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _is_authorized(update: Update) -> bool:
    """Return True iff the update is from the configured chat."""
    if update.effective_chat is None:
        return False
    cfg = get_config()
    if not cfg.secrets.telegram_chat_id:
        return False
    return update.effective_chat.id == int(cfg.secrets.telegram_chat_id)


# ---------------------------------------------------------------------------
# Approve / Reject button handlers
# ---------------------------------------------------------------------------


def _process_button(approval_id: int, action: str) -> tuple[bool, str, str]:
    """Synchronous DB work: update approval status, optionally enqueue an order.

    Returns (found, decision_text, candidate_id_short).
    decision_text is plain text (no parse_mode) suitable for edit_message_text.
    """
    found = False
    decision_text = ""
    candidate_short = ""

    try:
        with session_scope() as session:
            approval = session.get(ApprovalRow, approval_id)
            if approval is None:
                return False, "", ""

            found = True
            candidate_short = (
                approval.candidate_id[:16] + "..."
                if len(approval.candidate_id) > 16
                else approval.candidate_id
            )

            # Idempotency guard: Telegram retries the same callback if our ack is slow.
            if approval.status != ApprovalStatus.PENDING:
                return found, f"Already {approval.status}\n({candidate_short})", candidate_short

            # Fetch candidate for human-readable display in the decision text.
            from sqlalchemy import select

            crow = session.execute(
                select(CandidateRow).where(CandidateRow.candidate_id == approval.candidate_id)
            ).scalar_one_or_none()

            if crow:
                right_lbl = "Call" if crow.right == "C" else "Put"
                strat_lbl = crow.strategy.replace("_", " ").title()
                expiry_str = f" · {crow.expiry}" if crow.expiry else ""
                candidate_display = (
                    f"{crow.underlying} {strat_lbl} ${crow.strike:.0f} {right_lbl}{expiry_str}"
                )
            else:
                candidate_display = candidate_short

            approval.decided_at = datetime.now(UTC)

            if action == "approve":
                approval.status = ApprovalStatus.APPROVED
                order = OrderRow(
                    candidate_id=approval.candidate_id,
                    approval_id=approval_id,
                    state=OrderState.QUEUED,
                )
                session.add(order)
                decision_text = f"✅ Approved — queued for execution\n{candidate_display}"
            else:
                approval.status = ApprovalStatus.REJECTED
                decision_text = f"❌ Rejected\n{candidate_display}"
                record_outcome(approval.candidate_id, USER_REJECTED)

    except IntegrityError:
        # UniqueConstraint on OrderRow.approval_id fired — a concurrent Telegram
        # callback already created the OrderRow for this approval. Safe to ignore.
        logger.warning(
            "Duplicate OrderRow for approval_id=%s — concurrent callback dropped",
            approval_id,
        )
        return found, f"Already processing\n({candidate_short})", candidate_short

    return found, decision_text, candidate_short


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Approve/Reject inline button presses."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    if not _is_authorized(update):
        logger.warning(
            "Ignoring button from unauthorized chat %s",
            update.effective_chat and update.effective_chat.id,
        )
        return

    data = query.data or ""
    parts = data.split(":", 1)
    if len(parts) != 2 or parts[0] not in ("approve", "reject"):
        logger.warning("Unexpected callback_data: %r", data)
        return

    action, id_str = parts
    try:
        approval_id = int(id_str)
    except ValueError:
        logger.warning("Non-integer approval_id in callback_data: %r", data)
        return

    found, decision_text, _ = _process_button(approval_id, action)

    if not found:
        await query.edit_message_text("Trade not found (may have been cleared).")
        return

    # decision_text is plain text — no parse_mode needed.
    await query.edit_message_text(decision_text)
    logger.info("Button %s for approval_id=%s processed", action, approval_id)


async def handle_live_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle [CONFIRM LIVE] button presses for live-order second confirmation."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    if not _is_authorized(update):
        logger.warning(
            "Ignoring live confirm from unauthorized chat %s",
            update.effective_chat and update.effective_chat.id,
        )
        return

    data = query.data or ""
    if not data.startswith("confirm_live:"):
        return

    try:
        order_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        logger.warning("Invalid confirm_live callback_data: %r", data)
        return

    resolved = resolve_live_confirm(order_id)
    if resolved:
        await query.edit_message_text(
            f"✅ LIVE order confirmed — executing now. (order_id={order_id})"
        )
        logger.info("Live confirmation received for order_id=%s", order_id)
    else:
        await query.edit_message_text(
            f"Order {order_id} not found — it may have already timed out."
        )


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def handle_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all available commands."""
    if not _is_authorized(update) or update.message is None:
        return
    from src.notify.formatters import format_help

    await update.message.reply_text(format_help(), parse_mode="MarkdownV2")


async def handle_scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Trigger a full live pipeline scan."""
    if not _is_authorized(update) or update.message is None:
        if update.effective_chat:
            logger.warning("Ignoring /scan from unauthorized chat %s", update.effective_chat.id)
        return

    ib_scan: IB | None = context.bot_data.get("ib_scan")
    if ib_scan is None or not ib_scan.isConnected():
        await update.message.reply_text(
            "IBKR market data connection unavailable — scan aborted\\.", parse_mode="MarkdownV2"
        )
        return

    # Single-flight: two overlapping scans would interleave market data requests.
    if context.bot_data.get("scan_running"):
        await update.message.reply_text(
            "A scan is already running — please wait for it to finish\\.", parse_mode="MarkdownV2"
        )
        return
    context.bot_data["scan_running"] = True

    prog_msg = await update.message.reply_text(
        "🔍 *Scan started*\nFetching market data and running analytics\\. Results arrive in \\~1\\-2 minutes\\.",
        parse_mode="MarkdownV2",
    )

    chat_id = str(update.effective_chat.id)  # type: ignore[union-attr]
    prog_msg_id = prog_msg.message_id

    async def _update_progress(text: str) -> None:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=prog_msg_id,
                text=text,
                parse_mode="MarkdownV2",
            )
        except Exception:
            pass

    async def _run_and_notify() -> None:
        from src.orchestrator.scan import run_scan

        try:
            await run_scan(ib_scan, context.bot, chat_id, progress_callback=_update_progress)
        except Exception:
            logger.exception("Scan failed")
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=prog_msg_id,
                    text="🔍 *Scan failed*\n\n⚠️ Unexpected error — check logs\\.",
                    parse_mode="MarkdownV2",
                )
            except Exception:
                pass
        finally:
            context.bot_data["scan_running"] = False

    asyncio.create_task(_run_and_notify())


async def handle_positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show live portfolio positions with P&L."""
    if not _is_authorized(update) or update.message is None:
        return

    ib: IB | None = context.bot_data.get("ib_scan")
    if ib is None or not ib.isConnected():
        await update.message.reply_text(
            "IBKR connection unavailable — start the approval service with TWS running\\.",
            parse_mode="MarkdownV2",
        )
        return

    try:
        cfg = get_config()
        from src.ibkr.portfolio import get_account_snapshot_async, get_positions
        from src.notify.formatters import format_positions

        positions = get_positions(ib)
        account = (
            await get_account_snapshot_async(ib, cfg.secrets.ibkr_account)
            if cfg.secrets.ibkr_account
            else None
        )
        text = format_positions(positions, account)
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    except Exception:
        logger.exception("/positions command failed")
        await update.message.reply_text(
            "Failed to fetch positions — check logs\\.", parse_mode="MarkdownV2"
        )


async def handle_account_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show account balances: buying power, net liq, margin."""
    if not _is_authorized(update) or update.message is None:
        return

    ib: IB | None = context.bot_data.get("ib_scan")
    if ib is None or not ib.isConnected():
        await update.message.reply_text("IBKR connection unavailable\\.", parse_mode="MarkdownV2")
        return

    cfg = get_config()
    if not cfg.secrets.ibkr_account:
        await update.message.reply_text("IBKR\\_ACCOUNT not set in \\.env", parse_mode="MarkdownV2")
        return

    try:
        from src.ibkr.portfolio import get_account_snapshot_async
        from src.notify.formatters import format_account

        account = await get_account_snapshot_async(ib, cfg.secrets.ibkr_account)
        await update.message.reply_text(format_account(account), parse_mode="MarkdownV2")
    except Exception:
        logger.exception("/account command failed")
        await update.message.reply_text(
            "Failed to fetch account data — check logs\\.", parse_mode="MarkdownV2"
        )


async def handle_health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """System health check: connections, DB, last scan, open orders."""
    if not _is_authorized(update) or update.message is None:
        return

    ib_exec: IB | None = context.bot_data.get("ib_exec")
    ib_scan: IB | None = context.bot_data.get("ib_scan")

    ib_exec_ok = ib_exec is not None and ib_exec.isConnected()
    ib_scan_ok = ib_scan is not None and ib_scan.isConnected()

    db_ok = False
    last_scan_at: datetime | None = None
    pending_approvals = 0
    open_orders = 0

    try:
        from sqlalchemy import func, select

        from src.storage.models import CandidateRow

        with session_scope() as sess:
            db_ok = True
            last_scan_at = sess.execute(
                select(CandidateRow.created_at).order_by(CandidateRow.created_at.desc()).limit(1)
            ).scalar_one_or_none()

            pending_approvals = sess.execute(
                select(func.count())
                .select_from(ApprovalRow)
                .where(ApprovalRow.status == ApprovalStatus.PENDING)
            ).scalar_one()

            open_orders = sess.execute(
                select(func.count())
                .select_from(OrderRow)
                .where(OrderRow.state.in_([OrderState.QUEUED, OrderState.SUBMITTED]))
            ).scalar_one()
    except Exception:
        logger.exception("/health DB query failed")

    from src.notify.formatters import format_health

    text = format_health(
        ib_exec_ok, ib_scan_ok, last_scan_at, pending_approvals, open_orders, db_ok
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def handle_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Combined overview: account + short options + pending approvals."""
    if not _is_authorized(update) or update.message is None:
        return

    ib: IB | None = context.bot_data.get("ib_scan")
    positions = []
    account = None

    if ib is not None and ib.isConnected():
        try:
            cfg = get_config()
            from src.ibkr.portfolio import get_account_snapshot_async, get_positions

            positions = get_positions(ib)
            if cfg.secrets.ibkr_account:
                account = await get_account_snapshot_async(ib, cfg.secrets.ibkr_account)
        except Exception:
            logger.exception("/status: failed to fetch IBKR data")
    else:
        await update.message.reply_text(
            "_IBKR connection unavailable — account/position data not shown\\._",
            parse_mode="MarkdownV2",
        )

    pending_approvals = 0
    open_orders = 0
    try:
        from sqlalchemy import func, select

        with session_scope() as sess:
            pending_approvals = sess.execute(
                select(func.count())
                .select_from(ApprovalRow)
                .where(ApprovalRow.status == ApprovalStatus.PENDING)
            ).scalar_one()
            open_orders = sess.execute(
                select(func.count())
                .select_from(OrderRow)
                .where(OrderRow.state.in_([OrderState.QUEUED, OrderState.SUBMITTED]))
            ).scalar_one()
    except Exception:
        logger.exception("/status DB query failed")

    from src.notify.formatters import format_status

    text = format_status(positions, account, pending_approvals, open_orders)
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def handle_pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all pending approvals with expiry times."""
    if not _is_authorized(update) or update.message is None:
        return

    try:
        from sqlalchemy import select

        with session_scope() as session:
            approvals = (
                session.query(ApprovalRow)
                .filter(ApprovalRow.status == ApprovalStatus.PENDING)
                .order_by(ApprovalRow.created_at.asc())
                .all()
            )

            pending_data: list[dict] = []
            for a in approvals:
                crow = session.execute(
                    select(CandidateRow).where(CandidateRow.candidate_id == a.candidate_id)
                ).scalar_one_or_none()
                pending_data.append(
                    {
                        "approval_id": a.id,
                        "candidate_id": a.candidate_id,
                        "underlying": crow.underlying if crow else "?",
                        "strategy": crow.strategy if crow else "?",
                        "right": crow.right if crow else "?",
                        "strike": crow.strike if crow else 0.0,
                        "expiry": crow.expiry if crow else None,
                        "blended_score": crow.blended_score if crow else 0.0,
                        "expires_at": a.expires_at,
                        "created_at": a.created_at,
                    }
                )

        from src.notify.formatters import format_pending_approvals

        text = format_pending_approvals(pending_data)
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    except Exception:
        logger.exception("/pending command failed")
        await update.message.reply_text(
            "Failed to fetch pending approvals — check logs\\.", parse_mode="MarkdownV2"
        )


async def handle_fills_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recent fills from the last 7 days."""
    if not _is_authorized(update) or update.message is None:
        return

    try:
        from sqlalchemy import select

        cutoff = datetime.now(UTC) - timedelta(days=7)

        with session_scope() as session:
            rows = session.execute(
                select(FillRow, CandidateRow)
                .join(CandidateRow, CandidateRow.candidate_id == FillRow.candidate_id)
                .where(FillRow.filled_at >= cutoff)
                .order_by(FillRow.filled_at.desc())
                .limit(20)
            ).all()

            fills_data: list[dict] = []
            for fill, candidate in rows:
                fills_data.append(
                    {
                        "filled_at": fill.filled_at,
                        "underlying": candidate.underlying,
                        "strategy": candidate.strategy,
                        "right": candidate.right,
                        "strike": candidate.strike,
                        "expiry": candidate.expiry,
                        "filled_qty": fill.filled_qty,
                        "avg_price": fill.avg_price,
                        "action": fill.action,
                        "is_live": fill.is_live,
                    }
                )

        from src.notify.formatters import format_fills_history

        text = format_fills_history(fills_data)
        await update.message.reply_text(text, parse_mode="MarkdownV2")
    except Exception:
        logger.exception("/fills command failed")
        await update.message.reply_text(
            "Failed to fetch fills — check logs\\.", parse_mode="MarkdownV2"
        )


async def handle_expire_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Expire all pending approvals (clears the approval queue without acting on them)."""
    if not _is_authorized(update) or update.message is None:
        return

    try:
        with session_scope() as session:
            pending = (
                session.query(ApprovalRow)
                .filter(ApprovalRow.status == ApprovalStatus.PENDING)
                .all()
            )
            count = len(pending)
            for row in pending:
                row.status = ApprovalStatus.EXPIRED

        if count == 0:
            await update.message.reply_text(
                "No pending approvals to expire\\.", parse_mode="MarkdownV2"
            )
        else:
            s = "s" if count != 1 else ""
            await update.message.reply_text(
                f"✅ Expired *{count}* pending approval{s}\\.",
                parse_mode="MarkdownV2",
            )
        logger.info("Manual /expire: cleared %d pending approval(s)", count)
    except Exception:
        logger.exception("/expire command failed")
        await update.message.reply_text(
            "Failed to expire approvals — check logs\\.", parse_mode="MarkdownV2"
        )


# ---------------------------------------------------------------------------
# Background order poll loop
# ---------------------------------------------------------------------------


async def _order_poll_loop(ib: IB, bot: object, chat_id: str, interval: int) -> None:
    """Background task: process QUEUED orders on a fixed interval."""
    while True:
        try:
            await process_queued_orders(ib, bot, chat_id)  # type: ignore[arg-type]
        except Exception:
            logger.exception("Error in order poll loop")
        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# Service bootstrap
# ---------------------------------------------------------------------------


def _recover_orphan_orders() -> None:
    """On startup, reset any SUBMITTED orders with no IB order ID back to QUEUED.

    These are orders that were claimed (SUBMITTED) by a previous process run but
    crashed before `ib.placeOrder` was called. Without recovery they stay stuck
    forever since the poll loop never revisits SUBMITTED rows.
    """
    with session_scope() as s:
        orphans = (
            s.query(OrderRow)
            .filter(OrderRow.state == OrderState.SUBMITTED, OrderRow.ib_order_id.is_(None))
            .all()
        )
        for o in orphans:
            o.state = OrderState.QUEUED
            logger.warning("Recovered orphan order id=%s to QUEUED", o.id)


async def _run_service(token: str, chat_id: str) -> None:
    cfg = get_config()
    reconnectors: list[AutoReconnect] = []

    # Exec connection: holds the order placement TWS session.
    ib: IB | None = None
    exec_id = cfg.ibkr.client_ids["exec"]
    try:
        ib_inst = IB()
        await ib_inst.connectAsync(
            cfg.ibkr.host,
            cfg.ibkr_port,
            clientId=exec_id,
            timeout=cfg.ibkr.connect_timeout_seconds,
        )
        ib = ib_inst
        reconnectors.append(
            AutoReconnect(
                ib,
                cfg.ibkr.host,
                cfg.ibkr_port,
                exec_id,
                market_data_type=cfg.ibkr.market_data_type,
                label="exec",
            )
        )
        mode = "LIVE" if cfg.is_live else "PAPER"
        logger.warning(
            "=" * 60 + "\n  IBKR MODE: %s  |  port=%s  |  clientId=%s\n" + "=" * 60,
            mode,
            cfg.ibkr_port,
            exec_id,
        )
    except Exception:
        logger.warning(
            "Could not connect to IBKR exec (port=%s) — order execution disabled; "
            "Telegram polling still active",
            cfg.ibkr_port,
        )

    # Scan connection: used for /scan, /positions, /account, /status commands.
    ib_scan: IB | None = None
    scan_id = cfg.ibkr.client_ids.get("scan", 15)
    try:
        ib_scan_inst = IB()
        await ib_scan_inst.connectAsync(
            cfg.ibkr.host,
            cfg.ibkr_port,
            clientId=scan_id,
            timeout=cfg.ibkr.connect_timeout_seconds,
        )
        ib_scan = ib_scan_inst
        reconnectors.append(
            AutoReconnect(
                ib_scan,
                cfg.ibkr.host,
                cfg.ibkr_port,
                scan_id,
                market_data_type=cfg.ibkr.market_data_type,
                label="scan",
            )
        )
        logger.info("IBKR scan connection ready (clientId=%s)", scan_id)
    except Exception:
        logger.warning(
            "Could not connect IBKR scan connection — "
            "/scan, /positions, /account, /status will be unavailable"
        )

    app = Application.builder().token(token).build()
    app.bot_data["ib_exec"] = ib
    app.bot_data["ib_scan"] = ib_scan

    # Button callbacks
    app.add_handler(CallbackQueryHandler(handle_button, pattern="^(approve|reject):"))
    app.add_handler(CallbackQueryHandler(handle_live_confirm, pattern="^confirm_live:"))

    # Commands
    app.add_handler(CommandHandler("help", handle_help_command))
    app.add_handler(CommandHandler("scan", handle_scan_command))
    app.add_handler(CommandHandler("positions", handle_positions_command))
    app.add_handler(CommandHandler("account", handle_account_command))
    app.add_handler(CommandHandler("health", handle_health_command))
    app.add_handler(CommandHandler("status", handle_status_command))
    app.add_handler(CommandHandler("pending", handle_pending_command))
    app.add_handler(CommandHandler("fills", handle_fills_command))
    app.add_handler(CommandHandler("expire", handle_expire_command))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    assert app.updater is not None, "Application must have an Updater (use default builder)"

    async with app:
        await app.start()
        await app.updater.start_polling()
        logger.info("Approval service running — Telegram polling active")

        # Register commands so "/" shows the autocomplete menu in Telegram.
        try:
            from telegram import BotCommand

            await app.bot.set_my_commands(
                [
                    BotCommand("scan", "Run full pipeline scan (CC/CSP/buy candidates)"),
                    BotCommand("status", "Account · shorts · pending approvals"),
                    BotCommand("positions", "Full portfolio positions with P&L"),
                    BotCommand("account", "Account balances (buying power, net liq, margin)"),
                    BotCommand("pending", "List pending approvals with expiry times"),
                    BotCommand("fills", "Recent fills (last 7 days)"),
                    BotCommand("expire", "Expire all pending approvals"),
                    BotCommand("health", "System health: connections, DB, last scan"),
                    BotCommand("help", "List all available commands"),
                ]
            )
            logger.info("Telegram bot commands registered")
        except Exception:
            logger.warning("Could not register Telegram bot commands", exc_info=True)

        # Send startup notification to Telegram.
        try:
            from src.notify.formatters import format_startup

            db_ok = False
            try:
                from src.storage.db import session_scope as _ss

                with _ss():
                    db_ok = True
            except Exception:
                pass

            mode = "LIVE" if cfg.is_live else "PAPER"
            services = [
                "Telegram bot (polling)",
                f"IBKR exec (clientId {exec_id})" + (" — connected" if ib else " — OFFLINE"),
                f"IBKR scan (clientId {scan_id})" + (" — connected" if ib_scan else " — OFFLINE"),
                "Order execution loop"
                + (" — active" if ib else " — disabled (no exec connection)"),
            ]
            thread_id = (
                int(cfg.secrets.telegram_thread_id) if cfg.secrets.telegram_thread_id else None
            )
            await app.bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text=format_startup(
                    ib_exec_ok=ib is not None,
                    ib_scan_ok=ib_scan is not None,
                    db_ok=db_ok,
                    mode=mode,
                    services=services,
                ),
                parse_mode="MarkdownV2",
            )
        except Exception:
            logger.warning("Could not send startup notification to Telegram", exc_info=True)

        poll_task: asyncio.Task | None = None
        if ib is not None:
            poll_task = asyncio.create_task(
                _order_poll_loop(
                    ib,
                    app.bot,
                    chat_id,
                    cfg.execution.poll_interval_seconds,
                )
            )
            logger.info(
                "Order execution loop started (poll every %ss)", cfg.execution.poll_interval_seconds
            )

        try:
            await stop_event.wait()
        finally:
            for rc in reconnectors:
                rc.stop()
            if poll_task is not None:
                poll_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poll_task
            await app.updater.stop()
            await app.stop()

    if ib is not None:
        ib.disconnect()
        logger.info("IBKR exec connection closed")

    if ib_scan is not None:
        ib_scan.disconnect()
        logger.info("IBKR scan connection closed")


def main() -> None:
    """Entry point for `python -m scripts.run_approval_service`."""
    from src.common.logging import setup_logging

    setup_logging()
    init_db()

    cfg = get_config()
    token = cfg.secrets.telegram_bot_token
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in .env")
    chat_id = cfg.secrets.telegram_chat_id
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is not set in .env")

    logger.info("Approval service starting")
    _recover_orphan_orders()
    try:
        asyncio.run(_run_service(token, chat_id))
    except KeyboardInterrupt:
        logger.info("Approval service stopped")
