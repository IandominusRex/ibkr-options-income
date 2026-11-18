"""The hedge package's storage: the only writer of the ``hedge_*`` rows (risk-envelope Tasks 16, 33).

* ``hedge_quotes`` (Task 16): ``record_capture`` writes one capture's rows in one transaction;
  ``load_quotes`` reads them back as plain ``QuoteRecord`` data for the H4 report.
  ``needed_contracts`` is the bridge size the capture records beside each row.
* ``hedge_programme``, ``hedge_orders``, ``hedge_fills``, ``hedge_marks`` (Task 33): the bridge's
  state, its orders (each written **before** the order is sent), their fills and booked settlements or
  lapses, and its daily marks. The wheel's ``orders`` and ``fills`` never receive a hedge row.
  Everyone outside ``src/hedge/`` reads these through ``src/common/hedge_view.py`` (``mode=ro``).

Timestamps are stored naive-UTC, like the trading DB. Deterministic tier: imports no enrichment.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from src.common.schemas import HedgeCandidate
from src.storage.db import session_scope
from src.storage.models import (
    HedgeFillRow,
    HedgeMarkRow,
    HedgeOrderRow,
    HedgeProgrammeRow,
    HedgeQuoteRow,
)


@dataclass(frozen=True, slots=True)
class QuoteRecord:
    captured_at: datetime  # tz-aware UTC
    session_date: date
    instrument: str
    item_key: str
    leg: str  # long | short
    is_default: bool
    con_id: int | None
    strike: float
    right: str
    expiry: date
    spot: float
    bid: float | None
    ask: float | None
    bid_size: float | None
    ask_size: float | None
    mid: float | None
    delta: float | None
    needed_contracts: int = 0
    iv: float | None = None


NEEDED_KEY = "hedge_needed_contracts"  # system_settings: the size rule's last want (Task 36)


def needed_contracts() -> int:
    """The bridge size the H5 rule last asked for (``manager._pick`` writes it to
    ``system_settings``); 0 before the bridge has sized anything, which the H4 report reads as
    "at least one"."""
    from src.storage.system_settings import get_setting

    try:
        return max(0, int(get_setting(NEEDED_KEY, "0") or 0))
    except ValueError:
        return 0


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


def record_capture(records: Iterable[QuoteRecord]) -> int:
    """Write *records* in one transaction; the number written."""
    rows = [
        HedgeQuoteRow(
            captured_at=_naive(r.captured_at),
            session_date=r.session_date,
            instrument=r.instrument,
            item_key=r.item_key,
            leg=r.leg,
            is_default=r.is_default,
            con_id=r.con_id,
            strike=r.strike,
            right=r.right,
            expiry=r.expiry,
            spot=r.spot,
            bid=r.bid,
            ask=r.ask,
            bid_size=r.bid_size,
            ask_size=r.ask_size,
            mid=r.mid,
            delta=r.delta,
            needed_contracts=r.needed_contracts,
            iv=r.iv,
        )
        for r in records
    ]
    if not rows:
        return 0
    with session_scope() as s:
        s.add_all(rows)
    return len(rows)


def load_quotes(*, instrument: str | None = None) -> list[QuoteRecord]:
    """Every stored capture row (optionally one instrument's), oldest first."""
    stmt = select(HedgeQuoteRow).order_by(HedgeQuoteRow.captured_at, HedgeQuoteRow.id)
    if instrument is not None:
        stmt = stmt.where(HedgeQuoteRow.instrument == instrument.upper())
    with session_scope() as s:
        return [
            QuoteRecord(
                captured_at=r.captured_at.replace(tzinfo=UTC),
                session_date=r.session_date,
                instrument=r.instrument,
                item_key=r.item_key,
                leg=r.leg,
                is_default=bool(r.is_default),
                con_id=r.con_id,
                strike=r.strike,
                right=r.right,
                expiry=r.expiry,
                spot=r.spot,
                bid=r.bid,
                ask=r.ask,
                bid_size=r.bid_size,
                ask_size=r.ask_size,
                mid=r.mid,
                delta=r.delta,
                needed_contracts=r.needed_contracts,
                iv=r.iv,
            )
            for r in s.execute(stmt).scalars()
        ]


# --------------------------------------------------------------------------- #
# The book: programme, orders, fills, marks (Task 33)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Programme:
    id: int
    state: str  # on | ended
    instrument: str
    started_on: date
    nlv0: float
    glide_end: date | None
    ended_on: date | None
    zero_size_sessions: int
    last_session: date | None
    review_posted_on: date | None


def _programme(r: HedgeProgrammeRow) -> Programme:
    return Programme(
        id=r.id,
        state=r.state,
        instrument=r.instrument,
        started_on=r.started_on,
        nlv0=float(r.nlv0),
        glide_end=r.glide_end,
        ended_on=r.ended_on,
        zero_size_sessions=int(r.zero_size_sessions or 0),
        last_session=r.last_session,
        review_posted_on=r.review_posted_on,
    )


def load_programme() -> Programme | None:
    """The latest bridge programme, or None when none was ever started."""
    with session_scope() as s:
        row = s.execute(
            select(HedgeProgrammeRow).order_by(HedgeProgrammeRow.id.desc()).limit(1)
        ).scalar_one_or_none()
        return _programme(row) if row is not None else None


def start_programme(
    *, instrument: str, started_on: date, nlv0: float, glide_end: date | None
) -> Programme:
    """Write the bridge's first-day row. Idempotent: an existing programme is returned unchanged,
    so NLV0 is fixed once (spec §3.10.3)."""
    existing = load_programme()
    if existing is not None:
        return existing
    with session_scope() as s:
        row = HedgeProgrammeRow(
            state="on",
            instrument=instrument.upper(),
            started_on=started_on,
            nlv0=float(nlv0),
            glide_end=glide_end,
            zero_size_sessions=0,
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        s.add(row)
        s.flush()
        return _programme(row)


def update_programme(programme_id: int, **values: Any) -> None:
    """Set *values* on the programme row (``nlv0`` and ``started_on`` are never changed)."""
    values.pop("nlv0", None)
    values.pop("started_on", None)
    with session_scope() as s:
        row = s.get(HedgeProgrammeRow, programme_id)
        if row is None:
            return
        for k, v in values.items():
            setattr(row, k, v)
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)


def _leg_json(cand: HedgeCandidate) -> list[dict[str, Any]]:
    return [
        {
            "action": leg.action,
            "right": leg.right,
            "strike": leg.strike,
            "expiry": leg.expiry.isoformat(),
            "con_id": leg.con_id,
        }
        for leg in cand.legs
    ]


def position_id(cand: HedgeCandidate) -> str:
    """The position an order belongs to: its own id for an opening, the position it sells for a
    close."""
    return cand.closes if cand.intent == "close" and cand.closes else cand.hedge_id


def record_order(
    cand: HedgeCandidate, *, limit_price: float | None, state: str = "submitted"
) -> int:
    """Insert the order row (before the order is sent): its ``order_ref`` is the candidate's. Returns
    the row id."""
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as s:
        row = HedgeOrderRow(
            hedge_id=position_id(cand),
            order_ref=cand.order_ref,
            instrument=cand.instrument.upper(),
            intent=cand.intent,
            kind=cand.kind,
            contracts=int(cand.contracts),
            multiplier=int(cand.multiplier),
            debit_approved=float(cand.debit),
            limit_price=limit_price,
            state=state,
            legs=_leg_json(cand),
            closes=cand.closes,
            roll_of=cand.roll_of,
            reason=cand.reason[:64],
            created_at=now,
            updated_at=now,
        )
        s.add(row)
        s.flush()
        return int(row.id)


def update_order(order_id: int, **values: Any) -> None:
    with session_scope() as s:
        row = s.get(HedgeOrderRow, order_id)
        if row is None:
            return
        for k, v in values.items():
            setattr(row, k, v)
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)


def working_orders(hedge_id: str | None = None) -> list[dict[str, Any]]:
    """Orders still ``submitted`` or ``working`` (optionally one position's); ``partial`` is final."""
    stmt = select(HedgeOrderRow).where(HedgeOrderRow.state.in_(("submitted", "working")))
    if hedge_id is not None:
        stmt = stmt.where(HedgeOrderRow.hedge_id == hedge_id)
    with session_scope() as s:
        return [
            {
                "id": r.id,
                "hedge_id": r.hedge_id,
                "order_ref": r.order_ref,
                "intent": r.intent,
                "contracts": r.contracts,
                "multiplier": r.multiplier,
                "filled_qty": r.filled_qty,
                "created_at": r.created_at,
            }
            for r in s.execute(stmt).scalars()
        ]


def fill_exec_ids(order_id: int) -> set[str]:
    """The broker ``execId``s already booked against one order (a late fill is booked once)."""
    with session_scope() as s:
        return {
            e
            for (e,) in s.execute(
                select(HedgeFillRow.exec_id).where(
                    HedgeFillRow.order_id == order_id, HedgeFillRow.exec_id.is_not(None)
                )
            ).all()
            if e
        }


def record_fill(
    *,
    hedge_id: str,
    qty: float,
    price: float,
    multiplier: int = 100,
    order_id: int | None = None,
    kind: str = "fill",
    commission: float = 0.0,
    exec_id: str | None = None,
    filled_at: datetime | None = None,
) -> int:
    """One fill or booked event on position *hedge_id*: *qty* contracts (positive = bought, negative
    = sold, settled or lapsed) at *price* per share (net). ``cash`` = -qty x price x multiplier -
    commission (paying is negative)."""
    when = (filled_at or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)
    with session_scope() as s:
        row = HedgeFillRow(
            order_id=order_id,
            hedge_id=hedge_id,
            kind=kind,
            qty=float(qty),
            price=float(price),
            cash=-float(qty) * float(price) * multiplier - abs(float(commission)),
            commission=abs(float(commission)),
            exec_id=exec_id,
            filled_at=when,
        )
        s.add(row)
        s.flush()
        return int(row.id)


def record_mark(
    *,
    session_date: date,
    hedge_id: str,
    contracts: float,
    mark: float,
    multiplier: int = 100,
    source: str,
    marked_at: datetime | None = None,
) -> None:
    """One mark of an open position: *mark* per share (net), value = mark x multiplier x contracts.
    *source* is ``captured`` (a captured mid) or ``bs`` (the labelled Black-Scholes fallback)."""
    when = (marked_at or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)
    with session_scope() as s:
        s.add(
            HedgeMarkRow(
                session_date=session_date,
                hedge_id=hedge_id,
                contracts=float(contracts),
                mark=float(mark),
                value=float(mark) * multiplier * float(contracts),
                source=source,
                marked_at=when,
            )
        )


def last_mark_at(hedge_id: str) -> datetime | None:
    """When position *hedge_id* was last marked (tz-aware UTC), or None."""
    with session_scope() as s:
        at = s.execute(
            select(HedgeMarkRow.marked_at)
            .where(HedgeMarkRow.hedge_id == hedge_id)
            .order_by(HedgeMarkRow.marked_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    return at.replace(tzinfo=UTC) if at is not None else None
