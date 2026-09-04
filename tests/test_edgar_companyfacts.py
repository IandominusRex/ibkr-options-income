"""Company facts: CIK padding, ETag reuse, and fail-soft behaviour."""

from __future__ import annotations

import httpx
import pytest

from src.data.edgar_backend import EdgarClient, EdgarFilingsProvider

_FACTS = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {"us-gaap": {"Assets": {"units": {"USD": [{"end": "2024-09-28", "val": 1}]}}}},
}


@pytest.fixture(autouse=True)
def _contact(monkeypatch):
    monkeypatch.setattr("src.data.edgar_backend._contact_email", lambda: "t@example.com")


def test_requests_a_zero_padded_cik() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_FACTS, headers={"ETag": "abc"})

    p = EdgarFilingsProvider(client=EdgarClient(transport=httpx.MockTransport(handler)))
    payload, _etag = p.get_company_facts("320193")
    assert "CIK0000320193.json" in seen[0]
    assert payload["entityName"] == "Apple Inc."


def test_already_padded_cik_is_not_double_padded() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=_FACTS, headers={"ETag": "abc"})

    p = EdgarFilingsProvider(client=EdgarClient(transport=httpx.MockTransport(handler)))
    p.get_company_facts("0000320193")
    assert "CIK0000320193.json" in seen[0]


def test_returns_the_payload_and_etag() -> None:
    p = EdgarFilingsProvider(
        client=EdgarClient(
            transport=httpx.MockTransport(
                lambda _r: httpx.Response(200, json=_FACTS, headers={"ETag": "v1"})
            )
        )
    )
    payload, etag = p.get_company_facts("320193")
    assert payload["entityName"] == "Apple Inc."
    assert etag == "v1"


def test_304_returns_empty_payload_but_preserves_the_etag() -> None:
    """A 304 means the caller's cached payload is still current; the etag is returned
    so the caller can keep using it, and an empty payload signals 'no new body'."""
    p = EdgarFilingsProvider(
        client=EdgarClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(304, headers={"ETag": "v1"}))
        )
    )
    payload, etag = p.get_company_facts("320193", etag="v1")
    assert payload == {}
    assert etag == "v1"


def test_returns_empty_dict_on_404_rather_than_raising() -> None:
    """Not every filer has XBRL facts. A missing document degrades the page, not the request."""
    p = EdgarFilingsProvider(
        client=EdgarClient(
            transport=httpx.MockTransport(lambda _r: httpx.Response(404)), max_retries=0
        )
    )
    payload, _etag = p.get_company_facts("320193")
    assert payload == {}


def test_blank_cik_short_circuits_without_a_request() -> None:
    called = False

    def handler(_r: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_FACTS, headers={"ETag": "abc"})

    p = EdgarFilingsProvider(client=EdgarClient(transport=httpx.MockTransport(handler)))
    payload, etag = p.get_company_facts("")
    assert payload == {}
    assert etag is None
    assert called is False
