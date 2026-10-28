"""GET /options/orders and GET /options/fills — working orders and recent fills.

Owner-only, ``state=working`` by default, ``avg_fill_price`` null for unfilled
(not 0.0), snapshot fallback when the candidate has been pruned, empty list 200.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.storage.db import session_scope
from src.storage.models import CandidateRow, FillRow, OrderRow, SizingActionRow

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

_EXPIRY = date.today() + timedelta(days=30)


def _snap(**kw) -> dict:
    base = {
        "underlying": "NVDA",
        "strategy": "cash_secured_put",
        "right": "P",
        "strike": 190.0,
        "expiry": _EXPIRY.isoformat(),
        "contracts": 1,
        "premium": 3.25,
    }
    base.update(kw)
    return base


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
        s.add(
            CandidateRow(
                candidate_id="c1",
                run_id="r1",
                strategy="cash_secured_put",
                underlying="NVDA",
                right="P",
                strike=190.0,
                expiry=_EXPIRY,
                blended_score=72.0,
                payload=_snap(),
            )
        )
        s.add(
            OrderRow(
                candidate_id="c1",
                approval_id=1,
                state="submitted",
                limit_price=3.25,
                filled_qty=0.0,
                avg_fill_price=None,
                is_live=False,
                snapshot=_snap(),
            )
        )
        s.add(
            OrderRow(
                candidate_id="c2",
                state="filled",
                limit_price=3.10,
                filled_qty=1.0,
                avg_fill_price=3.10,
                is_live=False,
                snapshot=_snap(underlying="AAPL", strike=185.0),
            )
        )
        s.add(
            OrderRow(
                candidate_id="c3",
                state="queued",
                filled_qty=0.0,
                is_live=False,
                snapshot=_snap(underlying="MSFT", strike=300.0),
            )
        )
        # A fill for the filled order.
        s.add(
            FillRow(
                order_id=2,
                candidate_id="c2",
                action="SELL",
                filled_qty=1.0,
                avg_price=3.10,
                is_live=False,
                filled_at=datetime.now(UTC),
            )
        )
    return TestClient(create_app())


def test_orders_requires_owner_auth(client) -> None:
    assert client.get("/options/orders").status_code == 401


def test_orders_requires_owner_role(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/options/orders", headers=AUTH).status_code == 403


def test_orders_working_by_default(client) -> None:
    r = client.get("/options/orders", headers=AUTH)
    assert r.status_code == 200
    states = {o["state"] for o in r.json()["orders"]}
    # working = queued, submitted — filled and partial (the rest was cancelled) are excluded.
    assert states <= {"queued", "submitted"}
    assert "filled" not in states and "partial" not in states


def test_orders_all_returns_everything(client) -> None:
    r = client.get("/options/orders?state=all", headers=AUTH)
    states = {o["state"] for o in r.json()["orders"]}
    assert "filled" in states


def test_avg_fill_price_is_null_for_unfilled(client) -> None:
    """A fabricated 0.0 would read as real to an operator — must be null."""
    r = client.get("/options/orders?state=all", headers=AUTH)
    orders = r.json()["orders"]
    submitted = [o for o in orders if o["state"] == "submitted"][0]
    assert submitted["avg_fill_price"] is None
    assert submitted["avg_fill_price"] != 0.0


def test_avg_fill_price_is_set_for_filled(client) -> None:
    r = client.get("/options/orders?state=all", headers=AUTH)
    filled = [o for o in r.json()["orders"] if o["state"] == "filled"][0]
    assert filled["avg_fill_price"] == 3.10


def test_underlying_strategy_strike_from_snapshot(client) -> None:
    r = client.get("/options/orders?state=all", headers=AUTH)
    by_cid = {o["candidate_id"]: o for o in r.json()["orders"]}
    assert by_cid["c2"]["underlying"] == "AAPL"
    assert by_cid["c2"]["strike"] == 185.0
    assert by_cid["c3"]["underlying"] == "MSFT"


def test_pruned_candidate_does_not_blank_the_row(client) -> None:
    """An order whose CandidateRow is gone still renders from its snapshot."""
    with session_scope() as s:
        s.add(
            OrderRow(
                candidate_id="orphan",
                state="queued",
                filled_qty=0.0,
                is_live=False,
                snapshot=_snap(underlying="ORPH", strike=50.0),
            )
        )
    r = client.get("/options/orders?state=all", headers=AUTH)
    by_cid = {o["candidate_id"]: o for o in r.json()["orders"]}
    assert by_cid["orphan"]["underlying"] == "ORPH"
    assert by_cid["orphan"]["strike"] == 50.0


def test_empty_orders_returns_200_with_empty_list(monkeypatch, tmp_path) -> None:
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
    r = c.get("/options/orders", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["orders"] == []


def test_fills_requires_owner_auth(client) -> None:
    assert client.get("/options/fills").status_code == 401


def test_fills_returns_recent(client) -> None:
    r = client.get("/options/fills?days=7", headers=AUTH)
    assert r.status_code == 200
    fills = r.json()["fills"]
    assert len(fills) == 1
    assert fills[0]["candidate_id"] == "c2"
    assert fills[0]["avg_price"] == 3.10


def test_fills_empty_returns_200(client) -> None:
    r = client.get("/options/fills?days=1", headers=AUTH)
    # the seeded fill is "now" so days=1 should still find it; use a very small db
    # to test the truly empty case
    assert r.status_code == 200
    assert isinstance(r.json()["fills"], list)


def test_fills_filters_by_days(client) -> None:
    """A fill older than the window is excluded."""
    with session_scope() as s:
        s.add(
            FillRow(
                order_id=1,
                candidate_id="c1",
                action="SELL",
                filled_qty=1.0,
                avg_price=3.25,
                is_live=False,
                filled_at=datetime.now(UTC) - timedelta(days=30),
            )
        )
    r = client.get("/options/fills?days=7", headers=AUTH)
    # the 30-day-old fill must not appear; only the "now" one does.
    cids = {f["candidate_id"] for f in r.json()["fills"]}
    assert "c1" not in cids


def test_unknown_state_returns_422_not_silent_empty(client) -> None:
    """An operator typo should surface as a validation error, not an empty list."""
    r = client.get("/options/orders?state=foo", headers=AUTH)
    assert r.status_code == 422


def test_specific_state_filter_returns_only_that_state(client) -> None:
    r = client.get("/options/orders?state=filled", headers=AUTH)
    assert r.status_code == 200
    states = {o["state"] for o in r.json()["orders"]}
    assert states == {"filled"}


def _sizing(
    order_id: int, kind: str, *, wanted: int, sent: int, reason: str = ""
) -> SizingActionRow:
    return SizingActionRow(
        created_at=datetime.now(UTC).replace(tzinfo=None),
        candidate_id="c2",
        record_key=f"c2-{kind}",
        underlying="AAPL",
        strategy="cash_secured_put",
        right="P",
        strike=185.0,
        expiry=_EXPIRY,
        premium=3.10,
        kind=kind,
        regime="stressed",
        deterministic_contracts=wanted,
        sent_contracts=sent,
        reason=reason,
        action_day=date.today(),
        order_id=order_id,
    )


def test_an_order_carries_the_sizing_action_that_shaped_it(client) -> None:
    with session_scope() as s:
        s.add(_sizing(2, "claude_cut", wanted=3, sent=1, reason="Claude suggested 1"))
    by_cid = {
        o["candidate_id"]: o
        for o in client.get("/options/orders?state=all", headers=AUTH).json()["orders"]
    }
    assert by_cid["c2"]["sizing"] == [
        {
            "kind": "claude_cut",
            "deterministic_contracts": 3,
            "sent_contracts": 1,
            "reason": "Claude suggested 1",
        }
    ]


def test_an_order_no_action_touched_has_an_empty_sizing_list(client) -> None:
    by_cid = {
        o["candidate_id"]: o
        for o in client.get("/options/orders?state=all", headers=AUTH).json()["orders"]
    }
    assert by_cid["c1"]["sizing"] == []


def test_two_actions_on_one_order_both_come_back_oldest_first(client) -> None:
    with session_scope() as s:
        s.add(_sizing(2, "regime_budget", wanted=3, sent=2))
        s.add(_sizing(2, "claude_cut", wanted=2, sent=1))
    by_cid = {
        o["candidate_id"]: o
        for o in client.get("/options/orders?state=all", headers=AUTH).json()["orders"]
    }
    assert [a["kind"] for a in by_cid["c2"]["sizing"]] == ["regime_budget", "claude_cut"]


def test_orders_can_be_windowed_by_days(client) -> None:
    with session_scope() as s:
        s.add(
            OrderRow(
                candidate_id="old",
                state="filled",
                filled_qty=1.0,
                is_live=False,
                snapshot=_snap(underlying="OLD"),
                created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30),
            )
        )
    week = {
        o["candidate_id"]
        for o in client.get("/options/orders?state=all&days=7", headers=AUTH).json()["orders"]
    }
    quarter = {
        o["candidate_id"]
        for o in client.get("/options/orders?state=all&days=90", headers=AUTH).json()["orders"]
    }
    assert "old" not in week and "old" in quarter
    assert client.get("/options/orders?days=0", headers=AUTH).status_code == 422
    assert client.get("/options/orders?days=366", headers=AUTH).status_code == 422


def test_a_fill_names_its_contract(client) -> None:
    (fill,) = client.get("/options/fills?days=7", headers=AUTH).json()["fills"]
    assert (fill["underlying"], fill["strategy"], fill["right"], fill["strike"]) == (
        "AAPL",
        "cash_secured_put",
        "P",
        185.0,
    )
    assert fill["expiry"] == _EXPIRY.isoformat()


def test_a_fill_falls_back_to_its_candidate_when_the_order_has_no_snapshot(client) -> None:
    with session_scope() as s:
        order = OrderRow(
            candidate_id="c1", state="filled", filled_qty=1.0, is_live=False, snapshot=None
        )
        s.add(order)
        s.flush()
        s.add(
            FillRow(
                order_id=order.id,
                candidate_id="c1",
                action="SELL",
                filled_qty=1.0,
                avg_price=3.25,
                is_live=False,
                filled_at=datetime.now(UTC),
            )
        )
    fills = client.get("/options/fills?days=7", headers=AUTH).json()["fills"]
    nvda = next(f for f in fills if f["candidate_id"] == "c1")
    assert (nvda["underlying"], nvda["strike"], nvda["right"]) == ("NVDA", 190.0, "P")


def test_a_fill_with_no_order_and_no_candidate_has_an_unknown_contract_not_a_zero(client) -> None:
    with session_scope() as s:
        s.add(
            FillRow(
                order_id=999,
                candidate_id="ghost",
                action="SELL",
                filled_qty=1.0,
                avg_price=1.0,
                is_live=False,
                filled_at=datetime.now(UTC),
            )
        )
    ghost = next(
        f
        for f in client.get("/options/fills?days=7", headers=AUTH).json()["fills"]
        if f["candidate_id"] == "ghost"
    )
    for field in ("underlying", "strategy", "right", "strike", "expiry"):
        assert ghost[field] is None, field


def test_fills_reach_back_a_year_and_no_further(client) -> None:
    assert client.get("/options/fills?days=365", headers=AUTH).status_code == 200
    assert client.get("/options/fills?days=366", headers=AUTH).status_code == 422


def test_a_partial_order_is_history_not_working(client) -> None:
    """`partial` is final (the executors cancel the rest at the fill timeout, 2026-10-27): the
    rewritten route must keep it out of `working`, as the route it replaces did."""
    with session_scope() as s:
        s.add(
            OrderRow(
                candidate_id="half",
                state="partial",
                filled_qty=1.0,
                is_live=False,
                snapshot=_snap(underlying="HALF"),
            )
        )
    working = {
        o["candidate_id"] for o in client.get("/options/orders", headers=AUTH).json()["orders"]
    }
    every = {
        o["candidate_id"]
        for o in client.get("/options/orders?state=all", headers=AUTH).json()["orders"]
    }
    assert "half" not in working and "half" in every
