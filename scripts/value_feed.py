"""The plain data the value process hands to ``src/value/`` (spec §6.6, §6.9): earnings dates
from news.db and yfinance market facts. ``src/value/`` may fetch neither itself: news.db is
enrichment's database and yfinance is a network provider, so ``scripts/run_value.py`` gathers
both here and passes them in as dicts.

Importable (no side effects at import), so it is tested and fenced; ``scripts/run_value.py`` is
not imported by anything.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from src.common.value_types import MarketFacts

log = logging.getLogger(__name__)

EARNINGS_HORIZON_DAYS = 180
RETRY_SECONDS = 3600.0  # a failed night is retried at most once an hour
CRITICAL_AFTER = 3  # failures for one session before the log turns CRITICAL


def earnings_dates(as_of: date) -> dict[str, date]:
    """Each name's earliest earnings date on or after *as_of* from news.db's
    ``earnings_events`` (read-only). An unreadable news.db is an empty dict: the scorecard then
    falls back to yfinance's calendar, and a missing date is UNKNOWN timing, never a pass."""
    import src.news.store.queries as queries
    from src.news.store.readonly import read_only_session

    out: dict[str, date] = {}
    with read_only_session() as s:
        if s is None:
            log.warning("value feed: news.db unreadable; earnings fall back to yfinance")
            return out
        for e in queries.earnings_between(s, as_of, as_of + timedelta(days=EARNINGS_HORIZON_DAYS)):
            out.setdefault(e.symbol, e.report_date)
    return out


class NightRetry:
    """Back-off for a night that keeps failing (review I2). Without it a failure that repeats
    every night (a bad row, a lock) would refetch ~1,000 names from yfinance every poll, all
    day. Pure: the clock is injected."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        retry_seconds: float = RETRY_SECONDS,
        critical_after: int = CRITICAL_AFTER,
    ) -> None:
        self._clock = clock
        self.retry_seconds = retry_seconds
        self.critical_after = critical_after
        self._as_of: date | None = None
        self._failures = 0
        self._last = 0.0

    def ready(self, as_of: date) -> bool:
        """True when the session has not failed yet, or the hour since its last failure is up."""
        if as_of != self._as_of or self._failures == 0:
            return True
        return self._clock() - self._last >= self.retry_seconds

    def failed(self, as_of: date) -> int:
        """Record a failure for *as_of*; returns how many times that session has failed."""
        if as_of != self._as_of:
            self._as_of, self._failures = as_of, 0
        self._failures += 1
        self._last = self._clock()
        return self._failures

    def succeeded(self) -> None:
        self._as_of, self._failures = None, 0


class FactsCache:
    """Market facts held in the process for one session, so a retry refetches nothing it already
    has. A name whose read came back empty (a failed fetch) is fetched again."""

    def __init__(
        self, fetch: Callable[[list[str], int], dict[str, MarketFacts]] | None = None
    ) -> None:
        self._fetch = fetch or market_facts
        self._as_of: date | None = None
        self._facts: dict[str, MarketFacts] = {}

    def get(self, as_of: date, names: list[str], workers: int) -> dict[str, MarketFacts]:
        if as_of != self._as_of:
            self._as_of, self._facts = as_of, {}
        empty = MarketFacts()
        missing = [n for n in names if self._facts.get(n, empty) == empty]
        if missing:
            self._facts.update(self._fetch(missing, workers))
        return {n: self._facts.get(n, empty) for n in names}

    def clear(self) -> None:
        self._as_of, self._facts = None, {}


def market_facts(names: list[str], workers: int) -> dict[str, MarketFacts]:
    """yfinance market cap, sector, industry, quote type and next earnings for each name
    (``fetch_market_facts`` never raises: a failed read is an empty ``MarketFacts``)."""
    from src.common.value_inputs import fetch_market_facts

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip(names, pool.map(fetch_market_facts, names), strict=True))
