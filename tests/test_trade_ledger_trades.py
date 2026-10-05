"""Orders, FIFO, option trades, outcomes, rolls, orphans, annotations (spec §4.1–4.2; R3, R4, R9, R10)."""

from __future__ import annotations

import itertools
from datetime import date

import pytest

from src.ledger.contracts import et_date, parse_et_timestamp, parse_option_symbol, stock_contract
from src.reporting.trade_ledger import (
    LedgerAnnotation,
    LedgerExec,
    apply_annotations,
    build_option_trades,
    group_orders,
)

_ids = itertools.count(1)
TODAY = date(2026, 10, 5)


def ex(
    symbol: str,
    when: str,
    qty: float,
    price: float,
    *,
    comm: float = -1.0,
    codes: str = "",
    perm: int | None = None,
    book: str = "manual",
    multiplier: float = 100.0,
    realized: float | None = None,
    currency: str = "USD",
) -> LedgerExec:
    contract = (
        parse_option_symbol(symbol, currency=currency, multiplier=multiplier)
        if " " in symbol
        else stock_contract(symbol, currency)
    )
    ts = parse_et_timestamp(when)
    return LedgerExec(
        row_id=next(_ids),
        contract=contract,
        trade_time=ts,
        trade_date=et_date(ts),
        quantity=qty,
        price=price,
        proceeds=-qty * price * contract.multiplier,
        commission=comm,
        codes=codes,
        perm_id=perm,
        book=book,
        ibkr_realized_pnl=realized,
    )


def trades_of(*execs: LedgerExec, today: date = TODAY):
    trades, orphans = build_option_trades(group_orders(list(execs)), today=today)
    return trades, orphans


def test_sheet_formula_nvda_bought_back_for_a_penny() -> None:
    (t,), _ = trades_of(
        ex("NVDA 27JUN25 138 P", "2025-06-17, 10:02:11", -1, 1.31, codes="O"),
        ex("NVDA 27JUN25 138 P", "2025-06-27, 11:09:57", 1, 0.01, codes="C"),
    )
    assert (t.side, t.right, t.lots, t.premium, t.dte) == ("Sell", "P", 1.0, 131.0, 10)
    assert round(t.pct_profit, 2) == 34.65
    assert t.outcome == "Bought back"  # R9: IBKR recorded a $0.01 buy-back, not an expiry
    assert t.net_pnl == pytest.approx(131 - 1 - 1 - 1)
    assert t.capital == 13800.0


def test_sheet_formula_amzn_expired() -> None:
    (t,), _ = trades_of(
        ex("AMZN 18JUL25 207.5 P", "2025-06-25, 13:17:15", -1, 3.25, codes="O"),
        ex("AMZN 18JUL25 207.5 P", "2025-07-18, 16:20:00", 1, 0.0, comm=0.0, codes="C;Ep"),
    )
    assert t.outcome == "Expired"
    assert round(t.pct_profit, 2) == 24.86
    assert t.close_date == date(2025, 7, 18)


def test_partial_fills_merge_into_one_order() -> None:
    (t,), _ = trades_of(
        ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:00", -1, 1.93, perm=9),
        ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:01", -1, 1.94, perm=9),
    )
    assert t.lots == 2.0 and t.premium == pytest.approx(387.0)
    assert len(t.exec_row_ids) == 2


def test_partial_close_stays_open_then_pending_after_expiry() -> None:
    legs = (
        ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:00", -2, 1.9),
        ex("NVDA 25JUL25 170 P", "2025-07-21, 10:00:00", 1, 0.5, codes="C"),
    )
    (t,), _ = trades_of(*legs, today=date(2025, 7, 22))
    assert t.outcome == "Open" and t.net_pnl is None and len(t.closes) == 1
    (t2,), _ = trades_of(*legs, today=date(2025, 7, 28))
    assert t2.outcome == "Pending"  # R10


def test_mixed_close_takes_the_largest_and_flags_it() -> None:
    (t,), _ = trades_of(
        ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:00", -3, 1.9),
        ex("NVDA 25JUL25 170 P", "2025-07-21, 10:00:00", 1, 0.5, codes="C"),
        ex("NVDA 25JUL25 170 P", "2025-07-25, 16:20:00", 2, 0.0, comm=0.0, codes="C;Ep"),
    )
    assert t.outcome == "Expired" and t.mixed_close is True


@pytest.mark.parametrize(
    ("symbol", "open_qty", "close_codes", "expected"),
    [
        ("AMZN 10OCT25 215 P", -1, "A;C", "Assigned"),
        ("AMZN 31OCT25 235 C", -1, "A;C", "Called away"),
        ("OPEN 19SEP25 3 C", 4, "C;Ex", "Exercised"),
    ],
)
def test_assignment_and_exercise_outcomes(symbol, open_qty, close_codes, expected) -> None:
    (t,), _ = trades_of(
        ex(symbol, "2025-09-01, 10:00:00", open_qty, 1.0, codes="O"),
        ex(symbol, "2025-10-31, 16:20:00", -open_qty, 0.0, comm=0.0, codes=close_codes),
    )
    assert t.outcome == expected


def test_long_option_has_no_sheet_percentage() -> None:
    (t,), _ = trades_of(
        ex("OPEN 19SEP25 3 C", "2025-07-21, 10:00:00", 4, 1.2, codes="O"),
        ex("OPEN 19SEP25 3 C", "2025-09-19, 16:20:00", -4, 0.0, comm=0.0, codes="C;Ex"),
    )
    assert t.side == "Buy" and t.premium == pytest.approx(-480.0)
    assert t.pct_profit is None and t.capital == pytest.approx(480.0)


def test_same_session_buyback_and_new_short_is_a_roll() -> None:
    trades, _ = trades_of(
        ex("NVDA 18JUL25 170 P", "2025-07-11, 10:00:00", -1, 2.0, codes="O"),
        ex("NVDA 18JUL25 170 P", "2025-07-16, 10:00:00", 1, 1.0, codes="C"),
        ex("NVDA 25JUL25 165 P", "2025-07-16, 10:00:00", -1, 1.6, codes="O"),
    )
    first, second = sorted(trades, key=lambda t: t.open_time)
    assert first.outcome == "Rolled" and first.rolled_to == second.order_key
    assert second.rolled_from == first.order_key


def test_order_key_is_the_same_for_a_csv_order_and_its_exec_fills() -> None:
    csv_order = group_orders([ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -2, 1.935)])
    fills = group_orders(
        [
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.93, perm=7),
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:01", -1, 1.94, perm=7),
        ]
    )
    assert csv_order[0].order_key == fills[0].order_key
    assert len(csv_order[0].order_key) == 16


def test_order_key_ignores_a_vwap_gap_between_csv_and_exec_twin() -> None:
    """F18: price is deliberately excluded from the order_key signature. Task 4's twin pass
    tolerates up to a 0.005 VWAP gap between a CSV order row and its exec-level twin; if price
    were part of the key, a superseding twin would hash to a different key and any annotation
    keyed on the CSV order's key would silently detach from it."""
    csv_order = group_orders([ex("AMD 29AUG25 157.5 P", "2025-08-14, 10:00:00", -2, 1.3100)])
    fills = group_orders(
        [
            ex("AMD 29AUG25 157.5 P", "2025-08-14, 10:00:00", -1, 1.3100, perm=11),
            ex("AMD 29AUG25 157.5 P", "2025-08-14, 10:00:01", -1, 1.3174, perm=11),
        ]
    )
    assert fills[0].price == pytest.approx(1.3137)
    assert csv_order[0].order_key == fills[0].order_key


def test_an_order_that_closes_and_opens_splits() -> None:
    trades, _ = trades_of(
        ex("NVDA 18JUL25 170 P", "2025-07-11, 10:00:00", -1, 2.0),
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", 3, 1.0),
    )
    short, long = sorted(trades, key=lambda t: t.open_time)
    assert short.outcome == "Bought back" and short.closes[0].quantity == 1
    assert long.side == "Buy" and long.lots == 2.0
    assert long.premium == pytest.approx(-200.0)


def test_an_order_that_closes_and_opens_splits_with_realistic_codes() -> None:
    """IBKR gives a crossing order (closes the old position, opens a new one in the same fill)
    the code pair ``C;O``, not a bare ``C``. ``is_closing`` must not treat that as a pure close —
    otherwise the leftover 2 lots never become a new opening and the order is misrouted to the
    orphan list instead of splitting into a close + a new long, exactly as the bare-code variant
    above does."""
    trades, orphans = trades_of(
        ex("NVDA 18JUL25 170 P", "2025-07-11, 10:00:00", -1, 2.0, codes="O"),
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", 3, 1.0, codes="C;O"),
    )
    assert orphans == []
    short, long = sorted(trades, key=lambda t: t.open_time)
    assert short.outcome == "Bought back" and short.closes[0].quantity == 1
    assert long.side == "Buy" and long.lots == 2.0
    assert long.premium == pytest.approx(-200.0)


def test_orphan_close_is_reported_not_turned_into_a_long() -> None:
    # Review Focus 1: the statement starts after the put was sold.
    trades, orphans = trades_of(
        ex("NVDA 11APR25 100 P", "2025-04-04, 10:00:00", 1, 0.2, codes="C", realized=150.0),
    )
    assert trades == []
    assert len(orphans) == 1 and orphans[0].ibkr_realized_pnl == 150.0


def test_non_100_multiplier_drives_premium_and_capital() -> None:
    # Review Focus 5.
    (t,), _ = trades_of(ex("OPEN1 19DEC25 5 C", "2025-11-20, 10:00:00", -2, 0.5, multiplier=50.0))
    assert t.premium == pytest.approx(50.0)
    assert t.capital == pytest.approx(5 * 50 * 2)
    assert t.pct_profit == pytest.approx(t.premium / t.capital * 365 / t.dte * 100)


def test_annotation_override_and_notes() -> None:
    (t,), _ = trades_of(
        ex("NVDA 27JUN25 138 P", "2025-06-17, 10:02:11", -1, 1.31, codes="O"),
        ex("NVDA 27JUN25 138 P", "2025-06-27, 11:09:57", 1, 0.01, codes="C"),
    )
    apply_annotations(
        [t],
        {
            t.order_key: LedgerAnnotation(
                order_key=t.order_key,
                notes="treat as expired",
                tags=["earnings"],
                outcome_override="Expired",
                exclude_from_stats=False,
            )
        },
    )
    assert (t.outcome, t.computed_outcome, t.outcome_overridden) == ("Expired", "Bought back", True)
    assert t.notes == "treat as expired" and t.tags == ["earnings"]
