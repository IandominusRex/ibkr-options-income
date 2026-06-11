"""Process-local, day-scoped cache for expensive idempotent-per-day lookups.

yfinance fundamentals (earnings dates, quality screen) and HV30 change at most once a
day (at the daily close), yet the scan re-fetches them for the whole universe every run —
and the 15-minute automated intraday loop runs the scan ~26 times a session. This decorator
memoizes such calls keyed by ``(args, today)`` so each symbol is fetched at most once per
calendar day in a long-lived process. Entries for prior days are dropped on access.

Thread-safe: per-symbol analytics run in a ThreadPoolExecutor during a scan, so the cache
is guarded by a lock. One-shot scripts (the cron jobs) get no benefit and no harm — the
process exits before a second lookup would hit the cache.

Tests must reset state between cases (symbols are reused with different mocks); an autouse
fixture in ``tests/conftest.py`` calls :func:`clear_all` before every test.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date
from functools import wraps
from typing import Any

# Registry of every cache created by @daily_cached, so tests can flush them all at once.
_REGISTRY: list[dict] = []
_REGISTRY_LOCK = threading.Lock()


def clear_all() -> None:
    """Empty every daily cache. Used by the test harness between cases."""
    with _REGISTRY_LOCK:
        for store in _REGISTRY:
            store.clear()


def daily_cached[F: Callable[..., Any]](fn: F) -> F:
    """Memoize *fn* by ``(args, date.today())``. Args must be hashable.

    Only positional args form the key; keyword args are passed through but not part of
    the key (the wrapped analytics helpers take a single positional symbol).
    """
    store: dict[tuple, Any] = {}
    lock = threading.Lock()
    with _REGISTRY_LOCK:
        _REGISTRY.append(store)

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        today = date.today()
        key = (today, args)
        with lock:
            if key in store:
                return store[key]
            # Drop entries from previous days so the cache can't grow unboundedly.
            stale = [k for k in store if k[0] != today]
            for k in stale:
                del store[k]
        result = fn(*args, **kwargs)
        with lock:
            store[key] = result
        return result

    return wrapper  # type: ignore[return-value]
