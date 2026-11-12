"""Fix pass for the whole-branch review of the roll redesign (2026-10-11).

One test per Important finding; each failed before its fix.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.common.config import RollCfg
from src.common.schemas import OptionRight
from tests.test_roll_evaluate import wired  # noqa: F401 — fixture reuse

# --- 1. a missing roll: block is loud ------------------------------------------------------


def test_a_settings_file_without_a_roll_block_warns(caplog: pytest.LogCaptureFixture) -> None:
    from src.common.config import _warn_if_roll_block_missing

    with caplog.at_level(logging.WARNING):
        _warn_if_roll_block_missing({"monitor": {}})
    assert "roll:" in caplog.text and "config/examples/settings.yaml" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        _warn_if_roll_block_missing({"roll": {}})
    assert caplog.text == ""


# --- 2. the Rules Engine enforces roll economics --------------------------------------------


def test_the_engine_enforces_the_roll_floor_strike_direction_size_and_debit_rights() -> None:
    from tests.test_risk_engine_roll import _reasons, _roll, roll_from

    assert "roll_net_below_floor" in _reasons(_roll(premium=0.01))
    put_debit = roll_from().model_copy(update={"allow_debit": True})
    assert "roll_debit_not_allowed" in _reasons(_roll(premium=-0.10, roll_from=put_debit))
    assert "roll_strike_worse" in _reasons(_roll(strike=155.0))  # put above the old 150
    assert "roll_contracts_mismatch" in _reasons(_roll(contracts=3))
    call_origin = roll_from().model_copy(update={"right": OptionRight.CALL, "allow_debit": True})
    call = _roll(right=OptionRight.CALL, strike=155.0, premium=-0.20, roll_from=call_origin)
    assert not {"roll_net_below_floor", "roll_debit_not_allowed"} & set(_reasons(call))
    assert "roll_net_below_floor" in _reasons(call.model_copy(update={"premium": -0.30}))


# --- 3. ex-dividend: ITM calls only, and only an upcoming ex-date ---------------------------


def test_an_otm_call_never_gets_an_ex_div_trigger() -> None:
    from src.strategies.roll_policy import roll_trigger
    from tests.test_roll_policy import _TODAY, _call_fund, _pos, _q

    pos = _pos(OptionRight.CALL, 100.0, days=20)
    otm = _q(100.0, 20, 0.15, 0.10, OptionRight.CALL, spot=95.0)  # mid 0.15 < dividend
    assert roll_trigger(pos, otm, _call_fund(), RollCfg(), ex_div_guard=True, today=_TODAY) is None


def test_a_past_ex_date_does_not_reject_a_call_roll() -> None:
    from tests.test_rolling_construct import _OLD, _TODAY, _W1, _build, _ctx, q

    ctx = _ctx(
        right=OptionRight.CALL,
        strike=320.0,
        ex_div_date=_TODAY - timedelta(days=30),
        dividend=0.24,
        current=q(320.0, _OLD, 5.05, 0.80, OptionRight.CALL),
    )
    cand, rej = _build(ctx, [q(320.0, _W1, 5.10, 0.78, OptionRight.CALL)])
    assert cand is not None, rej


# --- 4. a declined roll is not re-proposed the same day -------------------------------------


@pytest.mark.parametrize("status", ["rejected", "expired"])
async def test_a_declined_roll_is_not_reproposed_today(wired, db, status) -> None:  # noqa: F811
    from src.execution.roll_pipeline import evaluate_roll
    from src.storage.models import ApprovalRow
    from tests.test_roll_evaluate import _pos

    first, approval_id = await evaluate_roll(MagicMock(), _pos(), chat_id="1", ttl_minutes=30)
    assert first.action == "roll"
    with db() as s:
        row = s.get(ApprovalRow, approval_id)
        row.status = status
        row.decided_at = datetime.now(UTC).replace(tzinfo=None)
    again, again_id = await evaluate_roll(MagicMock(), _pos(), chat_id="1", ttl_minutes=30)
    assert (again.action, again.reason, again_id) == ("defer", "roll_declined_today", None)
    manual, manual_id = await evaluate_roll(
        MagicMock(), _pos(), chat_id="1", ttl_minutes=30, manual=True
    )
    assert manual.action == "roll" and manual_id is not None  # the operator asked explicitly


# --- 5. the executor never prices a leg off a stale last print ------------------------------


async def test_a_one_sided_old_leg_is_refused_not_priced_off_last(tmp_path, monkeypatch) -> None:
    from src.common.schemas import OrderState
    from tests.test_roll_executor import (
        _cfg,
        _db_setup,
        _make_ib,
        _no_sleep,
        _roll_candidate,
        _run,
        _short,
        _ticker,
    )

    _db_setup(tmp_path, monkeypatch)
    _no_sleep(monkeypatch)
    _cfg(monkeypatch, steps=0)
    ib = _make_ib(new_mid=(1.78, 1.82), old_mid=(0.78, 0.82))
    old = _ticker(-1.0, 0.82, -0.55)  # IBKR's -1 "no bid" sentinel
    old.bid = None
    old.last = 0.10  # stale print: would fake a 1.70 credit
    ib.reqMktData.side_effect = [_ticker(1.78, 1.82, -0.50), old]
    state, detail, _ = await _run(monkeypatch, _roll_candidate(), ib, [_short()])
    assert state == OrderState.REJECTED and "two-sided" in detail
    ib.placeOrder.assert_not_called()


# --- 6. recorded leg prices net to the combo's actual fill ----------------------------------


async def test_fallback_leg_prices_net_to_the_actual_combo_fill(tmp_path, monkeypatch) -> None:
    from src.storage.db import session_scope
    from src.storage.models import FillRow
    from tests.test_roll_executor import (
        _cfg,
        _db_setup,
        _make_ib,
        _no_sleep,
        _roll_candidate,
        _run,
        _short,
    )

    _db_setup(tmp_path, monkeypatch)
    _no_sleep(monkeypatch)
    _cfg(monkeypatch, steps=0)
    ib = _make_ib(new_mid=(1.78, 1.82), old_mid=(0.78, 0.82))  # mid net 1.00
    trade = ib.placeOrder.return_value
    trade.fills = []  # broker reported no per-leg fills
    trade.orderStatus.avgFillPrice = -0.90  # filled at a 0.90 credit after concession
    await _run(monkeypatch, _roll_candidate(premium=0.40), ib, [_short()])
    with session_scope() as s:
        sell = s.query(FillRow).filter_by(action="SELL").one()
        buy = s.query(FillRow).filter_by(action="BUY").one()
        assert sell.avg_price - buy.avg_price == pytest.approx(0.90)


# --- 7. chain attribution ------------------------------------------------------------------


def test_the_buyback_is_booked_under_the_rolled_from_candidate(db) -> None:
    from src.execution.roll_executor import _close_candidate_id
    from tests.test_roll_executor import _roll_candidate, _short

    origin = _roll_candidate().roll_from.model_copy(update={"candidate_id": "c-exact"})
    cand = _roll_candidate().model_copy(update={"roll_from": origin})
    assert _close_candidate_id(_short(), cand) == "c-exact"


def test_a_chain_from_an_outside_short_includes_its_buyback(db) -> None:
    from src.common.schemas import RollOrigin
    from src.storage.roll_chains import chain_entry_credit_per_share, synthetic_close_id
    from tests.test_roll_chains import _NEW_EXP, _OLD_EXP, _pos, _seed

    origin = RollOrigin(
        con_id=1,
        candidate_id=None,
        strike=335.0,
        expiry=_OLD_EXP,
        right=OptionRight.PUT,
        contracts=1,
        chain_id="x",
        seq=1,
        original_expiry=_OLD_EXP,
        old_mid=3.0,
        new_mid=3.2,
    )
    close_id = synthetic_close_id("GOOGL", _OLD_EXP, 335.0, "P")
    _seed(db, close_id, 335.0, _OLD_EXP, [("BUY", 1, 3.00, 0.0)])
    _seed(
        db,
        "c-new",
        330.0,
        _NEW_EXP,
        [("SELL", 1, 3.20, 0.0)],
        payload={"roll_from": origin.model_dump(mode="json")},
    )
    with db() as s:
        assert chain_entry_credit_per_share(s, _pos()) == pytest.approx(0.20)


# --- 8. a partial close of the open leg does not shrink its credit --------------------------


def test_a_partial_close_of_the_open_leg_keeps_its_entry_credit(db) -> None:
    from src.storage.roll_chains import chain_entry_credit_per_share
    from tests.test_roll_chains import _NEW_EXP, _pos, _seed

    _seed(db, "c-multi", 330.0, _NEW_EXP, [("SELL", 2, 1.50, 0.0), ("BUY", 1, 0.70, 0.0)])
    with db() as s:
        assert chain_entry_credit_per_share(s, _pos(qty=-1)) == pytest.approx(1.50)


@pytest.fixture(autouse=True)
def _no_roll_down_rule(monkeypatch):
    """These tests predate the ITM roll-down rule (2026-11-12) and use same-strike rolls of an
    in-the-money put; the rule has its own tests (tests/test_roll_down_rule.py)."""
    from src.common.config import get_config

    monkeypatch.setattr(get_config().roll.csp, "itm_min_basis_drop_pct", None)
