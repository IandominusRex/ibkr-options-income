"""ForexFactory weekly calendar JSON — the economic *schedule* (no actuals; spec §5.1).

Unofficial public feed. Cached in-process for 30 minutes (polling it harder gains nothing:
the schedule changes rarely) behind the "forexfactory" breaker. Never raises.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

import httpx

from src.data.breaker import get_breaker
from src.data.protocols import EconScheduleItem

log = logging.getLogger(__name__)

_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_UA = "Mozilla/5.0 (compatible; ibkr-income-system/1.0; news)"
_TTL = 30 * 60
_cache: tuple[float, list[EconScheduleItem]] | None = None
_lock = threading.Lock()


def parse_ff(rows: list[dict]) -> list[EconScheduleItem]:
    out: list[EconScheduleItem] = []
    for r in rows if isinstance(rows, list) else []:
        try:
            when = datetime.fromisoformat(str(r["date"]))
            if when.tzinfo is None:
                continue
            out.append(
                EconScheduleItem(
                    title=str(r["title"]).strip(),
                    country=str(r.get("country") or "").upper(),
                    scheduled_at=when,
                    impact=str(r.get("impact") or ""),
                    forecast=(str(r.get("forecast") or "").strip() or None),
                    previous=(str(r.get("previous") or "").strip() or None),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out


class ForexFactoryScheduleProvider:
    def this_week(self) -> list[EconScheduleItem]:
        global _cache
        with _lock:
            if _cache is not None and time.monotonic() - _cache[0] < _TTL:
                return _cache[1]
        breaker = get_breaker("forexfactory")
        if not breaker.allow():
            return _cache[1] if _cache else []
        try:
            resp = httpx.get(_URL, headers={"User-Agent": _UA}, timeout=10.0)
            resp.raise_for_status()
            items = parse_ff(resp.json())
        except Exception as exc:  # noqa: BLE001
            log.debug("forexfactory: fetch failed: %s", exc)
            breaker.record_failure()
            return _cache[1] if _cache else []
        breaker.record_success()
        with _lock:
            _cache = (time.monotonic(), items)
        return items
