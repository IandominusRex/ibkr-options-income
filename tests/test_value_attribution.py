"""Share attribution (value book spec §9.2): orderRef through the ledger, the wheel's own count W,
the wheel's view, fail-closed reads and the sell cap. Several of the seven fault drills are pinned
here; tests/test_value_fault_drills.py names all seven."""

from __future__ import annotations

import pytest

from src.common.books import attribute, is_value_order_ref, value_sell_cap
from src.common.value_view import ValueHolding
from tests.value_book_fixtures import order


def test_the_wheel_sees_min_of_its_count_and_broker_less_value() -> None:
    v = ValueHolding("GOOGL", filled=30, pending_buy=10)
    ok = attribute(130, 100, v)
    assert (ok.wheel_view, ok.unexplained) == (90.0, 0.0)  # a pending buy errs short
    untagged = attribute(160, 130, ValueHolding("GOOGL", filled=30))  # a value fill counted twice
    assert untagged.unexplained == 0 and untagged.wheel_view == 130
    missing = attribute(130, 130, ValueHolding("GOOGL", filled=30))
    assert missing.unexplained == -30 and missing.wheel_view == 100  # errs short
    assert attribute(100, 120, ValueHolding("X")).wheel_view == 100  # never above the broker


def test_an_unreadable_value_db_leaves_the_wheel_only_what_the_broker_confirms() -> None:
    assert attribute(100, 100, None).wheel_view == 100
    assert attribute(130, 100, None).wheel_view == 0  # unexplained shares: no covered call


def test_a_value_sell_never_uncovers_a_wheel_call() -> None:
    assert value_sell_cap(30, 130, 1) == 30
    assert value_sell_cap(30, 120, 1) == 20  # the broker holds 20 fewer than the books say
    assert value_sell_cap(30, 100, 1) == 0
    assert is_value_order_ref("value:12") and not is_value_order_ref("CS:7")


def test_a_split_corporate_action_restates_the_wheels_count() -> None:
    from src.storage.wheel_shares import split_ratio

    assert split_ratio("GOOGL(US02079K3059) SPLIT 20 FOR 1 (GOOGL, ...)") == 20.0
    assert split_ratio("XYZ SPLIT 1 FOR 10") == 0.1
    assert split_ratio("XYZ CASH DIVIDEND 0.20 USD") is None


def test_value_exposure_is_nothing_while_the_book_is_off(value_book_db, monkeypatch) -> None:
    from src.common.books import value_exposure
    from src.common.config import get_config

    order("GOOGL", shares=100, filled=100, avg=150.0)
    off = value_exposure()
    assert (off.active, off.claim, off.by_name) == (False, 0.0, {})
    monkeypatch.setattr(get_config().value.book, "enabled", True)
    on = value_exposure()
    assert on.by_name == {"GOOGL": 15_000.0} and on.claim == pytest.approx(11_250.0)
