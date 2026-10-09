"""Schemas for the news service. Views are the read-side types; nothing passes ORM rows
across a module boundary (CLAUDE.md). Later tasks add Fact/FactSheet (13), card payloads (15)
and LLM outputs (23)."""

from __future__ import annotations

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
