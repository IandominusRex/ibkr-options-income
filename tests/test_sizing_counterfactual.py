"""Task 15: the counterfactual resolver and its report.

`sizing_actions` rows say what the market regime, the leveraged-ETF ceiling, a floor lot or
Claude's cut did to a cash-secured put's size. This module's job is to say later what the
difference earned, so a human can decide whether the limits (and Claude's overrides) paid before
the live cutover. Two kinds of value, kept apart: EXACT (the contracts that were not withheld
traded, so the withheld ones are valued at the traded contract's realised P&L per contract) and
SHADOW (nothing traded: marked to expiry, and under the system's own profit-take and loss-exit
rules with Black-Scholes at the entry IV). Read by a human; nothing here reaches a gate."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.analytics.black_scholes import bs_price
from src.claude.eval import sizing_counterfactual as sc
from src.claude.eval.sizing_counterfactual import resolve_actions, summarize
from src.common.universe import is_leveraged_etf
from src.storage.models import FillRow, OrderRow, PriceHistoryRow, SizingActionRow

ACTION_DAY = date(2026, 11, 2)
EXPIRY = date(2026, 11, 20)
NOW = datetime(2026, 11, 30, 21, tzinfo=UTC)  # after the expiry


@pytest.fixture(autouse=True)
def _no_network(monkeypatch) -> None:
    """The provider fallback for missing bars must never run for real in a test."""
    monkeypatch.setattr(sc, "_provider_closes", lambda symbol, start, end: {})


def _row(db, **kw) -> int:
    base: dict = dict(
        candidate_id="c1",
        underlying="AAPL",
        strategy="cash_secured_put",
        right="P",
        strike=60.0,
        expiry=EXPIRY,
        premium=1.5,
        kind="regime_ceiling",
        regime="stressed",
        deterministic_contracts=10,
        sent_contracts=3,
        reason="x",
        action_day=ACTION_DAY,
        entry_iv=50.0,
        record_key="c1",
    )
    base.update(kw)
    with db() as s:
        row = SizingActionRow(**base)
        s.add(row)
        s.flush()
        return row.id


def _get(db, row_id: int) -> SizingActionRow:
    with db() as s:
        row = s.get(SizingActionRow, row_id)
        s.expunge(row)
        return row


def _bars(db, symbol: str, closes: dict[date, float]) -> None:
    with db() as s:
        for d, c in closes.items():
            s.add(PriceHistoryRow(symbol=symbol, obs_date=d, open=c, high=c, low=c, close=c))


def _flat(symbol: str, db, price: float, *, start: date = ACTION_DAY, end: date = EXPIRY) -> None:
    """A close on every weekday from *start* to *end*."""
    closes, d = {}, start
    while d <= end:
        if d.weekday() < 5:
            closes[d] = price
        d += timedelta(days=1)
    _bars(db, symbol, closes)


def _order(
    db,
    candidate_id: str = "c1",
    *,
    state: str = "filled",
    filled: float = 3,
    expiry: date = EXPIRY,
    strike: float = 60.0,
) -> int:
    with db() as s:
        order = OrderRow(
            candidate_id=candidate_id,
            state=state,
            filled_qty=filled,
            snapshot={
                "candidate_id": candidate_id,
                "underlying": "AAPL",
                "strategy": "cash_secured_put",
                "right": "P",
                "strike": strike,
                "expiry": expiry.isoformat(),
                "contracts": 3,
            },
        )
        s.add(order)
        s.flush()
        return order.id


def _fills(
    db,
    order_id: int,
    candidate_id: str = "c1",
    *,
    sold: tuple[float, float] = (3, 1.5),
    bought: tuple[float, float] | None = None,
    commission: float = 0.0,
) -> None:
    with db() as s:
        s.add(
            FillRow(
                order_id=order_id,
                candidate_id=candidate_id,
                action="SELL",
                filled_qty=sold[0],
                avg_price=sold[1],
                commission=commission,
                filled_at=datetime(2026, 11, 2, 15),
            )
        )
        if bought is not None:
            s.add(
                FillRow(
                    order_id=order_id + 100,
                    candidate_id=candidate_id,
                    action="BUY",
                    filled_qty=bought[0],
                    avg_price=bought[1],
                    commission=0.0,
                    close_reason="profit_take",
                    filled_at=datetime(2026, 11, 9, 15),
                )
            )


# --------------------------------------------------------------------------- #
# Exact: the traded contract's realised P&L
# --------------------------------------------------------------------------- #


def test_partial_cut_is_valued_at_the_traded_legs_realised_pnl(db) -> None:
    oid = _order(db, filled=3)
    _fills(db, oid, sold=(3, 1.5), bought=(3, 0.5), commission=6.0)
    rid = _row(db, order_id=oid, deterministic_contracts=10, sent_contracts=3)
    assert resolve_actions(NOW) == 1

    row = _get(db, rid)
    # ((1.50 - 0.50) x 100 x 3 - 6.00 commission) / 3 contracts = $98 per contract
    assert row.realized_pnl_per_contract == pytest.approx(98.0)
    # 7 contracts were withheld: valued at what the 3 that traded earned each.
    assert row.shadow_pnl_expiry == pytest.approx(98.0 * 7)
    assert row.shadow_pnl_rules == pytest.approx(98.0 * 7)  # exact: both columns agree
    assert row.resolved_at is not None


def test_a_traded_lot_that_is_still_open_waits(db) -> None:
    oid = _order(db, filled=3)
    _fills(db, oid)  # sold, never bought back
    future = NOW.date() + timedelta(days=30)
    rid = _row(db, order_id=oid, expiry=future)
    assert resolve_actions(NOW) == 0
    assert _get(db, rid).resolved_at is None


def test_an_expired_traded_lot_marks_an_assignment_at_the_expiry_close(db) -> None:
    oid = _order(db, filled=3)
    _fills(db, oid, sold=(3, 1.5), commission=3.0)  # no buy-back: it ran to expiry
    _flat("AAPL", db, 55.0)  # closed at 55 against a 60 strike: $5 of intrinsic
    rid = _row(db, order_id=oid, deterministic_contracts=5, sent_contracts=3)
    resolve_actions(NOW)
    row = _get(db, rid)
    # (1.50 - 5.00) x 100 - $1 commission per contract
    assert row.realized_pnl_per_contract == pytest.approx(-351.0)
    assert row.shadow_pnl_expiry == pytest.approx(-351.0 * 2)


def test_a_trim_the_gate_later_cancelled_is_not_valued_as_a_traded_lot(db) -> None:
    """The order never filled, so the trimmed `sent` was never sent and nothing was prevented
    from sending by the trim: the row is moot (withheld 0), not valued at a leg that never was."""
    oid = _order(db, state="cancelled", filled=0)
    rid = _row(db, order_id=oid, deterministic_contracts=10, sent_contracts=3)
    assert resolve_actions(NOW) == 1
    row = _get(db, rid)
    assert row.realized_pnl_per_contract is None
    assert (row.shadow_pnl_expiry, row.shadow_pnl_rules) == (0.0, 0.0)
    assert row.resolved_at is not None
    assert summarize(ACTION_DAY)["regime_ceiling:sent_smaller"]["contracts_withheld"] == 0


def test_a_working_order_is_left_alone(db) -> None:
    oid = _order(db, state="submitted", filled=0)
    rid = _row(db, order_id=oid)
    assert resolve_actions(NOW) == 0
    assert _get(db, rid).resolved_at is None


# --------------------------------------------------------------------------- #
# Shadow: nothing traded
# --------------------------------------------------------------------------- #


def test_cut_to_zero_is_valued_to_expiry_and_under_the_exit_rules(db) -> None:
    """A name pushed far out of the money at once: the profit take fires on the first close, so
    the exit-rule mark is a hair under the expiry mark (the put's remaining value)."""
    _bars(db, "AAPL", {ACTION_DAY: 80.0, EXPIRY: 80.0})
    rid = _row(
        db,
        kind="claude_cut",
        deterministic_contracts=3,
        sent_contracts=0,
        premium=1.5,
        entry_iv=40.0,
    )
    resolve_actions(NOW)
    row = _get(db, rid)
    assert row.shadow_pnl_expiry == pytest.approx(1.5 * 100 * 3)  # expired worthless
    v0 = bs_price(80.0, 60.0, (EXPIRY - ACTION_DAY).days, 0.40, "P")
    assert v0 is not None and v0 <= 0.75  # the profit take (50%) fires on the first close
    assert row.shadow_pnl_rules == pytest.approx((1.5 - v0) * 100 * 3)
    assert row.shadow_pnl_rules < row.shadow_pnl_expiry
    assert row.realized_pnl_per_contract is None  # nothing traded: shadow, not exact


def test_expired_otm_and_itm(db) -> None:
    _flat("AAPL", db, 62.0)
    otm = _row(
        db, candidate_id="otm", record_key="otm", sent_contracts=0, deterministic_contracts=2
    )
    _flat("MSFT", db, 55.0)
    itm = _row(
        db,
        candidate_id="itm",
        record_key="itm",
        underlying="MSFT",
        sent_contracts=0,
        deterministic_contracts=2,
    )
    assert resolve_actions(NOW) == 2
    assert _get(db, otm).shadow_pnl_expiry == pytest.approx(1.5 * 100 * 2)
    assert _get(db, itm).shadow_pnl_expiry == pytest.approx((1.5 - 5.0) * 100 * 2)


def test_an_exit_rule_mark_that_stops_out_before_expiry_differs_from_the_expiry_mark(db) -> None:
    """A leveraged put that went past 2x the premium, then recovered out of the money: the
    system's loss exit would have sold it at a loss; marked to expiry it kept the whole premium."""
    assert is_leveraged_etf("TQQQ")
    day1 = ACTION_DAY + timedelta(days=1)
    _bars(db, "TQQQ", {ACTION_DAY: 70.0, day1: 62.0, EXPIRY: 72.0})
    rid = _row(
        db,
        underlying="TQQQ",
        strike=65.0,
        premium=1.5,
        entry_iv=80.0,
        kind="loss_exit_cooldown",
        deterministic_contracts=2,
        sent_contracts=0,
    )
    resolve_actions(NOW)
    row = _get(db, rid)
    v1 = bs_price(62.0, 65.0, (EXPIRY - day1).days, 0.80, "P")
    v0 = bs_price(70.0, 65.0, (EXPIRY - ACTION_DAY).days, 0.80, "P")
    assert v0 is not None and 0.75 < v0 < 3.0  # neither exit line is touched on day 0
    assert v1 is not None and v1 >= 2.0 * 1.5  # the loss line is crossed on day 1
    assert row.shadow_pnl_expiry == pytest.approx(1.5 * 100 * 2)  # positive: it recovered
    assert row.shadow_pnl_rules == pytest.approx((1.5 - v1) * 100 * 2)
    assert row.shadow_pnl_rules < 0 < row.shadow_pnl_expiry


def test_the_loss_exit_is_only_the_systems_for_leveraged_names(db) -> None:
    """Every other short is rolled, not closed, at the loss line (check_loss_exits), so the
    mark does not invent a stop for them."""
    assert not is_leveraged_etf("AAPL")
    day1 = ACTION_DAY + timedelta(days=1)
    _bars(db, "AAPL", {ACTION_DAY: 70.0, day1: 62.0, EXPIRY: 72.0})
    rid = _row(
        db, strike=65.0, premium=1.5, entry_iv=80.0, deterministic_contracts=2, sent_contracts=0
    )
    resolve_actions(NOW)
    row = _get(db, rid)
    assert row.shadow_pnl_rules == pytest.approx(row.shadow_pnl_expiry)  # held to expiry


def test_no_entry_iv_leaves_the_rules_mark_none(db) -> None:
    _flat("AAPL", db, 62.0)
    rid = _row(db, entry_iv=None, sent_contracts=0, deterministic_contracts=2)
    assert resolve_actions(NOW) == 1
    row = _get(db, rid)
    assert row.shadow_pnl_expiry == pytest.approx(1.5 * 100 * 2)
    assert row.shadow_pnl_rules is None
    assert row.resolved_at is not None


def test_unresolved_before_expiry(db) -> None:
    """Held back by the date alone: the store even has bars through the (future) expiry."""
    future = NOW.date() + timedelta(days=20)
    _flat("AAPL", db, 62.0, end=future)
    rid = _row(db, expiry=future, sent_contracts=0)
    assert resolve_actions(NOW) == 0
    assert _get(db, rid).resolved_at is None
    # The expiry day itself is not settled until the next day's run.
    today = NOW.astimezone(sc._ET).date()
    _flat("MSFT", db, 62.0, end=today)
    same_day = _row(
        db, underlying="MSFT", candidate_id="m", record_key="m", expiry=today, sent_contracts=0
    )
    assert resolve_actions(NOW) == 0
    assert _get(db, same_day).resolved_at is None


def test_missing_price_history_leaves_it_unresolved(db) -> None:
    rid = _row(db, sent_contracts=0)  # no bars at all, and the provider fallback finds none
    assert resolve_actions(NOW) == 0
    assert _get(db, rid).resolved_at is None


def test_a_missing_expiry_bar_is_not_papered_over_with_a_stale_one(db) -> None:
    """Bars end the day before the expiry: the option cannot be marked to a close that is not
    there, and an earlier bar must not stand in for it."""
    _bars(db, "AAPL", {ACTION_DAY: 62.0, EXPIRY - timedelta(days=1): 55.0})
    rid = _row(db, sent_contracts=0)
    assert resolve_actions(NOW) == 0
    assert _get(db, rid).resolved_at is None


def test_a_holiday_expiry_is_marked_to_the_prior_session(db) -> None:
    """No bar on the expiry date, but the store holds a later one: the market was shut that day,
    so the last close before it is the settlement price."""
    holiday = date(2026, 11, 26)  # a Thursday with no bar of its own
    _bars(
        db,
        "AAPL",
        {ACTION_DAY: 62.0, date(2026, 11, 25): 55.0, date(2026, 11, 27): 70.0},
    )
    rid = _row(db, expiry=holiday, sent_contracts=0, deterministic_contracts=2, entry_iv=None)
    assert resolve_actions(NOW) == 1
    assert _get(db, rid).shadow_pnl_expiry == pytest.approx((1.5 - 5.0) * 100 * 2)


def test_the_provider_fallback_fills_a_gap(db, monkeypatch) -> None:
    """Bars missing from the store are fetched from the price provider (then marked)."""
    monkeypatch.setattr(
        sc, "_provider_closes", lambda symbol, start, end: {ACTION_DAY: 62.0, EXPIRY: 62.0}
    )
    rid = _row(db, sent_contracts=0, deterministic_contracts=2, entry_iv=None)
    assert resolve_actions(NOW) == 1
    assert _get(db, rid).shadow_pnl_expiry == pytest.approx(1.5 * 100 * 2)


# --------------------------------------------------------------------------- #
# What counts as withheld, per kind
# --------------------------------------------------------------------------- #


def test_claude_cut_unapplied_is_valued_on_claudes_suggested_withholding(db) -> None:
    oid = _order(db, filled=10)
    _fills(db, oid, sold=(10, 1.5), bought=(10, 0.5))
    rid = _row(
        db,
        kind="claude_cut_unapplied",
        order_id=oid,
        deterministic_contracts=10,
        sent_contracts=10,  # the system's size went out
        reason="live_record_only: Claude suggested 3: FOMC inside the window",
    )
    resolve_actions(NOW)
    row = _get(db, rid)
    # Claude wanted 7 of the 10 withheld; the traded leg earned $100 per contract.
    assert row.realized_pnl_per_contract == pytest.approx(100.0)
    assert row.shadow_pnl_expiry == pytest.approx(100.0 * 7)


def test_an_unapplied_row_with_no_readable_suggestion_withholds_nothing(db) -> None:
    oid = _order(db, filled=10)
    _fills(db, oid, sold=(10, 1.5), bought=(10, 0.5))
    rid = _row(
        db,
        kind="claude_cut_unapplied",
        order_id=oid,
        deterministic_contracts=10,
        sent_contracts=10,
        reason="garbled",
    )
    resolve_actions(NOW)
    assert _get(db, rid).shadow_pnl_expiry == 0.0


def test_regime_floor_lot_is_valued_on_the_lot_itself(db) -> None:
    """A floor lot is what the regime let through: what it earned is what is valued."""
    oid = _order(db, filled=1)
    _fills(db, oid, sold=(1, 1.5), bought=(1, 1.0))
    rid = _row(
        db,
        kind="regime_floor_lot",
        order_id=oid,
        deterministic_contracts=1,
        sent_contracts=1,
    )
    resolve_actions(NOW)
    row = _get(db, rid)
    assert row.realized_pnl_per_contract == pytest.approx(50.0)
    assert row.shadow_pnl_expiry == pytest.approx(50.0)  # the one lot that was let through
    # A floor lot that was never sent has nothing to value.
    moot = _row(
        db,
        kind="regime_floor_lot",
        candidate_id="f2",
        record_key="f2",
        order_id=_order(db, "f2", state="cancelled", filled=0),
        deterministic_contracts=1,
        sent_contracts=1,
    )
    resolve_actions(NOW)
    assert _get(db, moot).shadow_pnl_expiry == 0.0


def test_a_call_row_is_marked_as_a_short_call(db) -> None:
    """A covered-call breakout row is a call: the intrinsic runs the other way."""
    _flat("AAPL", db, 70.0)
    rid = _row(
        db,
        kind="cc_breakout_floor",
        right="C",
        strategy="covered_call",
        strike=65.0,
        premium=1.5,
        deterministic_contracts=2,
        sent_contracts=0,
        entry_iv=None,
    )
    resolve_actions(NOW)
    assert _get(db, rid).shadow_pnl_expiry == pytest.approx((1.5 - 5.0) * 100 * 2)


def test_resolving_is_idempotent_and_touches_only_the_value_columns(db) -> None:
    _flat("AAPL", db, 62.0)
    rid = _row(db, sent_contracts=0, deterministic_contracts=2)
    before = _get(db, rid)
    assert resolve_actions(NOW) == 1
    assert resolve_actions(NOW) == 0  # already resolved
    after = _get(db, rid)
    for col in (
        "kind",
        "regime",
        "deterministic_contracts",
        "sent_contracts",
        "reason",
        "order_id",
        "entry_iv",
        "premium",
        "strike",
        "record_key",
        "action_day",
    ):
        assert getattr(before, col) == getattr(after, col), col


# --------------------------------------------------------------------------- #
# The summary
# --------------------------------------------------------------------------- #


def _set(db, rid: int, **cols) -> None:
    with db() as s:
        row = s.get(SizingActionRow, rid)
        for k, v in cols.items():
            setattr(row, k, v)


def test_the_sent_smaller_never_sent_and_pushed_out_split(db) -> None:
    # Trimmed from 10 to 3 (an order went out: the row carries it, as `link_order` leaves it),
    # valued exactly.
    a = _row(
        db,
        candidate_id="a",
        record_key="a",
        kind="regime_ceiling",
        order_id=_order(db, "a", filled=3),
    )
    _set(
        db,
        a,
        realized_pnl_per_contract=98.0,
        shadow_pnl_expiry=686.0,
        shadow_pnl_rules=686.0,
        resolved_at=NOW,
    )
    # Blocked outright, shadow valued.
    b = _row(
        db,
        candidate_id="b",
        record_key="csp:AAPL:regime_ceiling:d",
        kind="regime_ceiling",
        sent_contracts=0,
        deterministic_contracts=4,
    )
    _set(db, b, shadow_pnl_expiry=600.0, shadow_pnl_rules=400.0, resolved_at=NOW)
    # An unresolved one still counts, but is not valued.
    _row(
        db,
        candidate_id="c",
        record_key="c",
        kind="regime_budget",
        sent_contracts=1,
        deterministic_contracts=2,
    )
    # A breakout row with a covered call sold on the name the same day: pushed out, not valued.
    d = _row(
        db,
        candidate_id="d",
        record_key="cctiming:AAPL:d",
        kind="cc_breakout_floor",
        right="C",
        strategy="covered_call",
        sent_contracts=0,
        deterministic_contracts=1,
    )
    _set(db, d, shadow_pnl_expiry=999.0, shadow_pnl_rules=999.0, resolved_at=NOW)
    with db() as s:
        s.add(
            OrderRow(
                candidate_id="cc-sold",
                state="filled",
                filled_qty=1,
                snapshot={"underlying": "AAPL", "strategy": "covered_call"},
                created_at=datetime(2026, 11, 2, 16),
            )
        )
    # ... and one with no covered call that day: counted as never sent, valued.
    e = _row(
        db,
        candidate_id="e",
        record_key="cctiming:NVDA:d",
        kind="cc_breakout_floor",
        underlying="NVDA",
        right="C",
        strategy="covered_call",
        sent_contracts=0,
        deterministic_contracts=1,
    )
    _set(db, e, shadow_pnl_expiry=50.0, shadow_pnl_rules=-20.0, resolved_at=NOW)

    out = summarize(ACTION_DAY)
    smaller = out["regime_ceiling:sent_smaller"]
    assert smaller["count"] == 1 and smaller["contracts_withheld"] == 7
    assert smaller["pnl_expiry"] == 686.0 and smaller["pnl_rules"] == 686.0
    assert smaller["exact"] == 1
    never = out["regime_ceiling:never_sent"]
    assert never["count"] == 1 and never["contracts_withheld"] == 4
    assert (never["pnl_expiry"], never["pnl_rules"], never["exact"]) == (600.0, 400.0, 0)
    pending = out["regime_budget:sent_smaller"]
    assert pending["count"] == 1 and pending["resolved"] == 0 and pending["pnl_expiry"] == 0.0
    pushed = out["cc_breakout_floor:pushed_out"]
    assert pushed["count"] == 1 and "pnl_expiry" not in pushed  # counted, not valued
    breakout_never = out["cc_breakout_floor:never_sent"]
    assert breakout_never["count"] == 1 and breakout_never["pnl_expiry"] == 50.0


def test_since_excludes_older_rows(db) -> None:
    _row(db, candidate_id="old", record_key="old", action_day=date(2026, 10, 1))
    _row(db, candidate_id="new", record_key="new")
    assert summarize(ACTION_DAY)["regime_ceiling:sent_smaller"]["count"] == 1
    assert summarize(date(2026, 9, 1))["regime_ceiling:sent_smaller"]["count"] == 2


def test_claudes_overrides_are_summarised_together(db) -> None:
    a = _row(
        db,
        candidate_id="a",
        record_key="a",
        kind="claude_cut",
        deterministic_contracts=10,
        sent_contracts=3,
    )
    _set(
        db,
        a,
        realized_pnl_per_contract=100.0,
        shadow_pnl_expiry=700.0,
        shadow_pnl_rules=700.0,
        resolved_at=NOW,
    )
    z = _row(
        db,
        candidate_id="z",
        record_key="z",
        kind="claude_cut",
        deterministic_contracts=3,
        sent_contracts=0,
    )
    _set(db, z, shadow_pnl_expiry=-300.0, shadow_pnl_rules=-120.0, resolved_at=NOW)
    u = _row(
        db,
        candidate_id="u",
        record_key="u",
        kind="claude_cut_unapplied",
        deterministic_contracts=10,
        sent_contracts=10,
        reason="live_record_only: Claude suggested 4: x",
    )
    _set(
        db,
        u,
        realized_pnl_per_contract=50.0,
        shadow_pnl_expiry=300.0,
        shadow_pnl_rules=300.0,
        resolved_at=NOW,
    )

    out = summarize(ACTION_DAY)
    both = out["claude_overrides"]
    assert both["count"] == 3 and both["applied"] == 2 and both["unapplied"] == 1
    assert both["contracts_withheld"] == 7 + 3 + 6  # det - sent, det - 0, det - suggested
    assert both["pnl_expiry"] == 700.0 - 300.0 + 300.0
    assert both["pnl_rules"] == 700.0 - 120.0 + 300.0
    assert "claude_cut:sent_smaller" not in out  # not reported twice


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #


def test_the_report_prints_both_marks_and_says_which_rows_are_exact(db, capsys) -> None:
    from scripts.sizing_report import main

    a = _row(db, candidate_id="a", record_key="a", kind="regime_ceiling")
    _set(
        db,
        a,
        realized_pnl_per_contract=98.0,
        shadow_pnl_expiry=686.0,
        shadow_pnl_rules=686.0,
        resolved_at=NOW,
    )
    b = _row(
        db,
        candidate_id="b",
        record_key="csp:AAPL:regime_ceiling:d",
        kind="regime_ceiling",
        sent_contracts=0,
        deterministic_contracts=4,
        entry_iv=None,
    )
    _set(db, b, shadow_pnl_expiry=600.0, shadow_pnl_rules=None, resolved_at=NOW)
    assert main(["--since", ACTION_DAY.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "regime_ceiling" in out and "sent smaller" in out and "never sent" in out
    assert "686" in out and "600" in out and "400" not in out
    assert "exact" in out.lower() and "shadow" in out.lower()
    assert "no entry IV" in out  # the row whose rules mark could not be computed says so


def test_the_report_says_so_when_there_is_nothing(db, capsys) -> None:
    from scripts.sizing_report import main

    assert main(["--since", "2026-01-01"]) == 0
    assert "no sizing actions" in capsys.readouterr().out.lower()


# --------------------------------------------------------------------------- #
# R4 (whole-branch review): a trim or floor lot recorded at scan time for a card that never
# became an order is moot, not valued as if its `sent` contracts had traded
# --------------------------------------------------------------------------- #

TRIM_KINDS = ["regime_ceiling", "leveraged_ceiling", "regime_budget", "escalation_trim"]


@pytest.mark.parametrize("kind", TRIM_KINDS)
def test_an_unlinked_trim_is_moot_not_valued_as_if_it_traded(db, kind) -> None:
    """The review's repro: a card trimmed 10 -> 6 and shown on a scan, never approved, so no order
    exists. Valuing the 4 withheld contracts against a trade that never happened booked $600."""
    _flat("AAPL", db, 62.0)  # expires worthless: the shadow mark would be the whole premium
    rid = _row(db, kind=kind, deterministic_contracts=10, sent_contracts=6)  # order_id is None
    assert resolve_actions(NOW) == 1
    row = _get(db, rid)
    assert (row.shadow_pnl_expiry, row.shadow_pnl_rules) == (0.0, 0.0)
    assert row.realized_pnl_per_contract is None
    assert row.resolved_at is not None


def test_an_unlinked_floor_lot_is_moot(db) -> None:
    """A floor lot surfaced on a scan and never sent: nothing was let through, so letting it
    through earned nothing (it was valued at the lot's premium, $150, before)."""
    _flat("AAPL", db, 62.0)
    rid = _row(db, kind="regime_floor_lot", deterministic_contracts=1, sent_contracts=1)
    assert resolve_actions(NOW) == 1
    row = _get(db, rid)
    assert (row.shadow_pnl_expiry, row.shadow_pnl_rules) == (0.0, 0.0)
    assert row.realized_pnl_per_contract is None and row.resolved_at is not None


def test_one_card_shown_with_three_strikes_is_not_valued_three_times(db) -> None:
    """The scan writes a row per surfaced contract; none of them was sent."""
    _flat("AAPL", db, 62.0)
    for i, strike in enumerate((58.0, 60.0, 61.0)):
        _row(
            db,
            candidate_id=f"tqqq-{i}",
            record_key=f"tqqq-{i}",
            strike=strike,
            kind="leveraged_ceiling",
            deterministic_contracts=10,
            sent_contracts=6,
        )
    assert resolve_actions(NOW) == 3
    group = summarize(ACTION_DAY)["leveraged_ceiling:sent_smaller"]
    assert group["count"] == 3 and group["resolved"] == 3
    assert group["contracts_withheld"] == 0
    assert (group["pnl_expiry"], group["pnl_rules"]) == (0.0, 0.0)


@pytest.mark.parametrize("kind", TRIM_KINDS)
def test_the_same_trim_linked_to_a_filled_order_keeps_its_exact_value(db, kind) -> None:
    oid = _order(db, filled=6)
    _fills(db, oid, sold=(6, 1.5), bought=(6, 0.5))
    rid = _row(db, kind=kind, order_id=oid, deterministic_contracts=10, sent_contracts=6)
    assert resolve_actions(NOW) == 1
    row = _get(db, rid)
    assert row.realized_pnl_per_contract == pytest.approx(100.0)
    assert row.shadow_pnl_expiry == pytest.approx(100.0 * 4)  # the 4 withheld at the traded rate
    assert row.shadow_pnl_rules == pytest.approx(100.0 * 4)


def test_the_same_floor_lot_linked_to_a_filled_order_keeps_its_exact_value(db) -> None:
    oid = _order(db, filled=1)
    _fills(db, oid, sold=(1, 1.5), bought=(1, 1.0))
    rid = _row(
        db, kind="regime_floor_lot", order_id=oid, deterministic_contracts=1, sent_contracts=1
    )
    resolve_actions(NOW)
    row = _get(db, rid)
    assert row.realized_pnl_per_contract == pytest.approx(50.0)
    assert row.shadow_pnl_expiry == pytest.approx(50.0)


def test_a_trim_linked_to_a_working_order_still_waits(db) -> None:
    oid = _order(db, state="submitted", filled=0)
    rid = _row(db, kind="regime_ceiling", order_id=oid)
    assert resolve_actions(NOW) == 0
    assert _get(db, rid).resolved_at is None


@pytest.mark.parametrize("kind", TRIM_KINDS + ["regime_daily_limit", "scale_in_zone"])
def test_a_never_sent_row_is_still_shadow_valued(db, kind) -> None:
    """`sent_contracts == 0` means the name was refused outright: nothing was withheld from a
    trade that existed, but the refusal itself is the action and is valued as before."""
    _flat("AAPL", db, 62.0)
    rid = _row(
        db,
        kind=kind,
        candidate_id="name",
        record_key=f"csp:AAPL:{kind}:{ACTION_DAY.isoformat()}",
        deterministic_contracts=2,
        sent_contracts=0,
    )
    assert resolve_actions(NOW) == 1
    assert _get(db, rid).shadow_pnl_expiry == pytest.approx(1.5 * 100 * 2)


def test_a_cut_to_zero_is_still_shadow_valued(db) -> None:
    """Claude's cut to zero queues no order, so it has none by design (the row's `sent` is 0)."""
    _flat("AAPL", db, 62.0)
    rid = _row(db, kind="claude_cut", deterministic_contracts=3, sent_contracts=0)
    assert resolve_actions(NOW) == 1
    assert _get(db, rid).shadow_pnl_expiry == pytest.approx(1.5 * 100 * 3)


@pytest.mark.parametrize("kind", ["claude_cut", "claude_cut_unapplied"])
def test_the_rule_is_for_scan_time_trims_and_floor_lots_only(db, kind) -> None:
    """Claude's rows that sent something are written in the same transaction as their order
    (`sender._auto_queue_candidates`), so the rule does not reach them."""
    _flat("AAPL", db, 62.0)
    rid = _row(
        db,
        kind=kind,
        deterministic_contracts=10,
        sent_contracts=3,
        reason="live_record_only: Claude suggested 3: x",
    )
    assert resolve_actions(NOW) == 1
    assert _get(db, rid).shadow_pnl_expiry != 0.0


def test_summarize_shows_a_moot_row_with_no_lots_withheld(db) -> None:
    _row(db, kind="regime_ceiling", deterministic_contracts=10, sent_contracts=6)
    before = summarize(ACTION_DAY)["regime_ceiling:sent_smaller"]  # not resolved yet
    assert before["count"] == 1 and before["contracts_withheld"] == 0 and before["resolved"] == 0
    resolve_actions(NOW)
    after = summarize(ACTION_DAY)["regime_ceiling:sent_smaller"]
    assert after["count"] == 1 and after["resolved"] == 1
    assert (after["contracts_withheld"], after["pnl_expiry"], after["pnl_rules"]) == (0, 0.0, 0.0)
