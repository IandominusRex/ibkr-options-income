from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.schemas import ChainOption, ChainSnapshot
from src.spreads.pricing import MIN_T, delta, gamma, implied_vol, price, years_to_close

TODAY = date(2026, 10, 7)
TEN_AM = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)  # 10:00 EDT


def test_years_to_close_counts_calendar_time_to_the_bell() -> None:
    assert years_to_close(TEN_AM, TODAY) == pytest.approx(6 / 8760)


def test_years_to_close_is_zero_after_the_bell() -> None:
    assert years_to_close(datetime(2026, 10, 7, 21, 0, tzinfo=UTC), TODAY) == 0.0


def test_gamma_peaks_at_the_money_and_stays_finite_at_the_bell() -> None:
    t = 6 / 8760
    assert gamma(690, 690, t, 0.18) > gamma(690, 680, t, 0.18) > 0
    assert gamma(690, 690, 0.0, 0.18) == pytest.approx(gamma(690, 690, MIN_T, 0.18))
    assert gamma(690, 690, t, 0.0) == 0.0


def test_put_delta_is_call_delta_minus_one() -> None:
    t = 6 / 8760
    assert delta(690, 685, t, 0.18, "P") == pytest.approx(delta(690, 685, t, 0.18, "C") - 1.0)


def test_implied_vol_round_trips_a_bs_price() -> None:
    t = 6 / 8760
    p = price(690, 685, t, 0.18, "P")
    assert implied_vol(p, 690, 685, t, "P") == pytest.approx(0.18, abs=1e-4)


def test_implied_vol_is_none_below_intrinsic() -> None:
    assert implied_vol(1.0, 690, 700, 6 / 8760, "P") is None


def test_chain_option_mid_and_spread_pct() -> None:
    o = ChainOption(strike=680, right="P", expiry=TODAY, bid=0.80, ask=0.90)
    assert o.mid == pytest.approx(0.85)
    assert o.spread_pct == pytest.approx(0.10 / 0.85)
    assert ChainOption(strike=680, right="P", expiry=TODAY, bid=-1.0, ask=0.9).mid is None
    assert ChainOption(strike=680, right="P", expiry=TODAY, bid=0.0, ask=0.05).mid == 0.025


def test_chain_snapshot_find() -> None:
    o = ChainOption(strike=680, right="P", expiry=TODAY)
    snap = ChainSnapshot(symbol="XSP", spot=690.0, as_of=TEN_AM, options=[o])
    assert snap.find(680.0, "P", TODAY) is o
    assert snap.find(680.0, "C", TODAY) is None


def test_amendment_schemas_default_safely() -> None:
    from src.common.schemas import SessionSnapshot, SpreadExit, SpreadRiskContext, SpreadTrigger

    ctx = SpreadRiskContext(
        now=TEN_AM,
        levels=None,
        open_spreads=0,
        open_risk_usd=0.0,
        trades_today=0,
        realized_pnl_today_usd=0.0,
        excess_liquidity_usd=None,
        capital_usd=100_000.0,
    )
    assert ctx.sides_today == []
    assert SpreadTrigger(reason="no_move").sides == []
    assert SessionSnapshot(as_of=TEN_AM, last=690.0).prior_close is None
    assert SpreadExit(spread_id="s1", reason="max_hold", close=True).reason == "max_hold"


# Review I6 — on an early-close session the time stop moves with the close (SPY settles in shares).
def test_day_schedule_moves_the_time_stop_and_entry_end_on_an_early_close() -> None:
    from datetime import date

    from src.common.config import get_config
    from src.spreads.pricing import close_time, day_schedule

    sched = get_config().spreads.schedule
    black_friday = date(2026, 11, 27)
    early = day_schedule(sched, black_friday)
    assert close_time(black_friday).hour == 13
    assert (early.entry_end, early.force_close) == ("10:30", "12:45")
    assert early.map_time == sched.map_time and early.entry_start == sched.entry_start
    assert day_schedule(sched, date(2026, 11, 24)) is sched


def test_years_to_close_uses_the_early_close() -> None:
    from datetime import UTC, date, datetime

    from src.spreads.pricing import years_to_close

    noon = datetime(2026, 11, 27, 17, 0, tzinfo=UTC)  # 12:00 EST
    assert years_to_close(noon, date(2026, 11, 27)) * 365 * 24 == pytest.approx(1.0)
