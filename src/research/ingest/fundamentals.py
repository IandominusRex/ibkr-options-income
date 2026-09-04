"""Fetch, normalise, and persist a filer's financial statements.

Every ratio the checks engine later computes is derived from THESE numbers, never taken from
a vendor's precomputed field. That is the discipline src/analytics/fundamentals.py already
follows, and it is why the concept map and period selection matter so much.

The cache contract: a warm view of a symbol must never hit SEC. ``load_cached_financials``
rebuilds :class:`NormalizedFinancials` from the ``financials`` table alone; ``ingest_fundamentals``
is the cold path, which fetches (honouring ETags so a 304 is free), normalises, and persists.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, date, datetime

from src.data.factory import get_filings_provider
from src.research.ingest.concepts import (
    assert_units_supported,
    load_concept_map,
    resolve_line_item,
    select_periods,
)
from src.research.schemas import LineItemValue, NormalizedFinancials, PeriodStatement
from src.research.store.models import CompanyFactsRawRow, FinancialRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)

ANNUAL_LIMIT = 5
QUARTERLY_LIMIT = 8


def normalize(
    payload: dict,
    symbol: str,
    *,
    annual_limit: int = ANNUAL_LIMIT,
    quarterly_limit: int = QUARTERLY_LIMIT,
) -> NormalizedFinancials:
    """Turn a companyfacts document into periods of canonical line items."""
    concept_map = load_concept_map()

    # period_type -> period_end -> line_item -> value
    buckets: dict[str, dict[date, dict[str, LineItemValue]]] = {
        "annual": defaultdict(dict),
        "quarterly": defaultdict(dict),
    }

    for name, spec in concept_map.items():
        assert_units_supported(spec)
        resolved = resolve_line_item(payload, spec)
        if resolved is None:
            continue  # the filer reports nothing we recognise; absent, never zero
        concept, facts = resolved

        for period_type, limit in (("annual", annual_limit), ("quarterly", quarterly_limit)):
            for fact in select_periods(facts, kind=spec.kind, period_type=period_type, limit=limit):
                buckets[period_type][fact.end][name] = LineItemValue(
                    line_item=name,
                    value=fact.value,
                    concept=concept,
                    accn=fact.accn,
                    filed=fact.filed,
                    form=fact.form,
                )

    def statements(period_type: str, limit: int) -> list[PeriodStatement]:
        ends = sorted(buckets[period_type], reverse=True)[:limit]
        return [
            PeriodStatement(
                period_end=end, period_type=period_type, items=buckets[period_type][end]
            )
            for end in ends
        ]

    return NormalizedFinancials(
        symbol=symbol,
        cik=str(payload.get("cik", "")).zfill(10) if payload.get("cik") else "",
        entity_name=str(payload.get("entityName", "")),
        annual=statements("annual", annual_limit),
        quarterly=statements("quarterly", quarterly_limit),
    )


def load_cached_financials(symbol: str) -> NormalizedFinancials | None:
    """Rebuild :class:`NormalizedFinancials` from the ``financials`` table alone.

    Returns None when the symbol has no persisted rows. This is the warm path: no
    network, no SEC fetch, no re-normalisation. The rows were written by
    :func:`ingest_fundamentals` and carry every field the API payload needs.
    """
    with research_session() as session:
        rows = (
            session.query(FinancialRow)
            .filter_by(symbol=symbol)
            .order_by(FinancialRow.period_type, FinancialRow.period_end.desc())
            .all()
        )

    if not rows:
        return None

    # Recover the entity name from the cached raw payload when available, so the
    # header on a warm view does not flash blank. Falls back to "" otherwise.
    cik = _cached_cik_for_symbol(symbol)
    entity_name = ""
    if cik is not None:
        with research_session() as session:
            raw = session.get(CompanyFactsRawRow, cik)
            if raw is not None:
                try:
                    entity_name = str(json.loads(raw.payload_json).get("entityName", ""))
                except (json.JSONDecodeError, TypeError):
                    entity_name = ""

    # period_type -> period_end -> line_item -> LineItemValue
    buckets: dict[str, dict[date, dict[str, LineItemValue]]] = {
        "annual": defaultdict(dict),
        "quarterly": defaultdict(dict),
    }
    for row in rows:
        buckets[row.period_type][row.period_end][row.line_item] = LineItemValue(
            line_item=row.line_item,
            value=row.value,
            concept=row.concept,
            accn=row.accn,
            filed=row.filed,
            form=row.form,
        )

    def statements(period_type: str, limit: int) -> list[PeriodStatement]:
        ends = sorted(buckets[period_type], reverse=True)[:limit]
        return [
            PeriodStatement(
                period_end=end, period_type=period_type, items=buckets[period_type][end]
            )
            for end in ends
        ]

    return NormalizedFinancials(
        symbol=symbol,
        cik=cik or "",
        entity_name=entity_name,
        annual=statements("annual", ANNUAL_LIMIT),
        quarterly=statements("quarterly", QUARTERLY_LIMIT),
    )


def _cached_cik_for_symbol(symbol: str) -> str | None:
    """Recover the CIK for a symbol from the directory. None when not found."""
    from src.research.store.models import SymbolRow

    with research_session() as session:
        row = session.get(SymbolRow, symbol)
        return row.cik if row else None


def ingest_fundamentals(symbol: str, cik: str) -> NormalizedFinancials | None:
    """Fetch, cache the raw payload, normalise, and persist. None when there are no facts.

    On a 304 Not Modified the previously cached raw payload is re-used, so a warm
    re-ingest (e.g. the worker draining a refresh job) costs nothing against SEC.
    """
    # Carry the last-seen ETag so a 304 is free. The raw row's payload is reused.
    cached_raw: CompanyFactsRawRow | None = None
    with research_session() as session:
        cached_raw = session.get(CompanyFactsRawRow, cik)

    etag_in = cached_raw.etag if cached_raw is not None else None
    payload, new_etag = get_filings_provider().get_company_facts(cik, etag=etag_in)

    if not payload:
        if new_etag == etag_in and cached_raw is not None:
            # 304: reuse the previously cached payload; do not treat as "no facts".
            try:
                payload = json.loads(cached_raw.payload_json)
            except (json.JSONDecodeError, TypeError):
                log.warning("Cached raw payload for CIK %s was unparseable", cik)
                return None
        else:
            log.info("No XBRL facts for %s (CIK %s)", symbol, cik)
            return None

    financials = normalize(payload, symbol)
    now = datetime.now(UTC)

    with research_session() as session:
        blob = json.dumps(payload, separators=(",", ":"))
        raw = session.get(CompanyFactsRawRow, cik)
        if raw is None:
            session.add(
                CompanyFactsRawRow(cik=cik, payload_json=blob, etag=new_etag, fetched_at=now)
            )
        else:
            raw.payload_json = blob
            raw.etag = new_etag
            raw.fetched_at = now

        # Replace this symbol's rows wholesale: normalisation is deterministic, so a
        # re-ingest should leave exactly one row per (period, line item).
        session.query(FinancialRow).filter_by(symbol=symbol).delete()
        for statement in [*financials.annual, *financials.quarterly]:
            for item in statement.items.values():
                session.add(
                    FinancialRow(
                        symbol=symbol,
                        period_end=statement.period_end,
                        period_type=statement.period_type,
                        line_item=item.line_item,
                        value=item.value,
                        concept=item.concept,
                        accn=item.accn,
                        filed=item.filed,
                        form=item.form,
                    )
                )

    return financials
