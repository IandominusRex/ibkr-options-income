"""Response shapes for the research routes."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from src.api.models.common import Envelope, Sourced
from src.common.schemas import SentimentDetail, TechnicalStats
from src.research.checks.engine import CheckResult
from src.research.checks.payload import ChecksPayload
from src.research.checks.warnings import Warning as CheckWarning
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


class BuyCandidateOut(BaseModel):
    """One buy-to-own recommendation, rendered exactly as the scan scored it.

    The web layer does no re-scoring: every field below is the value
    ``generate_buy_candidates`` produced at scan time, persisted via
    ``BuyCandidateRow`` and read back unmodified so the site and Telegram can never
    disagree about what the system thinks.
    """

    symbol: str
    score: float
    sector: str | None = None
    iv_rank: float | None = None
    quality_flag: bool | None = None
    technical_regime: str | None = None
    rationale: str = ""
    price: float | None = None
    current_iv: float | None = None
    hv_30: float | None = None
    vrp: float | None = None
    rsi_14: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    next_earnings: date | None = None
    dividend_yield: float | None = None
    est_monthly_cc_yield: float | None = None
    iv_score: float | None = None
    fundamental_score: float | None = None
    technical_score: float | None = None


class RecommendationsResponse(Envelope):
    """``GET /research/recommendations`` — the buy list the scan produced.

    ``computed_at`` is the most recent full scan's compute time (the run the displayed
    candidates came from). ``as_of`` is the request time. ``candidates`` is empty (not
    an error) when no full scan has run yet; the route still returns 200 in that case.
    """

    computed_at: datetime | None = None
    candidates: list[BuyCandidateOut] = []


class SectorMover(BaseModel):
    """One symbol and its daily change, for the best/worst corner of a sector card."""

    symbol: str
    change_pct: float | None = None


class SectorCard(BaseModel):
    """One sector's aggregate summary for the landing-page grid.

    ``avg_iv_rank`` is the differentiator: where premium is rich today, at a glance —
    no consumer research site shows it. ``iv_rank_count`` is the number of members that
    actually contributed to that average, so a one-name average is visible as such
    (and ``avg_iv_rank`` is ``None`` when no member has IV history).
    ``change_pct`` is ``None`` (never ``0``) when no member has a priced quote.
    Cards are ordered by ``avg_iv_rank`` descending on the client, since premium
    richness is the reason to look.
    """

    sector: str
    count: int
    change_pct: float | None = None
    best: SectorMover
    worst: SectorMover
    avg_iv_rank: float | None = None
    iv_rank_count: int = 0


class SectorsResponse(Envelope):
    """``GET /research/sectors`` — the sector card grid."""

    sectors: list[SectorCard] = []


class WatchlistItem(BaseModel):
    """One row of the user's watchlist, with the fields the landing table needs.

    ``price`` ships as ``Sourced<float>`` so its provenance and staleness are explicit.
    ``checks`` is the aggregate {passed, evaluable, unknown} — the full per-check payload
    lives on the ticker page (M5), one click away. ``iv_rank`` is read-only from the
    trading DB's iv_history; ``None`` when the symbol has no IV history.
    """

    symbol: str
    name: str
    price: Sourced[float] | None = None
    change_pct: float | None = None
    iv_rank: float | None = None
    checks: dict[str, int]
    next_earnings: date | None = None


class WatchlistResponse(Envelope):
    """``GET /watchlist`` — the user's tracked symbols, scoped to their user_id."""

    items: list[WatchlistItem] = []


class OptionsCoverage(BaseModel):
    """What the on-demand options lens could actually check.

    ``option_chain`` is always ``false`` in P1 — the API process holds no IBKR
    connection, so ``atm_open_interest``/``atm_spread_pct`` stay ``UNKNOWN`` and the
    response says so rather than the UI quietly showing blanks.
    """

    iv_history: bool
    option_chain: bool = False


class OptionsLensResponse(Envelope):
    """``GET /research/{symbol}/options`` — the on-demand options-income checks lens.

    ``in_universe``/``tier`` reflect whether *symbol* is one of the ~46 `universe.yaml`
    names (the "hot" tier, with full IV history) or anything else ("cold", best-effort).
    ``checks`` is the catalogue's `options` category only. `iv_rank`/`vrp_points` are read
    real from the trading DB for a universe name; for an off-universe name with no
    `iv_history` they resolve to `UNKNOWN` rather than a percentile invented from a short
    series — `coverage.iv_history` names which case applied.
    """

    symbol: str
    in_universe: bool
    tier: Literal["hot", "cold"]
    checks: list[CheckResult] = []
    warnings: list[CheckWarning] = []
    coverage: OptionsCoverage
