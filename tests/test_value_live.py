"""The value book's money in paper (value book spec §7, §9, revision 4): the executor, the RTH
cycle (close first, confirm, then buy), the reconcile, the night's proposals, the hourly check."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from sqlalchemy import select

from src.common.config import get_config
from src.common.value_types import DayBar
from src.value import book, live
from src.value.executor import Outcome, Placed, Quote, send_order
from src.value.exits import DayFacts
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValueAttributionRow,
    ValueClaudeReadRow,
    ValueEffectiveRow,
    ValueFundingRow,
    ValueOrderRow,
    ValuePositionRow,
    ValueProposalRow,
    ValueReevaluationRow,
    value_session,
)
from src.value.ticker_file import persist
from tests.value_book_fixtures import NOW, order
from tests.value_fixtures import inputs

CFG = get_config().value
PORTFOLIO = {"max_gross_notional_pct": 100.0, "max_combined_name_pct": 15.0}
CARD = build_scorecard(inputs(symbol="STDY", close=30.0), CFG)  # deep READY, FV 46.85


class FakeBroker:
    def __init__(self, *, fill: float | None = None, price: float = 30.0) -> None:
        self.fill, self.price, self.placed = fill, price, []

    async def quote(self, symbol):
        return Quote(self.price - 0.05, self.price + 0.05, NOW)

    async def place(self, symbol, side, shares, limit, order_ref):
        with value_session() as s:  # the pending row exists before placeOrder (spec §9.2)
            row = s.scalars(select(ValueOrderRow).where(ValueOrderRow.order_ref == order_ref)).one()
            assert row.status == "pending"
        self.placed.append((symbol, side, shares, limit, order_ref))
        return Placed(41, 4100, None)

    async def wait(self, placed, timeout):
        filled = self.placed[-1][2] if self.fill is None else self.fill
        return Outcome(filled, self.price, filled >= self.placed[-1][2])

    async def cancel(self, placed):
        return Outcome(self.fill or 0.0, self.price if self.fill else None, True)


def _effective(symbol="STDY", list_name="deep_value", verdict="READY", fv=46.85, by="python"):
    with value_session() as s:
        s.add(
            ValueEffectiveRow(
                symbol=symbol,
                list_name=list_name,
                as_of=date(2026, 10, 30),
                verdict=verdict,
                decided_by=by,
                python_verdict=verdict,
                fair_value=fv,
                entry_ceiling=fv * 0.75,
                margin_of_safety=(fv - 30.0) / fv,
                updated_at=NOW,
            )
        )
        persist(
            s,
            CARD,
            universe="trading",
            ranks={},
            filed="deep_value",
            cfg=CFG.ticker_file,
            session_row=False,
        )


SNAP = live.Snapshot(net_liq=100_000.0, adv={"STDY": 1e9})


def _cycle(broker, snap=SNAP, now=NOW):
    return asyncio.run(
        live.cycle(
            value_session,
            broker,
            snap,
            wheel={},
            cfg=CFG,
            portfolio=PORTFOLIO,
            now=now,
            halted=False,
            is_live=False,
            trend_brake=False,
        )
    )


def _proposal(kind="buy", shares=20.0, status="approved", reason="tranche 1", cause="python"):
    with value_session() as s:
        row = book.propose(
            s,
            kind=kind,
            symbol="STDY",
            list_name="deep_value",
            shares=shares,
            price=30.0,
            reason=reason,
            cause=cause,
            auto=status == "approved",
            now=NOW,
            ttl_hours=30,
            tranche=1 if kind == "buy" else None,
        )
        assert row is not None
        return row.id


def test_an_order_is_written_before_it_is_placed_and_its_fill_recorded(value_book_db) -> None:
    broker = FakeBroker()
    oid = asyncio.run(
        send_order(
            value_session,
            broker,
            symbol="STDY",
            list_name="deep_value",
            side="buy",
            shares=20,
            limit=30.0,
            reason="tranche 1",
            proposal_id=None,
            tranche=1,
            timeout=1,
        )
    )
    with value_session() as s:
        row = s.get(ValueOrderRow, oid)
        assert (row.status, row.filled, row.order_ref, row.ib_order_id) == (
            "filled",
            20.0,
            f"value:{oid}",
            41,
        )
    assert broker.placed[0][4] == f"value:{oid}"


def test_a_part_fill_keeps_what_filled_and_cancels_the_rest(value_book_db) -> None:
    oid = asyncio.run(
        send_order(
            value_session,
            FakeBroker(fill=7),
            symbol="STDY",
            list_name="deep_value",
            side="buy",
            shares=20,
            limit=30.0,
            reason="t",
            proposal_id=None,
            tranche=1,
            timeout=1,
        )
    )
    with value_session() as s:
        row = s.get(ValueOrderRow, oid)
        assert (row.status, row.filled) == ("cancelled", 7.0)


def test_an_approved_buy_with_room_is_regated_sent_and_opens_a_position(value_book_db) -> None:
    _effective()
    pid = _proposal()
    msgs = _cycle(FakeBroker())
    assert msgs == ["Value book: bought 20 STDY at 30.0 (deep_value)"]
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "done"
        pos = s.scalars(select(ValuePositionRow)).one()
        assert (pos.symbol, pos.tranches_done, pos.status) == ("STDY", 1, "open")


def test_a_buy_short_of_cash_asks_for_capital_then_buys_once_the_room_is_there(
    value_book_db,
) -> None:
    """Close first, confirm, then buy: no order goes out until the fresh snapshot shows room."""
    _effective()
    pid = _proposal()
    full = live.Snapshot(net_liq=100_000.0, csp_by_name={"AAA": 99_800.0}, adv={"STDY": 1e9})
    broker = FakeBroker()
    msgs = _cycle(broker, full)
    assert msgs == ["Value book: STDY needs $401 released (capital release requested)"]
    assert broker.placed == []
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "funding"
        req = s.scalars(select(ValueFundingRow)).one()
        assert (req.status, req.needed_usd) == ("open", 401.0)  # 20 x 30.05 - 200
    released = live.Snapshot(net_liq=100_000.0, csp_by_name={"AAA": 89_800.0}, adv={"STDY": 1e9})
    assert _cycle(broker, released) == ["Value book: bought 20 STDY at 30.0 (deep_value)"]
    with value_session() as s:
        assert s.scalars(select(ValueFundingRow)).one().status == "funded"


def test_a_buy_refused_at_send_time_lapses_its_request_and_nothing_else_happens(
    value_book_db,
) -> None:
    _effective()
    pid = _proposal()
    full = live.Snapshot(net_liq=100_000.0, csp_by_name={"AAA": 99_800.0}, adv={"STDY": 1e9})
    _cycle(FakeBroker(), full)
    with value_session() as s:  # the name froze meanwhile: the buy may not go
        s.add(
            ValueAttributionRow(
                symbol="STDY", broker=0, wheel=0, value_filled=0, state="frozen", updated_at=NOW
            )
        )
    msgs = _cycle(FakeBroker(), full)
    assert "book_attribution_mismatch" in msgs[-1]
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "refused"
        assert s.scalars(select(ValueFundingRow)).one().status == "lapsed"


def test_a_sell_never_uncovers_a_wheel_call(value_book_db) -> None:
    order("STDY", shares=50, filled=50, avg=30.0)
    pid = _proposal(kind="sell", shares=50)
    snap = live.Snapshot(net_liq=100_000.0, shares={"STDY": 150.0}, wheel_short_calls={"STDY": 1})
    broker = FakeBroker()
    _cycle(broker, snap)
    assert broker.placed[0][1:3] == ("sell", 50.0)
    pid2 = _proposal(kind="sell", shares=50)
    short = live.Snapshot(net_liq=100_000.0, shares={"STDY": 100.0}, wheel_short_calls={"STDY": 1})
    msgs = _cycle(FakeBroker(), short)
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "done"
        assert s.get(ValueProposalRow, pid2).status == "refused"
    assert "sell cap" in msgs[-1]


def test_unexplained_shares_are_pending_then_frozen_until_a_human_clears_them(
    value_book_db,
) -> None:
    order("STDY", shares=50, filled=50, avg=30.0)
    with value_session() as s:
        assert (
            book.reconcile(s, {"STDY": 150.0}, {"STDY": 100.0}, {}, now=NOW, grace_hours=36) == []
        )
        assert s.get(ValueAttributionRow, "STDY").state == "ok"
        assert (
            book.reconcile(s, {"STDY": 180.0}, {"STDY": 100.0}, {}, now=NOW, grace_hours=36) == []
        )
        assert s.get(ValueAttributionRow, "STDY").state == "pending"
        later = NOW + timedelta(hours=37)
        assert book.reconcile(
            s, {"STDY": 180.0}, {"STDY": 100.0}, {}, now=later, grace_hours=36
        ) == ["STDY"]
        assert book.clear_attribution(s, "STDY", later) is True
        assert s.get(ValueAttributionRow, "STDY").state == "ok"


def _held(entry: float = 30.0) -> int:
    order("STDY", shares=20, filled=20, avg=entry)
    with value_session() as s:
        o = s.scalars(select(ValueOrderRow)).one()
        pos = book.open_position(
            s,
            o,
            day=date(2026, 10, 1),
            atr14=1.0,
            fair_value=46.85,
            effective_fair_value=60.0,
            fv_accn="a",
            cfg=CFG,
            decided_by="claude",
        )
        return pos.id


def _night(bars, facts=None, **kw):
    with value_session() as s:
        return live.plan_night(
            s,
            cards={"STDY": CARD},
            tags={"STDY": "trading"},
            bars={"STDY": bars},
            facts=facts or {},
            cfg=CFG,
            portfolio=PORTFOLIO,
            now=NOW,
            today=NOW.date(),
            may_auto_open=kw.get("auto_open", lambda sym: True),
            auto_close=True,
            halted=False,
            is_live=False,
            trend_brake=False,
        )


def test_the_night_turns_a_python_exit_into_an_auto_sell_and_claudes_into_a_tap(
    value_book_db,
) -> None:
    _held()
    crash = [DayBar(date=date(2026, 10, 2), close=20.0, open=21.0)]  # 33% under cost
    out = _night(crash)
    assert (out.sells, out.tap) == (1, 0)
    with value_session() as s:
        p = s.scalars(select(ValueProposalRow)).one()
        assert (p.reason, p.cause, p.status, p.shares) == ("catastrophe", "python", "approved", 20)


def test_a_half_sale_only_claudes_value_reaches_waits_for_a_tap(value_book_db) -> None:
    _held()
    up = [DayBar(date=date(2026, 10, 2), close=61.0, open=60.0)]  # past Claude's 60 only
    facts = {
        ("STDY", "deep_value"): DayFacts(
            python_fair_value=70.0, effective_fair_value=60.0, latest_accn="a"
        )
    }
    out = _night(up, facts)
    assert out.tap == 1
    with value_session() as s:
        p = s.scalars(select(ValueProposalRow)).one()
        assert (p.reason, p.cause, p.status, p.shares) == ("half", "claude", "pending", 10)


def test_claudes_broken_review_is_a_tap_only_sell(value_book_db) -> None:
    pid = _held()
    with value_session() as s:
        s.add(
            ValueReevaluationRow(
                shadow_id=0,
                position_id=pid,
                symbol="STDY",
                list_name="deep_value",
                session=date(2026, 10, 2),
                last_session=date(2026, 10, 2),
                severity="major",
                triggers_json="[]",
                plan_before_json="{}",
                plan_after_json="{}",
                verdict_at_entry="READY",
                review_state="BROKEN",
                ruleset_version="v4",
                ruleset_hash="x",
                created_at=NOW,
            )
        )
    out = _night([])
    with value_session() as s:
        p = s.scalars(select(ValueProposalRow)).one()
        assert (p.reason, p.cause, p.needs_tap) == ("claude_broken", "claude", True)
    assert out.tap == 1


def test_the_night_sizes_and_gates_a_ready_name_into_a_buy_proposal(value_book_db) -> None:
    _effective()
    assert _night([]).skipped.startswith("no account snapshot")
    with value_session() as s:
        book.set_state(s, live.SNAPSHOT, {"net_liq": 100_000.0, "adv": {"STDY": 1e9}}, NOW)
    out = _night([], auto_open=lambda sym: False)
    with value_session() as s:
        p = s.scalars(select(ValueProposalRow)).one()
    # MoS (46.85 - 30) / 46.85 = 36% -> 5% of the 30,000 ceiling = 1,500, a third = 500: 16 shares
    assert (out.buys, p.shares, p.status, p.needs_tap) == (1, 16.0, "pending", True)


def test_a_tap_decides_a_pending_proposal_once(value_book_db) -> None:
    pid = _proposal(status="pending")
    with value_session() as s:
        assert book.decide(s, pid, approve=True, now=NOW, by="cli") == "approved"
        assert book.decide(s, pid, approve=False, now=NOW, by="cli") == "already_approved"
        assert book.decide(s, 999, approve=True, now=NOW, by="cli") == "no_such_proposal"


def test_the_hourly_check_opens_a_held_reevaluation_pauses_adds_and_queues_review(
    value_book_db, monkeypatch
) -> None:
    monkeypatch.setattr(CFG.claude, "enabled", True)
    pid = _held()
    snap = live.Snapshot(net_liq=100_000.0, marks={"STDY": 26.5})
    with value_session() as s:
        opened = live.hourly_check(
            s, snap, {"STDY": 30.0}, set(), cfg=CFG, now=NOW, ruleset_version="v4", ruleset_hash="x"
        )
        assert opened == ["STDY"]  # -11.7% against the 30.00 close
        r = s.scalars(select(ValueReevaluationRow)).one()
        assert (r.position_id, r.severity) == (pid, "major")
        assert live.adds_paused(s, "STDY", NOW.date(), 3) is True
        read = s.scalars(select(ValueClaudeReadRow)).one()
        assert (read.kind, read.reevaluation_id) == ("review", r.id)
        assert (
            live.hourly_check(
                s,
                snap,
                {"STDY": 30.0},
                set(),
                cfg=CFG,
                now=NOW,
                ruleset_version="v4",
                ruleset_hash="x",
            )
            == []
        )


def test_on_a_frozen_name_only_a_stop_or_thesis_sale_sends(value_book_db) -> None:
    """Spec §9.2: both books freeze; only a value-book stop or thesis sale may still send."""
    order("STDY", shares=50, filled=50, avg=30.0)
    with value_session() as s:
        s.add(
            ValueAttributionRow(
                symbol="STDY", broker=50, wheel=0, value_filled=50, state="frozen", updated_at=NOW
            )
        )
    tap = _proposal(kind="sell", shares=20, reason="claude_broken", cause="claude")
    with value_session() as s:
        assert book.decide(s, tap, approve=True, now=NOW, by="cli") == "approved"
    snap = live.Snapshot(net_liq=100_000.0, shares={"STDY": 50.0})
    broker = FakeBroker()
    assert _cycle(broker, snap) == [] and broker.placed == []  # waits, never sends
    with value_session() as s:
        s.get(ValueProposalRow, tap).status = "expired"
    _proposal(kind="sell", shares=50, reason="catastrophe")
    _cycle(broker, snap)
    assert broker.placed[0][1:3] == ("sell", 50.0)
