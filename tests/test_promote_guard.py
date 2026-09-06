"""The gate saying no is the point of the gate. No web path may override it.

`POST /commands` with `kind: "promote"` must refuse `risk_gate`, `generator` and
`passed` stages with 409 before an `app_commands` row can exist — a browser cannot
override the deterministic Rules Engine (`risk_gate`) or the strategy filters
(`generator`), and `passed` already has an approval. `score_floor`, `dedupe` and
`top_n` are a ranking decision the operator is entitled to override.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

REFUSED = ("risk_gate", "generator", "passed")
ALLOWED = ("score_floor", "dedupe", "top_n")

_PAYLOAD = {
    "candidate_id": "c1",
    "symbol": "NVDA",
    "strategy": "covered_call",
    "strike": 180.0,
    "expiry": "2026-10-17",
}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN)

    trading_db = tmp_path / "income_system.db"
    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: trading_db.as_posix())
    monkeypatch.setattr("src.api.trading_db._cmd_engine", None)
    monkeypatch.setattr("src.api.trading_db._cmd_session_factory", None)

    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{trading_db}")
    dbmod.init_db()
    return TestClient(create_app())


@pytest.fixture
def seed_assessed():
    """Insert a `RiskVerdictRow` for `candidate_id` at `stage`.

    `candidate_id` is not unique on this table (14 days of run history are kept,
    with no upsert), so a test wanting more than one row for the same candidate
    passes distinct `created_at` values to control which one is "the most recent".
    """
    from src.storage.db import session_scope
    from src.storage.models import RiskVerdictRow

    def _seed(
        *,
        candidate_id: str,
        stage: str,
        symbol: str = "NVDA",
        strategy: str = "covered_call",
        strike: float = 180.0,
        expiry: date | None = None,
        created_at: datetime | None = None,
    ) -> None:
        with session_scope() as s:
            row = RiskVerdictRow(
                candidate_id=candidate_id,
                run_id="run-1",
                symbol=symbol,
                strategy=strategy,
                strike=strike,
                expiry=expiry or (date.today() + timedelta(days=30)),
                verdict="pass" if stage != "risk_gate" and stage != "generator" else "reject",
                stage=stage,
                reasons=[],
                blended_score=70.0,
                premium=3.0,
            )
            if created_at is not None:
                row.created_at = created_at
            s.add(row)

    return _seed


@pytest.fixture
def count_commands():
    """Count rows in `app_commands`, through the read-only engine."""
    from sqlalchemy import func, select

    from src.api.trading_db import trading_session
    from src.storage.models import AppCommandRow

    def _count() -> int:
        with trading_session() as s:
            return s.execute(select(func.count()).select_from(AppCommandRow)).scalar_one()

    return _count


@pytest.mark.parametrize("stage", REFUSED)
def test_a_non_promotable_stage_is_refused(client, seed_assessed, stage) -> None:
    seed_assessed(candidate_id="c1", stage=stage)
    r = client.post(
        "/commands",
        json={"kind": "promote", "payload": _PAYLOAD},
        headers=AUTH,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["reason"] == "stage_not_promotable"
    assert r.json()["detail"]["stage"] == stage


@pytest.mark.parametrize("stage", ALLOWED)
def test_a_promotable_stage_is_accepted(client, seed_assessed, stage) -> None:
    seed_assessed(candidate_id="c1", stage=stage)
    r = client.post(
        "/commands",
        json={"kind": "promote", "payload": _PAYLOAD},
        headers=AUTH,
    )
    assert r.status_code == 201


@pytest.mark.parametrize("stage", REFUSED)
def test_a_refused_promote_leaves_no_command_row(
    client, seed_assessed, count_commands, stage
) -> None:
    seed_assessed(candidate_id="c1", stage=stage)
    before = count_commands()
    client.post(
        "/commands",
        json={"kind": "promote", "payload": _PAYLOAD},
        headers=AUTH,
    )
    assert count_commands() == before


def test_an_unknown_candidate_is_404_not_409(client) -> None:
    r = client.post(
        "/commands",
        json={"kind": "promote", "payload": {**_PAYLOAD, "candidate_id": "nope"}},
        headers=AUTH,
    )
    assert r.status_code == 404


def test_an_unknown_candidate_leaves_no_command_row(client, count_commands) -> None:
    before = count_commands()
    client.post(
        "/commands",
        json={"kind": "promote", "payload": {**_PAYLOAD, "candidate_id": "nope"}},
        headers=AUTH,
    )
    assert count_commands() == before


def test_the_most_recent_assessed_row_wins_over_an_older_refusal(client, seed_assessed) -> None:
    """candidate_id is not unique across runs. An older `risk_gate` rejection must
    not shadow a newer `top_n` re-assessment — the newest row (by created_at, id
    as tiebreaker) is the one that governs promotability."""
    now = datetime.now(UTC)
    seed_assessed(candidate_id="c1", stage="risk_gate", created_at=now - timedelta(hours=1))
    seed_assessed(candidate_id="c1", stage="top_n", created_at=now)
    r = client.post(
        "/commands",
        json={"kind": "promote", "payload": _PAYLOAD},
        headers=AUTH,
    )
    assert r.status_code == 201


def test_the_most_recent_assessed_row_can_refuse_an_older_pass(client, seed_assessed) -> None:
    """Symmetric case: a newer risk_gate row must override an older promotable one."""
    now = datetime.now(UTC)
    seed_assessed(candidate_id="c1", stage="top_n", created_at=now - timedelta(hours=1))
    seed_assessed(candidate_id="c1", stage="risk_gate", created_at=now)
    r = client.post(
        "/commands",
        json={"kind": "promote", "payload": _PAYLOAD},
        headers=AUTH,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["stage"] == "risk_gate"


def test_the_guard_reads_through_the_read_only_engine(client, seed_assessed) -> None:
    """`assert_promotable` is exercised directly against a `trading_session` —
    the read-only engine, never the write-scoped command engine."""
    from fastapi import HTTPException

    from src.api.routers.commands import assert_promotable
    from src.api.trading_db import trading_session

    seed_assessed(candidate_id="c1", stage="score_floor")
    with trading_session() as s:
        row = assert_promotable(s, "c1")
        assert row.candidate_id == "c1"
        assert row.stage == "score_floor"

    with trading_session() as s:
        with pytest.raises(HTTPException) as exc_info:
            assert_promotable(s, "does-not-exist")
        assert exc_info.value.status_code == 404


def test_promotable_stages_match_the_spec_exactly() -> None:
    """A future edit that widens PROMOTABLE_STAGES must fail here first."""
    from src.api.routers.commands import PROMOTABLE_STAGES

    assert PROMOTABLE_STAGES == frozenset({"score_floor", "dedupe", "top_n"})
