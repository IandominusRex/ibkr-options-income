"""The value book's money in paper (value book spec §7, §9, revision 4): the executor, the RTH
cycle (close first, confirm, then buy), the reconcile, the night's proposals, the hourly check."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from sqlalchemy import select

from src.common.config import get_config
from src.common.value_types import DayBar
from src.value import book, live
from src.value.executor import Found, Outcome, Placed, Quote, send_order
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
    def __init__(
        self,
        *,
        fill: float | None = None,
        price: float = 30.0,
        found: dict | None = None,
        quote_age: float = 0.0,
        cancel_done: bool = True,
    ) -> None:
        self.fill, self.price, self.placed = fill, price, []
        self.found, self.cancelled, self.quote_age = found or {}, [], quote_age
        self.cancel_done = cancel_done

    async def quote(self, symbol):
        return Quote(
            self.price - 0.05, self.price + 0.05, NOW - timedelta(seconds=self.quote_age), NOW
        )

    async def lookup(self, order_ref):
        return self.found.get(order_ref)

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
        self.cancelled.append(placed)
        return Outcome(self.fill or 0.0, self.price if self.fill else None, self.cancel_done)


def _effective(
    symbol="STDY", list_name="deep_value", verdict="READY", fv=46.85, by="python", review=False
):
    with value_session() as s:
        s.add(
            ValueEffectiveRow(
                symbol=symbol,
                list_name=list_name,
                as_of=date(2026, 10, 30),
                verdict=verdict,
                decided_by=by,
                mos_review=review,
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


def _cycle(broker, snap=SNAP, now=NOW, **kw):
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
            **kw,
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


# --- Whole-branch review fixes -------------------------------------------------------------

FULL = live.Snapshot(net_liq=100_000.0, csp_by_name={"AAA": 99_800.0}, adv={"STDY": 1e9})
ROOM = live.Snapshot(net_liq=100_000.0, csp_by_name={"AAA": 89_800.0}, adv={"STDY": 1e9})


def test_a_funded_buy_that_does_not_fill_lapses_its_request_and_the_cooldown_applies(
    value_book_db,
) -> None:
    """Review I-4: funded only by the buy's FILL. A mid limit that misses used to mark the
    request funded, so the cooldown (keyed on lapsed) never held and the next night asked again."""
    _effective()
    pid = _proposal()
    _cycle(FakeBroker(), FULL)
    msgs = _cycle(FakeBroker(fill=0.0), ROOM)
    assert "did not fill" in msgs[-1]
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "expired"
        assert s.scalars(select(ValueFundingRow)).one().status == "lapsed"
    _proposal()  # the next night proposes again: the cooldown refuses to ask for capital again
    msgs = _cycle(FakeBroker(), FULL)
    assert "cooldown" in msgs[-1]
    with value_session() as s:
        assert len(s.scalars(select(ValueFundingRow)).all()) == 1


def test_the_funding_request_carries_the_cycle_that_wrote_its_need(value_book_db) -> None:
    """Review (b): needed_usd is rewritten each cycle from a fresh snapshot; as_of says when."""
    _effective()
    _proposal()
    _cycle(FakeBroker(), FULL)
    with value_session() as s:
        assert s.scalars(select(ValueFundingRow)).one().as_of == NOW
    later = NOW + timedelta(minutes=15)
    short = live.Snapshot(net_liq=100_000.0, csp_by_name={"AAA": 99_500.0}, adv={"STDY": 1e9})
    _cycle(FakeBroker(), short, now=later)
    with value_session() as s:
        req = s.scalars(select(ValueFundingRow)).one()
        assert (req.as_of, req.needed_usd) == (later, 101.0)  # re-written from the new snapshot


def test_a_review_line_buy_the_operator_tapped_is_sent_not_refused(value_book_db) -> None:
    """Review I-7: the night makes a tap-only proposal for a margin above the review line (the
    gate's only refusal is data_unreliable from mos_review). Once a human taps it, the send-time
    gate must not re-refuse it for the very reason the tap was asked for."""
    _effective(review=True)
    with value_session() as s:
        book.set_state(s, live.SNAPSHOT, {"net_liq": 100_000.0, "adv": {"STDY": 1e9}}, NOW)
    out = _night([])
    assert (out.buys, out.tap) == (1, 1)
    with value_session() as s:
        p = s.scalars(select(ValueProposalRow)).one()
        assert (p.status, p.needs_tap) == ("pending", True)
        assert book.decide(s, p.id, approve=True, now=NOW, by="cli") == "approved"
    broker = FakeBroker()
    msgs = _cycle(broker)
    assert msgs and msgs[0].startswith("Value book: bought")
    assert len(broker.placed) == 1


def test_an_untapped_review_line_buy_is_still_refused_at_send_time(value_book_db) -> None:
    _effective(review=True)
    pid = _proposal()  # auto-approved by the system: nobody tapped it
    msgs = _cycle(FakeBroker())
    assert "data_unreliable" in msgs[-1]
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "refused"


def test_a_quote_older_than_the_limit_refuses_the_buy_at_send_time(value_book_db) -> None:
    """Review minor: the quote's age is measured from its own time, so price_stale_at_send fires."""
    _effective()
    pid = _proposal()
    broker = FakeBroker(quote_age=CFG.book.quote_max_age_seconds + 10)
    msgs = _cycle(broker)
    assert "price_stale_at_send" in msgs[-1] and broker.placed == []
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "refused"


def test_a_cancel_the_broker_has_not_confirmed_leaves_the_order_to_be_resolved(
    value_book_db,
) -> None:
    """Review I-5: never record 'cancelled' for an order the broker may still fill."""
    _effective()
    pid = _proposal()
    msgs = _cycle(FakeBroker(fill=0.0, cancel_done=False))
    assert "not confirmed" in msgs[-1]
    with value_session() as s:
        row = s.scalars(select(ValueOrderRow)).one()
        assert row.status == "submitted" and row.filled == 0.0
        assert s.get(ValueProposalRow, pid).status == "sent"


def _stuck_buy(*, status="submitted", with_order=True) -> tuple[int, str | None]:
    """A buy a restart left half-way: proposal 'sent', its order row written (and 'submitted')."""
    _effective()
    pid = _proposal()
    with value_session() as s:
        s.get(ValueProposalRow, pid).status = "sent"
        if not with_order:
            return pid, None
        row = ValueOrderRow(
            symbol="STDY",
            list_name="deep_value",
            side="buy",
            tranche=1,
            reason="tranche 1",
            proposal_id=pid,
            shares=20,
            limit_price=30.0,
            status=status,
            ib_order_id=41,
            created_at=NOW - timedelta(minutes=20),
            sent_at=NOW - timedelta(minutes=20),
        )
        s.add(row)
        s.flush()
        row.order_ref = f"value:{row.id}"
        return pid, row.order_ref


def test_a_restart_mid_order_resolves_the_fill_from_the_broker(value_book_db) -> None:
    """Spec 9.2 drill 3, for real: the process died while the order waited. The next cycle finds
    the fill at the broker, V is right, the proposal is terminal and the name can be proposed
    again."""
    from src.common.value_view import read_book

    pid, ref = _stuck_buy()
    assert read_book(NOW).holding("STDY").claimed == 20.0  # the working row claims the shares
    broker = FakeBroker(found={ref: Found(Outcome(20.0, 29.95, True), None)})
    msgs = _cycle(broker)
    assert "recovered" in msgs[0] and broker.placed == []
    with value_session() as s:
        row = s.scalars(select(ValueOrderRow)).one()
        assert (row.status, row.filled, row.avg_price) == ("filled", 20.0, 29.95)
        assert s.get(ValueProposalRow, pid).status == "done"
        assert s.scalars(select(ValuePositionRow)).one().status == "open"
        assert book.totals(s).names["STDY"].filled == 20.0
        assert (
            book.propose(
                s,
                kind="buy",
                symbol="STDY",
                list_name="deep_value",
                shares=5,
                price=30.0,
                reason="tranche 2",
                cause="python",
                auto=True,
                now=NOW,
                ttl_hours=30,
                tranche=2,
            )
            is not None
        )  # not blocked by a 'sent' proposal that never ends
    h = read_book(NOW).holding("STDY")
    assert (h.filled, h.pending_buy) == (20.0, 0.0)


def test_a_working_order_past_its_timeout_is_cancelled_and_what_filled_is_recorded(
    value_book_db,
) -> None:
    pid, ref = _stuck_buy()
    broker = FakeBroker(
        fill=5.0, found={ref: Found(Outcome(5.0, 30.0, False), Placed(41, 4100, "handle"))}
    )
    _cycle(broker)
    assert broker.cancelled and broker.cancelled[0].handle == "handle"
    with value_session() as s:
        row = s.scalars(select(ValueOrderRow)).one()
        assert (row.status, row.filled) == ("cancelled", 5.0)
        assert s.get(ValueProposalRow, pid).status == "done"


def test_a_fill_only_the_ledger_knows_is_recorded(value_book_db) -> None:
    pid, ref = _stuck_buy()
    _cycle(FakeBroker(), ledger_fill=lambda r: (20.0, 29.9) if r == ref else (0.0, None))
    with value_session() as s:
        row = s.scalars(select(ValueOrderRow)).one()
        assert (row.status, row.filled, row.avg_price) == ("filled", 20.0, 29.9)
        assert s.get(ValueProposalRow, pid).status == "done"


def test_an_order_found_nowhere_is_closed_out_unfilled_and_the_name_is_free(value_book_db) -> None:
    from src.common.value_view import read_book

    pid, ref = _stuck_buy()
    _cycle(FakeBroker(), now=NOW + timedelta(days=1))  # a DAY order cannot still be working
    with value_session() as s:
        row = s.scalars(select(ValueOrderRow)).one()
        assert (row.status, row.filled) == ("cancelled", 0.0) and "not found" in row.detail
        assert s.get(ValueProposalRow, pid).status == "expired"
        assert book.totals(s).positions_open == 0
    assert read_book(NOW).holding("STDY").claimed == 0.0


def test_a_sent_proposal_with_no_order_goes_back_to_approved_and_is_sent_again(
    value_book_db,
) -> None:
    pid, _ = _stuck_buy(with_order=False)
    broker = FakeBroker()
    _cycle(broker)
    assert len(broker.placed) == 1  # re-gated and sent this very cycle
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "done"


def test_a_broker_that_cannot_be_asked_leaves_the_working_order_alone(value_book_db) -> None:
    pid, ref = _stuck_buy()

    class Down(FakeBroker):
        async def lookup(self, order_ref):
            raise TimeoutError("reqExecutions")

    _cycle(Down())
    with value_session() as s:
        assert s.scalars(select(ValueOrderRow)).one().status == "submitted"
        assert s.get(ValueProposalRow, pid).status == "sent"


def _ib_trade(*, ref="value:3", filled=0.0, done=False, order_id=41):
    from types import SimpleNamespace

    state = {"done": done}
    trade = SimpleNamespace(
        order=SimpleNamespace(orderRef=ref, orderId=order_id, permId=4100),
        orderStatus=SimpleNamespace(filled=filled, avgFillPrice=30.0 if filled else 0.0),
        isDone=lambda: state["done"],
    )
    return trade, state


def test_the_ibkr_broker_confirms_a_cancel_before_calling_it_done() -> None:
    from types import SimpleNamespace

    from src.value.executor import IbkrValueBroker

    trade, state = _ib_trade()
    cancelled = []
    ib = SimpleNamespace(cancelOrder=lambda order: cancelled.append(order))
    broker = IbkrValueBroker(ib, cancel_confirm_seconds=0.6)
    out = asyncio.run(broker.cancel(Placed(41, 4100, trade)))
    assert cancelled and out.done is False  # IBKR never confirmed: not recorded as cancelled
    trade2, state2 = _ib_trade()
    ib2 = SimpleNamespace(cancelOrder=lambda order: state2.update(done=True))
    assert asyncio.run(IbkrValueBroker(ib2).cancel(Placed(41, 4100, trade2))).done is True


def test_the_ibkr_broker_finds_an_order_open_or_by_its_executions() -> None:
    from types import SimpleNamespace

    from src.value.executor import IbkrValueBroker

    async def open_orders():
        return [_ib_trade(ref="value:9")[0], _ib_trade(ref="value:3", filled=4.0)[0]]

    fills = [
        SimpleNamespace(execution=SimpleNamespace(orderRef="value:5", shares=12, price=30.0)),
        SimpleNamespace(execution=SimpleNamespace(orderRef="value:5", shares=8, price=31.0)),
        SimpleNamespace(execution=SimpleNamespace(orderRef="", shares=99, price=1.0)),
    ]

    async def executions():
        return fills

    ib = SimpleNamespace(reqOpenOrdersAsync=open_orders, reqExecutionsAsync=executions)
    broker = IbkrValueBroker(ib)
    open_ = asyncio.run(broker.lookup("value:3"))
    assert open_.placed is not None and open_.outcome.filled == 4.0
    done = asyncio.run(broker.lookup("value:5"))
    assert done.placed is None and (done.outcome.filled, done.outcome.avg_price) == (
        20.0,
        (12 * 30.0 + 8 * 31.0) / 20.0,
    )
    assert asyncio.run(broker.lookup("value:6")) is None


def test_a_quotes_age_runs_from_its_own_time_to_when_it_arrived() -> None:
    q = Quote(29.95, 30.05, NOW - timedelta(seconds=45), NOW)
    assert q.age_seconds == 45.0
    assert Quote(29.95, 30.05, NOW).age_seconds == 0.0
