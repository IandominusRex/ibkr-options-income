"""Runtime key-value system settings backed by the SQLite system_settings table.

Usage:
    from src.storage.system_settings import is_automated_mode, set_automated_mode
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError

from src.storage.db import session_scope
from src.storage.models import SystemSettingRow

log = logging.getLogger(__name__)

AUTOMATED_MODE_KEY = "automated_mode"
HALT_KEY = "execution_halted"
HALT_REASON_KEY = "execution_halt_reason"
SCAN_LEASE_KEY = "scan_lease_expiry"

# Sortable UTC timestamp (zero-padded) so lexicographic string comparison == chronological.
_LEASE_TS_FMT = "%Y%m%dT%H%M%S.%f"
_LEASE_EXPIRED = "0"  # sentinel < any real timestamp → lease is free


def get_setting(key: str, default: str = "") -> str:
    try:
        with session_scope() as s:
            row = s.query(SystemSettingRow).filter_by(key=key).first()
            return row.value if row else default
    except Exception:
        log.warning("get_setting(%s) failed", key, exc_info=True)
        return default


def set_setting(key: str, value: str) -> None:
    try:
        with session_scope() as s:
            row = s.query(SystemSettingRow).filter_by(key=key).first()
            if row:
                row.value = value
            else:
                s.add(SystemSettingRow(key=key, value=value))
    except Exception:
        log.warning("set_setting(%s=%s) failed", key, value, exc_info=True)


def is_automated_mode() -> bool:
    """Return True when the system is in fully-automated execution mode."""
    return get_setting(AUTOMATED_MODE_KEY, "false").lower() == "true"


def set_automated_mode(enabled: bool) -> None:
    """Persist the automated/manual mode toggle."""
    set_setting(AUTOMATED_MODE_KEY, "true" if enabled else "false")


def is_halted() -> bool:
    """Return True when the master execution kill switch is engaged.

    When halted, no order is queued or transmitted by either the order-poll loop or the
    intraday loop (manual approvals and auto-trades alike). Persisted so it survives a
    daemon restart — a halt must not silently clear itself. Toggled by `/halt` / `/resume`
    or auto-tripped by the circuit breakers (SYSTEM_REVIEW Phase 2).
    """
    return get_setting(HALT_KEY, "false").lower() == "true"


def set_halted(enabled: bool, reason: str = "") -> None:
    """Engage or release the kill switch, recording why it tripped."""
    set_setting(HALT_KEY, "true" if enabled else "false")
    set_setting(HALT_REASON_KEY, reason if enabled else "")


def get_halt_reason() -> str:
    """Human-readable reason the kill switch is engaged (empty when not halted)."""
    return get_setting(HALT_REASON_KEY, "")


def acquire_scan_lease(ttl_seconds: int = 600) -> bool:
    """Try to claim the cross-process scan lease; return True if acquired.

    A full chain scan consumes most of the account-level ~100 market-data line cap. The
    daemon's in-process ``scan_running`` flag can't see a *separate* process (the morning
    cron vs. the 15-min daemon loop), so two could scan at once and poison each other
    (SYSTEM_REVIEW F5). This lease serialises scans across processes.

    Atomic in two ways: a conditional UPDATE only succeeds when the stored expiry is in the
    past (free lease), and the first-ever INSERT is guarded by the row's unique constraint.
    """
    now = datetime.now(UTC)
    now_str = now.strftime(_LEASE_TS_FMT)
    new_expiry = (now + timedelta(seconds=ttl_seconds)).strftime(_LEASE_TS_FMT)
    try:
        with session_scope() as s:
            # Free/expired lease → claim it atomically (row-level conditional update).
            updated = (
                s.query(SystemSettingRow)
                .filter(SystemSettingRow.key == SCAN_LEASE_KEY, SystemSettingRow.value < now_str)
                .update({SystemSettingRow.value: new_expiry}, synchronize_session=False)
            )
            if updated == 1:
                return True
            # Row may not exist yet — first writer wins via the unique constraint.
            exists = s.query(SystemSettingRow).filter_by(key=SCAN_LEASE_KEY).first()
            if exists is None:
                try:
                    with s.begin_nested():
                        s.add(SystemSettingRow(key=SCAN_LEASE_KEY, value=new_expiry))
                    return True
                except IntegrityError:
                    return False
            # Row exists and is unexpired → held by someone else.
            return False
    except Exception:
        log.warning("acquire_scan_lease failed", exc_info=True)
        return False


def release_scan_lease() -> None:
    """Release the scan lease so the next scan can acquire it immediately."""
    set_setting(SCAN_LEASE_KEY, _LEASE_EXPIRED)
