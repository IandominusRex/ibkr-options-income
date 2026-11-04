"""Plain shapes between the value book and Claude (value book spec §8).

Neutral on purpose, like ``value_types.py``: standard library and pydantic only, so
``src/value/`` (deterministic, the only writer of value.db) and ``src/value_ai/`` (enrichment,
the only caller of Claude for the value book) share one definition without either importing the
other (tests/test_value_fence.py). Claude never sees a database row and ``src/value/`` never sees
a prompt: a request goes out as an ``AnalystRequest`` and comes back as an ``AnalystResult``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ReadKind = Literal["standard", "filing", "review"]
ClaudeVerdict = Literal["READY", "WATCH", "WAIT", "NO"]
ReviewState = Literal["INTACT", "WEAKENED", "BROKEN"]
Backend = Literal["cli", "ollama"]
KillKind = Literal[
    "revenue_growth_below",
    "fcf_ttm_negative",
    "net_debt_to_ebitda_above",
    "dilution_above",
    "gross_margin_below",
    "guidance_cut",
    "customer_loss",
]
KILL_KINDS: tuple[str, ...] = (
    "revenue_growth_below",
    "fcf_ttm_negative",
    "net_debt_to_ebitda_above",
    "dilution_above",
    "gross_margin_below",
    "guidance_cut",
    "customer_loss",
)
FactKind = Literal[
    "one_off",
    "segment_revenue",
    "guidance",
    "backlog",
    "customer_concentration",
    "covenant",
    "share_class_count",
    "guidance_cut",
    "customer_loss",
]
FACT_KINDS: tuple[str, ...] = (
    "one_off",
    "segment_revenue",
    "guidance",
    "backlog",
    "customer_concentration",
    "covenant",
    "share_class_count",
    "guidance_cut",
    "customer_loss",
)


class Range(BaseModel):
    lo: float
    hi: float


class DriverBounds(BaseModel):
    """Where Claude's drivers for one list must sit (spec §8.2), computed by Python from the
    company's own history. ``method`` ``dcf``: growth, terminal, discount, margin; ``ptbv``
    (banks and insurers): rote, terminal, discount."""

    list_name: str
    method: Literal["dcf", "ptbv"]
    growth: Range | None = None
    terminal: Range
    discount: Range
    margin: Range | None = None
    rote: Range | None = None


class Drivers(BaseModel):
    """Claude's assumptions for one list. Fractions (0.12 = 12%). Unknown is None."""

    growth: float | None = None  # FCF/share growth, years 1-5
    terminal: float | None = None
    discount: float | None = None
    margin: float | None = None  # normalised FCF margin
    rote: float | None = None  # sustainable return on tangible equity


class FilingSection(BaseModel):
    """One slice of a filing the research worker cut out (spec §8.5): Item 1, 1A, 7, ..."""

    accn: str
    form: str
    section: str
    text: str


class AnalystRequest(BaseModel):
    """One read, as the value process hands it to ``src/value_ai/``."""

    read_id: int
    symbol: str
    kind: ReadKind
    reason: str  # request | review | filing | top | stale
    lists: list[str]
    card_text: str  # the scorecard, rendered by src/value as labelled numbers
    bounds: list[DriverBounds] = Field(default_factory=list)
    kill_menu: dict[str, Range | None] = Field(default_factory=dict)
    max_kill_triggers: int = 5
    trigger_text: str = ""  # a review: what fired, the plan before and after
    sections: list[FilingSection] = Field(default_factory=list)  # a filing read
    model: str = ""
    effort: str = ""
    timeout_seconds: float = 240.0


class ListCall(BaseModel):
    list_name: str
    verdict: ClaudeVerdict
    why: str = ""
    drivers: Drivers = Field(default_factory=Drivers)


class KillTrigger(BaseModel):
    kind: KillKind
    threshold: float | None = None  # in the menu's unit; None for the fact-based kinds


class ProposedFact(BaseModel):
    """A number or claim Claude read in a filing, with the accession and a verbatim quote, for
    ``src/value/grounding.py`` to check (spec §8.2 "Grounded facts")."""

    kind: FactKind
    value: float | None = None
    unit: str = ""
    accn: str
    quote: str
    item: str | None = None  # a canonical XBRL item (revenue, sbc, ...) when it is one


class AnalystReply(BaseModel):
    """A reply that passed the shape check. Nothing here has been bounded or verified yet."""

    lists: list[ListCall] = Field(default_factory=list)
    profile: str = ""
    why_cheap: str = ""
    thesis: str = ""
    bear_case: str = ""
    kill_triggers: list[KillTrigger] = Field(default_factory=list)
    review_state: ReviewState | None = None
    review_why: str = ""
    facts: list[ProposedFact] = Field(default_factory=list)


class AnalystCall(BaseModel):
    """What the call cost and who answered. ``backend`` ``ollama`` is never effective."""

    model: str = ""
    backend: Backend = "cli"
    latency_ms: int = 0
    cost_usd: float | None = None
    error: str | None = None
    prompt_version: str = ""
    prompt: str = ""
    raw: str = ""


class AnalystResult(BaseModel):
    read_id: int
    reply: AnalystReply | None = None  # None: no notes (a failure or a malformed reply)
    call: AnalystCall = Field(default_factory=AnalystCall)
