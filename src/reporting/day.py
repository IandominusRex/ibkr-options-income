"""The day's executed trades and the month's realised calendar - read-only (web Home follow-ups,
2026-10-15).

Both come from the same `PnlLeg` list every P&L surface reads, plus the book's spread rows the
API hands in as plain `SpreadDayInput` values (this module never touches the spreads package or
its file), so a card, the calendar and the month's pay stub cannot disagree. The value book's
fills arrive the same way, as plain `ValueDayInput` values built from data/value.db.

What it adds to those legs is the *why*, and every word of it is worked out from stored facts:
the close reason stamped on the buy-back fill, the roll policy's own decision log, and the share
of the premium kept. Claude's stored review (for an opened trade) and Claude's stored view of a
rolled position are passed through labelled as Claude's. Nothing here calls a model.

Imports nothing from the enrichment layer or the API package, and writes nothing.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.schemas import (
    CloseReason,
    DayCalendarDay,
    DayFact,
    DayReview,
    DayRolledTo,
    DayTrade,
    MonthCalendar,
    PnlLeg,
    VerdictOutcome,
)
from src.reporting.pay import PayStrategy, ValuePayInput, close_day, et_date, leg_kind
from src.storage.models import ApprovalRow, ClaudeReviewRow, FillRow, RollAlertRow

_ET = ZoneInfo("America/New_York")
_SessionFactory = Callable[[], Session]
DecidedBy = Literal["system", "web", "telegram"]
OPTION_MULTIPLIER = 100


@dataclass(frozen=True)
class SpreadDayInput:
    """One spread position, as the API reads it from data/spreads.db."""

    spread_id: str
    underlying: str
    side: Literal["put", "call"]
    expiry: date
    short_strike: float
    long_strike: float
    width: float
    contracts_opened: int
    contracts_open: int
    entry_credit: float  # per share
    entry_commission: float
    opened_at: datetime
    closed_at: datetime | None
    exit_debit: float | None  # per share, quantity-weighted
    exit_commission: float
    exit_reason: str | None
    status: str
    realized_pnl_usd: float | None
    is_live: bool = False


@dataclass(frozen=True)
class ValueDayInput:
    """One filled value-book order (Part 6, ruling 25), as the API reads it from data/value.db."""

    at: datetime  # naive UTC, as value.db stores it
    symbol: str
    side: Literal["buy", "sell"]
    shares: float
    price: float  # the fill's average price per share
    reason: str  # the proposal's reason code (tranche N, stop, claude_no, ...)
    cause: str  # python | claude
    proposal_id: int | None
    realised_usd: float | None = None  # a sale: proceeds less the average cost; None if unknown


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _day_window(day: date) -> tuple[datetime, datetime]:
    """The New York day as a naive-UTC [start, end), the way fills are stored."""
    start = datetime.combine(day, time.min, tzinfo=_ET).astimezone(UTC).replace(tzinfo=None)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=_ET)
    return start, end.astimezone(UTC).replace(tzinfo=None)


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _expiry_close(expiry: date) -> datetime:
    """An expiry or assignment settles at the New York close of its date."""
    return datetime.combine(expiry, time(16, 0), tzinfo=_ET).astimezone(UTC)


def _compact(symbol: str) -> str:
    return re.sub(r"\s+", "", symbol)


def _leg_symbol(leg: PnlLeg) -> str:
    return f"{leg.underlying}{leg.expiry:%y%m%d}{leg.right}{round(leg.strike * 1000):08d}"


def _money(v: float) -> str:
    """$235 for a whole number of dollars, else $2.35 (never $2.3)."""
    return f"${v:,.0f}" if abs(v - round(v)) < 1e-9 else f"${v:,.2f}"


def _per_share(total: float, contracts: int) -> float | None:
    return total / (OPTION_MULTIPLIER * contracts) if contracts > 0 else None


def _right_word(right: str) -> str:
    return "put" if right == "P" else "call"


def _kind_in_scope(kind: str | None, strategy: PayStrategy) -> bool:
    return kind is not None and (strategy == "all" or kind == strategy)


def _pct_kept(credit: float, debit: float) -> float | None:
    return (credit - debit) / credit * 100 if credit > 0 else None


def _annualised(roc_pct: float | None, dte: int | None) -> float | None:
    return roc_pct * 365 / dte if roc_pct is not None and dte is not None and dte > 0 else None


def _label(strike: float, right: str, expiry: date) -> str:
    return f"${strike:g} {_right_word(right)} expiring {expiry:%b} {expiry.day}"


# --------------------------------------------------------------------------- #
# Stored reasoning
# --------------------------------------------------------------------------- #


def _review(payload: dict[str, Any] | None) -> DayReview | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("evidence")
    return DayReview(
        why_attractive=str(payload.get("why_attractive", "")),
        risks=str(payload.get("risks", "")),
        tradeoffs=str(payload.get("tradeoffs", "")),
        assignment_considerations=str(payload.get("assignment_considerations", "")),
        rolling_considerations=str(payload.get("rolling_considerations", "")),
        recommendation=payload.get("recommendation"),
        priority=payload.get("priority"),
        confidence=payload.get("confidence"),
        summary=str(payload.get("summary") or ""),
        evidence=[str(e) for e in raw if e] if isinstance(raw, list) else [],
    )


@dataclass
class _Lookups:
    """Everything stored that the cards need, fetched once per call."""

    approval_by_candidate: dict[str, int]
    review_by_candidate: dict[str, DayReview]
    roll_close_fill: dict[str, FillRow]  # old leg candidate id -> today's roll buy-back fill
    roll_new_ids: dict[str, list[str]]  # roll order id -> candidate ids it sold
    decisions: dict[str, list[RollAlertRow]]  # underlying -> roll_decision rows, newest first
    claude_views: dict[str, list[RollAlertRow]]  # underlying -> alert rows with a Claude view
    decided_by: dict[int, DecidedBy]  # approval id -> who decided it


def _lookups(
    session: _SessionFactory,
    candidate_ids: set[str],
    day: date,
    underlyings: set[str],
) -> _Lookups:
    start, end = _day_window(day)
    with session() as sess:
        approvals: dict[str, int] = {}
        decided: dict[int, DecidedBy] = {}
        reviews: dict[str, DayReview] = {}
        if candidate_ids:
            for a in sess.execute(
                select(ApprovalRow)
                .where(ApprovalRow.candidate_id.in_(candidate_ids))
                .order_by(ApprovalRow.id)
            ).scalars():
                approvals[a.candidate_id] = a.id  # the newest wins
                if a.decided_by in ("system", "web", "telegram"):
                    decided[a.id] = cast(DecidedBy, a.decided_by)
            for r in sess.execute(
                select(ClaudeReviewRow)
                .where(ClaudeReviewRow.candidate_id.in_(candidate_ids))
                .order_by(ClaudeReviewRow.created_at, ClaudeReviewRow.id)
            ).scalars():
                parsed = _review(r.payload)
                if parsed is not None:
                    reviews[r.candidate_id] = parsed  # the newest wins

        roll_close: dict[str, FillRow] = {}
        for f in sess.execute(
            select(FillRow).where(
                FillRow.close_reason == CloseReason.ROLL.value,
                FillRow.filled_at >= start,
                FillRow.filled_at < end,
            )
        ).scalars():
            roll_close[f.candidate_id] = f
        order_ids = {f.order_id for f in roll_close.values()}
        new_ids: dict[str, list[str]] = defaultdict(list)
        if order_ids:
            for f in sess.execute(
                select(FillRow).where(FillRow.order_id.in_(order_ids), FillRow.action == "SELL")
            ).scalars():
                new_ids[str(f.order_id)].append(f.candidate_id)

        decisions: dict[str, list[RollAlertRow]] = defaultdict(list)
        views: dict[str, list[RollAlertRow]] = defaultdict(list)
        if underlyings:
            for row in sess.execute(
                select(RollAlertRow)
                .where(RollAlertRow.underlying.in_(underlyings))
                .order_by(RollAlertRow.created_at.desc(), RollAlertRow.id.desc())
            ).scalars():
                if row.trigger == "roll_decision":
                    decisions[row.underlying].append(row)
                elif row.claude_recommendation:
                    views[row.underlying].append(row)
    return _Lookups(approvals, reviews, roll_close, new_ids, decisions, views, decided)


def _decider(look: _Lookups, candidate_id: str | None) -> DecidedBy | None:
    """Who approved the trade a candidate opened; None when unrecorded or there is no approval."""
    approval_id = look.approval_by_candidate.get(candidate_id or "")
    return look.decided_by.get(approval_id) if approval_id is not None else None


def _trigger_label(code: str) -> str:
    if code == "loss_line":
        return "loss line"
    try:
        from src.monitor.triggers import humanize_trigger

        return humanize_trigger(code)
    except Exception:  # noqa: BLE001 - a label is never worth failing the card
        return code.replace("_", " ")


# --------------------------------------------------------------------------- #
# Wheel legs
# --------------------------------------------------------------------------- #

_CLOSE_RULE: dict[CloseReason, tuple[str, str]] = {
    CloseReason.PROFIT_TAKE: (
        "Closed for a profit: the position reached its profit target.",
        "The system buys a short back once enough of its premium is kept, rather than holding "
        "it to expiry for the last few dollars.",
    ),
    CloseReason.LOSS_EXIT: (
        "Closed at the loss limit.",
        "The cost to close reached the loss limit set for this kind of name, so the system "
        "bought it back instead of letting the loss grow.",
    ),
    CloseReason.DEFENSIVE: (
        "Closed defensively, on your tap.",
        "The roll policy found no roll worth taking on a breached short and offered Close; "
        "you chose it.",
    ),
    CloseReason.MANUAL: (
        "Closed outside the system.",
        "The position was bought back at the broker, not by this system. It was recorded when "
        "the account next reconciled.",
    ),
}


def _held_idea(leg: PnlLeg) -> str:
    shares = OPTION_MULTIPLIER * leg.contracts
    if leg.right == "P":
        return f"you bought {shares} shares at ${leg.strike:g}"
    return f"your {shares} shares were sold at ${leg.strike:g}"


def _result_line(leg: PnlLeg, closed_on: date | None) -> str:
    sold = _per_share(leg.credit, leg.contracts)
    bought = _per_share(leg.debit, leg.contracts)
    kept = _pct_kept(leg.credit, leg.debit)
    parts: list[str] = []
    if sold is not None:
        parts.append(f"Sold at {_money(sold)} a share")
    if bought is not None and leg.debit > 0:
        parts.append(f"bought back at {_money(bought)}")
    head = ", ".join(parts)
    if kept is None:
        tail = ""
    elif kept >= 0:
        tail = f"{kept:.0f}% of the premium kept before commissions"
    else:
        tail = f"the buy-back cost {abs(kept):.0f}% more than the premium collected"
    left = (leg.expiry - closed_on).days if closed_on is not None else None
    when = (
        f"{left} day{'' if left == 1 else 's'} before expiry"
        if left is not None and left > 0
        else ""
    )
    return ". ".join(x for x in (head, ", ".join(x for x in (tail, when) if x)) if x) + "."


def _closed_trade(
    leg: PnlLeg,
    kind: Literal["csp", "cc"],
    look: _Lookups,
    legs_by_id: dict[str, PnlLeg],
) -> DayTrade | None:
    closed_on = close_day(leg)
    if closed_on is None:
        return None
    kept = _pct_kept(leg.credit, leg.debit)
    base: dict[str, Any] = {
        "key": f"{leg.candidate_id}:closed",
        "kind": kind,
        "source": "wheel",
        "underlying": leg.underlying,
        "right": leg.right.value,
        "strike": leg.strike,
        "expiry": leg.expiry,
        "contracts": leg.contracts,
        "is_live": leg.is_live,
        "premium": leg.credit,
        "bought_back": leg.debit,
        "commissions": leg.commissions,
        "commissions_complete": leg.commissions_complete,
        "net_pnl": leg.net_pnl,
        "pct_kept": kept,
        "days_held": leg.days_held,
        "roc_pct": leg.roc_pct,
        "annualized_pct": leg.annualized_pct,
        "capital": leg.strike * OPTION_MULTIPLIER * leg.contracts if leg.strike > 0 else None,
        "approval_id": look.approval_by_candidate.get(leg.candidate_id),
    }
    if leg.outcome == VerdictOutcome.EXPIRED_WORTHLESS:
        return DayTrade(
            **base,
            action="closed",
            how="expired",
            at=_expiry_close(leg.expiry),
            reason="Expired worthless: you kept the whole premium.",
            facts=[
                DayFact(
                    label="Result",
                    text=f"Sold at {_money(_per_share(leg.credit, leg.contracts) or 0.0)} a share. "
                    "Nothing to buy back, so all of it is kept before commissions.",
                ),
            ],
        )
    if leg.outcome == VerdictOutcome.ASSIGNED:
        called = leg.right.value == "C"
        per_share = _per_share(leg.credit, leg.contracts) or 0.0
        result = DayFact(
            label="Result",
            text=f"{_held_idea(leg).capitalize()}. You also kept the "
            f"{_money(per_share)} a share premium"
            + (
                f", so your adjusted cost on those shares is {_money(leg.strike - per_share)}."
                if not called
                else "."
            ),
        )
        return DayTrade(
            **base,
            action="closed",
            how="called_away" if called else "assigned",
            at=_expiry_close(leg.expiry),
            reason=("Called away: " if called else "Assigned: ") + _held_idea(leg) + ".",
            facts=[result],
        )
    if leg.outcome != VerdictOutcome.CLOSED_EARLY or leg.closed_at is None:
        return None

    if leg.close_reason == CloseReason.ROLL:
        return _rolled_trade(leg, base, look, legs_by_id)

    headline, rule_text = (
        _CLOSE_RULE.get(leg.close_reason) if leg.close_reason is not None else None
    ) or ("Bought back; the reason was not recorded.", "This close predates the reason stamp.")
    return DayTrade(
        **base,
        action="closed",
        how="bought_back",
        at=_utc(leg.closed_at),
        reason=headline,
        facts=[
            DayFact(label="Rule", text=rule_text),
            DayFact(label="Result", text=_result_line(leg, closed_on)),
        ],
    )


def _decision_for(
    leg: PnlLeg, new_cid: str | None, look: _Lookups
) -> tuple[dict[str, Any] | None, str | None]:
    """The roll policy's logged decision for this position, and the trigger behind it.

    Matched first on the roll approval id the decision recorded (exact), else the newest
    decision logged for this contract before the buy-back (the position's symbol)."""
    rows = look.decisions.get(leg.underlying, [])
    want_approval = look.approval_by_candidate.get(new_cid) if new_cid else None
    symbol = _leg_symbol(leg)
    closed_at = _utc(leg.closed_at) if leg.closed_at else None
    fallback: RollAlertRow | None = None
    for row in rows:
        payload = row.payload or {}
        if want_approval is not None and payload.get("approval_id") == want_approval:
            return payload.get("decision"), payload.get("trigger")
        if fallback is None and _compact(row.position_symbol) == symbol:
            if closed_at is None or _utc(row.created_at) <= closed_at:
                fallback = row
    if fallback is not None:
        payload = fallback.payload or {}
        return payload.get("decision"), payload.get("trigger")
    return None, None


def _rolled_trade(
    leg: PnlLeg,
    base: dict[str, Any],
    look: _Lookups,
    legs_by_id: dict[str, PnlLeg],
) -> DayTrade:
    assert leg.closed_at is not None
    fill = look.roll_close_fill.get(leg.candidate_id)
    sold = look.roll_new_ids.get(str(fill.order_id), []) if fill is not None else []
    new_cid = next((c for c in sold if c != leg.candidate_id), None)
    new_leg = legs_by_id.get(new_cid) if new_cid else None
    rolled_to = (
        DayRolledTo(
            candidate_id=new_leg.candidate_id,
            strike=new_leg.strike,
            expiry=new_leg.expiry,
            contracts=new_leg.contracts,
            premium=new_leg.credit,
            commissions=new_leg.open_commissions
            if new_leg.open_commissions is not None
            else new_leg.commissions,
        )
        if new_leg is not None
        else None
    )

    facts: list[DayFact] = []
    decision, trigger = _decision_for(leg, new_cid, look)
    if decision is not None:
        why = str(decision.get("detail") or "").strip()
        label = _trigger_label(trigger) if trigger else None
        text = (f"Trigger: {label}. " if label else "") + (why or "The roll policy chose to roll.")
        facts.append(DayFact(label="Why it was rolled", text=text))
    else:
        facts.append(
            DayFact(
                label="Why it was rolled",
                text="The roll policy's log for this position was not found, so the trigger "
                "is not shown.",
            )
        )

    old_ps = _per_share(leg.debit, leg.contracts)
    old_sold_ps = _per_share(leg.credit, leg.contracts)
    if rolled_to is not None and old_ps is not None:
        new_ps = _per_share(rolled_to.premium or 0.0, rolled_to.contracts)
        terms = (
            f"Bought back the ${leg.strike:g} {_right_word(leg.right.value)} at {_money(old_ps)} a "
            f"share and sold the {_label(rolled_to.strike, leg.right.value, rolled_to.expiry)}"
        )
        if new_ps is not None:
            net = new_ps - old_ps
            terms += f" at {_money(new_ps)}: a net {'credit' if net >= 0 else 'debit'} of "
            terms += f"{_money(abs(net))} a share."
        else:
            terms += "."
        facts.append(DayFact(label="Roll terms", text=terms))
    elif old_ps is not None:
        facts.append(
            DayFact(
                label="Roll terms",
                text=f"Bought back at {_money(old_ps)} a share. The new leg is not on record yet.",
            )
        )
    if old_sold_ps is not None:
        facts.append(
            DayFact(
                label="This leg",
                text=f"Originally sold at {_money(old_sold_ps)} a share; the realised result "
                "below is for this leg only, the new one is still open.",
            )
        )
    view = next(
        (
            r
            for r in look.claude_views.get(leg.underlying, [])
            if _compact(r.position_symbol) == _leg_symbol(leg)
            and _utc(r.created_at) <= _utc(leg.closed_at)
        ),
        None,
    )
    if view is not None and view.claude_recommendation:
        facts.append(
            DayFact(
                label="Claude's view",
                text=f"Recommended: {view.claude_recommendation}.",
                source="claude",
            )
        )

    reason = (
        f"Rolled to the {_label(rolled_to.strike, leg.right.value, rolled_to.expiry)}."
        if rolled_to is not None
        else f"Rolled; the new leg is not on record. Bought back at {_money(old_ps or 0)} a share."
    )
    base = {
        **base,
        "key": f"{leg.candidate_id}:rolled",
        "approval_id": look.approval_by_candidate.get(new_cid or "")
        or look.approval_by_candidate.get(leg.candidate_id),
        # Only the roll's own approval; never the old leg's, which approval_id falls back to.
        "decided_by": _decider(look, new_cid),
    }
    return DayTrade(
        **base,
        action="rolled",
        how="rolled",
        at=_utc(leg.closed_at),
        reason=reason,
        facts=facts,
        rolled_to=rolled_to,
    )


def _opened_trade(leg: PnlLeg, kind: Literal["csp", "cc"], look: _Lookups) -> DayTrade:
    capital = leg.strike * OPTION_MULTIPLIER * leg.contracts if leg.strike > 0 else None
    opened_on = et_date(leg.opened_at)
    dte = (leg.expiry - opened_on).days if opened_on is not None else None
    open_commission = leg.open_commissions if leg.open_commissions is not None else leg.commissions
    roc = leg.credit / capital * 100 if capital else None
    return DayTrade(
        key=f"{leg.candidate_id}:opened",
        action="opened",
        kind=kind,
        source="wheel",
        underlying=leg.underlying,
        right=leg.right.value,
        strike=leg.strike,
        expiry=leg.expiry,
        contracts=leg.contracts,
        at=_utc(leg.opened_at),
        is_live=leg.is_live,
        premium=leg.credit,
        commissions=open_commission,
        commissions_complete=leg.commissions_complete,
        capital=capital,
        roc_pct=roc,
        annualized_pct=_annualised(roc, dte),
        dte_at_open=dte,
        approval_id=look.approval_by_candidate.get(leg.candidate_id),
        decided_by=_decider(look, leg.candidate_id),
        review=look.review_by_candidate.get(leg.candidate_id),
    )


def _approval_kind(snapshot: Any) -> Literal["csp", "cc"] | None:
    """The side of the book a proposal's snapshot is on, as leg_kind does for a leg."""
    if not isinstance(snapshot, dict):
        return None
    s, r = snapshot.get("strategy"), snapshot.get("right")
    if s == "cash_secured_put" or (s == "roll" and r == "P"):
        return "csp"
    if s == "covered_call" or (s == "roll" and r == "C"):
        return "cc"
    return None


def activity_days(
    session: _SessionFactory, legs: Iterable[PnlLeg], *, strategy: PayStrategy
) -> set[date]:
    """New York days with a wheel trade (opened, closed, rolled) or a wheel proposal raised, in
    the strategy's scope: History's previous and next day. Spreads are not counted; the spreads
    view navigates over GET /spreads/picks."""
    days: set[date] = set()
    for leg in legs:
        if not _kind_in_scope(leg_kind(leg), strategy):
            continue
        for d in (et_date(leg.opened_at), close_day(leg)):
            if d is not None:
                days.add(d)
    with session() as sess:
        for created_at, snapshot in sess.execute(
            select(ApprovalRow.created_at, ApprovalRow.snapshot)
        ):
            d = et_date(created_at)
            if d is not None and _kind_in_scope(_approval_kind(snapshot), strategy):
                days.add(d)
    return days


# --------------------------------------------------------------------------- #
# Spreads
# --------------------------------------------------------------------------- #

_SPREAD_EXIT: dict[str, tuple[str, str]] = {
    "expire_worthless": ("Expired worthless: you kept the whole credit.", "Settled at expiry."),
    "expired_itm": (
        "Expired in the money and settled for its intrinsic value.",
        "The spread was left to expire and finished past the short strike.",
    ),
    "time_stop": (
        "Closed by the time stop.",
        "Every spread is closed shortly before the session ends, because SPY settles in shares.",
    ),
    "stop_loss": (
        "Closed at the stop loss.",
        "The cost to close reached the stop multiple of the credit received.",
    ),
    "profit_take": (
        "Closed for a profit: the target was reached.",
        "The cost to close fell to the profit-take share of the credit received.",
    ),
    "strike_touch": (
        "Closed when SPY touched the short strike.",
        "The spread is closed as soon as the underlying reaches the short strike.",
    ),
    "max_hold": (
        "Closed at the maximum hold time.",
        "The spread had been open for the longest time the book allows.",
    ),
}


def _spread_economics(s: SpreadDayInput) -> tuple[float, float | None, float | None]:
    """(premium USD, max loss USD, ROC percent) of the contracts opened."""
    premium = s.entry_credit * OPTION_MULTIPLIER * s.contracts_opened
    risk = (s.width - s.entry_credit) * OPTION_MULTIPLIER * s.contracts_opened
    return premium, (risk if risk > 0 else None), (premium / risk * 100 if risk > 0 else None)


def _spread_trade_base(s: SpreadDayInput) -> dict[str, Any]:
    premium, risk, roc = _spread_economics(s)
    opened_on = et_date(s.opened_at)
    dte = (s.expiry - opened_on).days if opened_on is not None else None
    return {
        "kind": "spread",
        "source": "spreads",
        "underlying": s.underlying,
        "right": "P" if s.side == "put" else "C",
        "strike": s.short_strike,
        "long_strike": s.long_strike,
        "expiry": s.expiry,
        "contracts": s.contracts_opened,
        "is_live": s.is_live,
        "premium": premium,
        "capital": risk,
        "roc_pct": roc,
        "annualized_pct": _annualised(roc, dte),
        "dte_at_open": dte,
    }


def _spread_net(s: SpreadDayInput) -> float | None:
    if s.realized_pnl_usd is not None:
        return s.realized_pnl_usd
    if s.exit_debit is None:
        return None
    gross = (s.entry_credit - s.exit_debit) * OPTION_MULTIPLIER * s.contracts_opened
    return gross - s.entry_commission - s.exit_commission


def _spread_closed(s: SpreadDayInput) -> DayTrade | None:
    if s.closed_at is None or s.status != "closed":
        return None
    base = _spread_trade_base(s)
    debit = (s.exit_debit or 0.0) * OPTION_MULTIPLIER * s.contracts_opened
    kept = _pct_kept(base["premium"], debit)
    reason, rule = _SPREAD_EXIT.get(
        s.exit_reason or "",
        (
            "Closed." if not s.exit_reason else f"Closed ({s.exit_reason.replace('_', ' ')}).",
            "The exit reason is not one this card knows how to explain.",
        ),
    )
    expired = s.exit_reason in ("expire_worthless", "expired_itm")
    return DayTrade(
        **base,
        key=f"spread:{s.spread_id}:closed",
        action="closed",
        how="expired" if expired else "bought_back",
        at=_utc(s.closed_at),
        bought_back=debit,
        commissions=s.entry_commission + s.exit_commission,
        net_pnl=_spread_net(s),
        pct_kept=kept,
        days_held=max(
            (et_date(s.closed_at) or s.expiry) - (et_date(s.opened_at) or s.expiry), timedelta(0)
        ).days,
        reason=reason,
        facts=[
            DayFact(label="Rule", text=rule),
            DayFact(
                label="Result",
                text=(
                    f"Sold for {_money(s.entry_credit)} a share"
                    + (
                        f", closed at {_money(s.exit_debit)}: "
                        f"{kept:.0f}% of the credit kept before commissions."
                        if s.exit_debit is not None and kept is not None
                        else "."
                    )
                ),
            ),
        ],
    )


def _spread_opened(s: SpreadDayInput) -> DayTrade:
    return DayTrade(
        **_spread_trade_base(s),
        key=f"spread:{s.spread_id}:opened",
        action="opened",
        at=_utc(s.opened_at),
        commissions=s.entry_commission,
    )


# --------------------------------------------------------------------------- #
# The value book
# --------------------------------------------------------------------------- #

_VALUE_WORDS = {
    "arm": "the trailing stop armed",
    "half": "the price reached fair value: sold half, tightened the stop on the rest",
    "stop": "the stop was hit",
    "trail": "the trailing stop was hit",
    "peak": "the peak signal fired",
    "thesis": "a thesis exit fired",
    "remark": "fair value was re-marked",
    "remark_below": "fair value fell below the price",
    "catastrophe": "the catastrophe stop was hit",
    "time": "the holding period ended",
    "shock": "a shock stop fired",
    "drawdown_trim": "the book's drawdown passed its trim line: trimmed to half",
    "claude_broken": "Claude's review of the held name returned BROKEN",
    "claude_no": "Claude's verdict on the name turned NO",
}


def _value_words(code: str, side: str) -> str:
    if code.startswith("tranche "):
        return f"scaling in, {code}"
    return _VALUE_WORDS.get(code, code.replace("_", " ") or ("bought" if side == "buy" else "sold"))


def _value_trade(v: ValueDayInput) -> DayTrade:
    words = _value_words(v.reason, v.side)
    shares = int(round(v.shares))
    facts = [DayFact(label="Rule", text=f"{words[:1].upper()}{words[1:]}.")]
    if v.cause == "claude":
        facts.append(
            DayFact(
                label="Claude's call",
                text=(
                    "Claude's value work called for this sale; it waited for your tap."
                    if v.side == "sell"
                    else "Claude's value work called for this buy; Python's gates still applied."
                ),
                source="claude",
            )
        )
    day = et_date(v.at) or _utc(v.at).date()
    verb = "Bought" if v.side == "buy" else "Sold"
    return DayTrade(
        key=f"value:{v.proposal_id or 0}:{v.side}:{_utc(v.at):%Y%m%dT%H%M%S}",
        action="opened" if v.side == "buy" else "closed",
        kind="value",
        source="value",
        underlying=v.symbol,
        strike=v.price,
        expiry=day,
        contracts=shares,
        at=_utc(v.at),
        capital=v.shares * v.price if v.side == "buy" else None,
        net_pnl=v.realised_usd if v.side == "sell" else None,
        reason=f"{verb} {shares} {v.symbol} at {_money(v.price)}: {words}.",
        facts=facts,
    )


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def build_day_trades(
    session: _SessionFactory,
    legs: Iterable[PnlLeg],
    spreads: Iterable[SpreadDayInput],
    values: Iterable[ValueDayInput] = (),
    *,
    day: date,
    strategy: PayStrategy,
) -> list[DayTrade]:
    """Every trade opened, closed or rolled on the New York `day`, newest first.

    A roll is one card: the buy-back leg and the new short it opened share one combo order, so
    they are paired on that order id and the new leg is not repeated under Opened. An expiry or
    assignment on `day` is listed as Closed (it is not an execution, but the position leaves the
    book and would otherwise vanish without a trace).
    """
    all_legs = list(legs)
    legs_by_id = {leg.candidate_id: leg for leg in all_legs}
    scoped: list[tuple[PnlLeg, Literal["csp", "cc"]]] = []
    for leg in all_legs:
        kind = leg_kind(leg)
        if kind is not None and _kind_in_scope(kind, strategy):
            scoped.append((leg, kind))
    todays = [leg for leg, _ in scoped if et_date(leg.opened_at) == day or close_day(leg) == day]
    look = _lookups(
        session,
        {leg.candidate_id for leg in todays},
        day,
        {leg.underlying for leg in todays},
    )
    # Pair first, so a roll's new leg can be told from an ordinary opening.
    rolled_in: set[str] = set()
    for fill in look.roll_close_fill.values():
        rolled_in.update(look.roll_new_ids.get(str(fill.order_id), []))
        rolled_in.discard(fill.candidate_id)

    out: list[DayTrade] = []
    for leg, kind in scoped:
        if et_date(leg.opened_at) == day and leg.candidate_id not in rolled_in:
            out.append(_opened_trade(leg, kind, look))
        if close_day(leg) == day:
            closed = _closed_trade(leg, kind, look, legs_by_id)
            if closed is not None:
                out.append(closed)
    if strategy in ("all", "spread"):
        for s in spreads:
            if et_date(s.opened_at) == day:
                out.append(_spread_opened(s))
            if s.closed_at is not None and et_date(s.closed_at) == day:
                closed_spread = _spread_closed(s)
                if closed_spread is not None:
                    out.append(closed_spread)
    if strategy in ("all", "value"):
        out.extend(_value_trade(v) for v in values if et_date(v.at) == day)
    out.sort(key=lambda t: t.at, reverse=True)
    return out


def build_month_calendar(
    legs: Iterable[PnlLeg],
    spreads: Iterable[SpreadDayInput],
    values: Iterable[ValuePayInput] = (),
    *,
    month: date,
    strategy: PayStrategy,
) -> MonthCalendar:
    """Each New York day's realised P&L in the month: the net result, after every commission,
    of the legs and spreads that closed that day. A day nothing closed has no entry. An open
    leg has a mark, not a result, and contributes nothing (its net is None, never 0)."""
    first = month.replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    totals: dict[date, float] = defaultdict(float)
    counts: dict[date, int] = defaultdict(int)
    incomplete: set[date] = set()

    for leg in legs:
        if not _kind_in_scope(leg_kind(leg), strategy):
            continue
        d = close_day(leg)
        if d is None or not first <= d < nxt or leg.net_pnl is None:
            continue
        totals[d] += leg.net_pnl
        counts[d] += 1
        if not leg.commissions_complete:
            incomplete.add(d)
    if strategy in ("all", "spread"):
        for s in spreads:
            d = et_date(s.closed_at)
            net = _spread_net(s) if s.status == "closed" else None
            if d is None or net is None or not first <= d < nxt:
                continue
            totals[d] += net
            counts[d] += 1
    if strategy in ("all", "value"):
        for v in values:
            d = et_date(v.closed_at)
            if d is None or not first <= d < nxt:
                continue
            totals[d] += v.realised_usd - (v.commissions_usd or 0.0)
            counts[d] += 1
            if v.commissions_usd is None:
                incomplete.add(d)

    days = [
        DayCalendarDay(date=d, realized=totals[d], n_closed=counts[d], complete=d not in incomplete)
        for d in sorted(totals)
    ]
    return MonthCalendar(
        month=first,
        strategy=strategy,
        days=days,
        total=sum(totals.values()),
        n_closed=sum(counts.values()),
        complete=not incomplete,
    )


def build_position_story(
    session: _SessionFactory,
    legs: Iterable[PnlLeg],
    *,
    underlying: str,
    right: str,
    strike: float,
    expiry: date,
) -> tuple[DayTrade | None, DayTrade | None]:
    """One contract's initial trade and how it ended: (opened, closed or rolled).

    The same cards as the day's list, for the position page: the opening with its premium,
    commission, return and Claude's stored review; and, once the contract is no longer held, the
    close, expiry, assignment or roll with its reason. When the same contract was sold more than
    once, the open leg wins, else the most recent. (None, None) when the system has no fills for
    it (a position opened outside the system)."""
    all_legs = list(legs)
    matches = [
        leg
        for leg in all_legs
        if leg.underlying == underlying
        and leg.right.value == right
        and leg.strike == strike
        and leg.expiry == expiry
        and leg_kind(leg) is not None
    ]
    if not matches:
        return None, None
    leg = next((m for m in matches if m.outcome == VerdictOutcome.STILL_OPEN), None) or max(
        matches, key=lambda m: m.opened_at
    )
    kind = leg_kind(leg)
    assert kind is not None
    closed_on = close_day(leg)
    look = _lookups(
        session,
        {m.candidate_id for m in all_legs if m.underlying == underlying},
        closed_on or et_date(leg.opened_at) or leg.expiry,
        {underlying},
    )
    legs_by_id = {m.candidate_id: m for m in all_legs}
    return _opened_trade(leg, kind, look), _closed_trade(leg, kind, look, legs_by_id)


def build_spread_story(spread: SpreadDayInput) -> tuple[DayTrade, DayTrade | None]:
    """A spread's opening card and, once it is closed, its closing card."""
    return _spread_opened(spread), _spread_closed(spread)
