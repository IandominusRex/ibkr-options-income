"""Response models for GET /news/* (spec §7.6)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from src.api.models.common import Envelope


class NewsPostOut(BaseModel):
    id: int
    kind: str
    subject: str | None
    posted_at: datetime
    stage: str
    critical: bool
    silent: bool
    has_chart: bool
    payload: dict[str, Any]


class NewsFeedResponse(Envelope):
    available: bool
    posts: list[NewsPostOut] = []


class NewsPostDetailResponse(Envelope):
    available: bool
    post: NewsPostOut
    chart_data_uri: str | None = None


class EconEventOut(BaseModel):
    title: str
    scheduled_at: datetime
    impact: str
    forecast: str | None
    previous: str | None
    actual: str | None
    surprise_dir: str | None


class EarningsOut(BaseModel):
    symbol: str
    report_date: date
    timing: str
    eps_est: float | None
    eps_actual: float | None
    status: str
    held: bool = False


class NewsCalendarResponse(Envelope):
    available: bool
    econ: list[EconEventOut] = []
    earnings: list[EarningsOut] = []


class SourceLinkOut(BaseModel):
    name: str
    url: str


class ClusterOut(BaseModel):
    id: int
    headline: str
    source_count: int
    last_seen: datetime
    links: list[SourceLinkOut] = []


class NewsRequestOut(BaseModel):
    id: int
    status: str
    requested_at: datetime
    post_id: int | None
    error: str | None


class NewsTickerResponse(Envelope):
    available: bool
    symbol: str
    latest_brief: NewsPostOut | None = None
    clusters: list[ClusterOut] = []
    next_earnings: EarningsOut | None = None
    request: NewsRequestOut | None = None


class NewsStatusResponse(Envelope):
    available: bool
    heartbeat_at: datetime | None = None
    heartbeat_age_s: float | None = None
    sources_ok: dict[str, datetime] = {}
    # The news process's circuit breakers (closed/open/half_open), as of its last heartbeat.
    breakers: dict[str, str] = {}
    llm_calls_today: int = 0
    llm_cap: int = 0
