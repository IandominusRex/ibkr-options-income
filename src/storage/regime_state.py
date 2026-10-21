"""Persistence for the market regime: one JSON value in ``system_settings`` (no new table).

The **trading process owns the regime** (the scan and the order poll write it, through this
module only). The news process and the API read it read-only. Keys:

* ``market_regime_state`` — the :class:`~src.common.schemas.RegimeState` JSON: both indices'
  daily base, today's intraday escalation, the effective regime, and the queue of regime changes
  still to be announced on Telegram.
* ``regime_suspended_on`` — the ET date ``/regime off`` was sent. Suspension lasts for that
  trading day only: the next day's base is back under the limits.

Every read-modify-write holds one module-level lock (ruling 41): the scan thread and the order
poll's ``to_thread`` both refresh the regime, and an unlocked load-modify-save would let one
overwrite the other's regime change.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date

from sqlalchemy.orm import Session

from src.common.schemas import RegimeChange, RegimeState
from src.storage.db import session_scope
from src.storage.models import SystemSettingRow
from src.storage.system_settings import get_setting

log = logging.getLogger(__name__)

STATE_KEY = "market_regime_state"
SUSPENDED_KEY = "regime_suspended_on"

# Held across every load-modify-save of the state. Never call another function of this module
# that takes it from inside a callback passed to ``update_regime_state``.
_LOCK = threading.Lock()


def _row(session: Session, key: str) -> SystemSettingRow | None:
    return session.query(SystemSettingRow).filter_by(key=key).first()


def _read(session: Session) -> RegimeState | None:
    row = _row(session, STATE_KEY)
    if row is None or not row.value:
        return None
    try:
        return RegimeState.model_validate_json(row.value)
    except Exception:
        log.warning(
            "regime_state: stored state is unreadable — treating it as absent", exc_info=True
        )
        return None


def _write(session: Session, key: str, value: str) -> None:
    row = _row(session, key)
    if row is None:
        session.add(SystemSettingRow(key=key, value=value))
    else:
        row.value = value


def load_regime_state() -> RegimeState | None:
    """The persisted regime, or None when never written (or unreadable). Never raises."""
    try:
        with session_scope() as s:
            return _read(s)
    except Exception:
        log.warning("regime_state: could not read the regime state", exc_info=True)
        return None


def save_regime_state(state: RegimeState) -> None:
    """Replace the persisted regime. Raises on a database error (callers log and carry on)."""
    with _LOCK, session_scope() as s:
        _write(s, STATE_KEY, state.model_dump_json())


def _locked_update(
    fn: Callable[[RegimeState | None], RegimeState | None],
) -> RegimeState | None:
    with _LOCK, session_scope() as s:
        current = _read(s)
        new = fn(current)
        if new is not None:
            _write(s, STATE_KEY, new.model_dump_json())
        return new


def update_regime_state(fn: Callable[[RegimeState | None], RegimeState]) -> RegimeState:
    """Load the state, apply *fn* to it and save the result, all under one lock (ruling 41).

    *fn* receives the current state (None when never written) and returns the new one. It runs
    while the lock is held, so it must be quick and must not call back into this module.
    """
    result = _locked_update(fn)
    assert result is not None  # fn returns a state
    return result


def suspend_regime(day: date) -> None:
    """Suspend every regime limit for the ET trading day *day* (``/regime off``)."""
    with _LOCK, session_scope() as s:
        _write(s, SUSPENDED_KEY, day.isoformat())


def resume_regime() -> None:
    """Lift a suspension at once (``/regime on``)."""
    with _LOCK, session_scope() as s:
        _write(s, SUSPENDED_KEY, "")


def regime_suspended(day: date) -> bool:
    """True when ``/regime off`` was sent on *day*. The next trading day is never suspended."""
    return get_setting(SUSPENDED_KEY, "") == day.isoformat()


def unsent_changes() -> list[RegimeChange]:
    """Regime changes not yet announced on Telegram, oldest first."""
    state = load_regime_state()
    return [c for c in state.changes if not c.sent] if state else []


def _key(c: RegimeChange) -> tuple[str, str, str, str]:
    return (c.index, c.before.value, c.after.value, c.at.isoformat())


def mark_changes_sent(sent: list[RegimeChange] | None = None) -> None:
    """Flag queued changes as announced (they are kept, only flagged). No-op with no state.

    *sent* names the changes that actually went out; any other change appended since (the order
    poll can refresh the regime while a notice is in flight) stays queued for the next send.
    ``None`` flags every change.
    """
    wanted = None if sent is None else {_key(c) for c in sent}

    def fn(cur: RegimeState | None) -> RegimeState | None:
        if cur is None:
            return None
        return cur.model_copy(
            update={
                "changes": [
                    c.model_copy(update={"sent": True})
                    if wanted is None or _key(c) in wanted
                    else c
                    for c in cur.changes
                ]
            }
        )

    _locked_update(fn)
