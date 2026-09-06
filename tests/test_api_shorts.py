"""GET /options/shorts — open short option positions from the latest snapshot.

``as_of`` is the snapshot's capture time, not request time. Long options and stock
are excluded. ``delta`` carries its source. ``mark`` / ``unrealized_pnl`` are null
when absent, never 0.0. ``alerts`` is empty not null when nothing has fired.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.storage.db import session_scope
from src.storage.models import PositionSnapshotRow, RollAlertRow

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _positions() -> list[dict]:
    return [
        # Short put — the kind of position we want to see.
        {
            "symbol": "NVDA  260117 00190000 P",
            "sec_type": "OPT",
            "position": -1.0,
            "avg_cost": 3.25,
            "market_price": 2.10,
            "unrealized_pnl": 115.0,
            "right": "P",
            "strike": 190.0,
            "expiry": "2026-01-17",
            "delta": -0.22,
            "underlying": "NVDA",
            "greeks_source": "ibkr",
        },
        # Short call — also a short option.
        {
            "symbol": "AAPL  260117 00185000 C",
            "sec_type": "OPT",
            "position": -2.0,
            "avg_cost": 2.50,
            "market_price": None,
            "unrealized_pnl": None,
            "right": "C",
            "strike": 185.0,
            "expiry": "2026-01-17",
            "delta": 0.30,
            "underlying": "AAPL",
            "greeks_source": "black_scholes",
        },
        # Long stock — must be excluded.
        {
            "symbol": "NVDA",
            "sec_type": "STK",
            "position": 500.0,
            "avg_cost": 180.0,
            "market_price": 200.0,
            "unrealized_pnl": 10000.0,
        },
        # Long option — must be excluded.
        {
            "symbol": "MSFT  260117 00300000 C",
            "sec_type": "OPT",
            "position": 1.0,
            "avg_cost": 3.00,
            "right": "C",
            "strike": 300.0,
            "expiry": "2026-01-17",
            "delta": 0.45,
            "underlying": "MSFT",
        },
    ]


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

    capture_time = datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC)
    with session_scope() as s:
        s.add(
            PositionSnapshotRow(
                snapshot_date=date(2026, 9, 6),
                payload=_positions(),
                created_at=capture_time,
            )
        )
        s.add(
            RollAlertRow(
                position_symbol="NVDA  260117 00190000 P",
                underlying="NVDA",
                trigger="delta_drift",
                detail="delta has drifted to -0.42, beyond the 0.40 ceiling",
                created_at=capture_time,
            )
        )
    return TestClient(create_app())


def test_shorts_requires_owner_auth(client) -> None:
    assert client.get("/options/shorts").status_code == 401


def test_shorts_requires_owner_role(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/options/shorts", headers=AUTH).status_code == 403


def test_as_of_is_snapshot_capture_time_not_request_time(client) -> None:
    r = client.get("/options/shorts", headers=AUTH)
    assert r.status_code == 200
    # The snapshot was created at 2026-09-06T10:00:00Z — not "now".
    assert r.json()["as_of"].startswith("2026-09-06T10:00:00")


def test_only_short_options_are_returned(client) -> None:
    r = client.get("/options/shorts", headers=AUTH)
    shorts = r.json()["shorts"]
    syms = {s["position_symbol"] for s in shorts}
    assert "NVDA  260117 00190000 P" in syms
    assert "AAPL  260117 00185000 C" in syms
    # Long stock and long option excluded.
    assert "NVDA" not in syms
    assert "MSFT  260117 00300000 C" not in syms


def test_mark_is_null_not_zero_when_absent(client) -> None:
    r = client.get("/options/shorts", headers=AUTH)
    shorts = r.json()["shorts"]
    aapl = [s for s in shorts if s["underlying"] == "AAPL"][0]
    assert aapl["mark"] is None
    assert aapl["unrealized_pnl"] is None


def test_mark_is_set_when_present(client) -> None:
    r = client.get("/options/shorts", headers=AUTH)
    shorts = r.json()["shorts"]
    nvda = [s for s in shorts if s["underlying"] == "NVDA"][0]
    assert nvda["mark"] == 2.10
    assert nvda["unrealized_pnl"] == 115.0


def test_delta_carries_its_source(client) -> None:
    r = client.get("/options/shorts", headers=AUTH)
    shorts = r.json()["shorts"]
    nvda = [s for s in shorts if s["underlying"] == "NVDA"][0]
    aapl = [s for s in shorts if s["underlying"] == "AAPL"][0]
    # NVDA's delta is IBKR-sourced; AAPL's is BS-sourced (COMPUTED in the Source
    # enum). They must not look identical.
    assert nvda["delta"]["source"] == "ibkr"
    assert aapl["delta"]["source"] == "computed"
    assert nvda["delta"]["value"] == -0.22
    assert aapl["delta"]["value"] == 0.30


def test_alerts_is_empty_not_null_when_nothing_fired(client) -> None:
    r = client.get("/options/shorts", headers=AUTH)
    shorts = r.json()["shorts"]
    aapl = [s for s in shorts if s["underlying"] == "AAPL"][0]
    assert aapl["alerts"] == []
    assert aapl["alerts"] is not None


def test_alerts_render_on_the_position_row(client) -> None:
    r = client.get("/options/shorts", headers=AUTH)
    shorts = r.json()["shorts"]
    nvda = [s for s in shorts if s["underlying"] == "NVDA"][0]
    assert len(nvda["alerts"]) == 1
    assert nvda["alerts"][0]["trigger"] == "delta_drift"
    assert "0.42" in nvda["alerts"][0]["detail"]


def test_empty_shorts_returns_200(client) -> None:
    """A snapshot with only long positions returns an empty list, not 404."""
    with session_scope() as s:
        s.query(PositionSnapshotRow).delete()
        s.add(
            PositionSnapshotRow(
                snapshot_date=date(2026, 9, 7),
                payload=[
                    {"symbol": "NVDA", "sec_type": "STK", "position": 100.0, "avg_cost": 180.0}
                ],
                created_at=datetime(2026, 9, 7, 10, 0, 0, tzinfo=UTC),
            )
        )
    r = client.get("/options/shorts", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["shorts"] == []


def test_missing_expiry_renders_null_not_today(client) -> None:
    """A short with no expiry must surface null, never date.today() (which would
    fabricate dte=0 and a false assignment_risk signal)."""
    with session_scope() as s:
        s.query(PositionSnapshotRow).delete()
        s.add(
            PositionSnapshotRow(
                snapshot_date=date(2026, 9, 6),
                payload=[
                    {
                        "symbol": "NVDA P",
                        "sec_type": "OPT",
                        "position": -1.0,
                        "avg_cost": 3.25,
                        "market_price": 2.1,
                        "unrealized_pnl": 115.0,
                        "right": "P",
                        "strike": 190.0,
                        # No expiry, no delta.
                        "underlying": "NVDA",
                    }
                ],
                created_at=datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC),
            )
        )
    r = client.get("/options/shorts", headers=AUTH)
    assert r.status_code == 200
    short = r.json()["shorts"][0]
    assert short["expiry"] is None
    assert short["dte"] is None
    assert short["assignment_risk"] is False  # cannot assert without expiry + delta


def test_assignment_risk_requires_expiry_and_delta(client) -> None:
    """A deep-ITM short (|delta| >= 0.70) near expiry (dte <= 7) is assignment risk;
    a missing delta or a longer-dte position is not."""
    with session_scope() as s:
        s.query(PositionSnapshotRow).delete()
        near = (date.today() + timedelta(days=5)).isoformat()
        s.add(
            PositionSnapshotRow(
                snapshot_date=date.today(),
                payload=[
                    {
                        "symbol": "NVDA P",
                        "sec_type": "OPT",
                        "position": -1.0,
                        "avg_cost": 3.25,
                        "right": "P",
                        "strike": 190.0,
                        "expiry": near,
                        "delta": -0.78,
                        "underlying": "NVDA",
                    }
                ],
                created_at=datetime.now(UTC),
            )
        )
    r = client.get("/options/shorts", headers=AUTH)
    short = r.json()["shorts"][0]
    assert short["assignment_risk"] is True


def test_pnl_pct_uses_total_pnl_over_position_cost(client) -> None:
    """pnl_pct is unrealized_pnl / (|avg_cost| * contracts), not / |avg_cost|.

    A 1-contract short with $3.25/share avg cost and $115 total P&L is ~35% ROC,
    not ~3538% (which is what dividing by per-share cost alone would yield)."""
    r = client.get("/options/shorts", headers=AUTH)
    shorts = r.json()["shorts"]
    nvda = [s for s in shorts if s["underlying"] == "NVDA"][0]
    # $115 P&L on 1 contract at $3.25/share = 115 / 3.25 = ~35.38
    assert nvda["pnl_pct"] is not None
    assert 35.0 <= nvda["pnl_pct"] <= 36.0
    # Sanity: the per-share division would have given ~3538, far outside this band.
    assert nvda["pnl_pct"] < 100


def test_no_snapshot_returns_200_with_empty_list(monkeypatch, tmp_path) -> None:
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
    r = c.get("/options/shorts", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["shorts"] == []
