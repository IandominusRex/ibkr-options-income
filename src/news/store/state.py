"""Small key/value state in news_state: heartbeat, LLM call counter, per-source last-ok."""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.news.store.models import NewsStateRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session

HEARTBEAT_KEY = "heartbeat"


def _llm_key(day: date) -> str:
    return f"llm_calls:{day.isoformat()}"


def set_state(key: str, value: str, *, now: datetime | None = None) -> None:
    when = naive_utc(now or datetime.now(UTC))
    with news_session() as s:
        row = s.get(NewsStateRow, key)
        if row is None:
            s.add(NewsStateRow(key=key, value=value, updated_at=when))
        else:
            row.value = value
            row.updated_at = when


def get_state(key: str) -> str | None:
    with news_session() as s:
        row = s.get(NewsStateRow, key)
        return None if row is None else row.value


def touch_heartbeat(now: datetime) -> None:
    set_state(HEARTBEAT_KEY, now.astimezone(UTC).isoformat(), now=now)


def record_source_ok(source: str, now: datetime) -> None:
    set_state(f"source_ok:{source}", now.astimezone(UTC).isoformat(), now=now)


def llm_calls(day: date) -> int:
    raw = get_state(_llm_key(day))
    return int(raw) if raw else 0


def incr_llm_calls(day: date) -> int:
    with news_session() as s:
        row = s.get(NewsStateRow, _llm_key(day))
        now = naive_utc(datetime.now(UTC))
        if row is None:
            s.add(NewsStateRow(key=_llm_key(day), value="1", updated_at=now))
            return 1
        row.value = str(int(row.value) + 1)
        row.updated_at = now
        return int(row.value)
