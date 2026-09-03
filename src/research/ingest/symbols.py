"""Refresh the symbol directory from the configured provider.

Search reads ``symbols`` directly, so this table must never be empty. An upsert (rather
than a truncate-and-reload) keeps locally enriched columns and survives a failed fetch.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.data.factory import get_symbol_directory_provider
from src.research.store.models import SymbolRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)


def refresh_symbol_directory() -> int:
    """Upsert every symbol the provider returns. Returns the row count written.

    Returns 0 and leaves existing rows untouched when the provider returns nothing — a
    failed SEC fetch must never empty the directory that search depends on.
    """
    rows = get_symbol_directory_provider().list_symbols()
    if not rows:
        log.warning("Symbol directory fetch returned nothing; leaving existing rows intact")
        return 0

    now = datetime.now(UTC)
    with research_session() as session:
        existing = {r.symbol: r for r in session.query(SymbolRow).all()}
        for rec in rows:
            row = existing.get(rec.symbol)
            if row is None:
                session.add(
                    SymbolRow(
                        symbol=rec.symbol,
                        cik=rec.cik,
                        name=rec.name,
                        exchange=rec.exchange,
                        updated_at=now,
                    )
                )
            else:
                # Only the provider-owned columns. sector/industry/is_etf are enriched
                # by other jobs and must survive a directory refresh.
                row.cik = rec.cik
                row.name = rec.name
                row.exchange = rec.exchange
                row.updated_at = now

    log.info("Symbol directory refreshed: %d symbols", len(rows))
    return len(rows)
