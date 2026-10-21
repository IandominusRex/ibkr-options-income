"""The send-time regime re-check, the trim, and the counterfactual record (Task 4).

Between a card and its send the regime can escalate, a budget can shrink, a floor can be used
up. At send time the order is *trimmed down* to the current limit (never up), or refused with
the regime's reason; every trim is written once per day to `sizing_actions` for a human to read.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.config import get_config
from src.common.market_hours import today_et
from src.common.schemas import (
    AccountSnapshot,
    ApprovalStatus,
    FundamentalStats,
    IndexRegime,
    MarketRegime,
    OptionRight,
    OrderState,
    PositionSnapshot,
    RegimeInputs,
    RegimeState,
    RiskVerdict,
    ScaleInZone,
    SizingContext,
    SizingNote,
    Verdict,
)
from src.engine.regime_limits import trim_for_send
from src.regime.actions import record_action, record_scan_actions
from src.storage.models import ApprovalRow, OrderRow, SizingActionRow
from tests.test_execution import _db_setup, _make_candidate

N = MarketRegime.NORMAL
C = MarketRegime.CAUTIOUS
S = MarketRegime.STRESSED
X = MarketRegime.CRISIS


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    _db_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "src.execution.approval.get_fundamental_stats", lambda s: FundamentalStats(symbol=s)
    )
    mock_cfg = MagicMock()
    mock_cfg.secrets.ibkr_account = ""
    mock_cfg.execution.transmit_only_in_rth = False
    monkeypatch.setattr("src.execution.approval.get_config", lambda: mock_cfg)
    monkeypatch.setattr("src.execution.approval.is_rth", lambda: True)
    monkeypatch.setattr("src.execution.approval.evaluate_breakers", lambda positions, nlv: None)
    monkeypatch.setattr("src.execution.approval.remaining_entry_allowance", lambda s: None)


def seed_regime(spy: MarketRegime = N, qqq: MarketRegime = N) -> None:
    from src.storage.regime_state import save_regime_state

    today = today_et()

    def ir(index: str, r: MarketRegime) -> IndexRegime:
        return IndexRegime(
            index=index,  # type: ignore[arg-type]
            base=r,
            base_date=today,
            since=today,
            base_since=today,
            effective=r,
            inputs=RegimeInputs(),
        )

    save_regime_state(RegimeState(as_of=datetime.now(UTC), spy=ir("SPY", spy), qqq=ir("QQQ", qqq)))


def set_risk(monkeypatch, **blocks) -> None:
    cfg = get_config()
    risk = dict(cfg.risk)
    risk.update(blocks)
    monkeypatch.setattr(cfg, "risk", risk)


def set_portfolio(monkeypatch, **overrides) -> None:
    set_risk(monkeypatch, portfolio={**get_config().risk["portfolio"], **overrides})


def account(excess: float = 400_000.0, net_liq: float = 500_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=net_liq,
        total_cash=excess,
        buying_power=excess,
        maintenance_margin=0.0,
        excess_liquidity=excess,
    )


def book(collateral: float, underlying: str = "BOOK") -> PositionSnapshot:
    return PositionSnapshot(
        symbol=f"{underlying} 261120P",
        sec_type="OPT",
        position=-10.0,
        avg_cost=1.0,
        right=OptionRight.PUT,
        strike=collateral / 1000.0,
        expiry=date.today() + timedelta(days=30),
        underlying=underlying,
    )


def note(
    *, pre: int, regime: MarketRegime = N, index: str = "SPY", leverage=None, tier=None, floor=False
) -> SizingNote:
    return SizingNote(
        pre_regime_contracts=pre,
        regime=regime,
        regime_index=index,  # type: ignore[arg-type]
        per_trade_cap=10,
        budget_multiplier=1.0,
        leverage=leverage,
        leverage_tier=tier,
        floor_lot=floor,
    )


def queue(
    candidate_id: str, underlying: str, contracts: int, *, sizing: SizingNote | None = None, **kw
):
    """Queue an approved CSP the way the approval path does: an approval + a QUEUED order whose
    snapshot is the frozen card."""
    from src.storage.db import session_scope

    # With an IV the risk-unit budgets apply (without one the gate falls back to the stricter
    # raw-collateral cap, which would reject these lots for an unrelated reason).
    kw.setdefault("current_iv", 30.0)
    cand = _make_candidate(
        candidate_id=candidate_id,
        underlying=underlying,
        contracts=contracts,
        collateral=185.0 * contracts * 100,
        dte=21,
        **kw,
    ).model_copy(update={"sizing": sizing})
    with session_scope() as s:
        approval = ApprovalRow(
            candidate_id=candidate_id,
            status=ApprovalStatus.APPROVED,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        s.add(approval)
        s.flush()
        order = OrderRow(
            candidate_id=candidate_id,
            approval_id=approval.id,
            state=OrderState.QUEUED,
            snapshot=cand.model_dump(mode="json"),
        )
        s.add(order)
        s.flush()
        return cand, order.id


def add_sent_order(candidate_id: str, underlying: str, *, floor_lot: bool = False) -> None:
    """A CSP order already sent today (it counts toward the day's limit)."""
    from src.storage.db import session_scope

    snap = {
        "strategy": "cash_secured_put",
        "underlying": underlying,
        "sizing": {"floor_lot": floor_lot},
    }
    with session_scope() as s:
        s.add(OrderRow(candidate_id=candidate_id, state=OrderState.FILLED, snapshot=snap))


async def run_poll(monkeypatch, *, acct: AccountSnapshot | None = None, positions=None):
    """Run one order-poll pass; return the (order_id, candidate) pairs handed to the executor."""
    executed: list[tuple[int, object]] = []

    async def fake_execute(ib, bot, chat_id, order_id, candidate):
        executed.append((order_id, candidate))

    monkeypatch.setattr("src.execution.approval.execute_candidate", fake_execute)
    monkeypatch.setattr(
        "src.execution.approval.get_account_snapshot_async",
        AsyncMock(return_value=acct or account()),
    )
    monkeypatch.setattr("src.execution.approval.get_positions", lambda ib: positions or [])
    from src.execution.approval import process_queued_orders

    ib = MagicMock()
    ib.managedAccounts.return_value = ["DU1"]
    bot = AsyncMock()
    await process_queued_orders(ib, bot, "99999")
    return executed, bot


def order_row(order_id: int) -> OrderRow:
    from src.storage.db import session_scope

    with session_scope() as s:
        row = s.get(OrderRow, order_id)
        assert row is not None
        s.expunge(row)
        return row


def actions(**filters) -> list[SizingActionRow]:
    from src.storage.db import session_scope

    with session_scope() as s:
        rows = s.query(SizingActionRow).filter_by(**filters).order_by(SizingActionRow.id).all()
        for r in rows:
            s.expunge(r)
        return rows


# --------------------------------------------------------------------------- #
# the trim at send time
# --------------------------------------------------------------------------- #


async def test_escalation_after_approval_trims_down_and_notes_it(monkeypatch):
    seed_regime(N, S)  # QQQ escalated to stressed since the card
    cand, order_id = queue("c-1", "NVDA", 10, sizing=note(pre=10))

    executed, bot = await run_poll(monkeypatch)

    assert [(oid, c.contracts) for oid, c in executed] == [(order_id, 3)]
    sent = executed[0][1]
    assert sent.collateral == 185.0 * 3 * 100  # type: ignore[attr-defined]
    row = order_row(order_id)
    assert row.snapshot["contracts"] == 3  # the frozen order is the trimmed one
    assert row.snapshot["collateral"] == 185.0 * 3 * 100
    assert "trimmed 10 -> 3 by the market regime (QQQ stressed)" in (row.detail or "")
    (a,) = actions(kind="escalation_trim")
    assert (a.candidate_id, a.deterministic_contracts, a.sent_contracts) == ("c-1", 10, 3)
    assert a.order_id == order_id and a.regime == "stressed" and a.underlying == "NVDA"
    # the operator hears about it
    texts = [c.kwargs.get("text", "") for c in bot.send_message.call_args_list]
    assert any("trimmed 10 -> 3" in t for t in texts)


async def test_a_normal_regime_never_trims(monkeypatch):
    seed_regime(N, N)
    _, order_id = queue("c-1", "NVDA", 10, sizing=note(pre=10))
    executed, _ = await run_poll(monkeypatch, acct=account(excess=900_000.0, net_liq=2_000_000.0))
    assert [(oid, c.contracts) for oid, c in executed] == [(order_id, 10)]  # type: ignore[attr-defined]
    assert actions() == []


async def test_a_normal_regime_leaves_budget_rejections_to_the_gate(monkeypatch):
    """The trim is a regime behaviour: with the regime normal a card that no longer fits the book
    is refused by the gate exactly as before, not quietly shrunk."""
    seed_regime(N, N)
    _, order_id = queue("c-1", "BAC", 10, sizing=note(pre=10))
    executed, _ = await run_poll(monkeypatch, positions=[book(250_000)])  # 250k + 185k > 320k
    assert executed == []
    row = order_row(order_id)
    assert row.state == OrderState.CANCELLED and "csp_allocation_limit" in (row.detail or "")
    assert actions() == []


async def test_the_decision_time_rows_are_linked_to_the_order_when_it_is_sent(monkeypatch):
    seed_regime(N, N)
    cand, order_id = queue("c-1", "NVDA", 2, sizing=note(pre=2))
    # recorded by the scan when the card was made (no order existed yet)
    record_action(cand=cand, kind="regime_ceiling", deterministic=4, sent=2, reason="scan")
    (before,) = actions()
    assert before.order_id is None

    executed, _ = await run_poll(monkeypatch)

    assert len(executed) == 1
    (after,) = actions()
    assert after.order_id == order_id


async def test_escalation_to_a_zero_limit_rejects_with_the_regime_reason(monkeypatch):
    set_risk(monkeypatch, regime={"csp": {"per_trade_fraction": {"crisis": 0.0}}})
    seed_regime(N, X)
    _, order_id = queue("c-1", "NVDA", 10, sizing=note(pre=10))

    executed, bot = await run_poll(monkeypatch)

    assert executed == []
    row = order_row(order_id)
    assert row.state == OrderState.CANCELLED
    assert "regime_ceiling" in (row.detail or "")
    assert actions(kind="escalation_trim") == []  # nothing was trimmed: it was refused


def test_trim_never_raises_a_size():
    cand = _make_candidate(contracts=2, dte=21)
    ctx = SizingContext(regimes={"SPY": S, "QQQ": S}, tech_linked=[])
    assert trim_for_send(cand, ctx, 10, None) == 2  # the cap is 3: a 2-lot stays 2
    assert trim_for_send(cand, ctx, 10, 9) == 2
    assert trim_for_send(cand, ctx, 10, 1) == 1  # a smaller budget fit trims
    assert trim_for_send(cand, ctx, 10, 0) == 0
    assert trim_for_send(cand, None, 10, 1) == 2  # no context: untouched
    cc = _make_candidate(contracts=8, dte=21).model_copy(update={"strategy": "covered_call"})
    assert trim_for_send(cc, ctx, 10, 1) == 8  # covered calls are never trimmed
    ten = _make_candidate(contracts=10, dte=21)
    assert trim_for_send(ten, ctx, 10, None) == 3


async def test_a_budget_that_shrank_since_the_card_trims_to_the_fitted_size(monkeypatch):
    # 100k of CSP collateral held; the stressed book budget is 40% of 320k = 128k, which leaves
    # room for one 18.5k lot (the unscaled 320k would have fitted all ten).
    seed_regime(S, S)
    _, order_id = queue("c-1", "BAC", 10, sizing=note(pre=10))

    executed, _ = await run_poll(monkeypatch, positions=[book(100_000)])

    assert [(oid, c.contracts) for oid, c in executed] == [(order_id, 1)]  # type: ignore[attr-defined]
    (a,) = actions()
    assert a.kind == "escalation_trim" and a.sent_contracts == 1 and a.deterministic_contracts == 10


async def test_send_time_daily_limit_counts_only_sent_orders(monkeypatch):
    seed_regime(N, S)  # QQQ stressed: at most 3 new CSPs a day
    add_sent_order("sent-1", "NVDA")
    add_sent_order("sent-2", "AMD")
    ids = {}
    for cid, sym in (("q-1", "AAPL"), ("q-2", "MSFT"), ("q-3", "GOOGL")):
        _, ids[cid] = queue(cid, sym, 1, sizing=note(pre=1))

    executed, _ = await run_poll(monkeypatch)

    # two already sent, so exactly one of the three queued fits; the queued orders themselves
    # are the batch, not a count against it
    assert len(executed) == 1
    states = {cid: order_row(oid).state for cid, oid in ids.items()}
    assert sorted(states.values()) == [
        OrderState.CANCELLED,
        OrderState.CANCELLED,
        OrderState.SUBMITTED,
    ]
    cancelled = [
        order_row(oid).detail
        for oid in ids.values()
        if order_row(oid).state == OrderState.CANCELLED
    ]
    assert all("regime_daily_limit" in (d or "") for d in cancelled)


async def test_leveraged_trim_at_send_time_is_recorded_as_leveraged_ceiling(monkeypatch):
    # a calm 6-lot TQQQ card; QQQ escalates to stressed before the send -> the stressed tier
    seed_regime(N, S)
    _, order_id = queue("c-1", "TQQQ", 6, sizing=note(pre=10, leverage=3, tier="calm"))
    executed, _ = await run_poll(monkeypatch)
    assert [(oid, c.contracts) for oid, c in executed] == [(order_id, 1)]  # type: ignore[attr-defined]
    (a,) = actions()
    assert a.kind == "leveraged_ceiling"
    assert (a.deterministic_contracts, a.sent_contracts) == (6, 1)
    assert "leveraged ETF" in (order_row(order_id).detail or "")


async def test_leveraged_tier_never_loosens_at_send_time(monkeypatch):
    # The card was cut under the stressed tier (a ladder trigger then); the send-time context has
    # no bars to recompute the trigger, so the snapshot's tier holds: a 5-lot that cannot be a
    # calm-tier size in the first place is cut to the stressed ceiling (3), never left at 5.
    seed_regime(N, N)
    _, order_id = queue("c-1", "TQQQ", 5, sizing=note(pre=10, leverage=3, tier="stressed"))
    executed, _ = await run_poll(monkeypatch)
    assert [(oid, c.contracts) for oid, c in executed] == [(order_id, 3)]  # type: ignore[attr-defined]
    # control: the same 5-lot on a calm-tier snapshot is within the calm ceiling (6) and stays
    _, order2 = queue("c-2", "UPRO", 5, sizing=note(pre=10, leverage=3, tier="calm"))
    executed2, _ = await run_poll(monkeypatch)
    assert [(oid, c.contracts) for oid, c in executed2] == [(order2, 5)]  # type: ignore[attr-defined]


async def test_a_floor_lot_survives_send_time_while_the_floor_allows(monkeypatch):
    set_portfolio(monkeypatch, max_csp_allocation_pct_of_deployable=130.0)
    seed_regime(X, X)
    _, order_id = queue("c-1", "BAC", 1, sizing=note(pre=2, regime=X, floor=True))

    executed, _ = await run_poll(monkeypatch, positions=[book(323_200)])

    assert [(oid, c.contracts) for oid, c in executed] == [(order_id, 1)]  # type: ignore[attr-defined]
    assert executed[0][1].sizing.floor_lot is True  # type: ignore[attr-defined]


async def test_a_second_floor_lot_at_send_time_is_rejected_regime_budget(monkeypatch):
    set_portfolio(monkeypatch, max_csp_allocation_pct_of_deployable=130.0)
    seed_regime(X, X)
    add_sent_order("sent-floor", "WFC", floor_lot=True)  # crisis floor is 1 lot a day per index
    _, order_id = queue("c-1", "BAC", 1, sizing=note(pre=2, regime=X, floor=True))

    executed, _ = await run_poll(monkeypatch, positions=[book(323_200)])

    assert executed == []
    row = order_row(order_id)
    assert row.state == OrderState.CANCELLED and "regime_budget" in (row.detail or "")


async def test_send_context_is_built_outside_the_write_session(monkeypatch):
    """The context reads the database in its own session: it must be built before the write
    session opens, or it would hold the SQLite write lock across a slow regime refresh."""
    seed_regime(N, N)
    import src.execution.approval as approval

    depth = {"n": 0}
    seen: list[int] = []
    real_scope = approval.session_scope

    @contextlib.contextmanager
    def counting_scope():
        depth["n"] += 1
        try:
            with real_scope() as s:
                yield s
        finally:
            depth["n"] -= 1

    real_ctx = approval._send_context

    def spy(now, positions):
        seen.append(depth["n"])
        return real_ctx(now, positions)

    monkeypatch.setattr(approval, "session_scope", counting_scope)
    monkeypatch.setattr(approval, "_send_context", spy)
    queue("c-1", "NVDA", 1, sizing=note(pre=1))
    await run_poll(monkeypatch)
    assert seen == [0]


async def test_send_context_marks_stressed_leveraged_names_and_fetches_the_ladder_spot(
    monkeypatch,
):
    seed_regime(N, N)
    import src.execution.approval as approval

    queue("c-1", "TQQQ", 3, sizing=note(pre=10, leverage=3, tier="stressed"))
    queue("c-2", "SOXL", 3, sizing=note(pre=10, leverage=3, tier="calm"))
    queue(
        "c-3",
        "NVDA",
        2,
        sizing=note(pre=2).model_copy(
            update={
                "scale_in": ScaleInZone(
                    anchor=190.0,
                    anchor_source="price_history",
                    zone_low=170.0,
                    zone_high=175.0,
                    min_gap_pct=5.0,
                )
            }
        ),
    )
    prices = {"NVDA": 171.5}
    monkeypatch.setattr(
        approval, "get_price_provider", lambda: SimpleNamespace(get_last_price=prices.get)
    )
    ctx = approval._send_context(datetime.now(UTC), [])
    assert ctx is not None
    assert ctx.name_triggers == {"TQQQ": ["snapshot_stressed"]}
    assert ctx.spot_at_send == {"NVDA": 171.5}


# --------------------------------------------------------------------------- #
# the counterfactual table
# --------------------------------------------------------------------------- #


def test_record_action_is_idempotent_per_day(monkeypatch):
    """Review Focus 6: the same contract trimmed every 15 minutes counts once per day."""
    cand = _make_candidate(candidate_id="c-1", underlying="NVDA", dte=21, current_iv=44.0)
    for sent in (3, 3, 2, 3):
        record_action(cand=cand, kind="regime_ceiling", deterministic=10, sent=sent, reason="r")
    (row,) = actions()
    assert row.deterministic_contracts == 10  # the first row's value is kept
    assert row.sent_contracts == 3  # the latest sent / reason are updated
    assert row.entry_iv == 44.0 and row.record_key == "c-1" and row.action_day == today_et()
    # a different kind is a different row; a new ET day is a new row
    record_action(cand=cand, kind="leveraged_ceiling", deterministic=10, sent=1, reason="r")
    assert len(actions()) == 2
    monkeypatch.setattr("src.regime.actions.today_et", lambda: today_et() + timedelta(days=1))
    record_action(cand=cand, kind="regime_ceiling", deterministic=10, sent=3, reason="r")
    assert len(actions(kind="regime_ceiling")) == 2


def test_record_action_updates_the_order_id_and_keeps_the_first_entry_iv():
    cand = _make_candidate(candidate_id="c-1", dte=21, current_iv=44.0)
    record_action(cand=cand, kind="regime_ceiling", deterministic=10, sent=3, reason="a")
    later = cand.model_copy(update={"current_iv": 55.0})
    record_action(
        cand=later, kind="regime_ceiling", deterministic=10, sent=3, reason="b", order_id=7
    )
    (row,) = actions()
    assert row.order_id == 7 and row.reason == "b" and row.entry_iv == 44.0


def test_record_action_never_raises_on_a_db_error(monkeypatch):
    cand = _make_candidate(candidate_id="c-1", dte=21)

    @contextlib.contextmanager
    def broken():
        raise RuntimeError("database is locked")
        yield  # pragma: no cover

    monkeypatch.setattr("src.regime.actions.session_scope", broken)
    record_action(cand=cand, kind="regime_ceiling", deterministic=10, sent=3, reason="r")
    # a caller-supplied session that fails is survived too
    bad = MagicMock()
    bad.query.side_effect = RuntimeError("boom")
    record_action(
        cand=cand, kind="regime_ceiling", deterministic=10, sent=3, reason="r", session=bad
    )


def test_a_failed_record_inside_a_callers_session_does_not_poison_it():
    """record_action joins the order poll's write session; if its row cannot be written (here a
    NULL strike), the poll's own work must still commit."""
    from src.storage.db import session_scope

    broken = _make_candidate(candidate_id="c-bad", dte=21).model_copy()
    broken.__dict__["strike"] = None  # bypass validation: the NOT NULL column refuses it
    with session_scope() as s:
        s.add(OrderRow(candidate_id="keeps-working", state=OrderState.QUEUED))
        record_action(
            cand=broken, kind="regime_ceiling", deterministic=3, sent=1, reason="r", session=s
        )
        s.add(OrderRow(candidate_id="also-kept", state=OrderState.QUEUED))
    with session_scope() as s:
        kept = {r.candidate_id for r in s.query(OrderRow).all()}
    assert {"keeps-working", "also-kept"} <= kept
    assert actions() == []


def _scan_candidate(cid: str, underlying: str, contracts: int, sizing: SizingNote | None):
    return _make_candidate(
        candidate_id=cid, underlying=underlying, contracts=contracts, dte=21
    ).model_copy(update={"sizing": sizing})


def test_never_sent_csp_rows_are_one_per_name_kind_and_day():
    """Ruling 44: 3 scan cycles x 4 strikes rejected for the regime budget is one row."""
    verdicts = {}
    scored = []
    for _cycle in range(3):
        scored = [_scan_candidate(f"t-{i}", "TQQQ", 3, note(pre=3, regime=S)) for i in range(4)]
        verdicts = {
            c.candidate_id: RiskVerdict(
                candidate_id=c.candidate_id, verdict=Verdict.REJECT, reasons=["regime_budget"]
            )
            for c in scored
        }
        record_scan_actions(top=[], scored=scored, verdicts=verdicts)
    (row,) = actions()
    assert row.record_key == f"csp:TQQQ:regime_budget:{today_et().isoformat()}"
    assert row.kind == "regime_budget" and row.sent_contracts == 0
    assert row.candidate_id == "t-0"  # the name's highest-ranked candidate stands for it


def test_a_name_rejected_for_a_book_reason_is_not_recorded_as_a_regime_block():
    scored = [_scan_candidate("a", "BAC", 3, note(pre=3))]
    verdicts = {
        "a": RiskVerdict(candidate_id="a", verdict=Verdict.REJECT, reasons=["concentration_limit"])
    }
    record_scan_actions(top=[], scored=scored, verdicts=verdicts)
    mixed = [_scan_candidate("b", "WFC", 3, note(pre=3))]
    mixed_v = {
        "b": RiskVerdict(
            candidate_id="b",
            verdict=Verdict.REJECT,
            reasons=["regime_budget", "concentration_limit"],
        )
    }
    record_scan_actions(top=[], scored=mixed, verdicts=mixed_v)
    assert actions() == []


def test_a_name_with_a_passing_strike_is_not_a_never_sent_row():
    scored = [
        _scan_candidate("a", "BAC", 3, note(pre=3)),
        _scan_candidate("b", "BAC", 3, note(pre=3)),
    ]
    verdicts = {
        "a": RiskVerdict(candidate_id="a", verdict=Verdict.PASS, reasons=[]),
        "b": RiskVerdict(candidate_id="b", verdict=Verdict.REJECT, reasons=["regime_daily_limit"]),
    }
    record_scan_actions(top=[], scored=scored, verdicts=verdicts)
    assert actions() == []


def test_a_surfaced_trim_and_a_floor_lot_are_recorded():
    trimmed = _scan_candidate(
        "t",
        "NVDA",
        3,
        note(pre=10, regime=S, index="QQQ").model_copy(update={"ceiling_kind": "regime_ceiling"}),
    )
    leveraged = _scan_candidate(
        "l",
        "TQQQ",
        6,
        note(pre=10, leverage=3, tier="calm").model_copy(
            update={"ceiling_kind": "leveraged_ceiling"}
        ),
    )
    floor = _scan_candidate("f", "BAC", 1, note(pre=1, regime=X, floor=True))
    untouched = _scan_candidate("u", "AAPL", 4, note(pre=4))
    plain = _scan_candidate("p", "AMD", 4, None)
    record_scan_actions(top=[trimmed, leveraged, floor, untouched, plain], scored=[], verdicts={})
    rows = {r.candidate_id: r for r in actions()}
    assert set(rows) == {"t", "l", "f"}
    assert (rows["t"].kind, rows["t"].deterministic_contracts, rows["t"].sent_contracts) == (
        "regime_ceiling",
        10,
        3,
    )
    assert (rows["l"].kind, rows["l"].deterministic_contracts, rows["l"].sent_contracts) == (
        "leveraged_ceiling",
        10,
        6,
    )
    assert (rows["f"].kind, rows["f"].deterministic_contracts, rows["f"].sent_contracts) == (
        "regime_floor_lot",
        1,
        1,
    )


async def test_scan_records_a_decision_time_trim(tmp_path, monkeypatch):
    import src.orchestrator.scan as scanmod
    from tests.test_scan_review_reuse import _candidate, _stub_pipeline

    monkeypatch.setattr(get_config(), "universe", {"would_own": ["AAPL"], "sectors": {"AAPL": "t"}})
    _stub_pipeline(scanmod, monkeypatch, {"n": 0})
    cand = _candidate().model_copy(
        update={
            "contracts": 3,
            "sizing": note(pre=10, regime=S, index="QQQ").model_copy(
                update={"ceiling_kind": "regime_ceiling"}
            ),
        }
    )
    from src.strategies._evaluation import ScreenResult

    monkeypatch.setattr(
        scanmod, "screen_csp_candidates", lambda *a, **k: ScreenResult(passed=[cand])
    )
    for _ in range(3):  # three scan cycles in one day
        await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1")
    (row,) = actions()
    assert row.kind == "regime_ceiling"
    assert (row.deterministic_contracts, row.sent_contracts) == (10, 3)
    assert row.candidate_id == cand.candidate_id and row.underlying == "AAPL"
