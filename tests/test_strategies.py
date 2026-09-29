"""Unit tests for strategy modules. No TWS, no live data — all canned fixtures."""

from __future__ import annotations

import logging
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
from src.strategies.cash_secured_put import generate_csp_candidates, screen_csp_candidates
from src.strategies.covered_call import (
    generate_cc_candidates,
    screen_cc_candidates,
    uncovered_call_capacity,
)
from src.strategies.rolling import generate_roll_candidates

# Expiries within the [7, 28] DTE window; computed relative to today so tests
# stay green regardless of when they run.
#
# Spread/premium budget to clear ALL three gates for avg_cost=175 stock:
#   spread_pct < 10%  → (ask-bid)/mid < 0.10
#   roc_pct >= 1.0%   → premium >= 1.75
#   ann_yield >= 12%  → premium >= 175 * (12/100) * (24/365) ≈ 1.38
#
# Default bid=2.10 / ask=2.30 gives mid=2.20, spread_pct≈9.1%, roc≈1.26%, ann≈19.1%.

_TODAY = date.today()
_EXPIRY = _TODAY + timedelta(days=24)  # 24 DTE — inside [7, 28] and > the hardcoded
# pos_dte<=21 roll trigger in rolling.py, so it also serves as a "no roll" position expiry.
_EXPIRY_FAR = _TODAY + timedelta(days=27)  # 27 DTE — roll new-leg expiry: > _EXPIRY (so it
# clears the "further out" check) with a day of margin below the dte_max=28 window edge.
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


def _account(
    *,
    net_liq: float = 100_000.0,
    cash: float = 70_000.0,
    total_cash: float = 50_000.0,
    buying_power: float = 80_000.0,
) -> AccountSnapshot:
    # `cash` maps to `excess_liquidity` — the post-margin cushion `capital.resolve_caps`
    # actually reads as its deployable-cash basis, not `total_cash`.
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=net_liq,
        total_cash=total_cash,
        buying_power=buying_power,
        maintenance_margin=10_000.0,
        excess_liquidity=cash,
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

    # Regime alignment for SHORT premium (N1): we SELL these options, so the favourable
    # regime works against the long side of the contract we wrote.
    #   CSP (PUT):  BULLISH +10 · SIDEWAYS 0 · BEARISH -5
    #   CC  (CALL): BEARISH +10 · SIDEWAYS +10 · BULLISH -5
    @pytest.mark.parametrize(
        ("right", "regime", "expected"),
        [
            ("P", Regime.BULLISH, 60.0),  # CSP: bullish tailwind — favourable
            ("P", Regime.SIDEWAYS, 50.0),  # CSP: neutral
            ("P", Regime.BEARISH, 45.0),  # CSP: bearish headwind — penalised
            ("C", Regime.BEARISH, 60.0),  # CC: bearish — favourable
            ("C", Regime.SIDEWAYS, 60.0),  # CC: range-bound — favourable
            ("C", Regime.BULLISH, 45.0),  # CC: bullish — upside given up, penalised
        ],
    )
    def test_technical_score_regime_matrix(self, right, regime, expected):
        q = _put_quote() if right == "P" else _call_quote()
        score = technical_score(q, _tech(regime=regime))
        assert score == pytest.approx(expected)

    def test_technical_score_no_regime_is_neutral(self):
        assert technical_score(_call_quote(), _tech(regime=None)) == pytest.approx(50.0)
        assert technical_score(_put_quote(), _tech(regime=None)) == pytest.approx(50.0)

    def test_technical_score_clamped(self):
        q = _call_quote()
        score = technical_score(q, _tech())
        assert 0.0 <= score <= 100.0


class TestStrictMid:
    """N10: the strategy generators price premium off strict_mid (no `last` fallback)."""

    def _q(self, **kw) -> OptionQuote:
        base = dict(underlying="AAPL", right=OptionRight.CALL, strike=200.0, expiry=_EXPIRY)
        base.update(kw)
        return OptionQuote(**base)

    def test_strict_mid_two_sided(self):
        assert self._q(bid=2.10, ask=2.30).strict_mid == pytest.approx(2.20)

    def test_strict_mid_none_when_only_last(self):
        q = self._q(bid=None, ask=None, last=2.20)
        assert q.mid == pytest.approx(2.20)  # lenient property falls back to last
        assert q.strict_mid is None  # strict one refuses

    def test_strict_mid_accepts_zero_bid(self):
        assert self._q(bid=0.0, ask=0.10).strict_mid == pytest.approx(0.05)

    def test_cc_generator_rejects_last_only_quote(self):
        # A quote with no live two-sided market (only a stale `last`) must yield no candidate.
        q = _call_quote()
        q = q.model_copy(update={"bid": None, "ask": None, "last": 2.20})
        result = generate_cc_candidates("AAPL", [q], _long_stock(), _iv(), _tech(), _fund())
        assert result == []


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

    def test_existing_short_calls_reduce_contracts(self):
        # 300 shares = 3 coverable contracts; 2 calls already written → only 1 uncovered.
        result = generate_cc_candidates(
            "AAPL",
            [_call_quote()],
            _long_stock(shares=300.0),
            _iv(),
            _tech(),
            _fund(),
            existing_short_calls=2,
        )
        assert len(result) == 1
        assert result[0].contracts == 1

    def test_fully_covered_returns_empty(self):
        # 200 shares = 2 contracts, both already written → nothing left to sell.
        result = generate_cc_candidates(
            "AAPL",
            [_call_quote()],
            _long_stock(shares=200.0),
            _iv(),
            _tech(),
            _fund(),
            existing_short_calls=2,
        )
        assert result == []

    def test_uncovered_call_capacity_matches_the_screen(self):
        """`uncovered_call_capacity` is the same formula `screen_cc_candidates` sizes with,
        extracted for a caller (the execution-time share-coverage re-check) that only needs
        the number."""
        positions = [
            PositionSnapshot(symbol="AAPL", sec_type="STK", position=300.0, avg_cost=175.0),
            PositionSnapshot(
                symbol="AAPL  260918C00200000",
                sec_type="OPT",
                position=-2,
                avg_cost=1.0,
                right=OptionRight.CALL,
                strike=200.0,
                underlying="AAPL",
            ),
        ]
        assert uncovered_call_capacity(positions, "AAPL") == 1  # 3 coverable - 2 already written

    def test_uncovered_call_capacity_ignores_other_underlyings(self):
        positions = [
            PositionSnapshot(symbol="AAPL", sec_type="STK", position=300.0, avg_cost=175.0),
            PositionSnapshot(symbol="MSFT", sec_type="STK", position=1000.0, avg_cost=300.0),
        ]
        assert uncovered_call_capacity(positions, "AAPL") == 3

    def test_uncovered_call_capacity_zero_without_shares(self):
        assert uncovered_call_capacity([], "AAPL") == 0

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

    def test_illiquid_oi_low_is_a_granular_reason_not_the_legacy_code(self):
        # Task 7: a thin-OI reject must carry the precise sub-reason, not the collapsed
        # "illiquid" code, and the candidate's quote microstructure must be attached.
        quote = _call_quote(oi=5)
        result = screen_cc_candidates("AAPL", [quote], _long_stock(), _iv(), _tech(), _fund())
        assert result.passed == []
        assert len(result.rejected) == 1
        cand, reasons = result.rejected[0]
        assert "illiquid_oi_low" in reasons
        assert "illiquid" not in reasons
        assert cand.open_interest == 5


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
        # D1: sizing now calls engine.capital.max_contracts, which sizes to the *binding*
        # constraint rather than to the maximum affordable lot. With the in-code defaults
        # (no portfolio.* keys in config yet — Task 9 adds them), one contract already
        # costs strike*100 = 17,000, which exceeds max_ticker_collateral (10% of net_liq =
        # 10,000) and so consumes the single large-position slot; a second contract
        # (34,000) would breach large_ticker_collateral (25% of net_liq = 25,000). So the
        # binding constraint caps this candidate at 1 contract, not the 3 the old
        # cash/csp-budget-only formula would have proposed.
        result = generate_csp_candidates(
            "AAPL", [_put_quote()], _account(), _iv(), _tech(), _fund()
        )
        assert len(result) == 1
        assert result[0].contracts == 1

    def test_filters_call_quotes(self):
        result = generate_csp_candidates(
            "AAPL", [_call_quote()], _account(), _iv(), _tech(), _fund()
        )
        assert result == []

    def test_filters_high_abs_delta(self):
        # abs(delta)=0.50 exceeds the 0.35 max
        quote = _put_quote(delta=-0.50)
        result = generate_csp_candidates("AAPL", [quote], _account(), _iv(), _tech(), _fund())
        assert result == []

    def test_filters_low_abs_delta(self):
        # abs(delta)=0.05 is below the 0.20 min
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

    def test_illiquid_oi_low_is_a_granular_reason_not_the_legacy_code(self):
        # Task 7: a thin-OI reject must carry the precise sub-reason, not the collapsed
        # "illiquid" code, and the candidate's quote microstructure must be attached.
        quote = _put_quote(oi=5)
        result = screen_csp_candidates("AAPL", [quote], _account(), _iv(), _tech(), _fund())
        assert result.passed == []
        assert len(result.rejected) == 1
        cand, reasons = result.rejected[0]
        assert "illiquid_oi_low" in reasons
        assert "illiquid" not in reasons
        assert cand.open_interest == 5

    def test_symbolwide_outage_logs_distinct_warning(self, caplog):
        """When IBKR delivers no live market for the ENTIRE chain, that's a data-feed
        outage, not real illiquidity (2026-09-11 root cause: TQQQ/UPRO/AMZN/RKLB scan
        cycles where every quote came back with no bid/ask were silently folded into the
        ordinary 'illiquid' tally, making a data-feed outage indistinguishable from a
        genuinely thin market)."""
        quote = _put_quote(bid=None, ask=None, volume=None, oi=None)
        with caplog.at_level(logging.WARNING, logger="src.strategies.cash_secured_put"):
            result = screen_csp_candidates("AAPL", [quote], _account(), _iv(), _tech(), _fund())
        assert result.passed == []
        outage_msgs = [r.message for r in caplog.records if "data-feed outage" in r.message]
        assert outage_msgs, caplog.text

    def test_thin_but_real_market_does_not_log_outage_warning(self, caplog):
        """A genuine thin-liquidity reject (real bid/ask, just below the OI/volume floor)
        must not be mislabeled as a data-feed outage."""
        quote = _put_quote(bid=2.10, ask=2.30, volume=1, oi=1)
        with caplog.at_level(logging.WARNING, logger="src.strategies.cash_secured_put"):
            result = screen_csp_candidates("AAPL", [quote], _account(), _iv(), _tech(), _fund())
        assert result.passed == []
        outage_msgs = [r.message for r in caplog.records if "data-feed outage" in r.message]
        assert not outage_msgs, caplog.text


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
#   annualized = 1.70 * (365/27) ≈ 23.0%  (passes min_ann=12.0% with ample margin)
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
    # across the range of actual DTE values (26-27 days depending on when tests run).
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
        # _EXPIRY is 24 DTE (>21), delta=0.30 (<0.40) → should_roll=False
        pos = _short_call_position(expiry=_EXPIRY, delta=0.30)
        result = generate_roll_candidates(pos, _roll_quotes(), _iv(), _tech())
        assert result == []

    def test_rolls_when_dte_lte_21(self):
        # _EXPIRY_NEAR is 10 DTE (<=21) → triggers roll
        pos = _short_call_position(expiry=_EXPIRY_NEAR, delta=0.30)
        result = generate_roll_candidates(pos, _roll_quotes(), _iv(), _tech())
        assert len(result) >= 1

    def test_rolls_when_delta_drifted(self):
        # delta=0.45 > 0.40 triggers roll even with DTE=24; current contract is at _EXPIRY
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
        # current_mid=3.10, new_mid=2.90 → roll_credit=-0.20 ≤ 0 → no candidate.
        # D2 note: the bare `_roll_new_quote()` (mid=3.50) this test previously passed
        # actually produced roll_credit=+0.40 (0.20% ROC) — it was filtered by the *old*
        # 1.0% min_roc_pct floor, not by the `roll_credit <= 0` branch this test claims to
        # cover, and that floor is now a 0.15% noise floor that no longer catches it. Pass an
        # explicit new-leg quote priced below the current mid so the test actually exercises
        # the documented negative-credit path regardless of the income-gate config.
        current = _call_quote(expiry=_EXPIRY_NEAR, strike=200.0, bid=3.00, ask=3.20, delta=0.55)
        # Built directly (not via `_roll_new_quote`, which hardcodes bid/ask) so mid=2.90 < the
        # current mid=3.10.
        new_leg = _call_quote(expiry=_EXPIRY_FAR, delta=0.28, bid=2.80, ask=3.00)
        pos = _short_call_position(expiry=_EXPIRY_NEAR, delta=0.30, avg_cost=3.10)
        result = generate_roll_candidates(pos, [current, new_leg], _iv(), _tech())
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
        # ROC = (4.80/165)*100 = 2.91% ≥ 1.0%, ann = 2.91*(365/27) ≈ 39.3% ≥ 12.0%
        pos = _short_put_position(expiry=_EXPIRY_NEAR, delta=-0.25, contracts=2)
        put_new = _put_quote(strike=165.0, delta=-0.22, bid=4.80, ask=5.00, expiry=_EXPIRY_FAR)
        put_current = _put_quote(strike=170.0, delta=-0.55, bid=0.05, ask=0.15, expiry=_EXPIRY_NEAR)
        result = generate_roll_candidates(pos, [put_current, put_new], _iv(), _tech())
        assert len(result) >= 1
        expected_collateral = result[0].strike * 2 * 100
        assert result[0].collateral == pytest.approx(expected_collateral)


def test_candidates_carry_current_iv_for_risk_unit_sizing(monkeypatch):
    """The gate computes risk units from IV, so the generator must record it."""
    from src.common.schemas import IVStats

    iv_stats = IVStats(symbol="AAPL", current_iv=28.5, iv_rank=55.0, hv_30=22.0)
    result = screen_csp_candidates("AAPL", [_put_quote()], _account(), iv_stats, _tech(), _fund())
    all_cands = result.passed + [c for c, _ in result.rejected]
    assert all_cands, "fixture should produce at least one contract"
    assert all(c.current_iv == 28.5 for c in all_cands)


def test_csp_sizing_trims_to_headroom_rather_than_maxing_out():
    """D1: sizing must not propose a lot the gate will reject outright."""
    from src.common.schemas import IVStats
    from src.strategies.cash_secured_put import screen_csp_candidates

    account = _account(net_liq=300_000.0, cash=100_000.0)
    iv_stats = IVStats(symbol="AAPL", current_iv=28.0, iv_rank=55.0, hv_30=22.0)
    result = screen_csp_candidates(
        "AAPL", [_put_quote()], account, iv_stats, _tech(), _fund(), positions=[]
    )
    for cand in result.passed:
        # deployable cash = 100k - max(20k, 10k) = 80k
        assert cand.collateral <= 80_000.0


def test_csp_high_priced_name_is_sized_to_one_lot_not_rejected():
    """A $650 strike must be trimmed to 1 lot, not sized to the 2 lots the old
    cash/csp-budget-only formula would have proposed.

    Fixture review (2026-08-10): the brief's original fixture (net_liq=300k, cash=100k)
    already produced contracts=1 under the *pre-fix* formula too (cash_n=1, csp_budget_n=2,
    min(10,1,2)=1) — it never exercised the regression. This fixture is deliberately tighter:
    under the pre-fix formula, cash_n=floor(150_000/65_000)=2, csp_budget_n=
    floor(300_000*0.60/65_000)=2, so contracts=min(10,2,2)=2 — a $130,000 (43% of net_liq)
    single-name position. `engine.capital.max_contracts` trims this to 1 lot ($65,000, 21.7%
    of net_liq) because a second lot would exceed the deployable-cash ceiling. The premium is
    set high enough that the contract clears every other gate regardless of contract count
    (ROC/yield/delta/liquidity don't depend on size), so it lands in `.passed` at exactly 1 lot
    — a genuine fit, not the `insufficient_cash` display fallback for a 0-lot reject.
    """
    from src.common.schemas import IVStats
    from src.strategies.cash_secured_put import screen_csp_candidates

    account = _account(net_liq=300_000.0, cash=150_000.0)
    iv_stats = IVStats(symbol="META", current_iv=35.0, iv_rank=60.0, hv_30=28.0)
    quote = _put_quote(strike=650.0, bid=8.00, ask=8.20)  # mid=8.10; roc~1.25%, ann~18.9%
    # D2: spot must be plausible for a 650 strike now that the VRP gate is live — the
    # default `_tech()` spot (185.0) made this put ~465 deep ITM, so its own Black-Scholes
    # fair value (~$462) dwarfed the $8.10 mid and every fixture would fail
    # `premium_below_fair_value` regardless of the sizing logic under test. spot=700 makes
    # the 650 strike a plausible ~30-delta OTM put (fair value ~$3.46, floor ~$3.81 at the
    # required edge), which the $8.10 mid clears with margin.
    result = screen_csp_candidates(
        "META", [quote], account, iv_stats, _tech(price=700.0), _fund(), positions=[]
    )
    assert result.rejected == [], "should clear every gate at the trimmed size, not be flagged"
    assert len(result.passed) == 1
    assert result.passed[0].contracts == 1
