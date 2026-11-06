"""Response models for the read-only value-book routes (value book Part 6, Task 13).

Every figure is Python's or the stored scorecard's. What Claude wrote is in ``ValueClaudeOut`` and
labelled ``source: "claude"``; it is never mixed into a Python field. Unknown is ``None``, never
``0``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.api.models.common import Envelope

ListName = Literal["deep_value", "quality_growth"]
DecidedBy = Literal["claude", "python"]
Computed = Literal["stored", "now", "pending"]


class ValueNextExit(BaseModel):
    kind: Literal["sell_half", "stop"]  # the half sale at fair value, then the stop
    level: float


class ValueTopItem(BaseModel):
    symbol: str
    list_name: ListName
    verdict: str  # the effective verdict (READY | WATCH | WAIT)
    decided_by: DecidedBy
    price: float | None = None
    fair_value: float | None = None  # the effective one
    entry_ceiling: float | None = None
    stop: float | None = None  # the live policy sets no stop before the half sale: unknown
    half_sell: float | None = None  # the level the half sale fires at once held
    mos: float | None = None  # a fraction
    reasons: list[str] = Field(default_factory=list)
    put_ceiling: float | None = None  # the wheel's value-suggested put ceiling
    age_days: int | None = None
    # Claude's own why for this list, as one line (value_claude_verdicts, the CLI backend only: a
    # local model's verdict never decides and is not Claude's). Labelled as Claude's on the web,
    # never on a button. None when Claude has not read the name for this list.
    claude_note: str | None = None


class ValueTopResponse(Envelope):
    available: bool  # False when data/value.db does not exist or cannot be read
    list_name: ListName
    items: list[ValueTopItem] = Field(default_factory=list)


class ValuePositionOut(BaseModel):
    id: int
    symbol: str
    list_name: str
    status: Literal["open", "closed"]
    shares: float
    avg_cost: float | None = None
    mark: float | None = None
    opened_at: date | None = None
    closed_on: date | None = None
    next_exit: ValueNextExit | None = None
    realised_usd: float | None = None  # None until a sale has filled, never 0.0


class ValuePositionsResponse(Envelope):
    available: bool
    status: Literal["open", "closed"]
    positions: list[ValuePositionOut] = Field(default_factory=list)


class ValueProposalOut(BaseModel):
    id: int
    kind: Literal["buy", "sell"]
    symbol: str
    list_name: str
    shares: float
    price: float | None = None  # the close it was sized at
    cost_usd: float | None = None
    reason: str
    cause: Literal["python", "claude"]
    needs_tap: bool
    status: str  # pending | approved | funding | sent
    created_at: datetime
    expires_at: datetime
    fingerprint: str  # what a tap must carry back (value_approve / value_reject)


class ValueFundingOut(BaseModel):
    id: int
    proposal_id: int
    symbol: str
    needed_usd: float
    created_at: datetime | None = None
    expires_at: datetime | None = None


class ValueBreakersOut(BaseModel):
    trend: bool | None = None  # SPY under its 10-month average: entries stop, the ceiling shrinks
    drawdown: bool | None = None  # the drawdown stop is on
    drawdown_pct: float | None = None  # down from the high, in percent; None before a snapshot
    trim_offered: bool = False
    trim_episode: str | None = None  # the id a value_trim command carries
    trimmed: bool = False


class ValueBookResponse(Envelope):
    available: bool
    enabled: bool  # value.book.enabled; the book idles in live whatever it says
    ceiling_usd: float | None = None
    used_usd: float | None = None
    positions: list[ValuePositionOut] = Field(default_factory=list)
    proposals: list[ValueProposalOut] = Field(default_factory=list)
    funding: list[ValueFundingOut] = Field(default_factory=list)
    breakers: ValueBreakersOut = Field(default_factory=ValueBreakersOut)
    release_max_closes: int  # release.max_closes_per_request: the K in the approval sentence
    # The value process's command drain (web overhaul Part 4): when it last checked for value_*
    # commands (system_settings ``value_drain_heartbeat``), and whether that is recent enough for a
    # pending tap to read as queued. Never-run is false with a null time, never true.
    drain_healthy: bool = False
    drain_last_seen: datetime | None = None


# --- the ticker file -------------------------------------------------------------------------------


class ValueGateOut(BaseModel):
    id: str
    group: Literal["data_quality", "health", "entry", "timing"]
    state: str  # pass | fail | unknown | not_applicable
    value: float | None = None  # the number the gate read
    threshold: float | None = None  # the bar it was held to
    detail: str = ""


class ValueMethodOut(BaseModel):
    method: str
    value: float | None = None
    state: str  # ok | absent | unreliable | not_applicable
    detail: str = ""
    used: bool = False  # one of the methods this list's fair value is the median of
    median: bool = False  # the method whose value is the fair value (a two-method mean has none)


class ValueListOut(BaseModel):
    list_name: ListName
    baseline_verdict: str  # Python's baseline for the list
    verdict: str  # the effective verdict
    decided_by: DecidedBy
    fair_value: float | None = None  # Python's
    effective_fair_value: float | None = None  # the one the gate reads
    mos: float | None = None  # the effective margin of safety, a fraction
    required_mos_pct: float | None = None
    entry_ceiling: float | None = None  # the effective one
    entry: str | None = None
    timing: str | None = None
    reasons: list[str] = Field(default_factory=list)
    mos_review: bool = False
    methods: list[ValueMethodOut] = Field(default_factory=list)
    gates: list[ValueGateOut] = Field(default_factory=list)  # this list's entry and timing checks
    # The size tier the effective margin of safety reaches (value.book.tiers, spec section 9.5), in
    # percent of the book's ceiling and capped at the name cap: 0.0 below the first tier, None when
    # the margin is unknown (never 0). A buy aims at it in ``tranches`` steps.
    size_pct: float | None = None
    tranches: int = 3  # value.book.tranches


class ValueFileOut(BaseModel):
    symbol: str
    as_of: date
    computed_at: datetime | None = None
    universe: str | None = None
    company_class: str
    data_quality: str
    health: str
    not_applicable_reason: str | None = None
    price: float | None = None
    ruleset_version: str
    ruleset_hash: str
    gates: list[ValueGateOut] = Field(default_factory=list)  # data quality and health
    lists: list[ValueListOut] = Field(default_factory=list)
    metrics: dict[str, float | None] = Field(default_factory=dict)
    reverse_dcf_implied_growth: float | None = None
    put_ceiling: float | None = None
    adjustments: list[str] = Field(default_factory=list)


class ValueDriverOut(BaseModel):
    name: str
    chosen: float | None = None  # what Claude picked
    used: float | None = None  # what Python used after clamping
    clamped: bool = False
    bound: Literal["lo", "hi"] | None = None  # the bound the pick was moved to


class ValueClaudeListOut(BaseModel):
    list_name: str
    verdict: str
    why: str = ""
    fair_value: float | None = None  # Python's arithmetic on the clamped drivers, capped
    python_fair_value: float | None = None
    cap_applied: bool = False  # the 1.5x cap bound
    unreliable: str | None = None
    drivers: list[ValueDriverOut] = Field(default_factory=list)
    clamps: list[str] = Field(default_factory=list)
    backend: str  # cli | ollama; an ollama verdict never decides


class ValueNoteOut(BaseModel):
    kind: str  # profile | why_cheap | thesis | bear_case | review
    text: str


class ValueKillTriggerOut(BaseModel):
    name: str
    threshold: float | None = None
    actual: float | None = None
    state: str | None = None  # fired | near | far | unknown
    distance_pct: float | None = None  # room left before it fires, as a percent of the threshold


class ValueFactOut(BaseModel):
    text: str
    quote: str
    filing: str


class ValueClaudeOut(BaseModel):
    source: Literal["claude"] = "claude"
    read_at: datetime | None = None
    lists: list[ValueClaudeListOut] = Field(default_factory=list)
    notes: list[ValueNoteOut] = Field(default_factory=list)
    kill_triggers: list[ValueKillTriggerOut] = Field(default_factory=list)
    facts: list[ValueFactOut] = Field(default_factory=list)


class ValueReevaluationOut(BaseModel):
    id: int
    list_name: str
    session: date | None = None
    last_session: date | None = None
    severity: Literal["major", "minor"]
    triggers: list[dict[str, Any]] = Field(default_factory=list)
    plan_before: dict[str, Any] = Field(default_factory=dict)
    plan_after: dict[str, Any] = Field(default_factory=dict)
    review_state: str | None = None


class ValuePlanOut(BaseModel):
    position_id: int
    list_name: str
    opened_at: date | None = None
    shares: float
    avg_cost: float | None = None
    next_exit: ValueNextExit | None = None
    stop: float | None = None
    half_sold: bool = False
    fair_value: float | None = None
    effective_fair_value: float | None = None
    tranches_done: int | None = None  # how many of the tranches have been bought
    tranches: int = 3  # value.book.tranches
    tranche_min_sessions: int = 5  # value.book.tranche_min_sessions: sessions between two
    last_tranche_on: date | None = None


class ValueTickerResponse(Envelope):
    available: bool
    symbol: str
    computed: Computed = "stored"
    age_days: int | None = None
    file: ValueFileOut | None = None
    claude: ValueClaudeOut | None = None
    reevaluations: list[ValueReevaluationOut] = Field(default_factory=list)
    plan: ValuePlanOut | None = None
