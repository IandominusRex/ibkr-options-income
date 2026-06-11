"""Tests for the process-local daily cache."""

from __future__ import annotations

from src.common import cache
from src.common.cache import daily_cached


def test_memoizes_within_day():
    calls = {"n": 0}

    @daily_cached
    def f(symbol: str) -> str:
        calls["n"] += 1
        return f"{symbol}-{calls['n']}"

    first = f("AAPL")
    second = f("AAPL")
    assert first == second  # second call served from cache
    assert calls["n"] == 1


def test_distinct_args_cached_separately():
    calls = {"n": 0}

    @daily_cached
    def f(symbol: str) -> int:
        calls["n"] += 1
        return calls["n"]

    f("AAPL")
    f("MSFT")
    assert calls["n"] == 2


def test_clear_all_forces_recompute():
    calls = {"n": 0}

    @daily_cached
    def f(symbol: str) -> int:
        calls["n"] += 1
        return calls["n"]

    f("AAPL")
    cache.clear_all()
    f("AAPL")
    assert calls["n"] == 2


def test_stale_day_entries_dropped(monkeypatch):
    import src.common.cache as cmod

    calls = {"n": 0}

    @daily_cached
    def f(symbol: str) -> int:
        calls["n"] += 1
        return calls["n"]

    class _Day:
        value = (2026, 1, 1)

        @classmethod
        def today(cls):
            from datetime import date

            return date(*cls.value)

    monkeypatch.setattr(cmod, "date", _Day)
    f("AAPL")  # cached under 2026-01-01
    _Day.value = (2026, 1, 2)  # roll the day forward
    f("AAPL")  # recomputed for the new day
    assert calls["n"] == 2
