"""The research worker's nightly sweep for the value book (spec §6.1, §6.9).

The research worker owns every SEC and price fetch; the value process only reads research.db.
This queues a ``fundamentals`` job (companyfacts, ETag-reused) for every name whose raw payload
is missing or older than a day, and a ``prices`` job for every name whose daily bars are short
or stale, across both value universes. ``drain_ingest_jobs`` runs them at its own pace (EDGAR is
rate-limited to 10 requests a second in ``EdgarClient``).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from src.common.config import get_config
from src.common.value_keep_fresh import read_keep_fresh
from src.common.value_universe import build_value_universe
from src.research.ingest.materialize import enqueue
from src.research.store.models import CompanyFactsRawRow, DailyBarRow, SymbolRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

MIN_BARS = 260
FACTS_MAX_AGE = timedelta(days=1)
# The value book's benchmark (spec §6.8): its bars are refreshed with the universe's, never its
# filings (an ETF has none). SPY is the spreads book's underlying, so it is never in universe.yaml.
BENCHMARKS = ("SPY",)


def last_weekday_before(today: date) -> date:
    """The newest weekday strictly before *today*: the session a nightly sweep must have."""
    day = today - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def value_names() -> list[str]:
    """Both universes, then the names the value book still holds in its shadow record that have
    left them (a plain file the value process writes; spec §6.9, review I4)."""
    from src.common.universe import effective_universe

    cfg = get_config()
    names = build_value_universe(cfg.value, effective_universe()).all_names()
    return [*names, *(s for s in read_keep_fresh() if s not in set(names))]


def enqueue_value_universe(
    names: list[str] | None = None,
    *,
    today: date | None = None,
    bars_only: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """Queue what each name lacks. Returns counts: fundamentals, prices, no_cik.

    Bars are stale once the newest is older than the last weekday before *today* (the value
    book marks its shadow record every session). The nightly call (no *names*) also refreshes
    the benchmark's bars (*bars_only*, default ``BENCHMARKS``)."""
    if names is None:
        names = value_names()
        bars_only = BENCHMARKS if bars_only is None else bars_only
    extra = [s for s in (bars_only or ()) if s not in names]
    today = today or datetime.now(UTC).date()
    due = last_weekday_before(today)
    now = datetime.now(UTC).replace(tzinfo=None)
    counts = {"fundamentals": 0, "prices": 0, "no_cik": 0}
    with research_session() as s:
        ciks = {r.symbol: r.cik for r in s.query(SymbolRow).filter(SymbolRow.symbol.in_(names))}
        fetched = {
            cik: at
            for cik, at in s.execute(select(CompanyFactsRawRow.cik, CompanyFactsRawRow.fetched_at))
        }
        bars = {
            sym: (n, last)
            for sym, n, last in s.execute(
                select(DailyBarRow.symbol, func.count(), func.max(DailyBarRow.date))
                .where(DailyBarRow.symbol.in_([*names, *extra]))
                .group_by(DailyBarRow.symbol)
            )
        }
    for symbol in names:
        cik = ciks.get(symbol)
        if not cik:
            counts["no_cik"] += 1
        else:
            at = fetched.get(cik)
            if at is None or now - at.replace(tzinfo=None) > FACTS_MAX_AGE:
                enqueue(symbol, "fundamentals")
                counts["fundamentals"] += 1
    for symbol in [*names, *extra]:
        n, last = bars.get(symbol, (0, None))
        if n < MIN_BARS or last is None or last < due:
            enqueue(symbol, "prices")
            counts["prices"] += 1
    log.info("Value sweep queued %s for %d names", counts, len(names))
    return counts
