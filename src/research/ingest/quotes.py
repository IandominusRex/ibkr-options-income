"""Delayed intraday quotes for the warm tier.

Scoped to watchlisted and recently viewed symbols so free-tier limits are respected.
Freshness target is 15 to 30 minutes, so the scheduler runs this every 15 minutes during
regular trading hours only. The RTH guard is inside ``refresh_quotes`` itself so a manual
call outside market hours is a no-op rather than a wasted burst of provider calls.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from src.common.market_hours import is_rth
from src.data.factory import get_price_provider
from src.research.store.models import QuoteRow, RecentlyViewedRow, WatchlistItemRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

RECENT_VIEW_DAYS = 7


def warm_symbols() -> list[str]:
    """Union of watchlisted symbols and those viewed in the last ``RECENT_VIEW_DAYS`` days."""
    cutoff = datetime.now(UTC) - timedelta(days=RECENT_VIEW_DAYS)
    with research_session() as session:
        watched = {r.symbol for r in session.query(WatchlistItemRow).all()}
        viewed = {
            r.symbol
            for r in session.query(RecentlyViewedRow)
            .filter(RecentlyViewedRow.viewed_at >= cutoff)
            .all()
        }
    return sorted(watched | viewed)


def refresh_quotes() -> int:
    """Fetch a delayed quote for every warm symbol. Returns how many were written.

    No-op outside regular trading hours: the warm tier only needs intraday quotes while the
    market is actually open. A missing quote (``None``) is not the same as a price of zero
    and writes no row.
    """
    if not is_rth():
        return 0

    provider = get_price_provider()
    now = datetime.now(UTC)
    written = 0

    for symbol in warm_symbols():
        try:
            price = provider.get_last_price(symbol)
        except Exception as exc:
            log.warning("Quote fetch failed for %s: %s", symbol, exc)
            continue
        if price is None:
            continue  # absent, never zero

        with research_session() as session:
            row = session.get(QuoteRow, symbol)
            if row is None:
                session.add(QuoteRow(symbol=symbol, price=price, as_of=now, source="yfinance"))
            else:
                if row.price:
                    row.change_pct = (price - row.price) / row.price * 100.0
                else:
                    row.change_pct = None
                row.price = price
                row.as_of = now
        written += 1

    return written
