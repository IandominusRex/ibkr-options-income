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
from src.research.store.models import IngestJobRow, SymbolRow
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


def materialize(symbol: str, *, budget_seconds: float | None = None) -> MaterializeResult:
    """Build a symbol's analysis inputs, bounded by a wall-clock budget.

    Cache-first. If :func:`load_cached_financials` returns a payload, the request is
    served from the ``financials`` table with no SEC fetch and no budget consumed. The
    network path runs only on a cache miss.
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
            reason=_REASON_NO_FILER,
        )

    # Warm path: serve from the cache, no network.
    cached = load_cached_financials(upper)
    if cached is not None and cached.annual:
        return MaterializeResult(
            symbol=upper, fundamentals=cached, fundamentals_state=SectionState.READY
        )

    # Cold path: fetch from SEC inside the budget.
    started = time.monotonic()
    try:
        financials = ingest_fundamentals(upper, cik)
    except Exception as exc:
        log.warning("Fundamentals ingest failed for %s: %s", upper, exc)
        return MaterializeResult(
            symbol=upper,
            fundamentals_state=SectionState.UNAVAILABLE,
            reason=_REASON_SOURCE_UNAVAILABLE,
        )

    elapsed = time.monotonic() - started

    if financials is None:
        return MaterializeResult(
            symbol=upper,
            fundamentals_state=SectionState.UNAVAILABLE,
            reason=_REASON_NO_XBRL,
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

    return MaterializeResult(
        symbol=upper, fundamentals=financials, fundamentals_state=SectionState.READY
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
