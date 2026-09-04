"""Per-provider circuit breakers.

Mirrors the existing ``market_data.max_consecutive_chain_timeouts`` pattern: consecutive
failures open the circuit, not a failure rate. A breaker that opens too eagerly is worse
than none, so the threshold (default 3) is the number of failures in a row, and a single
success resets the run.

States:
  - **closed** — requests flow; failures increment the run.
  - **open** — ``allow()`` returns False without a network call; the cooldown timer runs.
  - **half_open** — after the cooldown, one request is allowed through. A success closes
    the circuit; a failure re-opens it.

Process-wide registry so :func:`breaker_states` can report every provider's state on
``/health``. Thread-safe via a single lock per breaker.
"""

from __future__ import annotations

import threading
import time

_state_closed = "closed"
_state_open = "open"
_state_half_open = "half_open"


class CircuitBreaker:
    """A consecutive-failure circuit breaker. Thread-safe.

    The breaker is a *consecutive* failure counter, not a rate. An intermittent failure
    that succeeds on retry never accumulates — :meth:`record_success` resets the run.
    """

    def __init__(
        self,
        name: str,
        threshold: int = 3,
        cooldown_seconds: float = 300.0,
    ) -> None:
        self.name = name
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._state = _state_closed

    @property
    def state(self) -> str:
        with self._lock:
            self._maybe_half_open()
            return self._state

    def allow(self) -> bool:
        """True if a request should proceed. Transitions open -> half_open after cooldown."""
        with self._lock:
            self._maybe_half_open()
            if self._state == _state_open:
                return False
            # closed or half_open: allow the request through.
            return True

    def record_success(self) -> None:
        """A request succeeded. Resets the failure run and closes the circuit."""
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._state = _state_closed

    def record_failure(self) -> None:
        """A request failed. Increments the run; opens the circuit at the threshold."""
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._state = _state_open
                self._opened_at = time.monotonic()

    def _maybe_half_open(self) -> None:
        """Transition open -> half_open if the cooldown has elapsed. Must hold the lock."""
        if self._state == _state_open and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self._cooldown:
                self._state = _state_half_open


# --------------------------------------------------------------------------- #
# Process-wide registry
# --------------------------------------------------------------------------- #
_registry: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    name: str, *, threshold: int = 3, cooldown_seconds: float = 300.0
) -> CircuitBreaker:
    """Return the process-wide breaker for *name*, creating it on first access."""
    with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(
                name, threshold=threshold, cooldown_seconds=cooldown_seconds
            )
        return _registry[name]


def breaker_states() -> dict[str, str]:
    """Snapshot of every registered breaker's state, for ``/health``."""
    with _registry_lock:
        return {name: b.state for name, b in _registry.items()}
