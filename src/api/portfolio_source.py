"""The portfolio fallback chain — what the API managed to find, and how good it is.

P3-P4 M1 Task 1.5, spec §4.5. The API cannot ask IBKR anything, so `read_portfolio`
resolves the freshest portfolio state available through a three-rung chain:

  1. the newest `portfolio_snapshots` row (written by the intraday monitor, a `refresh`
     command, or the EOD run) — `source` is that row's own writer, `degraded=False`;
  2. the newest `position_snapshots` row plus the account block out of the newest
     `journal.payload["eod_summary"]["account"]` — `source="eod"`, `degraded=True`.
     The account is optional on this rung: a journal payload without the block still
     returns the positions with `account=None` rather than falling all the way through;
  3. an explicit empty reading — `source="none"`, `snapshot=None`, `degraded=True`.
     Never a `PortfolioSnapshot` with empty lists and zeroed account values: a portfolio
     page rendering zeros is indistinguishable from an account that is genuinely empty,
     and the difference is the whole account.

An exception on any rung falls through to the next — a corrupt JSON payload in the
newest row must not take the portfolio down when yesterday's data is fine. `as_of` is
always the capture time (coerced through `as_utc_opt`), never `datetime.now()`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.models.common import as_utc_opt
from src.common.schemas import AccountSnapshot, PortfolioSnapshot, PositionSnapshot
from src.storage.models import JournalRow, PortfolioSnapshotRow, PositionSnapshotRow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PortfolioReading:
    """What the API managed to find, and how good it is.

    `snapshot` is None only when every rung failed — never a zeroed-out stand-in.
    `as_of` is the capture time, NOT request time. `degraded` is True on the `eod`
    rung and the empty rung. On the `eod` rung `snapshot.account` may be None (the
    journal payload's `eod_summary.account` block is optional); every other rung
    that returns a snapshot carries an account.
    """

    snapshot: PortfolioSnapshot | None
    source: Literal["monitor", "refresh", "eod", "none"]
    as_of: datetime | None
    degraded: bool


def read_portfolio(db: Session) -> PortfolioReading:
    """Resolve the freshest portfolio state available, through the fallback chain.

    Reads through the caller's read-only session. Never raises: a failure on any rung
    falls through to the next, and the final rung is the empty reading.
    """
    reading = _newest_portfolio_snapshot(db)
    if reading is not None:
        return reading

    reading = _eod_rung(db)
    if reading is not None:
        return reading

    return PortfolioReading(snapshot=None, source="none", as_of=None, degraded=True)


# ---------------------------------------------------------------------------
# Rung 1 — the newest portfolio_snapshots row
# ---------------------------------------------------------------------------


def _newest_portfolio_snapshot(db: Session) -> PortfolioReading | None:
    try:
        row = db.execute(
            select(PortfolioSnapshotRow).order_by(PortfolioSnapshotRow.id.desc()).limit(1)
        ).scalar_one_or_none()
        if row is None:
            return None
        snapshot = PortfolioSnapshot(
            captured_at=_required_as_utc(row.captured_at),
            source=row.source,  # type: ignore[arg-type]
            account=AccountSnapshot.model_validate(row.account),
            positions=[PositionSnapshot.model_validate(p) for p in row.positions],
        )
        return PortfolioReading(
            snapshot=snapshot, source=snapshot.source, as_of=snapshot.captured_at, degraded=False
        )
    except Exception:
        log.exception("read_portfolio: newest portfolio_snapshots rung failed — falling through")
        return None


# ---------------------------------------------------------------------------
# Rung 2 — position_snapshots + the journal's eod_summary account block
# ---------------------------------------------------------------------------


def _eod_rung(db: Session) -> PortfolioReading | None:
    try:
        snap_row = db.execute(
            select(PositionSnapshotRow).order_by(PositionSnapshotRow.snapshot_date.desc()).limit(1)
        ).scalar_one_or_none()
        if snap_row is None:
            return None
        positions = [PositionSnapshot.model_validate(p) for p in snap_row.payload or []]

        account = _journal_account(db)
        # The capture time on this rung is the position snapshot row's own created_at
        # (mirrors GET /options/shorts' discipline: the snapshot's capture time, not
        # request time) — the account block in the journal has no capture time of its
        # own worth trusting over the row's.
        captured_at = _required_as_utc(snap_row.created_at)
        snapshot = PortfolioSnapshot(
            captured_at=captured_at,
            source="eod",
            account=account,
            positions=positions,
        )
        return PortfolioReading(snapshot=snapshot, source="eod", as_of=captured_at, degraded=True)
    except Exception:
        log.exception("read_portfolio: eod rung failed — falling through")
        return None


def _journal_account(db: Session) -> AccountSnapshot | None:
    """The account block out of the newest journal row's eod_summary, or None.

    Validated through `AccountSnapshot.model_validate` (not read field by field), so a
    schema drift surfaces as a fall-through to `None`, never a `KeyError` at render
    time. A missing block — or a journal with no `eod_summary` payload at all — is the
    documented optional-account case on this rung, not an error.
    """
    row = db.execute(
        select(JournalRow).order_by(JournalRow.entry_date.desc()).limit(1)
    ).scalar_one_or_none()
    if row is None or not row.payload:
        return None
    try:
        block = (row.payload or {}).get("eod_summary", {}).get("account")
        if block is None:
            return None
        return AccountSnapshot.model_validate(block)
    except Exception:
        log.exception("read_portfolio: journal eod_summary.account failed validation")
        return None


def _required_as_utc(dt: datetime | None) -> datetime:
    """as_utc_opt for a column that is non-nullable; a None here is a corrupt row."""
    coerced = as_utc_opt(dt)
    if coerced is None:
        raise ValueError("non-nullable capture time is missing — treating the row as corrupt")
    return coerced
