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
from datetime import time as dtime
from zoneinfo import ZoneInfo

from ib_async import IB
from sqlalchemy.orm import Session
from telegram import Bot

from src.claude.memory import EXPIRED, RISK_REJECTED, record_outcome
from src.common.config import get_config
from src.common.schemas import ApprovalStatus, OrderState, TradeCandidate, Verdict
from src.engine.risk_engine import validate_candidates
from src.execution.executor import execute_candidate
from src.ibkr.portfolio import get_account_snapshot, get_positions
from src.storage.db import session_scope
from src.storage.models import ApprovalRow, CandidateRow, OrderRow

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def _is_rth() -> bool:
    """True when current time is within Regular Trading Hours (09:30–16:00 ET, weekdays)."""
    now = datetime.now(_ET)
    if now.weekday() >= 5:
        return False
    return dtime(9, 30) <= now.time() <= dtime(16, 0)


def _load_candidate(session: Session, candidate_id: str) -> TradeCandidate | None:
    row = session.query(CandidateRow).filter(CandidateRow.candidate_id == candidate_id).first()
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
    # Phase 1: synchronous classification                                  #
    # ------------------------------------------------------------------ #
    to_execute: list[tuple[int, TradeCandidate]] = []

    with session_scope() as session:
        queued = session.query(OrderRow).filter(OrderRow.state == OrderState.QUEUED).all()
        if not queued:
            return

        log.info("Processing %d QUEUED order(s)", len(queued))

        # Fetch account snapshot + positions once for all re-validations.
        try:
            managed = ib.managedAccounts()
            acct = cfg.secrets.ibkr_account or (managed[0] if managed else "")
            account_snap = get_account_snapshot(ib, acct)
            positions = get_positions(ib)
        except Exception:
            log.exception("Could not fetch account data from IB — skipping execution pass")
            return

        for order_row in queued:
            approval = session.get(ApprovalRow, order_row.approval_id)

            # --- TTL check ---
            # SQLite strips tzinfo on read-back; treat stored datetimes as UTC.
            def _aware(dt: datetime) -> datetime:
                return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

            if approval and approval.expires_at and _aware(approval.expires_at) < now:
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

            # --- RTH gate ---
            if cfg.execution.transmit_only_in_rth and not _is_rth():
                log.debug("Outside RTH — deferring order_id=%s", order_row.id)
                continue

            # --- Load candidate ---
            candidate = _load_candidate(session, order_row.candidate_id)
            if candidate is None:
                log.error(
                    "Candidate %s not found in DB — cancelling order_id=%s",
                    order_row.candidate_id,
                    order_row.id,
                )
                order_row.state = OrderState.CANCELLED
                order_row.detail = "Candidate not found"
                continue

            # --- Second Rules Engine pass ---
            verdicts = validate_candidates([candidate], account_snap, positions)
            if not verdicts or verdicts[0].verdict != Verdict.PASS:
                reasons = verdicts[0].reasons if verdicts else ["unknown"]
                log.warning(
                    "Re-validation REJECT for candidate=%s reasons=%s",
                    order_row.candidate_id,
                    reasons,
                )
                order_row.state = OrderState.CANCELLED
                order_row.detail = f"Re-validation failed: {reasons}"
                record_outcome(order_row.candidate_id, RISK_REJECTED)
                continue

            to_execute.append((order_row.id, candidate))

    # ------------------------------------------------------------------ #
    # Phase 2: async execution (session already committed and closed)      #
    # ------------------------------------------------------------------ #
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
