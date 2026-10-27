"""Response models for GET /claude/context (market picture spec section 11).

The page is read-only and shows what each Claude call is given. Every number on it was computed
by Python; the picture and the dossiers carry Claude's text, which the page labels as Claude's.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.api.models.common import Envelope
from src.common.schemas import (
    DossierEvent,
    DossierFact,
    DossierReported,
    MarketPicture,
    MarketRegime,
    RegimeState,
)


class RegimeLimitOut(BaseModel):
    """What one index's regime does to new cash-secured puts (``regime.csp`` in
    ``risk_limits.yaml``). Percentages are of the unscaled limit."""

    index: Literal["SPY", "QQQ"]
    regime: MarketRegime
    budget_pct: float
    per_trade_pct: float
    max_new_per_day: int | None  # None: no daily limit in this regime
    floor_new_per_day: int  # lots a day the budget cannot stop (spec decision 31)


class LeveragedLimitOut(BaseModel):
    """A leveraged ETF's per-trade ceiling as a fraction of the regime's own (ruling 35)."""

    symbol: str
    leverage: int
    calm_fraction: float
    stressed_fraction: float


class CallContextOut(BaseModel):
    """One Claude call and the context blocks its prompt carries (static: ``claude_calls.CALLS``)."""

    kind: str
    label: str
    blocks: list[str]


class DroppedOut(BaseModel):
    """A story the triage kept out of the picture, or one the market reaction promoted later."""

    cluster_id: int
    headline: str
    reason: str  # why it was dismissed (Claude's words, or the floor's)
    judged_at: datetime | None
    promoted: bool
    promoted_move_pct: float | None


class DossierOut(BaseModel):
    """One name's notes: Python's numbers and health, Claude's story and profile, verified events."""

    symbol: str
    kind: Literal["stock", "etf", "leveraged_etf"]
    health: Literal["strong", "ok", "weak", "n/a", "unknown"]
    health_why: list[str] = Field(default_factory=list)
    held: bool
    story: str
    story_evidence: list[str] = Field(default_factory=list)
    # Figures quoted from the cited news, kept apart from the story (the story carries only the
    # system's numbers). Each was checked against the cited cluster's text.
    reported: list[DossierReported] = Field(default_factory=list)
    events: list[DossierEvent] = Field(default_factory=list)
    profile: str
    facts: list[DossierFact] = Field(default_factory=list)
    facts_at: datetime
    prose_at: datetime | None
    stale: bool


class ClaudeContextResponse(Envelope):
    available: bool  # news.db is present (the picture, the dropped list and the notes need it)
    picture: MarketPicture | None = None
    regime: RegimeState | None = None
    regime_enabled: bool = True  # ``regime.enabled`` in risk_limits.yaml
    suspended_today: bool = False  # ``/regime off`` was sent today (ET)
    limits: list[RegimeLimitOut] = Field(default_factory=list)
    leveraged_enabled: bool = True  # ``leveraged_sizing.enabled``
    leveraged: list[LeveragedLimitOut] = Field(default_factory=list)
    claude_cut_mode: Literal["applied", "record_only"] = "record_only"
    # Today's daily breaker has tripped (Claude zeroed most of the day's auto CSPs): cuts are
    # recorded but not applied for the rest of the ET day, whatever the mode says.
    claude_cut_breaker_tripped_today: bool = False
    account_mode: Literal["paper", "live"] = "paper"
    calls: list[CallContextOut] = Field(default_factory=list)
    dropped: list[DroppedOut] = Field(default_factory=list)
    dropped_total: int = 0  # how many dropped stories there were (the list is capped)
    not_reviewed_7d: int = 0
    dossiers: list[DossierOut] = Field(default_factory=list)
    without_notes: list[str] = Field(default_factory=list)  # covered names with no dossier yet


class SizingActionOut(BaseModel):
    """One row of the sizing record (``sizing_actions``): a cash-secured put the regime, the
    scale-in ladder, the leveraged-ETF ceiling or Claude's cut trimmed or held back."""

    id: int
    created_at: datetime
    underlying: str
    right: str
    strike: float
    expiry: date
    premium: float
    kind: str  # regime_budget | scale_in_zone | loss_exit_cooldown | claude_cut | ...
    regime: str
    deterministic_contracts: int  # what the rules alone would have sent
    sent_contracts: int  # what was sent (0 when the put was held back)
    reason: str
    order_id: int | None = None


class SizingActionsResponse(Envelope):
    day: date  # the New York day shown
    actions: list[SizingActionOut] = Field(default_factory=list)
