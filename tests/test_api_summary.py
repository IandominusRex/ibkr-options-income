"""API route tests for the summary endpoints (M7 Task 7.4).

GET makes no model call; POST generates and caches; a cold-tier search on a symbol
with no cached summary returns ``unavailable`` without invoking the provider.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.research.ingest.materialize import MaterializeResult, SectionState
from src.research.store.models import SymbolRow
from src.research.store.session import init_research_db, research_session
from src.research.summary.protocol import Summary

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
NOW = datetime.now(UTC)


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
        s.add(
            SymbolRow(
                symbol="AAPL",
                cik="0000320193",
                name="Apple Inc.",
                exchange="Nasdaq",
                updated_at=NOW,
            )
        )
    return TestClient(create_app())


def _empty_materialize(symbol, **kw):
    return MaterializeResult(symbol=symbol, fundamentals_state=SectionState.UNAVAILABLE)


def test_get_summary_with_no_cache_returns_unavailable_and_no_model_call(
    client, monkeypatch
) -> None:
    monkeypatch.setattr("src.api.routers.research.materialize", _empty_materialize)
    calls = {"n": 0}

    def _gen(_ctx):
        calls["n"] += 1
        return None

    from src.research.summary import service as svc

    monkeypatch.setattr(svc, "_generate", _gen)
    body = client.get("/research/AAPL/summary", headers=AUTH).json()
    assert body["state"] == "unavailable"
    assert body["summary"] is None
    assert calls["n"] == 0


def test_post_summary_generates_and_caches(client, monkeypatch) -> None:
    monkeypatch.setattr("src.api.routers.research.materialize", _empty_materialize)

    fixed = Summary(
        thesis="Cached thesis",
        bull_points=["b1"],
        bear_points=[],
        watch_items=[],
        caveats=["Quantitative only."],
        model="test-model",
        data_as_of=NOW,
    )
    from src.research.summary import service as svc

    monkeypatch.setattr(svc, "_generate", lambda _ctx: fixed)
    r = client.post("/research/AAPL/summary", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "ready"
    assert body["summary"]["thesis"] == "Cached thesis"

    # GET now reads from cache — no model call.
    monkeypatch.setattr(svc, "_generate", lambda _ctx: pytest.fail("cache miss"))
    body2 = client.get("/research/AAPL/summary", headers=AUTH).json()
    assert body2["state"] == "ready"
    assert body2["summary"]["thesis"] == "Cached thesis"


def test_post_summary_failed_generation_returns_pending(client, monkeypatch) -> None:
    monkeypatch.setattr("src.api.routers.research.materialize", _empty_materialize)
    from src.research.summary import service as svc

    monkeypatch.setattr(svc, "_generate", lambda _ctx: None)
    body = client.post("/research/AAPL/summary", headers=AUTH).json()
    assert body["state"] == "pending"
    assert body["summary"] is None
    assert body["reason"]


def test_get_summary_unknown_symbol_is_404(client) -> None:
    assert client.get("/research/ZZZZ/summary", headers=AUTH).status_code == 404


def test_get_summary_requires_auth(client) -> None:
    assert client.get("/research/AAPL/summary").status_code == 401


def test_get_summary_with_cache_hit_makes_no_materialize_call(client, monkeypatch) -> None:
    """A GET on a symbol with a cached summary must not run ``materialize`` (which can
    trigger SEC fetches and enrichment work). The cache row is returned directly.
    """
    # First, POST to populate the cache.
    monkeypatch.setattr("src.api.routers.research.materialize", _empty_materialize)
    fixed = Summary(
        thesis="Cached",
        bull_points=[],
        bear_points=[],
        watch_items=[],
        caveats=[],
        model="test-model",
        data_as_of=NOW,
    )
    from src.research.summary import service as svc

    monkeypatch.setattr(svc, "_generate", lambda _ctx: fixed)
    r = client.post("/research/AAPL/summary", headers=AUTH)
    assert r.status_code == 200

    # Now GET: materialize must NOT be called, and the cache hit is returned.
    monkeypatch.setattr(
        "src.api.routers.research.materialize",
        lambda *a, **kw: pytest.fail("materialize called on a cache hit"),
    )
    monkeypatch.setattr(svc, "_generate", lambda _ctx: pytest.fail("model call on GET"))
    body = client.get("/research/AAPL/summary", headers=AUTH).json()
    assert body["state"] == "ready"
    assert body["summary"]["thesis"] == "Cached"
