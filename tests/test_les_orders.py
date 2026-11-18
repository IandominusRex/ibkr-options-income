"""LES share buys and trend-break sells (risk-envelope Task 32a; spec §3.5.1, rulings L1-L7).

The LES book (``les:<id>`` -> ledger ``book="les"``) stays out of the wheel's share count and
covered calls and in the envelope at leverage; ``execution/les.py`` is the one automatic stock
path, paper only, behind ``leveraged_entry``. Every broker object here is a fake."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from src.common.books import LesExposure, attribute
from src.common.envelope_types import EnvelopeRoom, ShockInputs
from src.common.schemas import (
    AccountSnapshot,
    LesSignal,
    ParsedExecution,
    ParsedStatement,
    PositionSnapshot,
    RiskVerdict,
    SizingContext,
    StockOrderIntent,
    Verdict,
)
from src.common.value_view import ValueHolding
from src.engine.risk_engine import validate_stock_order
from src.execution import les
from src.execution.stock_orders import StockOrderResult, StockQuote
from src.ledger.contracts import stock_contract

# Monday 2026-11-16, 11:00 ET: a trading day, after the 10:00 start
NOW = datetime(2026, 11, 16, 16, 0, tzinfo=UTC)
TODAY = date(2026, 11, 16)
ACCOUNT = AccountSnapshot(
    account="DU1",
    net_liquidation=100_000.0,
    total_cash=50_000.0,
    buying_power=80_000.0,
    maintenance_margin=5_000.0,
    excess_liquidity=60_000.0,
)


def _exec(sym: str, qty: float, price: float, when: str, *, exec_id: str, ref: str | None = None):
    return ParsedExecution(
        contract=stock_contract(sym, "USD"),
        trade_time=datetime.fromisoformat(when).replace(tzinfo=UTC),
        quantity=qty,
        price=price,
        proceeds=-qty * price,
        exec_id=exec_id,
        account="U0000001",
        source_kind="exec",
        order_ref=ref,
        ib_order_id=77 if ref else None,
    )


def _ingest(*execs: ParsedExecution) -> None:
    from src.ledger.ingest import ingest

    ingest(ParsedStatement(account="U0000001", executions=list(execs)), source="flex")


# --------------------------------------------------------------------------- #
# The book
# --------------------------------------------------------------------------- #


def test_les_ref_is_its_own_book(db) -> None:
    from src.common.books import is_les_order_ref
    from src.storage.models import BrokerExecutionRow, OrderRow

    with db() as s:  # an order id that collides with a wheel order must not retag it "system"
        s.add(
            OrderRow(
                candidate_id="opt-1",
                state="filled",
                ib_order_id=77,
                snapshot={"underlying": "TQQQ"},
            )
        )
    _ingest(
        _exec("TQQQ", 30, 60.0, "2026-11-10T15:00:00", exec_id="l1", ref="les:5"),
        _exec("TQQQ", 100, 55.0, "2026-10-01T15:00:00", exec_id="w1"),
    )
    with db() as s:
        books = {r.exec_id: r.book for r in s.scalars(select(BrokerExecutionRow))}
    assert books == {"l1": "les", "w1": "manual"}
    assert is_les_order_ref("les:5") and not is_les_order_ref("value:5")


def test_wheel_share_count_excludes_les_shares(db) -> None:
    from src.storage.wheel_shares import les_shares, wheel_shares

    _ingest(
        _exec("TQQQ", 100, 55.0, "2026-10-01T15:00:00", exec_id="w1"),
        _exec("TQQQ", 30, 60.0, "2026-11-10T15:00:00", exec_id="l1", ref="les:5"),
        _exec("TQQQ", -10, 62.0, "2026-11-12T15:00:00", exec_id="l2", ref="les:6"),
    )
    assert wheel_shares(["TQQQ"])["TQQQ"].shares == 100
    assert les_shares()["TQQQ"] == pytest.approx(20)


def test_no_covered_call_against_les_shares(db, monkeypatch) -> None:
    from src.ibkr.portfolio import wheel_view

    _ingest(
        _exec("TQQQ", 100, 55.0, "2026-10-01T15:00:00", exec_id="w1"),
        _exec("SOXL", 100, 30.0, "2026-11-10T15:00:00", exec_id="l1", ref="les:5"),
        _exec("TQQQ", 50, 60.0, "2026-11-10T15:00:00", exec_id="l2", ref="les:6"),
    )
    broker = [
        PositionSnapshot(
            symbol="TQQQ", sec_type="STK", position=150, avg_cost=56.0, underlying="TQQQ"
        ),
        PositionSnapshot(
            symbol="SOXL", sec_type="STK", position=100, avg_cost=30.0, underlying="SOXL"
        ),
    ]
    view = {p.symbol: p.position for p in wheel_view(broker)}
    assert view == {"TQQQ": 100}  # only the wheel's 100; SOXL is all LES: no wheel share at all

    from src.strategies.covered_call import uncovered_call_capacity

    assert uncovered_call_capacity(wheel_view(broker), "SOXL") <= 0


def test_trim_never_sells_les_shares() -> None:
    # broker 130 TQQQ = the wheel's 100 + 30 LES shares
    att = attribute(130, 100, ValueHolding("TQQQ"), les=30)
    assert att.wheel_view == 100 and att.unexplained == 0
    trim = StockOrderIntent(
        side="SELL", symbol="TQQQ", qty=110, source="repair", ref_id="1", tapped=True
    )
    v = validate_stock_order(trim, ACCOUNT, [], envelope=None, mid=60.0, attribution=att)
    assert v.reasons == ["stock_sell_not_wheel_shares"]
    # and the LES book's own sale never takes a wheel share either
    les_sell = StockOrderIntent(side="SELL", symbol="TQQQ", qty=40, source="les")
    v2 = validate_stock_order(
        les_sell, ACCOUNT, [], envelope=None, mid=60.0, attribution=att, les_shares=30
    )
    assert v2.reasons == ["stock_sell_not_les_shares"]


def test_envelope_counts_les_shares_at_leverage() -> None:
    from src.analytics.shock import measure
    from src.analytics.shock_inputs import build_inputs

    inputs = build_inputs(
        [],
        nlv=100_000.0,
        value_by_name={},
        les_by_name={"TQQQ": 6_000.0},
        ivs={},
        spots={"TQQQ": 60.0},
        beta_map={"TQQQ": 3.0, "QQQ": 1.1},
        beta_smh_map={},
    )
    [line] = inputs.lines
    assert (line.book, line.qty, line.spot) == ("les", pytest.approx(100.0), 60.0)
    r = measure(inputs)
    assert r.s10 == pytest.approx(6_000.0 * 3 * 1.1 * 0.10 / 100_000.0 * 100)  # leverage x QQQ beta
    assert r.uew == pytest.approx(6_000.0 * 3 / 100_000.0)


# --------------------------------------------------------------------------- #
# The cycle, on fakes
# --------------------------------------------------------------------------- #


def _signal(**kw: Any) -> LesSignal:
    base = dict(
        asof=TODAY - timedelta(days=3),  # Friday's close
        index="QQQ",
        trend_up=True,
        pullback=True,
        washout=False,
        trend_break=False,
        tier_pct=3.0,
        reasons=["pullback: RSI(2) 3.1 under 5"],
    )
    base.update(kw)
    return LesSignal(**base)  # type: ignore[arg-type]


def _ctx() -> SizingContext:
    return SizingContext(regimes={}, leverage={"TQQQ": 3, "SOXL": 3})


@pytest.fixture()
def cycle(db, monkeypatch):
    """Run ``les.run_les_cycle`` on fakes: one governing pair (TQQQ -> QQQ), a quote, a book
    whose envelope admits or refuses, and a broker that fills every order."""
    from src.storage.envelope_switches import set_switch

    monkeypatch.setattr(
        les,
        "get_regime_cfg",
        lambda: type(
            "C", (), {"leveraged_entry": type("L", (), {"governing": {"TQQQ": "QQQ"}})()}
        )(),
    )
    state: dict[str, Any] = {
        "signal": _signal(),
        "held": 0.0,
        "envelope": "admit",
        "sent": [],
        "notices": [],
    }
    monkeypatch.setattr(les, "latest_signal", lambda index: state["signal"])

    async def quote(ib: Any, symbol: str) -> StockQuote:
        return StockQuote(59.95, 60.05)

    def room_inputs() -> tuple[EnvelopeRoom, ShockInputs]:
        inputs = ShockInputs(
            (),
            {"QQQ": 1.1, "TQQQ": 3.0},
            {},
            {"TQQQ": 3},
            {"TQQQ": "QQQ"},
            frozenset(),
            frozenset(),
            100_000.0,
        )
        limit = 50.0 if state["envelope"] == "admit" else 0.1
        return EnvelopeRoom(0.0, limit, 0.0, 5.0, 0.0, None, "record", True), inputs

    async def book(ib: Any, intent: StockOrderIntent, mid: float) -> dict[str, Any]:
        return {
            "account": ACCOUNT,
            "positions": [],
            "attribution": attribute(state["held"], 0.0, ValueHolding("TQQQ"), les=state["held"]),
            "envelope": room_inputs() if intent.side == "BUY" else None,
        }

    async def send(ib: Any, intent: StockOrderIntent) -> StockOrderResult:
        state["sent"].append(intent)
        return StockOrderResult(
            "filled", intent, order_id=1, filled=float(intent.qty), avg_price=60.0
        )

    async def notify(text: str) -> None:
        state["notices"].append(text)

    def les_book() -> LesExposure:
        h = state["held"]
        return LesExposure(by_name={"TQQQ": h * 60.0} if h else {}, shares={"TQQQ": h} if h else {})

    async def run(mode: str = "on", **kw: Any) -> list[les.LesAction]:
        set_switch("leveraged_entry", mode, source="cli")
        return await les.run_les_cycle(
            object(),
            ACCOUNT,
            [],
            now=kw.get("now", NOW),
            quote_fn=quote,
            book_fn=book,
            send_fn=send,
            les_fn=les_book,
            ctx_fn=lambda now: _ctx(),
            notify=notify,
        )

    state["run"] = run
    return state


def _rows(db, kind: str) -> list[Any]:
    from src.storage.models import SizingActionRow

    with db() as s:
        return [
            (r.strategy, r.underlying, r.deterministic_contracts, r.sent_contracts, r.reason)
            for r in s.query(SizingActionRow).filter_by(kind=kind)
        ]


async def test_buy_sizes_to_the_tier_room_in_whole_shares(cycle, db) -> None:
    [action] = await cycle["run"]()
    # 3% of 100k = 3,000 leverage-weighted; at 60 x 3 per share: floor(16.67) = 16
    assert action.intent.side == "BUY" and action.intent.qty == 16
    assert les.buy_shares(3_000.0, 60.0, 3) == 16
    assert les.buy_shares(170.0, 60.0, 3) == 0  # never rounded up to one share
    [sent] = cycle["sent"]
    assert sent.source == "les" and sent.ref_id is None  # orderRef les:<order id>
    assert "tier 3%" in cycle["notices"][0] and "RSI(2)" in cycle["notices"][0]
    assert _rows(db, "les_order")[0][:4] == ("stock_buy", "TQQQ", 16, 16)


async def test_no_buy_below_sma200(cycle) -> None:
    cycle["signal"] = _signal(trend_up=False, pullback=False, tier_pct=0.0)
    assert await cycle["run"]() == []
    cycle["signal"] = _signal(trend_up=False, pullback=True, tier_pct=3.0)  # a stray tier
    assert await cycle["run"]() == []
    assert cycle["sent"] == []


async def test_one_buy_per_etf_per_three_sessions(cycle, db) -> None:
    from src.storage.models import OrderRow

    with db() as s:  # an LES buy sent on Friday (one session ago)
        s.add(
            OrderRow(
                candidate_id="les:9",
                state="filled",
                order_ref="les:9",
                snapshot={"strategy": "stock_buy", "underlying": "TQQQ"},
                created_at=datetime(2026, 11, 13, 16, 0),
            )
        )
    assert await cycle["run"]() == []
    # the record mode keeps its own pace from its would-be buys
    await cycle["run"]("record")
    assert len(_rows(db, "les_record")) == 1
    later = NOW + timedelta(hours=1)
    assert await cycle["run"]("record", now=later) == []


async def test_buy_blocked_by_s10_or_uew_records_the_reason(cycle, db) -> None:
    cycle["envelope"] = "refuse"
    [action] = await cycle["run"]()
    assert action.verdict.verdict == Verdict.REJECT and "shock_budget" in action.verdict.reasons
    assert cycle["sent"] == []
    [(strategy, _sym, would, sent, reason)] = _rows(db, "les_order")
    assert (strategy, would, sent) == ("stock_buy", 16, 0) and "shock_budget" in reason


async def test_record_mode_writes_les_record_and_sends_nothing(cycle, db) -> None:
    [action] = await cycle["run"]("record")
    assert action.mode == "record" and action.result is None
    assert cycle["sent"] == [] and cycle["notices"] == []
    [(strategy, sym, would, sent, reason)] = _rows(db, "les_record")
    assert (strategy, sym, would, sent) == ("stock_buy", "TQQQ", 16, 16)
    assert reason.startswith("would buy 16 TQQQ: admitted")
    cycle["envelope"] = "refuse"
    cycle["signal"] = _signal(asof=TODAY + timedelta(days=4), washout=True, tier_pct=6.0)
    await cycle["run"]("record", now=NOW + timedelta(days=7))  # Monday next week: pace clear
    assert any("refused: shock_budget" in r[4] for r in _rows(db, "les_record"))


async def test_refused_in_live_even_with_a_tap(cycle, db, monkeypatch) -> None:
    from src.common.config import Config
    from src.storage.envelope_switches import get_switch

    tapped = StockOrderIntent(side="BUY", symbol="TQQQ", qty=1, source="les", tapped=True)
    monkeypatch.setattr(Config, "is_live", property(lambda self: True))
    v = validate_stock_order(tapped, ACCOUNT, [], envelope=None, mid=60.0, attribution=None)
    assert "les_paper_only" in v.reasons
    await cycle["run"]("on")  # stored "on" reads its default, record, in live
    assert get_switch("leveraged_entry") == "record"
    assert cycle["sent"] == []
    assert all("les_paper_only" in r[4] for r in _rows(db, "les_record"))


async def test_trend_break_sells_all_les_shares_next_session(cycle, db) -> None:
    cycle["held"] = 40.0
    cycle["signal"] = _signal(trend_up=False, pullback=False, trend_break=True, tier_pct=0.0)
    [action] = await cycle["run"]()
    assert (action.intent.side, action.intent.qty) == ("SELL", 40)
    assert [i.side for i in cycle["sent"]] == ["SELL"]
    before_ten = datetime(2026, 11, 16, 14, 30, tzinfo=UTC)  # 09:30 ET: not yet
    cycle["sent"].clear()
    assert await cycle["run"](now=before_ten) == []


async def test_a_sell_needs_no_envelope_pass(cycle) -> None:
    cycle["held"] = 25.0
    cycle["envelope"] = "refuse"  # would refuse any buy
    cycle["signal"] = _signal(trend_up=False, pullback=False, trend_break=True, tier_pct=0.0)
    [action] = await cycle["run"]()
    assert action.verdict.verdict == Verdict.PASS and action.result is not None
    assert action.result.status == "filled"


async def test_a_stale_or_missing_signal_sends_nothing(cycle) -> None:
    cycle["signal"] = None
    assert await cycle["run"]() == []
    cycle["signal"] = _signal(asof=TODAY - timedelta(days=9))
    assert await cycle["run"]() == []


async def test_partial_fill_and_unconfirmed_cancel_handled_like_task_31(db, monkeypatch) -> None:
    from src.execution.stock_orders import execute_stock_order
    from src.storage.models import OrderRow
    from tests.test_stock_orders import FakeIB

    def install(ib: FakeIB) -> None:
        from types import SimpleNamespace

        monkeypatch.setattr(
            "src.execution.stock_orders.req_fresh_mkt_data",
            lambda _ib, _c, *a, **k: SimpleNamespace(bid=ib.bid, ask=ib.ask),
        )

    async def ok(intent: StockOrderIntent, mid: float) -> RiskVerdict:
        return RiskVerdict(candidate_id="x", verdict=Verdict.PASS)

    buy = StockOrderIntent(side="BUY", symbol="TQQQ", qty=16, source="les")
    part = FakeIB(fill=6.0, done=True)
    install(part)
    res = await execute_stock_order(part, buy, gate=ok, timeout=0)
    assert res.status == "partial" and res.filled == 6
    hung = FakeIB(fill=0.0, done=False, cancel_confirms=False)
    install(hung)
    res2 = await execute_stock_order(hung, buy, gate=ok, timeout=0, cancel_confirm=0)
    assert res2.status == "working" and "cancel" in hung.calls
    with db() as s:
        rows = {r.id: (r.state, r.order_ref) for r in s.query(OrderRow)}
    assert rows[res.order_id] == ("partial", f"les:{res.order_id}")
    assert rows[res2.order_id] == ("submitted", f"les:{res2.order_id}")  # never marked cancelled
    assert les.order_working("TQQQ")  # so the cycle sends no second order on the name
