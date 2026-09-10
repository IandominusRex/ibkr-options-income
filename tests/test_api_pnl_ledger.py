"""Task 5.1 — `GET /pnl/ledger` and `GET /pnl/summary`.

Thin renderers over `src/reporting/pnl.py` (M4): `build_legs` → `build_campaigns`
→ `build_summary`. No route computes a P&L figure of its own — the single-
accounting-rule invariant M4 established. Marks come from `read_portfolio`, the
same snapshot the portfolio page renders, so the two surfaces agree by
construction. Unknown means `null`, never zero.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import OWNER


@pytest.fixture()
def db(api_db):
    """Local override for these route tests: the storage engine bound to the
    API client's file, so seeds cross the boundary the routes read. M4's
    builder tests keep the private-t.db `db` in tests/conftest.py."""
    return api_db


def test_an_empty_database_is_empty_not_zero(client) -> None:
    r = client.get("/pnl/ledger", headers=OWNER)
    assert r.status_code == 200
    body = r.json()
    assert body["campaigns"] == []
    assert body["n_legs"] == 0
    assert body["marks_as_of"] is None
    assert body["filters"]["book"] == "all"


def test_a_seeded_wheel_returns_its_campaign_with_its_legs(client, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.5), campaign_id="NVDA-wheel", expiry_in_days=-3)
    seed_leg(candidate_id="c2", sold=(1, 1.0), campaign_id="NVDA-wheel", expiry_in_days=-2)

    body = client.get("/pnl/ledger", headers=OWNER).json()
    assert len(body["campaigns"]) == 1
    campaign = body["campaigns"][0]
    assert campaign["campaign_id"] == "NVDA-wheel"
    assert campaign["symbol"] == "NVDA"
    assert [leg["candidate_id"] for leg in campaign["legs"]] == ["c1", "c2"]


def test_symbol_filters(client, seed_leg) -> None:
    seed_leg(candidate_id="a1", sold=(1, 1.5), symbol="NVDA", expiry_in_days=-1)
    seed_leg(candidate_id="a2", sold=(1, 1.5), symbol="AAPL", expiry_in_days=-1)

    body = client.get("/pnl/ledger?symbol=NVDA", headers=OWNER).json()
    assert body["n_legs"] == 1
    assert body["campaigns"][0]["legs"][0]["underlying"] == "NVDA"


def test_strategy_filters(client, seed_leg) -> None:
    seed_leg(candidate_id="s1", sold=(1, 1.5), strategy="cash_secured_put", expiry_in_days=-1)
    seed_leg(
        candidate_id="s2", sold=(1, 1.5), strategy="covered_call", right="C", expiry_in_days=-1
    )

    body = client.get("/pnl/ledger?strategy=cash_secured_put", headers=OWNER).json()
    assert body["n_legs"] == 1
    assert body["campaigns"][0]["legs"][0]["strategy"] == "cash_secured_put"


def test_outcome_filters(client, seed_leg) -> None:
    """An open leg is `still_open`; an expired one is `expired_worthless`."""
    seed_leg(candidate_id="o1", sold=(1, 1.5), expiry_in_days=30)
    seed_leg(candidate_id="o2", sold=(1, 1.5), expiry_in_days=-3)

    body = client.get("/pnl/ledger?outcome=still_open", headers=OWNER).json()
    assert body["n_legs"] == 1
    assert body["campaigns"][0]["legs"][0]["candidate_id"] == "o1"

    closed = client.get("/pnl/ledger?outcome=expired_worthless", headers=OWNER).json()
    assert closed["n_legs"] == 1
    assert closed["campaigns"][0]["legs"][0]["candidate_id"] == "o2"


def test_since_filters_out_legs_opened_before_it(client, seed_leg) -> None:
    seed_leg(candidate_id="y1", sold=(1, 1.5), days_held=30, expiry_in_days=-1)
    seed_leg(candidate_id="y2", sold=(1, 1.5), days_held=1, expiry_in_days=-1)

    cutoff = (datetime.now(UTC) - timedelta(days=2)).date()
    body = client.get(f"/pnl/ledger?since={cutoff.isoformat()}", headers=OWNER).json()
    assert body["n_legs"] == 1
    assert body["campaigns"][0]["legs"][0]["candidate_id"] == "y2"


def test_until_filters_out_legs_opened_after_it(client, seed_leg) -> None:
    seed_leg(candidate_id="u1", sold=(1, 1.5), days_held=30, expiry_in_days=-1)
    seed_leg(candidate_id="u2", sold=(1, 1.5), days_held=1, expiry_in_days=-1)

    cutoff = (datetime.now(UTC) - timedelta(days=2)).date()
    body = client.get(f"/pnl/ledger?until={cutoff.isoformat()}", headers=OWNER).json()
    assert body["n_legs"] == 1
    assert body["campaigns"][0]["legs"][0]["candidate_id"] == "u1"


def test_a_mixed_book_summary_is_refused_not_totalled(client, seed_leg) -> None:
    """M4's ValueError becomes an answer here, never a 500 and never a wrong number."""
    seed_leg(candidate_id="p1", sold=(1, 1.0), is_live=False, expiry_in_days=-1)
    seed_leg(candidate_id="l1", sold=(1, 3.0), is_live=True, expiry_in_days=-1)

    r = client.get("/pnl/summary?book=all", headers=OWNER)
    assert r.status_code == 422
    assert r.json()["detail"]["reason"] == "mixed_book"

    paper = client.get("/pnl/summary?book=paper", headers=OWNER).json()["summary"]
    live = client.get("/pnl/summary?book=live", headers=OWNER).json()["summary"]
    assert paper["realized_total"] != live["realized_total"]


def test_a_single_book_summary_returns_one_summary(client, seed_leg) -> None:
    seed_leg(candidate_id="p1", sold=(1, 1.0), expiry_in_days=-1)
    body = client.get("/pnl/summary?book=paper", headers=OWNER).json()
    assert body["summary"]["realized_total"] > 0
    assert body["filters"]["book"] == "paper"


def test_an_empty_book_summary_is_a_valid_empty_summary_not_an_error(client) -> None:
    """No fills at all is an empty summary (win_rate null), never a 422."""
    body = client.get("/pnl/summary?book=live", headers=OWNER).json()
    assert body["summary"]["n_closed"] == 0
    assert body["summary"]["win_rate"] is None
    assert body["summary"]["realized_total"] == 0.0


def test_marks_come_from_the_same_snapshot_the_portfolio_renders(
    client, seed_leg, seed_portfolio_snapshot
) -> None:
    when = datetime.now(UTC) - timedelta(minutes=5)
    seed_portfolio_snapshot(captured_at=when)
    seed_leg(candidate_id="c1", sold=(1, 1.5), expiry_in_days=30)

    ledger = client.get("/pnl/ledger", headers=OWNER).json()
    portfolio = client.get("/portfolio/summary", headers=OWNER).json()
    assert ledger["marks_as_of"] == portfolio["as_of"]


def test_no_snapshot_means_null_marks_not_zero_marks(client, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.5), expiry_in_days=30)
    body = client.get("/pnl/ledger", headers=OWNER).json()
    assert body["marks_as_of"] is None
    assert all(c["option_unrealized"] is None for c in body["campaigns"])


def test_with_a_snapshot_marks_as_of_is_the_snapshot_captured_at(
    client, seed_leg, seed_portfolio_snapshot
) -> None:
    when = datetime.now(UTC) - timedelta(minutes=5)
    seed_portfolio_snapshot(captured_at=when)
    seed_leg(candidate_id="c1", sold=(1, 1.5), expiry_in_days=30)

    body = client.get("/pnl/ledger", headers=OWNER).json()
    assert body["marks_as_of"] == when.isoformat().replace("+00:00", "Z")


def test_filters_are_echoed_back(client) -> None:
    body = client.get("/pnl/ledger?symbol=NVDA&book=paper", headers=OWNER).json()
    assert body["filters"]["symbol"] == "NVDA"
    assert body["filters"]["book"] == "paper"

    body = client.get("/pnl/summary?book=live", headers=OWNER).json()
    assert body["filters"]["book"] == "live"


def test_n_legs_equals_the_sum_of_every_campaigns_leg_count(client, seed_leg) -> None:
    """M4 Task 4.4's every-leg-in-exactly-one-thread, checked at the client boundary."""
    seed_leg(candidate_id="w1", sold=(1, 1.5), campaign_id="wheel-1", expiry_in_days=-3)
    seed_leg(candidate_id="w2", sold=(1, 1.5), campaign_id="wheel-1", expiry_in_days=-2)
    seed_leg(candidate_id="w3", sold=(1, 1.5), expiry_in_days=-1)  # campaign-less → synthetic
    seed_leg(candidate_id="w4", sold=(1, 1.5), symbol="AAPL", expiry_in_days=-1)

    body = client.get("/pnl/ledger", headers=OWNER).json()
    assert sum(len(c["legs"]) for c in body["campaigns"]) == body["n_legs"] == 4


def test_a_non_owner_is_refused_on_both_routes(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/pnl/ledger", headers=OWNER).status_code == 403
    assert client.get("/pnl/summary?book=paper", headers=OWNER).status_code == 403


def test_an_unknown_filter_value_is_a_422_not_a_silently_ignored_one(client) -> None:
    assert client.get("/pnl/ledger?book=both", headers=OWNER).status_code == 422
    assert client.get("/pnl/summary?book=whatever", headers=OWNER).status_code == 422


def test_the_ledger_may_list_both_books_even_though_the_summary_refuses_their_total(
    client, seed_leg
) -> None:
    seed_leg(candidate_id="p1", sold=(1, 1.0), is_live=False, expiry_in_days=-1)
    seed_leg(candidate_id="l1", sold=(1, 3.0), is_live=True, expiry_in_days=-1)

    body = client.get("/pnl/ledger?book=all", headers=OWNER).json()
    assert body["n_legs"] == 2
