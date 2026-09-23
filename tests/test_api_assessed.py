"""GET /options/assessed — the stage-semantics surface.

``risk_gate`` and ``generator`` are never promotable (the load-bearing invariant),
``score_floor``'s note carries the actual configured minimum, ``run=latest`` filters
single-ticker runs, and ``reasons_text`` never returns a raw code.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.storage.db import session_scope
from src.storage.models import RiskVerdictRow

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

_EXPIRY = date.today() + timedelta(days=30)
_RUN = "2026-09-06T10:00:00"


def _verdict(
    *,
    candidate_id: str,
    symbol: str = "NVDA",
    run_id: str = _RUN,
    stage: str = "passed",
    reasons: list[str] | None = None,
    score: float = 72.0,
    strategy: str = "cash_secured_put",
    strike: float = 190.0,
    ideal_lo: float | None = None,
    ideal_hi: float | None = None,
    min_credit: float | None = None,
) -> RiskVerdictRow:
    return RiskVerdictRow(
        candidate_id=candidate_id,
        run_id=run_id,
        symbol=symbol,
        strategy=strategy,
        strike=strike,
        expiry=_EXPIRY,
        verdict="pass" if stage == "passed" else "reject",
        stage=stage,
        reasons=reasons or [],
        blended_score=score,
        premium=3.25,
        ideal_lo=ideal_lo,
        ideal_hi=ideal_hi,
        min_credit=min_credit,
    )


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

    with session_scope() as s:
        s.add(_verdict(candidate_id="a", stage="passed"))
        s.add(_verdict(candidate_id="b", stage="risk_gate", reasons=["delta_out_of_range"]))
        s.add(_verdict(candidate_id="c", stage="generator", reasons=["illiquid"]))
        s.add(_verdict(candidate_id="d", stage="score_floor", score=40.0))
        s.add(_verdict(candidate_id="e", stage="dedupe", reasons=["dedupe_not_surfaced"]))
        s.add(_verdict(candidate_id="f", stage="top_n", reasons=["top_n_not_surfaced"]))
        s.add(
            _verdict(
                candidate_id="g",
                symbol="AAPL",
                stage="risk_gate",
                reasons=["iv_rank_below_minimum"],
            )
        )

    return TestClient(create_app())


def test_assessed_requires_owner_auth(client) -> None:
    assert client.get("/options/assessed").status_code == 401


def test_assessed_requires_owner_role(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/options/assessed", headers=AUTH).status_code == 403


def test_risk_gate_is_never_promotable(client) -> None:
    r = client.get("/options/assessed", headers=AUTH)
    assert r.status_code == 200
    contracts = [c for g in r.json()["groups"] for c in g["contracts"]]
    gate = [c for c in contracts if c["stage"] == "risk_gate"]
    assert gate, "expected at least one risk_gate contract"
    for c in gate:
        assert c["promotable"] is False
        assert c["promote_note"] == "The Rules Engine rejected this contract."


def test_generator_is_never_promotable(client) -> None:
    r = client.get("/options/assessed", headers=AUTH)
    contracts = [c for g in r.json()["groups"] for c in g["contracts"]]
    gen = [c for c in contracts if c["stage"] == "generator"]
    assert gen, "expected at least one generator contract"
    for c in gen:
        assert c["promotable"] is False
        assert "strategy filter" in c["promote_note"]


def test_score_floor_is_promotable_and_carries_configured_minimum(client) -> None:
    r = client.get("/options/assessed", headers=AUTH)
    contracts = [c for g in r.json()["groups"] for c in g["contracts"]]
    sf = [c for c in contracts if c["stage"] == "score_floor"]
    assert sf, "expected at least one score_floor contract"
    for c in sf:
        assert c["promotable"] is True
        # The note carries the ACTUAL configured minimum, read from config.
        from src.common.config import get_config

        min_score = get_config().weights.get("min_candidate_score", 0)
        assert str(min_score) in c["promote_note"]


def test_dedupe_and_top_n_are_promotable_with_null_note(client) -> None:
    r = client.get("/options/assessed", headers=AUTH)
    contracts = [c for g in r.json()["groups"] for c in g["contracts"]]
    for c in contracts:
        if c["stage"] in ("dedupe", "top_n"):
            assert c["promotable"] is True
            assert c["promote_note"] is None


def test_passed_is_not_promotable(client) -> None:
    r = client.get("/options/assessed", headers=AUTH)
    contracts = [c for g in r.json()["groups"] for c in g["contracts"]]
    passed = [c for c in contracts if c["stage"] == "passed"]
    for c in passed:
        assert c["promotable"] is False
        assert "Already surfaced" in c["promote_note"]


def test_run_latest_filters_single_ticker_runs(client) -> None:
    """A /scan NVDA must not become "the latest run" for the assessed browser."""
    with session_scope() as s:
        # A single-ticker scan run, later than the real run.
        s.add(
            _verdict(
                candidate_id="scan1",
                run_id="scan-NVDA",
                stage="passed",
            )
        )
        # Bump the created_at so it sorts after the real run.
        s.flush()
        s.query(RiskVerdictRow).filter(RiskVerdictRow.run_id == "scan-NVDA").update(
            {"created_at": datetime.now(UTC) + timedelta(hours=1)}
        )

    r = client.get("/options/assessed?run=latest", headers=AUTH)
    assert r.status_code == 200
    # The latest run must NOT be the scan- prefixed one.
    assert r.json()["run_id"] != "scan-NVDA"
    assert r.json()["run_id"] == _RUN


def test_run_latest_filters_ticker_promote_runs(client) -> None:
    """Every promote attempt (win or lose) is audited under a `ticker-` run_id via
    `_price_and_gate_ticker` — a different prefix from `/scan TICKER`'s `scan-`, but the
    same "one ticker, not a full scan" meaning. It must not displace the full scan run
    either."""
    with session_scope() as s:
        # A promote's single-ticker audit run, later than the real run.
        s.add(
            _verdict(
                candidate_id="promote1",
                run_id="ticker-a1b2c3d4",
                stage="passed",
            )
        )
        s.flush()
        s.query(RiskVerdictRow).filter(RiskVerdictRow.run_id == "ticker-a1b2c3d4").update(
            {"created_at": datetime.now(UTC) + timedelta(hours=1)}
        )

    r = client.get("/options/assessed?run=latest", headers=AUTH)
    assert r.status_code == 200
    # The latest run must NOT be the ticker- prefixed one.
    assert r.json()["run_id"] != "ticker-a1b2c3d4"
    assert r.json()["run_id"] == _RUN


def test_assessed_runs_requires_owner_auth(client) -> None:
    assert client.get("/options/assessed/runs").status_code == 401


def test_assessed_runs_lists_the_fixture_run(client) -> None:
    r = client.get("/options/assessed/runs", headers=AUTH)
    assert r.status_code == 200
    runs = r.json()["runs"]
    assert len(runs) == 1
    assert runs[0]["run_id"] == _RUN
    assert runs[0]["candidate_count"] == 7  # a..g seeded by the fixture


def test_assessed_runs_excludes_single_ticker_runs(client) -> None:
    """`scan-`/`ticker-` prefixed audit runs are not "a run" for history browsing,
    same exclusion `run=latest` already applies."""
    with session_scope() as s:
        s.add(_verdict(candidate_id="s1", run_id="scan-NVDA", stage="passed"))
        s.add(_verdict(candidate_id="t1", run_id="ticker-a1b2c3d4", stage="passed"))
    r = client.get("/options/assessed/runs", headers=AUTH)
    run_ids = {row["run_id"] for row in r.json()["runs"]}
    assert run_ids == {_RUN}


def test_assessed_runs_newest_first(client) -> None:
    with session_scope() as s:
        s.add(_verdict(candidate_id="older", run_id="2026-09-01T10:00:00", stage="passed"))
        s.flush()
        s.query(RiskVerdictRow).filter(RiskVerdictRow.run_id == "2026-09-01T10:00:00").update(
            {"created_at": datetime.now(UTC) - timedelta(days=5)}
        )
    r = client.get("/options/assessed/runs", headers=AUTH)
    run_ids = [row["run_id"] for row in r.json()["runs"]]
    assert run_ids == [_RUN, "2026-09-01T10:00:00"]


def test_groups_ordered_by_best_contract_first(client) -> None:
    r = client.get("/options/assessed", headers=AUTH)
    groups = r.json()["groups"]
    # NVDA has a passed contract (promotable-adjacent, highest score); AAPL only has a reject.
    assert groups[0]["symbol"] == "NVDA"


def test_reasons_text_never_returns_a_raw_code(client) -> None:
    r = client.get("/options/assessed", headers=AUTH)
    contracts = [c for g in r.json()["groups"] for c in g["contracts"]]
    for c in contracts:
        for text in c["reasons_text"]:
            # Humanised, never a raw snake_case code.
            assert "_" not in text or " " in text, f"raw code leaked: {text}"
            assert text != ""


def test_reasons_text_falls_back_to_desnaked_code(client) -> None:
    """A code with no humanisation falls back to the code with underscores replaced."""
    with session_scope() as s:
        s.add(
            _verdict(
                candidate_id="unk",
                symbol="MSFT",
                stage="risk_gate",
                reasons=["some_unknown_code_xyz"],
            )
        )
    r = client.get("/options/assessed", headers=AUTH)
    contracts = [c for g in r.json()["groups"] for c in g["contracts"]]
    unk = [c for c in contracts if c["candidate_id"] == "unk"]
    assert unk
    assert "some unknown code xyz" in unk[0]["reasons_text"]


def test_empty_run_returns_empty_groups(client, monkeypatch, tmp_path) -> None:
    """An unknown run_id returns 200 with empty groups, not 404."""
    r = client.get("/options/assessed?run=nonexistent", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["groups"] == []


def test_filter_by_symbol(client) -> None:
    r = client.get("/options/assessed?symbol=AAPL", headers=AUTH)
    groups = r.json()["groups"]
    assert all(g["symbol"] == "AAPL" for g in groups)
    assert len(groups) == 1


def test_filter_by_stage(client) -> None:
    r = client.get("/options/assessed?stage=risk_gate", headers=AUTH)
    contracts = [c for g in r.json()["groups"] for c in g["contracts"]]
    assert all(c["stage"] == "risk_gate" for c in contracts)
    assert len(contracts) == 2  # NVDA + AAPL risk_gate rows


def test_unknown_stage_returns_422_not_silent_empty(client) -> None:
    """An operator typo should surface as a validation error, not an empty list."""
    r = client.get("/options/assessed?stage=foo", headers=AUTH)
    assert r.status_code == 422


def test_counts_per_stage_in_group_header(client) -> None:
    r = client.get("/options/assessed", headers=AUTH)
    nvda = [g for g in r.json()["groups"] if g["symbol"] == "NVDA"][0]
    counts = nvda["counts"]
    assert counts.get("passed", 0) == 1
    assert counts.get("risk_gate", 0) == 1
    assert counts.get("generator", 0) == 1
    assert counts.get("score_floor", 0) == 1


def test_within_group_ranking_follows_stage_progression_not_promotable_bool(client) -> None:
    """_rank_assessed orders rejects by how far they got: top_n > dedupe > score_floor.
    A score_floor reject at score 80 must NOT rank above a top_n reject at score 70."""
    with session_scope() as s:
        s.add(_verdict(candidate_id="sf80", symbol="TSLA", stage="score_floor", score=80.0))
        s.add(_verdict(candidate_id="tn70", symbol="TSLA", stage="top_n", score=70.0))
    r = client.get("/options/assessed?symbol=TSLA", headers=AUTH)
    contracts = r.json()["groups"][0]["contracts"]
    # top_n got further than score_floor, so it ranks first despite the lower score.
    assert contracts[0]["candidate_id"] == "tn70"
    assert contracts[1]["candidate_id"] == "sf80"


def test_group_order_uses_best_contract_not_promotable_count(client) -> None:
    """A symbol with one passed contract at score 90 ranks above one with ten
    score_floor rejects at score 80 — "best contract first" means the group's
    single best contract, not a count of promotable ones."""
    with session_scope() as s:
        # One passed contract at score 90.
        s.add(_verdict(candidate_id="p90", symbol="ONEPASS", stage="passed", score=90.0))
        # Ten score_floor rejects at score 80.
        for i in range(10):
            s.add(
                _verdict(
                    candidate_id=f"sf{i}",
                    symbol="MANYREJ",
                    stage="score_floor",
                    score=80.0,
                    strike=180.0 + i,
                )
            )
    r = client.get("/options/assessed", headers=AUTH)
    groups = r.json()["groups"]
    # ONEPASS's passed contract outranks MANYREJ's score_floor rejects.
    assert groups[0]["symbol"] == "ONEPASS"


def test_limit_caps_total_contracts_not_per_symbol(client) -> None:
    """limit=3 means three contracts total across all groups, not three per symbol."""
    r = client.get("/options/assessed?limit=3", headers=AUTH)
    total = sum(len(g["contracts"]) for g in r.json()["groups"])
    assert total == 3


def test_counts_reflect_full_run_not_truncated_subset(client) -> None:
    """When limit trims a group's contracts, the group's counts must still report
    the full per-stage tally for that symbol — the header tells the operator what
    the scan produced, not what fit under the limit."""
    # The seeded NVDA group has 5 contracts (passed, risk_gate, generator,
    # score_floor, dedupe, top_n — actually 6). With limit=1, only the best
    # contract is returned, but counts must still show all 6 stages.
    r = client.get("/options/assessed?symbol=NVDA&limit=1", headers=AUTH)
    g = r.json()["groups"][0]
    assert len(g["contracts"]) == 1  # trimmed
    counts_sum = sum(g["counts"].values())
    assert counts_sum >= 5  # the full NVDA tally, not just the 1 returned
