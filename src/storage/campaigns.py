"""Campaign storage — wheel-strategy P&L threads (C6).

A campaign groups all option legs on one symbol under one P&L thread so the
operator can see cumulative income, adjusted cost basis after assignment, and
total return across a CSP→assignment→CC→roll→close sequence.

Public API:
  attach_fill_to_campaign  — called after every fill; opens or updates the campaign
  mark_campaign_assigned   — called by EOD reconciler when assignment is detected
  load_campaigns           — read-side for /campaigns Telegram command
  adjusted_cost_basis_for  — read-side for the covered-call gate (D5)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select

from src.storage.db import session_scope
from src.storage.models import CampaignRow, FillRow

log = logging.getLogger(__name__)


def _generate_campaign_id(symbol: str) -> str:
    return f"{symbol}-{uuid.uuid4().hex[:8]}"


def _rollup(session, row: CampaignRow) -> None:
    """Recompute financial totals from all FillRow entries for the campaign's legs.

    Gross of commissions: this sums avg_price * filled_qty * 100 and never reads
    FillRow.commission, so total_premium_collected/total_debit_paid/net_premium exclude it by
    design (pinned by tests/test_campaign_rollup_semantics.py). src/reporting/ (from M4)
    reports the same trades net of commissions, the same way src/reporting/legs.py's
    classify_outcome does (credit - debit - commissions) — see CampaignRow's docstring for the
    fuller explanation of the gap between the two.
    """
    candidate_ids = list(row.leg_candidate_ids or [])
    if not candidate_ids:
        return

    fills = (
        session.execute(select(FillRow).where(FillRow.candidate_id.in_(candidate_ids)))
        .scalars()
        .all()
    )

    collected = 0.0
    paid = 0.0
    for f in fills:
        value = float(f.avg_price or 0.0) * float(f.filled_qty or 0.0) * 100
        if (f.action or "SELL").upper() == "SELL":
            collected += value
        else:
            paid += value

    row.total_premium_collected = round(collected, 2)
    row.total_debit_paid = round(paid, 2)
    row.net_premium = round(collected - paid, 2)


def _auto_close(session, row: CampaignRow) -> None:
    """Close the campaign when all entered contracts have been bought back (net flat)."""
    candidate_ids = list(row.leg_candidate_ids or [])
    if not candidate_ids:
        return

    fills = (
        session.execute(select(FillRow).where(FillRow.candidate_id.in_(candidate_ids)))
        .scalars()
        .all()
    )

    sell_qty = sum(
        float(f.filled_qty or 0) for f in fills if (f.action or "SELL").upper() == "SELL"
    )
    buy_qty = sum(float(f.filled_qty or 0) for f in fills if (f.action or "SELL").upper() == "BUY")

    if sell_qty > 0 and buy_qty >= sell_qty and not row.assigned:
        row.status = "closed"
        row.closed_date = datetime.now(UTC).date()


def attach_fill_to_campaign(
    symbol: str,
    candidate_id: str,
    strategy: str,
    action: str,
    avg_price: float,
    filled_qty: float,
) -> None:
    """Open or update the campaign for *symbol* after a fill is recorded.

    On a SELL fill (opening leg): find the open campaign for this symbol or create one.
    On a BUY fill (closing leg): attach to the open campaign (if any) for rollup.
    Always re-rolls the financials and checks for auto-close.

    Never raises — campaign failures are non-fatal relative to the fill record.
    """
    try:
        with session_scope() as session:
            # Find an open campaign for this symbol.
            row = session.execute(
                select(CampaignRow)
                .where(CampaignRow.symbol == symbol, CampaignRow.status == "open")
                .order_by(CampaignRow.opened_date.desc())
                .limit(1)
            ).scalar_one_or_none()

            if row is None:
                if action.upper() != "SELL":
                    # BUY with no open campaign — orphaned close, skip.
                    return
                # Open a new campaign on the first SELL (entry) fill.
                row = CampaignRow(
                    campaign_id=_generate_campaign_id(symbol),
                    symbol=symbol,
                    status="open",
                    opened_date=datetime.now(UTC).date(),
                    leg_candidate_ids=[candidate_id],
                    payload={"first_strategy": strategy},
                )
                session.add(row)
                session.flush()  # assigns row.id before rollup
            else:
                # Add this candidate to the leg list (deduplicated).
                legs = list(row.leg_candidate_ids or [])
                if candidate_id not in legs:
                    legs.append(candidate_id)
                    row.leg_candidate_ids = legs
                    payload = dict(row.payload or {})
                    payload["last_strategy"] = strategy
                    row.payload = payload

            _rollup(session, row)
            _auto_close(session, row)
    except Exception:
        log.warning(
            "attach_fill_to_campaign failed for %s candidate=%s",
            symbol,
            candidate_id,
            exc_info=True,
        )


def mark_campaign_assigned(
    symbol: str,
    assignment_price: float | None = None,
    right: str | None = None,
) -> None:
    """Mark the open campaign for *symbol* as assigned and compute adjusted cost basis.

    adjusted_cost_basis = assignment_price − (net_premium / 100) per share, so the
    operator knows their effective stock entry price net of all collected premium.

    The ACB is only meaningful when shares are *acquired* — i.e. a short **put** assignment
    (``right`` is ``"P"`` or unknown). For a short **call** assignment (``right == "C"``) the
    shares are called *away*, so we flag the campaign assigned but leave the basis untouched.

    Called by the EOD reconciler (``orchestrator/eod_report.py``) for each assigned short.
    """
    try:
        with session_scope() as session:
            row = session.execute(
                select(CampaignRow)
                .where(CampaignRow.symbol == symbol, CampaignRow.status == "open")
                .order_by(CampaignRow.opened_date.desc())
                .limit(1)
            ).scalar_one_or_none()

            if row is None:
                return

            row.assigned = True
            acquires_shares = (right or "P").upper() != "C"
            if acquires_shares and assignment_price is not None and row.net_premium > 0:
                # net_premium is total dollars; divide by 100 to get per-share.
                row.adjusted_cost_basis = round(assignment_price - row.net_premium / 100, 4)
    except Exception:
        log.warning("mark_campaign_assigned failed for %s", symbol, exc_info=True)


def load_campaigns(
    limit: int = 20,
    *,
    open_only: bool = False,
    since: date | None = None,
) -> list[dict]:
    """Return a list of campaign dicts ordered by opened_date descending.

    Each dict contains: campaign_id, symbol, status, opened_date, closed_date,
    leg_candidate_ids, leg_count, total_premium_collected, total_debit_paid,
    net_premium, assigned, adjusted_cost_basis, realized_stock_pnl.
    """
    try:
        with session_scope() as session:
            stmt = select(CampaignRow).order_by(CampaignRow.opened_date.desc()).limit(limit)
            if open_only:
                stmt = stmt.where(CampaignRow.status == "open")
            if since is not None:
                stmt = stmt.where(CampaignRow.opened_date >= since)
            rows = session.execute(stmt).scalars().all()
            return [
                {
                    "campaign_id": r.campaign_id,
                    "symbol": r.symbol,
                    "status": r.status,
                    "opened_date": r.opened_date,
                    "closed_date": r.closed_date,
                    "leg_candidate_ids": list(r.leg_candidate_ids or []),
                    "leg_count": len(r.leg_candidate_ids or []),
                    "total_premium_collected": r.total_premium_collected,
                    "total_debit_paid": r.total_debit_paid,
                    "net_premium": r.net_premium,
                    "assigned": r.assigned,
                    "adjusted_cost_basis": r.adjusted_cost_basis,
                    "realized_stock_pnl": r.realized_stock_pnl,
                }
                for r in rows
            ]
    except Exception:
        log.warning("load_campaigns failed", exc_info=True)
        return []


def adjusted_cost_basis_for(symbol: str) -> float | None:
    """Per-share adjusted cost basis from *symbol*'s open, assigned campaign, or None.

    After a CSP assignment the true basis is the assignment price less the premium already
    collected across the campaign (``mark_campaign_assigned``). Without this reader, the
    covered-call gate compared strikes to IBKR's raw ``avg_cost`` — so with the default
    ``min_strike_vs_basis: 1.00`` the premium already earned was invisible to the gate
    deciding whether you may earn more (D5).

    Never raises — a storage failure here must not break a scan.
    """
    try:
        with session_scope() as session:
            row = session.execute(
                select(CampaignRow)
                .where(
                    CampaignRow.symbol == symbol,
                    CampaignRow.status == "open",
                    CampaignRow.assigned,
                )
                .order_by(CampaignRow.opened_date.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row is None or row.adjusted_cost_basis is None:
                return None
            basis = float(row.adjusted_cost_basis)
            return basis if basis > 0 else None
    except Exception:
        log.warning("adjusted_cost_basis_for failed for %s", symbol, exc_info=True)
        return None
