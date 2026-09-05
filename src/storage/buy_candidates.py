"""Persistence for buy-to-own recommendations (``generate_buy_candidates`` output).

The orchestrator already computes the buy list at both call sites; this writes it to
SQLite so ``GET /research/recommendations`` reads the precomputed result rather than
triggering a full scan on every page load. Display-only: nothing in the pipeline reads
this back into a gate, score, or sizing decision.

Single-ticker ``/scan TICKER`` runs persist under a ``scan-`` prefixed ``run_id`` so
``latest_buy_candidates`` can filter them out: a one-name manual scan must never replace
the whole recommendations list.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.schemas import BuyCandidate
from src.storage.db import session_scope
from src.storage.models import BuyCandidateRow

log = logging.getLogger(__name__)

# run_id prefix used by the single-ticker /scan path. latest_buy_candidates ignores any
# run whose run_id starts with this so a /scan NVDA cannot displace the full-scan list.
SINGLE_TICKER_PREFIX = "scan-"


def save_buy_candidates(run_id: str, candidates: list[BuyCandidate]) -> int:
    """Persist *candidates* under run *run_id*. Returns the number written.

    An empty list writes nothing and never clears the previous run — a scan that produced
    no recommendations must not blank the recommendations page. Best-effort: a write
    failure is logged and swallowed (display data must never abort a scan).
    """
    if not candidates:
        return 0
    try:
        rows = [_to_row(run_id, cand) for cand in candidates]
        with session_scope() as s:
            s.add_all(rows)
        return len(rows)
    except Exception:
        log.warning(
            "save_buy_candidates(%s) failed — recommendations skipped", run_id, exc_info=True
        )
        return 0


def latest_buy_candidates(limit: int = 25) -> list[BuyCandidate]:
    """Return the most recent full-scan run's candidates, ranked by score descending.

    Single-ticker runs (``scan-`` prefix) are excluded so ``/scan NVDA`` cannot replace
    the whole list with one name. Returns ``[]`` when the table is empty; never raises.
    """
    try:
        with session_scope() as s:
            return _latest_from_session(s, limit)
    except Exception:
        log.exception("latest_buy_candidates failed — returning empty list")
        return []


def latest_buy_candidates_from(session: Session, limit: int = 25) -> list[BuyCandidate]:
    """Read-only variant for the API: reads the latest full-scan run through an existing
    (read-only) trading session. Used by ``GET /research/recommendations`` so the web
    layer honours §4.3 (the API writes nothing and reads through the ``mode=ro`` engine).
    """
    return _latest_from_session(session, limit)


def _latest_from_session(s: Session, limit: int) -> list[BuyCandidate]:
    latest_run = (
        s.execute(
            select(BuyCandidateRow.run_id)
            .where(~BuyCandidateRow.run_id.like(f"{SINGLE_TICKER_PREFIX}%"))
            .order_by(BuyCandidateRow.computed_at.desc(), BuyCandidateRow.run_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest_run is None:
        return []
    rows = (
        (
            s.execute(
                select(BuyCandidateRow)
                .where(BuyCandidateRow.run_id == latest_run)
                .order_by(BuyCandidateRow.score.desc(), BuyCandidateRow.symbol)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_from_row(r) for r in rows]


def _to_row(run_id: str, cand: BuyCandidate) -> BuyCandidateRow:
    return BuyCandidateRow(
        run_id=run_id,
        symbol=cand.symbol,
        score=float(cand.score),
        sector=cand.sector,
        iv_rank=cand.iv_rank,
        quality_flag=cand.quality_flag,
        technical_regime=(
            str(cand.technical_regime) if cand.technical_regime is not None else None
        ),
        rationale=cand.rationale,
        price=cand.price,
        current_iv=cand.current_iv,
        hv_30=cand.hv_30,
        vrp=cand.vrp,
        rsi_14=cand.rsi_14,
        sma_50=cand.sma_50,
        sma_200=cand.sma_200,
        next_earnings=cand.next_earnings,
        dividend_yield=cand.dividend_yield,
        est_monthly_cc_yield=cand.est_monthly_cc_yield,
        iv_score=cand.iv_score,
        fundamental_score=cand.fundamental_score,
        technical_score=cand.technical_score,
    )


def _from_row(r: BuyCandidateRow) -> BuyCandidate:
    return BuyCandidate(
        symbol=r.symbol,
        score=float(r.score),
        sector=r.sector,
        iv_rank=r.iv_rank,
        quality_flag=r.quality_flag,
        technical_regime=r.technical_regime,
        rationale=r.rationale or "",
        price=r.price,
        current_iv=r.current_iv,
        hv_30=r.hv_30,
        vrp=r.vrp,
        rsi_14=r.rsi_14,
        sma_50=r.sma_50,
        sma_200=r.sma_200,
        next_earnings=r.next_earnings,
        dividend_yield=r.dividend_yield,
        est_monthly_cc_yield=r.est_monthly_cc_yield,
        iv_score=r.iv_score,
        fundamental_score=r.fundamental_score,
        technical_score=r.technical_score,
    )
