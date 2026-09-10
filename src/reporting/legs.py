"""The paired realised-P&L accounting rule — one implementation, moved out of the fenced reconciler.

Provenance: `fill_economics` and `classify_outcome` (formerly `_fill_economics` and `_classify`)
and `OPTION_MULTIPLIER` were **moved verbatim** from `src/claude/eval/reconcile.py` (P3-P4 M4
Task 4.1). They are pure functions with no LLM involvement; they sat behind the fence only
because the reconciler happens to live there. `reconcile.py` now imports them from this module —
do **not** "restore" a copy into `eval/`, and do not re-implement the arithmetic anywhere else.

This package is the third, read-only analytics tier: downstream of everything, upstream of
nothing. `src/reporting/` imports nothing from `src/claude/`, and `src/engine/`, `src/execution/`
and `src/strategies/` may never import `src.reporting` — both asserted in
`tests/test_web_fence.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.common.schemas import VerdictOutcome
from src.storage.models import ApprovalRow, FillRow, OrderRow

OPTION_MULTIPLIER = 100


@dataclass(frozen=True)
class FillEconomics:
    credit: float  # dollars, SELL fills × OPTION_MULTIPLIER
    debit: float  # dollars, BUY fills × OPTION_MULTIPLIER
    commissions: float  # nulls summed as zero
    commissions_complete: bool  # False when any fill carried a null commission
    entry_premium: float  # per share
    entry_qty: int


@dataclass(frozen=True)
class ClassifiedOutcome:
    outcome: VerdictOutcome
    realized_pnl: float | None
    filled: bool
    entry_premium: float | None
    contracts: int | None


def fill_economics(fills: list[FillRow]) -> FillEconomics:
    """Split fills into entry (SELL) and close (BUY) legs.

    Moved verbatim from src/claude/eval/reconcile.py::_fill_economics. The tuple return
    became a frozen dataclass; the arithmetic did not change.

    Returns (credit_dollars, debit_dollars, commissions, entry_premium_per_share,
    entry_qty), with the one addition of `commissions_complete` — new information the old
    tuple did not carry and which no existing caller reads. An empty fill list yields
    all-zero economics and `commissions_complete=True`: with no fills there were no
    commissions to miss.
    """
    credit = debit = commissions = 0.0
    entry_notional = 0.0  # Σ price*qty over SELL fills, for the qty-weighted entry premium
    entry_qty = 0
    commissions_complete = True
    for f in fills:
        if f.commission is None:
            commissions_complete = False
        commissions += f.commission or 0.0
        dollars = f.avg_price * f.filled_qty * OPTION_MULTIPLIER
        if (f.action or "SELL").upper() == "BUY":
            debit += dollars
        else:
            credit += dollars
            entry_notional += f.avg_price * f.filled_qty
            entry_qty += int(f.filled_qty)
    entry_premium = (entry_notional / entry_qty) if entry_qty else 0.0
    return FillEconomics(
        credit=credit,
        debit=debit,
        commissions=commissions,
        commissions_complete=commissions_complete,
        entry_premium=entry_premium,
        entry_qty=entry_qty,
    )


def classify_outcome(
    candidate_id: str,
    fills: list[FillRow],
    approval: ApprovalRow | None,
    order: OrderRow | None,
    expiry: date,
    today: date,
    assigned: bool,
) -> ClassifiedOutcome:
    """The outcome decision. Moved verbatim from reconcile.py::_classify.

    Behaviour is unchanged: reconcile.py's own test suite must pass without edits.

    `candidate_id` is accepted for signature parity with the reconciler's call site (the
    original `_classify` took it) even though the pure decision does not read it.

    Outcome decision (per candidate):

      has a SELL (entry) fill?
        ├─ yes → entry economics recorded; row is `filled`
        │        ├─ has a BUY (close) fill?  → CLOSED_EARLY,  realized = credit − debit − commissions
        │        ├─ else past expiry?
        │        │     ├─ flagged assigned   → ASSIGNED,      realized = premium kept (option leg)*
        │        │     └─ else               → EXPIRED_WORTHLESS, realized = premium kept
        │        └─ else                     → STILL_OPEN (just stamp fill economics)
        └─ no  → approval rejected?          → USER_REJECTED
                 order risk-rejected?        → RISK_REJECTED
                 approval expired / past expiry / order cancelled → NOT_FILLED
                 else                        → STILL_OPEN (await execution)

      *Assignment realizes additional stock-leg P&L that this option-leg ledger does not model;
       the realized figure for ASSIGNED is the premium kept and is flagged approximate. Whether
       a row is "assigned" is a caller decision (it needs position knowledge) passed in via the
       `assigned` flag; on its own this function treats every past-expiry short as
       expired-worthless, the common income-desk case.
    """
    sell_fills = [f for f in fills if (f.action or "SELL").upper() == "SELL"]
    buy_fills = [f for f in fills if (f.action or "SELL").upper() == "BUY"]

    if sell_fills:
        econ = fill_economics(fills)
        if buy_fills:
            realized = econ.credit - econ.debit - econ.commissions
            return ClassifiedOutcome(
                outcome=VerdictOutcome.CLOSED_EARLY,
                realized_pnl=realized,
                filled=True,
                entry_premium=econ.entry_premium,
                contracts=econ.entry_qty,
            )
        if today > expiry:
            realized = econ.credit - econ.commissions  # premium kept (option leg)
            outcome = VerdictOutcome.ASSIGNED if assigned else VerdictOutcome.EXPIRED_WORTHLESS
            return ClassifiedOutcome(
                outcome=outcome,
                realized_pnl=realized,
                filled=True,
                entry_premium=econ.entry_premium,
                contracts=econ.entry_qty,
            )
        # Filled and live, not yet expired — stamp economics, stay open.
        return ClassifiedOutcome(
            outcome=VerdictOutcome.STILL_OPEN,
            realized_pnl=None,
            filled=True,
            entry_premium=econ.entry_premium,
            contracts=econ.entry_qty,
        )

    # Never filled.
    if approval is not None and approval.status == "rejected":
        return ClassifiedOutcome(VerdictOutcome.USER_REJECTED, None, False, None, None)
    if order is not None and order.state == "rejected":
        return ClassifiedOutcome(VerdictOutcome.RISK_REJECTED, None, False, None, None)
    stale = (
        today > expiry
        or (order is not None and order.state == "cancelled")
        or (approval is not None and approval.status == "expired")
    )
    if stale:
        return ClassifiedOutcome(VerdictOutcome.NOT_FILLED, None, False, None, None)
    return ClassifiedOutcome(VerdictOutcome.STILL_OPEN, None, False, None, None)
