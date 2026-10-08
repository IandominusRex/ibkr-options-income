from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption, SpreadPosition
from src.spreads.manager import (
    debit_to_close,
    evaluate_exit,
    intrinsic_debit,
    reconcile,
    short_strike_touched,
)

TODAY = date(2026, 10, 7)
MIDDAY = datetime(2026, 10, 7, 16, 0, tzinfo=UTC)  # 12:00 EDT
CLOSE = datetime(2026, 10, 7, 19, 46, tzinfo=UTC)  # 15:46 EDT, past force_close
_BASE = get_config().spreads
CFG = _BASE.model_copy(
    update={
        "exits": _BASE.exits.model_copy(
            update={
                "profit_take_pct": 50.0,
                "stop_debit_multiple": 2.0,
                "close_on_short_strike_touch": True,
                "max_hold_minutes": 150,
                "let_expire": True,
                "let_expire_max_debit": 0.05,
            }
        )
    }
)


def pos(**kw) -> SpreadPosition:
    base = dict(
        spread_id="s1",
        mode="paper",
        side="put",
        expiry=TODAY,
        short_strike=680.0,
        long_strike=675.0,
        width=5.0,
        contracts=1,
        entry_credit=0.60,
        opened_at=MIDDAY,
        short_con_id=111,
        long_con_id=222,
    )
    base.update(kw)
    return SpreadPosition(**base)


def legs(short_bid, short_ask, long_bid, long_ask):
    s = ChainOption(strike=680, right="P", expiry=TODAY, bid=short_bid, ask=short_ask)
    lg = ChainOption(strike=675, right="P", expiry=TODAY, bid=long_bid, ask=long_ask)
    return s, lg


def test_debit_to_close_mid_and_natural() -> None:
    mid, nat = debit_to_close(*legs(0.40, 0.44, 0.10, 0.14))
    assert mid == pytest.approx(0.30) and nat == pytest.approx(0.34)
    assert debit_to_close(*legs(None, 0.44, 0.10, 0.14)) == (None, pytest.approx(0.34))


def test_profit_take_at_half_the_credit() -> None:
    e = evaluate_exit(pos(), *legs(0.38, 0.42, 0.09, 0.11), 690.0, MIDDAY, CFG)
    assert e is not None and e.reason == "profit_take" and e.close


def test_stop_at_twice_the_credit() -> None:
    e = evaluate_exit(pos(), *legs(1.60, 1.70, 0.40, 0.46), 684.0, MIDDAY, CFG)
    assert e is not None and e.reason == "stop_loss"


def test_short_strike_touch() -> None:
    e = evaluate_exit(pos(), *legs(1.00, 1.10, 0.35, 0.39), 679.5, MIDDAY, CFG)
    assert e is not None and e.reason == "strike_touch"
    assert short_strike_touched(pos(side="call", short_strike=700, long_strike=705), 700.0)


def test_hold_when_nothing_triggers() -> None:
    assert evaluate_exit(pos(), *legs(0.50, 0.54, 0.12, 0.16), 688.0, MIDDAY, CFG) is None


def test_max_hold_closes_a_spread_held_too_long() -> None:
    late = datetime(2026, 10, 7, 18, 31, tzinfo=UTC)  # 14:31 EDT, 151 min after the 12:00 entry
    e = evaluate_exit(pos(), *legs(0.50, 0.54, 0.12, 0.16), 688.0, late, CFG)
    assert e is not None and e.reason == "max_hold" and e.close
    off = CFG.model_copy(update={"exits": CFG.exits.model_copy(update={"max_hold_minutes": None})})
    assert evaluate_exit(pos(), *legs(0.50, 0.54, 0.12, 0.16), 688.0, late, off) is None
    # A losing spread past the hold limit reports the stop, not the hold.
    stop = evaluate_exit(pos(), *legs(1.60, 1.70, 0.40, 0.46), 684.0, late, CFG)
    assert stop is not None and stop.reason == "stop_loss"


# Review Focus 2 — a leg without a usable quote.
def test_no_quote_means_no_decision_before_the_time_stop() -> None:
    assert evaluate_exit(pos(), *legs(-1.0, None, 0.0, 0.05), 688.0, MIDDAY, CFG) is None


def test_time_stop_fires_even_without_a_quote() -> None:
    e = evaluate_exit(pos(), *legs(-1.0, None, 0.0, 0.05), 688.0, CLOSE, CFG)
    assert e is not None and e.reason == "time_stop" and e.close


def test_far_otm_cheap_spread_is_left_to_expire_at_the_time_stop() -> None:
    e = evaluate_exit(pos(), *legs(0.02, 0.05, 0.0, 0.02), 690.0, CLOSE, CFG)
    assert e is not None and e.reason == "expire_worthless" and e.close is False


def test_spy_spreads_are_never_left_to_expire() -> None:
    assert _BASE.exits.let_expire is False  # SPY settles in shares
    spy = CFG.model_copy(update={"exits": CFG.exits.model_copy(update={"let_expire": False})})
    e = evaluate_exit(pos(), *legs(0.02, 0.05, 0.0, 0.02), 690.0, CLOSE, spy)
    assert e is not None and e.reason == "time_stop" and e.close


def test_cheap_but_breached_spread_is_still_closed_at_the_time_stop() -> None:
    e = evaluate_exit(pos(), *legs(0.02, 0.05, 0.0, 0.02), 679.0, CLOSE, CFG)
    assert e is not None and e.reason == "time_stop"


def test_intrinsic_debit_is_capped_at_width() -> None:
    assert intrinsic_debit(pos(), 690.0) == 0.0
    assert intrinsic_debit(pos(), 678.0) == pytest.approx(2.0)
    assert intrinsic_debit(pos(), 600.0) == 5.0
    call = pos(side="call", short_strike=700, long_strike=705)
    assert intrinsic_debit(call, 703.0) == pytest.approx(3.0)


def test_reconcile_agrees_with_a_matching_broker_book() -> None:
    assert reconcile([pos(contracts=2)], {111: -2.0, 222: 2.0}) == []


def test_reconcile_reports_missing_and_unexpected_legs() -> None:
    problems = reconcile([pos()], {111: -1.0, 333: 1.0})
    assert any("222" in p for p in problems) and any("333" in p for p in problems)


def test_reconcile_ignores_shadow_positions() -> None:
    assert reconcile([pos(mode="shadow")], {}) == []
