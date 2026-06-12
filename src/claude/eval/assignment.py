"""Assignment auto-detection via position diffing (SYSTEM_REVIEW Phase 4).

Removes the manual ``--assigned`` flag and fixes the ledger's weakest label: a short option
that is ITM at expiry is *assigned* (a stock leg is created/removed), not expired-worthless.
We detect this deterministically by diffing the prior day's position snapshot against current
positions — the most direct evidence (the shares literally appear or disappear), and the
method the review prescribed.

``detect_assignments`` is a pure function (positions in, candidate_ids out) so it is fully
unit-testable; ``assigned_candidate_ids`` is the DB-backed orchestration the EOD run calls.

Enrichment-layer input only: it produces the ``assigned_candidate_ids`` the reconciler consumes
to label a row ASSIGNED vs EXPIRED_WORTHLESS. Nothing here touches the risk engine or sizing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.claude.eval.ledger import open_filled_records
from src.common.schemas import PositionSnapshot
from src.storage.db import session_scope
from src.storage.models import FillRow
from src.storage.positions import load_latest_position_snapshot

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_SHARES_PER_CONTRACT = 100
# Require the stock move to be at least this fraction of the expected assigned shares, so a
# rounding/partial mismatch still counts but unrelated noise does not.
_MATCH_TOLERANCE = 0.99


@dataclass(frozen=True)
class OpenShort:
    candidate_id: str
    underlying: str
    right: str  # "C" | "P"
    strike: float
    expiry: date
    contracts: float  # net short contracts (Σ SELL − Σ BUY filled_qty)


def _net_short_contracts(session, candidate_id: str) -> float:
    rows = session.execute(
        select(FillRow.action, FillRow.filled_qty).where(FillRow.candidate_id == candidate_id)
    ).all()
    sold = sum(q for a, q in rows if (a or "SELL").upper() == "SELL")
    bought = sum(q for a, q in rows if (a or "SELL").upper() == "BUY")
    return float(sold - bought)


def open_shorts_from_ledger() -> list[OpenShort]:
    """Build the OpenShort work-list from filled, still-open ledger rows."""
    shorts: list[OpenShort] = []
    for r in open_filled_records():
        with session_scope() as s:
            contracts = _net_short_contracts(s, r.candidate_id)
        if contracts <= 0:
            continue  # already net flat (fully bought back) — not a candidate for assignment
        shorts.append(
            OpenShort(
                candidate_id=r.candidate_id,
                underlying=r.underlying,
                right=r.right.value,
                strike=r.strike,
                expiry=r.expiry,
                contracts=contracts,
            )
        )
    return shorts


def _stock_qty(positions: list[PositionSnapshot], underlying: str) -> float:
    return sum(
        p.position
        for p in positions
        if p.sec_type == "STK" and (p.underlying or p.symbol) == underlying
    )


def _option_present(positions: list[PositionSnapshot], short: OpenShort) -> bool:
    for p in positions:
        if (
            p.sec_type == "OPT"
            and p.position < 0
            and (p.underlying or p.symbol) == short.underlying
            and p.right is not None
            and p.right.value == short.right
            and p.strike is not None
            and abs(p.strike - short.strike) < 1e-3
            and p.expiry == short.expiry
        ):
            return True
    return False


def detect_assignments(
    open_shorts: list[OpenShort],
    prior_positions: list[PositionSnapshot],
    current_positions: list[PositionSnapshot],
    today: date,
) -> set[str]:
    """Candidate ids whose short was assigned, by diffing prior vs current positions.

    A short is assigned when it has reached/passed expiry, is no longer held, and the
    underlying stock position moved by ~100×contracts in the assignment direction:
      * short PUT  → we were put the shares (stock increases),
      * short CALL → our shares were called away (stock decreases).
    A vanished short with no matching stock move expired worthless (not assigned).
    """
    assigned: set[str] = set()
    for sh in open_shorts:
        if sh.expiry > today:
            continue  # not expired yet → still open, can't be assigned
        if _option_present(current_positions, sh):
            continue  # still in the book → not yet terminal
        delta = _stock_qty(current_positions, sh.underlying) - _stock_qty(
            prior_positions, sh.underlying
        )
        expected = _SHARES_PER_CONTRACT * sh.contracts * _MATCH_TOLERANCE
        if sh.right == "P" and delta >= expected:
            assigned.add(sh.candidate_id)
        elif sh.right == "C" and delta <= -expected:
            assigned.add(sh.candidate_id)
    return assigned


def assigned_candidate_ids(
    current_positions: list[PositionSnapshot], today: date | None = None
) -> set[str]:
    """DB-backed orchestration: detect assignments against the most recent prior snapshot."""
    today = today or datetime.now(_ET).date()
    prior = load_latest_position_snapshot(before=today)
    shorts = open_shorts_from_ledger()
    assigned = detect_assignments(shorts, prior, current_positions, today)
    if assigned:
        log.info(
            "Assignment auto-detection flagged %d position(s): %s",
            len(assigned),
            sorted(assigned),
        )
    return assigned
