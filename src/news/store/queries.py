"""Session-parameterised read helpers over data/news.db.

Takes a Session and never opens one, so the news process (read-write engine), the API
(src/api/news_db.py, read-only) and the read-only readers share one query implementation.
Imports no engine module — src/api/ may import this file (spec §10.6).
"""

from __future__ import annotations

from datetime import UTC, datetime


def naive_utc(dt: datetime) -> datetime:
    """Aware → naive UTC for storage (the spreads-store convention). Naive input is assumed UTC."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def aware_utc(dt: datetime) -> datetime:
    """Stored naive-UTC → aware UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
