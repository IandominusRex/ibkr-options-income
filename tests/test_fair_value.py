"""Tests for the deterministic ideal-price engine (src/analytics/fair_value.py).

Covers:
  1. Expected-move math and the base band.
  2. Support/resistance snapping — the first consumer of TechnicalStats.support_levels.
  3. Earnings / quality / ex-div widening.
  4. Cost-basis floor for covered calls.
  5. The min-credit floor vs Black-Scholes fair value at realised vol.
  6. Graceful degradation when inputs are missing.
  7. zone_fit_score and its default-off wiring into technical_score.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from src.analytics.black_scholes import bs_price
from src.analytics.fair_value import compute_ideal_zone, zone_fit_score
from src.common.schemas import (
    FundamentalStats,
    IdealZone,
    IVStats,
    OptionQuote,
    OptionRight,
    Regime,
    TechnicalStats,
)

_TODAY = date(2026, 8, 6)


def _tech(**kw: object) -> TechnicalStats:
    base: dict = {"symbol": "NVDA", "price": 200.0, "regime": Regime.SIDEWAYS}
    base.update(kw)
    return TechnicalStats(**base)


def _iv(**kw: object) -> IVStats:
    base: dict = {"symbol": "NVDA", "current_iv": 40.0, "hv_30": 30.0}
    base.update(kw)
    return IVStats(**base)


def _fund(**kw: object) -> FundamentalStats:
    base: dict = {"symbol": "NVDA"}
    base.update(kw)
    return FundamentalStats(**base)


def _zone(right: OptionRight = OptionRight.PUT, **kw: object) -> IdealZone:
    args: dict = {
        "symbol": "NVDA",
        "right": right,
        "dte": 30,
        "spot": 200.0,
        "tech": _tech(),
        "iv": _iv(),
        "fund": _fund(),
        "today": _TODAY,
    }
    args.update(kw)
    return compute_ideal_zone(**args)


# ---------------------------------------------------------------------------
# 1. Expected move + base band
# ---------------------------------------------------------------------------


def test_expected_move_matches_the_closed_form() -> None:
    z = _zone()
    expected = 200.0 * 0.40 * math.sqrt(30 / 365)
    assert z.expected_move == pytest.approx(round(expected, 2))


def test_put_band_sits_below_spot_and_call_band_above() -> None:
    put = _zone(OptionRight.PUT)
    call = _zone(OptionRight.CALL)
    assert put.strike_hi is not None and put.strike_hi < 200.0
    assert call.strike_lo is not None and call.strike_lo > 200.0


def test_band_width_reflects_the_configured_multipliers() -> None:
    z = _zone()
    assert z.expected_move is not None and z.strike_lo is not None and z.strike_hi is not None
    # 0.30σ..1.20σ → the band spans 0.9 of an expected move.
    assert (z.strike_hi - z.strike_lo) == pytest.approx(z.expected_move * 0.9, abs=0.05)


@pytest.mark.parametrize(
    ("spot", "vol_pct", "dte"),
    [(210.0, 38.0, 31), (100.0, 60.0, 45), (450.0, 18.0, 21), (50.0, 90.0, 40)],
)
@pytest.mark.parametrize("target_delta", [0.15, 0.22, 0.30])
def test_the_band_actually_contains_the_delta_range_the_screen_trades(
    spot: float, vol_pct: float, dte: int, target_delta: float
) -> None:
    """The zone is calibrated to the configured CSP delta band (0.15-0.30), not picked by feel.

    This is the regression that matters: the first cut used 0.75-1.25 expected moves, which sits
    roughly twice as far OTM as a 0.15-0.30 delta put actually does — so every real candidate
    would have been reported "outside the ideal zone" and the feature would have read as noise.
    """
    strike = _strike_at_delta(spot, vol_pct / 100.0, dte, "P", target_delta)
    z = _zone(
        OptionRight.PUT,
        spot=spot,
        dte=dte,
        tech=_tech(price=spot),
        iv=_iv(current_iv=vol_pct, hv_30=vol_pct * 0.8),
    )
    assert z.strike_lo is not None and z.strike_hi is not None
    assert z.strike_lo <= strike <= z.strike_hi, (
        f"{target_delta:.2f}-delta put at ${strike:.2f} falls outside "
        f"the ideal band ${z.strike_lo:.2f}-${z.strike_hi:.2f}"
    )


@pytest.mark.parametrize("target_delta", [0.20, 0.28, 0.35])
def test_the_call_band_contains_the_configured_cc_delta_range(target_delta: float) -> None:
    strike = _strike_at_delta(210.0, 0.38, 31, "C", target_delta)
    z = _zone(
        OptionRight.CALL, spot=210.0, dte=31, tech=_tech(price=210.0), iv=_iv(current_iv=38.0)
    )
    assert z.strike_lo is not None and z.strike_hi is not None
    assert z.strike_lo <= strike <= z.strike_hi


def _strike_at_delta(spot: float, iv: float, dte: int, right: str, target: float) -> float:
    """The strike whose Black-Scholes |delta| is closest to *target*."""
    from src.analytics.black_scholes import bs_delta

    best, err = spot, 9e9
    k = spot * 0.5
    while k <= spot * 1.5:
        d = bs_delta(spot, k, dte, iv, right)
        if d is not None and abs(abs(d) - target) < err:
            err, best = abs(abs(d) - target), k
        k += spot * 0.002
    return best


def test_falls_back_to_hv30_when_implied_vol_is_missing() -> None:
    z = _zone(iv=_iv(current_iv=None, hv_30=30.0))
    expected = 200.0 * 0.30 * math.sqrt(30 / 365)
    assert z.expected_move == pytest.approx(round(expected, 2))


# ---------------------------------------------------------------------------
# 2. Support / resistance snapping
# ---------------------------------------------------------------------------


def test_put_band_snaps_to_a_nearby_support_level() -> None:
    plain = _zone()
    assert plain.strike_lo is not None
    # Place a support level right on the outer edge of the unsnapped band.
    support = round(plain.strike_lo + 1.0, 2)
    snapped = _zone(tech=_tech(support_levels=[support]))
    assert snapped.strike_lo == pytest.approx(support, abs=0.01)
    assert any("support" in a for a in snapped.strike_anchors)


def test_snapping_translates_the_band_without_changing_its_width() -> None:
    plain = _zone()
    assert plain.strike_lo is not None and plain.strike_hi is not None
    width = plain.strike_hi - plain.strike_lo
    snapped = _zone(tech=_tech(support_levels=[round(plain.strike_lo + 1.0, 2)]))
    assert snapped.strike_lo is not None and snapped.strike_hi is not None
    assert (snapped.strike_hi - snapped.strike_lo) == pytest.approx(width, abs=0.02)


def test_distant_support_does_not_pull_the_band() -> None:
    plain = _zone()
    far = _zone(tech=_tech(support_levels=[50.0]))  # far outside support_pull_pct
    assert far.strike_lo == plain.strike_lo


def test_call_uses_resistance_not_support() -> None:
    plain = _zone(OptionRight.CALL)
    assert plain.strike_lo is not None
    # A support level below spot is irrelevant to a call band.
    with_support = _zone(OptionRight.CALL, tech=_tech(support_levels=[190.0]))
    assert with_support.strike_lo == plain.strike_lo


# ---------------------------------------------------------------------------
# 3. Event / quality widening
# ---------------------------------------------------------------------------


def test_earnings_inside_dte_pushes_the_put_band_further_otm() -> None:
    plain = _zone()
    with_earnings = _zone(fund=_fund(next_earnings=_TODAY + timedelta(days=10)))
    assert plain.strike_hi is not None and with_earnings.strike_hi is not None
    assert with_earnings.strike_hi < plain.strike_hi
    assert any("earnings" in a for a in with_earnings.strike_anchors)


def test_earnings_outside_dte_is_ignored() -> None:
    plain = _zone()
    later = _zone(fund=_fund(next_earnings=_TODAY + timedelta(days=90)))
    assert later.strike_hi == plain.strike_hi


def test_failing_quality_screen_deepens_the_put_band_only() -> None:
    plain_put = _zone(OptionRight.PUT)
    poor_put = _zone(OptionRight.PUT, fund=_fund(quality_flag=False))
    assert plain_put.strike_lo is not None and poor_put.strike_lo is not None
    assert poor_put.strike_lo < plain_put.strike_lo

    plain_call = _zone(OptionRight.CALL)
    poor_call = _zone(OptionRight.CALL, fund=_fund(quality_flag=False))
    assert poor_call.strike_lo == plain_call.strike_lo


def test_ex_dividend_inside_dte_keeps_the_call_at_least_one_sigma_out() -> None:
    z = _zone(OptionRight.CALL, fund=_fund(ex_dividend_date=_TODAY + timedelta(days=5)))
    assert z.strike_lo is not None and z.expected_move is not None
    assert z.strike_lo >= 200.0 + z.expected_move - 0.01
    assert any("ex-div" in a for a in z.strike_anchors)


# ---------------------------------------------------------------------------
# 4. Cost-basis floor (covered calls)
# ---------------------------------------------------------------------------


def test_call_band_is_floored_at_cost_basis() -> None:
    z = _zone(OptionRight.CALL, cost_basis=260.0)  # well above the natural band
    assert z.strike_lo is not None and z.strike_lo >= 260.0
    assert z.strike_hi is not None and z.strike_hi >= z.strike_lo
    assert any("basis" in a for a in z.strike_anchors)


def test_cost_basis_below_the_band_changes_nothing() -> None:
    plain = _zone(OptionRight.CALL)
    floored = _zone(OptionRight.CALL, cost_basis=100.0)
    assert floored.strike_lo == plain.strike_lo


def test_cost_basis_is_ignored_for_puts() -> None:
    plain = _zone(OptionRight.PUT)
    with_basis = _zone(OptionRight.PUT, cost_basis=260.0)
    assert with_basis.strike_lo == plain.strike_lo


# ---------------------------------------------------------------------------
# 5. Min credit
# ---------------------------------------------------------------------------


def test_min_credit_clears_black_scholes_fair_value_at_realised_vol() -> None:
    z = _zone()
    assert z.min_credit is not None and z.strike_anchor is not None
    fair = bs_price(200.0, z.strike_anchor, 30, 0.30, "P")
    assert fair is not None
    # Must demand at least the configured edge over the no-edge price.
    assert z.min_credit >= fair * 1.10 - 0.01


def test_min_credit_respects_the_roc_and_yield_gates() -> None:
    """With HV30 near zero the BS floor vanishes; the income gates must still bind."""
    z = _zone(iv=_iv(current_iv=40.0, hv_30=0.01))
    assert z.min_credit is not None and z.strike_anchor is not None
    # min_roc_pct 1.0% of the strike is the binding floor here.
    assert z.min_credit >= z.strike_anchor * 0.01 - 0.01
    assert any("ROC/yield" in a for a in z.credit_anchors)


def test_min_credit_is_none_without_any_vol_or_gate_basis() -> None:
    z = _zone(dte=0)
    assert z.min_credit is None


# ---------------------------------------------------------------------------
# 6. Degradation
# ---------------------------------------------------------------------------


def test_no_vol_yields_an_empty_zone_rather_than_raising() -> None:
    z = _zone(iv=_iv(current_iv=None, hv_30=None))
    assert z.expected_move is None
    assert z.strike_lo is None and z.strike_anchor is None
    assert z.confidence == "low"


@pytest.mark.parametrize("bad", [{"spot": 0.0}, {"dte": 0}, {"spot": -5.0}])
def test_degenerate_inputs_return_an_empty_zone(bad: dict) -> None:
    z = _zone(**bad)
    assert z.strike_lo is None


def test_bare_analytics_still_produce_a_band() -> None:
    """Only a spot, a DTE and a vol are required — everything else is optional."""
    z = _zone(tech=_tech(sma_50=None, sma_200=None), fund=_fund())
    assert z.strike_lo is not None and z.strike_anchor is not None
    assert z.confidence in {"low", "medium", "high"}


def test_confidence_rises_with_available_inputs() -> None:
    thin = _zone(tech=_tech())
    # Levels chosen to land inside the ~[171, 183] put band so both the snap and the SMA
    # anchor actually fire — a level outside the band contributes nothing, by design.
    rich = _zone(
        tech=_tech(support_levels=[180.0, 175.0], sma_50=178.0),
        fund=_fund(target_mean_price=230.0, fifty_two_week_low=120.0, fifty_two_week_high=250.0),
    )
    assert rich.confidence == "high"
    assert thin.confidence != "high"


# ---------------------------------------------------------------------------
# Action level / buy_below
# ---------------------------------------------------------------------------


def test_action_price_uses_the_band_midpoint_not_a_hard_sigma() -> None:
    """0.30-1.20σ band → midpoint 0.75σ. Demanding a full 1σ would flag well-placed
    contracts as needing a better entry, which is the opposite of useful."""
    put = _zone(OptionRight.PUT)
    assert put.action_price is not None and put.strike_anchor is not None
    assert put.expected_move is not None
    expected = put.strike_anchor + put.expected_move * 0.75
    assert put.action_price == pytest.approx(expected, abs=0.02)
    assert put.action_note is not None


def test_action_note_says_so_when_the_cushion_is_already_met() -> None:
    """Spot well above the level means the write already has its cushion — don't imply waiting."""
    z = _zone(OptionRight.PUT, tech=_tech(support_levels=[150.0]), spot=200.0)
    assert z.action_price is not None
    if 200.0 >= z.action_price:
        assert "already met" in (z.action_note or "")
    else:
        assert "wrong side" in (z.action_note or "")


def test_call_action_level_sits_below_spot_side() -> None:
    call = _zone(OptionRight.CALL)
    assert call.action_price is not None and call.strike_anchor is not None
    assert call.action_price < call.strike_anchor  # a call wants spot *below* the level
    assert "call mid-band" in (call.action_note or "")


def test_buy_below_picks_the_nearest_actionable_anchor() -> None:
    """The nearest level below spot, not the deepest — a "buy below" 28% away is not a level
    anyone acts on. The deeper anchors stay in the list, ordered nearest-first."""
    z = _zone(
        tech=_tech(support_levels=[185.0], sma_50=195.0),
        fund=_fund(target_mean_price=240.0),
    )
    assert z.buy_below == 195.0  # 50d SMA is the nearest level below spot
    assert z.buy_anchors[0].startswith("50d SMA")
    assert any("support" in a for a in z.buy_anchors)


def test_buy_below_ignores_anchors_at_or_above_spot() -> None:
    """A discounted analyst target on a beaten-down name can land above spot; advising a
    "buy below" a price you are already under is worse than saying nothing."""
    z = _zone(tech=_tech(sma_50=None), fund=_fund(target_mean_price=400.0))
    assert z.buy_below is None


def test_buy_below_uses_the_analyst_haircut_when_it_is_actionable() -> None:
    z = _zone(tech=_tech(sma_50=None), fund=_fund(target_mean_price=200.0))
    assert z.buy_below == pytest.approx(200.0 * 0.92, abs=0.01)
    assert "analyst mean" in z.buy_anchors[0]


def test_buy_below_is_none_without_anchors() -> None:
    z = _zone(tech=_tech(sma_50=None), fund=_fund())
    assert z.buy_below is None


# ---------------------------------------------------------------------------
# 7. zone_fit
# ---------------------------------------------------------------------------


def test_zone_fit_is_full_inside_the_band() -> None:
    z = _zone()
    assert z.strike_anchor is not None
    assert zone_fit_score(z.strike_anchor, z) == 100.0


def test_zone_fit_decays_outside_the_band_and_floors_at_zero() -> None:
    z = _zone()
    assert z.strike_hi is not None and z.expected_move is not None
    near = zone_fit_score(z.strike_hi + z.expected_move * 0.5, z)
    far = zone_fit_score(z.strike_hi + z.expected_move * 3, z)
    assert near is not None and far is not None
    assert 0.0 < near < 100.0
    assert far == 0.0


def test_zone_fit_is_none_without_a_zone() -> None:
    assert zone_fit_score(200.0, None) is None
    empty = IdealZone(symbol="X", right=OptionRight.PUT, dte=30, spot=1.0)
    assert zone_fit_score(200.0, empty) is None


def test_technical_score_is_unchanged_while_zone_fit_weight_is_zero() -> None:
    """The shipped config has zone_fit: 0.0, so scoring must be bit-identical to regime-only."""
    from src.strategies._scoring import technical_score

    quote = OptionQuote(
        underlying="NVDA",
        right=OptionRight.PUT,
        strike=150.0,  # far outside any sane zone
        expiry=_TODAY + timedelta(days=30),
        bid=1.0,
        ask=1.1,
    )
    tech = _tech(regime=Regime.BULLISH)
    assert technical_score(quote, tech) == technical_score(quote, tech, _zone())


def test_technical_score_blends_zone_fit_when_weighted(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.strategies import _scoring

    monkeypatch.setattr(_scoring, "_zone_fit_weight", lambda right: 0.5)
    quote = OptionQuote(
        underlying="NVDA",
        right=OptionRight.PUT,
        strike=150.0,  # a full expected move or more outside the band → fit 0
        expiry=_TODAY + timedelta(days=30),
        bid=1.0,
        ask=1.1,
    )
    tech = _tech(regime=Regime.BULLISH)
    regime_only = _scoring.technical_score(quote, tech)
    blended = _scoring.technical_score(quote, tech, _zone())
    assert blended < regime_only
