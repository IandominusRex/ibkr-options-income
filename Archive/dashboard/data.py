# ARCHIVED — original location: dashboard/data.py
# DB-access helpers for the Streamlit dashboard. To reinstate: move back to dashboard/data.py.
"""Pure DB-access and data-transformation helpers for the dashboard.

No Streamlit imports here — pages layer @st.cache_data on top.
All query functions return plain Python dicts/lists so they are unit-testable
without Streamlit and without touching the ORM outside this module.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from src.common.schemas import EODSummary
from src.storage.db import session_scope
from src.storage.models import (
    ApprovalRow,
    CandidateRow,
    ClaudeReviewRow,
    FillRow,
    IVHistoryRow,
    JournalRow,
    OrderRow,
    RiskVerdictRow,
)

# ---------------------------------------------------------------------------
# Portfolio / journal
# ---------------------------------------------------------------------------


def get_portfolio_summary() -> dict:
    """Return display-ready portfolio metrics from the most recent JournalRow."""
    with session_scope() as sess:
        row = sess.execute(
            select(JournalRow).order_by(JournalRow.entry_date.desc()).limit(1)
        ).scalar_one_or_none()
    if row is None:
        return _empty_portfolio()
    return _journal_row_to_portfolio(row)


def _journal_row_to_portfolio(row: JournalRow) -> dict:
    eod: EODSummary | None = _decode_eod(row)
    base: dict = {
        "entry_date": str(row.entry_date),
        "realized_pnl": row.realized_pnl or 0.0,
        "unrealized_pnl": row.unrealized_pnl or 0.0,
        "narrative": row.narrative or "",
        "nlv": None,
        "buying_power": None,
        "open_positions": 0,
        "net_delta": 0.0,
        "top_movers": [],
        "tomorrow_watchlist": [],
    }
    if eod:
        base.update(
            {
                "realized_pnl": eod.realized_pnl,
                "unrealized_pnl": eod.unrealized_pnl,
                "nlv": eod.account.net_liquidation,
                "buying_power": eod.account.buying_power,
                "open_positions": eod.open_positions,
                "net_delta": eod.net_delta_exposure,
                "top_movers": eod.top_movers,
                "tomorrow_watchlist": eod.tomorrow_watchlist,
            }
        )
    return base


def _empty_portfolio() -> dict:
    return {
        "entry_date": None,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "narrative": "",
        "nlv": None,
        "buying_power": None,
        "open_positions": 0,
        "net_delta": 0.0,
        "top_movers": [],
        "tomorrow_watchlist": [],
    }


def _decode_eod(row: JournalRow) -> EODSummary | None:
    if not row.payload or "eod_summary" not in row.payload:
        return None
    try:
        return EODSummary.model_validate(row.payload["eod_summary"])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Journal feed
# ---------------------------------------------------------------------------


def get_journal_feed(limit: int = 30) -> list[dict]:
    """Return journal rows as display-ready dicts, newest first."""
    with session_scope() as sess:
        rows = (
            sess.execute(select(JournalRow).order_by(JournalRow.entry_date.desc()).limit(limit))
            .scalars()
            .all()
        )
        return [_journal_row_to_feed_dict(r) for r in rows]


def _journal_row_to_feed_dict(row: JournalRow) -> dict:
    eod = _decode_eod(row)
    return {
        "Date": str(row.entry_date),
        "Realized P&L": row.realized_pnl,
        "Unrealized P&L": row.unrealized_pnl,
        "Fills": eod.fills_today if eod else None,
        "Positions": eod.open_positions if eod else None,
        "Net Delta": eod.net_delta_exposure if eod else None,
        "Narrative": (row.narrative or "")[:300],
    }


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


def get_latest_run_id() -> str | None:
    """Return the run_id of the most-recent candidate batch."""
    with session_scope() as sess:
        return sess.execute(
            select(CandidateRow.run_id).order_by(CandidateRow.created_at.desc()).limit(1)
        ).scalar_one_or_none()


def get_candidates(run_id: str | None = None) -> list[dict]:
    """Return candidates for *run_id* (or latest) as display-ready dicts."""
    if run_id is None:
        run_id = get_latest_run_id()
    if run_id is None:
        return []

    with session_scope() as sess:
        cands = (
            sess.execute(
                select(CandidateRow)
                .where(CandidateRow.run_id == run_id)
                .order_by(CandidateRow.blended_score.desc())
            )
            .scalars()
            .all()
        )

        cids = [c.candidate_id for c in cands]
        verdicts = {
            r.candidate_id: r.verdict
            for r in sess.execute(
                select(RiskVerdictRow).where(RiskVerdictRow.candidate_id.in_(cids))
            )
            .scalars()
            .all()
        }
        reviews = {
            r.candidate_id: r.recommendation
            for r in sess.execute(
                select(ClaudeReviewRow).where(ClaudeReviewRow.candidate_id.in_(cids))
            )
            .scalars()
            .all()
        }

        return [
            {
                "Symbol": c.underlying,
                "Strategy": c.strategy,
                "Right": c.right,
                "Strike": c.strike,
                "Expiry": str(c.expiry),
                "Score": round(c.blended_score, 1),
                "Risk": verdicts.get(c.candidate_id, "—"),
                "Claude": reviews.get(c.candidate_id, "—"),
                "_candidate_id": c.candidate_id,
            }
            for c in cands
        ]


# ---------------------------------------------------------------------------
# Orders / approvals / fills
# ---------------------------------------------------------------------------


def get_orders_pipeline() -> list[dict]:
    """Approvals joined with their orders and fill totals as display-ready dicts."""
    with session_scope() as sess:
        approvals = (
            sess.execute(select(ApprovalRow).order_by(ApprovalRow.created_at.desc()))
            .scalars()
            .all()
        )
        cids = [a.candidate_id for a in approvals]

        orders_by_cid: dict[str, list[OrderRow]] = {}
        for o in (
            sess.execute(select(OrderRow).where(OrderRow.candidate_id.in_(cids))).scalars().all()
        ):
            orders_by_cid.setdefault(o.candidate_id, []).append(o)

        fills_by_cid: dict[str, list[FillRow]] = {}
        for f in (
            sess.execute(select(FillRow).where(FillRow.candidate_id.in_(cids))).scalars().all()
        ):
            fills_by_cid.setdefault(f.candidate_id, []).append(f)

        rows = []
        for a in approvals:
            ords = orders_by_cid.get(a.candidate_id, [])
            fils = fills_by_cid.get(a.candidate_id, [])
            total_commission = sum(f.commission or 0.0 for f in fils)
            total_filled = sum(f.filled_qty for f in fils)
            latest_ord = ords[-1] if ords else None
            rows.append(
                {
                    "Candidate": a.candidate_id[:20],
                    "Approval": a.status,
                    "Order State": latest_ord.state if latest_ord else "—",
                    "Limit Price": latest_ord.limit_price if latest_ord else None,
                    "Filled Qty": total_filled if fils else None,
                    "Avg Fill": latest_ord.avg_fill_price if latest_ord else None,
                    "Commission": round(total_commission, 2) if fils else None,
                    "Live": latest_ord.is_live if latest_ord else False,
                    "Decided": str(a.decided_at.date()) if a.decided_at else "—",
                }
            )
        return rows


# ---------------------------------------------------------------------------
# IV conditions
# ---------------------------------------------------------------------------


def get_iv_history_by_symbol(lookback_days: int = 252) -> dict[str, list[tuple[date, float]]]:
    """Return {symbol: [(date, iv), ...]} sorted ascending by date for charting."""
    with session_scope() as sess:
        rows = (
            sess.execute(
                select(IVHistoryRow).order_by(IVHistoryRow.symbol, IVHistoryRow.obs_date.desc())
            )
            .scalars()
            .all()
        )

    by_sym: dict[str, list[tuple[date, float]]] = {}
    seen: dict[str, int] = {}
    for r in rows:
        count = seen.get(r.symbol, 0)
        if count >= lookback_days:
            continue
        seen[r.symbol] = count + 1
        by_sym.setdefault(r.symbol, []).append((r.obs_date, r.iv))

    return {sym: sorted(pts, key=lambda x: x[0]) for sym, pts in by_sym.items()}


def compute_iv_rank_table(by_symbol: dict[str, list[tuple[date, float]]]) -> list[dict]:
    """Pure function: compute IV Rank and Percentile from a {symbol: [(date, iv)]} map."""
    rows = []
    for sym, pts in sorted(by_symbol.items()):
        if not pts:
            continue
        ivs = [iv for _, iv in pts]
        current_iv = ivs[-1]
        iv_min, iv_max = min(ivs), max(ivs)
        iv_rank = (
            round((current_iv - iv_min) / (iv_max - iv_min) * 100, 1) if iv_max != iv_min else 0.0
        )
        below = sum(1 for iv in ivs[:-1] if iv < current_iv)
        iv_pct = round(below / len(ivs) * 100, 1) if ivs else 0.0
        rows.append(
            {
                "Symbol": sym,
                "Current IV %": round(current_iv * 100, 2),
                "IV Rank": iv_rank,
                "IV Pct": iv_pct,
                "52w Low %": round(iv_min * 100, 2),
                "52w High %": round(iv_max * 100, 2),
                "Days": len(pts),
            }
        )
    return rows
