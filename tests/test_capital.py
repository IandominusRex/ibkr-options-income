"""Unit tests for src/engine/capital.py — risk units, caps, and headroom sizing."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.common.market_hours import today_et
from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot
from src.engine.capital import (
    max_contracts,
    resolve_caps,
    risk_units,
    seed_budgets,
)

RISK = {
    "portfolio": {
        "cash_reserve_pct": 20.0,
        "cash_reserve_absolute": 10000,
        "max_csp_allocation_pct_of_deployable": 100.0,
        "max_risk_units_per_ticker_pct": 5.0,
        "max_risk_units_per_sector_pct": 25.0,
        "max_collateral_per_ticker_pct": 10.0,
        "max_large_positions": 1,
        "max_pct_per_ticker_large": 25.0,
    }
}


def _account(net_liq=300_000.0, cash=100_000.0):
    return AccountSnapshot(
        account="DU1",
        net_liquidation=net_liq,
        total_cash=cash,
        buying_power=cash,
        maintenance_margin=0.0,
        excess_liquidity=cash,
    )


def test_risk_units_scales_collateral_by_vol_and_horizon():
    # META-like: $65,000 collateral, 35% IV, 30 DTE -> 65000 * 0.35 * sqrt(30/365)
    assert risk_units(65_000.0, 35.0, 30) == pytest.approx(6520.0, abs=5.0)


def test_risk_units_makes_a_cheap_high_vol_position_comparable():
    # MARA-like: $15,000 collateral at 110% IV is NOT 4x smaller than META in risk terms.
    meta = risk_units(65_000.0, 35.0, 30)
    mara = risk_units(15_000.0, 110.0, 30)
    assert meta is not None and mara is not None
    assert 0.5 < mara / meta < 1.0


def test_risk_units_returns_none_without_iv():
    assert risk_units(65_000.0, None, 30) is None
    assert risk_units(65_000.0, 0.0, 30) is None


def test_resolve_caps_subtracts_reserve_before_the_csp_budget():
    caps = resolve_caps(_account(), RISK)
    # reserve = max(20% of 100k, 10k) = 20k -> deployable 80k, budget 100% of that
    assert caps.deployable_cash == pytest.approx(80_000.0)
    assert caps.max_csp_collateral == pytest.approx(80_000.0)


def test_resolve_caps_reserve_uses_the_absolute_floor_when_larger():
    caps = resolve_caps(_account(cash=20_000.0), RISK)
    # reserve = max(20% of 20k = 4k, 10k) = 10k -> deployable 10k
    assert caps.deployable_cash == pytest.approx(10_000.0)


def test_seed_budgets_charges_short_puts_at_strike_collateral():
    positions = [
        PositionSnapshot(
            symbol="AAPL  260918P00200000",
            sec_type="OPT",
            position=-2,
            avg_cost=500.0,
            right=OptionRight.PUT,
            strike=200.0,
            underlying="AAPL",
            market_value=-900.0,
        )
    ]
    budgets = seed_budgets(positions, lambda s: "tech")
    assert budgets.csp_collateral == pytest.approx(40_000.0)
    assert budgets.ticker_collateral["AAPL"] == pytest.approx(40_000.0)


def _short_put(
    symbol: str = "MARA",
    strike: float = 15.0,
    contracts: int = 50,
    days_out: int = 30,
) -> PositionSnapshot:
    """An existing short put: `contracts` lots at `strike`, expiring `days_out` days out."""
    return PositionSnapshot(
        symbol=f"{symbol} OPT",
        sec_type="OPT",
        position=-float(contracts),
        avg_cost=100.0,
        right=OptionRight.PUT,
        strike=strike,
        expiry=today_et() + timedelta(days=days_out),
        underlying=symbol,
        market_value=-2_000.0,
    )


def test_seed_budgets_charges_risk_units_when_an_iv_lookup_is_supplied():
    """The concentration caps are measured in risk units, so existing option positions have
    to be seeded in risk units too — otherwise every held position counts as zero against the
    per-ticker / per-sector cap on the (common) path where the candidate's own IV is known."""
    positions = [_short_put()]  # $75,000 collateral, 30 DTE
    budgets = seed_budgets(positions, lambda s: "crypto", lambda s: 70.0)
    # 75,000 x 0.70 x sqrt(30/365) = ~15,054 risk units
    assert budgets.ticker_risk["MARA"] == pytest.approx(15_054.0, abs=5.0)
    assert budgets.sector_risk["crypto"] == pytest.approx(15_054.0, abs=5.0)
    assert budgets.ticker_collateral["MARA"] == pytest.approx(75_000.0)


def test_seed_budgets_leaves_risk_units_unseeded_without_an_iv_lookup():
    """Omitting `iv_of` must preserve the previous behaviour exactly — the raw-collateral
    tally alone — for callers that cannot cheaply resolve IV (the order-approval re-gate,
    the single-ticker deep-dive)."""
    positions = [_short_put()]
    budgets = seed_budgets(positions, lambda s: "crypto")
    assert budgets.ticker_risk.get("MARA", 0.0) == 0.0
    assert budgets.sector_risk.get("crypto", 0.0) == 0.0
    assert budgets.ticker_collateral["MARA"] == pytest.approx(75_000.0)


def test_seed_budgets_skips_risk_units_when_iv_is_unresolvable():
    """An `iv_of` that returns None for this symbol is data-unavailable, not zero risk."""
    positions = [_short_put()]
    budgets = seed_budgets(positions, lambda s: "crypto", lambda s: None)
    assert budgets.ticker_risk.get("MARA", 0.0) == 0.0
    assert budgets.ticker_collateral["MARA"] == pytest.approx(75_000.0)


def test_seed_budgets_gives_stock_positions_no_risk_units():
    """Stock has no natural DTE, so it stays on the raw-collateral tally (deliberate)."""
    positions = [
        PositionSnapshot(
            symbol="AAPL",
            sec_type="STK",
            position=100.0,
            avg_cost=200.0,
            market_value=20_000.0,
        )
    ]
    budgets = seed_budgets(positions, lambda s: "tech", lambda s: 28.0)
    assert budgets.ticker_risk.get("AAPL", 0.0) == 0.0
    assert budgets.ticker_collateral["AAPL"] == pytest.approx(20_000.0)


def test_seed_budgets_skips_an_expired_option():
    """DTE <= 0 has no risk-unit meaning (sqrt of a non-positive horizon)."""
    positions = [_short_put(days_out=0)]
    budgets = seed_budgets(positions, lambda s: "crypto", lambda s: 70.0)
    assert budgets.ticker_risk.get("MARA", 0.0) == 0.0


def test_existing_position_consumes_the_new_candidates_ticker_risk_budget():
    """Regression (final-review Critical): an account already holding $75,000 of MARA short
    puts at 70% IV / 30 DTE is at ~15,054 risk units — over the $15,000 per-ticker cap (5% of
    $300k NLV) on its own. A further MARA lot must not fit. Before risk-unit seeding, the
    existing position charged `ticker_risk` nothing, so the sizer happily returned the full
    hard_max of 10 more lots."""
    caps = resolve_caps(_account(cash=300_000.0), RISK)
    positions = [_short_put()]

    seeded = seed_budgets(positions, lambda s: "crypto", lambda s: 70.0)
    n, binding = max_contracts(
        unit_collateral=1_500.0,
        current_iv=70.0,
        dte=30,
        symbol="MARA",
        sector="crypto",
        caps=caps,
        budgets=seeded,
        hard_max=10,
    )
    assert n == 0
    assert binding == "ticker_risk"

    # The same call with the position invisible to the risk-unit tallies is the bug's shape:
    # the sizer sees an empty per-ticker budget and grants the full hard_max.
    unseeded = seed_budgets(positions, lambda s: "crypto")
    n_blind, _ = max_contracts(
        unit_collateral=1_500.0,
        current_iv=70.0,
        dte=30,
        symbol="MARA",
        sector="crypto",
        caps=caps,
        budgets=unseeded,
        hard_max=10,
    )
    assert n_blind > n


def test_max_contracts_trims_to_the_binding_constraint_instead_of_rejecting():
    caps = resolve_caps(_account(), RISK)
    budgets = seed_budgets([], lambda s: "tech")
    # AAPL 230 strike -> $23,000/contract. Risk cap = 5% of 300k = $15,000 risk units.
    # One contract = 23000 * 0.28 * sqrt(30/365) = ~1,847 risk units, so risk is not binding;
    # cash (80k deployable) allows 3.
    n, binding = max_contracts(
        unit_collateral=23_000.0,
        current_iv=28.0,
        dte=30,
        symbol="AAPL",
        sector="tech",
        caps=caps,
        budgets=budgets,
        hard_max=10,
    )
    assert n == 3
    assert binding == "cash"


def test_max_contracts_allows_one_lot_of_a_high_priced_name():
    """A $65k META put must not be rejected merely for being expensive (D1)."""
    caps = resolve_caps(_account(), RISK)
    budgets = seed_budgets([], lambda s: "tech")
    n, _ = max_contracts(
        unit_collateral=65_000.0,
        current_iv=35.0,
        dte=30,
        symbol="META",
        sector="tech",
        caps=caps,
        budgets=budgets,
        hard_max=10,
    )
    assert n == 1


def test_max_contracts_consumes_the_large_slot_and_refuses_a_second():
    caps = resolve_caps(_account(), RISK)
    budgets = seed_budgets([], lambda s: "tech")
    budgets.large_slots_used = 1  # slot already taken
    n, binding = max_contracts(
        unit_collateral=65_000.0,  # 21.7% of net liq -> needs the large slot
        current_iv=35.0,
        dte=30,
        symbol="META",
        sector="tech",
        caps=caps,
        budgets=budgets,
        hard_max=10,
    )
    assert n == 0
    assert binding == "large_slot"


def test_max_contracts_falls_back_to_collateral_when_iv_is_missing():
    caps = resolve_caps(_account(), RISK)
    budgets = seed_budgets([], lambda s: "tech")
    # No IV -> stricter raw-collateral cap of 10% of 300k = $30,000
    n, binding = max_contracts(
        unit_collateral=23_000.0,
        current_iv=None,
        dte=30,
        symbol="AAPL",
        sector="tech",
        caps=caps,
        budgets=budgets,
        hard_max=10,
    )
    assert n == 1
    assert binding == "ticker_collateral"


def test_max_contracts_returns_zero_when_nothing_fits():
    caps = resolve_caps(_account(cash=5_000.0), RISK)
    budgets = seed_budgets([], lambda s: "tech")
    n, binding = max_contracts(
        unit_collateral=23_000.0,
        current_iv=28.0,
        dte=30,
        symbol="AAPL",
        sector="tech",
        caps=caps,
        budgets=budgets,
        hard_max=10,
    )
    assert n == 0
    assert binding == "cash"
