"""Persist daily OHLCV for a symbol.

Cold-tier ingest: pulls daily bars from the active :class:`BulkPriceProvider` and upserts
into ``daily_bars``. The caller (the analysis payload builder, the warm refresh job) does
not care which backend supplied the rows — stooq or the yfinance fallback — only that the
frame carries ``Open, High, Low, Close, Volume`` and a ``DatetimeIndex``.

A failed fetch (empty frame) returns 0 and **never deletes existing history**: a transient
provider outage must not erase a ticker's price series. Upserts are keyed on
``(symbol, date)`` so a re-ingest overwrites stale values rather than duplicating rows.
"""

from __future__ import annotations

import logging

from src.common.config import get_config
from src.data.factory import get_bulk_price_provider
from src.research.store.models import DailyBarRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)


def ingest_daily_bars(symbol: str) -> int:
    """Upsert daily bars for *symbol*. Returns rows written; 0 leaves history intact."""
    provider = get_bulk_price_provider()
    df = provider.get_daily_bars(symbol)
    if df is None or df.empty:
        log.info("No bars returned for %s; leaving history intact", symbol)
        return 0

    source = get_config().data.bulk_price_provider
    written = 0
    with research_session() as session:
        existing = {r.date: r for r in session.query(DailyBarRow).filter_by(symbol=symbol).all()}
        for ts, row in df.iterrows():
            day = ts.date() if hasattr(ts, "date") else ts
            target = existing.get(day)
            if target is None:
                session.add(
                    DailyBarRow(
                        symbol=symbol,
                        date=day,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row["Volume"]),
                        source=source,
                    )
                )
            else:
                target.open = float(row["Open"])
                target.high = float(row["High"])
                target.low = float(row["Low"])
                target.close = float(row["Close"])
                target.volume = float(row["Volume"])
                target.source = source
            written += 1
    return written
