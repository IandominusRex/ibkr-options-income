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

from src.analytics.fundamentals import get_fundamental_stats
from src.claude.memory import EXPIRED, RISK_REJECTED, record_outcome
from src.common.config import get_config
from src.common.market_hours import is_rth
from src.common.schemas import ApprovalStatus, OrderState, Strategy, TradeCandidate, Verdict
from src.engine.risk_engine import validate_candidates
from src.execution.circuit_breakers import (
    drawdown_breached,
    mark_based_loss,
    remaining_entry_allowance,
)
from src.execution.executor import execute_candidate
from src.ibkr.portfolio import get_account_snapshot_async, get_positions
from src.storage.db import session_scope
from src.storage.models import ApprovalRow, CandidateRow, OrderRow
from src.storage.system_settings import is_halted, set_halted
from src.strategies.covered_call import uncovered_call_capacity

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
    # Circuit breaker: auto-trip the kill switch on a mark-to-market daily #
    # loss or a drawdown from the high-water mark, then stop. (D3 fixes    #
    # the old cashflow-based breaker, which read a drawdown as a profit    #
    # on a day the system sold premium.) (SYSTEM_REVIEW Phase 2)           #
    # ------------------------------------------------------------------ #
    loss = mark_based_loss(positions, account_snap.net_liquidation)
    dd = drawdown_breached(account_snap.net_liquidation)
    with session_scope() as _s:
        cap_remaining = remaining_entry_allowance(_s)
    if loss is not None:
        reason = f"Daily mark-to-market loss ${loss:,.0f}"
    elif dd is not None:
        reason = f"Drawdown ${dd:,.0f} from high-water mark"
    else:
        reason = None
    if reason is not None:
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
    # Thread-58 failure notifications: (order_id, candidate, reason).
    thread58_failures: list[tuple[int, TradeCandidate | None, str]] = []

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
                tc: TradeCandidate | None = None
                if order_row.snapshot:
                    try:
                        tc = TradeCandidate.model_validate(order_row.snapshot)
                    except Exception:
                        pass
                thread58_failures.append((order_row.id, tc, "TTL expired — order not placed"))
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

            # Re-fetch earnings too (2026-09-11): the frozen snapshot's `next_earnings` is
            # whatever scan time saw, so a Friday-approved trade executing Monday morning
            # never learned that earnings were announced over the weekend — the
            # earnings-blackout check below (inside `validate_candidates`) judged a stale
            # date. `get_fundamental_stats` is TTL-cached with an earnings-aware window (1
            # day when a known date is within ±2 weeks, else 30), so this is a cheap DB read
            # in the common case, not a fresh network call on every ~30s poll.
            fresh_earnings = get_fundamental_stats(candidate.underlying).next_earnings
            candidate = candidate.model_copy(
                update={"dte": fresh_dte, "next_earnings": fresh_earnings}
            )

            pending.append((order_row, candidate))

        # --- Second Rules Engine pass (batched, cumulative-aware) ---
        # Sort by blended_score desc so the greedy cumulative budgets are consumed in
        # priority order, matching how the decision-time gate ran.
        #
        # The gate's per-symbol dedupe stays ON here (`dedupe_same_symbol` defaults True),
        # deliberately: this batch is the whole pending-order queue, which can hold two
        # approved-but-unexecuted orders on one underlying that were approved in different
        # scan cycles (`has_active_order` dedupes per candidate_id, not per name). Only one
        # of them should reach the shared budget, so collapsing them here is an extra
        # safety property, and it fails closed. The single-ticker deep-dive opts out
        # instead — it is a browse/compare view, and this gate is its backstop.
        ordered = sorted(pending, key=lambda pc: pc[1].blended_score, reverse=True)
        verdicts = validate_candidates([c for _, c in ordered], account_snap, positions)
        verdict_map = {v.candidate_id: v for v in verdicts}

        # Share-ownership re-check for covered calls. `validate_candidates` gates cash/
        # concentration/risk-unit budgets but never re-checks the underlying stock position —
        # if shares were sold (manually, or by an assignment the reconciler hasn't caught yet)
        # between scan and this poll, sending the call as-is would write a naked short. CC is
        # never grouped/deduped by the risk gate (unlike the income strategies above), so two
        # QUEUED calls on the same underlying from different scan cycles can both reach here;
        # `cc_shares_committed` tracks contracts claimed so far THIS PASS so the second one is
        # checked against what the first has already taken, not just the static snapshot.
        cc_shares_committed: dict[str, int] = {}

        for order_row, candidate in ordered:
            verdict = verdict_map.get(candidate.candidate_id)
            if verdict is None or verdict.verdict != Verdict.PASS:
                reasons = verdict.reasons if verdict else ["unknown"]
                # `dedupe_pre_gate` means something narrower at this gate than it does on a
                # scan card: the batch here is the pending-order queue, so the candidate
                # that displaced this one is another *approved* order on the same name, not
                # a better strike from a fresh scan. The bare reason code says nothing and
                # the scan-side humanised label ("a better strike ... claimed the shared
                # risk budget") would tell the wrong story, so the one opaque reason at this
                # call site gets a clarifying clause. Message only — no new reason code, and
                # the verdict itself is untouched.
                note = (
                    " — another approved order on the same underlying outranked this one"
                    if "dedupe_pre_gate" in reasons
                    else ""
                )
                log.warning(
                    "Re-validation REJECT for candidate=%s reasons=%s",
                    order_row.candidate_id,
                    reasons,
                )
                order_row.state = OrderState.CANCELLED
                order_row.detail = f"Re-validation failed: {reasons}{note}"
                record_outcome(order_row.candidate_id, RISK_REJECTED)
                thread58_failures.append(
                    (order_row.id, candidate, f"Re-validation failed: {', '.join(reasons)}{note}")
                )
                continue

            if candidate.strategy == Strategy.COVERED_CALL:
                capacity = uncovered_call_capacity(positions, candidate.underlying)
                committed = cc_shares_committed.get(candidate.underlying, 0)
                if candidate.contracts > capacity - committed:
                    reason = "insufficient_shares_at_execution"
                    log.warning(
                        "Share-coverage re-check REJECT — order_id=%s candidate=%s "
                        "capacity=%d already_committed=%d wants=%d",
                        order_row.id,
                        order_row.candidate_id,
                        capacity,
                        committed,
                        candidate.contracts,
                    )
                    order_row.state = OrderState.CANCELLED
                    order_row.detail = f"Re-validation failed: ['{reason}']"
                    record_outcome(order_row.candidate_id, RISK_REJECTED)
                    thread58_failures.append(
                        (order_row.id, candidate, f"Re-validation failed: {reason}")
                    )
                    continue
                cc_shares_committed[candidate.underlying] = committed + candidate.contracts

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
                thread58_failures.append(
                    (order_row.id, candidate, "Daily trade cap reached — order not placed")
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

    from src.notify.sender import send_order_notification

    for fail_order_id, fail_candidate, fail_reason in thread58_failures:
        if fail_candidate is None:
            continue
        try:
            await send_order_notification(
                "failed",
                candidate=fail_candidate,
                order_id=fail_order_id,
                failure_reason=fail_reason,
            )
        except Exception:
            log.exception(
                "Failed to send thread-58 failure notification for order_id=%s", fail_order_id
            )

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
