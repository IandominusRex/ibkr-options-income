from __future__ import annotations

from datetime import date

import httpx
import pytest

from src.spreads.backtest.thetadata import ThetaDataClient

DAY = date(2026, 10, 7)


def _client(tmp_path, handler, today: date = date(2026, 10, 9)) -> ThetaDataClient:
    return ThetaDataClient(
        "http://127.0.0.1:25503",
        tmp_path,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        today=lambda: today,
    )


def test_index_prices_hit_the_v3_endpoint_as_csv_and_are_cached(tmp_path) -> None:
    seen: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, text="timestamp,price\n2026-10-07T10:00:00.000,6900.5\n")

    c = _client(tmp_path, handler)
    assert c.index_prices("SPX", DAY) == [
        {"timestamp": "2026-10-07T10:00:00.000", "price": "6900.5"}
    ]
    c.index_prices("SPX", DAY)
    assert seen == [
        (
            "/v3/index/history/price",
            {"symbol": "SPX", "date": "20261007", "interval": "1m", "format": "csv"},
        )
    ]


def test_option_endpoints(tmp_path) -> None:
    seen: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, text="strike,right\n")

    c = _client(tmp_path, handler)
    c.option_quotes("SPXW", DAY, DAY)
    c.open_interest("SPXW", DAY, DAY)
    assert seen == [
        (
            "/v3/option/history/quote",
            {
                "symbol": "SPXW",
                "expiration": "20261007",
                "date": "20261007",
                "interval": "1m",
                "format": "csv",
            },
        ),
        (
            "/v3/option/history/open_interest",
            {"symbol": "SPXW", "expiration": "20261007", "date": "20261007", "format": "csv"},
        ),
    ]


def test_http_errors_are_raised_and_never_cached(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="terminal not ready")
        return httpx.Response(200, text="timestamp,price\n")

    c = _client(tmp_path, handler)
    with pytest.raises(httpx.HTTPStatusError):
        c.index_prices("SPX", DAY)
    assert c.index_prices("SPX", DAY) == []
    assert calls["n"] == 2


# Review minor — a day still in progress is never cached (its partial data would stick).
def test_today_is_never_cached(tmp_path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text="timestamp,price\n")

    c = _client(tmp_path, handler, today=DAY)
    c.index_prices("SPX", DAY)
    c.index_prices("SPX", DAY)
    assert calls["n"] == 2 and list(tmp_path.glob("*.csv")) == []
