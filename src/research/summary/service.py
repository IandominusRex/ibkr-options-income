"""Summary caching and the on-demand trigger.

The on-demand rule (P0-P1-design §7): a summary is generated on explicit request or
for watchlisted names, **never automatically for every cold-tier search**. A first-time
search on an obscure ticker must not silently trigger a model call. The ``GET`` endpoint
returns an ``unavailable`` section with a reason and makes no model call; the ``POST``
endpoint generates and caches. The cache key is ``(symbol, model, prompt_hash,
data_as_of)``; a changed ``data_as_of`` misses, and a row older than
``research.summary.cache_ttl_hours`` is regenerated.

This module is the only writer to the ``summaries`` table. The summary layer never
touches any other table (fence test in ``tests/test_web_fence.py``).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.research.store.models import SummaryRow
from src.research.summary.context import ResearchContext, build_context
from src.research.summary.factory import get_summary_provider
from src.research.summary.prompt import build_prompt
from src.research.summary.protocol import Summary

log = logging.getLogger(__name__)


def summary_for(
    symbol: str,
    analysis: object,
    db: Session,
    *,
    force: bool = False,
) -> tuple[Summary | None, str]:
    """Return ``(summary_or_none, state)`` for *symbol*.

    ``state`` is one of ``"ready"`` (cached summary returned), ``"stale"`` (cached but
    older than ``cache_ttl_hours``, caller may regenerate via POST), ``"unavailable"``
    (no cached summary, and none was generated), or ``"pending"`` (a generation was
    attempted but failed soft).

    When ``force=True`` a fresh generation is attempted regardless of cache state, and
    the result (if any) is written back to the cache. When ``force=False`` and a cached
    row exists and is fresh, it is returned without any model call.

    The cache key's ``model`` is config-derived (``research.summary.model`` or, for
    ``ollama``, ``claude.ollama_model``) so GET and POST always agree on the row. The
    provider's self-reported ``Summary.model`` (which may differ — e.g. ollama reports
    ``qwen3:8b`` while ``research.summary.model`` stays ``claude-sonnet-4-6``) is
    carried in the payload's ``model`` field for display attribution and preferred by
    ``_row_to_summary``.
    """
    upper = symbol.upper()
    ctx = build_context(upper, analysis)  # type: ignore[arg-type]
    cfg = get_config().research.summary
    key_model = cfg.model or _provider_model_name(cfg.backend)
    prompt_hash = _hash_prompt(ctx)

    if not force:
        cached = _read_cached(
            db, upper, key_model, prompt_hash, ctx.data_as_of, cfg.cache_ttl_hours
        )
        if cached is not None:
            return cached, "ready"
        stale = _read_stale(db, upper, key_model)
        if stale is not None:
            return stale, "stale"
        return None, "unavailable"

    summary = _generate(ctx)
    if summary is None:
        return None, "pending"
    # The cache key's ``model`` is config-derived so GET and POST always agree on the
    # row to read/write. The provider's self-reported model name (which may differ —
    # e.g. ollama reports ``qwen3:8b`` while ``research.summary.model`` stays
    # ``claude-sonnet-4-6``) is carried in the payload's ``model`` field for display
    # attribution, and ``_row_to_summary`` prefers it there.
    _write_cache(db, upper, key_model, prompt_hash, summary)
    return summary, "ready"


def cached_summary_for(
    symbol: str,
    db: Session,
) -> tuple[Summary | None, str]:
    """Read-only cache lookup. **Makes no model call, no ``materialize`` call, no
    network fetch.**

    The GET endpoint uses this before building the ``AnalysisResponse``: on a hit or a
    stale row, the cached summary is returned without paying for ``materialize`` (which
    can trigger SEC fetches and enrichment work — the spec says a GET must not silently
    trigger that any more than it may trigger a model call, design §7). Only on a miss
    (``unavailable``) does the GET route fall through to ``summary_for`` with the full
    analysis, and even then it makes no model call — it returns ``unavailable`` with a
    reason so the client can render a Generate action.
    """
    upper = symbol.upper()
    cfg = get_config().research.summary
    key_model = cfg.model or _provider_model_name(cfg.backend)

    row = db.execute(
        select(SummaryRow)
        .where(SummaryRow.symbol == upper, SummaryRow.model == key_model)
        .order_by(SummaryRow.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None, "unavailable"
    if datetime.now(UTC) - row.generated_at.replace(tzinfo=UTC) > timedelta(
        hours=cfg.cache_ttl_hours
    ):
        return _row_to_summary(row), "stale"
    return _row_to_summary(row), "ready"


def is_watchlisted(db: Session, symbol: str) -> bool:
    """True if *symbol* is on any watchlist (eligible for background generation)."""
    from src.research.store.models import WatchlistItemRow

    upper = symbol.upper()
    row = db.execute(
        select(WatchlistItemRow.symbol).where(WatchlistItemRow.symbol == upper).limit(1)
    ).first()
    return row is not None


def _generate(ctx: ResearchContext) -> Summary | None:
    """Call the configured provider. ``None`` on any failure (fail-soft)."""
    try:
        return get_summary_provider().generate(ctx)
    except Exception as exc:
        log.warning("summary: provider raised (fail-soft): %s", exc)
        return None


def _provider_model_name(backend: str | None = None) -> str:
    """The model name a backend stamps into ``Summary.model``.

    Used only to pre-fill the cache key on a cold miss (before the provider has run and
    returned its own model name). ``ollama`` ignores ``research.summary.model`` and
    reports ``claude.ollama_model``; every other backend reports ``research.summary.model``
    (or its own fallback if that field is empty). After a successful POST the cached
    ``Summary.model`` is what's used for reads, so this only bridges the GET-after-POST
    case where the GET needs to find the row the POST wrote.
    """
    backend = backend or get_config().research.summary.backend
    if backend == "ollama":
        return get_config().claude.ollama_model
    return get_config().research.summary.model or backend


def _hash_prompt(ctx: ResearchContext) -> str:
    prompt = build_prompt(ctx)
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _read_cached(
    db: Session,
    symbol: str,
    model: str,
    prompt_hash: str,
    data_as_of: datetime,
    ttl_hours: int,
) -> Summary | None:
    """Return a fresh cached summary matching the exact key, or ``None``."""
    row = db.execute(
        select(SummaryRow)
        .where(
            SummaryRow.symbol == symbol,
            SummaryRow.model == model,
            SummaryRow.prompt_hash == prompt_hash,
            SummaryRow.data_as_of == data_as_of,
        )
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    if datetime.now(UTC) - row.generated_at.replace(tzinfo=UTC) > timedelta(hours=ttl_hours):
        return None
    return _row_to_summary(row)


def _read_stale(db: Session, symbol: str, model: str) -> Summary | None:
    """Return the most recent cached summary for *symbol* regardless of freshness."""
    row = db.execute(
        select(SummaryRow)
        .where(SummaryRow.symbol == symbol, SummaryRow.model == model)
        .order_by(SummaryRow.generated_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return _row_to_summary(row)


def _write_cache(db: Session, symbol: str, model: str, prompt_hash: str, summary: Summary) -> None:
    """Upsert the summary row. One row per (symbol, model, prompt_hash, data_as_of)."""
    row = db.execute(
        select(SummaryRow)
        .where(
            SummaryRow.symbol == symbol,
            SummaryRow.model == model,
            SummaryRow.prompt_hash == prompt_hash,
            SummaryRow.data_as_of == summary.data_as_of,
        )
        .limit(1)
    ).scalar_one_or_none()
    payload = summary.model_dump(mode="json")
    if row is None:
        row = SummaryRow(
            symbol=symbol,
            model=model,
            prompt_hash=prompt_hash,
            data_as_of=summary.data_as_of,
            payload_json=json.dumps(payload, default=str),
            generated_at=datetime.now(UTC),
        )
        db.add(row)
    else:
        row.payload_json = json.dumps(payload, default=str)
        row.generated_at = datetime.now(UTC)


def _row_to_summary(row: SummaryRow) -> Summary:
    payload = json.loads(row.payload_json)
    # Prefer the model name the provider stamped into the payload; fall back to the
    # column value for rows written before the model-name consistency fix.
    model = payload.get("model") or row.model
    return Summary(
        thesis=payload.get("thesis", ""),
        bull_points=list(payload.get("bull_points") or []),
        bear_points=list(payload.get("bear_points") or []),
        watch_items=list(payload.get("watch_items") or []),
        caveats=list(payload.get("caveats") or []),
        model=model,
        data_as_of=row.data_as_of,
    )


__all__ = ["summary_for", "cached_summary_for", "is_watchlisted"]
