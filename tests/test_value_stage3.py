"""Stage 3's process side (value book spec §9.7, §7.1; Part 5): the broker snapshot, held
re-evaluations mirrored from the shadow record, held names kept fresh, the notifier, the CLI."""

from __future__ import annotations

import asyncio

from src.common.schemas import OptionRight, PositionSnapshot
from src.value import notify
from src.value.stage3 import build_snapshot


def _p(symbol, sec, qty, **kw) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        sec_type=sec,
        position=qty,
        avg_cost=1.0,
        underlying=kw.pop("underlying", symbol),
        **kw,
    )


def test_the_snapshot_is_the_brokers_whole_view() -> None:
    snap = build_snapshot(
        [
            _p("GOOGL", "STK", 130, market_price=150.0),
            _p("GOOGL C", "OPT", -1, underlying="GOOGL", right=OptionRight.CALL, strike=180.0),
            _p("AAPL P", "OPT", -2, underlying="AAPL", right=OptionRight.PUT, strike=200.0),
        ],
        100_000.0,
    )
    assert snap.shares == {"GOOGL": 130} and snap.marks == {"GOOGL": 150.0}
    assert snap.wheel_short_calls == {"GOOGL": 1} and snap.csp_by_name == {"AAPL": 40_000.0}
    assert (snap.stock_value, snap.csp_collateral) == (19_500.0, 40_000.0)


def test_the_notifier_logs_and_sends_nothing_without_a_token() -> None:
    assert asyncio.run(notify.send(["Value book: test"])) == 0
