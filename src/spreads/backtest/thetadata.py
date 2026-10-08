"""ThetaData v3 REST client (the local Theta Terminal) with an on-disk CSV cache.

Endpoints (https://thetadata.net/docs, v3; Terminal default http://127.0.0.1:25503):
  GET /v3/option/history/quote          symbol, expiration, date, interval → bid/ask per strike/right/time
  GET /v3/option/history/open_interest  symbol, expiration, date           → prior-close OI (OPRA ~06:30 ET)
  GET /v3/index/history/price           symbol, date, interval             → index price per time
Responses are requested as CSV and cached by (path, params), so a re-run never re-downloads a
day — one $80 month of Options Standard is enough to build the cache, then cancel. A day that
is not over yet (today, ET) is never cached: its partial data would be served forever.
"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import httpx

from src.common.market_hours import today_et


class ThetaDataClient:
    def __init__(
        self,
        base_url: str,
        cache_dir: Path,
        *,
        http: httpx.Client | None = None,
        timeout: float = 120.0,
        today: Callable[[], date] = today_et,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.http = http or httpx.Client(timeout=timeout)
        self.today = today

    def _get(self, path: str, params: dict[str, str]) -> list[dict[str, str]]:
        key = hashlib.sha256(f"{path}?{urlencode(sorted(params.items()))}".encode()).hexdigest()[
            :32
        ]
        cached = self.cache_dir / f"{key}.csv"
        if cached.exists():
            text = cached.read_text(encoding="utf-8")
        else:
            r = self.http.get(f"{self.base_url}{path}", params={**params, "format": "csv"})
            r.raise_for_status()
            text = r.text
            if params.get("date", "") < f"{self.today():%Y%m%d}":
                cached.write_text(text, encoding="utf-8")
        return list(csv.DictReader(io.StringIO(text)))

    def option_quotes(
        self, symbol: str, expiration: date, day: date, interval: str = "1m"
    ) -> list[dict[str, str]]:
        return self._get(
            "/v3/option/history/quote",
            {
                "symbol": symbol,
                "expiration": f"{expiration:%Y%m%d}",
                "date": f"{day:%Y%m%d}",
                "interval": interval,
            },
        )

    def open_interest(self, symbol: str, expiration: date, day: date) -> list[dict[str, str]]:
        return self._get(
            "/v3/option/history/open_interest",
            {"symbol": symbol, "expiration": f"{expiration:%Y%m%d}", "date": f"{day:%Y%m%d}"},
        )

    def index_prices(self, symbol: str, day: date, interval: str = "1m") -> list[dict[str, str]]:
        return self._get(
            "/v3/index/history/price",
            {"symbol": symbol, "date": f"{day:%Y%m%d}", "interval": interval},
        )
