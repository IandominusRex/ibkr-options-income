"""The slow drawdown breaker's state (risk-envelope Task 22; spec §3.4.5, ruling E14).

One ``system_settings`` row, ``slow_breaker_tripped``, JSON ``{"tripped": true, "at", "drawdown_pct",
"threshold_pct", "nlv", "high"}`` while it is tripped and ``{"tripped": false, "reset_at"}`` after a
human reset. The spreads service reads the same key (``src.spreads.service.SLOW_BREAKER_KEY``,
strictly: an unreadable row blocks its entries) and stops opening spreads while ``tripped`` is true.

* **Only a human resets it** (``python -m scripts.envelope reset-slow-breaker``): nothing here clears
  a trip because the drawdown recovered.
* **The wheel's side** is ``csp_budget_fraction()``: ``envelope.slow_breaker.csp_budget_fraction``
  while tripped, else 1.0. It is 1.0 whenever the ``slow_breaker`` switch is ``off`` (and in live,
  where every switch reads its default), so an old trip never throttles the wheel behind a switch
  the operator turned off. An unreadable row with the switch on reads as tripped (fail closed).
* **After a reset the window restarts**: the high is taken over the sessions since the reset (at
  least the current one), so a book still below its old high is not tripped again at once.

Deterministic tier: reads and writes ``system_settings`` only.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.common.config import get_envelope_cfg
from src.storage.envelope_switches import get_switch
from src.storage.system_settings import get_setting_strict, set_setting

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
KEY = "slow_breaker_tripped"


def read_state() -> dict[str, Any] | None:
    """The stored state, or None when never set. Raises when the row cannot be read or parsed (a
    caller that must fail closed catches it)."""
    raw = get_setting_strict(KEY)
    if not raw:
        return None
    data = json.loads(raw)
    return data if isinstance(data, dict) else {"tripped": bool(data)}


def is_tripped() -> bool:
    """Whether the breaker is tripped. An unreadable or unparseable row reads as tripped."""
    try:
        state = read_state()
    except Exception:
        log.warning("slow breaker state unreadable: reading it as tripped", exc_info=True)
        return True
    return bool(state and state.get("tripped"))


def csp_budget_fraction() -> float:
    """What the total CSP allocation is multiplied by: 1.0 unless the switch is on and the breaker
    is tripped (or unreadable)."""
    try:
        if get_switch("slow_breaker") == "off":
            return 1.0
        if not is_tripped():
            return 1.0
        return get_envelope_cfg().slow_breaker.csp_budget_fraction
    except Exception:
        log.warning("slow breaker fraction unreadable: using 1.0", exc_info=True)
        return 1.0


def reset_date() -> date | None:
    """The ET date of the last human reset, or None (never reset, or unreadable)."""
    try:
        state = read_state()
        at = state.get("reset_at") if state else None
        return datetime.fromisoformat(at).astimezone(_ET).date() if isinstance(at, str) else None
    except Exception:
        return None


def trip(*, drawdown_pct: float, threshold_pct: float, nlv: float, high: float) -> bool:
    """Set the trip. True when this call changed the state from not-tripped to tripped (the caller
    notifies exactly then), False when it was already tripped."""
    if is_tripped_strict():
        return False
    state = {
        "tripped": True,
        "at": datetime.now(UTC).isoformat(),
        "drawdown_pct": round(drawdown_pct, 2),
        "threshold_pct": threshold_pct,
        "nlv": round(nlv, 2),
        "high": round(high, 2),
    }
    set_setting(KEY, json.dumps(state))
    return True


def is_tripped_strict() -> bool:
    """Like ``is_tripped`` but an unreadable row raises (``trip`` must not write over state it
    could not read)."""
    state = read_state()
    return bool(state and state.get("tripped"))


def reset() -> dict[str, Any] | None:
    """The human reset: clear the trip and start the window afresh. Returns the state that was
    cleared, or None when the breaker was not tripped (nothing is written)."""
    state = read_state()
    if not state or not state.get("tripped"):
        return None
    stamp = datetime.now(UTC).isoformat()
    set_setting(KEY, json.dumps({"tripped": False, "reset_at": stamp, "cleared": state}))
    return state
