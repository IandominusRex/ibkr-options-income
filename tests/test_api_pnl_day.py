"""GET /pnl/day and GET /pnl/calendar - thin renders of src/reporting/day.py."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.storage.models import ApprovalRow, CandidateRow, FillRow
from tests.conftest import OWNER

ET = ZoneInfo("America/New_York")
DAY = date(2026, 10, 9)
FAR = date(2099, 1, 15)


@pytest.fixture()
def db(api_db):
    return api_db


@pytest.fixture(autouse=True)
def _no_real_spreads_db(tmp_path, monkeypatch):
    import src.api.spreads_db as sdb

    monkeypatch.setattr(sdb, "_resolve_path", lambda: str(tmp_path / "no-spreads.db"))
    sdb.reset_engine()
    yield
    sdb.reset_engine()


def seed(
    db, cid: str, *, right="P", strategy="cash_secured_put", sold_at, bought_at=None, reason=None
):
    with db() as s:
        s.add(
            CandidateRow(
                candidate_id=cid, run_id="r", strategy=strategy, underlying="AAPL",
                right=right, strike=180.0, expiry=FAR, payload={},
            )
        )  # fmt: skip
        s.add(
            FillRow(order_id=1, candidate_id=cid, action="SELL", filled_qty=1, avg_price=2.0,
                    commission=1.0, filled_at=sold_at)
        )  # fmt: skip
        if bought_at is not None:
            s.add(
                FillRow(order_id=2, candidate_id=cid, action="BUY", filled_qty=1, avg_price=0.5,
                        commission=1.0, close_reason=reason, filled_at=bought_at)
            )  # fmt: skip


def test_the_day_defaults_to_today_in_new_york_and_is_empty_when_nothing_happened(client) -> None:
    body = client.get("/pnl/day", headers=OWNER).json()
    assert body["date"] == datetime.now(UTC).astimezone(ET).date().isoformat()
    assert body["trades"] == [] and body["book"] == "paper" and body["strategy"] == "all"
    assert body["spreads_available"] is False  # no spreads.db in this fixture


def test_a_day_lists_what_was_opened_and_closed_with_its_reason(client, db) -> None:
    seed(
        db,
        "c1",
        sold_at=datetime(2026, 10, 9, 14),
        bought_at=datetime(2026, 10, 9, 17),
        reason="profit_take",
    )
    body = client.get("/pnl/day?date=2026-10-09", headers=OWNER).json()
    assert [t["action"] for t in body["trades"]] == ["closed", "opened"]
    closed = body["trades"][0]
    assert closed["how"] == "bought_back" and closed["kind"] == "csp"
    assert closed["net_pnl"] == pytest.approx(150 - 2)
    assert {f["label"] for f in closed["facts"]} == {"Rule", "Result"}
    assert body["trades"][1]["net_pnl"] is None  # unknown stays null, never 0


def test_the_strategy_scopes_the_cards(client, db) -> None:
    seed(db, "put", sold_at=datetime(2026, 10, 9, 14))
    seed(db, "call", right="C", strategy="covered_call", sold_at=datetime(2026, 10, 9, 15))

    def kinds(scope: str) -> list[str]:
        r = client.get(f"/pnl/day?date=2026-10-09&strategy={scope}", headers=OWNER)
        return [t["kind"] for t in r.json()["trades"]]

    assert sorted(kinds("all")) == ["cc", "csp"]
    assert kinds("csp") == ["csp"] and kinds("cc") == ["cc"] and kinds("spread") == []


def test_bad_parameters_are_422_and_a_viewer_is_refused(client) -> None:
    assert client.get("/pnl/day?date=nope", headers=OWNER).status_code == 422
    assert client.get("/pnl/day?strategy=condor", headers=OWNER).status_code == 422
    assert client.get("/pnl/day").status_code in (401, 403)
    assert client.get("/pnl/calendar?month=2026-13", headers=OWNER).status_code == 422
    assert client.get("/pnl/calendar").status_code in (401, 403)


def test_the_calendar_totals_a_month_by_close_day(client, db) -> None:
    seed(
        db,
        "a",
        sold_at=datetime(2026, 10, 2, 14),
        bought_at=datetime(2026, 10, 9, 15),
        reason="profit_take",
    )
    seed(
        db,
        "b",
        sold_at=datetime(2026, 10, 2, 14),
        bought_at=datetime(2026, 10, 9, 16),
        reason="profit_take",
    )
    seed(
        db,
        "c",
        sold_at=datetime(2026, 10, 2, 14),
        bought_at=datetime(2026, 10, 12, 16),
        reason="profit_take",
    )
    seed(db, "open", sold_at=datetime(2026, 10, 5, 14))
    body = client.get("/pnl/calendar?month=2026-10", headers=OWNER).json()
    cal = body["calendar"]
    assert cal["month"] == "2026-10-01" and cal["strategy"] == "all"
    assert [(d["date"], d["n_closed"]) for d in cal["days"]] == [
        ("2026-10-09", 2),
        ("2026-10-12", 1),
    ]
    assert cal["days"][0]["realized"] == pytest.approx(2 * 148)
    assert cal["total"] == pytest.approx(3 * 148) and cal["n_closed"] == 3
    assert body["spreads_available"] is False
    other = client.get("/pnl/calendar?month=2026-09", headers=OWNER).json()["calendar"]
    assert other["days"] == [] and other["total"] == 0.0


def test_the_books_closed_spreads_appear_in_the_day_and_the_calendar(
    client, monkeypatch, tmp_path
) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import src.api.spreads_db as sdb
    from src.spreads.store import SpreadPositionRow, SpreadsBase

    path = tmp_path / "spreads.db"
    eng = create_engine(f"sqlite:///{path}")
    SpreadsBase.metadata.create_all(eng)
    with Session(eng) as s:
        for sid, mode in (("p1", "paper"), ("s1", "shadow")):
            s.add(
                SpreadPositionRow(
                    spread_id=sid, mode=mode, side="put", expiry=DAY, short_strike=580.0,
                    long_strike=575.0, width=5.0, contracts_opened=2, contracts=0,
                    entry_credit=0.84, entry_commission=2.6, opened_at=datetime(2026, 10, 9, 14),
                    status="closed", closed_at=datetime(2026, 10, 9, 18), exit_debit=0.2,
                    exit_commission=2.6, exit_reason="profit_take", realized_pnl_usd=123.6,
                )
            )  # fmt: skip
        s.commit()
    eng.dispose()
    monkeypatch.setattr(sdb, "_resolve_path", lambda: str(path))
    sdb.reset_engine()

    day = client.get("/pnl/day?date=2026-10-09", headers=OWNER).json()
    assert day["spreads_available"] is True
    assert sorted(t["action"] for t in day["trades"]) == ["closed", "opened"]  # paper only
    assert {t["source"] for t in day["trades"]} == {"spreads"}
    cal = client.get("/pnl/calendar?month=2026-10", headers=OWNER).json()
    assert cal["calendar"]["total"] == pytest.approx(123.6)
    assert cal["spreads_available"] is True


@pytest.mark.parametrize("strategy", ["csp", "cc"])
def test_a_wheel_only_scope_never_needs_the_spreads_book(client, strategy) -> None:
    assert (
        client.get(f"/pnl/day?strategy={strategy}", headers=OWNER).json()["spreads_available"]
        is True
    )
    assert (
        client.get(f"/pnl/calendar?strategy={strategy}", headers=OWNER).json()["spreads_available"]
        is True
    )


def test_the_future_is_simply_empty(client) -> None:
    far = (datetime.now(UTC) + timedelta(days=400)).date().isoformat()
    assert client.get(f"/pnl/day?date={far}", headers=OWNER).json()["trades"] == []


def test_previous_and_next_skip_days_with_no_wheel_activity(client, db) -> None:
    seed(db, "early", sold_at=datetime(2026, 10, 5, 14))
    seed(
        db,
        "late",
        sold_at=datetime(2026, 10, 14, 14),
        bought_at=datetime(2026, 10, 16, 15),
        reason="profit_take",
    )
    with db() as s:
        # A call proposal raised on the 7th that never traded still makes the 7th a History day.
        s.add(
            ApprovalRow(candidate_id="x", status="expired", created_at=datetime(2026, 10, 7, 15),
                        snapshot={"strategy": "covered_call", "right": "C"})
        )  # fmt: skip
    body = client.get("/pnl/day?date=2026-10-09", headers=OWNER).json()
    assert (body["previous_day"], body["next_day"]) == ("2026-10-07", "2026-10-14")
    puts = client.get("/pnl/day?date=2026-10-09&strategy=csp", headers=OWNER).json()
    assert puts["previous_day"] == "2026-10-05"  # the call proposal is outside the puts' scope
    last = client.get("/pnl/day?date=2026-10-16", headers=OWNER).json()
    assert (last["previous_day"], last["next_day"]) == ("2026-10-14", None)
