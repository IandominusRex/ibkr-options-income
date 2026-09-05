"""Research routes: search today, the analysis payload from Milestone 3."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, or_, select

from src.api.deps import CurrentUser, ResearchDb, TradingDb
from src.api.models.common import Envelope, Source, Sourced
from src.api.models.research import (
    AnalysisResponse,
    Bar,
    BarsResponse,
    BuyCandidateOut,
    NewsItem,
    OptionsCoverage,
    OptionsLensResponse,
    RecommendationsResponse,
    Section,
    SectorCard,
    SectorMover,
    SectorsResponse,
)
from src.common.config import get_config
from src.common.schemas import FundamentalStats, IVStats, SentimentDetail, TechnicalStats
from src.research.checks.metrics import build_metrics
from src.research.checks.payload import ChecksPayload, build_checks_payload
from src.research.ingest.materialize import materialize
from src.research.schemas import NormalizedFinancials
from src.research.store.models import DailyBarRow, QuoteRow, RecentlyViewedRow, SymbolRow
from src.storage.buy_candidates import SINGLE_TICKER_PREFIX, latest_buy_candidates_from

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


@router.get("/recommendations", response_model=RecommendationsResponse)
def recommendations(
    user: CurrentUser,
    trading: TradingDb,
    limit: int = Query(default=25, ge=1, le=100),
) -> RecommendationsResponse:
    """The scan's buy-to-own list, rendered exactly as it was scored.

    Reads ``BuyCandidateRow`` through the **read-only** trading session (§4.3 — the API
    writes nothing). The web layer does no re-scoring: every field is what
    ``generate_buy_candidates`` produced at scan time, so the site and the Telegram card
    can never disagree about what the system thinks. An empty table returns an empty
    list with a 200, not a 404 — no scan has run yet is a legitimate state.
    """
    now = datetime.now(UTC)
    cands = latest_buy_candidates_from(trading, limit=limit)

    computed_at: datetime | None = None
    if cands:
        # computed_at is the stamp of the run the displayed candidates came from.
        # Filter out single-ticker `scan-` runs so a `/scan NVDA` cannot re-stamp
        # the recommendations page with the one-name run's time.
        from src.storage.models import BuyCandidateRow

        row = (
            trading.execute(
                select(BuyCandidateRow.computed_at, BuyCandidateRow.run_id)
                .where(~BuyCandidateRow.run_id.like(f"{SINGLE_TICKER_PREFIX}%"))
                .order_by(BuyCandidateRow.computed_at.desc(), BuyCandidateRow.run_id.desc())
                .limit(1)
            )
        ).first()
        if row is not None:
            computed_at = row[0]

    return RecommendationsResponse(
        as_of=now,
        computed_at=computed_at,
        candidates=[
            BuyCandidateOut(
                symbol=c.symbol,
                score=c.score,
                sector=c.sector,
                iv_rank=c.iv_rank,
                quality_flag=c.quality_flag,
                technical_regime=(
                    str(c.technical_regime) if c.technical_regime is not None else None
                ),
                rationale=c.rationale,
                price=c.price,
                current_iv=c.current_iv,
                hv_30=c.hv_30,
                vrp=c.vrp,
                rsi_14=c.rsi_14,
                sma_50=c.sma_50,
                sma_200=c.sma_200,
                next_earnings=c.next_earnings,
                dividend_yield=c.dividend_yield,
                est_monthly_cc_yield=c.est_monthly_cc_yield,
                iv_score=c.iv_score,
                fundamental_score=c.fundamental_score,
                technical_score=c.technical_score,
            )
            for c in cands
        ],
    )


@router.get("/sectors", response_model=SectorsResponse)
def sectors(
    user: CurrentUser,
    db: ResearchDb,
    trading: TradingDb,
) -> SectorsResponse:
    """Sector cards: aggregate daily change, best/worst mover, count, and average IV rank.

    Membership comes from ``universe.yaml``'s ``sectors`` map (every universe symbol tagged
    with its sector). ``change_pct`` is the warm-tier quote's daily change from the research
    DB; a sector with no priced members reports ``change_pct`` as ``None``, never ``0``.
    ``avg_iv_rank`` averages only members that actually have IV history in the trading DB
    (read-only), and the card carries the contributing count so a one-name average is visible.

    Cards are returned ordered by ``avg_iv_rank`` descending (premium richness is the
    reason to look); sectors with no IV history sort last, preserving their file order.
    """
    now = datetime.now(UTC)
    u = get_config().universe
    sector_map: dict[str, str] = {str(k): str(v) for k, v in (u.get("sectors") or {}).items()}

    # Members of a sector = every universe symbol tagged with that sector.
    members_by_sector: dict[str, list[str]] = {}
    for symbol, sector in sector_map.items():
        members_by_sector.setdefault(sector, []).append(symbol)

    # Warm-tier quotes (research DB): the daily change for each priced member.
    quote_rows = db.execute(select(QuoteRow)).scalars().all()
    change_by_symbol: dict[str, float | None] = {q.symbol: q.change_pct for q in quote_rows}

    # IV rank per symbol from the trading DB's iv_history (read-only). Replicates the
    # rank formula in src/analytics/iv.py but reads through the read-only session so the
    # API honours §4.3. A symbol with no history contributes nothing to its sector's avg.
    from src.storage.models import IVHistoryRow

    iv_rank_by_symbol: dict[str, float] = {}
    for symbol in sector_map:
        rows = (
            (
                trading.execute(
                    select(IVHistoryRow.iv)
                    .where(IVHistoryRow.symbol == symbol)
                    .order_by(IVHistoryRow.obs_date.desc())
                    .limit(365)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            continue
        history = list(rows)
        current = history[0]
        lo, hi = min(history), max(history)
        if hi != lo:
            iv_rank_by_symbol[symbol] = round(
                max(0.0, min(100.0, (current - lo) / (hi - lo) * 100)), 2
            )

    cards: list[SectorCard] = []
    for sector_name, members in members_by_sector.items():
        priced: list[tuple[str, float]] = [
            (s, c) for s in members if (c := change_by_symbol.get(s)) is not None
        ]
        change_pct: float | None = None
        best = SectorMover(symbol="-")
        worst = SectorMover(symbol="-")
        if priced:
            change_pct = round(sum(c for _, c in priced) / len(priced), 4)
            best = max(
                (SectorMover(symbol=s, change_pct=c) for s, c in priced),
                key=lambda m: m.change_pct or 0.0,
            )
            worst = min(
                (SectorMover(symbol=s, change_pct=c) for s, c in priced),
                key=lambda m: m.change_pct or 0.0,
            )

        sector_ranks = [iv_rank_by_symbol[s] for s in members if s in iv_rank_by_symbol]
        avg_iv_rank = round(sum(sector_ranks) / len(sector_ranks), 2) if sector_ranks else None

        cards.append(
            SectorCard(
                sector=sector_name,
                count=len(members),
                change_pct=change_pct,
                best=best,
                worst=worst,
                avg_iv_rank=avg_iv_rank,
                iv_rank_count=len(sector_ranks),
            )
        )

    # Order by avg_iv_rank descending; sectors with no IV history keep file order after.
    cards.sort(key=lambda c: (c.avg_iv_rank is None, -(c.avg_iv_rank or 0.0)))

    return SectorsResponse(as_of=now, sectors=cards)


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


_UNIVERSE_TIER_LISTS = ("indexes", "watchlist", "would_own", "actively_wheeling")


def _in_universe(symbol: str) -> bool:
    """True iff *symbol* is one of the ~46 universe.yaml names — the "hot" tier with full
    IV history and option-chain data (design §5.5). Watchlisting alone doesn't grant that;
    only membership in one of universe.yaml's own lists does.
    """
    u = get_config().universe
    return any(symbol in (u.get(key) or []) for key in _UNIVERSE_TIER_LISTS)


def _hv30_for(trading: TradingDb, symbol: str) -> float | None:
    """Read-only 30-day annualised historical vol from `price_history`.

    Mirrors `analytics/iv.py::_compute_hv30`'s formula (log returns, sample std over the
    last 30 sessions, annualised), but reads through the read-only trading engine instead
    of `get_ohlcv`, which fetches-and-writes on a cache miss — not safe for the API (§4.3).
    """
    import math

    from src.storage.models import PriceHistoryRow

    rows = (
        (
            trading.execute(
                select(PriceHistoryRow.close)
                .where(PriceHistoryRow.symbol == symbol)
                .order_by(PriceHistoryRow.obs_date.desc())
                .limit(31)
            )
        )
        .scalars()
        .all()
    )
    if len(rows) < 31:
        return None
    closes = list(reversed(rows))  # ascending, oldest first
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mean = sum(log_returns) / len(log_returns)
    variance = sum((x - mean) ** 2 for x in log_returns) / (len(log_returns) - 1)
    hv = math.sqrt(variance) * math.sqrt(252) * 100
    return round(hv, 4)


def _iv_stats_for(trading: TradingDb, symbol: str) -> IVStats:
    """Read-only IVStats from the trading DB's `iv_history` (+ `price_history` for HV30).

    Mirrors `analytics/iv.py::get_iv_stats`'s rank formula exactly (note #4 in the M6 plan:
    keep the two in sync if the formula changes). An empty history returns an all-None
    `IVStats`, same as `get_iv_stats` — the honest "no coverage" case, never a fabricated
    rank from a handful of observations.
    """
    from src.storage.models import IVHistoryRow

    ivs = (
        (
            trading.execute(
                select(IVHistoryRow.iv)
                .where(IVHistoryRow.symbol == symbol)
                .order_by(IVHistoryRow.obs_date.desc())
                .limit(365)
            )
        )
        .scalars()
        .all()
    )
    if not ivs:
        return IVStats(symbol=symbol)

    history = list(ivs)
    current = history[0]
    lo, hi = min(history), max(history)
    iv_rank = round(max(0.0, min(100.0, (current - lo) / (hi - lo) * 100)), 2) if hi != lo else None
    return IVStats(
        symbol=symbol,
        current_iv=round(current * 100, 4),
        iv_rank=iv_rank,
        hv_30=_hv30_for(trading, symbol),
    )


def _fundamentals_for(trading: TradingDb, symbol: str) -> FundamentalStats:
    """Read-only next-earnings date from the fundamentals cache (trading DB)."""
    from src.storage.models import FundamentalCacheRow

    row = trading.get(FundamentalCacheRow, symbol)
    return FundamentalStats(
        symbol=symbol, next_earnings=row.next_earnings_date if row is not None else None
    )


@router.get("/{symbol}/options", response_model=OptionsLensResponse)
def options_lens(
    symbol: str, user: CurrentUser, db: ResearchDb, trading: TradingDb
) -> OptionsLensResponse:
    """On-demand options-income lens — honest about what it does and doesn't know.

    A universe symbol gets real `iv_rank`/`vrp_points` from the trading DB, read-only
    (§4.3). An off-universe symbol gets the same shape with `UNKNOWN` and
    `coverage.iv_history` false rather than a percentile invented from a short series.
    `coverage.option_chain` is always false in P1 — the API holds no IBKR connection, so
    `atm_open_interest`/`atm_spread_pct` stay `UNKNOWN` too. Leverage warnings (Task 5.4)
    are included for leveraged names via the shared `warnings_for` catalogue.
    """
    now = datetime.now(UTC)
    upper = symbol.upper()

    row = db.get(SymbolRow, upper)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown symbol {upper}")

    iv_stats = _iv_stats_for(trading, upper)
    fund_stats = _fundamentals_for(trading, upper)
    quote = db.get(QuoteRow, upper)
    price = quote.price if quote is not None else None

    metrics = build_metrics(
        None, price=price, is_etf=row.is_etf, iv_stats=iv_stats, fundamentals=fund_stats
    )
    payload = build_checks_payload(metrics, symbol=upper, is_etf=row.is_etf)
    options_checks = next(
        (c.checks for c in payload.categories if c.category == "options"), []
    )

    return OptionsLensResponse(
        as_of=now,
        symbol=upper,
        in_universe=_in_universe(upper),
        tier="hot" if _in_universe(upper) else "cold",
        checks=options_checks,
        warnings=payload.warnings,
        coverage=OptionsCoverage(iv_history=iv_stats.current_iv is not None, option_chain=False),
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
        checks=Section[ChecksPayload](
            state=result.checks_state,
            data=result.checks,
            reason=result.checks_reason,
        ),
        quote=quote_sourced,
    )
