"""One accounting rule, in a package the trading path cannot import."""

from __future__ import annotations

from datetime import date

import pytest

from src.common.schemas import VerdictOutcome
from src.reporting.legs import OPTION_MULTIPLIER, classify_outcome, fill_economics
from src.storage.models import ApprovalRow, FillRow, OrderRow


def _sell(qty: float, price: float, commission: float | None = 1.0) -> FillRow:
    return FillRow(
        candidate_id="c1",
        order_id=1,
        action="SELL",
        filled_qty=qty,
        avg_price=price,
        commission=commission,
    )


def _buy(qty: float, price: float, commission: float | None = 1.0) -> FillRow:
    return FillRow(
        candidate_id="c1",
        order_id=1,
        action="BUY",
        filled_qty=qty,
        avg_price=price,
        commission=commission,
    )


def test_credit_and_debit_are_dollars_not_per_share() -> None:
    econ = fill_economics([_sell(2, 1.50), _buy(2, 0.40)])
    assert econ.credit == 2 * 1.50 * OPTION_MULTIPLIER
    assert econ.debit == 2 * 0.40 * OPTION_MULTIPLIER
    assert econ.entry_premium == 1.50
    assert econ.entry_qty == 2


def test_a_null_commission_is_summed_as_zero_and_flagged() -> None:
    """The figure stays usable; the UI must be able to say it is gross."""
    econ = fill_economics([_sell(1, 1.00, commission=None), _buy(1, 0.20, commission=0.65)])
    assert econ.commissions == 0.65
    assert econ.commissions_complete is False


def test_complete_commissions_are_flagged_complete() -> None:
    econ = fill_economics([_sell(1, 1.00, commission=0.65)])
    assert econ.commissions_complete is True


def test_a_bought_back_leg_is_closed_early() -> None:
    out = classify_outcome(
        "c1",
        [_sell(1, 1.50), _buy(1, 0.40)],
        None,
        None,
        date(2026, 10, 16),
        date(2026, 10, 1),
        assigned=False,
    )
    assert out.outcome is VerdictOutcome.CLOSED_EARLY
    assert out.realized_pnl == pytest.approx(150.0 - 40.0 - 2.0)


def test_a_past_expiry_short_with_no_buy_expired_worthless() -> None:
    out = classify_outcome(
        "c1", [_sell(1, 1.50)], None, None, date(2026, 10, 16), date(2026, 10, 17), assigned=False
    )
    assert out.outcome is VerdictOutcome.EXPIRED_WORTHLESS


def test_an_assigned_flag_changes_the_outcome_not_the_arithmetic() -> None:
    kw = dict(
        fills=[_sell(1, 1.50)],
        approval=None,
        order=None,
        expiry=date(2026, 10, 16),
        today=date(2026, 10, 17),
    )
    expired = classify_outcome("c1", assigned=False, **kw)
    assigned = classify_outcome("c1", assigned=True, **kw)
    assert assigned.outcome is VerdictOutcome.ASSIGNED
    assert assigned.realized_pnl == expired.realized_pnl


def test_an_open_leg_has_no_realized_pnl() -> None:
    out = classify_outcome(
        "c1", [_sell(1, 1.50)], None, None, date(2026, 12, 18), date(2026, 10, 1), assigned=False
    )
    assert out.outcome is VerdictOutcome.STILL_OPEN
    assert out.realized_pnl is None


def test_a_rejected_approval_is_user_rejected() -> None:
    out = classify_outcome(
        "c1",
        [],
        ApprovalRow(status="rejected"),
        None,
        date(2026, 12, 18),
        date(2026, 10, 1),
        assigned=False,
    )
    assert out.outcome is VerdictOutcome.USER_REJECTED
    assert out.filled is False


def test_a_rejected_order_is_risk_rejected() -> None:
    out = classify_outcome(
        "c1",
        [],
        None,
        OrderRow(state="rejected"),
        date(2026, 12, 18),
        date(2026, 10, 1),
        assigned=False,
    )
    assert out.outcome is VerdictOutcome.RISK_REJECTED


def test_an_unfilled_past_expiry_candidate_is_not_filled() -> None:
    out = classify_outcome(
        "c1", [], None, None, date(2026, 10, 16), date(2026, 10, 17), assigned=False
    )
    assert out.outcome is VerdictOutcome.NOT_FILLED
