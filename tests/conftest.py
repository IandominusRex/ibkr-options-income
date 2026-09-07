"""Shared pytest fixtures."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.common import cache
from src.common.universe import invalidate_universe_cache


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


@pytest.fixture(autouse=True)
def _clear_effective_universe_cache():
    """Reset ``src.common.universe``'s process-local TTL cache around every test (M7 Task 7.3).

    ``effective_universe()`` (read by scan.py, eod_report.py, and others as of Task 7.3) caches
    its composed result for ``_TTL_SECONDS`` of *wall*-monotonic time — far longer than a test
    file takes to run. Several pre-existing scan tests monkeypatch ``get_config().universe``
    directly and expect the change to take effect immediately; without this reset, a value
    cached by an earlier test in the same pytest process would leak into a later one that
    monkeypatches a different universe, independent of any DB override.
    """
    invalidate_universe_cache()
    yield
    invalidate_universe_cache()


@pytest.fixture(autouse=True)
def _mock_telegram_sender(monkeypatch):
    """Prevent tests from hitting the live Telegram API via sender.py helpers.

    send_order_notification creates its own Bot(token=...) internally using the real
    system config — not the mock bot passed to execute_candidate — so without this patch
    executor tests make real HTTP round-trips (~1–2 s each) to Telegram.
    """
    monkeypatch.setattr("src.notify.sender.send_order_notification", AsyncMock())
