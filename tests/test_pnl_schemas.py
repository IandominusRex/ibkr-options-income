"""The P&L schemas (P3-P4 M4 Task 4.2): one leg, one campaign, one summary, one curve.

Round-trips, nullability, and the "None means unknown" honesty rules.
"""

from __future__ import annotations

import copy
from datetime import date, datetime

import pytest

from src.common.schemas import (
    CampaignPnl,
    EquityCurve,
    EquityPoint,
    PnlBucket,
    PnlLeg,
    PnlSummary,
)


def _leg(**overrides: object) -> PnlLeg:
    """A minimal valid leg; tests override what they assert on."""
    base = dict(
        candidate_id="c1",
        symbol="NVDA 241016C00170000",
        underlying="NVDA",
        strategy="cash_secured_put",
        right="P",
        strike=170.0,
        expiry=date(2026, 10, 16),
        contracts=1,
        opened_at=datetime(2026, 9, 16),
        credit=240.0,
        debit=0.0,
        commissions=1.30,
        commissions_complete=True,
        days_held=30,
        outcome="expired_worthless",
        is_live=False,
    )
    return PnlLeg(**{**base, **overrides})  # type: ignore[arg-type]


def _closed_leg(**overrides: object) -> PnlLeg:
    return _leg(
        closed_at=datetime(2026, 10, 17),
        net_pnl=238.70,
        roc_pct=240.0 / 17000.0 * 100,
        annualized_pct=30.0,
        **overrides,
    )


def test_pnl_leg_round_trips_through_json() -> None:
    leg = _closed_leg()
    dumped = leg.model_dump(mode="json")
    assert PnlLeg.model_validate(dumped) == leg


def test_campaign_pnl_round_trips_through_json() -> None:
    campaign = CampaignPnl(
        campaign_id="camp1",
        symbol="NVDA",
        status="open",
        opened_date=date(2026, 9, 16),
        legs=[_closed_leg()],
        option_realized=238.70,
        stock_unrealized=12.5,
    )
    assert CampaignPnl.model_validate(campaign.model_dump(mode="json")) == campaign


def test_pnl_bucket_round_trips_through_json() -> None:
    bucket = PnlBucket(
        label="cash_secured_put",
        n_closed=3,
        realized=700.0,
        win_rate=2 / 3,
        mean_days_held=21.0,
        mean_roc_pct=1.4,
    )
    assert PnlBucket.model_validate(bucket.model_dump(mode="json")) == bucket


def test_pnl_summary_round_trips_through_json() -> None:
    summary = PnlSummary(
        realized_total=238.70,
        unrealized_total=None,
        commissions_complete=True,
        n_open=1,
        n_closed=1,
        win_rate=1.0,
        by_strategy=[
            PnlBucket(label="cash_secured_put", n_closed=1, realized=238.70, win_rate=1.0)
        ],
        best=_closed_leg(),
        worst=_leg(
            candidate_id="c2",
            credit=100.0,
            outcome="closed_early",
            net_pnl=-40.0,
            closed_at=datetime(2026, 10, 2),
        ),
    )
    assert PnlSummary.model_validate(summary.model_dump(mode="json")) == summary


def test_equity_point_round_trips_through_json() -> None:
    point = EquityPoint(
        entry_date=date(2026, 9, 16),
        net_liquidation=150_000.0,
        unrealized_pnl=120.0,
        cumulative_realized=238.70,
        premium_cashflow=238.70,
    )
    assert EquityPoint.model_validate(point.model_dump(mode="json")) == point


def test_equity_curve_round_trips_through_json() -> None:
    curve = EquityCurve(
        points=[
            EquityPoint(entry_date=date(2026, 9, 16), cumulative_realized=0.0),
            EquityPoint(entry_date=date(2026, 9, 17), cumulative_realized=238.70),
        ],
        gaps=[date(2026, 9, 16)],
        starts_at=date(2026, 9, 16),
    )
    assert EquityCurve.model_validate(curve.model_dump(mode="json")) == curve


def test_an_open_leg_keeps_net_pnl_none_with_no_validator_defaulting_it() -> None:
    leg = _leg()
    assert leg.net_pnl is None
    # And it survives a round trip — nothing "fixed" it to 0.0 in either direction.
    assert PnlLeg.model_validate(leg.model_dump(mode="json")).net_pnl is None


def test_a_zero_closed_bucket_leaves_win_rate_none() -> None:
    assert PnlBucket(label="cash_secured_put", n_closed=0, realized=0.0).win_rate is None


def test_an_empty_equity_curve_is_valid_and_starts_nowhere() -> None:
    curve = EquityCurve()
    assert curve.points == []
    assert curve.gaps == []
    assert curve.starts_at is None


def test_model_defs_are_not_shared_between_instances() -> None:
    """default_factory, not a shared mutable default — two campaigns' legs are independent."""
    a, b = (
        CampaignPnl(campaign_id="a", symbol="X", status="open", opened_date=date(2026, 1, 1)),
        CampaignPnl(campaign_id="b", symbol="Y", status="open", opened_date=date(2026, 1, 1)),
    )
    a.legs.append(_closed_leg())
    assert b.legs == []


def test_deep_copy_of_a_leg_is_still_valid() -> None:
    """Sanity for the reporting layer's internal copies — a leg carries no ORM identity."""
    leg = _closed_leg()
    assert copy.deepcopy(leg) == leg


@pytest.mark.parametrize(
    "model", [PnlLeg, CampaignPnl, PnlBucket, PnlSummary, EquityPoint, EquityCurve]
)
def test_models_reject_wrong_types(model: type) -> None:
    """Pydantic is the boundary: garbage in is a ValidationError, never a silent pass."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        # Every model requires at least this much; a string where a date/float belongs raises.
        if model is PnlLeg:
            model(
                candidate_id=1,
                symbol=[],
                underlying=2,
                strategy="cash_secured_put",
                right="P",
                strike="not-a-float",
                expiry="not-a-date",
                contracts="x",
                opened_at="nope",
                credit="x",
                debit="x",
                commissions="x",
                commissions_complete="maybe",
                days_held="x",
                outcome="still_open",
                is_live="no",
            )
        elif model is CampaignPnl:
            model(campaign_id=[], symbol={}, status=123, opened_date="not-a-date")
        elif model is PnlBucket:
            model(label=1, n_closed="x", realized="y")
        elif model is PnlSummary:
            model(realized_total="x", commissions_complete="maybe", n_open="x", n_closed="y")
        elif model is EquityPoint:
            model(entry_date="not-a-date", cumulative_realized="x")
        else:  # EquityCurve
            model(points="not-a-list", gaps=1, starts_at=2)
