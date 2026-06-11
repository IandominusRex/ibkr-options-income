"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from src.common import cache


@pytest.fixture(autouse=True)
def _clear_daily_caches():
    """Reset the process-local daily caches around every test.

    Analytics helpers (get_fundamental_stats, _compute_hv30) are @daily_cached, and tests
    reuse the same symbol with different yfinance mocks. Without this, a cached result from
    one test would leak into the next and mask the mock.
    """
    cache.clear_all()
    yield
    cache.clear_all()
