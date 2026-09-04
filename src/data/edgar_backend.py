"""SEC EDGAR backend: the symbol directory and (from Milestone 3) XBRL company facts.

EDGAR is free and keyless, but it has rules, and breaking them gets an IP blocked:
  - Declare a User-Agent carrying a real contact address.
  - Stay under 10 requests/second.
  - Zero-pad CIKs to 10 digits in API paths.
Honour ETags so a repeat fetch of an unchanged document costs a 304.
"""

from __future__ import annotations

import logging
import threading
import time

import httpx

from src.common.config import get_config
from src.data.protocols import SymbolRecord

log = logging.getLogger(__name__)

DIRECTORY_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


def _contact_email() -> str:
    """Indirection so tests can supply a contact address without touching .env."""
    return get_config().secrets.sec_contact_email


def user_agent() -> str:
    """SEC-compliant User-Agent. Raises rather than sending an anonymous request."""
    email = _contact_email()
    if not email:
        raise ValueError(
            "SEC_CONTACT_EMAIL is not set. SEC EDGAR requires a contact address in the "
            "User-Agent header and blocks callers that omit it."
        )
    product = get_config().research.providers.edgar.user_agent_product
    return f"{product} {email}"


class RateLimiter:
    """Thread-safe minimum-interval limiter. Simpler than a bucket and enough here."""

    def __init__(self, rate_per_second: float) -> None:
        self._interval = 1.0 / rate_per_second if rate_per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._next_at = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_at = now + self._interval


class EdgarClient:
    """Rate-limited, ETag-aware JSON client. Never raises on an HTTP failure."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 2,
    ) -> None:
        cfg = get_config().research.providers.edgar
        self._limiter = RateLimiter(cfg.max_requests_per_second)
        self._client = httpx.Client(
            timeout=cfg.timeout_seconds,
            transport=transport,
            headers={"Accept-Encoding": "gzip, deflate"},
        )
        self._max_retries = max_retries

    def get_json(self, url: str, *, etag: str | None = None) -> tuple[dict | None, str | None]:
        """Fetch JSON. Returns (payload, etag); (None, etag) on 304 or on failure."""
        headers = {"User-Agent": user_agent()}
        if etag:
            headers["If-None-Match"] = etag

        for attempt in range(self._max_retries + 1):
            self._limiter.acquire()
            try:
                resp = self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                log.warning("EDGAR request failed for %s: %s", url, exc)
                return None, etag

            if resp.status_code == 304:
                return None, etag
            if resp.status_code == 200:
                return resp.json(), resp.headers.get("ETag", etag)
            if resp.status_code in (403, 429, 500, 502, 503, 504) and attempt < self._max_retries:
                # 403/429: throttle. 5xx: EDGAR transient outage. Retry with backoff.
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(min(float(retry_after), 10.0))
                else:
                    time.sleep(2.0 * (attempt + 1))
                continue
            log.warning("EDGAR returned %s for %s", resp.status_code, url)
            return None, etag
        return None, etag


class EdgarSymbolDirectoryProvider:
    """Every listed US filer, from company_tickers_exchange.json."""

    def __init__(self, client: EdgarClient | None = None) -> None:
        self._client = client or EdgarClient()

    def list_symbols(self) -> list[SymbolRecord]:
        payload, _ = self._client.get_json(DIRECTORY_URL)
        if not payload:
            return []
        try:
            fields = payload["fields"]
            idx = {name: i for i, name in enumerate(fields)}
            rows: list[SymbolRecord] = []
            for row in payload["data"]:
                ticker = str(row[idx["ticker"]] or "").strip().upper()
                if not ticker:
                    continue
                rows.append(
                    SymbolRecord(
                        symbol=ticker,
                        cik=str(row[idx["cik"]]).zfill(10),
                        name=str(row[idx["name"]] or ""),
                        exchange=(str(row[idx["exchange"]]) if row[idx["exchange"]] else None),
                    )
                )
            return rows
        except (KeyError, IndexError, TypeError) as exc:
            log.warning("EDGAR directory payload had an unexpected shape: %s", exc)
            return []


class EdgarFilingsProvider:
    """XBRL company facts. One document per filer, sometimes tens of megabytes."""

    def __init__(self, client: EdgarClient | None = None) -> None:
        self._client = client or EdgarClient()

    def get_company_facts(self, cik: str, *, etag: str | None = None) -> tuple[dict, str | None]:
        cik = (cik or "").strip()
        if not cik:
            return {}, None
        payload, new_etag = self._client.get_json(
            COMPANYFACTS_URL.format(cik=cik.zfill(10)), etag=etag
        )
        return payload or {}, new_etag
