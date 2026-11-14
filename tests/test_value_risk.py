"""The value gate and sizing (value book spec §9.4-§9.6 as amended by revision 4). Pure."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.common.config import get_config
from src.common.envelope_types import EnvelopeRoom
from src.value import sizing
from src.value.risk import (
    FUNDABLE,
    BuyContext,
    ValueEnvelope,
    envelope_reasons,
    fundable_only,
    validate,
)

BOOK = get_config().value.book
# A $100,000 account; the book's ceiling is 30% = $30,000; the name cap 8% of it = $2,400.
OK = BuyContext(
    symbol="GOOGL",
    list_name="quality_growth",
    shares=10,
    price=150.0,
    verdict="READY",
    mos=0.25,
    required_mos_pct=10.0,
    mos_review=False,
    health="pass",
    data_quality="pass",
    timing="pass",
    earnings_in_window=False,
    net_liq=100_000.0,
    ceiling=30_000.0,
    book_cost=5_000.0,
    list_cost=5_000.0,
    name_cost=0.0,
    holds_name=False,
    positions_open=3,
    wheel_name_exposure=10_000.0,
    gross_used=80_000.0,
    adv_dollar_20=5_000_000_000.0,
)


def _v(ctx: BuyContext) -> list[str]:
    return validate(ctx, BOOK, max_gross_notional_pct=100.0, max_combined_name_pct=15.0)


def test_a_clean_buy_passes() -> None:
    assert _v(OK) == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"verdict": "WATCH"}, "verdict_not_ready"),
        ({"health": "fail"}, "health_gate_failed"),
        ({"mos_review": True}, "data_unreliable"),
        ({"mos": 0.05}, "mos_below_required"),
        ({"timing": "unknown"}, "timing_not_ready"),
        ({"earnings_in_window": None}, "earnings_within_window"),  # unknown is never a pass
        ({"attribution": "pending"}, "book_attribution_mismatch"),
        ({"adds_paused": True}, "adds_paused"),
        ({"trend_brake": True}, "trend_brake"),
        ({"drawdown_stop": True}, "sleeve_breaker"),
        ({"book_cost": 29_000.0}, "sleeve_exhausted"),
        ({"name_cost": 1_000.0}, "name_cap"),  # 1,000 + 1,500 > 2,400
        ({"list_cost": 20_000.0}, "list_share_cap"),  # 20,000 + 1,500 > 21,000
        ({"positions_open": 20}, "max_positions"),
        ({"wheel_name_exposure": 14_000.0}, "combined_name_cap"),
        ({"gross_used": 99_000.0}, "gross_notional_cap"),
        ({"adv_dollar_20": 100_000.0}, "illiquid"),
        ({"quote_age_seconds": 45.0}, "price_stale_at_send"),
        ({"is_live": True}, "not_paper"),
        ({"spreads_underlying": True}, "reserved_for_spreads_book"),
    ],
)
def test_every_reason(change, reason) -> None:
    assert reason in _v(replace(OK, **change))


def test_only_the_gross_cap_is_curable_by_released_capital() -> None:
    assert fundable_only(_v(replace(OK, gross_used=99_000.0)))
    assert not fundable_only(_v(replace(OK, gross_used=99_000.0, timing="fail")))
    assert not fundable_only([])


def test_tiers_tranches_and_the_trend_brake() -> None:
    rows = BOOK.tiers.deep_value
    assert [sizing.tier_pct(m, rows) for m in (20.0, 25.0, 40.0, 50.0, None)] == [
        0.0,
        3.0,
        5.0,
        8.0,
        0.0,
    ]
    # $100,000 net liq: ceiling 30,000; a 50% deep-value margin buys 8% = 2,400, in thirds
    assert sizing.target_cost("deep_value", 0.50, 100_000.0, BOOK, trend_brake=False) == 2_400.0
    assert sizing.target_cost("deep_value", 0.50, 100_000.0, BOOK, trend_brake=True) == 1_200.0
    assert sizing.tranche_shares(2_400.0, 3, 75.0, 0.0) == 10  # 800 / 75
    assert sizing.tranche_shares(2_400.0, 3, 75.0, 2_000.0) == 5  # never past the target
    lows = [10.0, 9.0, 8.5, 8.8, 9.0, 9.1, 9.2, 9.3, 9.4, 9.5]
    assert sizing.tranche_due(0, None, [], 10.0, None, BOOK)
    assert sizing.tranche_due(1, 10, lows, 10.0, None, BOOK)  # 9.1 > 8.5: a higher low
    assert not sizing.tranche_due(1, 3, lows, 10.0, None, BOOK)  # too soon
    assert sizing.tranche_due(2, 6, [], 10.0, 9.5, BOOK) and not sizing.tranche_due(
        2, 6, [], 9.0, 9.5, BOOK
    )
    assert not sizing.tranche_due(3, 10, [], 10.0, 9.0, BOOK)
    assert sizing.trend_brake([100.0] * 9 + [90.0]) is True
    assert sizing.trend_brake([100.0] * 9) is None


# --- risk-envelope Task 20: value-book buys under the envelope (ruling Q2) -----------------------

# A $1,500 buy (10 x $150) of a beta-1.2 name on a $100,000 book: S10 +0.18 points (1,500 x 0.12 /
# 100,000 x 100), U_ew +0.015.
S10_RATE = 1.2 * 0.10 / 100_000.0
UEW_RATE = 1.0 / 100_000.0


def _room(*, s10=20.0, s10_limit=25.0, uew=1.20, uew_limit=1.30, enforce="on", measured=True):
    return EnvelopeRoom(
        s10_gross=s10,
        s10_limit=s10_limit,
        uew=uew,
        uew_limit=uew_limit,
        t20_gross=0.0,
        t20_limit=None,
        enforce=enforce,
        measured=measured,
    )


def _env(**room) -> BuyContext:
    return replace(OK, envelope=_room(**room), s10_per_dollar=S10_RATE, uew_per_dollar=UEW_RATE)


def test_a_buy_inside_the_envelope_passes() -> None:
    assert _v(_env()) == []


def test_a_buy_that_breaches_l_of_t_is_refused() -> None:
    assert _v(_env(s10=24.9)) == ["envelope_shock_budget"]  # 24.9 + 0.18 > 25.0
    assert _v(_env(s10=24.8)) == []  # 24.98: under it


def test_a_buy_over_the_uew_limit_is_refused() -> None:
    assert _v(_env(uew=1.29)) == ["envelope_gross_budget"]  # 1.29 + 0.015 > 1.30
    # a book already above its limit takes no buy at all (every buy raises U_ew)
    assert "envelope_gross_budget" in _v(_env(uew=1.40))


def test_unmeasured_envelope_refuses_the_buy() -> None:
    assert _v(_env(measured=False)) == ["envelope_unmeasured"]
    no_rate = replace(_env(), s10_per_dollar=None)  # no beta for the name
    assert _v(no_rate) == ["envelope_unmeasured"]


def test_record_mode_records_only() -> None:
    ctx = _env(s10=24.9, uew=1.29, enforce="record")
    assert _v(ctx) == []  # refuses nothing
    assert envelope_reasons(ctx) == ["envelope_shock_budget", "envelope_gross_budget"]
    off = _env(s10=24.9, enforce="off")
    assert _v(off) == [] and envelope_reasons(off) == []


def test_envelope_reasons_are_never_fundable() -> None:
    assert FUNDABLE == frozenset({"gross_notional_cap"})
    both = _v(replace(_env(s10=24.9), gross_used=99_000.0))
    assert set(both) == {"gross_notional_cap", "envelope_shock_budget"}
    assert not fundable_only(both)


def test_a_filled_buy_joins_the_envelope_for_the_next() -> None:
    env = ValueEnvelope(
        room=_room(), s10_per_dollar={"GOOGL": S10_RATE}, uew_per_dollar={"GOOGL": UEW_RATE}
    )
    after = env.after_buy("GOOGL", 10_000.0)
    assert after.room.s10_gross == pytest.approx(21.2) and after.room.uew == pytest.approx(1.30)
    assert env.after_buy("ZZZ", 10_000.0) is env  # no rate: unchanged (that buy was unmeasured)
