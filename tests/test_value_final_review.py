"""Part 6 final whole-branch review fixes (I-A, I-B, I-C, M1-M5): the drawdown trim's episode, the
unknown mark, the running average cost shared by the book and the API, and the small ones."""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from src.common import value_commands as vc
from src.common.config import get_config
from src.common.value_cost import RunningCost
from tests.value_book_fixtures import NOW, order

ROOT = Path(__file__).resolve().parent.parent
CFG = get_config().value
TRIM = CFG.book.drawdown_trim_pct


# --- RunningCost ---------------------------------------------------------------------------------


def test_running_cost_buys_average_and_a_sale_leaves_the_average() -> None:
    rc = RunningCost()
    rc.buy(10, 100.0)
    rc.buy(10, 50.0)
    assert rc.avg == 75.0
    assert rc.sell(10) == 75.0 and (rc.qty, rc.avg) == (10, 75.0)
    assert rc.sell(10) == 75.0 and rc.avg is None  # a full exit resets it
    rc.buy(10, 50.0)
    assert rc.avg == 50.0
    assert RunningCost().sell(5) is None  # nothing held: no cost to measure against


# --- I-C: totals, open_position, and the API's reader agree on the running average ---------------


def _reentry() -> None:
    order("AAA", shares=10, filled=10, avg=100.0)
    order("AAA", side="sell", shares=10, filled=10, avg=110.0)
    order("AAA", shares=10, filled=10, avg=50.0)


def test_totals_carry_the_running_average_across_a_re_entry(value_book_db) -> None:
    from src.value.book import totals
    from src.value.store import value_session

    _reentry()
    with value_session() as vs:
        n = totals(vs).names["AAA"]
    assert (n.filled, n.cost) == (10, 500.0)  # not 10 x 75


def test_totals_after_a_partial_sale_then_a_buy(value_book_db) -> None:
    from src.value.book import totals
    from src.value.store import value_session

    order("AAA", shares=10, filled=10, avg=100.0)
    order("AAA", side="sell", shares=4, filled=4, avg=120.0)
    order("AAA", shares=10, filled=10, avg=50.0)
    with value_session() as vs:
        n = totals(vs).names["AAA"]
    assert n.filled == 16 and n.cost == pytest.approx(6 * 100.0 + 10 * 50.0)


def test_a_re_entry_opens_its_plan_at_its_own_price(value_book_db) -> None:
    from sqlalchemy import select

    from src.value.book import open_position
    from src.value.exits import LegState
    from src.value.store import ValueOrderRow, value_session

    _reentry()
    with value_session() as vs:
        last = vs.scalars(select(ValueOrderRow).order_by(ValueOrderRow.id.desc())).first()
        assert last is not None
        pos = open_position(
            vs,
            last,
            day=date(2026, 11, 2),
            atr14=1.0,
            fair_value=80.0,
            effective_fair_value=80.0,
            fv_accn="a",
            cfg=CFG,
            decided_by="python",
        )
        plan = LegState.model_validate_json(pos.plan_json)
    assert plan.entry_price == 50.0
    assert plan.entry_price * (1 - CFG.rules.exits.catastrophe_stop_pct / 100) == pytest.approx(
        35.0
    )


@pytest.fixture()
def api_reads(value_book_db, monkeypatch):
    import src.api.value_db as vdb

    monkeypatch.setattr(vdb, "_resolve_path", lambda: str(value_book_db))
    vdb.reset_engine()
    yield vdb
    vdb.reset_engine()


def test_the_api_reads_the_same_running_average(api_reads) -> None:
    from src.value.store import ValuePositionRow, value_session

    _reentry()
    with value_session() as vs:
        vs.add(
            ValuePositionRow(
                symbol="AAA", list_name="deep_value", status="open", opened_on=date(2026, 11, 1)
            )
        )
    with api_reads.value_read_session() as s:
        assert s is not None
        orders = api_reads.read_orders(s)
        assert api_reads.used_usd(orders) == 500.0
        pos = api_reads.read_positions(s, "open")
        fills = api_reads.read_fills(s)
    assert pos is not None and pos[0]["avg_cost"] == 50.0 and pos[0]["shares"] == 10
    assert pos[0]["realised_usd"] == pytest.approx(10 * (110.0 - 100.0))
    assert fills is not None
    assert [f["realised_usd"] for f in fills] == [None, pytest.approx(100.0), None]


def test_a_sale_never_realises_more_shares_than_were_held(api_reads) -> None:
    order("AAA", shares=10, filled=10, avg=100.0)
    order("AAA", side="sell", shares=15, filled=15, avg=110.0)  # a restated fill: more than held
    with api_reads.value_read_session() as s:
        assert s is not None
        fills = api_reads.read_fills(s)
    assert fills is not None and fills[1]["realised_usd"] == pytest.approx(10 * 10.0)


# --- I-A / I-B: the drawdown trim episode and the unknown mark -----------------------------------


def _hw(marks: dict[str, float], now: datetime):
    from src.value import live
    from src.value.book import get_state
    from src.value.store import value_session

    snap = live.Snapshot(net_liq=100_000.0, marks=marks)
    with value_session() as vs:
        offered = live._high_water(vs, snap, CFG, now)
    with value_session() as vs:
        return offered, get_state(vs, "high_water") or {}


def test_a_later_breach_opens_a_new_offer_after_the_first_went_stale(value_book_db) -> None:
    from src.value.commands import ValueCommandFailed, apply
    from src.value.store import value_session

    order("AAA", shares=10, filled=10, avg=100.0)
    _hw({"AAA": 100.0}, NOW)  # the high is 1,000
    first, state = _hw({"AAA": 74.0}, NOW)  # 26% under: offered
    assert first == state["episode"]
    eased, state = _hw({"AAA": 90.0}, NOW + timedelta(hours=1))  # 10% down: the offer is stale
    assert eased is None and "episode" not in state and "trim_offered_at" not in state
    assert state["high"] == 1000.0 and state["stop"] is True  # only the offer state is cleared
    second, state = _hw({"AAA": 60.0}, NOW + timedelta(days=2))  # 40% down: a new offer
    assert second is not None and second != first and state["episode"] == second
    with value_session() as vs, pytest.raises(ValueCommandFailed) as exc:
        apply(vs, "value_trim", {"episode": first}, requested_by="web", now=NOW, live=False)
    assert exc.value.reason == "stale_proposal"


def test_an_offer_that_outlived_its_ttl_is_renewed_while_the_book_is_still_down(
    value_book_db,
) -> None:
    from src.common.value_commands import TRIM_TTL_HOURS

    order("AAA", shares=10, filled=10, avg=100.0)
    _hw({"AAA": 100.0}, NOW)
    first, _ = _hw({"AAA": 70.0}, NOW)
    again, _ = _hw({"AAA": 70.0}, NOW + timedelta(hours=TRIM_TTL_HOURS - 1))
    assert again is None  # still live: not offered twice
    renewed, state = _hw({"AAA": 70.0}, NOW + timedelta(hours=TRIM_TTL_HOURS + 1))
    assert renewed is not None and renewed != first and state["episode"] == renewed


def test_a_trimmed_episode_is_not_offered_again_until_a_reset(value_book_db) -> None:
    from src.value.book import get_state, set_state
    from src.value.store import value_session

    order("AAA", shares=10, filled=10, avg=100.0)
    _hw({"AAA": 100.0}, NOW)
    first, state = _hw({"AAA": 70.0}, NOW)
    with value_session() as vs:
        set_state(vs, "high_water", {**state, "trimmed": True, "trimmed_at": NOW.isoformat()}, NOW)
    for hours, mark in ((1, 95.0), (80, 50.0)):
        offered, state = _hw({"AAA": mark}, NOW + timedelta(hours=hours))
        assert offered is None and state["trimmed"] is True and state["episode"] == first
    with value_session() as vs:
        assert (get_state(vs, "high_water") or {})["episode"] == first


def test_one_missing_mark_fakes_no_drawdown(value_book_db) -> None:
    order("AAA", shares=10, filled=10, avg=100.0)
    order("BBB", shares=10, filled=10, avg=100.0)
    _hw({"AAA": 100.0, "BBB": 100.0}, NOW)  # the high is 2,000
    for marks in ({"AAA": 100.0}, {"AAA": 100.0, "BBB": 0.0}):
        offered, state = _hw(marks, NOW + timedelta(hours=1))
        assert offered is None and state["stop"] is False and state["high"] == 2000.0
        assert state["value"] == 2000.0 and "episode" not in state  # nothing was updated
    offered, state = _hw({"AAA": 100.0, "BBB": 40.0}, NOW + timedelta(hours=2))  # the mark is back
    assert state["stop"] is True and offered is not None  # 1,400 vs 2,000: 30% down


# --- M1: Home stops saying "Trim offered" over a card whose tap would be refused ------------------


def test_the_trim_staleness_rule_is_shared_and_naive_aware_safe() -> None:
    state = {"trim_offered_at": NOW.isoformat(), "high": 100.0, "value": 70.0}
    assert not vc.trim_offer_stale(state, TRIM, NOW + timedelta(hours=1))
    assert vc.trim_offer_stale(state, TRIM, NOW + timedelta(hours=vc.TRIM_TTL_HOURS + 1))
    assert vc.trim_offer_stale({**state, "value": 90.0}, TRIM, NOW)  # eased
    assert not vc.trim_offer_stale({"trim_offered_at": "garbage"}, TRIM, NOW)  # unknown
    aware = NOW.replace(tzinfo=UTC)
    assert not vc.trim_offer_stale(state, TRIM, aware)  # a mixed clock never raises or refuses


def test_the_book_and_the_api_use_the_one_staleness_rule() -> None:
    for rel in ("src/value/book.py", "src/api/routers/value.py"):
        mods = {
            n.module
            for n in ast.walk(ast.parse((ROOT / rel).read_text(encoding="utf-8")))
            if isinstance(n, ast.ImportFrom)
        }
        assert "src.common.value_commands" in mods


# --- M2: a command the TTL sweep expired is not flipped; the value drain skips old rows -----------


def test_mark_applied_and_failed_leave_an_expired_command_expired(db) -> None:
    from src.storage import app_commands as ac
    from src.storage.db import session_scope

    with session_scope() as s:
        a, _ = ac.enqueue_command(
            s,
            kind="value_approve",
            payload={"proposal_id": 1, "fingerprint": "abcdef0123"},
            requested_by="web",
        )
        b, _ = ac.enqueue_command(
            s,
            kind="value_approve",
            payload={"proposal_id": 2, "fingerprint": "abcdef0123"},
            requested_by="web",
        )
        a.status = b.status = "expired"
        s.flush()
        ac.mark_applied(s, a.id, {"ok": True})
        ac.mark_failed(s, b.id, "stale_proposal")
        s.flush()
        s.refresh(a)
        s.refresh(b)
        assert (a.status, b.status) == ("expired", "expired")


def test_the_value_drain_skips_a_command_older_than_the_ttl() -> None:
    src = (ROOT / "scripts" / "run_value.py").read_text(encoding="utf-8")
    drain = src[src.index("def _drain_commands") : src.index("def _post_outbox")]
    assert "ttl_minutes" in drain and "cutoff" in drain


# --- M3: an approval the cycle has moved on is still a success -----------------------------------


@pytest.mark.parametrize("status", ["funding", "sent", "filled"])
def test_approve_after_the_cycle_moved_on_is_an_idempotent_success(value_book_db, status) -> None:
    from src.value import book
    from src.value.commands import ValueCommandFailed, apply
    from src.value.store import ValueProposalRow, value_session

    with value_session() as vs:
        row = book.propose(
            vs,
            kind="buy",
            symbol="STDY",
            list_name="deep_value",
            shares=10.0,
            price=30.0,
            reason="tranche 1",
            cause="python",
            auto=False,
            now=NOW,
            ttl_hours=30.0,
        )
        assert row is not None
        pid = row.id
        fp = vc.proposal_fingerprint(row.id, row.kind, row.symbol, row.shares, row.created_at)
        row.status = status
    with value_session() as vs:
        out = apply(
            vs,
            "value_approve",
            {"proposal_id": pid, "fingerprint": fp},
            requested_by="web",
            now=NOW,
            live=False,
        )
        assert out["already"] is True and out["decision"] == "approved"
        assert vs.get(ValueProposalRow, pid).status == status  # no side effect
    with value_session() as vs, pytest.raises(ValueCommandFailed) as exc:
        apply(
            vs,
            "value_reject",
            {"proposal_id": pid, "fingerprint": fp},
            requested_by="web",
            now=NOW,
            live=False,
        )
    assert exc.value.reason == f"already_{status}"
