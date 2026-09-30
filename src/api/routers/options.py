"""Options console read routes (P2 Milestone 2).

Every route is owner-only and reads through the ``mode=ro`` trading engine. The
snapshot is the source of truth for what the human was shown; joined
``CandidateRow`` / ``RiskVerdictRow`` / ``ClaudeReviewRow`` rows are enrichment
whose absence must never 500. No ``null`` numeric is ever coerced to ``0``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from src.api.deps import OwnerUser, TradingDb
from src.api.models.common import Source, Sourced, as_utc, as_utc_opt
from src.api.models.options import (
    AlternativeStrike,
    ApprovalDetail,
    ApprovalListResponse,
    ApprovalSourceLit,
    ApprovalSummary,
    AssessedContract,
    AssessedGroup,
    AssessedResponse,
    AssessedRunsResponse,
    AssessedRunSummary,
    ClaudeReviewPayload,
    ControlsResponse,
    FillListResponse,
    FillSummary,
    IdealZonePayload,
    OrderListResponse,
    OrderSummary,
    RollAlertSummary,
    ShortListResponse,
    ShortPosition,
)
from src.api.settings_read import parse_setting_dt, read_setting
from src.common.assignment_risk import assignment_risk_thresholds, is_assignment_risk
from src.common.config import get_config
from src.common.schemas import AssessmentStage

router = APIRouter(prefix="/options", tags=["options"])

_ET = ZoneInfo("America/New_York")


def _right_lit(raw: Any) -> Literal["C", "P"]:
    """Coerce a snapshot's right field to the ``C``/``P`` literal the schema expects."""
    r = str(raw).upper()
    return "C" if r.startswith("C") else "P"


# Roll run_id prefix — matches ``src.strategies.rolling`` (a roll candidate's run_id
# is ``roll-...`` so the approvals list can tell a roll-sourced approval from a scan one).
_ROLL_RUN_PREFIX = "roll-"


# Human-readable labels for the raw risk-gate / filter reason codes surfaced on the web.
#
# Mirrors ``src.notify.formatters._REJECT_REASON_LABELS`` but is duplicated here
# deliberately: the formatters module is Telegram-coupled (MarkdownV2 escaping,
# chat-length constraints) and importing it would pull the web layer into the notify
# layer's concerns. The duplication is a deliberate cost, not an accident — so
# ``tests/test_reason_label_parity.py`` fails the build if the two ever diverge. Add a code
# to one, add it to the other, with the identical phrase.
_REASON_LABELS: dict[str, str] = {
    "iv_rank_below_minimum": "IV rank too low (poor premium)",
    "iv_rv_below_minimum": "IV/RV ratio too low (premium not rich vs realized)",
    "delta_out_of_range": "delta outside target band",
    "delta_missing": "no delta available (illiquid / no Greeks)",
    "delta_sign_mismatch": "delta sign wrong for strategy",
    "dte_out_of_range": "no expiries in the target DTE window",
    "roc_below_minimum": "return-on-capital below floor",
    "yield_below_minimum": "annualized yield below floor",
    "premium_below_fair_value": "credit is below fair value for the risk (no variance premium)",
    "earnings_blackout": "earnings inside the window",
    "no_contracts": "no contracts at the target strike",
    "negative_bid_sentinel": "no real bid (stale / illiquid quote)",
    "buying_power_buffer": "not enough buying-power headroom",
    "concentration_limit": "per-ticker concentration cap hit",
    "large_position_slot_full": "no large-position slot is free",
    "sector_limit": "per-sector concentration cap hit",
    "csp_allocation_limit": "total CSP allocation cap hit",
    "margin_limit": "margin limit hit",
    "contracts_exceeds_max": "size exceeds max contracts",
    "score_below_minimum": "blended score below quality floor",
    "no_two_sided_market": "no live bid/ask (can't price it)",
    # Legacy: collapsed all liquidity-gate failures into one code. Superseded by the seven
    # illiquid_* codes below (Task 7); kept only to humanize pre-existing risk_verdicts rows.
    "illiquid": "fails liquidity gates (spread / OI / volume)",
    "illiquid_no_quote": "liquidity: no usable bid/ask to measure spread",
    "illiquid_zero_bid": "liquidity: zero bid (no buyer at any price)",
    "illiquid_spread_wide": "liquidity: bid/ask spread wider than limit",
    "illiquid_oi_missing": "liquidity: open interest not reported",
    "illiquid_oi_low": "liquidity: open interest below minimum",
    "illiquid_volume_missing": "liquidity: day volume not reported",
    "illiquid_volume_low": "liquidity: day volume below minimum",
    "strike_below_basis": "strike below cost basis (would lock in a loss)",
    "insufficient_cash": "not enough cash to secure one contract",
    "no_headroom": "no room under the concentration or budget caps",
    "dedupe_pre_gate": "a better strike on this name already claimed the shared risk budget",
    "dedupe_not_surfaced": "a better strike on this name won the slot",
    "top_n_not_surfaced": "max new positions per run already full",
    # Order-send-time codes (risk_engine.validate_live_quote) — the second Rules Engine
    # pass against a fresh quote, distinct from the decision-time codes above.
    "live_no_mid": "no live two-sided market at order time (missing bid/ask)",
    "live_greeks_required": "live mode requires IBKR-sourced greeks, unavailable at order time",
    "live_delta_out_of_range": "delta drifted outside target band between approval and order time",
    "live_premium_collapse": "live mid collapsed well below the approved premium (price moved against the trade)",
}


def _humanize_reason(code: str) -> str:
    """Map a raw gate/filter reason code to a readable phrase.

    The fallback — de-snake-cased code, never an empty string — matches
    ``src.notify.formatters._humanize_reject_reason``'s behaviour exactly.
    """
    return _REASON_LABELS.get(code, code.replace("_", " "))


def _humanize_reasons(codes: list[str] | None) -> list[str]:
    """Humanise a list of raw reason codes, de-duplicating while preserving order."""
    out: list[str] = []
    for c in codes or []:
        label = _humanize_reason(c)
        if label and label not in out:
            out.append(label)
    return out


def _dte(expiry: date) -> int:
    """Days to expiry, in the exchange timezone (ET) so a UTC server at 11 PM is correct."""
    return (expiry - datetime.now(_ET).date()).days


# ---------------------------------------------------------------------------
# Task 2.1 — GET /options/approvals and GET /options/approvals/{id}
# ---------------------------------------------------------------------------


def _source_from_run_id(run_id: str | None) -> ApprovalSourceLit:
    """Derive ``source`` from the candidate's run_id prefix.

    A ``roll-`` prefix means the approval came from a roll proposal; anything else
    (including the normal scan run_id and the ``scan-`` single-ticker prefix) is a
    scan-sourced approval.
    """
    if run_id and run_id.startswith(_ROLL_RUN_PREFIX):
        return "roll"
    return "scan"


def _snapshot_fields(snap: dict[str, Any] | None) -> dict[str, Any]:
    """Extract the display fields from a frozen TradeCandidate snapshot.

    The snapshot is the source of truth for what the human was shown. When the
    joined ``CandidateRow`` has been pruned (the 14-day purge), the summary still
    renders from the snapshot alone — so every field the card needs is read here
    first, before any join is attempted.
    """
    if not snap:
        return {}
    return {
        "underlying": snap.get("underlying"),
        "strategy": snap.get("strategy"),
        "right": snap.get("right"),
        "strike": snap.get("strike"),
        "expiry": snap.get("expiry"),
        "contracts": snap.get("contracts", 1),
        "premium": snap.get("premium"),
        "blended_score": snap.get("blended_score"),
        "rationale_tags": snap.get("rationale_tags"),
    }


def _build_summary(
    approval: Any,
    cand: Any | None,
    order_state: str | None,
    review: ClaudeReviewPayload | None = None,
) -> ApprovalSummary:
    """Build an ``ApprovalSummary`` from the joined rows, preferring the snapshot."""
    snap = approval.snapshot or {}
    snap_fields = _snapshot_fields(snap)

    underlying = snap_fields.get("underlying") or (cand.underlying if cand else "")
    strategy = snap_fields.get("strategy") or (cand.strategy if cand else "")
    right = snap_fields.get("right") or (cand.right if cand else "")
    strike = snap_fields.get("strike") or (cand.strike if cand else 0.0)
    expiry = snap_fields.get("expiry") or (cand.expiry if cand else None)
    contracts = snap_fields.get("contracts") or (
        cand.payload.get("contracts", 1) if cand is not None and cand.payload else 1
    )
    premium = snap_fields.get("premium")
    blended_score = snap_fields.get("blended_score")
    raw_tags = snap_fields.get("rationale_tags")
    rationale_tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
    run_id = cand.run_id if cand else None

    if premium is None and cand is not None:
        # Fall back to the candidate payload's premium. The snapshot is preferred
        # (it's what the human was shown) but a very old approval may predate the
        # freeze and have a null snapshot.
        premium = cand.payload.get("premium") if cand.payload else None

    if contracts is None or contracts == 0:
        contracts = 1

    return ApprovalSummary(
        as_of=datetime.now(UTC),
        id=approval.id,
        candidate_id=approval.candidate_id,
        status=approval.status,
        underlying=underlying,
        strategy=strategy,
        right=right,
        strike=strike,
        expiry=expiry,
        contracts=contracts,
        premium=premium,
        blended_score=blended_score,
        created_at=as_utc(approval.created_at),
        expires_at=as_utc_opt(approval.expires_at),
        decided_at=as_utc_opt(approval.decided_at),
        order_state=order_state,
        source=_source_from_run_id(run_id),
        review=review,
        rationale_tags=rationale_tags,
    )


def _review_payload(payload: dict[str, Any] | None) -> ClaudeReviewPayload | None:
    """Build a ``ClaudeReviewPayload`` from a stored ``ClaudeReviewRow.payload`` dict."""
    if not isinstance(payload, dict):
        return None
    raw_evidence = payload.get("evidence")
    return ClaudeReviewPayload(
        why_attractive=str(payload.get("why_attractive", "")),
        risks=str(payload.get("risks", "")),
        tradeoffs=str(payload.get("tradeoffs", "")),
        assignment_considerations=str(payload.get("assignment_considerations", "")),
        rolling_considerations=str(payload.get("rolling_considerations", "")),
        recommendation=payload.get("recommendation"),
        priority=payload.get("priority"),
        confidence=payload.get("confidence"),
        summary=str(payload.get("summary") or ""),
        evidence=[str(e) for e in raw_evidence if e] if isinstance(raw_evidence, list) else [],
    )


def _latest_reviews_by_candidate(
    db: Any, candidate_ids: set[str]
) -> dict[str, ClaudeReviewPayload]:
    """Batch-fetch the newest ``ClaudeReviewRow`` per candidate id — one query, not N.

    Ordered by candidate_id then recency descending, so the first row seen per
    candidate while iterating is its newest (same "take the newest" rule
    ``get_approval`` already applies to a single candidate).
    """
    from src.storage.models import ClaudeReviewRow

    if not candidate_ids:
        return {}
    rows = (
        db.execute(
            select(ClaudeReviewRow)
            .where(ClaudeReviewRow.candidate_id.in_(candidate_ids))
            .order_by(
                ClaudeReviewRow.candidate_id,
                ClaudeReviewRow.created_at.desc(),
                ClaudeReviewRow.id.desc(),
            )
        )
        .scalars()
        .all()
    )
    out: dict[str, ClaudeReviewPayload] = {}
    for row in rows:
        if row.candidate_id in out:
            continue
        payload = _review_payload(row.payload)
        if payload is not None:
            out[row.candidate_id] = payload
    return out


@router.get("/approvals", response_model=ApprovalListResponse)
def list_approvals(
    _user: OwnerUser,
    db: TradingDb,
    status: Literal["pending", "approved", "rejected", "expired", "all"] = Query(
        default="pending",
        description="Filter by approval status, or `all` for every status (newest first).",
    ),
    symbol: str | None = Query(
        default=None,
        description="Filter to one underlying (case-insensitive), matched via the joined "
        "CandidateRow. An approval whose candidate has since been pruned (14-day purge) will "
        "not match even if its own snapshot still carries the symbol.",
    ),
    # Bare `= None` rather than `Query(default=None, ...)`, matching the convention
    # `src/api/routers/pnl.py` already uses for date params — `date | None` is not on
    # ruff's built-in B008 immutable-annotation list, so wrapping it in `Query(...)`
    # would (harmlessly, but needlessly) trip the mutable-default-argument lint.
    since: date | None = None,
    until: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> ApprovalListResponse:
    """List approvals, pending by default. ``status=all`` returns decided ones too.

    An unknown status value is rejected with 422 (not a silent empty list) — an
    operator typo should surface, not look like "no approvals." ``since``/``until``
    filter by UTC calendar date, inclusive on both ends.
    """
    from src.storage.models import ApprovalRow, CandidateRow, OrderRow

    now = datetime.now(UTC)

    stmt = select(ApprovalRow)
    if status != "all":
        stmt = stmt.where(ApprovalRow.status == status)
    if since is not None:
        stmt = stmt.where(ApprovalRow.created_at >= datetime.combine(since, datetime.min.time()))
    if until is not None:
        stmt = stmt.where(
            ApprovalRow.created_at
            < datetime.combine(until, datetime.min.time()) + timedelta(days=1)
        )
    if symbol is not None:
        stmt = stmt.join(CandidateRow, CandidateRow.candidate_id == ApprovalRow.candidate_id).where(
            func.upper(CandidateRow.underlying) == symbol.upper()
        )
    # Newest first overall. For status=all this is "newest first" as the spec
    # requires; for a single-status filter the secondary sort is redundant but
    # harmless. A pending approval is NOT promoted above a newer decided one in
    # the all view — "newest first" means by created_at, full stop.
    stmt = stmt.order_by(ApprovalRow.created_at.desc()).limit(limit)

    approvals = db.execute(stmt).scalars().all()
    if not approvals:
        return ApprovalListResponse(as_of=now, approvals=[])

    # Batch the joins: one pass each for candidates, orders, and reviews.
    candidate_ids = {a.candidate_id for a in approvals}
    approval_ids = {a.id for a in approvals}

    cand_map: dict[str, Any] = {}
    if candidate_ids:
        cands = (
            db.execute(select(CandidateRow).where(CandidateRow.candidate_id.in_(candidate_ids)))
            .scalars()
            .all()
        )
        cand_map = {c.candidate_id: c for c in cands}

    order_map: dict[int, str] = {}
    if approval_ids:
        orders = db.execute(
            select(OrderRow.approval_id, OrderRow.state).where(
                OrderRow.approval_id.in_(approval_ids)
            )
        ).all()
        order_map = {row[0]: row[1] for row in orders if row[0] is not None}

    review_map = _latest_reviews_by_candidate(db, candidate_ids)

    summaries = [
        _build_summary(
            a, cand_map.get(a.candidate_id), order_map.get(a.id), review_map.get(a.candidate_id)
        )
        for a in approvals
    ]
    return ApprovalListResponse(as_of=now, approvals=summaries)


@router.get("/approvals/{approval_id}", response_model=ApprovalDetail)
def get_approval(
    approval_id: int,
    _user: OwnerUser,
    db: TradingDb,
) -> ApprovalDetail:
    """One approval in full. 404 if unknown. Joined enrichment degrades to null."""
    from src.storage.models import (
        ApprovalRow,
        CandidateRow,
        ClaudeReviewRow,
        FillRow,
        OrderRow,
        RiskVerdictRow,
    )

    approval = db.get(ApprovalRow, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    cand = db.execute(
        select(CandidateRow).where(CandidateRow.candidate_id == approval.candidate_id)
    ).scalar_one_or_none()

    order_state: str | None = None
    order_id: int | None = None
    fills: list[FillSummary] = []
    if approval.id is not None:
        order_row = db.execute(
            select(OrderRow.id, OrderRow.state).where(OrderRow.approval_id == approval.id)
        ).first()
        if order_row is not None:
            order_id, order_state = order_row
            # The approval-to-fill lineage the console otherwise needs two more
            # requests (GET /options/orders, GET /options/fills) to assemble.
            fill_rows = (
                db.execute(
                    select(FillRow)
                    .where(FillRow.order_id == order_id)
                    .order_by(FillRow.filled_at.asc(), FillRow.id.asc())
                )
                .scalars()
                .all()
            )
            fills = [
                FillSummary(
                    as_of=datetime.now(UTC),
                    id=f.id,
                    order_id=f.order_id,
                    candidate_id=f.candidate_id,
                    action=f.action,
                    filled_qty=f.filled_qty,
                    avg_price=f.avg_price,
                    commission=f.commission,
                    is_live=bool(f.is_live),
                    filled_at=as_utc(f.filled_at),
                )
                for f in fill_rows
            ]

    summary = _build_summary(approval, cand, order_state)

    # Ideal zone from the RiskVerdictRow (denormalised lo / hi / min_credit).
    # risk_verdicts stores one row per assessed contract PER RUN, so a candidate
    # scanned more than once has more than one row here — take the newest.
    ideal: IdealZonePayload | None = None
    verdict_row = db.execute(
        select(RiskVerdictRow)
        .where(RiskVerdictRow.candidate_id == approval.candidate_id)
        .order_by(RiskVerdictRow.created_at.desc(), RiskVerdictRow.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if verdict_row is not None:
        ideal = IdealZonePayload(
            lo=verdict_row.ideal_lo,
            hi=verdict_row.ideal_hi,
            min_credit=verdict_row.min_credit,
        )

    # Gate reasons — humanised, not raw codes.
    gate_reasons: list[str] = []
    if verdict_row is not None:
        raw_reasons = verdict_row.reasons
        if isinstance(raw_reasons, dict):
            # RiskVerdictRow.reasons is stored as a JSON dict; the formatters expect a
            # list of codes. Handle both shapes defensively — a dict may carry a
            # ``codes`` list or be a code->bool map.
            if "codes" in raw_reasons and isinstance(raw_reasons["codes"], list):
                gate_reasons = _humanize_reasons(raw_reasons["codes"])
            elif "reasons" in raw_reasons and isinstance(raw_reasons["reasons"], list):
                gate_reasons = _humanize_reasons(raw_reasons["reasons"])
            else:
                gate_reasons = _humanize_reasons(
                    [str(k) for k, v in raw_reasons.items() if v is True or v == "true"]
                )
        elif isinstance(raw_reasons, list):
            gate_reasons = _humanize_reasons(raw_reasons)

    # Claude review — the five fields, separately, never one blob.
    # A candidate reviewed more than once (retry, re-review) has more than one row
    # here — take the newest, same reasoning as the verdict lookup above.
    review_row = db.execute(
        select(ClaudeReviewRow)
        .where(ClaudeReviewRow.candidate_id == approval.candidate_id)
        .order_by(ClaudeReviewRow.created_at.desc(), ClaudeReviewRow.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    review = _review_payload(review_row.payload if review_row is not None else None)

    # Alternatives — other contracts assessed on this underlying during the same run.
    alternatives: list[AlternativeStrike] = []
    if cand is not None and cand.run_id:
        alt_rows = (
            db.execute(
                select(RiskVerdictRow)
                .where(
                    RiskVerdictRow.run_id == cand.run_id,
                    RiskVerdictRow.symbol == cand.underlying,
                    RiskVerdictRow.candidate_id != cand.candidate_id,
                )
                .order_by(RiskVerdictRow.blended_score.desc())
                .limit(10)
            )
            .scalars()
            .all()
        )
        for r in alt_rows:
            raw_reasons = r.reasons
            alt_codes: list[str] = []
            if isinstance(raw_reasons, list):
                alt_codes = raw_reasons
            elif isinstance(raw_reasons, dict) and "codes" in raw_reasons:
                alt_codes = list(raw_reasons.get("codes") or [])
            alternatives.append(
                AlternativeStrike(
                    candidate_id=r.candidate_id,
                    strategy=r.strategy or "",
                    strike=r.strike or 0.0,
                    expiry=r.expiry,
                    blended_score=r.blended_score,
                    premium=r.premium,
                    stage=r.stage,
                    reasons=alt_codes,
                )
            )

    return ApprovalDetail(
        as_of=summary.as_of,
        id=summary.id,
        candidate_id=summary.candidate_id,
        status=summary.status,
        underlying=summary.underlying,
        strategy=summary.strategy,
        right=summary.right,
        strike=summary.strike,
        expiry=summary.expiry,
        contracts=summary.contracts,
        premium=summary.premium,
        blended_score=summary.blended_score,
        created_at=summary.created_at,
        expires_at=summary.expires_at,
        decided_at=summary.decided_at,
        order_state=summary.order_state,
        source=summary.source,
        review=review,
        rationale_tags=summary.rationale_tags,
        snapshot=approval.snapshot or {},
        ideal=ideal,
        gate_reasons=gate_reasons,
        alternatives=alternatives,
        order_id=order_id,
        fills=fills,
    )


# ---------------------------------------------------------------------------
# Task 2.2 — GET /options/assessed
# ---------------------------------------------------------------------------


def _latest_run_id(db: TradingDb) -> tuple[str | None, datetime | None]:
    """Resolve the newest non-single-ticker-prefixed run_id from ``risk_verdicts``.

    Mirrors ``latest_buy_candidates_from``'s single-ticker filter: a ``/scan NVDA``
    must not become "the latest run" for the assessed browser either. Two prefixes
    carry that same "one ticker, not a full scan" meaning and are both excluded:
    ``scan-`` (the Telegram ``/scan TICKER`` command) and ``ticker-`` (every promote
    attempt, win or lose, via ``src.orchestrator.scan._price_and_gate_ticker``).
    Returns ``(run_id, computed_at)`` where ``computed_at`` is the newest
    ``created_at`` among that run's rows.
    """
    from src.storage.models import RiskVerdictRow

    row = db.execute(
        select(RiskVerdictRow.run_id, func.max(RiskVerdictRow.created_at))
        .where(RiskVerdictRow.run_id.isnot(None))
        .where(~RiskVerdictRow.run_id.like("scan-%"))
        .where(~RiskVerdictRow.run_id.like("ticker-%"))
        .group_by(RiskVerdictRow.run_id)
        .order_by(func.max(RiskVerdictRow.created_at).desc())
        .limit(1)
    ).first()
    if row is None:
        return None, None
    return row[0], as_utc_opt(row[1])


def _promotable_for(stage: str, min_candidate_score: float) -> tuple[bool, str | None]:
    """The promotable table from spec §5.2, implemented exactly."""
    if stage == AssessmentStage.GENERATOR.value:
        return False, "Failed a strategy filter, so the system never priced it as a candidate."
    if stage == AssessmentStage.RISK_GATE.value:
        return False, "The Rules Engine rejected this contract."
    if stage == AssessmentStage.SCORE_FLOOR.value:
        return True, f"Scores below your configured minimum of {min_candidate_score}."
    if stage == AssessmentStage.DEDUPE.value:
        return True, None
    if stage == AssessmentStage.TOP_N.value:
        return True, None
    if stage == AssessmentStage.PASSED.value:
        return False, "Already surfaced for approval."
    return False, None


@router.get("/assessed/runs", response_model=AssessedRunsResponse)
def list_assessed_runs(
    _user: OwnerUser,
    db: TradingDb,
    limit: int = Query(default=20, ge=1, le=100),
) -> AssessedRunsResponse:
    """Past full-scan run ids, newest first — lets the Assessed tab browse history.

    Registered ahead of ``/assessed`` in this file only for reading order; the two
    paths never collide (this one carries no path parameter). Excludes single-ticker
    runs (``scan-``/``ticker-`` prefixes) the same way ``_latest_run_id`` does — a
    ``/scan NVDA`` or a promote attempt is not "a run" in the sense this list means.
    """
    from src.storage.models import RiskVerdictRow

    now = datetime.now(UTC)
    rows = db.execute(
        select(
            RiskVerdictRow.run_id,
            func.max(RiskVerdictRow.created_at),
            func.count(RiskVerdictRow.id),
        )
        .where(RiskVerdictRow.run_id.isnot(None))
        .where(~RiskVerdictRow.run_id.like("scan-%"))
        .where(~RiskVerdictRow.run_id.like("ticker-%"))
        .group_by(RiskVerdictRow.run_id)
        .order_by(func.max(RiskVerdictRow.created_at).desc())
        .limit(limit)
    ).all()

    return AssessedRunsResponse(
        as_of=now,
        runs=[
            AssessedRunSummary(
                as_of=now,
                run_id=r[0],
                computed_at=as_utc_opt(r[1]),
                candidate_count=r[2],
            )
            for r in rows
        ],
    )


@router.get("/assessed", response_model=AssessedResponse)
def list_assessed(
    _user: OwnerUser,
    db: TradingDb,
    run: str = Query(default="latest"),
    symbol: str | None = Query(default=None),
    stage: Literal["generator", "risk_gate", "score_floor", "dedupe", "top_n", "passed"]
    | None = Query(
        default=None,
        description="Filter to one assessment stage. Unknown values return 422.",
    ),
    limit: int = Query(default=200, ge=1, le=1000),
) -> AssessedResponse:
    """The assessed browser: every contract the scan priced, grouped by symbol."""
    from src.storage.models import RiskVerdictRow

    now = datetime.now(UTC)

    run_id: str | None
    computed_at: datetime | None
    if run == "latest":
        run_id, computed_at = _latest_run_id(db)
    else:
        run_id = run
        row = db.execute(
            select(func.max(RiskVerdictRow.created_at)).where(RiskVerdictRow.run_id == run)
        ).scalar_one_or_none()
        computed_at = as_utc_opt(row)

    if run_id is None:
        return AssessedResponse(as_of=now, run_id=None, computed_at=None, groups=[])

    min_score = float(get_config().weights.get("min_candidate_score", 0) or 0)

    stmt = select(RiskVerdictRow).where(RiskVerdictRow.run_id == run_id)
    if symbol:
        stmt = stmt.where(RiskVerdictRow.symbol == symbol.upper())
    if stage:
        stmt = stmt.where(RiskVerdictRow.stage == stage)

    rows = db.execute(stmt).scalars().all()
    if not rows:
        return AssessedResponse(as_of=now, run_id=run_id, computed_at=computed_at, groups=[])

    # Group by symbol. Within each group, rank the same way _rank_assessed does
    # (scan.py:850): PASSED first, then rejects by how far they got (later stage =
    # got further = ranks higher), then blended score descending. The spec says
    # "the same ranking idea as _rank_assessed" — not a separate promotable/score
    # key, which would rank a score_floor reject above a top_n one even though
    # top_n got further.
    _stage_order = {s.value: i for i, s in enumerate(AssessmentStage)}
    # Unknown stages sort as if they never got past the generator (order = -1
    # pushes them below every known reject), but this is a display-only fallback;
    # the literal will reject the response before it reaches the client.

    def _rank_key(r: RiskVerdictRow) -> tuple[int, int, float]:
        stage = r.stage or ""
        order = _stage_order.get(stage, -1)
        passed = stage == AssessmentStage.PASSED.value
        return (0 if passed else 1, -order, -(r.blended_score or 0.0))

    by_symbol: dict[str, list[RiskVerdictRow]] = {}
    for r in rows:
        by_symbol.setdefault(r.symbol or "?", []).append(r)

    def _build_contract(r: RiskVerdictRow, sym: str) -> AssessedContract:
        raw_reasons = r.reasons
        codes: list[str] = []
        if isinstance(raw_reasons, list):
            codes = raw_reasons
        elif isinstance(raw_reasons, dict):
            if "codes" in raw_reasons and isinstance(raw_reasons["codes"], list):
                codes = list(raw_reasons["codes"])
            elif "reasons" in raw_reasons and isinstance(raw_reasons["reasons"], list):
                codes = list(raw_reasons["reasons"])
        humanised = _humanize_reasons(codes)
        promotable, promote_note = _promotable_for(r.stage or "", min_score)
        # Do not coerce an unknown stage to "generator" — that would silently
        # mark it non-promotable with a "failed a strategy filter" note, which
        # is a lie. Pass the raw value through; if it isn't one of the six
        # known stages, the AssessedStageLit literal will reject the response
        # and surface the schema drift instead of hiding it.
        stage_val = r.stage or "generator"
        ideal = (
            IdealZonePayload(lo=r.ideal_lo, hi=r.ideal_hi, min_credit=r.min_credit)
            if (r.ideal_lo is not None or r.ideal_hi is not None or r.min_credit is not None)
            else None
        )
        return AssessedContract(
            as_of=now,
            candidate_id=r.candidate_id,
            symbol=sym,
            strategy=r.strategy or "",
            strike=r.strike,
            expiry=r.expiry,
            stage=stage_val,  # type: ignore[arg-type]
            reasons=codes,
            reasons_text=humanised,
            blended_score=r.blended_score,
            premium=r.premium,
            ideal=ideal,
            promotable=promotable,
            promote_note=promote_note,
        )

    # Build each group fully: contracts ranked best-first, and counts over every
    # row in the symbol (not a truncated subset — the header count must reflect
    # what the scan actually produced, not what fit under the limit).
    groups: list[AssessedGroup] = []
    for sym in sorted(by_symbol):
        sym_rows = sorted(by_symbol[sym], key=_rank_key)
        contracts = [_build_contract(r, sym) for r in sym_rows]
        counts: dict[str, int] = {}
        for c in contracts:
            counts[c.stage] = counts.get(c.stage, 0) + 1
        groups.append(AssessedGroup(as_of=now, symbol=sym, contracts=contracts, counts=counts))

    # Order groups by their best contract under the same _rank_assessed idea, so a
    # symbol with one passed contract at score 90 ranks above one with ten
    # score_floor rejects at score 80. "Best contract first" per the spec means
    # the group's single best contract, not a count of promotable ones. The key
    # mirrors _rank_key above: passed first, then stage progression, then score.
    def _group_key(g: AssessedGroup) -> tuple[int, int, float]:
        if not g.contracts:
            return (1, 0, 0.0)
        c = g.contracts[0]
        order = _stage_order.get(c.stage, -1)
        passed = c.stage == AssessmentStage.PASSED.value
        return (0 if passed else 1, -order, -(c.blended_score or 0.0))

    groups.sort(key=_group_key)

    # `limit` is the overall cap on contracts returned, not a per-symbol cap. A
    # run with 20 symbols × 50 contracts would otherwise return 1000 rows under
    # the default limit=200. Trim across the ranked groups, preserving each
    # group's internal ranking and the group order, so the best contracts across
    # the whole run are what surfaces. Counts stay complete (see build above) so
    # the group header still reports what the scan produced, not what survived.
    if limit > 0:
        remaining = limit
        trimmed: list[AssessedGroup] = []
        for g in groups:
            if remaining <= 0:
                break
            take = g.contracts[:remaining]
            remaining -= len(take)
            trimmed.append(g.model_copy(update={"contracts": take}))
        groups = trimmed

    return AssessedResponse(as_of=now, run_id=run_id, computed_at=computed_at, groups=groups)


# ---------------------------------------------------------------------------
# Task 2.3 — GET /options/orders and GET /options/fills
# ---------------------------------------------------------------------------


def _order_underlying_strategy_strike(
    snap: dict[str, Any] | None, cand: Any | None
) -> tuple[str, str, float, date | None]:
    """Underlying / strategy / strike from the order's snapshot, falling back to CandidateRow."""
    snap = snap or {}
    underlying = snap.get("underlying") or (cand.underlying if cand else "")
    strategy = snap.get("strategy") or (cand.strategy if cand else "")
    strike = snap.get("strike") or (cand.strike if cand else 0.0)
    expiry = snap.get("expiry") or (cand.expiry if cand else None)
    return underlying, strategy, strike, expiry


@router.get("/orders", response_model=OrderListResponse)
def list_orders(
    _user: OwnerUser,
    db: TradingDb,
    state: Literal[
        "working", "all", "queued", "submitted", "filled", "partial", "cancelled", "rejected"
    ] = Query(
        default="working",
        description="`working` (queued/submitted/partial), `all`, or a specific state.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> OrderListResponse:
    """Working orders by default. ``state=all`` returns everything.

    An unknown state value is rejected with 422 (not a silent empty list).
    """
    from src.storage.models import CandidateRow, OrderRow

    now = datetime.now(UTC)
    _WORKING = {"queued", "submitted", "partial"}

    stmt = select(OrderRow)
    if state == "working":
        stmt = stmt.where(OrderRow.state.in_(_WORKING))
    elif state != "all":
        # A specific state: validate by the literal above, then filter directly.
        stmt = stmt.where(OrderRow.state == state)
    stmt = stmt.order_by(OrderRow.created_at.desc()).limit(limit)

    orders = db.execute(stmt).scalars().all()
    if not orders:
        return OrderListResponse(as_of=now, orders=[])

    candidate_ids = {o.candidate_id for o in orders}
    cand_map: dict[str, Any] = {}
    if candidate_ids:
        cands = (
            db.execute(select(CandidateRow).where(CandidateRow.candidate_id.in_(candidate_ids)))
            .scalars()
            .all()
        )
        cand_map = {c.candidate_id: c for c in cands}

    out: list[OrderSummary] = []
    for o in orders:
        cand = cand_map.get(o.candidate_id)
        underlying, strategy, strike, expiry = _order_underlying_strategy_strike(o.snapshot, cand)
        # avg_fill_price is null for an unfilled order, never 0.0. The row's column
        # is nullable; a fabricated zero would read as real to an operator.
        avg_fill = o.avg_fill_price if o.avg_fill_price is not None else None
        out.append(
            OrderSummary(
                as_of=now,
                id=o.id,
                candidate_id=o.candidate_id,
                approval_id=o.approval_id,
                underlying=underlying,
                strategy=strategy,
                strike=strike,
                expiry=expiry,
                state=o.state,  # type: ignore[arg-type]
                limit_price=o.limit_price,
                filled_qty=o.filled_qty if o.filled_qty is not None else 0.0,
                avg_fill_price=avg_fill,
                is_live=bool(o.is_live),
                detail=o.detail,
                created_at=as_utc_opt(o.created_at) or now,
                updated_at=as_utc_opt(o.updated_at) or now,
            )
        )
    return OrderListResponse(as_of=now, orders=out)


@router.get("/fills", response_model=FillListResponse)
def list_fills(
    _user: OwnerUser,
    db: TradingDb,
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=500),
) -> FillListResponse:
    """Recent fills within the last ``days`` days."""
    from src.storage.models import FillRow

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)

    rows = (
        db.execute(
            select(FillRow)
            .where(FillRow.filled_at >= cutoff)
            .order_by(FillRow.filled_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    fills = [
        FillSummary(
            as_of=now,
            id=r.id,
            order_id=r.order_id,
            candidate_id=r.candidate_id,
            action=r.action,
            filled_qty=r.filled_qty,
            avg_price=r.avg_price,
            commission=r.commission,
            is_live=bool(r.is_live),
            filled_at=as_utc_opt(r.filled_at) or now,
        )
        for r in rows
    ]
    return FillListResponse(as_of=now, fills=fills)


# ---------------------------------------------------------------------------
# Task 2.4 — GET /options/shorts
# ---------------------------------------------------------------------------


@router.get("/shorts", response_model=ShortListResponse)
def list_shorts(
    _user: OwnerUser,
    db: TradingDb,
) -> ShortListResponse:
    """Open short option positions from the most recent position snapshot.

    ``as_of`` is the snapshot's capture time, not request time — the same discipline
    P0/P1 M4 fixed for quotes. Long options and stock are excluded. ``delta`` carries
    its source through ``Sourced`` so a BS delta never looks identical to an IBKR one.
    A position with no snapshot data returns ``null`` for ``mark`` and
    ``unrealized_pnl``, never ``0.0``.
    """
    from src.storage.models import PositionSnapshotRow, RollAlertRow

    snap_row = db.execute(
        select(PositionSnapshotRow).order_by(PositionSnapshotRow.snapshot_date.desc()).limit(1)
    ).scalar_one_or_none()

    if snap_row is None:
        return ShortListResponse(as_of=datetime.now(UTC), shorts=[])

    # as_of is the snapshot's capture time, not request time.
    as_of = as_utc_opt(snap_row.created_at) or datetime.now(UTC)

    positions: list[dict[str, Any]] = snap_row.payload or []
    short_opts = [
        p for p in positions if p.get("sec_type") == "OPT" and float(p.get("position", 0) or 0) < 0
    ]
    if not short_opts:
        return ShortListResponse(as_of=as_of, shorts=[])

    # Pre-fetch roll alerts for the position symbols on this snapshot.
    position_symbols = {p.get("symbol", "") for p in short_opts}
    alert_rows: list[RollAlertRow] = []
    if position_symbols:
        alert_rows = list(
            db.execute(
                select(RollAlertRow)
                .where(RollAlertRow.position_symbol.in_(position_symbols))
                .order_by(RollAlertRow.created_at.desc())
            )
            .scalars()
            .all()
        )
    alerts_by_symbol: dict[str, list[RollAlertSummary]] = {}
    from src.monitor.triggers import humanize_trigger

    for a in alert_rows:
        alerts_by_symbol.setdefault(a.position_symbol, []).append(
            RollAlertSummary(
                id=a.id,
                trigger=a.trigger,
                trigger_label=humanize_trigger(a.trigger),
                detail=a.detail,
                claude_recommendation=a.claude_recommendation,
                created_at=as_utc_opt(a.created_at) or as_of,
            )
        )

    shorts: list[ShortPosition] = []
    for p in short_opts:
        position_symbol = p.get("symbol", "")
        expiry_raw = p.get("expiry")
        expiry: date | None = None
        if expiry_raw:
            try:
                expiry = date.fromisoformat(str(expiry_raw)[:10])
            except (ValueError, TypeError):
                expiry = None
        # dte is None when expiry is unknown — never 0, which would read as "expires today".
        dte = _dte(expiry) if expiry else None
        contracts = int(abs(float(p.get("position", 0) or 0)))
        # assignment_risk: deep-ITM short near expiry, per the one shared definition
        # (Task 0.3, src/common/assignment_risk.py) — the monitor's configured thresholds,
        # not a hardcoded pair. Unknown expiry or delta means we cannot assert it, so we
        # surface false rather than fabricate the signal from a missing field.
        delta_val = p.get("delta")
        delta_threshold, dte_threshold = assignment_risk_thresholds(get_config())
        assignment_risk = is_assignment_risk(
            position=float(p.get("position", 0) or 0),
            delta=float(delta_val) if delta_val is not None else None,
            dte=dte,
            delta_threshold=delta_threshold,
            dte_threshold=dte_threshold,
        )

        # delta provenance: the snapshot may carry a greeks_source. "black_scholes"
        # maps to Source.COMPUTED (the Source enum has no BS value); "ibkr" stays
        # IBKR so a BS-derived delta never looks identical to an IBKR-derived one.
        delta_sourced: Sourced[float] | None = None
        if delta_val is not None:
            greeks_source = str(p.get("greeks_source", "ibkr"))
            _BS_SOURCES = {"black_scholes", "bs", "computed"}
            src = Source.COMPUTED if greeks_source in _BS_SOURCES else Source.IBKR
            delta_sourced = Sourced[float](
                value=float(delta_val),
                source=src,
                as_of=as_of,
                stale=False,
            )

        mark = p.get("market_price")
        unrealized = p.get("unrealized_pnl")
        avg_cost = p.get("avg_cost")
        pnl_pct: float | None = None
        # unrealized_pnl is the total dollar P&L on the position; avg_cost is the
        # per-share cost basis. The position is `contracts * 100` shares, so the
        # percentage is unrealized / (|avg_cost| * contracts * 100) * 100, which
        # simplifies to unrealized / (|avg_cost| * contracts). Dividing by the
        # per-share cost alone would be off by ~contracts*100.
        if unrealized is not None and avg_cost and float(avg_cost) != 0 and contracts > 0:
            pnl_pct = round(float(unrealized) / (abs(float(avg_cost)) * contracts), 2)

        shorts.append(
            ShortPosition(
                as_of=as_of,
                position_symbol=position_symbol,
                underlying=p.get("underlying", ""),
                right=_right_lit(p.get("right", "P")),
                strike=float(p.get("strike", 0.0) or 0.0),
                expiry=expiry,
                dte=dte,
                contracts=contracts,
                avg_cost=avg_cost if avg_cost is not None else None,
                mark=mark if mark is not None else None,
                unrealized_pnl=unrealized if unrealized is not None else None,
                pnl_pct=pnl_pct,
                delta=delta_sourced,
                assignment_risk=bool(assignment_risk),
                alerts=alerts_by_symbol.get(position_symbol, []),
            )
        )
    return ShortListResponse(as_of=as_of, shorts=shorts)


# ---------------------------------------------------------------------------
# Task 2.5 — GET /options/controls
# ---------------------------------------------------------------------------


# The command drain heartbeat key in system_settings. Written by
# ``src.notify.command_drain.drain_once`` after every cycle (M1 Task 1.5 / P2
# §5.5). This route reads it and compares against twice the poll interval — a
# drain that has never run is ``false`` with ``drain_last_seen: null``.
#
# Hardcoded rather than imported from ``src.notify.command_drain``: the API must
# not pull in the notify layer (which drags in the broker client and the write
# path). The key is a shared contract, kept in sync with
# ``COMMAND_DRAIN_HEARTBEAT_KEY`` in ``src/notify/command_drain.py``.
_DRAIN_HEARTBEAT_KEY = "command_drain_heartbeat"

# The four rungs in ladder order, matching ``AutonomyLevel`` (OBSERVE → FULL).
_RUNGS: list[tuple[str, str]] = [
    ("observe", "Observe"),
    ("manual", "Manual"),
    ("whitelist", "Whitelist"),
    ("full", "Full"),
]


@router.get("/controls", response_model=ControlsResponse)
def controls(
    _user: OwnerUser,
    db: TradingDb,
) -> ControlsResponse:
    """Autonomy rung, halt state, mode, and command-drain health."""
    from src.storage.models import AppCommandRow
    from src.storage.system_settings import (
        get_autonomy_level,
        get_halt_reason,
        is_halted,
    )

    now = datetime.now(UTC)
    level = get_autonomy_level()
    halted = is_halted()
    halt_reason = get_halt_reason() if halted else None
    mode = "live" if get_config().is_live else "paper"

    # drain_healthy: compare the drain heartbeat against twice the poll interval.
    # Do NOT reuse /health's worker_heartbeat — that reports the research worker
    # and would show green while the command drain is dead.
    poll_interval = get_config().execution.poll_interval_seconds
    drain_raw = read_setting(db, _DRAIN_HEARTBEAT_KEY)
    drain_last_seen = parse_setting_dt(drain_raw)
    drain_healthy = False
    if drain_last_seen is not None:
        age = now - drain_last_seen
        drain_healthy = age <= timedelta(seconds=poll_interval * 2)

    pending = db.execute(
        select(func.count()).select_from(AppCommandRow).where(AppCommandRow.status == "pending")
    ).scalar_one()

    # halted_at (M6 Task 6.3): the time the current halt was engaged, derived from the
    # most recent APPLIED `halt` command row — the command queue is the one place a
    # web halt's moment is recorded without a new settings key. A halt tripped by a
    # circuit breaker has no command row, so this is null and the banner honestly
    # renders no time rather than a fabricated one. Only meaningful while `halted`
    # is true. The halt search is bounded to after the most recent APPLIED `resume`
    # command: without that bound, a resume followed by a fresh, command-row-less
    # halt (a circuit-breaker trip, or a Telegram /halt — neither writes a row) would
    # surface the *previous* halt episode's timestamp instead of an honest null.
    halted_at: datetime | None = None
    if halted:
        last_resume_at = db.execute(
            select(func.max(AppCommandRow.applied_at)).where(
                AppCommandRow.kind == "resume", AppCommandRow.status == "applied"
            )
        ).scalar_one_or_none()
        halt_query = select(func.max(AppCommandRow.applied_at)).where(
            AppCommandRow.kind == "halt", AppCommandRow.status == "applied"
        )
        if last_resume_at is not None:
            halt_query = halt_query.where(AppCommandRow.applied_at > last_resume_at)
        halted_at = db.execute(halt_query).scalar_one_or_none()

    from src.api.models.options import AutonomyRung

    rungs = [AutonomyRung(level=lvl, label=lbl) for lvl, lbl in _RUNGS]
    # The active rung's label comes from _RUNGS so it cannot drift from the
    # rungs list (two sources of truth would let a renamed label diverge).
    active_label = next(
        (lbl for lvl, lbl in _RUNGS if lvl == level.value), level.value.capitalize()
    )
    return ControlsResponse(
        as_of=now,
        autonomy=AutonomyRung(level=level.value, label=active_label),
        rungs=rungs,
        halted=halted,
        halt_reason=halt_reason,
        halted_at=halted_at,
        mode=mode,  # type: ignore[arg-type]
        drain_healthy=drain_healthy,
        drain_last_seen=drain_last_seen,
        pending_commands=int(pending or 0),
    )
