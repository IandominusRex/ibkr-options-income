"""GET /research/{symbol}/bars returns OHLCV with server-side SMAs in lightweight-charts shape."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.research.store.models import DailyBarRow, SymbolRow
from src.research.store.session import init_research_db, research_session

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN)
    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc."))
    return TestClient(create_app())


def _bar(d: str, close: float) -> DailyBarRow:
    return DailyBarRow(
        symbol="AAPL",
        date=date.fromisoformat(d),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000.0,
        source="yfinance",
    )


def test_bars_returned_in_lightweight_charts_shape(client) -> None:
    with research_session() as s:
        s.add(_bar("2026-01-05", 220.0))
        s.add(_bar("2026-01-06", 221.0))
    r = client.get("/research/AAPL/bars?range=1y", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert "as_of" in body
    bars = body["bars"]
    assert len(bars) == 2
    assert bars[0]["time"] == "2026-01-05"
    for key in ("time", "open", "high", "low", "close", "volume"):
        assert key in bars[0]


def test_sma_50_and_200_computed_server_side(client) -> None:
    """When enough bars exist, the response carries sma50 and sma200 series."""
    rows = []
    base = 220.0
    today = date.today().toordinal()
    for i in range(210):
        d = today - (210 - i)  # 210 trading days back from today, all inside range=1y
        rows.append(
            DailyBarRow(
                symbol="AAPL",
                date=date.fromordinal(d),
                open=base,
                high=base,
                low=base,
                close=base,
                volume=1000.0,
                source="yfinance",
            )
        )
    with research_session() as s:
        for r in rows:
            s.add(r)
    body = client.get("/research/AAPL/bars?range=1y", headers=AUTH).json()
    assert "sma50" in body
    assert "sma200" in body
    # SMA50 starts producing values after 50 bars; SMA200 after 200.
    assert any(v is not None for v in body["sma50"])
    assert any(v is not None for v in body["sma200"])


def test_sma_200_is_seeded_from_history_before_the_display_window(client) -> None:
    """SMA200 needs 200 prior closes. Without extra lookback, the first ~200 trading days
    of a 1y-range response would have a null SMA200 — most of the visible chart. Bars
    outside the display window must not themselves appear in the response.
    """
    today = date.today().toordinal()
    rows = []
    # Seed-only history: 221 bars, all more than 365 days ago (outside the 1y display
    # window) but within the endpoint's SMA lookback buffer — enough to seed SMA200.
    for days_ago in range(620, 399, -1):
        rows.append(_bar(date.fromordinal(today - days_ago).isoformat(), 220.0))
    # Display-window bars: 60 bars, well inside the last 365 days.
    for days_ago in range(60, 0, -1):
        rows.append(_bar(date.fromordinal(today - days_ago).isoformat(), 220.0))
    with research_session() as s:
        for r in rows:
            s.add(r)

    body = client.get("/research/AAPL/bars?range=1y", headers=AUTH).json()
    bars, sma50, sma200 = body["bars"], body["sma50"], body["sma200"]

    assert len(bars) == 60
    assert len(bars) == len(sma50) == len(sma200)
    display_cutoff = date.fromordinal(today - 365).isoformat()
    assert all(b["time"] >= display_cutoff for b in bars), "seed-only bars leaked into bars"
    # With the seed buffer, every bar actually shown already has an SMA200 — not just the
    # last few once the display window itself accumulates 200 bars.
    assert all(v is not None for v in sma200)


def test_unknown_symbol_is_404(client) -> None:
    assert client.get("/research/ZZZZ/bars", headers=AUTH).status_code == 404


def test_a_cold_symbol_triggers_an_on_demand_backfill(client, monkeypatch) -> None:
    """Regression: a symbol with zero daily_bars rows (viewed for the first time, or
    viewed while the nightly warm-tier cron was down) used to render a permanently blank
    chart until the next night's cron ran. The endpoint now backfills once, synchronously,
    the same way `materialize()` already does for fundamentals."""

    def _fake_ingest(symbol: str) -> int:
        with research_session() as s:
            s.add(_bar("2026-01-05", 220.0))
        return 1

    monkeypatch.setattr("src.api.routers.research.ingest_daily_bars", _fake_ingest)
    body = client.get("/research/AAPL/bars?range=1y", headers=AUTH).json()
    assert len(body["bars"]) == 1
    assert body["bars"][0]["time"] == "2026-01-05"


def test_bars_stays_empty_when_the_on_demand_backfill_finds_nothing(client, monkeypatch) -> None:
    """A genuinely unpriceable/delisted symbol must still degrade to empty lists, not an
    error — the on-demand backfill is best-effort, mirroring ingest_daily_bars' own
    contract of leaving history untouched (never raising) on an empty provider fetch."""
    monkeypatch.setattr("src.api.routers.research.ingest_daily_bars", lambda symbol: 0)
    body = client.get("/research/AAPL/bars?range=1y", headers=AUTH).json()
    assert body["bars"] == []
    assert body["sma50"] == []
    assert body["sma200"] == []


def test_bars_stays_empty_when_the_on_demand_backfill_raises(client, monkeypatch) -> None:
    """A provider exception during the on-demand backfill must not 500 the chart — it
    falls through to the existing 'no bars -> empty lists' contract."""

    def _boom(symbol: str) -> int:
        raise RuntimeError("yfinance is down")

    monkeypatch.setattr("src.api.routers.research.ingest_daily_bars", _boom)
    r = client.get("/research/AAPL/bars?range=1y", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["bars"] == []


def test_a_warm_symbol_with_existing_bars_does_not_re_fetch(client, monkeypatch) -> None:
    """The on-demand backfill is only for a symbol with zero rows — a symbol that already
    has history must not pay a fetch on every chart view."""
    with research_session() as s:
        s.add(_bar("2026-01-05", 220.0))

    def _boom(symbol: str) -> int:
        raise AssertionError("ingest_daily_bars must not be called when bars already exist")

    monkeypatch.setattr("src.api.routers.research.ingest_daily_bars", _boom)
    r = client.get("/research/AAPL/bars?range=1y", headers=AUTH)
    assert r.status_code == 200
    assert len(r.json()["bars"]) == 1
