"""Schemas for the news service. Views are the read-side types; nothing passes ORM rows
across a module boundary (CLAUDE.md). Later tasks add Fact/FactSheet (13), card payloads (15)
and LLM outputs (23)."""

from __future__ import annotations

import re
from datetime import date, datetime

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
