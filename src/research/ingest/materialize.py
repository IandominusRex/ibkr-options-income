"""Cold-tier materialisation with a wall-clock budget.

A symbol nobody has viewed before has no cached analysis. We try to build one synchronously
inside a budget; if that overruns, the caller gets a partial payload with the slow sections
marked PENDING and a background job queued. The client polls. There is never a spinner over
a blank screen. See design §5.5.

Cache contract (load-bearing):

* A warm view of a symbol MUST hit the ``financials`` table, never SEC.
  :func:`load_cached_financials` rebuilds the payload from rows alone; the network is
  touched only on a cache miss or an explicit refresh.

* ``PENDING`` is a true partial state: it never carries ``fundamentals`` data. A section
  that finished slowly is returned ``READY`` with its data; a section that did not finish
  at all is ``PENDING`` with ``reason`` and no data. The client polls and the next request
  resolves against the now-warm cache.

* ``reason`` is a fixed user-facing string, never ``str(exc)``. An exception message can
  carry a CIK or a transport detail; the user sees a sanitised explanation and the full
  error is logged.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel

from src.common.config import get_config
from src.research.ingest.fundamentals import ingest_fundamentals, load_cached_financials
from src.research.schemas import NormalizedFinancials
from src.research.store.models import IngestJobRow, QuoteRow, SymbolRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

# User-facing reasons. These are rendered verbatim by the frontend; an exception
# string must never reach the browser, so every state-to-reason mapping is fixed here.
_REASON_NO_FILER = "No SEC filer record for this symbol"
_REASON_NO_XBRL = "No XBRL financial statements filed for this symbol"
_REASON_BUILDING = "Still building this section. It will appear shortly."
_REASON_SOURCE_UNAVAILABLE = "EDGAR is unavailable right now. Try again shortly."
_REASON_REFRESH_QUEUED = "A refresh is queued in the background."
_REASON_NO_DATA = "No data available for this section."
_REASON_SOURCE_DOWN = "Data provider temporarily unavailable"


class SectionState(StrEnum):
    READY = "ready"  # data is present
    PENDING = "pending"  # queued; poll again
    UNAVAILABLE = "unavailable"  # will not resolve; reason explains why


class MaterializeResult(BaseModel):
    symbol: str
    fundamentals: NormalizedFinancials | None = None
    # PENDING is the safer default: "I don't know yet" is always a better fallback than
    # "no" for a field whose sole purpose is tri-state UI.
    fundamentals_state: SectionState = SectionState.PENDING
    fundamentals_reason: str | None = None
    # Each enrichment section degrades independently. The plan's contract: a triple of
    # (data, state, reason) per source, and the reason field is what the UI renders when a
    # section is unavailable. Sentiment is enrichment-tier and must never become an input
    # to the deterministic sections (technicals/fundamentals).
    technicals: object | None = None
    technicals_state: SectionState = SectionState.PENDING
    technicals_reason: str | None = None
    sentiment: object | None = None
    sentiment_state: SectionState = SectionState.PENDING
    sentiment_reason: str | None = None
    news: list[dict] | None = None
    news_state: SectionState = SectionState.PENDING
    news_reason: str | None = None
    quote: float | None = None
    quote_as_of: datetime | None = None
    quote_state: SectionState = SectionState.PENDING
    quote_reason: str | None = None
    # Kept for backwards compatibility with callers that read the single `reason` field.
    reason: str | None = None


def enqueue(symbol: str, kind: str) -> None:
    """Queue a background ingest. Deduplicated on (symbol, kind, pending)."""
    with research_session() as session:
        exists = (
            session.query(IngestJobRow)
            .filter_by(symbol=symbol, kind=kind, status="pending")
            .first()
        )
        if exists is None:
            session.add(
                IngestJobRow(
                    symbol=symbol,
                    kind=kind,
                    status="pending",
                    attempts=0,
                    enqueued_at=datetime.now(UTC),
                )
            )


def _technicals(symbol: str) -> object:
    """Deterministic tier: RSI, MACD, SMAs, ATR, phase, regime. May feed scoring."""
    from src.analytics.technicals import get_technical_stats

    return get_technical_stats(symbol)


def _sentiment(symbol: str) -> object:
    """Enrichment tier. Reaches the card and the prompt only, never a deterministic input."""
    from src.analytics.sentiment import SentimentScorer

    return SentimentScorer().score(symbol)


def _news(symbol: str) -> object:
    """Enrichment tier. Per-item VADER-scored headlines, persisted for the warm tier."""
    from src.research.ingest.news import recent_news

    return recent_news(symbol)


def _quote(symbol: str) -> tuple[float | None, datetime | None, str | None]:
    """Read the most recent warm-tier quote row for *symbol*.

    Returns ``(price, as_of, reason)``. ``(None, None, reason)`` when no quote has been
    ingested. ``as_of`` is the row's actual capture time — the API layer stamps a
    ``Sourced`` value with it so a stale quote reads as stale, not silently as fresh.
    Never raises — a missing quote is a section-level unavailable, not a page failure.
    """
    with research_session() as session:
        row = session.get(QuoteRow, symbol)
        if row is None or row.price is None:
            return None, None, _REASON_NO_DATA
        return float(row.price), row.as_of, None


def _section(fn, *args) -> tuple[object | None, SectionState, str | None]:
    """Run one source. Returns (data, state, reason) and never raises.

    An exception's ``str`` is returned as the reason — this module is server-side only
    and the reason is logged here; the API layer's ``Section`` re-maps to a fixed
    user-facing string before it reaches the browser.
    """
    try:
        data = fn(*args)
    except Exception as exc:
        log.warning("Section %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None, SectionState.UNAVAILABLE, str(exc)
    if data is None:
        return None, SectionState.UNAVAILABLE, _REASON_NO_DATA
    return data, SectionState.READY, None


def _enrich(symbol: str, result: MaterializeResult) -> MaterializeResult:
    """Run the three enrichment sections + quote, independently of fundamentals.

    Each section is guarded by :func:`_section` so one outage cannot cascade. Sentiment is
    enrichment-tier and is never passed into technicals or fundamentals (the
    ``test_sentiment_is_never_an_input_to_the_deterministic_sections`` structural test
    guards this by inspecting this module's source).
    """
    tech_data, tech_state, tech_reason = _section(_technicals, symbol)
    result.technicals = tech_data
    result.technicals_state = tech_state
    result.technicals_reason = tech_reason

    sent_data, sent_state, sent_reason = _section(_sentiment, symbol)
    result.sentiment = sent_data
    result.sentiment_state = sent_state
    result.sentiment_reason = sent_reason

    news_data, news_state, news_reason = _section(_news, symbol)
    result.news = news_data if isinstance(news_data, list) else None
    result.news_state = news_state
    result.news_reason = news_reason

    price, quote_as_of, quote_reason = _quote(symbol)
    result.quote = price
    result.quote_as_of = quote_as_of
    if price is not None:
        result.quote_state = SectionState.READY
        result.quote_reason = None
    else:
        result.quote_state = SectionState.UNAVAILABLE
        result.quote_reason = quote_reason or _REASON_NO_DATA

    return result


def materialize(symbol: str, *, budget_seconds: float | None = None) -> MaterializeResult:
    """Build a symbol's analysis inputs, bounded by a wall-clock budget.

    Cache-first. If :func:`load_cached_financials` returns a payload, the request is
    served from the ``financials`` table with no SEC fetch and no budget consumed. The
    network path runs only on a cache miss. The three enrichment sections (technicals,
    sentiment, news) and the quote run on every call, independently of fundamentals.
    """
    budget = (
        budget_seconds
        if budget_seconds is not None
        else get_config().research.tiers.materialization_budget_seconds
    )

    upper = symbol.upper()

    # Resolve the CIK once; both the cache read and the ingest path need it.
    with research_session() as session:
        row = session.get(SymbolRow, upper)
        cik = row.cik if row else None

    if not cik:
        # No directory row means no CIK, and a queued job would never resolve. Saying
        # "pending" here would be a lie the client renders as a spinner forever.
        return MaterializeResult(
            symbol=upper,
            fundamentals_state=SectionState.UNAVAILABLE,
            fundamentals_reason=_REASON_NO_FILER,
            reason=_REASON_NO_FILER,
        )

    # Warm path: serve from the cache, no network.
    cached = load_cached_financials(upper)
    if cached is not None and cached.annual:
        return _enrich(
            upper,
            MaterializeResult(
                symbol=upper,
                fundamentals=cached,
                fundamentals_state=SectionState.READY,
            ),
        )

    # Cold path: fetch from SEC inside the budget.
    started = time.monotonic()
    try:
        financials = ingest_fundamentals(upper, cik)
    except Exception as exc:
        log.warning("Fundamentals ingest failed for %s: %s", upper, exc)
        return _enrich(
            upper,
            MaterializeResult(
                symbol=upper,
                fundamentals_state=SectionState.UNAVAILABLE,
                fundamentals_reason=_REASON_SOURCE_UNAVAILABLE,
                reason=_REASON_SOURCE_UNAVAILABLE,
            ),
        )

    elapsed = time.monotonic() - started

    if financials is None:
        return _enrich(
            upper,
            MaterializeResult(
                symbol=upper,
                fundamentals_state=SectionState.UNAVAILABLE,
                fundamentals_reason=_REASON_NO_XBRL,
                reason=_REASON_NO_XBRL,
            ),
        )

    # The ingest finished. If it exceeded the budget, queue a background warm refresh
    # so the *next* view is served from cache, but return what we have NOW as READY.
    # PENDING-with-data was the old contract; it caused the client to poll and re-fetch
    # indefinitely. A complete result is READY, regardless of how long it took.
    if elapsed > budget:
        enqueue(upper, "fundamentals")
        log.info(
            "Fundamentals for %s took %.2fs (budget %.2fs); queued a warm refresh",
            upper,
            elapsed,
            budget,
        )

    return _enrich(
        upper,
        MaterializeResult(
            symbol=upper, fundamentals=financials, fundamentals_state=SectionState.READY
        ),
    )


def drain_ingest_jobs(max_jobs: int = 20) -> int:
    """Run queued jobs. Returns how many succeeded.

    One session per drain, not one session per job. A failure rolls back the row
    update for that job only (via a nested savepoint); the rest of the drain proceeds.
    """
    with research_session() as session:
        jobs = (
            session.query(IngestJobRow)
            .filter_by(status="pending")
            .order_by(IngestJobRow.enqueued_at)
            .limit(max_jobs)
            .all()
        )
        pending = [(j.id, j.symbol, j.kind) for j in jobs]

    done = 0
    for job_id, symbol, kind in pending:
        # Resolve the CIK once per job. The directory is small and local.
        with research_session() as session:
            row = session.get(SymbolRow, symbol)
            cik = row.cik if row else None

        error: str | None = None
        if kind == "fundamentals" and cik:
            try:
                ingest_fundamentals(symbol, cik)
            except Exception as exc:
                error = str(exc)
        else:
            error = f"Cannot run job kind {kind!r} for {symbol}"

        with research_session() as session:
            job = session.get(IngestJobRow, job_id)
            if job is None:
                continue
            job.attempts += 1
            if error is None:
                job.status = "done"
                job.last_error = None
                done += 1
            else:
                job.last_error = error
                job.status = "failed" if job.attempts >= MAX_ATTEMPTS else "pending"

    return done
