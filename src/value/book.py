"""The value book's held positions, proposals and share reconcile (spec §7, §9.2, §9.5; revision 4).

Writes value.db only. Pure arithmetic lives in ``sizing.py``, ``risk.py`` and ``exits.py``; this
module turns them into rows:

- ``totals``: what the book holds and is buying, from ``value_orders`` (the V of spec §9.2);
- ``reconcile``: broker = wheel (W) + value (V filled) per shared name; unexplained shares are
  ``pending`` for ``attribution_grace_hours`` (the ledger's own lag), then ``frozen`` until a human
  clears them; a freeze stops both books opening on the name (the gate and the Rules Engine read it);
- ``step_held``: each night, each open position's live-policy plan (``rules.exits.live_policy``,
  ``value``) on tonight's bar and Python's numbers; a sale it signals becomes a sell proposal.
  Every sale that sends without a tap reads Python's fair value; one only Claude's value (or
  Claude's review, or its NO) would make is a proposal that **always waits for a tap**;
- ``propose``: a buy or sell proposal, approved at once when the autonomy ladder allows (buys:
  ``may_auto_open``; Python's sells: ``automation.auto_close_enabled``), else pending a tap.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.config import ValueCfg
from src.common.value_types import DayBar
from src.value.exits import DayFacts, LegState, open_leg, step
from src.value.store import (
    ValueAttributionRow,
    ValueBookStateRow,
    ValueFundingRow,
    ValueOrderRow,
    ValuePositionRow,
    ValueProposalRow,
)

WORKING = ("pending", "submitted", "partial")
PYTHON_SELLS = ("stop", "trail", "peak", "thesis", "remark_below", "catastrophe", "time")
TRIM_TTL_HOURS = 30.0  # a trim's approved sells: the same horizon as a funding request
# the drawdown trim's episode in the high_water state (Part 6, ruling 11); a reset drops them
TRIM_STATE_KEYS = ("trim_offered_at", "episode", "trimmed", "trimmed_at")


class BookRefused(Exception):
    """A book action that cannot apply, with a machine reason (``commands`` maps it to a failed
    command; ``book`` never imports ``commands``)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class NameTotals:
    filled: float = 0.0
    cost: float = 0.0  # filled shares at their average cost
    working_buy_cost: float = 0.0
    list_name: str = ""


@dataclass
class BookTotals:
    names: dict[str, NameTotals] = field(default_factory=dict)

    @property
    def cost(self) -> float:
        return sum(n.cost + n.working_buy_cost for n in self.names.values())

    def list_cost(self, list_name: str) -> float:
        return sum(
            n.cost + n.working_buy_cost for n in self.names.values() if n.list_name == list_name
        )

    @property
    def positions_open(self) -> int:
        return sum(1 for n in self.names.values() if n.filled > 0 or n.working_buy_cost > 0)


def totals(vs: Session) -> BookTotals:
    out = BookTotals()
    bought: dict[str, tuple[float, float]] = {}
    for o in vs.scalars(select(ValueOrderRow)):
        n = out.names.setdefault(o.symbol, NameTotals(list_name=o.list_name))
        if o.side == "buy":
            q, c = bought.get(o.symbol, (0.0, 0.0))
            bought[o.symbol] = (q + o.filled, c + o.filled * (o.avg_price or 0.0))
            n.filled += o.filled
            if o.status in WORKING:
                n.working_buy_cost += (o.shares - o.filled) * (o.limit_price or 0.0)
        else:
            n.filled -= o.filled
    for symbol, n in out.names.items():
        q, c = bought.get(symbol, (0.0, 0.0))
        n.filled = max(0.0, n.filled)
        n.cost = n.filled * (c / q) if q else 0.0
    return out


def get_state(vs: Session, key: str) -> dict | None:
    row = vs.get(ValueBookStateRow, key)
    return None if row is None else json.loads(row.value)


def set_state(vs: Session, key: str, value: dict, now: datetime) -> None:
    row = vs.get(ValueBookStateRow, key)
    blob = json.dumps(value, sort_keys=True, default=str)
    if row is None:
        vs.add(ValueBookStateRow(key=key, value=blob, updated_at=now))
    else:
        row.value, row.updated_at = blob, now


def reset_drawdown(state: dict) -> dict:
    """``--reset-drawdown`` (spec §9.6: a human resets the breaker): the high becomes today's
    value, the stop lifts and the trim episode ends, so a later 25% drawdown is offered afresh."""
    kept = {k: v for k, v in state.items() if k not in TRIM_STATE_KEYS}
    return {**kept, "stop": False, "high": state.get("value", 0)}


def reconcile(
    vs: Session,
    broker: dict[str, float],
    wheel: dict[str, float],
    marks: dict[str, float],
    *,
    now: datetime,
    grace_hours: float,
) -> list[str]:
    """Spec §9.2's reconcile, for every name the value book holds or has an attribution row
    for. Returns the names that froze now (for the alert)."""
    t = totals(vs)
    names = {s for s, n in t.names.items() if n.filled > 0 or n.working_buy_cost > 0}
    names |= set(vs.scalars(select(ValueAttributionRow.symbol)))
    frozen_now: list[str] = []
    for symbol in sorted(names):
        n = t.names.get(symbol, NameTotals())
        pending = sum(
            o.shares - o.filled
            for o in vs.scalars(
                select(ValueOrderRow).where(
                    ValueOrderRow.symbol == symbol,
                    ValueOrderRow.side == "buy",
                    ValueOrderRow.status.in_(WORKING),
                )
            )
        )
        b, w = broker.get(symbol, 0.0), wheel.get(symbol, 0.0)
        unexplained = abs(b - (w + n.filled)) > 1e-6
        row = vs.get(ValueAttributionRow, symbol)
        if row is None:
            row = ValueAttributionRow(
                symbol=symbol, broker=b, wheel=w, value_filled=n.filled, updated_at=now
            )
            vs.add(row)
        row.broker, row.wheel, row.value_filled, row.value_pending = b, w, n.filled, pending
        row.mark, row.updated_at = marks.get(symbol, row.mark), now
        if not unexplained:
            if row.state != "frozen":
                row.state, row.since, row.detail = "ok", None, ""
            continue
        row.detail = f"broker {b:g} != wheel {w:g} + value {n.filled:g}"
        if row.state == "ok":
            row.state, row.since = "pending", now
        elif row.state == "pending" and row.since is not None:
            if now - row.since >= timedelta(hours=grace_hours):
                row.state = "frozen"
                frozen_now.append(symbol)
    return frozen_now


def clear_attribution(vs: Session, symbol: str, now: datetime) -> bool:
    """A human clears a freeze (spec §9.2). The next reconcile re-checks the name."""
    row = vs.get(ValueAttributionRow, symbol.upper())
    if row is None or row.state == "ok":
        return False
    row.state, row.since, row.cleared_at = "ok", None, now
    return True


def propose(
    vs: Session,
    *,
    kind: str,
    symbol: str,
    list_name: str,
    shares: float,
    price: float | None,
    reason: str,
    cause: str,
    auto: bool,
    now: datetime,
    ttl_hours: float,
    tranche: int | None = None,
    position_id: int | None = None,
    gate: list[str] | None = None,
) -> ValueProposalRow | None:
    """One proposal, unless the same name already has one open of the same kind. A Claude-caused
    sale is never auto (spec §7)."""
    open_ = vs.scalars(
        select(ValueProposalRow).where(
            ValueProposalRow.symbol == symbol,
            ValueProposalRow.kind == kind,
            ValueProposalRow.status.in_(("pending", "approved", "funding", "sent")),
        )
    ).first()
    if open_ is not None:
        return None
    auto = auto and not (kind == "sell" and cause == "claude")
    row = ValueProposalRow(
        kind=kind,
        symbol=symbol,
        list_name=list_name,
        shares=shares,
        price=price,
        cost_usd=shares * price if kind == "buy" and price else 0.0,
        tranche=tranche,
        position_id=position_id,
        reason=reason,
        cause=cause,
        needs_tap=not auto,
        status="approved" if auto else "pending",
        gate_json=json.dumps(gate or []),
        created_at=now,
        expires_at=now + timedelta(hours=ttl_hours),
        decided_at=now if auto else None,
        decided_by="system" if auto else None,
    )
    vs.add(row)
    vs.flush()
    return row


def decide(vs: Session, proposal_id: int, *, approve: bool, now: datetime, by: str) -> str:
    """A tap (spec §9.7): approve or reject a pending proposal. Returns the new status, or why
    nothing changed."""
    row = vs.get(ValueProposalRow, proposal_id)
    if row is None:
        return "no_such_proposal"
    if row.status != "pending":
        return f"already_{row.status}"
    if now >= row.expires_at:
        row.status = "expired"
        return "expired"
    row.status = "approved" if approve else "rejected"
    row.decided_at, row.decided_by = now, by
    return row.status


def expire(vs: Session, now: datetime) -> int:
    """Pending and approved proposals past their time expire; their funding requests lapse."""
    n = 0
    for row in vs.scalars(
        select(ValueProposalRow).where(
            ValueProposalRow.status.in_(("pending", "approved", "funding")),
            ValueProposalRow.expires_at <= now,
        )
    ):
        row.status = "expired"
        n += 1
    for req in vs.scalars(select(ValueFundingRow).where(ValueFundingRow.status == "open")):
        prop = vs.get(ValueProposalRow, req.proposal_id)
        if (
            now >= req.expires_at
            or prop is None
            or prop.status
            not in (
                "approved",
                "funding",
                "sent",
            )
        ):
            req.status, req.closed_at = "lapsed", now
            req.detail = "expired" if now >= req.expires_at else "the buy is no longer approved"
    return n


def open_position(
    vs: Session,
    order: ValueOrderRow,
    *,
    day: date,
    atr14: float | None,
    fair_value: float | None,
    effective_fair_value: float | None,
    fv_accn: str | None,
    cfg: ValueCfg,
    decided_by: str,
) -> ValuePositionRow:
    """The position a first buy fill opens (or the one it adds to), with the live policy's plan
    written at entry (spec §7). A later tranche moves the plan's average cost; no stop is ever
    lowered by it (the live policy's only price exit is the catastrophe floor on the average)."""
    pos = vs.scalars(
        select(ValuePositionRow).where(
            ValuePositionRow.symbol == order.symbol,
            ValuePositionRow.list_name == order.list_name,
            ValuePositionRow.status == "open",
        )
    ).first()
    t = totals(vs).names.get(order.symbol, NameTotals())
    avg = t.cost / t.filled if t.filled else (order.avg_price or 0.0)
    if pos is None:
        plan = open_leg(
            cfg.rules.exits.live_policy,
            entry_date=day,
            entry_price=avg,
            atr14=atr14,
            fair_value=fair_value,
            effective_fair_value=effective_fair_value,
            fv_accn=fv_accn,
            cfg=cfg.rules.exits,
        )
        pos = ValuePositionRow(
            symbol=order.symbol,
            list_name=order.list_name,
            status="open",
            opened_on=day,
            tranches_done=1,
            last_tranche_on=day,
            plan_json=plan.model_dump_json(),
            plan_step=day,
            decided_by=decided_by,
        )
        vs.add(pos)
    else:
        state = LegState.model_validate_json(pos.plan_json or "{}")
        pos.plan_json = state.model_copy(update={"entry_price": avg}).model_dump_json()
        pos.tranches_done += 1
        pos.last_tranche_on = day
    vs.flush()
    return pos


@dataclass(frozen=True, slots=True)
class SellSignal:
    position_id: int
    symbol: str
    list_name: str
    fraction: float  # of the shares held now
    reason: str
    cause: str  # python | claude


def step_held(
    vs: Session,
    bars: dict[str, list[DayBar]],
    facts: dict[tuple[str, str], DayFacts],
    cfg: ValueCfg,
) -> list[SellSignal]:
    """Step every open position's plan over the sessions it has not seen, on Python's numbers
    (``facts`` carries Python's fair value and the effective one for the half-sale). A sale the
    plan signals is returned (the proposal is the caller's); the plan itself never fills."""
    out: list[SellSignal] = []
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        state = LegState.model_validate_json(pos.plan_json or "{}")
        days = [
            b for b in bars.get(pos.symbol, []) if pos.plan_step is None or b.date > pos.plan_step
        ]
        for b in days:
            fact = facts.get((pos.symbol, pos.list_name)) if b is days[-1] else None
            state, events = step(state, b, fact, cfg.rules.exits)
            for e in events:
                if e.kind == "fill":
                    continue
                if e.kind in PYTHON_SELLS:
                    out.append(SellSignal(pos.id, pos.symbol, pos.list_name, 1.0, e.kind, "python"))
                elif e.kind == "half":
                    python_fv = fact.python_fair_value if fact else state.fair_value
                    cause = "python" if python_fv is not None and b.close >= python_fv else "claude"
                    frac = cfg.rules.exits.half_sell_pct / 100.0
                    out.append(SellSignal(pos.id, pos.symbol, pos.list_name, frac, "half", cause))
                elif e.kind == "proposal":
                    frac = e.fraction if e.fraction > 0.0 else 1.0
                    out.append(
                        SellSignal(
                            pos.id, pos.symbol, pos.list_name, frac, "claude_value", "claude"
                        )
                    )
            # the live book's sales happen as orders, never inside the plan
            state = state.model_copy(update={"pending": 0.0, "pending_reason": ""})
        pos.plan_json = state.model_dump_json()
        if days:
            pos.plan_step = days[-1].date
    return out


def sell_shares(held: float, fraction: float) -> int:
    return max(0, math.floor(held * min(1.0, fraction) + 1e-9))


def trim_to_half(vs: Session, *, episode: str, by: str, now: datetime) -> list[int]:
    """Spec §9.6 and Part 6 ruling 3: one tap sells half of every filled position, approved now; each sale is
    still re-gated and capped by the sell cap at send time. Returns the new proposal ids."""
    state = get_state(vs, "high_water") or {}
    if not state.get("episode"):
        raise BookRefused("no_trim_offered")
    if state.get("episode") != episode:
        raise BookRefused("stale_proposal")
    if state.get("trimmed"):
        raise BookRefused("already_trimmed")
    held_now = totals(vs).names
    made: list[int] = []
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        held = held_now.get(pos.symbol)
        shares = sell_shares(held.filled if held else 0.0, 0.5)
        if shares <= 0:
            continue
        row = propose(
            vs,
            kind="sell",
            symbol=pos.symbol,
            list_name=pos.list_name,
            shares=float(shares),
            price=None,
            reason="drawdown_trim",
            cause="python",
            auto=True,
            now=now,
            ttl_hours=TRIM_TTL_HOURS,
            position_id=pos.id,
        )
        if row is not None:
            row.decided_by = by
            made.append(row.id)
    set_state(vs, "high_water", {**state, "trimmed": True, "trimmed_at": now.isoformat()}, now)
    return made


def apply_split(vs: Session, symbol: str, ratio: float, now: datetime) -> int:
    """A split the operator confirms (spec §9.2 fault drill "a split"): the value book's orders
    for *symbol* are restated in post-split shares (shares and fills x ratio, prices / ratio) and
    each open plan's price levels rebased, so V matches the broker again. Returns the orders
    restated. The freeze it caused stays until the operator clears it."""
    n = 0
    for o in vs.scalars(select(ValueOrderRow).where(ValueOrderRow.symbol == symbol.upper())):
        o.shares, o.filled = o.shares * ratio, o.filled * ratio
        o.limit_price = None if o.limit_price is None else o.limit_price / ratio
        o.avg_price = None if o.avg_price is None else o.avg_price / ratio
        o.detail = (o.detail + f" split x{ratio:g} restated {now:%Y-%m-%d}").strip()
        n += 1
    for pos in vs.scalars(
        select(ValuePositionRow).where(
            ValuePositionRow.symbol == symbol.upper(), ValuePositionRow.status == "open"
        )
    ):
        if pos.plan_json:
            pos.plan_json = (
                LegState.model_validate_json(pos.plan_json).rebased(1.0 / ratio).model_dump_json()
            )
    return n
