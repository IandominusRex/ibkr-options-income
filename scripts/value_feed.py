"""The plain data the value process hands to ``src/value/`` (spec §6.6, §6.9): earnings dates
from news.db and yfinance market facts. ``src/value/`` may fetch neither itself: news.db is
enrichment's database and yfinance is a network provider, so ``scripts/run_value.py`` gathers
both here and passes them in as dicts.

Importable (no side effects at import), so it is tested and fenced; ``scripts/run_value.py`` is
not imported by anything.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from src.common.value_types import MarketFacts

log = logging.getLogger(__name__)

EARNINGS_HORIZON_DAYS = 180


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


def market_facts(names: list[str], workers: int) -> dict[str, MarketFacts]:
    """yfinance market cap, sector, industry, quote type and next earnings for each name
    (``fetch_market_facts`` never raises: a failed read is an empty ``MarketFacts``)."""
    from src.common.value_inputs import fetch_market_facts

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip(names, pool.map(fetch_market_facts, names), strict=True))
