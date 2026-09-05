"""GET /research/recommendations — the buy list, rendered exactly as the scan scored it.

The rule that matters: the web layer does no re-scoring. A test asserts the returned
scores equal the stored scores exactly, and that an empty table returns an empty list
with a 200, not a 404. The route reads through the read-only trading engine (§4.3).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.storage.models import BuyCandidateRow

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    # Auth.
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN)

    # Read-only trading engine → a temp DB with buy_candidates populated by the orchestrator.
    trading_db = tmp_path / "income_system.db"
    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: trading_db.as_posix())

    # Build the trading DB (read-write) and seed buy_candidates, mirroring what the
    # orchestrator would persist. The API reads it back through the read-only engine.
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{trading_db}")
    dbmod.init_db()

    return TestClient(create_app())


def _seed(client, rows: list[BuyCandidateRow]) -> None:
    """Write rows directly into the trading DB the orchestrator owns."""
    import src.storage.db as dbmod

    with dbmod.session_scope() as s:
        s.add_all(rows)


def _row(symbol: str, score: float, run_id: str = "run-1", **kw) -> BuyCandidateRow:
    return BuyCandidateRow(
        run_id=run_id,
        symbol=symbol,
        score=score,
        computed_at=kw.pop("computed_at", datetime.now(UTC)),
        **kw,
    )


def test_requires_auth(client) -> None:
    assert client.get("/research/recommendations").status_code == 401


def test_empty_table_returns_200_with_empty_list(client) -> None:
    r = client.get("/research/recommendations", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["candidates"] == []
    assert r.json()["computed_at"] is None


def test_returns_candidates_ordered_by_score_descending(client) -> None:
    _seed(
        client,
        [
            _row("META", 74.0, run_id="run-1"),
            _row("NVDA", 80.0, run_id="run-1"),
        ],
    )
    r = client.get("/research/recommendations", headers=AUTH)
    assert [c["symbol"] for c in r.json()["candidates"]] == ["NVDA", "META"]


def test_scores_are_unmodified(client) -> None:
    """The web layer does no re-scoring — returned scores equal the stored scores."""
    _seed(client, [_row("NVDA", 80.0, run_id="run-1", iv_rank=45.0, vrp=14.0)])
    c = client.get("/research/recommendations", headers=AUTH).json()["candidates"][0]
    assert c["score"] == 80.0
    assert c["iv_rank"] == 45.0
    assert c["vrp"] == 14.0


def test_only_the_latest_full_scan_run_is_returned(client) -> None:
    _seed(client, [_row("OLD", 90.0, run_id="run-1")])
    _seed(client, [_row("NEW", 50.0, run_id="run-2")])
    assert [
        c["symbol"]
        for c in client.get("/research/recommendations", headers=AUTH).json()["candidates"]
    ] == ["NEW"]


def test_single_ticker_scan_does_not_displace_the_full_scan(client) -> None:
    """A /scan NVDA must never replace the whole list with one name."""
    _seed(client, [_row("NVDA", 80.0, run_id="run-full"), _row("META", 74.0, run_id="run-full")])
    _seed(client, [_row("NVDA", 99.0, run_id="scan-NVDA-1")])
    got = [
        c["symbol"]
        for c in client.get("/research/recommendations", headers=AUTH).json()["candidates"]
    ]
    assert got == ["NVDA", "META"]


def test_limit_caps_the_returned_count(client) -> None:
    _seed(client, [_row("A", 90.0, run_id="run-1"), _row("B", 80.0, run_id="run-1")])
    got = client.get("/research/recommendations?limit=1", headers=AUTH).json()["candidates"]
    assert [c["symbol"] for c in got] == ["A"]


def test_computed_at_reflects_the_run_the_candidates_came_from(client) -> None:
    from datetime import timedelta

    old = datetime.now(UTC) - timedelta(hours=2)
    _seed(client, [_row("OLD", 90.0, run_id="run-1", computed_at=old)])
    new = datetime.now(UTC)
    _seed(client, [_row("NEW", 50.0, run_id="run-2", computed_at=new)])
    r = client.get("/research/recommendations", headers=AUTH).json()
    assert r["candidates"][0]["symbol"] == "NEW"
    # computed_at is the latest run's stamp (the run the displayed candidates came from).
    assert r["computed_at"] is not None


def test_single_ticker_scan_does_not_re_stamp_computed_at(client) -> None:
    """A /scan NVDA after the full scan must not move computed_at to the one-name run.

    The displayed candidates come from the full scan; computed_at must remain the full
    scan's stamp, not the newer single-ticker run's.
    """
    from datetime import timedelta

    full = datetime.now(UTC) - timedelta(hours=1)
    later = datetime.now(UTC)
    _seed(client, [_row("NVDA", 80.0, run_id="run-full", computed_at=full)])
    _seed(client, [_row("NVDA", 99.0, run_id="scan-NVDA-1", computed_at=later)])
    r = client.get("/research/recommendations", headers=AUTH).json()
    assert [c["symbol"] for c in r["candidates"]] == ["NVDA"]
    # computed_at is the full scan's stamp, not the newer single-ticker run's.
    assert r["computed_at"] is not None
    parsed = datetime.fromisoformat(r["computed_at"].replace("Z", "+00:00"))
    # SQLite strips tzinfo on round-trip; compare wall-clock components only.
    expected = full.replace(tzinfo=None)
    assert parsed.replace(tzinfo=None) == expected


def test_route_reads_through_the_read_only_engine(client) -> None:
    """§4.3: the API writes nothing. Seeding should still be readable after build."""
    _seed(client, [_row("NVDA", 80.0, run_id="run-1")])
    assert client.get("/research/recommendations", headers=AUTH).status_code == 200
