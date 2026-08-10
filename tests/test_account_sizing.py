"""The regression class the suite lacked: what can this system actually trade?

1,088 tests asked "does the gate reject what it says it rejects" and never "given this
account and this universe, is the tradeable set non-empty and sane" — which is why D1 and
D2 both passed CI for months.
"""

from __future__ import annotations

import pytest

from scripts.capacity_report import build_report
from src.common.schemas import AccountSnapshot


def _account(net_liq: float, cash: float) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=net_liq,
        total_cash=cash,
        buying_power=cash,
        maintenance_margin=0.0,
        excess_liquidity=cash,
    )


PRICES = {"SPY": 660.0, "META": 700.0, "AAPL": 230.0, "XLF": 52.0, "SOFI": 18.0}
IVS = {"SPY": 13.5, "META": 35.0, "AAPL": 28.0, "XLF": 20.0, "SOFI": 60.0}


@pytest.mark.parametrize("net_liq,cash", [(50_000, 25_000), (300_000, 100_000), (1_000_000, 400_000)])
def test_tradeable_set_is_never_empty(net_liq, cash):
    rows = build_report(_account(net_liq, cash), [], list(PRICES), IVS, PRICES)
    tradeable = [r for r in rows if r.contracts >= 1]
    assert tradeable, f"no symbol tradeable at NLV={net_liq}"


def test_no_symbol_is_excluded_solely_for_share_price():
    """D1: META must be reachable at $300k; only cash may refuse it."""
    rows = build_report(_account(300_000, 100_000), [], list(PRICES), IVS, PRICES)
    by_symbol = {r.symbol: r for r in rows}
    meta = by_symbol["META"]
    if meta.contracts == 0:
        assert meta.binding in {"cash", "csp_budget"}, (
            f"META refused for {meta.binding!r}, which is not an affordability reason"
        )


def test_low_iv_names_are_reachable_at_a_large_account():
    """D2: the defensive diversifiers must be sizeable when capital allows."""
    rows = build_report(_account(1_000_000, 400_000), [], list(PRICES), IVS, PRICES)
    by_symbol = {r.symbol: r for r in rows}
    assert by_symbol["SPY"].contracts >= 1
    assert by_symbol["XLF"].contracts >= 1


def test_report_reports_the_nlv_needed_for_one_lot():
    rows = build_report(_account(50_000, 25_000), [], ["META"], IVS, PRICES)
    assert rows[0].nlv_needed_for_one > 50_000
