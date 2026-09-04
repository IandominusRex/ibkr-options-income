"""Research routes: search today, the analysis payload from Milestone 3."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, or_, select

from src.api.deps import CurrentUser, ResearchDb
from src.api.models.common import Envelope, Source, Sourced
from src.api.models.research import AnalysisResponse, Bar, BarsResponse, NewsItem, Section
from src.common.schemas import SentimentDetail, TechnicalStats
from src.research.ingest.materialize import materialize
from src.research.schemas import NormalizedFinancials
from src.research.store.models import DailyBarRow, RecentlyViewedRow, SymbolRow

router = APIRouter(prefix="/research", tags=["research"])


class SearchHit(Envelope):
    symbol: str
    name: str
    exchange: str | None = None
    is_etf: bool = False


class SearchResponse(Envelope):
    query: str
    results: list[SearchHit]


@router.get("/search", response_model=SearchResponse)
def search(
    user: CurrentUser,
    db: ResearchDb,
    q: str = Query(default="", max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
) -> SearchResponse:
    """Rank: exact ticker, then ticker prefix, then name substring.

    Each band is alphabetical within itself. A blank query returns no results rather
    than the whole table.
    """
    now = datetime.now(UTC)
    term = q.strip()
    if not term:
        return SearchResponse(as_of=now, query=q, results=[])

    upper = term.upper()
    like_prefix = f"{upper}%"
    like_name = f"%{term.lower()}%"

    # Ranking bands: 0 exact ticker, 1 ticker prefix, 2 name substring.
    # `case` is portable across SQLite and Postgres (unlike `func.iif`).
    band = case(
        (SymbolRow.symbol == upper, 0),
        (SymbolRow.symbol.like(like_prefix), 1),
        else_=2,
    ).label("band")

    stmt = (
        select(SymbolRow, band)
        .where(
            or_(
                SymbolRow.symbol.like(like_prefix),
                func.lower(SymbolRow.name).like(like_name),
            )
        )
        .order_by(band, SymbolRow.symbol)
        .limit(limit)
    )

    rows = db.execute(stmt).all()
    return SearchResponse(
        as_of=now,
        query=q,
        results=[
            SearchHit(
                as_of=now,
                symbol=row[0].symbol,
                name=row[0].name,
                exchange=row[0].exchange,
                is_etf=row[0].is_etf,
            )
            for row in rows
        ],
    )


_RANGE_DAYS = {"1mo": 25, "3mo": 80, "6mo": 170, "1y": 365, "2y": 730, "5y": 1825}

# SMA 200 needs 200 prior closes to produce its first value. Fetching only the display
# range would leave the leading ~200 trading days of every chart's SMA200 as null (most
# of a 1y view). This buffer of calendar days comfortably covers 200 trading days
# (~280 calendar days with weekends/holidays) so the SMAs are seeded before the window.
_SMA_SEED_BUFFER_DAYS = 400


def _sma(closes: list[float], n: int) -> list[float | None]:
    """Simple moving average aligned to *closes*. ``None`` until n values exist."""
    out: list[float | None] = []
    running = 0.0
    for i, c in enumerate(closes):
        running += c
        if i >= n:
            running -= closes[i - n]
        out.append(round(running / n, 4) if i >= n - 1 else None)
    return out


@router.get("/{symbol}/bars", response_model=BarsResponse)
def bars(
    symbol: str,
    user: CurrentUser,
    db: ResearchDb,
    range: str = Query(default="1y", pattern="^(1mo|3mo|6mo|1y|2y|5y)$"),
) -> BarsResponse:
    """Daily OHLCV with server-side SMA 50 and 200, in lightweight-charts' field names.

    ``time`` is ``YYYY-MM-DD`` (lightweight-charts' accepted daily format). SMA 50 and 200
    are computed from ``daily_bars`` here so the chart and the technical panel can never
    disagree. A symbol with no bars returns empty lists, not an error.
    """
    now = datetime.now(UTC)
    upper = symbol.upper()

    row = db.get(SymbolRow, upper)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {upper}")

    days = _RANGE_DAYS.get(range, 365)
    display_cutoff = date.today().toordinal() - days
    seed_cutoff = display_cutoff - _SMA_SEED_BUFFER_DAYS
    rows = (
        db.query(DailyBarRow)
        .filter(DailyBarRow.symbol == upper)
        .filter(DailyBarRow.date >= date.fromordinal(seed_cutoff))
        .order_by(DailyBarRow.date)
        .all()
    )

    # SMAs are computed over the full seeded series so the display window's SMA200 is
    # populated from its first bar (not null for its first ~200 trading days), then both
    # the bars and the SMAs are sliced to the display range, staying index-aligned.
    closes = [float(r.close or 0.0) for r in rows]
    sma50_full = _sma(closes, 50)
    sma200_full = _sma(closes, 200)

    display_start = date.fromordinal(display_cutoff)
    start_idx = next((i for i, r in enumerate(rows) if r.date >= display_start), len(rows))

    bar_list = [
        Bar(
            time=r.date.isoformat(),
            open=float(r.open or 0.0),
            high=float(r.high or 0.0),
            low=float(r.low or 0.0),
            close=float(r.close or 0.0),
            volume=float(r.volume or 0.0),
        )
        for r in rows[start_idx:]
    ]
    return BarsResponse(
        as_of=now,
        bars=bar_list,
        sma50=sma50_full[start_idx:],
        sma200=sma200_full[start_idx:],
    )


@router.get("/{symbol}", response_model=AnalysisResponse)
def analysis(symbol: str, user: CurrentUser, db: ResearchDb) -> AnalysisResponse:
    """Full analysis for one symbol.

    404 only when the symbol is not a known filer. Everything else degrades per section.
    """
    now = datetime.now(UTC)
    upper = symbol.upper()

    row = db.get(SymbolRow, upper)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {upper}")

    view = db.get(RecentlyViewedRow, (user.id, upper))
    if view is None:
        db.add(RecentlyViewedRow(user_id=user.id, symbol=upper, viewed_at=now))
    else:
        view.viewed_at = now

    result = materialize(upper)

    # Quote provenance: the warm-tier quote row's as_of is what makes a stale price visibly
    # stale rather than silently wrong. When no quote has been ingested, the field is None
    # and the frontend renders the quote section as unavailable.
    quote_sourced: Sourced[float] | None = None
    if result.quote is not None and result.quote_as_of is not None:
        quote_sourced = Sourced[float].of(
            result.quote,
            Source.YFINANCE,
            result.quote_as_of,
            fresh_for=timedelta(minutes=30),
        )

    # The enrichment helpers return Pydantic models (TechnicalStats/SentimentDetail) or
    # None. Passing the model straight through lets the response schema validate the fields
    # and gives the generated TypeScript types their proper shape. A non-Pydantic object
    # (e.g. a bare dict from a test stub) is rejected — the Section's data stays None and the
    # state/reason carry the failure, so the page never renders a half-shaped payload.
    technicals_data: TechnicalStats | None = None
    if isinstance(result.technicals, TechnicalStats):
        technicals_data = result.technicals

    sentiment_data: SentimentDetail | None = None
    if isinstance(result.sentiment, SentimentDetail):
        sentiment_data = result.sentiment

    news_data: list[NewsItem] | None = None
    if result.news is not None:
        news_data = [
            NewsItem(
                title=str(item.get("title", "")),
                url=item.get("url"),
                published_at=item.get("published_at"),
                source=item.get("source"),
                sentiment=item.get("sentiment"),
            )
            for item in result.news
            if item.get("title")
        ]

    return AnalysisResponse(
        as_of=now,
        symbol=upper,
        name=row.name,
        exchange=row.exchange,
        is_etf=row.is_etf,
        fundamentals=Section[NormalizedFinancials](
            state=result.fundamentals_state,
            data=result.fundamentals,
            reason=result.fundamentals_reason or result.reason,
        ),
        technicals=Section[TechnicalStats](
            state=result.technicals_state,
            data=technicals_data,
            reason=result.technicals_reason,
        ),
        sentiment=Section[SentimentDetail](
            state=result.sentiment_state,
            data=sentiment_data,
            reason=result.sentiment_reason,
        ),
        news=Section[list[NewsItem]](
            state=result.news_state,
            data=news_data,
            reason=result.news_reason,
        ),
        quote=quote_sourced,
    )
