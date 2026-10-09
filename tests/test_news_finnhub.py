from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from src.data.finnhub_backend import FinnhubClient

FIX = Path(__file__).parent / "fixtures" / "news"


def _router(monkeypatch, routes: dict[str, object], seen: list[str]) -> None:
    def fake_get(url, params, timeout, headers):
        seen.append(url)
        assert params["token"] == "KEY"
        for suffix, body in routes.items():
            if url.endswith(suffix):
                return httpx.Response(200, json=body, request=httpx.Request("GET", url))
        return httpx.Response(403, json={"error": "no"}, request=httpx.Request("GET", url))

    monkeypatch.setattr("src.data.finnhub_backend.httpx.get", fake_get)


def test_company_news_maps_fields_and_drops_empty(monkeypatch) -> None:
    seen: list[str] = []
    _router(
        monkeypatch,
        {"/company-news": json.loads((FIX / "finnhub_company_news.json").read_text())},
        seen,
    )
    items = FinnhubClient("KEY").company_news("NVDA", days=2, today=date(2026, 10, 9))
    assert len(items) == 1
    it = items[0]
    assert it.image_url.startswith("https://s.yimg.com") and it.summary.startswith("Google may")
    assert it.source == "Yahoo" and it.published is not None


def test_earnings_calendar_timing_and_actuals(monkeypatch) -> None:
    seen: list[str] = []
    _router(
        monkeypatch,
        {"/calendar/earnings": json.loads((FIX / "finnhub_earnings_calendar.json").read_text())},
        seen,
    )
    rows = FinnhubClient("KEY").earnings_calendar(date(2026, 10, 9), date(2026, 10, 16))
    by = {r.symbol: r for r in rows}
    assert by["BAC"].timing == "bmo" and by["BAC"].eps_actual is None
    assert by["NFLX"].timing == "amc" and by["NFLX"].eps_actual == 5.4
    assert by["ZZZ"].timing == "unknown"


def test_errors_never_raise_and_key_never_logged(monkeypatch, caplog) -> None:
    seen: list[str] = []
    _router(monkeypatch, {}, seen)
    c = FinnhubClient("KEY")
    assert c.general_news() == []
    assert "KEY" not in caplog.text


def test_factory_returns_none_without_key(monkeypatch) -> None:
    from src.common.config import get_config
    from src.data import factory

    monkeypatch.setattr(get_config().secrets, "finnhub_api_key", "")
    factory.get_finnhub_client.cache_clear()
    assert factory.get_finnhub_client() is None
    factory.get_finnhub_client.cache_clear()
