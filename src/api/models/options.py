"""Response shapes for the options console read surfaces (P2 Milestone 2).

Every route is owner-only and reads through the ``mode=ro`` trading engine. No
``null`` numeric renders as ``0``; the snapshot is the source of truth for what the
human was shown, and joined rows are enrichment whose absence must never 500.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.api.models.common import Envelope, Sourced

# ---------------------------------------------------------------------------
# Shared sub-shapes
# ---------------------------------------------------------------------------


class IdealZonePayload(BaseModel):
    """The denormalised ideal zone from ``RiskVerdictRow`` (lo / hi / min_credit)."""

    lo: float | None = None
    hi: float | None = None
    min_credit: float | None = None


class ClaudeReviewPayload(BaseModel):
    """Claude's five review fields, surfaced separately — never one prose blob.

    Telegram renders these as one chat bubble; the console renders them as five
    labelled sections beside the numbers they refer to. ``rolling_considerations``
    is the fifth and may be empty on the full-universe path.
    """

    why_attractive: str = ""
    risks: str = ""
    tradeoffs: str = ""
    assignment_considerations: str = ""
    rolling_considerations: str = ""
    recommendation: str | None = None
    priority: int | None = None
    confidence: float | None = None


class AlternativeStrike(BaseModel):
    """Another contract assessed on the same underlying during the same run."""

    candidate_id: str
    strategy: str
    strike: float
    expiry: date | None = None
    right: str | None = None
    blended_score: float | None = None
    premium: float | None = None
    stage: str | None = None
    reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Approvals (Task 2.1)
# ---------------------------------------------------------------------------


ApprovalStatusLit = Literal["pending", "approved", "rejected", "expired"]
ApprovalSourceLit = Literal["scan", "roll"]


class ApprovalSummary(Envelope):
    """One row in the approvals list."""

    id: int
    candidate_id: str
    status: ApprovalStatusLit
    underlying: str
    strategy: str
    right: str
    strike: float
    expiry: date | None = None
    contracts: int
    premium: float | None = (
        None  # per share, always; null only for a pruned snapshot with no premium
    )
    blended_score: float | None = None
    expires_at: datetime | None = None
    decided_at: datetime | None = None
    order_state: str | None = None  # joined from OrderRow when one exists
    source: ApprovalSourceLit  # derived from the candidate's run_id prefix


class ApprovalDetail(ApprovalSummary):
    """One approval in full, with the joined enrichment."""

    snapshot: dict  # the frozen payload the human was shown
    ideal: IdealZonePayload | None = None  # lo, hi, min_credit, from RiskVerdictRow
    gate_reasons: list[str] = Field(default_factory=list)  # humanised
    review: ClaudeReviewPayload | None = None  # the five fields, separately, never one blob
    alternatives: list[AlternativeStrike] = Field(default_factory=list)


class ApprovalListResponse(Envelope):
    approvals: list[ApprovalSummary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Assessed (Task 2.2)
# ---------------------------------------------------------------------------


AssessedStageLit = Literal["generator", "risk_gate", "score_floor", "dedupe", "top_n", "passed"]


class AssessedContract(Envelope):
    candidate_id: str
    symbol: str
    strategy: str
    strike: float | None = None
    expiry: date | None = None
    stage: AssessedStageLit
    reasons: list[str] = Field(default_factory=list)  # raw codes
    reasons_text: list[str] = Field(default_factory=list)  # humanised
    blended_score: float | None = None
    premium: float | None = None
    ideal: IdealZonePayload | None = None
    promotable: bool
    promote_note: str | None = None  # why not, when promotable is false


class AssessedGroup(Envelope):
    symbol: str
    contracts: list[AssessedContract] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)  # per stage


class AssessedResponse(Envelope):
    run_id: str | None = None
    computed_at: datetime | None = None
    groups: list[AssessedGroup] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Orders and fills (Task 2.3)
# ---------------------------------------------------------------------------


OrderStateLit = Literal["queued", "submitted", "filled", "partial", "cancelled", "rejected"]


class OrderSummary(Envelope):
    id: int
    candidate_id: str
    approval_id: int | None = None
    underlying: str
    strategy: str
    strike: float
    expiry: date | None = None
    state: OrderStateLit
    limit_price: float | None = None
    filled_qty: float
    avg_fill_price: float | None = None
    is_live: bool
    detail: str | None = None
    created_at: datetime
    updated_at: datetime


class OrderListResponse(Envelope):
    orders: list[OrderSummary] = Field(default_factory=list)


class FillSummary(Envelope):
    id: int
    order_id: int
    candidate_id: str
    action: str
    filled_qty: float
    avg_price: float
    commission: float | None = None
    is_live: bool
    filled_at: datetime


class FillListResponse(Envelope):
    fills: list[FillSummary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Shorts (Task 2.4)
# ---------------------------------------------------------------------------


class RollAlertSummary(BaseModel):
    id: int
    trigger: str  # the raw code, kept for audit
    # Human-readable label through the same mapping the Telegram formatter uses (M5 Task 5.3).
    # `src/monitor/triggers.py::humanize_trigger` is the single source; the API imports it, the
    # formatter imports it, the web renders this field verbatim — no second mapping anywhere.
    trigger_label: str
    detail: str
    # Claude's recommendation on the alert, labelled as a model opinion on the row — enrichment,
    # never a deterministic number. Carried from RollAlertRow.claude_recommendation (nullable).
    claude_recommendation: str | None = None
    created_at: datetime


class ShortPosition(Envelope):
    position_symbol: str  # the OCC option symbol
    underlying: str
    right: Literal["C", "P"]
    strike: float
    expiry: date | None = None  # null when the snapshot carried no expiry — never fabricated
    dte: int | None = None  # null when expiry is unknown; never 0 for a live short
    contracts: int
    avg_cost: float | None = None
    mark: float | None = None
    unrealized_pnl: float | None = None
    pnl_pct: float | None = None
    delta: Sourced[float] | None = None  # provenance matters: BS-derived is not IBKR-derived
    assignment_risk: bool
    alerts: list[RollAlertSummary] = Field(default_factory=list)


class ShortListResponse(Envelope):
    shorts: list[ShortPosition] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Controls (Task 2.5)
# ---------------------------------------------------------------------------


class AutonomyRung(BaseModel):
    level: str
    label: str


class ControlsResponse(Envelope):
    autonomy: AutonomyRung
    rungs: list[AutonomyRung] = Field(default_factory=list)
    halted: bool
    halt_reason: str | None = None
    # When the current halt was engaged: the most recent applied `halt` command's
    # applied_at. Null when halted by a circuit breaker (no command row) — the
    # console then renders the banner without a time rather than fabricating one
    # (M6 Task 6.3). No separate settings key exists for this, by design.
    halted_at: datetime | None = None
    mode: Literal["paper", "live"]
    drain_healthy: bool
    drain_last_seen: datetime | None = None
    pending_commands: int
