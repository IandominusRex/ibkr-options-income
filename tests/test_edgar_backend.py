"""EDGAR client: User-Agent policy, rate limiting, ETag handling, directory parsing."""

from __future__ import annotations

import time

import httpx
import pytest

from src.data.edgar_backend import (
    EdgarClient,
    EdgarSymbolDirectoryProvider,
    RateLimiter,
    user_agent,
)

_DIRECTORY = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        [789019, "MICROSOFT CORP", "MSFT", "Nasdaq"],
        [1045810, "NVIDIA CORP", "NVDA", "Nasdaq"],
    ],
}


@pytest.fixture(autouse=True)
def _contact(monkeypatch):
    monkeypatch.setattr(
        "src.data.edgar_backend._contact_email", lambda: "trader@example.com"
    )


def test_user_agent_carries_a_contact_address() -> None:
    """SEC requires a contact address in the User-Agent or it blocks the caller."""
    ua = user_agent()
    assert "trader@example.com" in ua
    assert "IBKR-Income-System" in ua


def test_user_agent_raises_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr("src.data.edgar_backend._contact_email", lambda: "")
    with pytest.raises(ValueError, match="SEC_CONTACT_EMAIL"):
        user_agent()


def test_rate_limiter_spaces_requests() -> None:
    limiter = RateLimiter(rate_per_second=20.0)  # 50ms apart
    start = time.monotonic()
    for _ in range(3):
        limiter.acquire()
    assert time.monotonic() - start >= 0.09  # two gaps of 50ms


def test_client_sends_the_user_agent_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"ok": True}, headers={"ETag": "abc"})

    client = EdgarClient(transport=httpx.MockTransport(handler))
    payload, etag = client.get_json("https://data.sec.gov/x.json")
    assert payload == {"ok": True}
    assert etag == "abc"
    assert "trader@example.com" in seen["user-agent"]


def test_client_returns_none_on_304_not_modified() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(304, headers={"ETag": "abc"})

    client = EdgarClient(transport=httpx.MockTransport(handler))
    payload, etag = client.get_json("https://data.sec.gov/x.json", etag="abc")
    assert payload is None
    assert etag == "abc"


def test_client_returns_none_on_429_rather_than_raising() -> None:
    """A throttled SEC must degrade the page, not crash the request."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429)

    client = EdgarClient(transport=httpx.MockTransport(handler), max_retries=0)
    payload, _ = client.get_json("https://data.sec.gov/x.json")
    assert payload is None


def test_directory_parses_and_zero_pads_cik() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_DIRECTORY)

    provider = EdgarSymbolDirectoryProvider(
        client=EdgarClient(transport=httpx.MockTransport(handler))
    )
    rows = provider.list_symbols()
    assert len(rows) == 3
    apple = next(r for r in rows if r.symbol == "AAPL")
    assert apple.cik == "0000320193"  # zero-padded to 10
    assert apple.name == "Apple Inc."
    assert apple.exchange == "Nasdaq"


def test_directory_returns_empty_list_on_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    provider = EdgarSymbolDirectoryProvider(
        client=EdgarClient(transport=httpx.MockTransport(handler), max_retries=0)
    )
    assert provider.list_symbols() == []
