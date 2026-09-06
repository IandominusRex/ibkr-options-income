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
from src.storage.models import CandidateRow, FillRow, OrderRow

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
    # working = queued, submitted, partial — filled is excluded.
    assert states <= {"queued", "submitted", "partial"}
    assert "filled" not in states


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
