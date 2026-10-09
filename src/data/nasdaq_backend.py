"""Nasdaq's public calendar API — economic actuals (and, Task 8, earnings timing).

Undocumented; needs browser-like headers. Probed 2026-10-09 (spec §5.1): ``date=D`` returns
the US releases of ET day D−1, and the ``gmt`` column holds ET HH:MM. The request date is
``et_day + date_offset_days`` (config ``news.sources.nasdaq_econ_date_offset_days``).
Never raises.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date, timedelta

import httpx

from src.data.breaker import get_breaker
from src.data.protocols import EarningsItem, EconActualItem

log = logging.getLogger(__name__)

_BASE = "https://api.nasdaq.com/api/calendar"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
_HHMM = re.compile(r"^\d{2}:\d{2}$")


def clean_value(v: object) -> str | None:
    if v is None:
        return None
    s = html.unescape(str(v)).replace("\xa0", " ").strip()
    return None if s in ("", "-", "—", "N/A") else s


def _get(path: str, day: date) -> dict | None:
    breaker = get_breaker("nasdaq")
    if not breaker.allow():
        return None
    try:
        resp = httpx.get(
            f"{_BASE}/{path}", params={"date": day.isoformat()}, headers=_HEADERS, timeout=12.0
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.debug("nasdaq: %s %s failed: %s", path, day, exc)
        breaker.record_failure()
        return None
    breaker.record_success()
    return body if isinstance(body, dict) else None


def _rows(body: dict | None) -> list[dict]:
    data = (body or {}).get("data") or {}
    rows = data.get("rows") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def parse_nasdaq_econ(body: dict, et_day: date) -> list[EconActualItem]:
    out: list[EconActualItem] = []
    for r in _rows(body):
        if str(r.get("country") or "") != "United States":
            continue
        title = clean_value(r.get("eventName"))
        if not title:
            continue
        t = str(r.get("gmt") or "").strip()
        out.append(
            EconActualItem(
                title=title,
                et_day=et_day,
                et_time=t if _HHMM.match(t) else None,
                actual=clean_value(r.get("actual")),
                consensus=clean_value(r.get("consensus")),
                previous=clean_value(r.get("previous")),
            )
        )
    return out


class NasdaqEconActualsProvider:
    def __init__(self, date_offset_days: int = 1) -> None:
        self._offset = date_offset_days

    def actuals(self, et_day: date) -> list[EconActualItem]:
        body = _get("economicevents", et_day + timedelta(days=self._offset))
        return parse_nasdaq_econ(body, et_day) if body else []


_TIMING = {"time-pre-market": "bmo", "time-after-hours": "amc"}


def _money(v: object) -> float | None:
    s = clean_value(v)
    if s is None:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def parse_nasdaq_earnings(body: dict, et_day: date) -> list[EarningsItem]:
    out: list[EarningsItem] = []
    for r in _rows(body):
        sym = clean_value(r.get("symbol"))
        if not sym:
            continue
        out.append(
            EarningsItem(
                symbol=sym.upper(),
                report_date=et_day,
                timing=_TIMING.get(str(r.get("time") or ""), "unknown"),
                eps_est=_money(r.get("epsForecast")),
                source="nasdaq",
            )
        )
    return out


class NasdaqEarningsProvider:
    def __init__(self, date_offset_days: int = 0) -> None:
        self._offset = date_offset_days

    def on(self, et_day: date) -> list[EarningsItem]:
        body = _get("earnings", et_day + timedelta(days=self._offset))
        return parse_nasdaq_earnings(body, et_day) if body else []
