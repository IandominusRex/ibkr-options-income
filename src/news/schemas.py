"""Schemas for the news service. Views are the read-side types; nothing passes ORM rows
across a module boundary (CLAUDE.md). Later tasks add Fact/FactSheet (13), card payloads (15)
and LLM outputs (23)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ItemView(BaseModel):
    title: str
    url: str | None = None
    source: str | None = None
    source_domain: str | None = None
    published_at: datetime | None = None
    summary: str | None = None
    image_url: str | None = None
    det_sentiment: float | None = None


class ClusterView(BaseModel):
    id: int
    headline: str
    category: str
    first_seen: datetime
    last_seen: datetime
    source_count: int
    source_domains: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    topic_class: str = "other"
    items: list[ItemView] = Field(default_factory=list)


class EconEventView(BaseModel):
    event_key: str
    title: str
    playbook_key: str | None = None
    scheduled_at: datetime
    impact: str
    forecast: str | None = None
    previous: str | None = None
    consensus: str | None = None
    actual: str | None = None
    surprise_dir: str | None = None


class EarningsView(BaseModel):
    symbol: str
    report_date: date
    timing: str = "unknown"
    eps_est: float | None = None
    eps_actual: float | None = None
    rev_est: float | None = None
    rev_actual: float | None = None
    status: str = "scheduled"


_NUM = re.compile(r"[-+]?\d[\d,]*\.?\d*")


class Fact(BaseModel):
    id: str
    label: str
    value: float | None = None
    display: str


class FactSheet(BaseModel):
    """Numbered facts (F1…Fk) computed by deterministic code — the LLM's only source of numbers
    (spec §6.1) and the grounding checker's reference set (§6.6)."""

    facts: list[Fact] = Field(default_factory=list)
    flags: dict[str, list[str]] = Field(default_factory=dict)

    def add(self, label: str, value: float | None, display: str) -> Fact:
        f = Fact(id=f"F{len(self.facts) + 1}", label=label, value=value, display=display)
        self.facts.append(f)
        return f

    def get(self, label: str) -> Fact | None:
        return next((f for f in self.facts if f.label == label), None)

    def flag(self, name: str, *evidence: Fact | None) -> None:
        self.flags[name] = [f.id for f in evidence if f is not None]

    def ids(self) -> set[str]:
        return {f.id for f in self.facts}

    def numbers(self) -> list[float]:
        out = [f.value for f in self.facts if f.value is not None]
        for f in self.facts:
            for m in _NUM.findall(f.display):
                try:
                    out.append(float(m.replace(",", "")))
                except ValueError:
                    continue
        return out

    def render(self) -> str:
        lines = [f"{f.id} {f.label}: {f.display}" for f in self.facts]
        lines += [f"FLAG {name} ← {', '.join(ev) or '-'}" for name, ev in self.flags.items()]
        return "\n".join(lines)


Verdict = Literal[
    "further_downside_likely",
    "further_upside_likely",
    "overreaction_likely",
    "priced_in",
    "unclear",
]
Confidence = Literal["low", "medium", "high"]
CardKind = Literal[
    "macro_print",
    "earnings",
    "market_move",
    "vix_spike",
    "ticker_move",
    "breaking",
    "brief",
    "digest_premarket",
    "digest_close",
    "digest_week",
]


class Explanation(BaseModel):
    """The writer pass's output (spec §6.5). Budgets are enforced here, not by asking nicely."""

    headline: str = Field(max_length=80)
    what_happened: str = Field(max_length=180)
    read: str = Field(max_length=240)
    bull: str = Field(max_length=100)
    bear: str = Field(max_length=100)
    verdict: Verdict
    confidence: Confidence
    book_impact: str = Field(default="", max_length=200)
    setup_impact: str = Field(default="", max_length=160)
    evidence: list[str] = Field(default_factory=list)


class DigestRead(BaseModel):
    """One thread's read inside a digest — produced by ONE batched writer call per digest (Task 24)."""

    cluster_id: int
    headline: str = Field(max_length=80)
    read: str = Field(max_length=200)
    verdict: Verdict
    evidence: list[str] = Field(default_factory=list)


class DigestReads(BaseModel):
    items: list[DigestRead] = Field(default_factory=list, max_length=10)


class EditorThread(BaseModel):
    cluster_ids: list[int] = Field(min_length=1)
    title: str = Field(max_length=80)


class EditorOutput(BaseModel):
    """The editor pass (spec §6.5 pass 1): regime, ranked threads, dropped noise."""

    regime: Literal["risk_on", "risk_off", "rotation", "mixed"]
    threads: list[EditorThread] = Field(default_factory=list, max_length=10)
    dropped: list[int] = Field(default_factory=list)


class SourceLink(BaseModel):
    name: str
    url: str


class GridRow(BaseModel):
    asset: str
    textbook: str | None = None
    actual: str | None = None


class DigestItem(BaseModel):
    text: str
    read: str | None = None
    verdict: Verdict | None = None
    links: list[SourceLink] = Field(default_factory=list)


class DigestSection(BaseModel):
    title: str
    items: list[DigestItem] = Field(default_factory=list)


class CardPayload(BaseModel):
    """Everything a post shows — rendered to Telegram HTML here and to React on the web (§7.6)."""

    kind: CardKind
    subject: str | None = None
    title: str
    emoji: str
    when: datetime
    headline_line: str | None = None
    facts_line: str | None = None
    grid: list[GridRow] = Field(default_factory=list)
    grid_note: str | None = None
    facts: FactSheet | None = None
    explanation: Explanation | None = None
    trimmed: bool = False
    llm_note: str | None = None
    regime: str | None = None
    sections: list[DigestSection] = Field(default_factory=list)
    links: list[SourceLink] = Field(default_factory=list)
    image_url: str | None = None
    preview_url: str | None = None
    critical: bool = False
    updates: list[str] = Field(default_factory=list)
    cluster_ids: list[int] = Field(default_factory=list)
    event_keys: list[str] = Field(default_factory=list)
