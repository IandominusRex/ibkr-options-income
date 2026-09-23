"""Warm-tier data: watchlisted and recently viewed symbols.

Scoped to watchlisted and recently viewed symbols so free-tier limits are respected.
Four refreshes live here:

- ``refresh_quotes`` — delayed intraday quotes for every warm symbol, every 15 minutes
  during regular trading hours only. The RTH guard is inside the function itself so a
  manual call outside market hours is a no-op rather than a wasted burst of provider calls.
- ``refresh_quote_for`` — the single-symbol counterpart, called on demand from
  ``materialize()`` the first time a symbol with no quote row is viewed. NOT RTH-gated:
  the point is a symbol's first-ever view must not wait up to 15 minutes for the next
  ``refresh_quotes`` sweep, market hours or not (yfinance returns the last close when the
  market is shut, which is exactly what a quiet-hours view should show).
- ``refresh_warm_bars`` — nightly daily-bar refresh for the warm tier, the job
  the P0-P1 design promised for ``daily_bars`` ("Warm tier - refreshed nightly").
  A failed fetch returns 0 and never deletes history (``ingest_daily_bars``'s own
  guarantee); one symbol failing never stops the rest.
- ``refresh_warm_news`` — the same nightly pass over ``ingest_news`` so the
  ticker page's persisted news table fills for warm names.

The research worker schedules the two nightly jobs as one ``warm_refresh`` job
at ``research.tiers.warm_refresh_hour_et``.

``change_pct`` (the "Day" column/figure) is always the change versus the most recent
*completed* trading session's close, read from ``daily_bars`` — never the delta between
two consecutive polls, which used to be the actual behaviour: a number that drifted
further from a real day change with every 15-minute cycle, and stayed ``None`` for a
symbol's entire first cycle since there was no earlier poll to diff against.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from src.common.market_hours import is_rth, today_et
from src.data.factory import get_price_provider
from src.research.ingest.news import ingest_news
from src.research.ingest.prices import ingest_daily_bars
from src.research.store.models import DailyBarRow, QuoteRow, RecentlyViewedRow, WatchlistItemRow
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


def _prior_close(symbol: str) -> float | None:
    """Most recent daily-bar close strictly before today (exchange time).

    Seeds ``daily_bars`` on demand when none exist yet — the same cold-path backfill the
    ``/bars`` route uses — so a symbol's very first quote still carries a real
    ``change_pct`` instead of one stuck ``None`` until someone happens to open the price
    chart tab first. Never raises: a failed backfill just leaves ``change_pct`` unset,
    same as any other missing-data case.
    """
    cutoff = today_et()

    def _latest() -> float | None:
        with research_session() as session:
            row = (
                session.query(DailyBarRow)
                .filter(DailyBarRow.symbol == symbol, DailyBarRow.date < cutoff)
                .order_by(DailyBarRow.date.desc())
                .first()
            )
            return float(row.close) if row is not None and row.close is not None else None

    close = _latest()
    if close is not None:
        return close

    try:
        ingest_daily_bars(symbol)
    except Exception as exc:
        log.warning("On-demand daily-bar backfill for day-change failed for %s: %s", symbol, exc)
        return None
    return _latest()


def _day_change_pct(symbol: str, price: float) -> float | None:
    """``(price - prior close) / prior close * 100`` — a genuine day-over-day change,
    never a delta between two intraday polls. ``None`` (not ``0``) when no prior close
    is available at all (e.g. a symbol with no trading history yet)."""
    prior = _prior_close(symbol)
    if not prior:
        return None
    return round((price - prior) / prior * 100.0, 4)


def _write_quote(symbol: str, price: float, now: datetime) -> None:
    change_pct = _day_change_pct(symbol, price)
    with research_session() as session:
        row = session.get(QuoteRow, symbol)
        if row is None:
            session.add(
                QuoteRow(
                    symbol=symbol, price=price, change_pct=change_pct, as_of=now, source="yfinance"
                )
            )
        else:
            row.price = price
            row.change_pct = change_pct
            row.as_of = now


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

        _write_quote(symbol, price, now)
        written += 1

    return written


def refresh_quote_for(symbol: str) -> bool:
    """On-demand single-symbol quote seed for a cold view. Returns True iff a quote was
    written; a missing price (``None``) writes nothing, matching ``refresh_quotes``'s own
    contract. Never raises — a failed fetch is the caller's cue to render "no quote yet",
    not a page failure.

    Deliberately NOT RTH-gated, unlike ``refresh_quotes``'s periodic sweep: a symbol's
    first-ever view should get a quote at any hour rather than wait for the next market-
    hours poll.
    """
    provider = get_price_provider()
    try:
        price = provider.get_last_price(symbol)
    except Exception as exc:
        log.warning("On-demand quote fetch failed for %s: %s", symbol, exc)
        return False
    if price is None:
        return False
    _write_quote(symbol, price, datetime.now(UTC))
    return True


def refresh_warm_bars(symbols: list[str] | None = None) -> int:
    """Re-ingest daily bars for the warm tier. Returns rows written across all symbols.

    One symbol's failed fetch never stops the rest (the same per-symbol isolation
    ``refresh_quotes`` uses). ``ingest_daily_bars`` itself never deletes history
    on an empty fetch, so an outage leaves the chart's data intact.
    """
    targets = symbols if symbols is not None else warm_symbols()
    written = 0
    for symbol in targets:
        try:
            written += ingest_daily_bars(symbol)
        except Exception as exc:
            log.warning("Daily-bar refresh failed for %s: %s", symbol, exc)
    return written


def refresh_warm_news(symbols: list[str] | None = None) -> int:
    """Persist news for the warm tier. Returns rows written across all symbols.

    Per-symbol isolation as above; ``ingest_news`` never raises on a fetch
    failure (it returns 0), and dedupes on ``(symbol, url)``.
    """
    targets = symbols if symbols is not None else warm_symbols()
    written = 0
    for symbol in targets:
        try:
            written += ingest_news(symbol)
        except Exception as exc:
            log.warning("News refresh failed for %s: %s", symbol, exc)
    return written


def refresh_warm_tier() -> dict[str, int]:
    """Nightly warm-tier refresh: bars + news for every warm symbol.

    One job so the worker's heartbeat reflects the whole pass. Returns per-part
    counts for the log line; never raises (per-symbol failures are logged and
    skipped inside the two part functions).
    """
    symbols = warm_symbols()
    bars = refresh_warm_bars(symbols)
    news = refresh_warm_news(symbols)
    log.info(
        "Warm-tier refresh: %d symbols, %d bars, %d news rows",
        len(symbols),
        bars,
        news,
    )
    return {"symbols": len(symbols), "bars": bars, "news": news}
