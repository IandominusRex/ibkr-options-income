"""Refresh the symbol directory from the configured provider.

Search reads ``symbols`` directly, so this table must never be empty. An upsert (rather
than a truncate-and-reload) keeps locally enriched columns and survives a failed fetch.

A handful of actively-traded leveraged/inverse ETFs (TQQQ, SOXL, UPRO, ...) are absent from
EDGAR's ticker directory entirely — they're share classes registered under a shared trust
CIK, not individually-registered filers — even though they're part of the live
options-income universe (``config/universe.yaml``). ``config/symbol_directory_overrides.yaml``
supplements those by hand; see that file's header for why they carry no CIK.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import yaml

from src.common.config import CONFIG_DIR
from src.data.factory import get_symbol_directory_provider
from src.research.store.models import SymbolRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

_OVERRIDES_PATH = CONFIG_DIR / "symbol_directory_overrides.yaml"


def _load_overrides() -> list[dict[str, Any]]:
    """Read the manual supplement list. Missing file or empty ``overrides`` key: none."""
    if not _OVERRIDES_PATH.exists():
        return []
    with _OVERRIDES_PATH.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    return payload.get("overrides") or []


def refresh_symbol_directory() -> int:
    """Upsert every symbol the provider returns, then seed manual overrides.

    Returns the count of provider-sourced rows written — 0 when the fetch fails or
    returns nothing, matching the existing contract that a failed SEC fetch must never
    empty (or otherwise misreport) the directory search depends on. Overrides are applied
    unconditionally on every call and are not counted in the return value: each only ever
    fills a symbol the provider has never covered, and never overwrites an existing row
    (EDGAR-sourced or a prior override) — so if EDGAR ever adds real coverage for one of
    these tickers, the next refresh upserts over it normally and this stops touching it.
    """
    rows = get_symbol_directory_provider().list_symbols()
    now = datetime.now(UTC)

    with research_session() as session:
        existing = {r.symbol: r for r in session.query(SymbolRow).all()}
        known = set(existing)

        if rows:
            for rec in rows:
                row = existing.get(rec.symbol)
                if row is None:
                    row = SymbolRow(symbol=rec.symbol, updated_at=now)
                    session.add(row)
                    known.add(rec.symbol)
                # Only the provider-owned columns. sector/industry/is_etf are enriched
                # by other jobs and must survive a directory refresh.
                row.cik = rec.cik
                row.name = rec.name
                row.exchange = rec.exchange
                row.updated_at = now
        else:
            log.warning("Symbol directory fetch returned nothing; leaving existing rows intact")

        for override in _load_overrides():
            symbol = str(override["symbol"]).strip().upper()
            if not symbol or symbol in known:
                continue
            session.add(
                SymbolRow(
                    symbol=symbol,
                    cik=override.get("cik"),
                    name=str(override.get("name") or ""),
                    exchange=override.get("exchange"),
                    is_etf=bool(override.get("is_etf", False)),
                    updated_at=now,
                )
            )
            known.add(symbol)

    log.info("Symbol directory refreshed: %d symbols", len(rows))
    return len(rows)
