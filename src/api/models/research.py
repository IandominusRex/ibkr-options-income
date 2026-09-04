"""Response shapes for the research routes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from src.api.models.common import Envelope, Sourced
from src.common.schemas import SentimentDetail, TechnicalStats
from src.research.checks.payload import ChecksPayload
from src.research.ingest.materialize import SectionState
from src.research.schemas import NormalizedFinancials


class Section[T](BaseModel):
    """One region of the page, with its own state.

    A slow or missing section never fails the whole page. `reason` is rendered to the user
    verbatim, so it must read as an explanation rather than an exception string.
    """

    state: SectionState
    data: T | None = None
    reason: str | None = None


class NewsItem(BaseModel):
    """One news headline with its per-item VADER sentiment.

    ``sentiment`` is the VADER compound polarity in -1.0..+1.0 (0.0 = neutral/unavailable).
    The frontend renders it as a labelled chip (label + tint, never colour-only).
    """

    title: str
    url: str | None = None
    published_at: datetime | None = None
    source: str | None = None
    sentiment: float | None = None


class Bar(BaseModel):
    """One daily OHLCV bar in lightweight-charts' expected field names.

    ``time`` is a ``YYYY-MM-DD`` string (lightweight-charts accepts the date prefix of an
    ISO timestamp for a daily series). No client-side remapping is needed.
    """

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class BarsResponse(Envelope):
    """Daily bars with server-side SMA 50 and 200 overlays.

    ``sma50``/``sma200`` are parallel lists aligned to ``bars``: ``None`` until enough
    data exists to compute the moving average at that index, then the value. Computed
    server-side from ``daily_bars`` so the chart and the technical panel can never disagree.
    """

    bars: list[Bar] = []
    sma50: list[float | None] = []
    sma200: list[float | None] = []


class AnalysisResponse(Envelope):
    symbol: str
    name: str
    exchange: str | None = None
    is_etf: bool = False
    fundamentals: Section[NormalizedFinancials]
    technicals: Section[TechnicalStats] = Section[TechnicalStats](state=SectionState.PENDING)
    sentiment: Section[SentimentDetail] = Section[SentimentDetail](state=SectionState.PENDING)
    news: Section[list[NewsItem]] = Section[list[NewsItem]](state=SectionState.PENDING)
    checks: Section[ChecksPayload] = Section[ChecksPayload](state=SectionState.PENDING)
    quote: Sourced[float] | None = None
