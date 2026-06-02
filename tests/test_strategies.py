"""Unit tests for strategy modules. No TWS, no live data — all canned fixtures."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    Regime,
    TechnicalStats,
)
from src.strategies._scoring import fundamental_score, make_candidate_id, technical_score
from src.strategies.cash_secured_put import generate_csp_candidates
from src.strategies.covered_call import generate_cc_candidates
from src.strategies.rolling import generate_roll_candidates

# Expiries within the [21, 45] DTE window; computed relative to today so tests
# stay green regardless of when they run.
#
# Spread/premium budget to clear ALL three gates for avg_cost=175 stock:
#   spread_pct < 10%  → (ask-bid)/mid < 0.10
#   roc_pct >= 1.0%   → premium >= 1.75
#   ann_yield >= 12%  → premium >= 175 * (12/100) * (34/365) ≈ 1.96
#
# Default bid=2.10 / ask=2.30 gives mid=2.20, spread_pct≈9.1%, roc≈1.26%, ann≈13.5%.

_TODAY = date.today()
_EXPIRY = _TODAY + timedelta(days=34)  # 34 DTE — mid of [21, 45] window
_EXPIRY_FAR = _TODAY + timedelta(days=42)  # 42 DTE — used as roll new-leg expiry
_EXPIRY_NEAR = _TODAY + timedelta(days=10)  # 10 DTE — triggers dte<=21 roll condition


# --------------------------------------------------------------------------- #
# Shared fixtures
# --------------------------------------------------------------------------- #


def _call_quote(
    strike: float = 200.0,
    delta: float = 0.28,
    bid: float = 2.10,
    ask: float = 2.30,
    volume: int = 500,
    oi: int = 2000,
    expiry: date = _EXPIRY,
) -> OptionQuote:
    return OptionQuote(
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=strike,
        expiry=expiry,
        bid=bid,
        ask=ask,
        volume=volume,
        open_interest=oi,
        iv=0.28,
        delta=delta,
    )


def _put_quote(
    strike: float = 170.0,
    delta: float = -0.25,
    bid: float = 2.10,
    ask: float = 2.30,
    volume: int = 500,
    oi: int = 2000,
    expiry: date = _EXPIRY,
) -> OptionQuote:
    return OptionQuote(
        underlying="AAPL",
        right=OptionRight.PUT,
        strike=strike,
        expiry=expiry,
        bid=bid,
        ask=ask,
        volume=volume,
        open_interest=oi,
        iv=0.28,
        delta=delta,
    )


def _long_stock(
    symbol: str = "AAPL", shares: float = 200.0, avg_cost: float = 175.0
) -> PositionSnapshot:
    return PositionSnapshot(symbol=symbol, sec_type="STK", position=shares, avg_cost=avg_cost)


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=100_000.0,
        total_cash=50_000.0,
        buying_power=80_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=70_000.0,
    )


def _iv(symbol: str = "AAPL", rank: float = 65.0) -> IVStats:
    return IVStats(symbol=symbol, current_iv=28.0, iv_rank=rank)


def _tech(
    symbol: str = "AAPL", price: float = 185.0, regime: Regime | None = None
) -> TechnicalStats:
    return TechnicalStats(symbol=symbol, price=price, rsi_14=55.0, regime=regime)


def _fund(quality: bool | None = True, dividend_safe: bool | None = None) -> FundamentalStats:
    return FundamentalStats(symbol="AAPL", quality_flag=quality, dividend_safe=dividend_safe)


# --------------------------------------------------------------------------- #
# _scoring helpers
# --------------------------------------------------------------------------- #


class TestScoringHelpers:
    def test_candidate_id_deterministic(self):
        id1 = make_candidate_id("covered_call", "AAPL", "C", 200.0, _EXPIRY)
        id2 = make_candidate_id("covered_call", "AAPL", "C", 200.0, _EXPIRY)
        assert id1 == id2
        assert len(id1) == 16

    def test_candidate_id_varies_by_strike(self):
        id1 = make_candidate_id("covered_call", "AAPL", "C", 200.0, _EXPIRY)
        id2 = make_candidate_id("covered_call", "AAPL", "C", 205.0, _EXPIRY)
        assert id1 != id2

    def test_fundamental_score_quality_true(self):
        assert fundamental_score(_fund(quality=True)) == 70.0

    def test_fundamental_score_quality_false(self):
        assert fundamental_score(_fund(quality=False)) == 20.0

    def test_fundamental_score_quality_none(self):
        assert fundamental_score(_fund(quality=None)) == 50.0

    def test_fundamental_score_dividend_safe_bonus(self):
        assert fundamental_score(_fund(quality=True, dividend_safe=True)) == 85.0

    def test_technical_score_bullish_call(self):
        q = _call_quote()
        score = technical_score(q, _tech(regime=Regime.BULLISH))
        assert score == pytest.approx(60.0)  # 50 + 10 for bullish+call

    def test_technical_score_bullish_put(self):
        q = _put_quote()
        score = technical_score(q, _tech(regime=Regime.BULLISH))
        assert score == pytest.approx(45.0)  # 50 - 5

    def test_technical_score_clamped(self):
        q = _call_quote()
        score = technical_score(q, _tech())
        assert 0.0 <= score <= 100.0


# --------------------------------------------------------------------------- #
# Covered call tests
# --------------------------------------------------------------------------- #


class TestCoveredCall:
    def test_empty_quotes_returns_empty(self):
        result = generate_cc_candidates("AAPL", [], _long_stock(), _iv(), _tech(), _fund())
        assert result == []

    def test_short_position_returns_empty(self):
        short_pos = PositionSnapshot(symbol="AAPL", sec_type="STK", position=-100.0, avg_cost=175.0)
        result = generate_cc_candidates("AAPL", [_call_quote()], short_pos, _iv(), _tech(), _fund())
        assert result == []

    def test_zero_position_returns_empty(self):
        zero_pos = PositionSnapshot(symbol="AAPL", sec_type="STK", position=0.0, avg_cost=175.0)
        result = generate_cc_candidates("AAPL", [_call_quote()], zero_pos, _iv(), _tech(), _fund())
        assert result == []

    def test_less_than_100_shares_returns_empty(self):
        small_pos = PositionSnapshot(symbol="AAPL", sec_type="STK", position=50.0, avg_cost=175.0)
        result = generate_cc_candidates("AAPL", [_call_quote()], small_pos, _iv(), _tech(), _fund())
        assert result == []

    def test_contracts_count_200_shares(self):
        result = generate_cc_candidates(
            "AAPL", [_call_quote()], _long_stock(shares=200.0), _iv(), _tech(), _fund()
        )
        assert len(result) == 1
        assert result[0].contracts == 2

    def test_contracts_count_350_shares(self):
        result = generate_cc_candidates(
            "AAPL", [_call_quote()], _long_stock(shares=350.0), _iv(), _tech(), _fund()
        )
        assert len(result) == 1
        assert result[0].contracts == 3

    def test_breakeven_formula(self):
        avg_cost = 175.0
        quote = _call_quote()  # mid=2.20
        result = generate_cc_candidates(
            "AAPL", [quote], _long_stock(avg_cost=avg_cost), _iv(), _tech(), _fund()
        )
        assert len(result) == 1
        assert result[0].breakeven == pytest.approx(avg_cost - quote.mid, abs=1e-4)

    def test_annualized_yield_formula(self):
        avg_cost = 175.0
        quote = _call_quote()  # mid=2.20
        result = generate_cc_candidates(
            "AAPL", [quote], _long_stock(avg_cost=avg_cost), _iv(), _tech(), _fund()
        )
        assert len(result) == 1
        c = result[0]
        mid = quote.mid
        expected_roc = (mid / avg_cost) * 100
        expected_ann = expected_roc * (365 / c.dte)
        assert c.roc_pct == pytest.approx(expected_roc, abs=1e-3)
        assert c.annualized_yield_pct == pytest.approx(expected_ann, abs=1e-3)

    def test_collateral_is_cost_basis_per_contract(self):
        avg_cost = 175.0
        result = generate_cc_candidates(
            "AAPL", [_call_quote()], _long_stock(avg_cost=avg_cost), _iv(), _tech(), _fund()
        )
        assert len(result) == 1
        # _long_stock defaults to 200 shares → 2 contracts; collateral = avg_cost * contracts * 100
        expected_contracts = result[0].contracts
        assert result[0].collateral == pytest.approx(avg_cost * expected_contracts * 100)

    def test_filters_put_quotes(self):
        result = generate_cc_candidates(
            "AAPL", [_put_quote()], _long_stock(), _iv(), _tech(), _fund()
        )
        assert result == []

    def test_filters_out_of_delta_range(self):
        # delta=0.50 is above the 0.35 max
        quote = _call_quote(delta=0.50)
        result = generate_cc_candidates("AAPL", [quote], _long_stock(), _iv(), _tech(), _fund())
        assert result == []

    def test_filters_below_min_strike_vs_basis(self):
        # strike=170 < avg_cost=175 → rejected by min_strike_vs_basis=1.0
        quote = _call_quote(strike=170.0, delta=0.28)
        result = generate_cc_candidates(
            "AAPL", [quote], _long_stock(avg_cost=175.0), _iv(), _tech(), _fund()
        )
        assert result == []

    def test_income_gate_filters_low_yield(self):
        # bid=ask=0.01 → spread=0% passes liquidity, but roc_pct≈0.006% << 1.0% → filtered
        quote = _call_quote(bid=0.01, ask=0.01)
        result = generate_cc_candidates("AAPL", [quote], _long_stock(), _iv(), _tech(), _fund())
        assert result == []

    def test_sorted_by_roc_desc(self):
        # q1 mid=2.20 → roc≈1.26%; q2 mid=4.30 → roc≈2.46%
        q1 = _call_quote(strike=200.0, bid=2.10, ask=2.30, delta=0.28)
        q2 = _call_quote(strike=205.0, bid=4.10, ask=4.50, delta=0.25)
        result = generate_cc_candidates("AAPL", [q1, q2], _long_stock(), _iv(), _tech(), _fund())
        assert len(result) == 2
        assert result[0].roc_pct >= result[1].roc_pct

    def test_iv_rank_none_defaults_to_zero(self):
        result = generate_cc_candidates(
            "AAPL", [_call_quote()], _long_stock(), _iv(rank=None), _tech(), _fund()
        )
        assert len(result) == 1
        assert result[0].scores.iv_score == 0.0


# --------------------------------------------------------------------------- #
# Cash-secured put tests
# --------------------------------------------------------------------------- #


class TestCashSecuredPut:
    def test_symbol_not_in_would_own_returns_empty(self):
        # LABU is in indexes but not in would_own
        result = generate_csp_candidates(
            "LABU", [_put_quote()], _account(), _iv(), _tech(), _fund()
        )
        assert result == []

    def test_symbol_in_would_own_proceeds(self):
        result = generate_csp_candidates(
            "AAPL", [_put_quote()], _account(), _iv(), _tech(), _fund()
        )
        assert len(result) == 1

    def test_collateral_is_strike_times_contracts(self):
        strike = 170.0
        result = generate_csp_candidates(
            "AAPL", [_put_quote(strike=strike)], _account(), _iv(), _tech(), _fund()
        )
        assert len(result) == 1
        # collateral = strike * contracts * 100; contracts sized by buying power
        expected_contracts = result[0].contracts
        assert result[0].collateral == pytest.approx(strike * expected_contracts * 100)

    def test_contracts_sized_by_excess_liquidity(self):
        # CSPs size off ExcessLiquidity (post-margin cushion): excess_liquidity=70_000, strike=170
        # → cash_n = floor(70000 / (170*100)) = 4
        # → csp_budget_n = floor((100_000 * 0.60) / (170*100)) = 3
        # → contracts = min(10, 4, 3) = 3
        result = generate_csp_candidates(
            "AAPL", [_put_quote()], _account(), _iv(), _tech(), _fund()
        )
        assert len(result) == 1
        assert result[0].contracts == 3

    def test_filters_call_quotes(self):
        result = generate_csp_candidates(
            "AAPL", [_call_quote()], _account(), _iv(), _tech(), _fund()
        )
        assert result == []

    def test_filters_high_abs_delta(self):
        # abs(delta)=0.50 exceeds the 0.30 max
        quote = _put_quote(delta=-0.50)
        result = generate_csp_candidates("AAPL", [quote], _account(), _iv(), _tech(), _fund())
        assert result == []

    def test_filters_low_abs_delta(self):
        # abs(delta)=0.05 is below the 0.15 min
        quote = _put_quote(delta=-0.05)
        result = generate_csp_candidates("AAPL", [quote], _account(), _iv(), _tech(), _fund())
        assert result == []

    def test_breakeven_formula(self):
        strike = 170.0
        quote = _put_quote(strike=strike)  # mid=2.20
        result = generate_csp_candidates("AAPL", [quote], _account(), _iv(), _tech(), _fund())
        assert len(result) == 1
        assert result[0].breakeven == pytest.approx(strike - quote.mid, abs=1e-4)

    def test_income_gate_filters_low_yield(self):
        # bid=ask=0.01 → roc_pct≈0.006% << 1.0% → filtered
        quote = _put_quote(bid=0.01, ask=0.01)
        result = generate_csp_candidates("AAPL", [quote], _account(), _iv(), _tech(), _fund())
        assert result == []

    def test_empty_quotes_returns_empty(self):
        result = generate_csp_candidates("AAPL", [], _account(), _iv(), _tech(), _fund())
        assert result == []

    def test_sorted_by_roc_desc(self):
        # q1 mid=2.20 → roc≈1.29%; q2 mid=4.30 → roc≈2.61%
        q1 = _put_quote(strike=170.0, bid=2.10, ask=2.30, delta=-0.25)
        q2 = _put_quote(strike=165.0, bid=4.10, ask=4.50, delta=-0.20)
        result = generate_csp_candidates("AAPL", [q1, q2], _account(), _iv(), _tech(), _fund())
        assert len(result) == 2
        assert result[0].roc_pct >= result[1].roc_pct


# --------------------------------------------------------------------------- #
# Rolling tests
# --------------------------------------------------------------------------- #


def _short_call_position(
    strike: float = 200.0,
    expiry: date | None = None,
    delta: float = 0.30,
    contracts: int = 2,
    avg_cost: float = 1.30,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="AAPL",
        sec_type="OPT",
        position=float(-contracts),
        avg_cost=avg_cost,
        right=OptionRight.CALL,
        strike=strike,
        expiry=expiry if expiry is not None else _EXPIRY_NEAR,
        delta=delta,
        underlying="AAPL",
    )


def _short_put_position(
    strike: float = 170.0,
    expiry: date | None = None,
    delta: float = -0.25,
    contracts: int = 1,
    avg_cost: float = 1.90,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="AAPL",
        sec_type="OPT",
        position=float(-contracts),
        avg_cost=avg_cost,
        right=OptionRight.PUT,
        strike=strike,
        expiry=expiry if expiry is not None else _EXPIRY_NEAR,
        delta=delta,
        underlying="AAPL",
    )


# Rolling test helpers.
# _roll_current_quote: the existing short contract (at EXPIRY_NEAR, mid=0.10).
# _roll_new_quote:     the proposed new leg (at EXPIRY_FAR, mid=3.50).
#
# With the P1-01 ROC fix (credit/strike, not credit/entry_premium):
#   roll_credit = 3.50 - 0.10 = 3.40
#   strike = 200  →  ROC = (3.40/200)*100 = 1.70%  (passes min_roc_pct=1.0%)
#   annualized = 1.70 * (365/42+) ≈ 14.8%+  (passes min_ann=12.0% with ample margin)
#
# _infer_current_mid requires a live quote for the current contract — tests must
# include both quotes so the function can find the existing contract's market price.
def _roll_current_quote(
    strike: float = 200.0,
    expiry: date = _EXPIRY_NEAR,
    **kwargs,
) -> OptionQuote:
    return _call_quote(expiry=expiry, strike=strike, delta=0.55, bid=0.05, ask=0.15, **kwargs)


def _roll_new_quote(**kwargs) -> OptionQuote:
    # Higher premium gives ample margin above the min_annualized_yield_pct=12% gate
    # across the range of actual DTE values (42-51 days depending on when tests run).
    return _call_quote(expiry=_EXPIRY_FAR, delta=0.28, bid=3.40, ask=3.60, **kwargs)


def _roll_quotes(strike: float = 200.0, current_expiry: date = _EXPIRY_NEAR, **kwargs) -> list:
    """Both the current-contract quote and the new-leg quote for a standard roll test."""
    return [_roll_current_quote(strike=strike, expiry=current_expiry), _roll_new_quote(**kwargs)]


class TestRolling:
    def test_long_position_returns_empty(self):
        long_pos = PositionSnapshot(
            symbol="AAPL",
            sec_type="OPT",
            position=1.0,
            avg_cost=1.30,
            right=OptionRight.CALL,
            strike=200.0,
            expiry=_EXPIRY_NEAR,
            underlying="AAPL",
        )
        result = generate_roll_candidates(long_pos, _roll_quotes(), _iv(), _tech())
        assert result == []

    def test_missing_expiry_returns_empty(self):
        pos = PositionSnapshot(
            symbol="AAPL",
            sec_type="OPT",
            position=-1.0,
            avg_cost=1.30,
            right=OptionRight.CALL,
            strike=200.0,
            expiry=None,
            underlying="AAPL",
        )
        result = generate_roll_candidates(pos, _roll_quotes(), _iv(), _tech())
        assert result == []

    def test_no_roll_when_dte_far_and_delta_safe(self):
        # _EXPIRY is 34 DTE (>21), delta=0.30 (<0.40) → should_roll=False
        pos = _short_call_position(expiry=_EXPIRY, delta=0.30)
        result = generate_roll_candidates(pos, _roll_quotes(), _iv(), _tech())
        assert result == []

    def test_rolls_when_dte_lte_21(self):
        # _EXPIRY_NEAR is 10 DTE (<=21) → triggers roll
        pos = _short_call_position(expiry=_EXPIRY_NEAR, delta=0.30)
        result = generate_roll_candidates(pos, _roll_quotes(), _iv(), _tech())
        assert len(result) >= 1

    def test_rolls_when_delta_drifted(self):
        # delta=0.45 > 0.40 triggers roll even with DTE=34; current contract is at _EXPIRY
        pos = _short_call_position(expiry=_EXPIRY, delta=0.45)
        result = generate_roll_candidates(pos, _roll_quotes(current_expiry=_EXPIRY), _iv(), _tech())
        assert len(result) >= 1

    def test_roll_candidate_dte_exceeds_position_dte(self):
        pos = _short_call_position(expiry=_EXPIRY_NEAR, delta=0.30)
        result = generate_roll_candidates(pos, _roll_quotes(), _iv(), _tech())
        assert len(result) >= 1
        pos_dte = (_EXPIRY_NEAR - date.today()).days
        for c in result:
            assert c.dte > pos_dte

    def test_no_roll_credit_filters_candidate(self):
        # current_mid=3.10, new_mid=2.90 → roll_credit=-0.20 ≤ 0 → no candidate
        current = _call_quote(expiry=_EXPIRY_NEAR, strike=200.0, bid=3.00, ask=3.20, delta=0.55)
        pos = _short_call_position(expiry=_EXPIRY_NEAR, delta=0.30, avg_cost=3.10)
        result = generate_roll_candidates(pos, [current, _roll_new_quote()], _iv(), _tech())
        assert result == []

    def test_no_current_quote_returns_empty(self):
        # When the current contract is not in the quote list, roll is skipped
        pos = _short_call_position(expiry=_EXPIRY_NEAR, delta=0.30)
        result = generate_roll_candidates(pos, [_roll_new_quote()], _iv(), _tech())
        assert result == []

    def test_empty_quotes_returns_empty(self):
        pos = _short_call_position(expiry=_EXPIRY_NEAR, delta=0.30)
        result = generate_roll_candidates(pos, [], _iv(), _tech())
        assert result == []

    def test_contracts_matches_position_size(self):
        pos = _short_call_position(expiry=_EXPIRY_NEAR, delta=0.30, contracts=3)
        result = generate_roll_candidates(pos, _roll_quotes(), _iv(), _tech())
        assert len(result) >= 1
        assert result[0].contracts == 3

    def test_roll_strategy_tag(self):
        from src.common.schemas import Strategy

        pos = _short_call_position(expiry=_EXPIRY_NEAR, delta=0.30)
        result = generate_roll_candidates(pos, _roll_quotes(), _iv(), _tech())
        assert len(result) >= 1
        assert result[0].strategy == Strategy.ROLL

    def test_roll_collateral_uses_strike_not_entry_premium(self):
        # With the P1-02 fix, collateral = strike * contracts * 100, not avg_cost * contracts * 100.
        # _roll_new_quote has strike=200. _short_call_position has 2 contracts, avg_cost=1.30.
        # Wrong (old): collateral = 1.30 * 2 * 100 = 260.
        # Correct:      collateral = 200 * 2 * 100 = 40,000.
        pos = _short_call_position(expiry=_EXPIRY_NEAR, delta=0.30, contracts=2, avg_cost=1.30)
        result = generate_roll_candidates(pos, _roll_quotes(), _iv(), _tech())
        assert len(result) >= 1
        new_strike = result[0].strike
        expected_collateral = new_strike * 2 * 100
        assert result[0].collateral == pytest.approx(expected_collateral)

    def test_roll_roc_uses_strike_denominator(self):
        # With the P1-01 fix, ROC = roll_credit / strike (not / avg_cost).
        # roll_credit = new_mid - current_mid = 3.50 - 0.10 = 3.40
        # new_strike = 200.0 → expected ROC = (3.40 / 200.0) * 100 = 1.70%
        # Old formula gave: (3.40 / 1.30) * 100 ≈ 261% — completely fictitious.
        pos = _short_call_position(expiry=_EXPIRY_NEAR, delta=0.30, avg_cost=1.30)
        result = generate_roll_candidates(pos, _roll_quotes(), _iv(), _tech())
        assert len(result) >= 1
        roll_credit = 3.50 - 0.10  # new_mid - current_mid (bid=3.40, ask=3.60)
        expected_roc = (roll_credit / result[0].strike) * 100
        assert result[0].roc_pct == pytest.approx(expected_roc, abs=1e-3)

    def test_roll_put_collateral(self):
        # PUT roll: collateral = new_strike * contracts * 100.
        # roll_credit = 4.90 - 0.10 = 4.80, strike=165
        # ROC = (4.80/165)*100 = 2.91% ≥ 1.0%, ann = 2.91*(365/50) ≈ 21.2% ≥ 12.0%
        pos = _short_put_position(expiry=_EXPIRY_NEAR, delta=-0.25, contracts=2)
        put_new = _put_quote(strike=165.0, delta=-0.22, bid=4.80, ask=5.00, expiry=_EXPIRY_FAR)
        put_current = _put_quote(strike=170.0, delta=-0.55, bid=0.05, ask=0.15, expiry=_EXPIRY_NEAR)
        result = generate_roll_candidates(pos, [put_current, put_new], _iv(), _tech())
        assert len(result) >= 1
        expected_collateral = result[0].strike * 2 * 100
        assert result[0].collateral == pytest.approx(expected_collateral)
