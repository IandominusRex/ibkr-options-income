"""Task 5.2 — `GET /pnl/equity`.

The route computes nothing: `build_legs` feeds `equity_curve` (M4 Task 4.6),
which owns the point/gap semantics. `book=all` is fine here, deliberately
unlike `/pnl/summary` — mixing books in a *curve* is a display choice the
client makes, not a headline total. Gaps pass through untouched so the chart
can render them as gaps, and no field anywhere is named `realized_pnl`.
"""

from __future__ import annotations

from datetime import date

import pytest

from tests.conftest import OWNER


@pytest.fixture()
def db(api_db):
    """Local override for these route tests: the storage engine bound to the
    API client's file, so seeds cross the boundary the routes read. M4's
    builder tests keep the private-t.db `db` in tests/conftest.py."""
    return api_db


def test_no_journal_rows_is_an_empty_curve_not_an_error(client, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.5), expiry_in_days=30)

    r = client.get("/pnl/equity", headers=OWNER)
    assert r.status_code == 200
    curve = r.json()["curve"]
    assert curve["points"] == []
    assert curve["gaps"] == []
    assert curve["starts_at"] is None


def test_three_journal_days_with_one_missing_trading_day_reports_it_as_a_gap(
    client, db, seed_journal_day
) -> None:
    from datetime import date as d

    # Mon 2026-09-07, Wed 2026-09-09, Fri 2026-09-11 — Tue 09-08 is a missed trading day.
    seed_journal_day(d(2026, 9, 7))
    seed_journal_day(d(2026, 9, 9))
    seed_journal_day(d(2026, 9, 11))

    curve = client.get("/pnl/equity", headers=OWNER).json()["curve"]
    assert date(2026, 9, 8) in [date.fromisoformat(g) for g in curve["gaps"]]


def test_starts_at_is_the_first_points_date(client, db, seed_journal_day) -> None:
    from datetime import date as d

    seed_journal_day(d(2026, 9, 1))
    seed_journal_day(d(2026, 9, 2))

    curve = client.get("/pnl/equity", headers=OWNER).json()["curve"]
    assert curve["starts_at"] == "2026-09-01"


def test_since_trims_leading_points_and_moves_starts_at(client, db, seed_journal_day) -> None:
    from datetime import date as d

    seed_journal_day(d(2026, 9, 1))
    seed_journal_day(d(2026, 9, 2))
    seed_journal_day(d(2026, 9, 3))

    curve = client.get("/pnl/equity?since=2026-09-02", headers=OWNER).json()["curve"]
    assert curve["starts_at"] == "2026-09-02"
    assert [p["entry_date"] for p in curve["points"]] == ["2026-09-02", "2026-09-03"]


def test_every_point_carries_premium_cashflow_and_nothing_is_named_realized_pnl(
    client, db, seed_journal_day
) -> None:
    from datetime import date as d

    seed_journal_day(d(2026, 9, 1), realized_pnl=42.0)
    seed_journal_day(d(2026, 9, 2), realized_pnl=-10.0)

    body = client.get("/pnl/equity", headers=OWNER).json()

    def no_realized_pnl_anywhere(node: object) -> bool:
        if isinstance(node, dict):
            return all(k != "realized_pnl" and no_realized_pnl_anywhere(v) for k, v in node.items())
        if isinstance(node, list):
            return all(no_realized_pnl_anywhere(v) for v in node)
        return True

    assert no_realized_pnl_anywhere(body), "the API renames the column; a regression here lies"
    assert all("premium_cashflow" in p for p in body["curve"]["points"])
    assert body["curve"]["points"][0]["premium_cashflow"] == 42.0


def test_a_mixed_book_is_fine_on_the_curve_unlike_the_summary(client, seed_leg) -> None:
    """Design point 3: a curve may show both books; only a headline total refuses."""
    seed_leg(candidate_id="p1", sold=(1, 1.0), is_live=False, expiry_in_days=-1)
    seed_leg(candidate_id="l1", sold=(1, 3.0), is_live=True, expiry_in_days=-1)

    r = client.get("/pnl/equity?book=all", headers=OWNER)
    assert r.status_code == 200


def test_filters_are_echoed_back(client) -> None:
    body = client.get("/pnl/equity?book=paper", headers=OWNER).json()
    assert body["filters"]["book"] == "paper"


def test_a_non_owner_is_refused(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/pnl/equity", headers=OWNER).status_code == 403
