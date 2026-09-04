"""Consecutive failures open a provider's circuit; one success closes it."""

from __future__ import annotations

import time

from src.data.breaker import CircuitBreaker


def test_starts_closed_and_allows() -> None:
    b = CircuitBreaker("edgar", threshold=3)
    assert b.state == "closed"
    assert b.allow() is True


def test_opens_after_consecutive_failures() -> None:
    b = CircuitBreaker("edgar", threshold=3, cooldown_seconds=60)
    for _ in range(3):
        b.record_failure()
    assert b.state == "open"
    assert b.allow() is False


def test_a_success_resets_the_failure_run() -> None:
    """Consecutive, not cumulative. An intermittent failure must not accumulate forever."""
    b = CircuitBreaker("edgar", threshold=3, cooldown_seconds=60)
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    assert b.state == "closed"


def test_it_half_opens_after_the_cooldown() -> None:
    b = CircuitBreaker("edgar", threshold=1, cooldown_seconds=0.01)
    b.record_failure()
    assert b.allow() is False
    time.sleep(0.02)
    assert b.allow() is True
    assert b.state == "half_open"


def test_a_success_while_half_open_closes_it() -> None:
    b = CircuitBreaker("edgar", threshold=1, cooldown_seconds=0.01)
    b.record_failure()
    time.sleep(0.02)
    b.allow()
    b.record_success()
    assert b.state == "closed"


def test_a_failure_while_half_open_reopens_it() -> None:
    b = CircuitBreaker("edgar", threshold=1, cooldown_seconds=0.01)
    b.record_failure()
    time.sleep(0.02)
    b.allow()
    b.record_failure()
    assert b.state == "open"
