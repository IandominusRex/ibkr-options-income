"""The bridge, run by Python for the glide only (risk-envelope Task 36; spec §3.10.2-§3.10.7,
§3.10.10 items 8 and 11; rulings H2-H6, H10, P9). Every broker object here is a fake."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.common import hedge_view
from src.common.envelope_types import BookLine, ShockInputs
from src.common.schemas import (
    AccountSnapshot,
    HedgeContext,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
)
from src.hedge import manager, sizing, store
from src.hedge.menu import HedgeMenuItem, HedgeQuote

# Wednesday 2026-11-18, 11:00 ET
NOW = datetime(2026, 11, 18, 16, 0, tzinfo=UTC)
TODAY = date(2026, 11, 18)
ACCOUNT = AccountSnapshot(
    account="DU1",
    net_liquidation=650_000.0,
    total_cash=400_000.0,
    buying_power=1_000_000.0,
    maintenance_margin=50_000.0,
    excess_liquidity=500_000.0,
)


def programme(**kw: Any) -> store.Programme:
    base = {
        "id": 1,
        "state": "on",
        "instrument": "QQQ",
        "started_on": TODAY - timedelta(days=10),
        "nlv0": 650_000.0,
        "glide_end": TODAY + timedelta(days=60),
        "ended_on": None,
        "zero_size_sessions": 0,
        "last_session": None,
        "review_posted_on": None,
    }
    base.update(kw)
    return store.Programme(**base)


def open_hedge(
    hid: str = "h1",
    *,
    instrument: str = "QQQ",
    expiry: date | None = None,
    contracts: float = 2.0,
    cost: float = 1200.0,
    working: bool = False,
    short: float | None = None,
) -> hedge_view.OpenHedge:
    exp = expiry or TODAY + timedelta(days=60)
    legs = [hedge_view.OpenLeg("BUY", "P", 560.0, exp, 9001)]
    if short is not None:
        legs.append(hedge_view.OpenLeg("SELL", "P", short, exp, 9002))
    return hedge_view.OpenHedge(
        hedge_id=hid,
        instrument=instrument,
        kind="vertical" if short else "outright",
        legs=tuple(legs),
        contracts=contracts,
        multiplier=100,
        cost=cost,
        opened_on=TODAY - timedelta(days=30),
        working=working,
    )


def position(h: hedge_view.OpenHedge | None = None, **kw: Any) -> manager.Position:
    h = h or open_hedge()
    expiry = h.expiry or TODAY
    base = {
        "hedge": h,
        "dte": (expiry - TODAY).days,
        "sessions_left": manager.sessions_until(TODAY, expiry),
        "mark": 6.0,
        "unit_cost": h.cost / (h.contracts * 100),
        "index": h.instrument == "XND",
    }
    base.update(kw)
    return manager.Position(**base)


def state(**kw: Any) -> manager.PlanState:
    base = {
        "today": TODAY,
        "programme": programme(),
        "bridge": "on",
        "monetise": False,
        "positions": (),
        "working": False,
        "t_minus": 2,
    }
    base.update(kw)
    return manager.PlanState(**base)


def kinds(acts: list[manager.Action]) -> list[tuple[str, str]]:
    return [(a.kind, a.reason) for a in acts]


# --------------------------------------------------------------------------- #
# Start, NLV0, size, default item
# --------------------------------------------------------------------------- #


class FakeIB:
    def __init__(self) -> None:
        self.disconnected = False
        self.exercised: list[tuple[Any, ...]] = []

    def disconnect(self) -> None:
        self.disconnected = True

    async def qualifyContractsAsync(self, *c: Any) -> list[Any]:
        return list(c)

    def exerciseOptions(self, *args: Any) -> None:
        self.exercised.append(args)


def _set(name: str, value: str) -> None:
    from src.storage.envelope_switches import set_switch

    set_switch(name, value, source="cli")


@pytest.fixture()
def bridge_env(hedge_db, monkeypatch):
    """A paper bridge with every broker read faked: the account at $650k, no position, nothing
    resolved, every action recorded instead of sent."""
    monkeypatch.setattr(
        "src.ibkr.portfolio.get_account_snapshot_async", AsyncMock(return_value=ACCOUNT)
    )
    monkeypatch.setattr(manager.executor, "resolve_working", AsyncMock(return_value=0))
    acted: list[manager.Action] = []

    async def act(action: manager.Action, sh: Any) -> str | None:
        acted.append(action)
        return None

    monkeypatch.setattr(manager, "_act", act)

    async def s10(self: Any) -> float:
        return 20.0

    monkeypatch.setattr(manager._Shared, "s10_gross", s10)
    monkeypatch.setattr(manager._Shared, "budget_left", lambda self: 1000.0)
    return acted


async def _cycle(now: datetime = NOW, **kw: Any) -> tuple[manager.HedgeCycle, list[str], FakeIB]:
    ib = FakeIB()
    said: list[str] = []

    async def notify(text: str) -> None:
        said.append(text)

    async def connect(cfg: Any) -> FakeIB:
        return ib

    out = await manager.run_hedge_cycle(now=now, notify=notify, connect=connect, **kw)
    return out, said, ib


async def test_the_bridge_starts_when_enforce_is_on_and_the_instrument_is_set(bridge_env) -> None:
    from src.storage.envelope_switches import get_switch

    out, _, _ = await _cycle()
    assert out.status == "idle" and store.load_programme() is None  # enforce reads record
    _set("envelope_enforce", "on")
    out, _, _ = await _cycle()
    assert out.status == "idle" and store.load_programme() is None  # no instrument yet
    _set("hedge_instrument", "QQQ")
    out, said, ib = await _cycle()
    prog = store.load_programme()
    assert out.status == "ran" and prog is not None and prog.instrument == "QQQ"
    assert get_switch("bridge") == "on" and "Bridge hedge started" in said[0]
    assert [a.kind for a in bridge_env] == ["buy"] and ib.disconnected


async def test_nlv0_is_fixed_on_day_one(bridge_env, monkeypatch) -> None:
    _set("envelope_enforce", "on")
    _set("hedge_instrument", "XND")
    await _cycle()
    richer = ACCOUNT.model_copy(update={"net_liquidation": 900_000.0})
    monkeypatch.setattr(
        "src.ibkr.portfolio.get_account_snapshot_async", AsyncMock(return_value=richer)
    )
    await _cycle(NOW + timedelta(days=1))
    prog = store.load_programme()
    assert prog is not None and prog.nlv0 == 650_000.0 and prog.started_on == TODAY
    again = store.start_programme(
        instrument="QQQ", started_on=TODAY + timedelta(days=2), nlv0=1.0, glide_end=None
    )
    assert (again.nlv0, again.instrument) == (650_000.0, "XND")


def _pick(s10_credit: float = 2_000.0, debit: float = 6.0) -> sizing.Pick:
    q = HedgeQuote(560.0, "P", TODAY + timedelta(days=90), 5.9, 6.1, delta=-0.22, iv=0.25)
    item = HedgeMenuItem("P560@x", "outright", q.expiry, 90, q, None, debit, 0.22, None)
    return sizing.Pick(item, {"S10": s10_credit, "S20": 4_000.0}, 0.3)


def test_size_is_min_of_budget_and_half_the_gap_to_fifteen() -> None:
    assert sizing.points_needed(22.0, 15.0) == pytest.approx(3.5)
    assert sizing.points_needed(14.0, 15.0) == 0.0
    args = {
        "nlv": 650_000.0,
        "per_contract_delta": -14_520.0,
        "book_delta": 2_000_000.0,
        "hedge_delta": 0.0,
        "max_delta_share": 0.5,
    }
    # need: 3.5% of 650k = 22,750 of S10 protection at 2,000 a contract -> 11 (rounded down)
    assert sizing.contracts_for(_pick(), points=3.5, budget_left=1e9, **args) == 11
    # the budget binds: 3,250 / 600 a contract -> 5
    assert sizing.contracts_for(_pick(), points=3.5, budget_left=3_250.0, **args) == 5
    assert sizing.contracts_for(_pick(), points=0.0, budget_left=1e9, **args) == 0
    # the delta cap binds: 0.5 x 100,000 / 14,520 -> 3
    capped = {**args, "book_delta": 100_000.0}
    assert sizing.contracts_for(_pick(), points=3.5, budget_left=1e9, **capped) == 3
    # no book delta: no size (fail closed)
    assert (
        sizing.contracts_for(_pick(), points=3.5, budget_left=1e9, **{**args, "book_delta": None})
        == 0
    )


def test_budget_room_is_the_least_of_the_three_caps() -> None:
    from src.common.config import get_hedge_cfg

    cfg = get_hedge_cfg()
    # month 0: net 6,500, pace 3,250, open 3,900
    assert sizing.budget_room(cfg, nlv0=650_000, spent=0, open_at_cost=0, months=0) == 3250.0
    assert sizing.budget_room(cfg, nlv0=650_000, spent=0, open_at_cost=3_000, months=6) == 900.0
    assert sizing.budget_room(cfg, nlv0=650_000, spent=7_000, open_at_cost=0, months=12) == 0.0


def _book() -> ShockInputs:
    return ShockInputs(
        lines=(BookLine("AAPL", "stock", 1_000.0, 200.0),),
        betas={"AAPL": 1.2, "QQQ": 1.1},
        betas_smh={"AAPL": 1.0, "QQQ": 1.0},
        leverage={},
        governing={},
        tech_linked=frozenset({"AAPL", "QQQ"}),
        semis=frozenset(),
        nlv=650_000.0,
    )


def _item(
    strike: float, debit: float, *, dte: int = 90, short: float | None = None
) -> HedgeMenuItem:
    exp = TODAY + timedelta(days=dte)
    long = HedgeQuote(strike, "P", exp, debit - 0.1, debit + 0.1, delta=-0.2, iv=0.25)
    sq = HedgeQuote(short, "P", exp, 0.5, 0.6, delta=-0.05, iv=0.30) if short else None
    d = debit - (0.55 if sq else 0.0)
    return HedgeMenuItem(
        f"P{strike:g}", "vertical" if sq else "outright", exp, dte, long, sq, d, 0.2, None
    )


def test_default_item_maximises_minimum_protection_per_dollar() -> None:
    items = [
        _item(570.0, 9.0),
        _item(550.0, 5.0),
        _item(530.0, 2.8),
        _item(560.0, 7.0, short=500.0),
    ]
    pick = sizing.default_item(items, "QQQ", 600.0, _book(), today=TODAY)
    assert pick is not None
    best = max(
        items,
        key=lambda it: (
            min(sizing.credits(it, "QQQ", 600.0, _book(), today=TODAY).values()) / (it.debit * 100)
        ),
    )
    assert pick.item.item_key == best.item_key
    assert set(pick.credits) == {"S10", "S20", "T20", "G10", "P20"}
    # full revaluation: a deeper fall pays more, and every scenario is a gain for a put
    assert pick.credits["S20"] > pick.credits["S10"] > 0
    # XND borrows QQQ's beta and is tech-linked like it
    assert sizing.credits(items[0], "XND", 600.0, _book(), today=TODAY) is not None


# --------------------------------------------------------------------------- #
# The schedule: rolls, the stress block, T-2, settlement, monetisation, end, review
# --------------------------------------------------------------------------- #


def test_roll_at_30_dte_sells_old_buys_new_in_the_plan() -> None:
    at_30 = position(open_hedge(expiry=TODAY + timedelta(days=30)))
    assert kinds(manager.plan(state(positions=(at_30,)))) == [("roll", "roll_date")]
    at_31 = position(open_hedge(expiry=TODAY + timedelta(days=31)))
    assert manager.plan(state(positions=(at_31,))) == []
    # no position: buy on the schedule; one position at a time
    assert kinds(manager.plan(state())) == [("buy", "schedule")]
    assert manager.plan(state(working=True)) == []


class _Sh:
    """The shared cycle state, faked: a context, a pick and the sends recorded."""

    def __init__(self, ctx: HedgeContext, pick: tuple[sizing.Pick, float, int] | None) -> None:
        self.ctx, self.picked = ctx, pick
        self.today = TODAY
        self.programme = programme()
        self.instrument = "QQQ"
        self.hcfg = __import__("src.common.config", fromlist=["x"]).get_hedge_cfg()
        self.ib = FakeIB()
        self.cfg = SimpleNamespace(secrets=SimpleNamespace(ibkr_account="DU1"))

    async def context(self) -> HedgeContext:
        return self.ctx


def _ctx(**kw: Any) -> HedgeContext:
    base = {
        "now": NOW,
        "nlv0": 650_000.0,
        "vix_close": 18.0,
        "vxn_close": 22.0,  # review fix 1: an unmeasured VXN percentile now blocks, so a calm
        "vxn_p90": 30.0,  # fixture names it
        "held_contracts": {"h1": 2.0},
    }
    base.update(kw)
    return HedgeContext(**base)


@pytest.fixture()
def sends(monkeypatch):
    """Record every order the manager would send; each fills in full at its debit's size."""
    from src.hedge.executor import HedgeOrderResult

    sent: list[Any] = []

    async def send(cand: Any, sh: Any) -> HedgeOrderResult:
        sent.append(cand)
        return HedgeOrderResult(
            "filled", cand, filled=float(cand.contracts), avg_price=getattr(sh, "fill_price", 7.0)
        )

    async def quote(ib: Any, cand: Any, **kw: Any) -> Any:
        from src.common.schemas import HedgeLeg

        legs = [
            HedgeLeg(**{**leg.model_dump(), "bid": 6.9, "ask": 7.1, "quoted_at": NOW})
            for leg in cand.legs
        ]
        return cand.model_copy(update={"legs": legs})

    monkeypatch.setattr(manager, "_send", send)
    monkeypatch.setattr(manager.executor, "quote_candidate", quote)
    return sent


def _with_pick(monkeypatch, sh: _Sh) -> None:
    async def pick(_sh: Any) -> Any:
        return sh.picked

    monkeypatch.setattr(manager, "_pick", pick)


async def test_roll_sells_old_then_buys_new(monkeypatch, sends) -> None:
    sh = _Sh(_ctx(), (_pick(debit=6.0), 600.0, 3))
    _with_pick(monkeypatch, sh)
    await manager._roll(open_hedge(expiry=TODAY + timedelta(days=29)), sh)  # type: ignore[arg-type]
    sale, buy = sends
    assert (sale.intent, sale.closes, sale.contracts) == ("close", "h1", 2)
    assert (buy.intent, buy.roll_of, buy.contracts) == ("open", "h1", 3)
    assert buy.roll_proceeds == pytest.approx(7.0 * 100 * 2)


async def test_the_stress_block_allows_only_a_self_funding_roll(monkeypatch, sends) -> None:
    # VIX 30: the new item costs 2 x 9.00 x 100 = 1,800 against a sale at the 6.90 bid = 1,380
    dear = _Sh(_ctx(vix_close=30.0), (_pick(debit=9.0), 600.0, 2))
    _with_pick(monkeypatch, dear)
    text = await manager._roll(open_hedge(expiry=TODAY + timedelta(days=29)), dear)  # type: ignore[arg-type]
    assert sends == [] and "held under the stress block" in text
    # cheap enough to fund itself: sold, and bought back at no more contracts than held
    cheap = _Sh(_ctx(vix_close=30.0), (_pick(debit=5.0), 600.0, 5))
    _with_pick(monkeypatch, cheap)
    await manager._roll(open_hedge(expiry=TODAY + timedelta(days=29)), cheap)  # type: ignore[arg-type]
    sale, buy = sends
    assert sale.intent == "close" and buy.contracts == 2 and buy.roll_contracts == 2
    assert buy.self_funding_roll


async def test_a_missing_vxn_percentile_blocks_a_roll_like_the_gate_does(
    monkeypatch, sends
) -> None:
    # Review fix 1: the bridge's own pre-check agrees with validate_hedge (hedge_stress_unmeasured)
    dear = _Sh(_ctx(vxn_p90=None), (_pick(debit=9.0), 600.0, 2))
    _with_pick(monkeypatch, dear)
    text = await manager._roll(open_hedge(expiry=TODAY + timedelta(days=29)), dear)  # type: ignore[arg-type]
    assert sends == [] and "held under the stress block" in text
    cheap = _Sh(_ctx(vxn_close=None), (_pick(debit=5.0), 600.0, 5))
    _with_pick(monkeypatch, cheap)
    await manager._roll(open_hedge(expiry=TODAY + timedelta(days=29)), cheap)  # type: ignore[arg-type]
    sale, buy = sends  # self-funding: still allowed, at no more contracts than held
    assert sale.intent == "close" and buy.contracts == 2 and buy.self_funding_roll


async def test_qqq_route_closes_by_t_minus_2_and_sends_a_lapse_instruction(
    hedge_db, monkeypatch
) -> None:
    friday = date(2026, 11, 20)  # Wednesday -> Thursday, Friday: two sessions left
    h = open_hedge(expiry=friday)
    p = position(h)
    assert p.sessions_left == 2
    assert kinds(manager.plan(state(positions=(p,)))) == [("close", "t_minus_close")]
    # XND never has a T-2 rule (cash-settled, European)
    x = position(open_hedge(instrument="XND", expiry=friday), index=True)
    assert ("close", "t_minus_close") not in kinds(manager.plan(state(positions=(x,))))

    from src.hedge.executor import HedgeOrderResult

    async def send(cand: Any, sh: Any) -> HedgeOrderResult:
        return HedgeOrderResult("cancelled", cand, reasons=[])

    monkeypatch.setattr(manager, "_send", send)
    sh = _Sh(_ctx(), None)
    text = await manager._close(h, sh, "t_minus_close")  # type: ignore[arg-type]
    ((contract, action, qty, account, override),) = sh.ib.exercised
    assert (contract.strike, contract.right, action, qty, account, override) == (
        560.0,
        "P",
        2,
        2,
        "DU1",
        1,
    )
    assert "Lapse instruction sent" in text


async def test_xnd_cash_settlement_is_booked(hedge_db) -> None:
    from src.common.schemas import HedgeCandidate, HedgeLeg

    exp = TODAY - timedelta(days=1)
    cand = HedgeCandidate(
        hedge_id="x1",
        order_ref="hedge:x1",
        instrument="XND",
        legs=[HedgeLeg(action="BUY", strike=240.0, expiry=exp, con_id=7001)],
        contracts=2,
        debit=3.0,
        max_loss=600.0,
    )
    oid = store.record_order(cand, limit_price=3.0)
    store.record_fill(hedge_id="x1", qty=2, price=3.0, order_id=oid)
    store.update_order(oid, state="filled", filled_qty=2)
    store.record_capture(
        [
            store.QuoteRecord(
                captured_at=datetime(2026, 11, 17, 19, 30, tzinfo=UTC),
                session_date=exp,
                instrument="XND",
                item_key="P240",
                leg="long",
                is_default=True,
                con_id=7001,
                strike=240.0,
                right="P",
                expiry=exp,
                spot=232.0,
                bid=7.9,
                ask=8.1,
                bid_size=5,
                ask_size=5,
                mid=8.0,
                delta=-0.9,
            )
        ]
    )
    (h,) = hedge_view.open_hedges() or []
    p = position(h, index=True)
    assert kinds(manager.plan(state(positions=(p,)))) == [("settle", "expired")]
    text = manager._settle(h, TODAY)
    assert "settled in cash at 232.00" in text
    assert hedge_view.open_hedges() == []
    assert hedge_view.spend() == pytest.approx(600.0 - 8.0 * 100 * 2)  # paid 600, received 1,600


def test_monetisation_applies_only_when_switched() -> None:
    rich = position(mark=12.5, unit_cost=6.0)  # 2.08x its cost
    assert manager.plan(state(positions=(rich,))) == []
    assert kinds(manager.plan(state(positions=(rich,), monetise=True))) == [("close", "monetise")]
    assert manager.plan(state(positions=(position(mark=11.0, unit_cost=6.0),), monetise=True)) == []


def test_the_bridge_ends_at_the_glide_end() -> None:
    ended = programme(glide_end=TODAY)
    acts = manager.plan(state(programme=ended))
    assert [a.kind for a in acts] == ["end", "review"]  # no buy
    at_roll = position(open_hedge(expiry=TODAY + timedelta(days=25)))
    acts = manager.plan(state(programme=ended, positions=(at_roll,)))
    assert kinds(acts)[:2] == [("end", "glide_end"), ("close", "roll_date_after_end")]
    # after the end nothing is bought or rolled; a position not yet at its roll date is held
    after = programme(state="ended", review_posted_on=TODAY)
    held = position(open_hedge(expiry=TODAY + timedelta(days=50)))
    assert manager.plan(state(programme=after, positions=(held,), bridge="ended")) == []


async def test_the_cycle_records_the_end(bridge_env) -> None:
    from src.storage.envelope_switches import get_switch

    store.start_programme(instrument="QQQ", started_on=TODAY, nlv0=650_000.0, glide_end=TODAY)
    _set("bridge", "on")
    await _cycle()
    prog = store.load_programme()
    assert prog is not None and prog.state == "ended" and prog.ended_on == TODAY
    assert get_switch("bridge") == "ended"
    assert [a.kind for a in bridge_env] == ["end", "review"]


def test_zero_size_for_20_sessions_posts_the_review_record(hedge_db) -> None:
    prog = store.start_programme(
        instrument="QQQ", started_on=TODAY, nlv0=650_000.0, glide_end=TODAY + timedelta(days=90)
    )
    day = TODAY
    for _ in range(20):
        manager.update_zero_sessions(prog, today=day, s10_gross=14.0, budget=1000.0)
        prog = store.load_programme() or prog
        day += timedelta(days=1)
    assert prog.zero_size_sessions == 20 and manager.review_due(prog)
    assert ("review", "") in kinds(manager.plan(state(programme=prog, working=True)))
    # a session with size resets the count
    manager.update_zero_sessions(prog, today=day, s10_gross=22.0, budget=1000.0)
    assert (store.load_programme() or prog).zero_size_sessions == 0

    from src.reporting.hedge import review_record

    text = review_record(today=day)
    assert "default: off" in text.lower()


async def test_the_review_is_posted_once(hedge_db) -> None:
    store.start_programme(instrument="QQQ", started_on=TODAY, nlv0=650_000.0, glide_end=None)
    prog = store.load_programme()
    assert prog is not None
    sh = _Sh(_ctx(), None)
    sh.programme = prog
    text = await manager._review(sh)  # type: ignore[arg-type]
    assert "default: off" in text.lower()
    assert not manager.review_due(store.load_programme())


# --------------------------------------------------------------------------- #
# Marks, breakers, capital, live, the monitors
# --------------------------------------------------------------------------- #


def test_hedge_marks_enter_the_daily_leg_net(hedge_db, monkeypatch) -> None:
    from src.execution import circuit_breakers as cb
    from tests.test_hedge_book import hedge_candidate, seed_open_hedge

    hid = seed_open_hedge(hedge_candidate(contracts=2, debit=6.0))
    store.record_mark(
        session_date=TODAY - timedelta(days=1),
        hedge_id=hid,
        contracts=2,
        mark=6.0,
        source="captured",
        marked_at=NOW - timedelta(days=1),
    )
    # move the opening fill to yesterday so today's leg is the mark change alone
    import src.storage.db as dbmod
    from src.storage.models import HedgeFillRow

    with dbmod.session_scope() as s:
        s.query(HedgeFillRow).update({"filled_at": (NOW - timedelta(days=1)).replace(tzinfo=None)})
    store.record_mark(
        session_date=TODAY, hedge_id=hid, contracts=2, mark=10.0, source="captured", marked_at=NOW
    )
    assert hedge_view.pnl_today(TODAY) == pytest.approx(800.0)  # (10 - 6) x 100 x 2

    monkeypatch.setattr(cb, "today_et", lambda: TODAY)
    monkeypatch.setattr(cb, "_mark_delta", lambda positions: -10_000.0)
    monkeypatch.setattr(cb, "spreads_pnl_today", lambda day: 0.0)
    delta, wheel, spreads, hedge = cb._daily_pnl_by_book([])
    assert (wheel, hedge) == (-10_000.0, 800.0)
    assert delta == pytest.approx(-9_200.0)  # net: the hedge's gain counts against the loss
    monkeypatch.setattr(cb, "get_breaker_ack", lambda *a, **k: None)
    monkeypatch.setattr(cb, "_drawdown_raw", lambda nlv: None)
    monkeypatch.setattr(cb.get_config().automation, "daily_loss_halt_pct", 1.0)
    reason = cb.evaluate_breakers([], 650_000.0)
    assert reason == "Daily mark-to-market loss $9,200 (wheel -$10,000, spreads $0, hedge $800)"


def test_capital_counts_no_hedge_collateral() -> None:
    from src.engine.capital import seed_budgets

    long_put = PositionSnapshot(
        symbol="QQQ 270219P00560000",
        sec_type="OPT",
        position=2,
        avg_cost=600.0,
        right=OptionRight.PUT,
        strike=560.0,
        expiry=date(2027, 2, 19),
        underlying="QQQ",
    )
    b = seed_budgets([long_put], lambda s: "index")
    assert b.csp_collateral == 0.0 and b.ticker_collateral.get("QQQ", 0.0) == 0.0
    assert b.cash_used == 0.0  # the debit is already out of cash: the account shows it


async def test_the_manager_idles_in_live(bridge_env, monkeypatch) -> None:
    from src.common.config import get_config

    _set("envelope_enforce", "on")
    _set("hedge_instrument", "QQQ")
    monkeypatch.setattr(type(get_config()), "is_live", property(lambda self: True))
    connect = AsyncMock()
    out = await manager.run_hedge_cycle(now=NOW, connect=connect, notify=AsyncMock())
    assert out.status == "live" and connect.await_count == 0
    assert store.load_programme() is None


def test_every_existing_monitor_still_skips_long_options() -> None:
    from src.common.config import RollCfg
    from src.monitor import triggers
    from src.strategies.roll_policy import roll_trigger

    exp = TODAY + timedelta(days=5)
    long_put = PositionSnapshot(
        symbol="QQQ P560",
        sec_type="OPT",
        position=2,
        avg_cost=600.0,
        right=OptionRight.PUT,
        strike=560.0,
        expiry=exp,
        underlying="QQQ",
    )
    q = OptionQuote(
        underlying="QQQ",
        right=OptionRight.PUT,
        strike=560.0,
        expiry=exp,
        bid=40,
        ask=41,
        delta=-0.95,
        iv=0.9,
    )
    assert triggers.check_delta_drift(long_put, q, 0.3) is None
    assert triggers.check_dte_threshold(long_put, 7) is None
    assert triggers.check_manage_at_dte(long_put, 21) is None
    assert triggers.check_strike_breach(long_put, q) is None
    assert triggers.check_iv_spike(long_put, q, 0.2, 10.0) is None
    assert triggers.check_assignment_risk(long_put, q, 0.8, 7) is None
    assert triggers.check_loss_multiple(long_put, q, 1.0, 2.0) is None
    assert roll_trigger(long_put, q, None, RollCfg(), ex_div_guard=False, today=TODAY) is None


def test_the_hedge_book_creates_no_headroom() -> None:
    """H1, H10: a hedge vertical (its short leg too) is outside S10_gross and U_ew."""
    from src.analytics.shock import measure

    base = _book()
    exp_dte = 60
    hedge = (
        BookLine("QQQ", "long_put", 5, 600.0, 560.0, exp_dte, 0.25, book="hedge"),
        BookLine("QQQ", "short_put", 5, 600.0, 500.0, exp_dte, 0.30, book="hedge"),
    )
    without = measure(base)
    with_hedge = measure(replace(base, lines=base.lines + hedge))
    assert with_hedge.s10 == pytest.approx(without.s10)
    assert with_hedge.uew == pytest.approx(without.uew)
    assert with_hedge.s10_net < without.s10_net  # net (display) sees the protection
