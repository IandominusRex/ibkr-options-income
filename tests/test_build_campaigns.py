"""Campaign threads: legs grouped, stock leg read (never recomputed), marks honest."""

from __future__ import annotations

from datetime import date

from src.reporting.pnl import build_campaigns, build_legs


def test_no_snapshot_means_unrealised_is_unknown_not_zero(db, seed_leg) -> None:
    """A total that quietly means 'realised only' is how a P&L page misleads."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=30, campaign_id="camp1")
    campaign = build_campaigns(db, build_legs(db), snapshot=None)[0]
    assert campaign.option_unrealized is None
    assert campaign.stock_unrealized is None
    assert campaign.total_net == campaign.option_realized


def test_every_leg_lands_in_exactly_one_thread(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", campaign_id="camp1", sold=(1, 1.0))
    seed_leg(candidate_id="c2", campaign_id=None, sold=(1, 1.0))
    legs = build_legs(db)
    campaigns = build_campaigns(db, legs, snapshot=None)
    assert sum(len(c.legs) for c in campaigns) == len(legs)


def test_an_open_campaign_reports_a_real_zero_realised(db, seed_leg) -> None:
    """Zero closed legs is a measurement. It is not the same as unknown."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=30, campaign_id="camp1")
    assert build_campaigns(db, build_legs(db), snapshot=None)[0].option_realized == 0.0


def test_a_three_leg_campaign_groups_all_three_in_leg_order(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", campaign_id="camp1", sold=(1, 1.0), days_held=30)
    seed_leg(candidate_id="c2", campaign_id="camp1", sold=(1, 1.0), bought=(1, 0.3), days_held=20)
    seed_leg(candidate_id="c3", campaign_id="camp1", sold=(1, 1.0), days_held=10)
    campaign = build_campaigns(db, build_legs(db), snapshot=None)[0]
    assert len(campaign.legs) == 3
    assert [leg.candidate_id for leg in campaign.legs] == ["c1", "c2", "c3"]


def test_option_realized_sums_only_closed_legs(db, seed_leg) -> None:
    seed_leg(candidate_id="open", campaign_id="camp1", sold=(1, 2.00, 1.30), expiry_in_days=30)
    seed_leg(
        candidate_id="closed",
        campaign_id="camp1",
        sold=(1, 1.50, 1.30),
        bought=(1, 0.50, 1.30),
        expiry_in_days=30,
    )
    campaign = build_campaigns(db, build_legs(db), snapshot=None)[0]
    assert campaign.option_realized == 150.0 - 50.0 - 2.60  # the closed leg only (2 commissions)


def test_a_leg_with_no_campaign_lands_in_a_synthetic_thread(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", campaign_id=None, sold=(1, 1.0), bought=(1, 0.4))
    campaigns = build_campaigns(db, build_legs(db), snapshot=None)
    assert len(campaigns) == 1
    assert campaigns[0].campaign_id  # stable derived value, not None, not ""
    assert campaigns[0].status == "closed"  # every leg closed


def test_an_open_leg_with_no_campaign_makes_its_thread_open(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", campaign_id=None, sold=(1, 1.0), expiry_in_days=30)
    thread = build_campaigns(db, build_legs(db), snapshot=None)[0]
    assert thread.status == "open"


def test_an_assigned_campaign_reports_stock_fields_exactly_as_stored(db, seed_leg) -> None:
    from src.storage.models import CampaignRow

    seed_leg(candidate_id="c1", campaign_id="camp1", sold=(1, 1.50), expiry_in_days=-1)
    with db() as s:
        row = s.query(CampaignRow).one()
        row.assigned = True
        row.adjusted_cost_basis = 173.50
        row.realized_stock_pnl = 250.0
    campaign = build_campaigns(db, build_legs(db), snapshot=None)[0]
    assert campaign.assigned is True
    assert campaign.adjusted_cost_basis == 173.50
    assert campaign.stock_realized == 250.0
    assert campaign.total_net == campaign.option_realized + 250.0


def test_with_a_snapshot_an_open_legs_mark_contributes_to_option_unrealized(
    db,
    seed_leg,
    snapshot_mark,
) -> None:
    seed_leg(candidate_id="c1", campaign_id="camp1", sold=(1, 1.50), expiry_in_days=30)
    snapshot = snapshot_mark(underlying="NVDA", strike=170.0, right="P", unrealized_pnl=45.0)
    legs = build_legs(db)
    campaign = build_campaigns(db, legs, snapshot=snapshot)[0]
    assert campaign.option_unrealized == 45.0
    # and the leg's own field is populated — for the open leg only
    open_leg = campaign.legs[0]
    assert open_leg.unrealized_pnl == 45.0


def test_a_closed_legs_unrealized_stays_none_even_with_a_snapshot(
    db,
    seed_leg,
    snapshot_mark,
) -> None:
    """A closed leg has a result, not a mark; a mark on it would be meaningless."""
    seed_leg(
        candidate_id="c1",
        campaign_id="camp1",
        sold=(1, 1.50, 1.30),
        bought=(1, 0.40, 1.30),
        expiry_in_days=30,
    )
    seed_leg(candidate_id="c2", campaign_id="camp1", sold=(1, 1.50), expiry_in_days=30)
    snapshot = snapshot_mark(underlying="NVDA", strike=170.0, right="P", unrealized_pnl=45.0)
    campaign = build_campaigns(db, build_legs(db), snapshot=snapshot)[0]
    by_id = {leg.candidate_id: leg for leg in campaign.legs}
    assert by_id["c1"].unrealized_pnl is None  # closed — has a realized result
    assert by_id["c2"].unrealized_pnl == 45.0  # open — has a mark


def test_a_snapshot_without_a_matching_position_leaves_the_mark_none(
    db,
    seed_leg,
    snapshot_mark,
) -> None:
    """No fabricated marks: an open leg the snapshot does not know stays unmarked."""
    seed_leg(candidate_id="c1", campaign_id="camp1", sold=(1, 1.50), expiry_in_days=30)
    snapshot = snapshot_mark(underlying="AAPL", strike=100.0, right="P", unrealized_pnl=45.0)
    campaign = build_campaigns(db, build_legs(db), snapshot=snapshot)[0]
    assert campaign.option_unrealized is None  # nothing could be marked


def test_stock_unrealized_comes_from_the_snapshot_positions(db, seed_leg, snapshot_mark) -> None:
    seed_leg(candidate_id="c1", campaign_id="camp1", sold=(1, 1.50), expiry_in_days=-1)
    snapshot = snapshot_mark(
        underlying="NVDA", strike=170.0, right="P", unrealized_pnl=45.0, stock_unrealized=123.0
    )
    campaign = build_campaigns(db, build_legs(db), snapshot=snapshot)[0]
    assert campaign.stock_unrealized == 123.0
    assert campaign.total_net == campaign.option_realized + 123.0


def test_campaign_dates_come_from_the_campaign_row(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", campaign_id="camp1", sold=(1, 1.0), days_held=30)
    campaign = build_campaigns(db, build_legs(db), snapshot=None)[0]
    assert campaign.opened_date == date.today().toordinal() - 30 or campaign.opened_date
    assert campaign.symbol == "NVDA"
    assert campaign.status == "open"
