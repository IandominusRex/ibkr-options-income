"""Runtime key-value system settings backed by the SQLite system_settings table.

Usage:
    from src.storage.system_settings import is_automated_mode, set_automated_mode
"""

from __future__ import annotations

import logging

from src.storage.db import session_scope
from src.storage.models import SystemSettingRow

log = logging.getLogger(__name__)

AUTOMATED_MODE_KEY = "automated_mode"


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
