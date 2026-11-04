"""The wheel's side of the value book (value book spec §9.2-§9.3 as amended by revision 4): the
value claim on excess liquidity, the gross and combined caps, the attribution freeze, and
capital release - the selection, the Rules Engine's release gate and the runner."""

from __future__ import annotations

import pytest

from src.common.config import get_config
from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot
from src.engine.capital import ReleaseCandidate, resolve_caps, seed_budgets, select_releases
from src.engine.risk_engine import validate_candidates, validate_release
from src.value.store import ValueAttributionRow, value_session
from tests.test_engine import _candidate
from tests.value_book_fixtures import NOW, order, proposal

RELEASE = get_config().value.book.release.model_dump()


@pytest.fixture()
def book_on(monkeypatch):
    monkeypatch.setattr(get_config().value.book, "enabled", True)


def _acct(net_liq: float = 100_000.0, excess: float = 60_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=net_liq,
        total_cash=excess,
        buying_power=excess,
        maintenance_margin=0.0,
        excess_liquidity=excess,
    )


def test_the_value_claim_comes_off_excess_liquidity_before_the_reserve() -> None:
    risk = {"portfolio": {"cash_reserve_pct": 20.0, "cash_reserve_absolute": 0}}
    assert resolve_caps(_acct(), risk).deployable_cash == pytest.approx(48_000.0)
    # $20,000 of value stock at 25% maintenance claims $15,000; reserve 20% of 45,000
    assert resolve_caps(_acct(), risk, value_claim=15_000.0).deployable_cash == pytest.approx(
        36_000.0
    )
    budgets = seed_budgets([], lambda s: None, extra_exposure={"GOOGL": 20_000.0})
    assert budgets.ticker_collateral == {"GOOGL": 20_000.0}


def test_with_the_book_off_the_wheel_is_unchanged(value_book_db) -> None:
    order("AAPL", shares=100, filled=100, avg=150.0)  # a value holding the wheel would count
    big = _candidate(collateral=90_000.0, contracts=1)
    before = validate_candidates([big], _acct(), [])[0].reasons
    assert "gross_notional_cap" not in before and "combined_name_cap" not in before


def test_the_gross_cap_counts_both_books_and_approved_buys(value_book_db, book_on) -> None:
    order("GOOGL", shares=100, filled=100, avg=150.0)  # $15,000 of value stock at cost
    proposal("META", status="funding", cost=30_000.0)  # approved, not yet bought: earmarked
    stock = PositionSnapshot(
        symbol="MSFT",
        sec_type="STK",
        position=100,
        avg_cost=380.0,
        market_value=40_000.0,
        underlying="MSFT",
    )
    # 40,000 wheel stock + 15,000 value + 30,000 earmarked + 16,000 put = 101,000 > 100,000
    out = validate_candidates([_candidate(collateral=16_000.0)], _acct(), [stock])[0].reasons
    assert "gross_notional_cap" in out
    ok = validate_candidates([_candidate(collateral=14_000.0)], _acct(), [stock])[0].reasons
    assert "gross_notional_cap" not in ok


def test_the_combined_name_cap_and_the_freeze(value_book_db, book_on) -> None:
    order("AAPL", shares=50, filled=50, avg=150.0)  # $7,500 of AAPL in the value book
    over = validate_candidates([_candidate(collateral=8_000.0)], _acct(), [])[0].reasons
    assert "combined_name_cap" in over  # 7,500 + 8,000 > 15% of 100,000
    with value_session() as s:
        s.add(
            ValueAttributionRow(
                symbol="AAPL",
                broker=150,
                wheel=100,
                value_filled=50,
                state="frozen",
                updated_at=NOW,
            )
        )
    frozen = validate_candidates([_candidate(collateral=1_000.0)], _acct(), [])[0].reasons
    assert "book_attribution_mismatch" in frozen


def test_an_unreadable_value_db_refuses_new_puts(monkeypatch, tmp_path, book_on) -> None:
    bad = tmp_path / "value.db"
    bad.write_bytes(b"garbage")
    monkeypatch.setattr("src.common.value_view._path", lambda: bad)
    out = validate_candidates([_candidate(collateral=1_000.0)], _acct(), [])[0].reasons
    assert "value_book_unreadable" in out


def _c(key: str, strike: float, credit: float, mid: float, contracts: int = 1) -> ReleaseCandidate:
    return ReleaseCandidate(
        key, key.split(":")[0], strike, contracts, credit, mid - 0.05, mid + 0.05
    )


def test_the_fewest_closes_that_cover_the_need_never_a_partial_one() -> None:
    a = _c("AAA:1", 100.0, 2.0, 1.0)  # 50% kept, frees 10,000
    b = _c("BBB:1", 150.0, 2.0, 1.8)  # 10% kept, frees 15,000
    c = _c("CCC:1", 60.0, 1.0, 0.2)  # 80% kept, frees 6,000
    assert select_releases([a, b, c], 14_000.0, RELEASE) == [b]  # one close covers it
    assert select_releases([a, b, c], 9_000.0, RELEASE) == [a]  # both A-tier would; least given up
    assert select_releases([a, c], 15_000.0, RELEASE) == [a, c]
    assert select_releases([a, c], 17_000.0, RELEASE) == []  # not enough: release nothing
    assert select_releases([a], 0.0, RELEASE) == []


def test_the_release_gate_never_closes_at_a_loss_or_a_call_and_caps_the_day() -> None:
    win = _c("AAA:1", 100.0, 2.0, 1.0)
    loss = _c("BBB:1", 100.0, 2.0, 2.2)
    args = dict(closes_today=0, released_today=0.0, net_liq=100_000.0)
    assert validate_release(win, right=OptionRight.PUT, **args) == []
    assert "release_at_loss" in validate_release(loss, right=OptionRight.PUT, **args)
    assert "release_not_csp" in validate_release(win, right=OptionRight.CALL, **args)
    capped = validate_release(
        win, right=OptionRight.PUT, closes_today=4, released_today=5_000.0, net_liq=100_000.0
    )
    assert capped == ["release_daily_cap", "release_daily_notional"]  # 15,000 > 10% of 100,000
    wide = ReleaseCandidate("W:1", "W", 100.0, 1, 2.0, 0.5, 1.5)
    assert "release_spread_too_wide" in validate_release(wide, right=OptionRight.PUT, **args)
