"""Approval-to-execution bridge: polls QUEUED OrderRows and drives execution.

Called periodically from the approval_service daemon (clientId 14).
Two-phase design:
  Phase 1 (sync)  — classify every QUEUED order: expire TTL, defer off-hours,
                    cancel if re-validation fails, collect IDs to execute.
  Phase 2 (async) — call executor.execute_candidate for each approved order.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ib_async import IB
from sqlalchemy import ColumnElement, func
from sqlalchemy.orm import Session
from telegram import Bot

from src.analytics.fundamentals import get_fundamental_stats
from src.claude.memory import EXPIRED, RISK_REJECTED, record_outcome
from src.common.config import get_config
from src.common.market_hours import is_rth
from src.common.schemas import (
    AccountSnapshot,
    ApprovalStatus,
    OrderState,
    PositionSnapshot,
    SizingContext,
    Strategy,
    TradeCandidate,
    Verdict,
)
from src.data.factory import get_price_provider
from src.engine.regime_limits import (
    hard_max_contracts,
    per_trade_cap,
    scaled_budget_fit,
    sizing_note,
    trim_for_send,
)
from src.engine.risk_engine import validate_candidates
from src.execution.circuit_breakers import evaluate_breakers, remaining_entry_allowance
from src.execution.executor import execute_candidate
from src.ibkr.portfolio import get_account_snapshot_async, get_positions
from src.regime.actions import link_order, record_action
from src.regime.context import build_sizing_context
from src.regime.refresh import refresh_regime_cached
from src.storage.db import session_scope
from src.storage.models import ApprovalRow, CandidateRow, OrderRow
from src.storage.system_settings import get_halt_source, is_halted, set_halted
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


def _send_context(now: datetime, positions: list[PositionSnapshot]) -> SizingContext | None:
    """The sizing context for the send-time re-gate: the regime as it is *now*.

    Refreshes the regime through a short cache (a regime that escalated between the card and this
    poll is seen here; a change found now is persisted unsent and announced by the next scan) and
    builds a ``for_send=True`` context, which counts today's already-sent CSPs but not the queued
    orders that are the batch being validated. No bars are fetched here, so what the card knew
    about each name is carried over from its frozen snapshot: a leveraged ETF whose card was cut
    under the stressed tier stays in that tier (the tier can tighten between card and send, never
    loosen), and the live spot of every name under the scale-in ladder is read once for the
    gate's ladder re-check (ruling 48). Reads the database in its own session and the price
    provider outside it, so it is called *before* the write session below is opened.
    """
    try:
        refresh_regime_cached(now)
    except Exception:
        log.warning("send-time regime refresh failed — using the last known regime", exc_info=True)
    triggers: dict[str, list[str]] = {}
    ladder_names: set[str] = set()
    with session_scope() as session:
        ctx = build_sizing_context(now=now, session=session, for_send=True, positions=positions)
        if ctx is None:
            return None
        rows = session.query(OrderRow.snapshot).filter(OrderRow.state == OrderState.QUEUED).all()
    for (snap,) in rows:
        if not isinstance(snap, dict) or snap.get("strategy") != Strategy.CASH_SECURED_PUT.value:
            continue
        note = snap.get("sizing") or {}
        symbol = str(snap.get("underlying", ""))
        if note.get("leverage_tier") == "stressed":
            triggers[symbol] = ["snapshot_stressed"]
        if note.get("scale_in"):
            ladder_names.add(symbol)
    spots: dict[str, float] = {}
    if ladder_names:
        provider = get_price_provider()
        for symbol in sorted(ladder_names):
            try:
                price = provider.get_last_price(symbol)
            except Exception:
                price = None
            if price:
                spots[symbol] = float(price)
    return ctx.model_copy(
        update={"name_triggers": {**ctx.name_triggers, **triggers}, "spot_at_send": spots}
    )


def _trim_to_regime(
    session: Session,
    order_row: OrderRow,
    candidate: TradeCandidate,
    sizing: SizingContext,
    hard_max: int,
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
) -> tuple[TradeCandidate, str | None]:
    """Trim a queued CSP down to what the regime allows *now*; returns ``(candidate, note)``.

    The regime can escalate, a budget can shrink and a floor can be used up between the card and
    this send. Unlike the gate (which rejects rather than trims) this only ever *reduces* the
    order, which can only reduce exposure; a candidate the regime now allows nothing of
    (a result of zero) is left as it is for the gate to refuse with the regime's own reason.
    The trimmed order replaces the frozen snapshot, and the trim is recorded once per day.
    """
    if candidate.strategy != Strategy.CASH_SECURED_PUT:
        return candidate, None
    fit = scaled_budget_fit(candidate, sizing, account, positions)
    n = trim_for_send(candidate, sizing, hard_max, fit)
    old = candidate.contracts
    if not 0 < n < old:
        return candidate, None
    cap = per_trade_cap(sizing, candidate.underlying, hard_max)
    fresh = sizing_note(sizing, candidate.underlying, old, hard_max)
    budget_bound = fit is not None and fit < min(old, cap)
    kind = "escalation_trim"
    if fresh is not None and not budget_bound and fresh.ceiling_kind == "leveraged_ceiling":
        kind = "leveraged_ceiling"
        text = (
            f"trimmed {old} -> {n} by the size limit for a leveraged ETF "
            f"({fresh.leverage}x, {fresh.leverage_tier})"
        )
    elif fresh is not None:
        suffix = ": budget" if budget_bound else ""
        text = (
            f"trimmed {old} -> {n} by the market regime ({fresh.regime_index} "
            f"{fresh.regime.value}{suffix})"
        )
    else:  # pragma: no cover - a CSP with a context always has a note
        text = f"trimmed {old} -> {n} by the market regime"
    update: dict[str, object] = {"contracts": n, "collateral": candidate.strike * n * 100}
    if fresh is not None:
        base = candidate.sizing or fresh
        update["sizing"] = base.model_copy(
            update={
                "regime": fresh.regime,
                "regime_index": fresh.regime_index,
                "per_trade_cap": fresh.per_trade_cap,
                "budget_multiplier": fresh.budget_multiplier,
                "leverage": fresh.leverage,
                "leverage_tier": fresh.leverage_tier,
                "ceiling_kind": fresh.ceiling_kind,
            }
        )
    trimmed = candidate.model_copy(update=update)
    order_row.snapshot = trimmed.model_dump(mode="json")
    record_action(
        cand=trimmed,
        kind=kind,
        deterministic=old,
        sent=n,
        reason=text,
        order_id=order_row.id,
        session=session,
    )
    return trimmed, text


def _is_roll_order() -> ColumnElement[bool]:
    """SQL predicate: the order's frozen snapshot is a roll candidate."""
    return func.json_extract(OrderRow.snapshot, "$.strategy") == Strategy.ROLL.value


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
    # A circuit-breaker halt still lets QUEUED rolls through (2026-10-15): the breaker trips on
    # the move that breaches shorts, and a roll swaps a short for another of the same size —
    # no new exposure. Every roll goes through the same re-gate and send-time checks below. An
    # operator /halt blocks them like everything else.
    rolls_only = False
    if is_halted():
        if get_halt_source() == "breaker":
            with session_scope() as _s:
                rolls_only = bool(
                    _s.query(OrderRow)
                    .filter(OrderRow.state == OrderState.QUEUED, _is_roll_order())
                    .count()
                )
        if not rolls_only:
            log.warning("Execution halted (kill switch engaged) — skipping order processing")
            return
        log.info("Circuit-breaker halt: processing queued roll orders only")

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
    with session_scope() as _s:
        cap_remaining = remaining_entry_allowance(_s)
    # Already halted (rolls-only pass): the breaker has nothing left to trip.
    reason = None if rolls_only else evaluate_breakers(positions, account_snap.net_liquidation)
    if reason is not None:
        set_halted(True, reason, source="breaker")
        log.critical("Circuit breaker tripped — %s. Execution halted.", reason)
        text = (
            f"🛑 Circuit breaker: execution HALTED — {reason}. New-entry scans are paused "
            "until you send /resume (profit-take and loss exits keep running; queued rolls "
            "still go through; /resume lets it run until the loss grows by another full step)."
        )
        # The main chat, and the scan thread where every skipped cycle now shows (2026-10-12:
        # the main-chat alert alone was missed and the scans stopped for the session).
        scan_thread = cfg.secrets.telegram_thread_scan
        for thread in [None, *([int(scan_thread)] if scan_thread else [])]:
            try:
                await bot.send_message(chat_id=chat_id, message_thread_id=thread, text=text)
            except Exception:
                log.exception("Failed to send circuit-breaker halt notification")
        return

    # The send-time sizing context is built here, before the write session below opens (like the
    # IBKR fetches above, it must not hold the SQLite write lock). If it cannot be built the
    # pass is skipped: the orders stay QUEUED and are retried, rather than being sent without
    # the regime's limits.
    try:
        sizing = await asyncio.to_thread(_send_context, now, positions)
    except Exception:
        log.exception("Could not build the send-time sizing context — skipping execution pass")
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
        queued_q = session.query(OrderRow).filter(OrderRow.state == OrderState.QUEUED)
        if rolls_only:
            queued_q = queued_q.filter(_is_roll_order())
        queued = queued_q.all()
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

        # --- Market regime: the order can only SHRINK between the card and now. ---
        # An escalated regime, a smaller budget or a used-up floor trims the order down to what
        # is allowed (a zero is left for the gate to refuse with the regime's reason).
        trim_notes: dict[int, str] = {}
        if sizing is not None:
            hard_max = hard_max_contracts()
            retrimmed: list[tuple[OrderRow, TradeCandidate]] = []
            for order_row, candidate in pending:
                candidate, trim_text = _trim_to_regime(
                    session, order_row, candidate, sizing, hard_max, account_snap, positions
                )
                if trim_text is not None:
                    trim_notes[order_row.id] = trim_text
                    notify_msgs.append(
                        f"Order {candidate.underlying} {candidate.strike:g}P {trim_text} before "
                        "sending."
                    )
                retrimmed.append((order_row, candidate))
            pending = retrimmed

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
        verdicts = validate_candidates(
            [c for _, c in ordered], account_snap, positions, sizing=sizing
        )
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
            # A roll is exempt: it swaps one short for another of the same size (2026-10-14).
            if (
                cap_remaining is not None
                and cap_remaining <= 0
                and candidate.strategy != Strategy.ROLL
            ):
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
            order_row.detail = "Queued for async execution" + (
                f" — {trim_notes[order_row.id]}" if order_row.id in trim_notes else ""
            )
            if candidate.strategy == Strategy.CASH_SECURED_PUT:
                # Tie the day's counterfactual rows for this card to the order that was sent.
                link_order(candidate.candidate_id, order_row.id, session=session)
                if candidate.sizing is not None and candidate.sizing.bottoming == "name":
                    # A lot opened above its zone on a name-level bottoming signal: recorded
                    # when SENT (a card nobody approved does not use up the name's turn), so a
                    # human can see whether these lots pay and the guard can count them.
                    record_action(
                        cand=candidate,
                        kind="bottoming_lot",
                        deterministic=candidate.contracts,
                        sent=candidate.contracts,
                        reason="lot opened on a name-level bottoming signal",
                        order_id=order_row.id,
                        session=session,
                    )
            to_execute.append((order_row.id, candidate))
            if cap_remaining is not None and candidate.strategy != Strategy.ROLL:
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
            await execute_candidate(ib, bot, chat_id, order_id, candidate, sizing=sizing)
        except Exception:
            log.exception("Execution error for order_id=%s", order_id)
            with session_scope() as session:
                row = session.get(OrderRow, order_id)
                if row and row.state not in (OrderState.FILLED, OrderState.PARTIAL):
                    row.state = OrderState.REJECTED
                    row.detail = "Execution exception"
