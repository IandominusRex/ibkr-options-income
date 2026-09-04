"""The analysis payload: per-section state, and honest 404s."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.research.ingest.materialize import MaterializeResult, SectionState
from src.research.schemas import LineItemValue, NormalizedFinancials, PeriodStatement
from src.research.store.models import SymbolRow
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
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc.", exchange="Nasdaq"))
    return TestClient(create_app())


def _financials() -> NormalizedFinancials:
    from datetime import date

    return NormalizedFinancials(
        symbol="AAPL",
        cik="0000320193",
        entity_name="Apple Inc.",
        annual=[
            PeriodStatement(
                period_end=date(2024, 9, 28),
                period_type="annual",
                items={
                    "revenue": LineItemValue(
                        line_item="revenue",
                        value=391035000000.0,
                        concept="Revenues",
                        accn="acc-1",
                        filed=date(2024, 11, 1),
                        form="10-K",
                    )
                },
            )
        ],
    )


def test_requires_auth(client) -> None:
    assert client.get("/research/AAPL").status_code == 401


def test_unknown_symbol_is_404(client) -> None:
    assert client.get("/research/ZZZZ", headers=AUTH).status_code == 404


def test_ready_section_carries_data(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol,
            fundamentals=_financials(),
            fundamentals_state=SectionState.READY,
        ),
    )
    body = client.get("/research/AAPL", headers=AUTH).json()
    assert body["symbol"] == "AAPL"
    assert body["fundamentals"]["state"] == "ready"
    assert body["fundamentals"]["data"]["annual"][0]["items"]["revenue"]["value"] > 0


def test_pending_section_is_200_with_a_reason_not_an_error(client, monkeypatch) -> None:
    """A slow section must not fail the page. The client polls."""
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol,
            fundamentals_state=SectionState.PENDING,
            reason="Still building; refresh shortly",
        ),
    )
    r = client.get("/research/AAPL", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["fundamentals"]["state"] == "pending"
    assert r.json()["fundamentals"]["reason"]


def test_unavailable_section_still_returns_the_symbol_header(client, monkeypatch) -> None:
    """An ETF with no XBRL still renders a page. The section explains itself."""
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol,
            fundamentals_state=SectionState.UNAVAILABLE,
            reason="No XBRL financial statements filed for this symbol",
        ),
    )
    body = client.get("/research/AAPL", headers=AUTH).json()
    assert body["name"] == "Apple Inc."
    assert body["fundamentals"]["state"] == "unavailable"
    assert body["fundamentals"]["data"] is None


def test_symbol_lookup_is_case_insensitive(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol, fundamentals_state=SectionState.UNAVAILABLE, reason="x"
        ),
    )
    assert client.get("/research/aapl", headers=AUTH).status_code == 200


def test_quote_staleness_reflects_the_actual_quote_age_not_request_time(
    client, monkeypatch
) -> None:
    """A quote fetched 45 minutes ago (fresh_for is 30 min) must read as stale — using the
    request time instead of the quote row's own as_of would always report it as fresh.
    """
    from datetime import UTC, datetime, timedelta

    old_as_of = datetime.now(UTC) - timedelta(minutes=45)
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol,
            fundamentals_state=SectionState.UNAVAILABLE,
            reason="x",
            quote=221.4,
            quote_as_of=old_as_of,
            quote_state=SectionState.READY,
        ),
    )
    body = client.get("/research/AAPL", headers=AUTH).json()
    assert body["quote"]["value"] == 221.4
    assert body["quote"]["as_of"] is not None
    assert body["quote"]["stale"] is True


def test_a_fresh_quote_is_not_stale(client, monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    recent_as_of = datetime.now(UTC) - timedelta(minutes=5)
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol,
            fundamentals_state=SectionState.UNAVAILABLE,
            reason="x",
            quote=221.4,
            quote_as_of=recent_as_of,
            quote_state=SectionState.READY,
        ),
    )
    assert client.get("/research/AAPL", headers=AUTH).json()["quote"]["stale"] is False


def test_no_quote_ingested_yet_is_null_not_an_error(client, monkeypatch) -> None:
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol, fundamentals_state=SectionState.UNAVAILABLE, reason="x"
        ),
    )
    assert client.get("/research/AAPL", headers=AUTH).json()["quote"] is None


def test_viewing_a_symbol_records_it_for_the_warm_tier(client, monkeypatch) -> None:
    """GET /research/{symbol} is the only signal the warm tier has for "recently viewed" —
    without recording it here, refresh_quotes' recently-viewed half is permanently empty.
    """
    from src.research.store.models import RecentlyViewedRow
    from src.research.store.session import research_session

    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda symbol, **kw: MaterializeResult(
            symbol=symbol, fundamentals_state=SectionState.UNAVAILABLE, reason="x"
        ),
    )
    client.get("/research/AAPL", headers=AUTH)
    with research_session() as s:
        row = s.get(RecentlyViewedRow, ("owner", "AAPL"))
        assert row is not None
        first_seen = row.viewed_at

    client.get("/research/AAPL", headers=AUTH)
    with research_session() as s:
        row = s.get(RecentlyViewedRow, ("owner", "AAPL"))
        assert row.viewed_at >= first_seen, "a re-view should update, not duplicate"
        assert s.query(RecentlyViewedRow).filter_by(symbol="AAPL").count() == 1
