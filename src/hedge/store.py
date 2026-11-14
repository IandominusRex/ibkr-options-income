"""The hedge package's storage: the only writer of ``hedge_quotes`` rows (risk-envelope Task 16).

``record_capture`` writes one capture's rows in one transaction; ``load_quotes`` reads them back as
plain ``QuoteRecord`` data for the H4 report. ``needed_contracts`` is the bridge size Task 36's rule
would want right now: 0 until that rule exists. Timestamps are stored naive-UTC, like the trading DB.

Deterministic tier: imports no enrichment.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select

from src.storage.db import session_scope
from src.storage.models import HedgeQuoteRow


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


def needed_contracts() -> int:
    """The bridge size of Task 36's rule at the latest snapshot. The rule does not exist yet (the
    bridge is built in Task 36), so a capture records 0 and the H4 report reads it as "at least one"."""
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
            )
            for r in s.execute(stmt).scalars()
        ]
