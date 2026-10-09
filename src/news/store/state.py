"""Small key/value state in news_state: heartbeat, breaker states, LLM call counter,
per-source last-ok, and alerts the hourly cap held back for the next digest."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from sqlalchemy import select

from src.news.store.models import NewsStateRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session

HEARTBEAT_KEY = "heartbeat"
BREAKERS_KEY = "breakers"
HELD_PREFIX = "held_alert:"


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


def delete_state(keys: list[str]) -> None:
    with news_session() as s:
        for key in keys:
            row = s.get(NewsStateRow, key)
            if row is not None:
                s.delete(row)


def touch_heartbeat(now: datetime, *, breakers: dict[str, str] | None = None) -> None:
    """Beat the watchdog's heartbeat. ``breakers`` (src.data.breaker.breaker_states()) is
    stored beside it: breakers live in the news process's memory, so this is the only way
    ``GET /news/status`` can show them (spec §7.6)."""
    set_state(HEARTBEAT_KEY, now.astimezone(UTC).isoformat(), now=now)
    if breakers is not None:
        set_state(BREAKERS_KEY, json.dumps(breakers, sort_keys=True), now=now)


def record_source_ok(source: str, now: datetime) -> None:
    """Call only when the source answered with data (or an HTTP 304): ``source_ok`` means
    "last good response", not "last polled"."""
    set_state(f"source_ok:{source}", now.astimezone(UTC).isoformat(), now=now)


def _held_key(day: date, kind: str, subject: str) -> str:
    return f"{HELD_PREFIX}{day.isoformat()}|{kind}|{subject}"


def hold_for_digest(day: date, kind: str, subject: str, text: str, *, now: datetime) -> None:
    """A non-critical alert the hourly cap dropped rolls into the next digest (spec §7.2).
    Keyed per (day, kind, subject), so a candidate re-detected every loop is held once — and,
    since a digested entry is kept (marked) rather than deleted, listed in one digest only."""
    key = _held_key(day, kind, subject)
    if get_state(key) is None:
        set_state(key, json.dumps({"at": now.astimezone(UTC).isoformat(), "text": text}), now=now)


def release_held(day: date, kind: str, subject: str) -> None:
    """The alert posted after all (the cap window emptied): it no longer needs the digest."""
    delete_state([_held_key(day, kind, subject)])


def mark_digested(keys: list[str], *, now: datetime) -> None:
    """A digest listed these: keep the rows (so a re-detection the same day is not held
    again) but never list them again. Prune deletes them after a week."""
    with news_session() as s:
        for key in keys:
            row = s.get(NewsStateRow, key)
            if row is None:
                continue
            try:
                d = json.loads(row.value)
            except ValueError:
                d = {}
            row.value = json.dumps({**(d if isinstance(d, dict) else {}), "digested": True})
            row.updated_at = naive_utc(now)


def held_alerts() -> list[tuple[str, datetime, str]]:
    """Every held alert no digest has listed yet, as (key, held_at, text), oldest first.
    Unparseable rows are skipped."""
    with news_session() as s:
        rows = s.scalars(
            select(NewsStateRow).where(NewsStateRow.key.startswith(HELD_PREFIX, autoescape=True))
        )
        raw = [(r.key, r.value) for r in rows]
    out: list[tuple[str, datetime, str]] = []
    for key, value in raw:
        try:
            d = json.loads(value)
            if d.get("digested"):
                continue
            at = datetime.fromisoformat(d["at"])
            text = str(d["text"])
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        out.append((key, at if at.tzinfo else at.replace(tzinfo=UTC), text))
    return sorted(out, key=lambda t: t[1])


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
