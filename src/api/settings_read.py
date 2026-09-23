"""Shared read of a system_settings row through an injected DB session.

Used by GET /options/controls (the drain heartbeat) and GET /system/status (the drain
and monitor heartbeats) so the two routers read a setting the same way rather than each
keeping its own private copy.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from src.api.deps import TradingDb
from src.api.models.common import as_utc
from src.storage.models import SystemSettingRow


def read_setting(db: TradingDb, key: str) -> str | None:
    row = db.execute(
        select(SystemSettingRow.value).where(SystemSettingRow.key == key)
    ).scalar_one_or_none()
    return row if row is not None else None


def parse_setting_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
        return as_utc(dt)
    except (ValueError, TypeError):
        return None
