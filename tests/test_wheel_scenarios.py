"""The wheel-scenario suite (P3-P4 M4 Task 4.7).

Every expected number here is written out by hand — credit, debit, commissions, totals.
A test that computes its expectation the same way the code does proves nothing.

Scenario shape: seed fills + campaigns through the shared conftest fixtures, then assert
on build_legs / build_campaigns / build_summary output with literal numbers.
"""

from __future__ import annotations

import pytest

from src.reporting.pnl import build_campaigns, build_legs, build_summary


def test_scenario_1_a_csp_that_expires_worthless(db, seed_leg) -> None:
    """Sell one NVDA 170 put for 2.40, commission 1.30, 30 DTE, expires worthless."""
    seed_leg(candidate_id="csp1", sold=(1, 2.40, 1.30), expiry_in_days=-1, strike=170.0)

    legs = build_legs(db)
    assert len(legs) == 1
    leg = legs[0]
    assert leg.credit == 240.00
    assert leg.debit == 0.0
    assert leg.commissions == 1.30
    assert leg.net_pnl == 238.70  # 240.00 − 1.30, written out
    assert leg.outcome.value == "expired_worthless"
    assert leg.roc_pct == 240.0 / 17000.0 * 100  # ≈ 1.4118 — credit over collateral
    assert leg.commissions_complete is True


def test_scenario_2_the_full_wheel(db, seed_leg) -> None:
    """CSP assigned, two covered calls, the second called away — three option legs + stock."""
    # Leg 1: CSP on NVDA, sold for 2.40 (commission 1.30), expired and assigned.
    seed_leg(
        candidate_id="csp",
        sold=(1, 2.40, 1.30),
        expiry_in_days=-40,
        campaign_id="wheel",
        strike=170.0,
        strategy="cash_secured_put",
        right="P",
    )
    # Leg 2: first CC, sold for 1.80 (commission 1.30), bought back for 0.30 (commission 1.30).
    seed_leg(
        candidate_id="cc1",
        sold=(1, 1.80, 1.30),
        bought=(1, 0.30, 1.30),
        expiry_in_days=-20,
        campaign_id="wheel",
        strike=175.0,
        strategy="covered_call",
        right="C",
    )
    # Leg 3: second CC, sold for 1.20 (commission 1.30), called away (assigned at expiry).
    seed_leg(
        candidate_id="cc2",
        sold=(1, 1.20, 1.30),
        expiry_in_days=-5,
        campaign_id="wheel",
        strike=180.0,
        strategy="covered_call",
        right="C",
    )

    from src.storage.models import CampaignRow

    with db() as s:
        row = s.query(CampaignRow).one()
        row.assigned = True
        row.realized_stock_pnl = 1000.0
        row.adjusted_cost_basis = 167.60

    legs = build_legs(db)
    assert len(legs) == 3

    campaigns = build_campaigns(db, legs, snapshot=None)
    assert len(campaigns) == 1
    campaign = campaigns[0]

    # Hand-computed option legs:
    #   csp:  240.00 − 1.30 = 238.70   (assigned — premium kept)
    #   cc1:  180.00 − 30.00 − 2.60 = 147.40
    #   cc2:  120.00 − 1.30 = 118.70   (called away — premium kept)
    assert campaign.option_realized == pytest.approx(238.70 + 147.40 + 118.70)
    assert campaign.option_realized == pytest.approx(504.80)
    assert campaign.assigned is True
    assert campaign.adjusted_cost_basis == 167.60
    assert campaign.stock_realized == 1000.0
    assert campaign.total_net == pytest.approx(504.80 + 1000.0)
    assert len(campaign.legs) == 3


def test_scenario_3_a_roll_chain(db, seed_leg) -> None:
    """Open, buy back at a debit, new leg at a credit the same day, held to expiry: two legs."""
    # Leg 1: opened, bought back for a 0.90 debit (commissions 1.10 + 0.90).
    seed_leg(
        candidate_id="orig",
        sold=(1, 1.50, 1.10),
        bought=(1, 0.90, 0.90),
        expiry_in_days=-10,
        campaign_id="chain",
        strike=170.0,
    )
    # Leg 2: the new leg opened the same day for 1.60, held to expiry (commission 1.20).
    seed_leg(
        candidate_id="rolled",
        sold=(1, 1.60, 1.20),
        expiry_in_days=-10,
        campaign_id="chain",
        strike=172.5,
    )

    legs = build_legs(db)
    assert len(legs) == 2  # two legs, not one — the roll is two positions in the ledger
    by_id = {leg.candidate_id: leg for leg in legs}

    # Hand-computed: orig = 150 − 90 − 2.00 = 58.00; rolled = 160 − 1.20 = 158.80.
    assert by_id["orig"].net_pnl == pytest.approx(150.0 - 90.0 - 1.10 - 0.90)
    assert by_id["orig"].net_pnl == pytest.approx(58.00)
    assert by_id["rolled"].net_pnl == pytest.approx(160.0 - 1.20)
    assert by_id["rolled"].net_pnl == pytest.approx(158.80)

    campaigns = build_campaigns(db, legs, snapshot=None)
    assert len(campaigns) == 1
    campaign = campaigns[0]
    assert len(campaign.legs) == 2
    assert campaign.option_realized == pytest.approx(58.00 + 158.80)
    assert campaign.option_realized == pytest.approx(216.80)

    # And the first leg is negative only if the debit exceeds the credit — here it does not,
    # but the assertion that matters is that the two legs are independent positions.


def test_scenario_4_a_leg_with_no_commission_data(db, seed_leg) -> None:
    seed_leg(candidate_id="nocomm", sold=(1, 2.00, None), expiry_in_days=-1, strike=170.0)

    legs = build_legs(db)
    assert len(legs) == 1
    leg = legs[0]
    assert leg.commissions == 0.0
    assert leg.commissions_complete is False
    assert leg.net_pnl == pytest.approx(200.0)  # gross — the UI must say so

    summary = build_summary(legs, [])
    assert summary.commissions_complete is False


def test_scenario_5_paper_and_live_side_by_side(db, seed_leg) -> None:
    seed_leg(candidate_id="paper", sold=(1, 1.50, 1.30), expiry_in_days=-1, is_live=False)
    seed_leg(candidate_id="live", sold=(1, 3.00, 1.30), expiry_in_days=-1, is_live=True)

    both = build_legs(db)
    assert {leg.candidate_id for leg in both} == {"paper", "live"}

    with pytest.raises(ValueError):
        build_summary(both, [])

    paper_summary = build_summary(build_legs(db, include_live=False), [])
    live_summary = build_summary(build_legs(db, include_paper=False), [])
    paper_total = paper_summary.realized_total  # 150 − 1.30 = 148.70
    live_total = live_summary.realized_total  # 300 − 1.30 = 298.70
    assert paper_total == pytest.approx(148.70)
    assert live_total == pytest.approx(298.70)
    # Neither filtered total equals their sum — and mixing is refused, not summed.
    assert paper_total != live_total
    assert paper_total + live_total == pytest.approx(447.40)
    assert not any(total == pytest.approx(447.40) for total in (paper_total, live_total))


# ------------------------------------------------------------------------- #
# Cross-checks against the existing machinery
# ------------------------------------------------------------------------- #


def test_the_ledger_and_the_reporting_layer_agree_on_every_closed_trade(
    db,
    seed_leg,
    seed_wheel_ledger,
) -> None:
    """Task 4.1's whole point: one accounting rule, so these cannot disagree."""
    seed_wheel_ledger()
    from src.claude.eval.reconcile import reconcile

    reconcile()

    for leg in build_legs(db):
        if leg.net_pnl is None:
            continue
        ledger_row = _ledger_row_for(db, leg.candidate_id)
        if ledger_row is None or ledger_row.realized_pnl is None:
            continue
        assert leg.net_pnl == pytest.approx(ledger_row.realized_pnl)
        assert leg.outcome.value == ledger_row.outcome


def test_the_campaign_rollup_and_the_leg_sum_agree(db, seed_leg) -> None:
    """Both are rolled up from FillRow, so they must reconcile — but not naively.

    campaigns.net_premium is GROSS of commissions (pinned by M0 Task 0.4); PnlLeg.net_pnl is
    NET of them. Compare like with like: sum the legs' credit - debit, before commissions.
    A test that compared net_pnl to net_premium would fail by exactly the commission total
    and tell you nothing about whether the two rollups agree.
    """
    seed_leg(candidate_id="c1", sold=(1, 2.00, 0.65), bought=(1, 0.50, 0.65), campaign_id="camp1")
    from src.storage.campaigns import attach_fill_to_campaign

    # The fixture seeded rows directly; drive the real rollup so net_premium is honest.
    attach_fill_to_campaign(
        symbol="NVDA",
        candidate_id="c1",
        strategy="cash_secured_put",
        action="SELL",
        avg_price=2.00,
        filled_qty=1,
    )
    attach_fill_to_campaign(
        symbol="NVDA",
        candidate_id="c1",
        strategy="cash_secured_put",
        action="BUY",
        avg_price=0.50,
        filled_qty=1,
    )

    from src.storage.campaigns import load_campaigns

    legs = build_legs(db)
    assert len(legs) == 1
    gross = legs[0].credit - legs[0].debit
    stored = load_campaigns()[0]
    assert gross == pytest.approx(stored["net_premium"])


def test_the_gross_and_net_views_differ_by_exactly_the_commissions(db, seed_leg) -> None:
    """Makes the relationship explicit rather than leaving it as a known discrepancy."""
    seed_leg(candidate_id="c1", sold=(1, 2.00, 0.65), bought=(1, 0.50, 0.65))
    legs = [leg for leg in build_legs(db) if leg.net_pnl is not None]
    gross = sum(leg.credit - leg.debit for leg in legs)
    net = sum(leg.net_pnl for leg in legs)  # type: ignore[misc]
    assert gross - net == pytest.approx(sum(leg.commissions for leg in legs))


def _ledger_row_for(db, candidate_id: str):
    from src.storage.models import VerdictLedgerRow

    with db() as s:
        return (
            s.query(VerdictLedgerRow)
            .filter(VerdictLedgerRow.candidate_id == candidate_id)
            .one_or_none()
        )
