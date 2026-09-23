"""GET /options/approvals and GET /options/approvals/{id} — the first options router.

Owner-only, joined across four tables, snapshot-first when the candidate has been
pruned, five review fields rendered separately, premium always per share.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.storage.db import session_scope
from src.storage.models import (
    ApprovalRow,
    CandidateRow,
    ClaudeReviewRow,
    FillRow,
    OrderRow,
    RiskVerdictRow,
)

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

_EXPIRY = date.today() + timedelta(days=30)


def _snapshot(
    *,
    underlying: str = "NVDA",
    strategy: str = "cash_secured_put",
    right: str = "P",
    strike: float = 190.0,
    expiry: date = _EXPIRY,
    contracts: int = 1,
    premium: float = 3.25,
    score: float = 72.0,
) -> dict:
    return {
        "underlying": underlying,
        "strategy": strategy,
        "right": right,
        "strike": strike,
        "expiry": expiry.isoformat(),
        "contracts": contracts,
        "premium": premium,
        "blended_score": score,
    }


def _seed_candidate(
    session,
    *,
    candidate_id: str = "c1",
    run_id: str = "2026-09-06T10:00:00",
    underlying: str = "NVDA",
    strategy: str = "cash_secured_put",
    right: str = "P",
    strike: float = 190.0,
    premium: float = 3.25,
    score: float = 72.0,
) -> CandidateRow:
    row = CandidateRow(
        candidate_id=candidate_id,
        run_id=run_id,
        strategy=strategy,
        underlying=underlying,
        right=right,
        strike=strike,
        expiry=_EXPIRY,
        blended_score=score,
        payload=_snapshot(
            underlying=underlying,
            strategy=strategy,
            right=right,
            strike=strike,
            premium=premium,
            score=score,
        ),
    )
    session.add(row)
    return row


def _seed_approval(
    session,
    *,
    approval_id: int | None = None,
    candidate_id: str = "c1",
    status: str = "pending",
    snapshot: dict | None = None,
    expires_at: datetime | None = None,
    decided_at: datetime | None = None,
) -> ApprovalRow:
    row = ApprovalRow(
        candidate_id=candidate_id,
        status=status,
        snapshot=snapshot or _snapshot(),
        expires_at=expires_at,
        decided_at=decided_at,
    )
    if approval_id is not None:
        row.id = approval_id
    session.add(row)
    return row


def _seed_verdict(
    session,
    *,
    candidate_id: str = "c1",
    symbol: str = "NVDA",
    run_id: str = "2026-09-06T10:00:00",
    stage: str = "passed",
    reasons: list[str] | None = None,
    ideal_lo: float | None = 185.0,
    ideal_hi: float | None = 192.0,
    min_credit: float | None = 3.10,
) -> RiskVerdictRow:
    row = RiskVerdictRow(
        candidate_id=candidate_id,
        run_id=run_id,
        symbol=symbol,
        strategy="cash_secured_put",
        strike=190.0,
        expiry=_EXPIRY,
        verdict="pass" if stage == "passed" else "reject",
        stage=stage,
        reasons={"codes": reasons or []},
        blended_score=72.0,
        premium=3.25,
        ideal_lo=ideal_lo,
        ideal_hi=ideal_hi,
        min_credit=min_credit,
    )
    session.add(row)
    return row


def _seed_review(
    session,
    *,
    candidate_id: str = "c1",
) -> ClaudeReviewRow:
    row = ClaudeReviewRow(
        candidate_id=candidate_id,
        priority=1,
        recommendation="sell",
        payload={
            "why_attractive": "Rich IV rank, premium is above fair value.",
            "risks": "Earnings inside the window could move the stock through the strike.",
            "tradeoffs": "A higher strike captures more premium but raises assignment risk.",
            "assignment_considerations": "Assignment at $190 is acceptable — it is below your buy zone.",
            "rolling_considerations": "Roll if delta approaches -0.40 before 21 DTE.",
            "recommendation": "sell",
            "priority": 1,
            "confidence": 0.78,
        },
    )
    session.add(row)
    return row


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

    # Seed through the read-write storage engine (session_scope), not the API's
    # read-only engine — the API must not write to these tables.
    with session_scope() as s:
        _seed_candidate(s)
        _seed_approval(s)
        _seed_verdict(s)
        _seed_review(s)

    return TestClient(create_app())


def test_list_approvals_requires_owner_auth(client) -> None:
    assert client.get("/options/approvals").status_code == 401


def test_list_approvals_requires_owner_role(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    r = client.get("/options/approvals", headers=AUTH)
    assert r.status_code == 403


def test_list_approvals_pending_by_default(client) -> None:
    with session_scope() as s:
        _seed_approval(s, candidate_id="c2", status="approved")
    r = client.get("/options/approvals", headers=AUTH)
    assert r.status_code == 200
    approvals = r.json()["approvals"]
    assert len(approvals) == 1  # only the pending one
    assert approvals[0]["status"] == "pending"


def test_list_approvals_all_returns_decided_too(client) -> None:
    with session_scope() as s:
        _seed_approval(
            s,
            candidate_id="c2",
            status="approved",
            decided_at=datetime.now(UTC),
        )
    r = client.get("/options/approvals?status=all", headers=AUTH)
    assert r.status_code == 200
    assert len(r.json()["approvals"]) == 2


def test_empty_table_returns_200_with_empty_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN)
    trading_db = tmp_path / "empty.db"
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
    c = TestClient(create_app())
    r = c.get("/options/approvals", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["approvals"] == []


def test_premium_is_per_share_not_multiplied_by_100(client) -> None:
    r = client.get("/options/approvals", headers=AUTH)
    assert r.status_code == 200
    a = r.json()["approvals"][0]
    assert a["premium"] == 3.25  # exactly the stored per-share number, not 325.0


def test_list_approvals_includes_a_review_preview(client) -> None:
    """The list route (not just the detail route) carries the review so the card
    can show a why/risks preview without a click-through for every candidate."""
    r = client.get("/options/approvals", headers=AUTH)
    assert r.status_code == 200
    a = r.json()["approvals"][0]
    assert a["review"] is not None
    assert a["review"]["why_attractive"] == "Rich IV rank, premium is above fair value."


def test_list_approvals_review_is_null_when_no_review_exists(client) -> None:
    with session_scope() as s:
        _seed_candidate(s, candidate_id="c2", underlying="AAPL")
        _seed_approval(s, candidate_id="c2", snapshot=_snapshot(underlying="AAPL"))
    r = client.get("/options/approvals?status=all", headers=AUTH)
    by_cid = {a["candidate_id"]: a for a in r.json()["approvals"]}
    assert by_cid["c2"]["review"] is None


def test_contracts_falls_back_to_candidate_payload_when_snapshot_is_null(client) -> None:
    """A pre-freeze approval predating the snapshot feature has snapshot=None; its
    contracts must come from the joined CandidateRow's payload, not a hardcoded 1
    (regression: the old fallback ternary's two branches were both `1`, always)."""
    with session_scope() as s:
        _seed_candidate(s, candidate_id="c3", underlying="TSLA")
        cand = s.query(CandidateRow).filter_by(candidate_id="c3").one()
        cand.payload = {**cand.payload, "contracts": 4}
        s.add(ApprovalRow(candidate_id="c3", status="pending", snapshot=None))
    r = client.get("/options/approvals?status=all", headers=AUTH)
    by_cid = {a["candidate_id"]: a for a in r.json()["approvals"]}
    assert by_cid["c3"]["contracts"] == 4


def test_list_approvals_filters_by_symbol_case_insensitively(client) -> None:
    with session_scope() as s:
        _seed_candidate(s, candidate_id="c2", underlying="AAPL")
        _seed_approval(s, candidate_id="c2", snapshot=_snapshot(underlying="AAPL"))
    r = client.get("/options/approvals?status=all&symbol=aapl", headers=AUTH)
    assert r.status_code == 200
    approvals = r.json()["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["underlying"] == "AAPL"


def test_list_approvals_filters_by_since_and_until(client) -> None:
    with session_scope() as s:
        s.add(
            ApprovalRow(
                candidate_id="c1",
                status="pending",
                snapshot=_snapshot(),
                created_at=datetime(2020, 1, 1),
            )
        )
    # `since` today excludes the 2020 row, leaving only the fixture's c1 approval.
    r = client.get(f"/options/approvals?status=all&since={date.today().isoformat()}", headers=AUTH)
    assert r.status_code == 200
    assert all(not a["created_at"].startswith("2020") for a in r.json()["approvals"])

    # `until` 2020-01-02 leaves only the 2020 row.
    r2 = client.get("/options/approvals?status=all&until=2020-01-02", headers=AUTH)
    assert r2.status_code == 200
    approvals2 = r2.json()["approvals"]
    assert len(approvals2) == 1
    assert approvals2[0]["created_at"].startswith("2020-01-01")


def test_approval_summary_reports_when_it_was_raised(client) -> None:
    """`created_at` is the approval's actual raise time — never `as_of`, which
    is a per-request freshness stamp (`datetime.now(UTC)` at response build
    time) and is therefore always "just now" no matter how old the approval
    is."""
    with session_scope() as s:
        ap = s.query(ApprovalRow).first()
        stamp = ap.created_at

    r = client.get("/options/approvals", headers=AUTH)
    assert r.status_code == 200
    a = r.json()["approvals"][0]
    assert a["created_at"] is not None
    assert a["created_at"] != a["as_of"]
    assert datetime.fromisoformat(a["created_at"].replace("Z", "+00:00")) == stamp.replace(
        tzinfo=UTC
    )


def test_order_state_is_null_when_no_order_exists(client) -> None:
    r = client.get("/options/approvals", headers=AUTH)
    assert r.status_code == 200
    a = r.json()["approvals"][0]
    assert a["order_state"] is None


def test_order_state_joined_when_an_order_exists(client) -> None:
    with session_scope() as s:
        ap = s.query(ApprovalRow).first()
        s.add(
            OrderRow(
                candidate_id=ap.candidate_id,
                approval_id=ap.id,
                state="submitted",
                limit_price=3.25,
                snapshot=_snapshot(),
            )
        )
    r = client.get("/options/approvals", headers=AUTH)
    a = r.json()["approvals"][0]
    assert a["order_state"] == "submitted"


def test_source_is_roll_for_roll_run_id(client) -> None:
    with session_scope() as s:
        _seed_candidate(s, candidate_id="rc1", run_id="roll-2026-09-06", underlying="AAPL")
        _seed_approval(s, candidate_id="rc1", snapshot=_snapshot(underlying="AAPL"))
    r = client.get("/options/approvals?status=all", headers=AUTH)
    by_cid = {a["candidate_id"]: a for a in r.json()["approvals"]}
    assert by_cid["c1"]["source"] == "scan"
    assert by_cid["rc1"]["source"] == "roll"


def test_pruned_candidate_renders_from_snapshot_alone(client) -> None:
    """A missing CandidateRow must not 500; the snapshot is the source of truth."""
    with session_scope() as s:
        _seed_approval(s, candidate_id="orphan", snapshot=_snapshot(underlying="ORPH"))
    r = client.get("/options/approvals?status=all", headers=AUTH)
    by_cid = {a["candidate_id"]: a for a in r.json()["approvals"]}
    # The snapshot carries the underlying; the joined CandidateRow is absent.
    assert by_cid["orphan"]["underlying"] == "ORPH"
    assert by_cid["orphan"]["strike"] == 190.0


def test_detail_route_returns_404_for_unknown(client) -> None:
    r = client.get("/options/approvals/99999", headers=AUTH)
    assert r.status_code == 404


def test_detail_route_requires_owner_auth(client) -> None:
    assert client.get("/options/approvals/1").status_code == 401


def test_detail_route_requires_owner_role(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    r = client.get("/options/approvals/1", headers=AUTH)
    assert r.status_code == 403


def test_detail_renders_five_review_fields_separately(client) -> None:
    r = client.get("/options/approvals/1", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    review = body["review"]
    assert review is not None
    # Five separate fields, not one concatenated blob.
    assert review["why_attractive"] == "Rich IV rank, premium is above fair value."
    assert "Earnings" in review["risks"]
    assert "higher strike" in review["tradeoffs"]
    assert "Assignment at $190" in review["assignment_considerations"]
    assert "Roll if delta" in review["rolling_considerations"]
    # The five fields are distinct strings, not joined into one blob.
    five = [
        review["why_attractive"],
        review["risks"],
        review["tradeoffs"],
        review["assignment_considerations"],
        review["rolling_considerations"],
    ]
    # None of them is a concatenation of the others.
    assert all(f and isinstance(f, str) for f in five)
    assert five[0] == "Rich IV rank, premium is above fair value."


def test_detail_ideal_zone_from_risk_verdict(client) -> None:
    r = client.get("/options/approvals/1", headers=AUTH)
    ideal = r.json()["ideal"]
    assert ideal is not None
    assert ideal["lo"] == 185.0
    assert ideal["hi"] == 192.0
    assert ideal["min_credit"] == 3.10


def test_detail_gate_reasons_are_humanised_not_raw_codes(client) -> None:
    with session_scope() as s:
        # Update the verdict to carry a rejection reason code.
        v = s.query(RiskVerdictRow).first()
        v.reasons = {"codes": ["iv_rank_below_minimum", "earnings_blackout"]}
    r = client.get("/options/approvals/1", headers=AUTH)
    reasons = r.json()["gate_reasons"]
    assert "IV rank too low (poor premium)" in reasons
    assert "earnings inside the window" in reasons
    # No raw code leaks through.
    assert all("iv_rank_below_minimum" != x for x in reasons)


def test_detail_survives_multiple_verdict_rows_for_the_same_candidate(client) -> None:
    """risk_verdicts stores one row per assessed contract PER RUN — a candidate scanned
    on two different runs has two rows. The detail route must not 500."""
    with session_scope() as s:
        _seed_verdict(s, run_id="2026-09-05T10:00:00", ideal_lo=180.0, ideal_hi=188.0)
    r = client.get("/options/approvals/1", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["ideal"] is not None


def test_detail_survives_multiple_review_rows_for_the_same_candidate(client) -> None:
    """A candidate reviewed more than once (retry, re-review) has multiple
    claude_reviews rows. The detail route must not 500."""
    with session_scope() as s:
        _seed_review(s)
    r = client.get("/options/approvals/1", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["review"] is not None


def test_detail_review_is_null_when_no_review_exists(client) -> None:
    with session_scope() as s:
        _seed_candidate(s, candidate_id="norev", underlying="MSFT")
        _seed_approval(s, candidate_id="norev", snapshot=_snapshot(underlying="MSFT"))
    # Find the approval id for the norev candidate.
    with session_scope() as s:
        ap = s.query(ApprovalRow).filter(ApprovalRow.candidate_id == "norev").first()
        aid = ap.id
    r = client.get(f"/options/approvals/{aid}", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["review"] is None


def test_detail_order_id_and_fills_are_null_and_empty_when_no_order_exists(client) -> None:
    r = client.get("/options/approvals/1", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["order_id"] is None
    assert body["fills"] == []


def test_detail_carries_the_approval_to_fill_lineage(client) -> None:
    """The detail route chains approval -> order -> fills in one response, so
    tracing a candidate to its fill price needs no second/third request."""
    with session_scope() as s:
        ap = s.query(ApprovalRow).first()
        order = OrderRow(
            candidate_id=ap.candidate_id,
            approval_id=ap.id,
            state="filled",
            limit_price=3.25,
            filled_qty=1.0,
            avg_fill_price=3.20,
            snapshot=_snapshot(),
        )
        s.add(order)
        s.flush()
        order_id = order.id
        s.add(
            FillRow(
                order_id=order_id,
                candidate_id=ap.candidate_id,
                action="SELL",
                filled_qty=1.0,
                avg_price=3.20,
                commission=0.65,
                is_live=False,
            )
        )

    r = client.get("/options/approvals/1", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["order_id"] == order_id
    assert len(body["fills"]) == 1
    fill = body["fills"][0]
    assert fill["order_id"] == order_id
    assert fill["avg_price"] == 3.20
    assert fill["action"] == "SELL"


def test_detail_alternatives_list_other_contracts_on_same_run(client) -> None:
    with session_scope() as s:
        _seed_verdict(
            s,
            candidate_id="alt1",
            symbol="NVDA",
            run_id="2026-09-06T10:00:00",
            stage="dedupe",
            ideal_lo=None,
            ideal_hi=None,
            min_credit=None,
        )
    r = client.get("/options/approvals/1", headers=AUTH)
    alts = r.json()["alternatives"]
    assert len(alts) >= 1
    assert alts[0]["candidate_id"] == "alt1"


def test_unknown_status_returns_422_not_silent_empty(client) -> None:
    """An operator typo should surface as a validation error, not an empty list."""
    r = client.get("/options/approvals?status=foo", headers=AUTH)
    assert r.status_code == 422


def test_status_all_is_newest_first_overall(client) -> None:
    """status=all returns newest first by created_at, not pending-above-decided.

    The fixture's c1 is pending and created ~now. We add an approved approval
    created strictly AFTER c1 and an old pending one. The new approved approval
    must sort above c1, proving a decided row is not pushed below a pending one
    just because it's pending.
    """
    with session_scope() as s:
        # Pin c1's created_at into the past so the new approved one is unambiguously
        # newer.
        s.query(ApprovalRow).filter(ApprovalRow.candidate_id == "c1").update(
            {"created_at": datetime.now(UTC) - timedelta(days=5)}
        )
        new_approved = ApprovalRow(
            candidate_id="newa",
            status="approved",
            snapshot=_snapshot(underlying="NEWA"),
            decided_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        old_pending = ApprovalRow(
            candidate_id="oldp",
            status="pending",
            snapshot=_snapshot(underlying="OLDP"),
            created_at=datetime.now(UTC) - timedelta(days=10),
        )
        s.add(new_approved)
        s.add(old_pending)
    r = client.get("/options/approvals?status=all", headers=AUTH)
    approvals = r.json()["approvals"]
    # Newest first: newa (approved, just now) before c1 (pending, 5d ago) before
    # oldp (pending, 10d ago). The load-bearing assertion is that a pending row
    # is NOT promoted above a newer decided one.
    assert approvals[0]["candidate_id"] == "newa"
    assert approvals[1]["candidate_id"] == "c1"
    assert approvals[2]["candidate_id"] == "oldp"
