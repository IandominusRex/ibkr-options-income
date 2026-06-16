"""Approval-to-execution bridge: polls QUEUED OrderRows and drives execution.

Called periodically from the approval_service daemon (clientId 14).
Two-phase design:
  Phase 1 (sync)  — classify every QUEUED order: expire TTL, defer off-hours,
                    cancel if re-validation fails, collect IDs to execute.
  Phase 2 (async) — call executor.execute_candidate for each approved order.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ib_async import IB
from sqlalchemy.orm import Session
from telegram import Bot

from src.claude.memory import EXPIRED, RISK_REJECTED, record_outcome
from src.common.config import get_config
from src.common.market_hours import is_rth
from src.common.schemas import ApprovalStatus, OrderState, TradeCandidate, Verdict
from src.engine.risk_engine import validate_candidates
from src.execution.circuit_breakers import daily_loss_breached, remaining_entry_allowance
from src.execution.executor import execute_candidate
from src.ibkr.portfolio import get_account_snapshot_async, get_positions
from src.storage.db import session_scope
from src.storage.models import ApprovalRow, CandidateRow, OrderRow
from src.storage.system_settings import is_halted, set_halted

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def _load_candidate(session: Session, order_row: OrderRow) -> TradeCandidate | None:
    """Load the candidate to execute, preferring the frozen approval snapshot (N2a).

    The OrderRow carries the exact payload that was approved. We execute that — never the
    latest CandidateRow payload, which a 15-min re-scan may have mutated (different contracts
    or premium) between approval and this execution pass. Legacy orders created before the
    freeze have no snapshot; those fall back to the CandidateRow.
    """
    if order_row.snapshot:
        return TradeCandidate.model_validate(order_row.snapshot)
    row = (
        session.query(CandidateRow)
        .filter(CandidateRow.candidate_id == order_row.candidate_id)
        .first()
    )
    if row is None:
        return None
    return TradeCandidate.model_validate(row.payload)


async def process_queued_orders(ib: IB, bot: Bot, chat_id: str) -> None:
    """Pick up QUEUED orders, TTL-expire stale ones, re-validate, and execute.

    Designed to be called periodically (e.g. every 30 s) from a background task.
    All synchronous DB and IB work is done in Phase 1 before any async executor
    calls so the DB session is never held open across awaits.
    """
    cfg = get_config()
    now = datetime.now(UTC)

    # ------------------------------------------------------------------ #
    # Kill switch: when halted, transmit nothing. Orders stay QUEUED and  #
    # resume when /resume is sent (or TTL-expire). (SYSTEM_REVIEW Phase 2) #
    # ------------------------------------------------------------------ #
    if is_halted():
        log.warning("Execution halted (kill switch engaged) — skipping order processing")
        return

    # ------------------------------------------------------------------ #
    # Fast check: any QUEUED orders at all?                                #
    # ------------------------------------------------------------------ #
    with session_scope() as _s:
        count = _s.query(OrderRow).filter(OrderRow.state == OrderState.QUEUED).count()
    if not count:
        return

    # ------------------------------------------------------------------ #
    # Fetch IBKR data BEFORE opening the write session so we never hold   #
    # the SQLite write lock across a slow TWS network call (~30 s max).   #
    # ------------------------------------------------------------------ #
    try:
        managed = ib.managedAccounts()
        acct = cfg.secrets.ibkr_account or (managed[0] if managed else "")
        account_snap = await get_account_snapshot_async(ib, acct)
        positions = get_positions(ib)
    except Exception:
        log.exception("Could not fetch account data from IB — skipping execution pass")
        return

    # ------------------------------------------------------------------ #
    # Circuit breaker: auto-trip the kill switch on a daily realized-loss  #
    # breach, then stop. (SYSTEM_REVIEW Phase 2)                           #
    # ------------------------------------------------------------------ #
    with session_scope() as _s:
        loss = daily_loss_breached(_s, account_snap.net_liquidation)
        cap_remaining = remaining_entry_allowance(_s)
    if loss is not None:
        reason = f"daily realized loss ${loss:,.0f} exceeded the configured loss limit"
        set_halted(True, reason)
        log.critical("Circuit breaker tripped — %s. Execution halted.", reason)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"🛑 Circuit breaker: execution HALTED — {reason}. Send /resume to re-enable.",
            )
        except Exception:
            log.exception("Failed to send circuit-breaker halt notification")
        return

    # ------------------------------------------------------------------ #
    # Phase 1: synchronous classification                                  #
    # ------------------------------------------------------------------ #
    to_execute: list[tuple[int, TradeCandidate]] = []
    # Notifications to send in Phase 2 (can't await inside the session block).
    notify_msgs: list[str] = []

    with session_scope() as session:
        queued = session.query(OrderRow).filter(OrderRow.state == OrderState.QUEUED).all()
        if not queued:
            return

        log.info("Processing %d QUEUED order(s)", len(queued))

        # SQLite strips tzinfo on read-back; treat stored datetimes as UTC.
        def _aware(dt: datetime) -> datetime:
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

        # First pass: expire/defer/load. Survivors go to a batch re-validation so the
        # cumulative budgets (per-ticker / sector / CSP collateral / buying power) are
        # enforced ACROSS all pending orders, not one-at-a-time (which is cumulative-blind:
        # N same-ticker orders would each pass against current positions alone).
        pending: list[tuple[OrderRow, TradeCandidate]] = []
        for order_row in queued:
            approval = session.get(ApprovalRow, order_row.approval_id)

            # Missing expires_at is treated as expired — an approval with no TTL
            # could persist indefinitely and execute a stale order days later.
            if approval is None or not approval.expires_at:
                log.error(
                    "Approval %s has no expires_at — cancelling order_id=%s",
                    order_row.approval_id,
                    order_row.id,
                )
                order_row.state = OrderState.CANCELLED
                order_row.detail = "Approval missing TTL"
                notify_msgs.append(
                    f"Order CANCELLED: approval for {order_row.candidate_id[:12]} is missing "
                    f"TTL (order_id={order_row.id}). Please re-scan."
                )
                continue

            if _aware(approval.expires_at) < now:
                log.info(
                    "Expiring stale approval=%s candidate=%s",
                    order_row.approval_id,
                    order_row.candidate_id,
                )
                approval.status = ApprovalStatus.EXPIRED
                order_row.state = OrderState.CANCELLED
                order_row.detail = "TTL expired"
                record_outcome(order_row.candidate_id, EXPIRED)
                continue

            if cfg.execution.transmit_only_in_rth and not is_rth():
                log.debug("Outside RTH — deferring order_id=%s", order_row.id)
                continue

            candidate = _load_candidate(session, order_row)
            if candidate is None:
                log.error(
                    "Candidate %s not found in DB — cancelling order_id=%s",
                    order_row.candidate_id,
                    order_row.id,
                )
                order_row.state = OrderState.CANCELLED
                order_row.detail = "Candidate not found"
                continue

            # Recompute DTE from the stored expiry so a Friday-scanned trade
            # processed Monday has an accurate DTE at re-validation time.
            today = datetime.now(_ET).date()
            fresh_dte = (candidate.expiry - today).days
            candidate = candidate.model_copy(update={"dte": fresh_dte})

            pending.append((order_row, candidate))

        # --- Second Rules Engine pass (batched, cumulative-aware) ---
        # Sort by blended_score desc so the greedy cumulative budgets are consumed in
        # priority order, matching how the decision-time gate ran.
        ordered = sorted(pending, key=lambda pc: pc[1].blended_score, reverse=True)
        verdicts = validate_candidates([c for _, c in ordered], account_snap, positions)
        verdict_map = {v.candidate_id: v for v in verdicts}

        for order_row, candidate in ordered:
            verdict = verdict_map.get(candidate.candidate_id)
            if verdict is None or verdict.verdict != Verdict.PASS:
                reasons = verdict.reasons if verdict else ["unknown"]
                log.warning(
                    "Re-validation REJECT for candidate=%s reasons=%s",
                    order_row.candidate_id,
                    reasons,
                )
                order_row.state = OrderState.CANCELLED
                order_row.detail = f"Re-validation failed: {reasons}"
                record_outcome(order_row.candidate_id, RISK_REJECTED)
                continue

            # Daily trade-count circuit breaker: once today's entry cap is reached,
            # cancel further entry orders rather than transmit them. (SYSTEM_REVIEW Phase 2)
            if cap_remaining is not None and cap_remaining <= 0:
                log.warning(
                    "Daily trade cap reached — cancelling order_id=%s candidate=%s",
                    order_row.id,
                    order_row.candidate_id,
                )
                order_row.state = OrderState.CANCELLED
                order_row.detail = "Daily trade cap reached"
                notify_msgs.append(
                    f"Order CANCELLED: daily trade cap reached for {order_row.candidate_id[:12]}."
                )
                continue

            # Mark as SUBMITTED inside Phase 1 so the next poll cycle (which fires
            # every poll_interval_seconds) does not pick up the same order again.
            # If execution fails, the except block in Phase 2 sets it to REJECTED.
            order_row.state = OrderState.SUBMITTED
            order_row.detail = "Queued for async execution"
            to_execute.append((order_row.id, candidate))
            if cap_remaining is not None:
                cap_remaining -= 1

    # ------------------------------------------------------------------ #
    # Phase 2: async execution (session already committed and closed)      #
    # ------------------------------------------------------------------ #
    for msg in notify_msgs:
        try:
            await bot.send_message(chat_id=chat_id, text=msg)
        except Exception:
            log.exception("Failed to send TTL-null cancel notification")

    for order_id, candidate in to_execute:
        try:
            await execute_candidate(ib, bot, chat_id, order_id, candidate)
        except Exception:
            log.exception("Execution error for order_id=%s", order_id)
            with session_scope() as session:
                row = session.get(OrderRow, order_id)
                if row and row.state not in (OrderState.FILLED, OrderState.PARTIAL):
                    row.state = OrderState.REJECTED
                    row.detail = "Execution exception"
