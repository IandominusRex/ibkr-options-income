"""Every number here is one an operator will act on. None of them may be invented."""

from __future__ import annotations

from datetime import date

import pytest

from src.reporting.pnl import build_legs


def test_an_open_leg_has_no_realized_pnl(db, seed_leg) -> None:
    """The single most valuable assertion in P4. An open leg has a mark, not a result."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=30)
    leg = build_legs(db)[0]
    assert leg.net_pnl is None
    assert leg.outcome.value == "still_open"


def test_a_bought_back_leg_nets_credit_minus_debit_minus_commissions(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(2, 1.50, 1.30), bought=(2, 0.40, 1.30), expiry_in_days=30)
    leg = build_legs(db)[0]
    assert leg.credit == 300.0
    assert leg.debit == 80.0
    assert leg.commissions == pytest.approx(2.60)
    assert leg.net_pnl == pytest.approx(300.0 - 80.0 - 2.60)


def test_a_sold_and_expired_leg_keeps_its_premium(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 2.40, 1.30), expiry_in_days=-1)
    leg = build_legs(db)[0]
    assert leg.outcome.value == "expired_worthless"
    assert leg.net_pnl == pytest.approx(240.0 - 1.30)


def test_a_leg_whose_candidate_was_pruned_still_appears(db, seed_leg) -> None:
    """Fills survive pruning. A total that silently loses a row is the worse failure."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=-1, prune_candidate=True)
    legs = build_legs(db)
    assert len(legs) == 1
    assert legs[0].candidate_id == "c1"


def test_assignment_is_read_from_the_campaign_not_recomputed(db, seed_leg, set_campaign) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=-1, campaign_id="camp1")
    assert build_legs(db)[0].outcome.value == "expired_worthless"

    set_campaign("camp1", assigned=True)
    assert build_legs(db)[0].outcome.value == "assigned"


def test_roc_is_none_when_collateral_is_unknown(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=-1, strike=None)
    assert build_legs(db)[0].roc_pct is None


def test_roc_is_credit_over_collateral_when_known(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 2.40, 1.30), expiry_in_days=-1, strike=170.0)
    leg = build_legs(db)[0]
    assert leg.roc_pct == pytest.approx(240.0 / (170.0 * 1 * 100) * 100)


def test_annualized_is_none_for_a_same_day_leg(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.50), bought=(1, 0.20), days_held=0)
    assert build_legs(db)[0].annualized_pct is None


def test_annualized_is_computed_for_a_multi_day_leg(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 2.40, 1.30), expiry_in_days=-1, days_held=30)
    leg = build_legs(db)[0]
    assert leg.annualized_pct is not None
    assert leg.annualized_pct > 0


def test_paper_and_live_can_be_filtered_apart(db, seed_leg) -> None:
    seed_leg(candidate_id="paper", sold=(1, 1.0), is_live=False)
    seed_leg(candidate_id="live", sold=(1, 1.0), is_live=True)
    assert {leg.candidate_id for leg in build_legs(db, include_live=False)} == {"paper"}
    assert {leg.candidate_id for leg in build_legs(db, include_paper=False)} == {"live"}


def test_symbol_filters_on_the_underlying(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.0), symbol="NVDA")
    seed_leg(candidate_id="c2", sold=(1, 1.0), symbol="AAPL")
    assert {leg.candidate_id for leg in build_legs(db, symbol="NVDA")} == {"c1"}


def test_since_filters_on_the_opening_fill_date(db, seed_leg) -> None:
    seed_leg(candidate_id="old", sold=(1, 1.0), days_held=30)  # opened 30d ago
    seed_leg(candidate_id="new", sold=(1, 1.0), days_held=1)  # opened yesterday
    from datetime import timedelta

    cutoff = date.today() - timedelta(days=2)
    assert {leg.candidate_id for leg in build_legs(db, since=cutoff)} == {"new"}


def test_a_candidate_with_no_fills_is_not_a_leg(db, seed_candidate_only) -> None:
    seed_candidate_only("c1")
    assert build_legs(db) == []


def test_a_leg_with_a_null_commission_flags_incomplete(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.50, None), bought=(1, 0.40, 0.65))
    leg = build_legs(db)[0]
    assert leg.commissions_complete is False
    assert leg.commissions == pytest.approx(0.65)


def test_contract_detail_comes_from_the_candidate_row(db, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.50), strategy="covered_call", right="C", strike=190.0)
    leg = build_legs(db)[0]
    assert leg.strategy.value == "covered_call"
    assert leg.right.value == "C"
    assert leg.strike == 190.0


def test_a_pruned_candidates_leg_carries_what_the_fill_knows_and_nulls_the_rest(db, seed_leg):
    """A pruned candidate has unknown strike/expiry, but the fills' dollars are real."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=-1, prune_candidate=True)
    leg = build_legs(db)[0]
    assert leg.credit == pytest.approx(150.0)
    assert leg.strike == 0.0  # unknown — the fill knows no strike
    assert leg.campaign_id is None


def test_legs_are_newest_first(db, seed_leg) -> None:
    seed_leg(candidate_id="older", sold=(1, 1.0), days_held=30)
    seed_leg(candidate_id="newer", sold=(1, 1.0), days_held=1)
    assert [leg.candidate_id for leg in build_legs(db)] == ["newer", "older"]


def test_unrealized_pnl_is_always_none_from_build_legs(db, seed_leg) -> None:
    """build_legs takes no snapshot; the mark is Task 4.4's job, and only for open legs."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=30)
    seed_leg(candidate_id="c2", sold=(1, 1.50), bought=(1, 0.40), expiry_in_days=30)
    for leg in build_legs(db):
        assert leg.unrealized_pnl is None
