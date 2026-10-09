"""Finnhub free tier (personal use): company/general news with images, earnings calendar.

Probed 2026-10-09 with the operator's key (spec §5.1): company-news, news?category=general,
calendar/earnings and stock/earnings return 200; calendar/economic returns 403 (premium) and
is not used. The key travels only as the ``token`` query parameter and is never logged.
A client-side token bucket keeps us under ``per_minute`` (free tier: 60/min).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from src.data.breaker import get_breaker
from src.data.protocols import EarningsItem, NewsItem

log = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"
_TIMEOUT = 10.0
_HOUR = {"bmo": "bmo", "amc": "amc", "dmh": "unknown", "": "unknown"}


class _Bucket:
    def __init__(self, per_minute: int) -> None:
        self._interval = 60.0 / max(1, per_minute)
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._interval
        if delay:
            time.sleep(delay)


class FinnhubClient:
    def __init__(self, api_key: str, *, per_minute: int = 50) -> None:
        self._key = api_key
        self._bucket = _Bucket(per_minute)

    def _get(self, path: str, **params: Any) -> object | None:
        breaker = get_breaker("finnhub")
        if not breaker.allow():
            return None
        self._bucket.wait()
        try:
            resp = httpx.get(
                f"{_BASE}{path}",
                params={**params, "token": self._key},
                timeout=_TIMEOUT,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:  # noqa: BLE001 — never raise; log only the exception type (httpx messages embed the key-bearing URL)
            log.debug("finnhub: %s failed: %s", path, type(exc).__name__)
            breaker.record_failure()
            return None
        breaker.record_success()
        return body

    @staticmethod
    def _news(rows: object) -> list[NewsItem]:
        out: list[NewsItem] = []
        for r in rows if isinstance(rows, list) else []:
            title = (r.get("headline") or "").strip()
            if not title:
                continue
            ts = r.get("datetime")
            out.append(
                NewsItem(
                    title=title,
                    source=r.get("source") or None,
                    url=r.get("url") or None,
                    published=datetime.fromtimestamp(ts, UTC)
                    if isinstance(ts, int | float) and ts > 0
                    else None,
                    summary=(r.get("summary") or "").strip()[:1000] or None,
                    image_url=r.get("image") or None,
                )
            )
        return out

    def company_news(
        self, symbol: str, *, days: int = 3, today: date | None = None
    ) -> list[NewsItem]:
        end = today or datetime.now(UTC).date()
        start = end - timedelta(days=days)
        return self._news(
            self._get(
                "/company-news",
                symbol=symbol.upper(),
                **{"from": start.isoformat(), "to": end.isoformat()},
            )
        )

    def general_news(self) -> list[NewsItem]:
        return self._news(self._get("/news", category="general"))

    def earnings_calendar(
        self, start: date, end: date, symbol: str | None = None
    ) -> list[EarningsItem]:
        params: dict[str, Any] = {"from": start.isoformat(), "to": end.isoformat()}
        if symbol:
            params["symbol"] = symbol.upper()
        body = self._get("/calendar/earnings", **params)
        rows = body.get("earningsCalendar", []) if isinstance(body, dict) else []
        out: list[EarningsItem] = []
        for r in rows:
            try:
                out.append(
                    EarningsItem(
                        symbol=str(r["symbol"]).upper(),
                        report_date=date.fromisoformat(r["date"]),
                        timing=_HOUR.get(str(r.get("hour") or "").lower(), "unknown"),
                        eps_est=r.get("epsEstimate"),
                        eps_actual=r.get("epsActual"),
                        rev_est=r.get("revenueEstimate"),
                        rev_actual=r.get("revenueActual"),
                        source="finnhub",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return out
