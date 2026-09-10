"""GET /portfolio/campaigns — the wheel threads Telegram's /campaigns renders as text.

`as_of` is request time here, not a snapshot time — campaigns are written on fill,
not captured. A pruned candidate still renders as a leg with `known: false`;
financials survive pruning, so the leg list must not silently shrink beneath them.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from tests.conftest import OWNER


def test_an_open_campaign_with_three_legs_returns_all_three_in_leg_order(
    client, seed_campaign
) -> None:
    seed_campaign(
        symbol="NVDA", leg_candidate_ids=["c1", "c2", "c3"], seed_candidates=["c1", "c2", "c3"]
    )

    body = client.get("/portfolio/campaigns", headers=OWNER).json()
    assert len(body["campaigns"]) == 1
    campaign = body["campaigns"][0]
    assert campaign["symbol"] == "NVDA"
    assert campaign["status"] == "open"
    assert [leg["candidate_id"] for leg in campaign["legs"]] == ["c1", "c2", "c3"]
    assert all(leg["known"] is True for leg in campaign["legs"])


def test_a_pruned_candidate_still_renders_as_a_leg(client, seed_campaign) -> None:
    """Financials survive pruning; the leg list must not silently shrink beneath them."""
    seed_campaign(symbol="NVDA", leg_candidate_ids=["c1", "c2"], seed_candidates=["c1"])

    campaign = client.get("/portfolio/campaigns", headers=OWNER).json()["campaigns"][0]
    assert len(campaign["legs"]) == 2
    assert campaign["legs"][0]["known"] is True
    assert campaign["legs"][1]["known"] is False
    assert campaign["legs"][1]["strike"] is None
    assert campaign["legs"][1]["expiry"] is None


def test_status_open_excludes_closed(client, seed_campaign) -> None:
    seed_campaign(symbol="NVDA", leg_candidate_ids=["c1"], status="open")
    seed_campaign(
        symbol="AAPL", leg_candidate_ids=["a1"], status="closed", closed_date=date.today()
    )

    body = client.get("/portfolio/campaigns?status=open", headers=OWNER).json()
    assert [c["symbol"] for c in body["campaigns"]] == ["NVDA"]


def test_status_closed_excludes_open(client, seed_campaign) -> None:
    seed_campaign(symbol="NVDA", leg_candidate_ids=["c1"], status="open")
    seed_campaign(
        symbol="AAPL", leg_candidate_ids=["a1"], status="closed", closed_date=date.today()
    )

    body = client.get("/portfolio/campaigns?status=closed", headers=OWNER).json()
    assert [c["symbol"] for c in body["campaigns"]] == ["AAPL"]


def test_status_omitted_returns_both(client, seed_campaign) -> None:
    seed_campaign(symbol="NVDA", leg_candidate_ids=["c1"], status="open")
    seed_campaign(
        symbol="AAPL", leg_candidate_ids=["a1"], status="closed", closed_date=date.today()
    )

    body = client.get("/portfolio/campaigns", headers=OWNER).json()
    assert len(body["campaigns"]) == 2


def test_symbol_filters(client, seed_campaign) -> None:
    seed_campaign(symbol="NVDA", leg_candidate_ids=["c1"])
    seed_campaign(symbol="AAPL", leg_candidate_ids=["a1"])

    body = client.get("/portfolio/campaigns?symbol=NVDA", headers=OWNER).json()
    assert [c["symbol"] for c in body["campaigns"]] == ["NVDA"]


def test_an_assigned_campaign_reports_stored_fields_without_recomputation(
    client, seed_campaign
) -> None:
    seed_campaign(
        symbol="NVDA",
        leg_candidate_ids=["c1"],
        assigned=True,
        adjusted_cost_basis=173.50,
        realized_stock_pnl=250.0,
    )

    campaign = client.get("/portfolio/campaigns", headers=OWNER).json()["campaigns"][0]
    assert campaign["assigned"] is True
    assert campaign["adjusted_cost_basis"] == 173.50
    assert campaign["realized_stock_pnl"] == 250.0


def test_financial_rollups_ride_along(client, seed_campaign) -> None:
    seed_campaign(
        symbol="NVDA",
        leg_candidate_ids=["c1"],
        total_premium_collected=650.0,
        total_debit_paid=150.0,
        net_premium=500.0,
    )

    campaign = client.get("/portfolio/campaigns", headers=OWNER).json()["campaigns"][0]
    assert campaign["total_premium_collected"] == 650.0
    assert campaign["total_debit_paid"] == 150.0
    assert campaign["net_premium"] == 500.0


def test_open_campaigns_sort_before_closed_at_the_same_date(client, seed_campaign) -> None:
    seed_campaign(
        symbol="AAA",
        leg_candidate_ids=["x1"],
        status="closed",
        closed_date=date.today(),
        opened=date.today(),
    )
    # Inserted AFTER the closed one, so id-ordering alone would put it second —
    # the explicit status key, not insertion order, must win.
    seed_campaign(symbol="BBB", leg_candidate_ids=["x2"], status="open", opened=date.today())

    body = client.get("/portfolio/campaigns", headers=OWNER).json()
    assert [c["symbol"] for c in body["campaigns"]] == ["BBB", "AAA"]


def test_campaigns_order_by_opened_date_descending(client, seed_campaign) -> None:
    seed_campaign(symbol="OLD", leg_candidate_ids=["x1"], opened=date.today() - timedelta(days=5))
    seed_campaign(symbol="NEW", leg_candidate_ids=["x2"], opened=date.today())

    body = client.get("/portfolio/campaigns", headers=OWNER).json()
    assert [c["symbol"] for c in body["campaigns"]] == ["NEW", "OLD"]


def test_empty_database_returns_an_empty_list_and_valid_as_of(client) -> None:
    body = client.get("/portfolio/campaigns", headers=OWNER).json()
    assert body["campaigns"] == []
    assert body["as_of"]


def test_as_of_is_request_time_not_a_snapshot_time(client, seed_campaign) -> None:
    """Campaigns are written on fill, not captured — request time is the honest stamp."""
    before = datetime.now(UTC) - timedelta(seconds=1)
    body = client.get("/portfolio/campaigns", headers=OWNER).json()
    after = datetime.now(UTC) + timedelta(seconds=1)
    assert before <= datetime.fromisoformat(body["as_of"]) <= after


def test_a_non_owner_is_refused(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/portfolio/campaigns", headers=OWNER).status_code == 403
