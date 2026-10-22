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

    async def fake_execute(ib, bot, chat_id, order_id, candidate, sizing=None):
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


# --------------------------------------------------------------------------- #
# a lot opened on a name-level bottoming signal is recorded when it is sent
# --------------------------------------------------------------------------- #


async def test_a_name_signal_lot_is_recorded_when_it_is_sent(monkeypatch):
    seed_regime(N, N)
    signal = note(pre=1).model_copy(update={"bottoming": "name"})
    _, order_id = queue("sig-1", "NVDA", 1, sizing=signal)
    executed, _ = await run_poll(monkeypatch)
    assert [oid for oid, _ in executed] == [order_id]
    (a,) = actions(kind="bottoming_lot")
    assert (a.candidate_id, a.underlying, a.deterministic_contracts, a.sent_contracts) == (
        "sig-1",
        "NVDA",
        1,
        1,
    )
    assert a.order_id == order_id


async def test_a_market_tagged_or_ordinary_lot_is_not_recorded_as_a_signal_lot(monkeypatch):
    seed_regime(N, N)
    queue("mkt-1", "NVDA", 1, sizing=note(pre=1).model_copy(update={"bottoming": "market"}))
    queue("plain-1", "WFC", 1, sizing=note(pre=1))
    executed, _ = await run_poll(monkeypatch)
    assert len(executed) == 2
    assert actions(kind="bottoming_lot") == []


# --------------------------------------------------------------------------- #
# the covered-call breakout is re-checked at send time from the frozen card (Task 16)
# --------------------------------------------------------------------------- #


def queue_call(candidate_id: str, *, strike: float, delta: float, breakout=None):
    """Queue an approved covered call the way the approval path does (snapshot = the frozen card)."""
    from src.common.schemas import Strategy
    from src.storage.db import session_scope

    cand = _make_candidate(
        candidate_id=candidate_id,
        underlying="AAPL",
        strategy=Strategy.COVERED_CALL,
        delta=delta,
        dte=21,
        current_iv=30.0,
    ).model_copy(update={"right": OptionRight.CALL, "strike": strike, "cc_breakout": breakout})
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
        return order.id


async def test_the_send_time_regate_enforces_the_breakout_frozen_on_the_card(monkeypatch):
    from src.common.schemas import CcBreakout

    seed_regime(N, N)
    frozen = CcBreakout(
        trigger_day=date.today() - timedelta(days=1),
        trigger_close=190.0,
        jump_pct=6.1,
        volume_ratio=2.3,
        broke_level=185.0,
        floor_strike=190.0,
        delta_max=0.25,
        sessions_left=4,
    )
    stock = PositionSnapshot(symbol="AAPL", sec_type="STK", position=200.0, avg_cost=150.0)
    near = queue_call("cc-near", strike=186.0, delta=0.22, breakout=frozen)
    far = queue_call("cc-far", strike=192.0, delta=0.22, breakout=frozen)
    free = queue_call("cc-free", strike=186.0, delta=0.22)  # no breakout on its card

    executed, _ = await run_poll(monkeypatch, positions=[stock])

    sent = sorted(oid for oid, _ in executed)
    assert order_row(near).state == OrderState.CANCELLED
    assert "cc_breakout_strike_floor" in (order_row(near).detail or "")
    # 200 shares cover two calls: the far strike and the card without a breakout both go
    assert sent == sorted([far, free])


# --------------------------------------------------------------------------- #
# OI-B3: the variance-premium floor is waived for a name-level signal lot only, and at send time
# the re-gate reads the tag frozen on the card (it has no fresh signals)
# --------------------------------------------------------------------------- #


def freeze_floor(order_id: int, min_credit: float = 2.5, *, tag: str | None = None) -> None:
    """Freeze a fair-value floor above the card's 1.55 credit (and optionally a tag) into the
    order snapshot, the way a below-floor signal lot reaches the queue."""
    from src.common.schemas import IdealZone
    from src.storage.db import session_scope

    with session_scope() as s:
        row = s.get(OrderRow, order_id)
        assert row is not None
        snap = dict(row.snapshot)
        snap["ideal"] = IdealZone(
            symbol=snap["underlying"],
            right=OptionRight(snap["right"]),
            dte=snap["dte"],
            spot=185.0,
            min_credit=min_credit,
        ).model_dump(mode="json")
        if tag is not None:
            base = snap.get("sizing") or note(pre=1).model_dump(mode="json")
            snap["sizing"] = {**base, "bottoming": tag}
        row.snapshot = snap


async def test_a_below_floor_signal_lot_is_sent_and_the_waiver_is_recorded(monkeypatch):
    seed_regime(N, N)
    _, order_id = queue(
        "sig-vrp", "NVDA", 1, sizing=note(pre=1).model_copy(update={"bottoming": "name"})
    )
    freeze_floor(order_id)

    executed, _ = await run_poll(monkeypatch)

    assert [oid for oid, _ in executed] == [order_id]
    sent = executed[0][1]
    assert sent.sizing is not None  # type: ignore[attr-defined]
    assert sent.sizing.bottoming == "name" and sent.sizing.vrp_waived is True  # type: ignore[attr-defined]
    (a,) = actions(kind="bottoming_lot")
    assert a.order_id == order_id
    assert "premium_below_fair_value" in a.reason and "waived" in a.reason


async def test_a_signal_lot_that_clears_the_floor_records_no_waiver(monkeypatch):
    seed_regime(N, N)
    _, order_id = queue(
        "sig-ok", "NVDA", 1, sizing=note(pre=1).model_copy(update={"bottoming": "name"})
    )
    freeze_floor(order_id, min_credit=1.0)  # the 1.55 credit is above the floor

    executed, _ = await run_poll(monkeypatch)

    assert [oid for oid, _ in executed] == [order_id]
    assert executed[0][1].sizing.vrp_waived is False  # type: ignore[attr-defined]
    (a,) = actions(kind="bottoming_lot")
    assert "waived" not in a.reason


@pytest.mark.parametrize("tag", [None, "market"])
async def test_a_below_floor_lot_without_the_name_tag_is_refused_at_send_time(monkeypatch, tag):
    seed_regime(N, N)
    sizing = note(pre=1).model_copy(update={"bottoming": tag})
    _, order_id = queue("plain-vrp", "NVDA", 1, sizing=sizing)
    freeze_floor(order_id)

    executed, _ = await run_poll(monkeypatch)

    assert executed == []
    row = order_row(order_id)
    assert row.state == OrderState.CANCELLED
    assert "premium_below_fair_value" in (row.detail or "")


async def test_a_name_tag_stops_waiving_when_the_regime_is_suspended_before_the_send(monkeypatch):
    from src.storage.regime_state import suspend_regime

    seed_regime(N, N)
    suspend_regime(today_et())  # /regime off: no signal lots exist while it is in force
    _, order_id = queue(
        "sig-off", "NVDA", 1, sizing=note(pre=1).model_copy(update={"bottoming": "name"})
    )
    freeze_floor(order_id)

    executed, _ = await run_poll(monkeypatch)

    assert executed == []
    assert "premium_below_fair_value" in (order_row(order_id).detail or "")


async def test_a_forged_name_tag_on_a_queued_covered_call_waives_nothing(monkeypatch):
    seed_regime(N, N)
    order_id = queue_call("cc-forged", strike=186.0, delta=0.22)
    freeze_floor(order_id, tag="name")
    stock = PositionSnapshot(symbol="AAPL", sec_type="STK", position=200.0, avg_cost=150.0)

    executed, _ = await run_poll(monkeypatch, positions=[stock])

    assert executed == []
    row = order_row(order_id)
    assert row.state == OrderState.CANCELLED
    assert "premium_below_fair_value" in (row.detail or "")


# --------------------------------------------------------------------------- #
# R1 (whole-branch review): a send-time sizing context that cannot be built (a bad typed block)
# holds new puts and calls but never stops a queued roll
# --------------------------------------------------------------------------- #


def queue_roll(candidate_id: str) -> int:
    """Queue an approved CSP roll the way the roll pipeline does (snapshot = the frozen card)."""
    from src.common.schemas import RollOrigin, Strategy
    from src.storage.db import session_scope

    origin = RollOrigin(
        con_id=1,
        candidate_id="c-old",
        strike=190.0,
        expiry=date.today() + timedelta(days=3),
        right=OptionRight.PUT,
        contracts=1,
        chain_id="c-old",
        seq=1,
        original_expiry=date.today() + timedelta(days=3),
        old_mid=5.0,
        new_mid=5.4,
    )
    cand = _make_candidate(
        candidate_id=candidate_id,
        underlying="NVDA",
        strategy=Strategy.ROLL,
        current_iv=30.0,
        dte=21,
    ).model_copy(update={"roll_from": origin, "roc_pct": 0.0, "annualized_yield_pct": 0.0})
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
        return order.id


def break_risk_block(monkeypatch, how: str) -> None:
    """Make one of the typed sizing blocks invalid the ways the operator can: a mistyped key in
    a block typed in by hand, or a strategy ``delta_min`` retuned up to a guard's cap (the
    guard then leaves an empty delta band, which both getters refuse)."""
    risk = get_config().risk
    if how == "regime_typo":
        set_risk(monkeypatch, regime={"enabledd": True})
    elif how == "leveraged_typo":
        set_risk(monkeypatch, leveraged_sizing={"enabledd": True})
    elif how == "cc_delta_min":
        set_risk(monkeypatch, covered_call={**risk["covered_call"], "delta_min": 0.25})
    elif how == "csp_delta_min":
        set_risk(monkeypatch, cash_secured_put={**risk["cash_secured_put"], "delta_min": 0.25})
    else:  # pragma: no cover
        raise AssertionError(how)


BAD_BLOCKS = ["regime_typo", "leveraged_typo", "cc_delta_min", "csp_delta_min"]


def alert_texts(bot) -> list[str]:
    return [c.kwargs.get("text", "") for c in bot.send_message.call_args_list]


@pytest.mark.parametrize("how", BAD_BLOCKS)
async def test_a_bad_sizing_block_still_sends_a_queued_roll_and_holds_a_put_and_a_call(
    monkeypatch, how
):
    seed_regime(N, N)
    roll_id = queue_roll("roll-1")
    _, csp_id = queue("csp-1", "BAC", 1, sizing=note(pre=1))
    call_id = queue_call("cc-1", strike=192.0, delta=0.22)
    stock = PositionSnapshot(symbol="AAPL", sec_type="STK", position=200.0, avg_cost=150.0)
    break_risk_block(monkeypatch, how)

    executed, _ = await run_poll(monkeypatch, positions=[stock])

    # the roll went to the executor, with no sizing context (as the roll executor sends it)
    assert [oid for oid, _ in executed] == [roll_id]
    assert order_row(roll_id).state == OrderState.SUBMITTED
    # the put and the call are neither sent nor cancelled: they wait for the next poll
    assert order_row(csp_id).state == OrderState.QUEUED
    assert order_row(call_id).state == OrderState.QUEUED


@pytest.mark.parametrize("how", BAD_BLOCKS)
async def test_the_held_put_is_sent_as_soon_as_the_block_is_valid_again(monkeypatch, how):
    seed_regime(N, N)
    _, csp_id = queue("csp-1", "BAC", 1, sizing=note(pre=1))
    with monkeypatch.context() as broken:
        break_risk_block(broken, how)
        executed, _ = await run_poll(monkeypatch)
        assert executed == []
    executed, _ = await run_poll(monkeypatch)  # config fixed
    assert [oid for oid, _ in executed] == [csp_id]


async def test_a_bad_sizing_block_never_sends_a_put_without_the_regime_limits(monkeypatch):
    """The fail-closed half: with the limits unreadable no put or call reaches the executor, not
    even one the regime would have allowed in full (the fail-open mutation sends it)."""
    seed_regime(X, X)  # a crisis regime: a 10-lot NVDA put must never go out unlimited
    _, csp_id = queue("csp-big", "NVDA", 10, sizing=note(pre=10, regime=N))
    break_risk_block(monkeypatch, "regime_typo")

    executed, _ = await run_poll(monkeypatch)

    assert executed == []
    assert order_row(csp_id).state == OrderState.QUEUED


async def test_the_config_alert_names_the_error_and_goes_out_once_per_day(monkeypatch):
    from src.execution.approval import SIZING_CONFIG_ALERT_KEY
    from src.storage.system_settings import get_setting, set_setting

    seed_regime(N, N)
    queue_roll("roll-1")
    queue("csp-1", "BAC", 1, sizing=note(pre=1))
    break_risk_block(monkeypatch, "regime_typo")

    _, bot1 = await run_poll(monkeypatch)
    _, bot2 = await run_poll(monkeypatch)
    _, bot3 = await run_poll(monkeypatch)

    first = alert_texts(bot1)
    assert len(first) == 1
    text = first[0]
    assert "regime" in text and "enabledd" in text  # names the block and the bad key
    assert "on hold" in text and "rolls" in text and "keep" in text
    assert alert_texts(bot2) == [] and alert_texts(bot3) == []
    assert get_setting(SIZING_CONFIG_ALERT_KEY) == today_et().isoformat()

    # the next ET day it speaks again (the remembered day is yesterday's)
    set_setting(SIZING_CONFIG_ALERT_KEY, (today_et() - timedelta(days=1)).isoformat())
    _, bot4 = await run_poll(monkeypatch)
    assert len(alert_texts(bot4)) == 1


async def test_a_failure_that_is_not_a_config_error_is_held_and_alerted_with_its_own_text(
    monkeypatch,
):
    import src.execution.approval as approval

    seed_regime(N, N)
    roll_id = queue_roll("roll-1")
    _, csp_id = queue("csp-1", "BAC", 1, sizing=note(pre=1))

    def boom(now, positions):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(approval, "_send_context", boom)
    executed, bot = await run_poll(monkeypatch)

    assert [oid for oid, _ in executed] == [roll_id]
    assert order_row(csp_id).state == OrderState.QUEUED
    (text,) = alert_texts(bot)
    assert "database is locked" in text


async def test_a_good_config_changes_nothing(monkeypatch):
    seed_regime(N, N)
    roll_id = queue_roll("roll-1")
    _, csp_id = queue("csp-1", "BAC", 1, sizing=note(pre=1))

    executed, bot = await run_poll(monkeypatch)

    assert sorted(oid for oid, _ in executed) == sorted([roll_id, csp_id])
    assert not any("on hold" in t for t in alert_texts(bot))


async def test_a_breaker_halt_with_a_bad_block_still_sends_the_queued_roll(monkeypatch):
    from src.storage.system_settings import set_halted

    seed_regime(N, N)
    roll_id = queue_roll("roll-1")
    _, csp_id = queue("csp-1", "BAC", 1, sizing=note(pre=1))
    set_halted(True, "Daily mark-to-market loss", source="breaker")
    break_risk_block(monkeypatch, "regime_typo")

    executed, _ = await run_poll(monkeypatch)

    assert [oid for oid, _ in executed] == [roll_id]
    assert order_row(csp_id).state == OrderState.QUEUED


# the start-up check of the four typed blocks (the service still starts: refusing would also stop
# profit-takes and loss exits)


@pytest.mark.parametrize("how", BAD_BLOCKS)
async def test_the_startup_check_alerts_and_does_not_raise(monkeypatch, how):
    from src.execution.approval import check_sizing_config_at_startup

    break_risk_block(monkeypatch, how)
    bot = AsyncMock()

    errors = await check_sizing_config_at_startup(bot, "99999")

    assert errors  # it reports what is wrong
    (text,) = alert_texts(bot)
    assert "on hold" in text and "rolls" in text


async def test_the_startup_check_is_silent_with_a_good_config(monkeypatch):
    from src.execution.approval import check_sizing_config_at_startup

    bot = AsyncMock()
    assert await check_sizing_config_at_startup(bot, "99999") == []
    bot.send_message.assert_not_called()


async def test_the_startup_check_survives_a_failing_telegram_send(monkeypatch):
    from src.execution.approval import check_sizing_config_at_startup

    break_risk_block(monkeypatch, "regime_typo")
    bot = AsyncMock()
    bot.send_message.side_effect = RuntimeError("telegram down")

    assert await check_sizing_config_at_startup(bot, "99999")  # no exception


async def test_the_startup_alert_is_the_days_alert(monkeypatch):
    """A startup alert counts as the day's alert, so the first poll does not repeat it."""
    from src.execution.approval import check_sizing_config_at_startup

    seed_regime(N, N)
    queue("csp-1", "BAC", 1, sizing=note(pre=1))
    break_risk_block(monkeypatch, "regime_typo")
    await check_sizing_config_at_startup(AsyncMock(), "99999")

    executed, bot = await run_poll(monkeypatch)

    assert executed == [] and alert_texts(bot) == []


def test_the_service_runs_the_startup_check_before_it_arms_the_order_poll():
    """`_run_service` is not unit-testable without Telegram and IBKR, so (as the autonomy rung's
    enforcement does) the call is pinned textually: it must exist, and come before the order-poll
    loop is created."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    text = (root / "src" / "notify" / "approval_service.py").read_text(encoding="utf-8")
    assert text.index("check_sizing_config_at_startup(") < text.rindex("_order_poll_loop(")


# --------------------------------------------------------------------------- #
# R2 (whole-branch review): a card that first becomes a guaranteed-floor lot AT SEND TIME is
# written back to its order snapshot, so the floor's daily count sees it
# --------------------------------------------------------------------------- #


def floor_setup(monkeypatch) -> None:
    """A crisis regime and a book that fits the unscaled caps but not the scaled ones: a one-lot
    card has nothing but the guaranteed floor to get through on (as the floor tests above)."""
    set_portfolio(monkeypatch, max_csp_allocation_pct_of_deployable=130.0)
    seed_regime(X, X)


async def test_a_card_that_first_becomes_a_floor_lot_at_send_time_is_counted(monkeypatch):
    floor_setup(monkeypatch)
    # queued under a calm regime: nothing on the card says "floor lot"
    _, first = queue("c-bac", "BAC", 1, sizing=note(pre=1))
    assert order_row(first).snapshot["sizing"]["floor_lot"] is False

    executed, _ = await run_poll(monkeypatch, positions=[book(323_200)])

    assert [oid for oid, _ in executed] == [first]
    assert executed[0][1].sizing.floor_lot is True  # type: ignore[attr-defined]
    # the order's snapshot (what the day's counts read) now says so too
    assert order_row(first).snapshot["sizing"]["floor_lot"] is True

    # a second ordinary card in the next poll of the same crisis day finds the floor used up
    # (crisis floor: 1 lot a day per index)
    _, second = queue("c-wfc", "WFC", 1, sizing=note(pre=1))
    executed2, _ = await run_poll(monkeypatch, positions=[book(323_200)])

    assert executed2 == []
    row = order_row(second)
    assert row.state == OrderState.CANCELLED and "regime_budget" in (row.detail or "")


async def test_the_floor_lot_taken_at_send_time_is_recorded_once(monkeypatch):
    floor_setup(monkeypatch)
    _, order_id = queue("c-bac", "BAC", 1, sizing=note(pre=1))

    await run_poll(monkeypatch, positions=[book(323_200)])

    (a,) = actions(kind="regime_floor_lot")
    assert (a.candidate_id, a.underlying, a.deterministic_contracts, a.sent_contracts) == (
        "c-bac",
        "BAC",
        1,
        1,
    )
    assert a.order_id == order_id and a.regime == "crisis"
    # recording again for the same card and day updates the row, never adds a second
    record_action(
        cand=_candidate_from(order_id),
        kind="regime_floor_lot",
        deterministic=1,
        sent=1,
        reason="again",
        order_id=order_id,
    )
    assert len(actions(kind="regime_floor_lot")) == 1


def _candidate_from(order_id: int):
    from src.common.schemas import TradeCandidate

    return TradeCandidate.model_validate(order_row(order_id).snapshot)


async def test_a_card_already_recorded_as_a_floor_lot_at_scan_time_keeps_one_row(monkeypatch):
    """The scan recorded the floor lot (keyed by the card); the send updates that row and links it."""
    floor_setup(monkeypatch)
    cand, order_id = queue("c-bac", "BAC", 1, sizing=note(pre=2, regime=X, floor=True))
    record_action(
        cand=cand,
        kind="regime_floor_lot",
        deterministic=1,
        sent=1,
        reason="guaranteed floor lot under SPY crisis",
    )
    assert actions(kind="regime_floor_lot")[0].order_id is None

    await run_poll(monkeypatch, positions=[book(323_200)])

    (a,) = actions(kind="regime_floor_lot")
    assert a.order_id == order_id
    assert order_row(order_id).snapshot["sizing"]["floor_lot"] is True


async def test_persisting_the_tags_keeps_the_frozen_zone_the_signal_tag_and_the_size(monkeypatch):
    """The send-time gate deliberately keeps a name-level signal lot's tag and frozen zone (Task 7
    ruling 6): writing the gate's tags back must not erase them or move the contract count."""
    floor_setup(monkeypatch)
    zone = ScaleInZone(
        anchor=190.0,
        anchor_source="order_snapshot",
        zone_low=170.0,
        zone_high=178.0,
        support=172.0,
        min_gap_pct=6.0,
        triggers=["loss_exit"],
        bottoming_signal=True,
    )
    frozen = note(pre=1).model_copy(update={"bottoming": "name", "scale_in": zone})
    _, order_id = queue("c-sig", "BAC", 1, sizing=frozen)

    executed, _ = await run_poll(monkeypatch, positions=[book(323_200)])

    assert [oid for oid, _ in executed] == [order_id]
    snap = order_row(order_id).snapshot
    assert snap["sizing"]["floor_lot"] is True  # the new tag is there
    assert snap["sizing"]["bottoming"] == "name"  # the frozen ones are not erased
    assert snap["sizing"]["scale_in"] == zone.model_dump(mode="json")
    assert snap["contracts"] == 1 and executed[0][1].contracts == 1  # type: ignore[attr-defined]


async def test_a_card_that_no_longer_needs_the_floor_is_not_counted_as_one(monkeypatch):
    """Tagged at scan, but the book now fits the scaled caps: it used none of the floor, so the
    day's floor count must not include it."""
    seed_regime(N, N)
    _, order_id = queue("c-bac", "BAC", 1, sizing=note(pre=2, floor=True))

    executed, _ = await run_poll(monkeypatch)

    assert [oid for oid, _ in executed] == [order_id]
    assert order_row(order_id).snapshot["sizing"]["floor_lot"] is False
    assert actions(kind="regime_floor_lot") == []


async def test_a_non_floor_order_leaves_its_snapshot_as_it_was(monkeypatch):
    seed_regime(N, N)
    _, order_id = queue("c-bac", "BAC", 1, sizing=note(pre=1))
    before = order_row(order_id).snapshot

    await run_poll(monkeypatch)

    assert order_row(order_id).snapshot["sizing"] == before["sizing"]
    assert actions() == []


# --------------------------------------------------------------------------- #
# R3 (whole-branch review): two queued signal lots on one name, approved a poll apart
# --------------------------------------------------------------------------- #


def queue_signal_lot(candidate_id: str, underlying: str = "NVDA") -> int:
    """A queued name-level signal lot whose credit is under the frozen fair-value floor."""
    _, order_id = queue(
        candidate_id,
        underlying,
        1,
        sizing=note(pre=1).model_copy(update={"bottoming": "name"}),
    )
    freeze_floor(order_id)
    return order_id


async def test_a_second_signal_lot_on_a_name_is_refused_in_a_later_poll(monkeypatch):
    seed_regime(N, N)
    first = queue_signal_lot("sig-1")
    executed, _ = await run_poll(monkeypatch)
    assert [oid for oid, _ in executed] == [first]
    assert [a.candidate_id for a in actions(kind="bottoming_lot")] == ["sig-1"]

    # a second card on the same name, queued before the first was sent, is approved a poll later
    second = queue_signal_lot("sig-2")
    executed2, _ = await run_poll(monkeypatch)

    assert executed2 == []
    row = order_row(second)
    assert row.state == OrderState.CANCELLED
    assert "bottoming_lot_recent" in (row.detail or "")
    assert "premium_below_fair_value" in (row.detail or "")  # the waiver was not applied to it
    assert [a.candidate_id for a in actions(kind="bottoming_lot")] == ["sig-1"]  # not recorded


async def test_two_signal_lots_queued_for_one_poll_send_only_the_first(monkeypatch):
    seed_regime(N, N)
    first = queue_signal_lot("sig-1")
    second = queue_signal_lot("sig-2")

    executed, _ = await run_poll(monkeypatch)

    assert len(executed) == 1
    sent_id = executed[0][0]
    other = second if sent_id == first else first
    assert order_row(other).state == OrderState.CANCELLED
    assert len(actions(kind="bottoming_lot")) == 1


async def test_signal_lots_on_two_different_names_both_go(monkeypatch):
    seed_regime(N, N)
    a = queue_signal_lot("sig-nvda", "NVDA")
    b = queue_signal_lot("sig-amd", "AMD")

    executed, _ = await run_poll(monkeypatch)

    assert sorted(oid for oid, _ in executed) == sorted([a, b])
    assert len(actions(kind="bottoming_lot")) == 2


async def test_a_signal_lot_on_a_name_sent_before_the_window_is_not_blocked(monkeypatch):
    """The guard is N sessions, not forever: a lot recorded four trading days ago is outside it."""
    from src.regime.actions import record_action as rec

    seed_regime(N, N)
    old = _make_candidate(candidate_id="sig-old", underlying="NVDA", dte=21)
    rec(cand=old, kind="bottoming_lot", deterministic=1, sent=1, reason="old")
    from src.storage.db import session_scope

    with session_scope() as s:
        row = s.query(SizingActionRow).filter_by(candidate_id="sig-old").one()
        row.action_day = today_et() - timedelta(days=10)
    second = queue_signal_lot("sig-2")

    executed, _ = await run_poll(monkeypatch)

    assert [oid for oid, _ in executed] == [second]


async def test_a_market_eased_or_ordinary_lot_after_a_signal_lot_is_not_refused(monkeypatch):
    seed_regime(N, N)
    queue_signal_lot("sig-1")
    await run_poll(monkeypatch)
    queue("mkt", "NVDA", 1, sizing=note(pre=1).model_copy(update={"bottoming": "market"}))
    queue("plain", "WFC", 1, sizing=note(pre=1))

    executed, _ = await run_poll(monkeypatch)

    assert sorted(c.candidate_id for _, c in executed) == ["mkt", "plain"]  # type: ignore[attr-defined]
