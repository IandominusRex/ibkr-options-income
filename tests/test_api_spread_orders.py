"""GET /spreads/orders - the spreads book's filled orders (web overhaul Part 3, Task 3).

Read-only over data/spreads.db through src/api/spreads_db.py (the API may not import
src.spreads). The tests may import the spreads models to build a real schema.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.conftest import OWNER

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)


@pytest.fixture()
def spreads_file(tmp_path, monkeypatch):
    import src.api.routers.spreads as routes
    import src.api.spreads_db as sdb

    path = tmp_path / "spreads.db"
    monkeypatch.setattr(sdb, "_resolve_path", lambda: str(path))
    monkeypatch.setattr(routes, "_now", lambda: NOW)
    sdb.reset_engine()
    yield path
    sdb.reset_engine()


def _make_db(path, *, orders=(), positions=(), with_orders_table: bool = True) -> None:
    from src.spreads.store import SpreadOrderRow, SpreadPositionRow, SpreadsBase

    eng = create_engine(f"sqlite:///{path}")
    if with_orders_table:
        SpreadsBase.metadata.create_all(eng)
    else:
        SpreadPositionRow.__table__.create(eng)
    with Session(eng) as s:
        for p in positions:
            s.add(SpreadPositionRow(**p))
        for o in orders:
            s.add(SpreadOrderRow(**o))
        s.commit()
    eng.dispose()


def _position(**over) -> dict:
    base = dict(
        spread_id="20261015-P762-757-101726",
        mode="paper",
        side="put",
        expiry=date(2026, 10, 15),
        short_strike=762.0,
        long_strike=757.0,
        width=5.0,
        contracts_opened=2,
        contracts=0,
        entry_credit=0.25,
        entry_commission=2.6,
        opened_at=datetime(2026, 10, 15, 13, 46),
        status="closed",
    )
    base.update(over)
    return base


def _order(kind: str, at: datetime, **over) -> dict:
    base = dict(
        spread_id="20261015-P762-757-101726",
        kind=kind,
        order_ref=f"ref-{kind}",
        ib_order_id=11,
        perm_id=4001,
        filled_qty=2,
        price=0.25 if kind == "open" else 0.05,
        commission=2.6,
        reason=None if kind == "open" else "profit_take",
        created_at=at,
    )
    base.update(over)
    return base


def test_requires_owner(client, spreads_file) -> None:
    assert client.get("/spreads/orders").status_code == 401


def test_no_file_is_unavailable_not_an_error(client, spreads_file) -> None:
    body = client.get("/spreads/orders", headers=OWNER).json()
    assert body["available"] is False and body["orders"] == []
    assert isinstance(body["underlying"], str)


def test_orders_come_back_newest_first_with_their_spread(client, spreads_file) -> None:
    _make_db(
        spreads_file,
        positions=[_position()],
        orders=[
            _order("open", datetime(2026, 10, 15, 13, 46, 24)),
            _order("close", datetime(2026, 10, 15, 14, 33, 50)),
        ],
    )
    body = client.get("/spreads/orders", headers=OWNER).json()
    assert body["available"] is True
    assert [o["kind"] for o in body["orders"]] == ["close", "open"]
    close = body["orders"][0]
    assert (close["mode"], close["side"], close["short_strike"], close["long_strike"]) == (
        "paper",
        "put",
        762.0,
        757.0,
    )
    assert (close["filled_qty"], close["price"], close["commission"], close["reason"]) == (
        2,
        0.05,
        2.6,
        "profit_take",
    )
    assert close["expiry"] == "2026-10-15"
    # Stored naive UTC leaves the API with an offset, so a browser never reads it as local time.
    assert close["created_at"].endswith(("Z", "+00:00"))


def test_an_order_whose_spread_is_missing_still_lists_with_unknown_strikes(
    client, spreads_file
) -> None:
    _make_db(spreads_file, orders=[_order("open", datetime(2026, 10, 15, 13, 46))])
    (o,) = client.get("/spreads/orders", headers=OWNER).json()["orders"]
    for field in ("mode", "side", "expiry", "short_strike", "long_strike"):
        assert o[field] is None, field


def test_days_leaves_out_older_orders_and_limit_caps_the_list(client, spreads_file) -> None:
    _make_db(
        spreads_file,
        positions=[_position()],
        orders=[
            _order("open", datetime(2026, 9, 1, 13, 46)),
            _order("open", datetime(2026, 10, 15, 13, 46), order_ref="a"),
            _order("close", datetime(2026, 10, 15, 14, 33), order_ref="b"),
        ],
    )
    assert len(client.get("/spreads/orders?days=7", headers=OWNER).json()["orders"]) == 2
    assert len(client.get("/spreads/orders?days=60", headers=OWNER).json()["orders"]) == 3
    assert len(client.get("/spreads/orders?days=60&limit=1", headers=OWNER).json()["orders"]) == 1
    assert client.get("/spreads/orders?days=0", headers=OWNER).status_code == 422


def test_an_older_file_without_the_orders_table_is_available_with_no_orders(
    client, spreads_file
) -> None:
    _make_db(spreads_file, positions=[_position()], with_orders_table=False)
    body = client.get("/spreads/orders", headers=OWNER).json()
    assert body["available"] is True and body["orders"] == []
