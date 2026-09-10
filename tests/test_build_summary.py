"""The aggregator: pure, and the one place in src/reporting/ that raises."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.common.schemas import CampaignPnl, PnlLeg
from src.reporting.pnl import build_summary


def _leg(candidate_id: str, *, net_pnl: float | None, is_live: bool = False,
         strategy: str = "cash_secured_put", symbol: str = "NVDA",
         commissions_complete: bool = True, credit: float = 100.0, debit: float = 0.0,
         commissions: float = 1.30) -> PnlLeg:
    return PnlLeg(
        candidate_id=candidate_id,
        symbol=f"{symbol} 261016P00170000",
        underlying=symbol,
        strategy=strategy,  # type: ignore[arg-type]
        right="P",
        strike=170.0,
        expiry=date(2026, 10, 16),
        contracts=1,
        opened_at=datetime(2026, 9, 16),
        closed_at=datetime(2026, 10, 2) if net_pnl is not None else None,
        credit=credit,
        debit=debit,
        commissions=commissions,
        commissions_complete=commissions_complete,
        net_pnl=net_pnl,
        days_held=16 if net_pnl is not None else 0,
        roc_pct=1.0 if net_pnl is not None else None,
        outcome="closed_early" if net_pnl is not None else "still_open",  # type: ignore[arg-type]
        is_live=is_live,
    )


def test_mixing_paper_and_live_raises_rather_than_totalling() -> None:
    """A total across both is not a number. Refuse rather than return one."""
    paper_leg = _leg("paper", net_pnl=100.0, is_live=False)
    live_leg = _leg("live", net_pnl=-50.0, is_live=True)
    with pytest.raises(ValueError):
        build_summary([paper_leg, live_leg], [])


def test_win_rate_is_unknown_not_zero_with_nothing_closed() -> None:
    open_leg = _leg("c1", net_pnl=None)
    assert build_summary([open_leg], []).win_rate is None


def test_realized_total_sums_closed_legs_only() -> None:
    closed_a = _leg("a", net_pnl=100.0)
    closed_b = _leg("b", net_pnl=-40.0)
    open_leg = _leg("c", net_pnl=None)
    summary = build_summary([closed_a, closed_b, open_leg], [])
    assert summary.realized_total == pytest.approx(60.0)
    assert summary.n_closed == 2
    assert summary.n_open == 1


def test_win_rate_counts_wins_over_closed() -> None:
    summary = build_summary(
        [_leg("a", net_pnl=100.0), _leg("b", net_pnl=-40.0), _leg("c", net_pnl=5.0)],
        [],
    )
    assert summary.win_rate == pytest.approx(2 / 3)


def test_one_incomplete_leg_makes_the_summary_gross() -> None:
    complete = _leg("a", net_pnl=100.0, commissions_complete=True)
    incomplete = _leg("b", net_pnl=100.0, commissions_complete=False)
    assert build_summary([complete, incomplete], []).commissions_complete is False
    assert build_summary([complete], []).commissions_complete is True


def test_best_and_worst_are_closed_legs_never_open_ones() -> None:
    best = _leg("best", net_pnl=300.0)
    worst = _leg("worst", net_pnl=-100.0)
    open_leg = _leg("open", net_pnl=None)
    summary = build_summary([best, worst, open_leg], [])
    assert summary.best is not None and summary.best.candidate_id == "best"
    assert summary.worst is not None and summary.worst.candidate_id == "worst"


def test_best_and_worst_are_none_with_an_empty_leg_list() -> None:
    summary = build_summary([], [])
    assert summary.realized_total == 0.0
    assert summary.n_open == 0
    assert summary.n_closed == 0
    assert summary.win_rate is None
    assert summary.best is None
    assert summary.worst is None
    assert summary.by_strategy == []
    assert summary.by_symbol == []


def test_by_strategy_and_by_symbol_order_by_realized_descending() -> None:
    csp = _leg("a", net_pnl=100.0, strategy="cash_secured_put", symbol="NVDA")
    cc = _leg("b", net_pnl=300.0, strategy="covered_call", symbol="AAPL")
    csp2 = _leg("c", net_pnl=50.0, strategy="cash_secured_put", symbol="NVDA")
    summary = build_summary([csp, cc, csp2], [])
    assert [b.label for b in summary.by_strategy] == ["covered_call", "cash_secured_put"]
    assert [b.label for b in summary.by_symbol] == ["AAPL", "NVDA"]
    csp_bucket = next(b for b in summary.by_strategy if b.label == "cash_secured_put")
    assert csp_bucket.realized == pytest.approx(150.0)
    assert csp_bucket.n_closed == 2
    assert csp_bucket.win_rate == pytest.approx(1.0)


def test_a_tie_breaks_by_label() -> None:
    a = _leg("a", net_pnl=100.0, symbol="ZZZ")
    b = _leg("b", net_pnl=100.0, symbol="AAA")
    summary = build_summary([a, b], [])
    assert [s.label for s in summary.by_symbol] == ["AAA", "ZZZ"]


def test_bucket_means_average_only_closed_legs() -> None:
    a = _leg("a", net_pnl=100.0, symbol="NVDA", strategy="covered_call")
    b = _leg("b", net_pnl=-40.0, symbol="NVDA", strategy="covered_call")
    o = _leg("c", net_pnl=None, symbol="NVDA", strategy="covered_call")
    summary = build_summary([a, b, o], [])
    bucket = summary.by_strategy[0]
    assert bucket.mean_days_held == pytest.approx(16.0)   # the closed legs only
    assert bucket.mean_roc_pct == pytest.approx(1.0)


def test_unrealized_total_sums_open_legs_when_present() -> None:
    # build_summary takes no snapshot; the only unrealised it can see is a leg's
    # already-populated unrealized_pnl (build_campaigns' marked copies).
    marked_open = _leg("c", net_pnl=None)
    marked_open = marked_open.model_copy(update={"unrealized_pnl": 45.0})
    summary = build_summary([marked_open, _leg("a", net_pnl=100.0)], [])
    assert summary.unrealized_total == pytest.approx(45.0)


def test_unrealized_total_is_none_when_no_leg_has_a_mark() -> None:
    summary = build_summary([_leg("a", net_pnl=100.0), _leg("o", net_pnl=None)], [])
    assert summary.unrealized_total is None


def test_campaigns_parameter_is_accepted_but_the_totals_come_from_legs() -> None:
    """A total can never disagree with the rows above it — legs are the source."""
    legs = [_leg("a", net_pnl=100.0)]
    campaign = CampaignPnl(
        campaign_id="camp1", symbol="NVDA", status="closed",
        opened_date=date(2026, 9, 16), legs=legs, option_realized=999.0,
    )
    summary = build_summary(legs, [campaign])
    assert summary.realized_total == pytest.approx(100.0)  # not 999.0
