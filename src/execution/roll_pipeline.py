"""Turn a breached short into a roll decision and, for a roll, an approvable candidate.

``evaluate_roll`` (2026-10-11 roll redesign) is the one decision path for rolls, shared by the
intraday monitor (``handle_roll_trigger``) and the web console's ``roll_request`` drain handler:
targeted chain fetch (``market_data.get_roll_chain_quotes_async``) → roll-chain state →
``strategies.roll_policy.decide`` → a decision-time Rules Engine pass → a PENDING
``ApprovalRow`` with the frozen snapshot (N2a). The Telegram Approve handler then creates a
QUEUED ROLL ``OrderRow``, which ``process_queued_orders`` → ``execute_candidate`` routes to
``execute_roll`` (the two-leg BAG combo), where the roll is re-gated a third time on fresh
quotes. Nothing here places an order.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from ib_async import IB

from src.analytics.fundamentals import get_fundamental_stats
from src.analytics.iv import get_iv_stats
from src.analytics.technicals import get_technical_stats
from src.common.config import get_config
from src.common.market_hours import today_et
from src.common.schemas import (
    ApprovalStatus,
    OptionRight,
    OrderState,
    PositionSnapshot,
    RollDecision,
    TradeCandidate,
    Verdict,
)
from src.common.universe import effective_universe
from src.engine.risk_engine import validate_candidates
from src.ibkr.market_data import get_roll_chain_quotes_async
from src.ibkr.portfolio import get_account_snapshot_async, get_positions
from src.storage.campaigns import adjusted_cost_basis_for
from src.storage.db import session_scope
from src.storage.models import ApprovalRow, CandidateRow, OrderRow
from src.storage.orders import has_active_order
from src.storage.roll_chains import chain_state
from src.storage.system_settings import may_auto_roll
from src.strategies.roll_policy import decide
from src.strategies.rolling import RollContext

log = logging.getLogger(__name__)


def queue_roll_candidate(
    cand: TradeCandidate, *, chat_id: str, ttl_minutes: int, auto_approve: bool = False
) -> int | None:
    """Persist *cand* and raise an approval for it (frozen snapshot, N2a).

    PENDING (waits for the Approve tap) unless *auto_approve*, in which case the approval is
    written APPROVED with its QUEUED ``OrderRow`` in the same transaction — exactly what the
    Approve tap would have produced, and what the entry auto-queue writes on FULL autonomy
    (operator ruling 2026-10-14: "it should roll on full autonomy"). ``process_queued_orders``
    still re-gates it and ``execute_roll`` re-checks it on fresh quotes before anything is sent.

    None when an order is already working for the candidate. Never raises.
    """
    try:
        with session_scope() as s:
            if has_active_order(s, cand.candidate_id):
                log.info("roll: active order already exists for %s — skipping", cand.candidate_id)
                return None

            # Upsert the candidate payload (same semantics as the scan persister).
            existing = (
                s.query(CandidateRow).filter(CandidateRow.candidate_id == cand.candidate_id).first()
            )
            if existing is not None:
                s.delete(existing)
                s.flush()
            snapshot = cand.model_dump(mode="json")
            s.add(
                CandidateRow(
                    candidate_id=cand.candidate_id,
                    run_id=f"roll-{uuid.uuid4().hex[:8]}",
                    strategy=cand.strategy.value,
                    underlying=cand.underlying,
                    right=cand.right.value,
                    strike=cand.strike,
                    expiry=cand.expiry,
                    blended_score=cand.blended_score,
                    payload=snapshot,
                )
            )
            now = datetime.now(UTC)
            approval = ApprovalRow(
                candidate_id=cand.candidate_id,
                status=ApprovalStatus.APPROVED if auto_approve else ApprovalStatus.PENDING,
                chat_id=chat_id,
                decided_at=now if auto_approve else None,
                # Who decided: the system on FULL autonomy. Shown on the web, never read back.
                decided_by="system" if auto_approve else None,
                expires_at=now + timedelta(minutes=ttl_minutes),
                snapshot=snapshot,  # freeze the approved payload (N2a)
            )
            s.add(approval)
            s.flush()
            approval_id = approval.id
            if auto_approve:
                s.add(
                    OrderRow(
                        candidate_id=cand.candidate_id,
                        approval_id=approval_id,
                        state=OrderState.QUEUED,
                        snapshot=snapshot,
                        is_live=bool(get_config().is_live),
                    )
                )
        log.info(
            "roll: %s candidate %s (approval_id=%s)",
            "auto-approved and queued" if auto_approve else "queued for approval",
            cand.candidate_id,
            approval_id,
        )
        return approval_id
    except Exception:
        log.exception("roll: failed to queue roll candidate %s", cand.candidate_id)
        return None


# ---------------------------------------------------------------------------
# evaluate_roll (2026-10-11 roll redesign)
# ---------------------------------------------------------------------------


def _same_short(snapshot: dict | None, pos: PositionSnapshot) -> bool:
    """True when a frozen ROLL snapshot closes *pos* (by conId, else by contract)."""
    if not snapshot or snapshot.get("strategy") != "roll":
        return False
    origin = snapshot.get("roll_from") or {}
    if pos.con_id is not None and origin.get("con_id") is not None:
        return bool(origin["con_id"] == pos.con_id)
    return (
        snapshot.get("underlying") == (pos.underlying or pos.symbol)
        and origin.get("right") == (pos.right.value if pos.right else None)
        and abs(float(origin.get("strike") or 0.0) - (pos.strike or 0.0)) < 1e-3
        and origin.get("expiry") == (pos.expiry.isoformat() if pos.expiry else None)
    )


def pending_roll_approval_for(pos: PositionSnapshot) -> int | None:
    """Id of a PENDING roll approval — or the approval behind a working roll order — for *pos*.

    The monitor re-evaluates a breached short every ``roll.trigger.reevaluate_minutes``; this
    is what stops each re-evaluation from proposing the same roll again.
    """
    with session_scope() as s:
        pending = s.query(ApprovalRow).filter(ApprovalRow.status == ApprovalStatus.PENDING).all()
        for row in pending:
            if _same_short(row.snapshot, pos):
                return int(row.id)
        working = (
            s.query(OrderRow)
            .filter(
                OrderRow.state.in_([OrderState.QUEUED, OrderState.SUBMITTED, OrderState.PARTIAL])
            )
            .all()
        )
        for order in working:
            if _same_short(order.snapshot, pos):
                return int(order.approval_id) if order.approval_id is not None else -1
    return None


def roll_declined_today(pos: PositionSnapshot) -> bool:
    """True when a roll for *pos* was rejected or left to expire earlier this ET day.

    The monitor re-evaluates a breached short every 30 minutes; without this, a roll the
    operator rejected (or ignored past its TTL) came straight back with fresh buttons and a new
    Claude review up to ~13 times a day (whole-branch review, 2026-10-11). An explicit web
    ``roll_request`` (``manual=True``) is not held back by it.
    """
    from datetime import time as dtime
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    day_start = (
        datetime.combine(today_et(), dtime.min, tzinfo=et).astimezone(UTC).replace(tzinfo=None)
    )
    with session_scope() as s:
        rows = (
            s.query(ApprovalRow)
            .filter(
                ApprovalRow.status.in_([ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED]),
                ApprovalRow.created_at >= day_start - timedelta(days=1),
            )
            .all()
        )
        for row in rows:
            when = row.decided_at or row.created_at
            if when is not None and when >= day_start and _same_short(row.snapshot, pos):
                return True
    return False


def roll_failed_today(pos: PositionSnapshot) -> bool:
    """True when a roll order for *pos* was sent (or queued) today and did not fill.

    The loss line tries a roll before buying back; a roll that was cancelled, rejected or timed
    out must not be retried every cycle while the loss grows — the next pass closes instead.
    """
    from datetime import time as dtime
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    day_start = (
        datetime.combine(today_et(), dtime.min, tzinfo=et).astimezone(UTC).replace(tzinfo=None)
    )
    with session_scope() as s:
        rows = (
            s.query(OrderRow)
            .filter(
                OrderRow.state.in_([OrderState.CANCELLED, OrderState.REJECTED]),
                OrderRow.created_at >= day_start,
            )
            .all()
        )
        return any(_same_short(o.snapshot, pos) for o in rows)


def _gate_fallback(
    decision: RollDecision,
    pos: PositionSnapshot,
    cc_basis: float | None,
    reasons: list[str],
    *,
    on_no_roll: str = "policy",
) -> RollDecision:
    """The decision when the Rules Engine refuses a constructed roll: the no-roll branch."""
    reason = "rules_engine:" + ",".join(reasons)
    strike = pos.strike or 0.0
    if on_no_roll == "close":
        return RollDecision(
            action="close",
            reason=reason,
            rejections=decision.rejections,
            detail=f"Rules Engine refused the roll ({', '.join(reasons)}) — buying back at the "
            "loss line.",
        )
    if pos.right == OptionRight.PUT:
        action = "assign"
        detail = f"Rules Engine refused the roll ({', '.join(reasons)}) — letting it assign."
    elif cc_basis is None or strike >= cc_basis:
        action = "let_called_away"
        detail = f"Rules Engine refused the roll ({', '.join(reasons)}) — letting the shares go."
    else:
        action = "hold"
        detail = f"Rules Engine refused the roll ({', '.join(reasons)}) — holding below basis."
    return RollDecision(
        action=action,  # type: ignore[arg-type]
        reason=reason,
        rejections=decision.rejections,
        detail=detail,
    )


async def evaluate_roll(
    ib: IB,
    pos: PositionSnapshot,
    *,
    chat_id: str,
    ttl_minutes: int,
    manual: bool = False,
    on_no_roll: Literal["policy", "close"] = "policy",
) -> tuple[RollDecision, int | None]:
    """Decide what to do with one breached short; queue an approval when the answer is a roll.

    Targeted fetch (the alerted contract + a few same-or-better later strikes) → chain state,
    fundamentals and basis → ``roll_policy.decide`` → for a ``roll``, a decision-time Rules
    Engine pass (the first of three: this one, the approval-queue re-gate, and the executor's
    send-time check) → a PENDING approval. Returns the decision and the approval id (or the
    id of the roll already pending for this short). *manual* marks an operator-requested
    evaluation (web ``roll_request``) in the log; the policy is the same. *on_no_roll*
    ``"close"`` is the loss line's variant (``roll_policy.decide``): roll if one qualifies,
    otherwise close. On FULL autonomy with roll mode "auto" (``may_auto_roll``) a roll is approved and queued
    without a tap. Never raises.
    """
    underlying = pos.underlying or pos.symbol
    existing = pending_roll_approval_for(pos)
    if existing is not None:
        decision = RollDecision(
            action="defer",
            reason="roll_pending",
            detail="A roll for this short is already awaiting approval or working.",
        )
        return decision, existing

    if not manual and roll_declined_today(pos):
        decision = RollDecision(
            action="defer",
            reason="roll_declined_today",
            detail="A roll for this short was rejected or expired earlier today.",
        )
        _log_decision(pos, decision, manual)
        return decision, None

    cfg = get_config()
    rc = cfg.roll
    approval_id: int | None = None
    try:
        quotes = await get_roll_chain_quotes_async(
            ib,
            pos,
            max_expiries=rc.new_leg.max_expiries,
            target_dte_max=rc.new_leg.target_dte_max,
            strikes_outward=rc.new_leg.strikes_outward,
            batch_size=rc.new_leg.max_quote_lines,
        )
    except Exception:
        log.exception("roll: chain fetch failed for %s", underlying)
        quotes = []
    if not quotes:
        decision = RollDecision(
            action="defer",
            reason="chain_unavailable",
            detail="The roll chain fetch returned nothing — retrying next cycle.",
        )
        _log_decision(pos, decision, manual)
        return decision, None
    current = next(
        (
            q
            for q in quotes
            if q.right == pos.right
            and q.expiry == pos.expiry
            and abs(q.strike - (pos.strike or 0)) < 1e-3
        ),
        None,
    )
    if current is None:
        decision = RollDecision(
            action="defer",
            reason="current_unpriced",
            detail="No quote for the short itself — retrying next cycle.",
        )
        _log_decision(pos, decision, manual)
        return decision, None

    loop = asyncio.get_running_loop()
    iv_stats = await loop.run_in_executor(None, get_iv_stats, underlying, quotes)
    tech_stats = await loop.run_in_executor(None, get_technical_stats, underlying)
    fund = await loop.run_in_executor(None, get_fundamental_stats, underlying)
    positions = get_positions(ib)
    with session_scope() as s:
        chain = chain_state(s, pos)
    stock = next(
        (p for p in positions if p.sec_type == "STK" and (p.underlying or p.symbol) == underlying),
        None,
    )
    cc_basis = (
        (
            adjusted_cost_basis_for(underlying, shares_held=stock.position, avg_cost=stock.avg_cost)
            or stock.avg_cost
        )
        if stock
        else None
    )
    would_own = underlying.upper() in {
        str(x).upper() for x in (effective_universe().get("would_own") or [])
    }
    ctx = RollContext(
        position=pos,
        current=current,
        spot=current.underlying_price or tech_stats.price,
        chain=chain,
        closed_candidate_id=chain.current_candidate_id,
        next_earnings=fund.next_earnings,
        ex_div_date=fund.ex_dividend_date,
        dividend=fund.dividend_per_share,
        allow_debit=False,
        today=today_et(),
    )
    decision = decide(
        ctx,
        quotes,
        iv_stats,
        tech_stats,
        rc,
        would_own=would_own,
        cc_basis=cc_basis,
        on_no_roll=on_no_roll,
    )

    cand = decision.candidate
    if decision.action == "roll" and cand is not None:
        account = await get_account_snapshot_async(ib, cfg.secrets.ibkr_account)
        # Rolls are exempt from regime limits (spec section 5): sizing=None, on purpose.
        verdict = validate_candidates([cand], account, positions, sizing=None)[0]
        if verdict.verdict != Verdict.PASS:
            decision = _gate_fallback(
                decision, pos, cc_basis, list(verdict.reasons), on_no_roll=on_no_roll
            )
        else:
            approval_id = queue_roll_candidate(
                cand,
                chat_id=chat_id,
                ttl_minutes=ttl_minutes,
                auto_approve=may_auto_roll(underlying),
            )
    _log_decision(pos, decision, manual)
    return decision, approval_id


def _log_decision(pos: PositionSnapshot, decision: RollDecision, manual: bool) -> None:
    log.info(
        "roll decision: %s %s:%s%s rejections=%s",
        pos.symbol,
        decision.action,
        decision.reason,
        " (manual)" if manual else "",
        decision.rejections,
    )
