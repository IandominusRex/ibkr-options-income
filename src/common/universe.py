"""Compose ``config/universe.yaml`` with operator overrides from the ``universe_overrides``
table (``src/storage/universe_overrides.py``, M7 Task 7.1) into the *effective* scan universe.

Only ``would_own`` and ``watchlist`` are overridable — see ``OVERRIDABLE_LISTS``. Every other
key in ``config/universe.yaml`` (``indexes``, ``actively_wheeling``, ``sectors``,
``strike_bands``, ``leveraged_etfs``) passes through byte-for-byte, even if a stray override row
names one of them (defence in depth: the API and the schema already refuse it; this composer
refuses it again). ``sectors`` feeds ``risk_engine``'s concentration limits, so it must never be
movable from the web. See Web plan/P2-design.md §7.2 and §7.3.

``get_config()`` itself is never touched here: it is ``functools.lru_cache``'d with no
invalidation and is called from the risk engine, so composing overrides *inside* it would
(a) make ``src/common/config.py`` import a storage module and (b) never become visible to a
running process without a restart. ``effective_universe()`` is a separate accessor instead, with
its own small in-process TTL cache (a plain ``(dict, monotonic timestamp)`` tuple — this needs
both a TTL *and* a manual ``invalidate_universe_cache()`` escape hatch, which
``functools.lru_cache`` doesn't offer, so it isn't reused here).

Overrides are read through ``src.storage.db.session_scope()`` — a plain SQLAlchemy session on
its own connection — rather than the API's specially-fenced ``trading_session``/
``get_command_engine`` pair, since this module only ever reads (never writes) and has no reason
to go through that write-scoped fence.

Fail-safe: an unreadable overrides table (locked SQLite, missing table, anything at all) returns
the YAML base untouched and logs a warning — this must never raise, and must never return an
empty universe. A scan has to keep working against the file it has always had.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.common.config import get_config
from src.storage.db import session_scope
from src.storage.models import UniverseOverrideRow
from src.storage.universe_overrides import all_overrides

log = logging.getLogger(__name__)

# The only two universe.yaml lists an operator may add/remove symbols from through the web UI.
# Every other key in config/universe.yaml is a pure passthrough.
OVERRIDABLE_LISTS: frozenset[str] = frozenset({"would_own", "watchlist"})

# How long a computed effective universe is reused before being recomputed from the DB + YAML.
_TTL_SECONDS = 60

# (computed effective universe, time.monotonic() it was computed at) — never wall-clock, so a
# system clock adjustment can't corrupt the TTL. None means "not computed yet, or invalidated".
_cache: tuple[dict[str, Any], float] | None = None


def _read_overrides() -> list[UniverseOverrideRow]:
    """Read every override row on its own session.

    A small, separate function so failure-injection tests can monkeypatch exactly this call
    (``src.common.universe._read_overrides``) without reaching into ``session_scope`` itself.
    """
    with session_scope() as session:
        return all_overrides(session)


def _compose_list(
    base_list: list[str],
    overrides: list[UniverseOverrideRow],
    *,
    remove_guard: frozenset[str],
) -> list[str]:
    """YAML file order first (minus removed symbols), then added symbols in ``created_at`` order.

    ``overrides`` must already be filtered to the one ``list_name`` being composed.
    ``remove_guard`` holds symbols a ``remove`` override must not affect — the
    ``actively_wheeling`` guard on ``would_own`` (design point 3): you cannot stop being willing
    to own something you are actively wheeling.
    """
    removed = {
        row.symbol for row in overrides if row.action == "remove" and row.symbol not in remove_guard
    }
    added = sorted(
        (row for row in overrides if row.action == "add"), key=lambda row: row.created_at
    )

    composed = [symbol for symbol in base_list if symbol not in removed]
    present = set(composed)
    for row in added:
        if row.symbol not in present:
            composed.append(row.symbol)
            present.add(row.symbol)
    return composed


def effective_universe() -> dict[str, Any]:
    """``config/universe.yaml`` with ``universe_overrides`` composed onto it.

    Only ``would_own`` and ``watchlist`` are composed; every other key is passed through from
    the YAML untouched, so sectors (and therefore risk_engine's concentration limits) can never
    be moved from the web. See Web plan/P2-design.md §7.2.

    Cached for ``_TTL_SECONDS``. An unreadable overrides table returns the YAML base — the safe
    direction — and logs a warning.
    """
    global _cache
    now = time.monotonic()
    if _cache is not None:
        computed, computed_at = _cache
        if now - computed_at < _TTL_SECONDS:
            return computed

    base = get_config().universe

    try:
        overrides = [row for row in _read_overrides() if row.list_name in OVERRIDABLE_LISTS]
    except Exception:
        log.warning(
            "effective_universe: could not read universe_overrides — falling back to the "
            "config/universe.yaml base untouched",
            exc_info=True,
        )
        overrides = []

    remove_guard = frozenset(base.get("actively_wheeling") or [])

    # A shallow `dict(base)` copies the top-level dict but aliases every value inside it —
    # `composed["sectors"]` would be the literal same dict object as `get_config().universe
    # ["sectors"]`, which is itself a single `@functools.lru_cache(maxsize=1)`-cached,
    # process-wide-shared object that risk_engine.py reads for concentration limits.
    # Nothing mutates it today, so this was not a live bug, but the object is unusually
    # consequential and copying one level deeper is cheap (M7 final-review Fix 5): every
    # passthrough value gets its own copy — dict-valued keys (sectors, strike_bands) via
    # `dict(v)`, list-valued keys (indexes, actively_wheeling, leveraged_etfs) via `list(v)`
    # — so nothing a caller does to `effective_universe()`'s return value can ever reach the
    # cached config object.
    composed: dict[str, Any] = {}
    for key, value in base.items():
        if key in OVERRIDABLE_LISTS:
            continue
        if isinstance(value, dict):
            composed[key] = dict(value)
        elif isinstance(value, list):
            composed[key] = list(value)
        else:
            composed[key] = value

    for list_name in OVERRIDABLE_LISTS:
        base_list = list(base.get(list_name) or [])
        list_overrides = [row for row in overrides if row.list_name == list_name]
        guard = remove_guard if list_name == "would_own" else frozenset()
        composed[list_name] = _compose_list(base_list, list_overrides, remove_guard=guard)

    _cache = (composed, now)
    return composed


def invalidate_universe_cache() -> None:
    """Called by the drain after applying a universe command, so an edit is visible at once in
    the process that made it rather than up to ``_TTL_SECONDS`` later."""
    global _cache
    _cache = None


def is_leveraged_etf(symbol: str) -> bool:
    """True if *symbol* is on ``config/universe.yaml → leveraged_etfs`` (file-only key).

    Used by the loss exit: a short on a leveraged ETF is closed at the loss line because the
    product can run against the position too fast to manage; every other short is rolled.
    """
    raw = get_config().universe.get("leveraged_etfs") or []
    return symbol.upper() in {str(s).upper() for s in raw}
