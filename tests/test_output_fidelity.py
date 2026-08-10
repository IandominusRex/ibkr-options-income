"""Regression tests for four user-facing output defects found in the Aug 2026 output audit.

Each test pins a number or string that was measurably wrong before the fix:

  1. ``min_credit`` was priced at the zone's *anchor* strike but rendered against the
     *offered* contract's premium, so any strike further OTM than the anchor was labelled
     "below fair value" while actually trading at a multiple of its own fair value.
  2. ``_snap_to_level`` translated the whole band onto a support/resistance level, dragging
     the inner edge through spot — a 0.53-delta covered call rendered as "✓ in zone".
  3. ``date.today()`` (server-local) and ``OptionQuote.dte`` (ET) disagreed for any operator
     outside US/Eastern, printing two different DTEs inside one roll alert.
  4. Roll/assignment alerts rendered raw debug text (``delta=0.46 > ceiling=0.45``) and the
     profit / auto-close alerts leaked the raw OCC symbol (``AAPL  260818C00245000``).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.analytics.black_scholes import bs_delta, bs_price
from src.analytics.fair_value import (
    _zone_cfg,
    compute_ideal_zone,
    zone_for_contract,
)
from src.common.market_hours import today_et
from src.common.schemas import (
    AssessedContract,
    AssessmentStage,
    FundamentalStats,
    IdealZone,
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RollReview,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)
from src.monitor.triggers import (
    check_assignment_risk,
    check_delta_drift,
    check_dte_threshold,
)
from src.notify.formatters import (
    contract_label,
    format_assessed_contracts,
    format_assignment_alert,
    format_auto_close_result,
    format_profit_alert,
    format_roll_alert,
)

_ET = ZoneInfo("America/New_York")

# The exact AAPL setup from the audit: the numbers below are reproducible by hand.
_SPOT = 232.40
_DTE = 29
_HV = 22.2


def _tech() -> TechnicalStats:
    return TechnicalStats(
        symbol="AAPL",
        price=_SPOT,
        rsi_14=58.0,
        sma_50=219.40,
        sma_200=205.30,
        support_levels=[214.90, 205.30],
        resistance_levels=[248.10, 260.10],
        price_source="ibkr",
    )


def _iv() -> IVStats:
    return IVStats(symbol="AAPL", current_iv=26.4, iv_rank=48.0, vrp=4.2, hv_30=_HV)


def _fund() -> FundamentalStats:
    return FundamentalStats(
        symbol="AAPL",
        next_earnings=date(2026, 10, 29),
        quality_flag=True,
        fifty_two_week_high=260.10,
        fifty_two_week_low=181.20,
        target_mean_price=248.00,
    )


def _call_zone():
    return compute_ideal_zone(
        symbol="AAPL",
        right=OptionRight.CALL,
        dte=_DTE,
        spot=_SPOT,
        tech=_tech(),
        iv=_iv(),
        fund=_fund(),
        cost_basis=198.40,
        today=date(2026, 8, 6),
    )


# ---------------------------------------------------------------------------
# 1. Credit floor must be priced at the strike actually on offer
# ---------------------------------------------------------------------------


def test_credit_floor_is_priced_at_the_offered_strike_not_the_anchor() -> None:
    """A $250 call must be judged against the $250 floor, not the anchor's.

    The audit case: the anchor (240.32) produced one floor of $3.35 applied to every strike,
    so a $250C trading at $2.31 rendered "below fair value". Its own floor is the greater of
    Black-Scholes at $250 ($1.13) and the ROC/yield gate on the $198.40 basis ($1.98) — so
    $2.31 clears.
    """
    zone = _call_zone()
    offered = zone_for_contract(zone, strike=250.0, iv=_iv(), cost_basis=198.40)

    own_fair = bs_price(_SPOT, 250.0, _DTE, _HV / 100.0, "C")
    edge = 1.0 + _zone_cfg()["min_credit_edge_pct"] / 100.0

    assert offered.min_credit is not None
    assert offered.min_credit < zone.min_credit  # strike-specific, not the anchor's
    assert offered.min_credit >= round(own_fair * edge, 2)  # never below its own fair value
    assert 2.31 >= offered.min_credit  # the regression: this contract now clears


def test_credit_floor_never_rises_as_the_offered_call_strike_rises() -> None:
    """Further OTM calls are cheaper, so their floors must never increase.

    They used to: the ROC/yield component divided by *strike* even for a covered call, whose
    gate divides by cost basis — so the floor climbed with strike while fair value fell.
    """
    zone = _call_zone()
    floors = [
        zone_for_contract(zone, strike=k, iv=_iv(), cost_basis=198.40).min_credit
        for k in (240.0, 245.0, 250.0, 255.0)
    ]
    assert all(f is not None for f in floors)
    assert floors == sorted(floors, reverse=True)


def test_covered_call_credit_floor_uses_cost_basis_not_strike() -> None:
    """The floor must mirror the gate the candidate actually has to clear."""
    zone = _call_zone()
    on_basis = zone_for_contract(zone, strike=255.0, iv=_iv(), cost_basis=198.40).min_credit
    on_strike = zone_for_contract(zone, strike=255.0, iv=_iv()).min_credit
    assert on_basis is not None and on_strike is not None
    assert on_basis < on_strike
    assert on_basis == round(198.40 * 0.01, 2)


def test_zone_for_contract_preserves_the_strike_independent_band() -> None:
    """Only the credit floor is contract-specific; the band and levels are not."""
    zone = _call_zone()
    offered = zone_for_contract(zone, strike=250.0, iv=_iv())
    assert offered.strike_lo == zone.strike_lo
    assert offered.strike_hi == zone.strike_hi
    assert offered.strike_anchor == zone.strike_anchor
    assert offered.buy_below == zone.buy_below


# ---------------------------------------------------------------------------
# 2. Snapping must not drag the band's inner edge through spot
# ---------------------------------------------------------------------------


def test_snapping_to_resistance_keeps_the_inner_edge_outside_the_base_cushion() -> None:
    """Resistance at 248.10 used to translate the band down to 232.54 — at-the-money.

    The inner edge must stay at least ``em_lo_mult`` expected moves OTM, so the band
    stretches to reach the level instead of sliding through spot.
    """
    zone = _call_zone()
    cfg = _zone_cfg()
    assert zone.expected_move is not None
    base_inner = _SPOT + zone.expected_move * cfg["em_lo_mult"]

    assert zone.strike_lo is not None
    assert zone.strike_lo >= round(base_inner, 2)
    # The outer edge still honours the resistance level it snapped to.
    assert zone.strike_hi == 248.10


def test_ideal_call_band_never_endorses_an_at_the_money_write() -> None:
    """The whole point of "✓ in zone": a ~0.50-delta covered call must fail it."""
    zone = _call_zone()
    assert zone.strike_lo is not None
    inner_delta = bs_delta(_SPOT, zone.strike_lo, _DTE, 0.264, "C")
    assert inner_delta < 0.45


def test_put_band_inner_edge_also_stays_outside_the_base_cushion() -> None:
    """The put band's inner edge is its *upper* bound — clamp the mirrored case too."""
    zone = compute_ideal_zone(
        symbol="AAPL",
        right=OptionRight.PUT,
        dte=_DTE,
        spot=_SPOT,
        tech=_tech(),
        iv=_iv(),
        fund=_fund(),
        today=date(2026, 8, 6),
    )
    cfg = _zone_cfg()
    assert zone.expected_move is not None and zone.strike_hi is not None
    base_inner = _SPOT - zone.expected_move * cfg["em_lo_mult"]
    assert zone.strike_hi <= round(base_inner, 2)


# ---------------------------------------------------------------------------
# 3. One definition of "today" — the exchange's
# ---------------------------------------------------------------------------


def test_today_et_returns_the_exchange_calendar_date() -> None:
    assert today_et() == datetime.now(_ET).date()


def test_dte_threshold_trigger_agrees_with_option_quote_dte() -> None:
    """The roll alert prints both numbers; they must be the same number.

    Reproduces the audit finding: an operator in UTC+8 saw "DTE=12 <= threshold=14" and
    "DTE 13" in a single card because the trigger used the server-local date.
    """
    expiry = today_et() + timedelta(days=12)
    pos = PositionSnapshot(
        symbol="AAPL  260818C00245000",
        sec_type="OPT",
        position=-2,
        avg_cost=336.0,
        right=OptionRight.CALL,
        strike=245.0,
        expiry=expiry,
        underlying="AAPL",
    )
    quote = OptionQuote(
        symbol=pos.symbol,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=245.0,
        expiry=expiry,
        bid=5.0,
        ask=5.2,
        delta=0.46,
    )
    alert = check_dte_threshold(pos, 14)
    assert alert is not None
    assert alert.dte == quote.dte == 12


def test_roll_alert_prints_a_single_consistent_dte() -> None:
    expiry = today_et() + timedelta(days=12)
    pos = PositionSnapshot(
        symbol="AAPL  260818C00245000",
        sec_type="OPT",
        position=-2,
        avg_cost=336.0,
        right=OptionRight.CALL,
        strike=245.0,
        expiry=expiry,
        underlying="AAPL",
    )
    quote = OptionQuote(
        symbol=pos.symbol,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=245.0,
        expiry=expiry,
        bid=5.0,
        ask=5.2,
        delta=0.46,
    )
    alerts = [a for a in (check_delta_drift(pos, quote, 0.45), check_dte_threshold(pos, 14)) if a]
    text = format_roll_alert(pos, quote, alerts, None)
    assert "13" not in text.replace("0.13", "")
    assert "12 days left" in text


# ---------------------------------------------------------------------------
# 4. No raw debug text, no raw OCC symbols
# ---------------------------------------------------------------------------


def test_trigger_details_read_as_prose_not_debug_output() -> None:
    expiry = today_et() + timedelta(days=12)
    pos = PositionSnapshot(
        symbol="AAPL  260818C00245000",
        sec_type="OPT",
        position=-2,
        avg_cost=336.0,
        right=OptionRight.CALL,
        strike=245.0,
        expiry=expiry,
        underlying="AAPL",
    )
    quote = OptionQuote(
        symbol=pos.symbol,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=245.0,
        expiry=expiry,
        bid=5.0,
        ask=5.2,
        delta=0.46,
    )
    drift = check_delta_drift(pos, quote, 0.45)
    dte = check_dte_threshold(pos, 14)
    assign = check_assignment_risk(pos, quote, 0.45, 14)

    for alert in (drift, dte, assign):
        assert alert is not None
        assert ">" not in alert.detail
        assert "<=" not in alert.detail
        assert "ceiling=" not in alert.detail
        assert "threshold=" not in alert.detail

    assert drift is not None and "Delta 0.46" in drift.detail
    assert dte is not None and "12 days left" in dte.detail


def test_roll_alert_humanises_trigger_names() -> None:
    expiry = today_et() + timedelta(days=12)
    pos = PositionSnapshot(
        symbol="AAPL  260818C00245000",
        sec_type="OPT",
        position=-2,
        avg_cost=336.0,
        right=OptionRight.CALL,
        strike=245.0,
        expiry=expiry,
        underlying="AAPL",
    )
    quote = OptionQuote(
        symbol=pos.symbol,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=245.0,
        expiry=expiry,
        bid=5.0,
        ask=5.2,
        delta=0.46,
    )
    alerts = [a for a in (check_delta_drift(pos, quote, 0.45), check_dte_threshold(pos, 14)) if a]
    text = format_roll_alert(pos, quote, alerts, None)
    assert "delta_drift" not in text
    assert "delta drift" in text.lower()
    assert "nearing expiry" in text.lower()


def test_contract_label_is_human_readable() -> None:
    assert contract_label("AAPL", 245.0, OptionRight.CALL, date(2026, 8, 18)) == "AAPL $245C Aug 18"


def test_profit_alert_shows_a_readable_contract_not_the_occ_symbol() -> None:
    text = format_profit_alert(
        underlying="AAPL",
        strike=245.0,
        right=OptionRight.CALL,
        expiry=date(2026, 8, 18),
        entry_price=3.36,
        current_mid=1.62,
        profit_pct=0.518,
    )
    assert "260818C00245000" not in text
    assert "AAPL $245C Aug 18" in text.replace("\\", "")


def test_auto_close_result_shows_a_readable_contract_not_the_occ_symbol() -> None:
    filled = format_auto_close_result(
        underlying="AAPL",
        strike=245.0,
        right=OptionRight.CALL,
        expiry=date(2026, 8, 18),
        qty=2,
        limit_price=1.65,
        filled_qty=2,
        avg_price=1.63,
    )
    assert "260818C00245000" not in filled
    assert "AAPL $245C Aug 18" in filled.replace("\\", "")

    unfilled = format_auto_close_result(
        underlying="AAPL",
        strike=245.0,
        right=OptionRight.CALL,
        expiry=date(2026, 8, 18),
        qty=2,
        limit_price=1.65,
        filled_qty=0,
        avg_price=0.0,
    )
    assert "260818C00245000" not in unfilled
    assert "did not fill" in unfilled


def test_assignment_alert_has_no_raw_debug_text() -> None:
    expiry = today_et() + timedelta(days=12)
    pos = PositionSnapshot(
        symbol="AAPL  260818C00245000",
        sec_type="OPT",
        position=-2,
        avg_cost=336.0,
        right=OptionRight.CALL,
        strike=245.0,
        expiry=expiry,
        underlying="AAPL",
    )
    quote = OptionQuote(
        symbol=pos.symbol,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=245.0,
        expiry=expiry,
        bid=5.0,
        ask=5.2,
        delta=0.46,
    )
    alert = check_assignment_risk(pos, quote, 0.45, 14)
    assert alert is not None
    review = RollReview(
        position_symbol=pos.symbol,
        recommendation="roll",
        roll_target="roll to $255 Oct 02",
        rationale="Moves the strike above resistance.",
        risks="Defers assignment at a higher basis.",
    )
    text = format_assignment_alert(pos, quote, [alert], review)
    assert "≥ 0.45 with DTE=" not in text
    assert "|Δ| 0.46" in text.replace("\\", "")


# ---------------------------------------------------------------------------
# 5. A cash-blocked CSP should surface the share-entry alternative (D1 follow-on)
# ---------------------------------------------------------------------------


def _csp_candidate(
    *, underlying: str = "AAPL", strike: float = 190.0, contracts: int = 1
) -> TradeCandidate:
    """Minimal CSP-shaped candidate for formatter tests — not the generator's own path.

    `tests/test_engine.py` will gain its own `_csp_candidate` (Task 4); this one is local to
    this file, mirroring the `_cand()` pattern already used by `tests/test_assessed_contracts.py`.
    """
    return TradeCandidate(
        candidate_id=f"{underlying}-{strike}-csp",
        strategy=Strategy.CASH_SECURED_PUT,
        underlying=underlying,
        right=OptionRight.PUT,
        strike=strike,
        expiry=date.today() + timedelta(days=30),
        contracts=contracts,
        premium=3.0,
        collateral=strike * contracts * 100,
        roc_pct=1.5,
        annualized_yield_pct=18.0,
        breakeven=strike - 3.0,
        dte=30,
        scores=ScoreCard(symbol=underlying),
    )


def test_cash_blocked_csp_names_the_share_entry_level() -> None:
    """A rejection should offer the other route to the same exposure, not just say no."""
    zone = IdealZone(symbol="META", right=OptionRight.PUT, dte=30, spot=700.0, buy_below=612.0)
    cand = _csp_candidate(underlying="META", strike=650.0, contracts=1).model_copy(
        update={"ideal": zone}
    )
    assessed = [
        AssessedContract(
            candidate=cand, stage=AssessmentStage.GENERATOR, reasons=["insufficient_cash"]
        )
    ]
    text = format_assessed_contracts(assessed)
    assert "612" in text, "the share entry level must be surfaced when cash blocks the CSP"
