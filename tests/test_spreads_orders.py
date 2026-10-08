from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.schemas import SpreadCandidate, SpreadPosition
from src.spreads.orders import (
    build_close_order,
    build_open_order,
    credit_ladder,
    debit_ladder,
    round_tick,
)

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)


def cand(**kw) -> SpreadCandidate:
    base = dict(
        spread_id="s1",
        side="put",
        expiry=date(2026, 10, 7),
        short_strike=679.0,
        long_strike=674.0,
        width=5.0,
        short_con_id=111,
        long_con_id=222,
        credit_mid=0.61,
        credit_natural=0.56,
        spot=690.0,
        quote_time=NOW,
    )
    base.update(kw)
    return SpreadCandidate(**base)


def test_open_order_sells_the_short_buys_the_long_at_a_negative_limit() -> None:
    bag, order = build_open_order("XSP", cand(), 2, 0.61, "CS:s1")
    assert bag.secType == "BAG" and bag.symbol == "XSP"
    assert [(leg.conId, leg.action, leg.ratio) for leg in bag.comboLegs] == [
        (111, "SELL", 1),
        (222, "BUY", 1),
    ]
    assert (order.action, order.totalQuantity, order.lmtPrice) == ("BUY", 2, -0.61)
    assert order.orderRef == "CS:s1" and order.tif == "DAY" and order.orderType == "LMT"


def test_close_order_reverses_the_legs_at_a_positive_limit() -> None:
    pos = SpreadPosition(
        spread_id="s1",
        mode="paper",
        side="put",
        expiry=date(2026, 10, 7),
        short_strike=679.0,
        long_strike=674.0,
        width=5.0,
        contracts=1,
        entry_credit=0.6,
        opened_at=NOW,
        short_con_id=111,
        long_con_id=222,
    )
    bag, order = build_close_order("XSP", pos, 1, 0.30, "CS:s1:X")
    assert [(leg.conId, leg.action) for leg in bag.comboLegs] == [(111, "BUY"), (222, "SELL")]
    assert (order.action, order.lmtPrice) == ("BUY", 0.30)


def test_orders_refuse_unqualified_legs_and_bad_prices() -> None:
    with pytest.raises(ValueError):
        build_open_order("XSP", cand(short_con_id=None), 1, 0.6, "CS:s1")
    with pytest.raises(ValueError):
        build_open_order("XSP", cand(), 0, 0.6, "CS:s1")
    with pytest.raises(ValueError):
        build_open_order("XSP", cand(), 1, 0.0, "CS:s1")


def test_ladders() -> None:
    assert round_tick(0.6049) == 0.60 and round_tick(-0.61) == -0.61
    assert credit_ladder(0.61, 0.56, 3, 0.01, 0.50) == [0.61, 0.60, 0.59]
    assert credit_ladder(0.61, 0.56, 5, 0.01, 0.60) == [0.61, 0.60]
    assert credit_ladder(0.45, 0.40, 3, 0.01, 0.50) == []
    assert debit_ladder(0.30, 3, 0.01, 0.40) == [0.30, 0.31, 0.32]
    assert debit_ladder(0.30, 3, 0.01, 0.31) == [0.30, 0.31]


# Review I4 — the operator check reads IBKR's fill-price sign, which the executor relies on.
def test_combo_check_reads_the_fill_sign() -> None:
    from scripts.spreads_combo_check import fill_sign_verdict

    assert fill_sign_verdict("open", -0.42).startswith("OK")
    assert fill_sign_verdict("open", 0.42).startswith("MISMATCH")
    assert fill_sign_verdict("close", 0.10).startswith("OK")
    assert fill_sign_verdict("close", -0.10).startswith("MISMATCH")
