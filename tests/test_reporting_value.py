"""The value book on Home's money: the month's pay stub, the day's cards and the realised calendar
(value book Part 6, Task 14). Pure builders over plain `ValuePayInput` / `ValueDayInput` values;
the routes read them through src/api/value_db.py."""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from src.common.schemas import IncomeTarget, PnlLeg
from src.reporting.day import ValueDayInput, build_day_trades, build_month_calendar
from src.reporting.pay import ValuePayInput, build_month_pay
from src.value.store import ValueOrderRow, ValuePositionRow, ValueProposalRow, value_session
from tests.conftest import OWNER

OCT = date(2026, 10, 1)
TODAY = date(2026, 10, 13)
DAY = date(2026, 10, 9)


def leg(**over) -> PnlLeg:
    base = dict(
        candidate_id="c1",
        symbol="AAPL",
        underlying="AAPL",
        strategy="cash_secured_put",
        right="P",
        strike=180.0,
        expiry=date(2026, 11, 21),
        contracts=1,
        opened_at=datetime(2026, 10, 2, 15, 0),
        credit=235.0,
        debit=0.0,
        commissions=1.3,
        commissions_complete=True,
        days_held=0,
        outcome="still_open",
        is_live=False,
    )
    base.update(over)
    return PnlLeg(**base)


def value_close(**over) -> ValuePayInput:
    base = dict(
        closed_at=datetime(2026, 10, 9, 15, 0),
        symbol="GOOGL",
        realised_usd=120.0,
        commissions_usd=None,
    )
    base.update(over)
    return ValuePayInput(**base)


def pay(legs=(), values=(), **kw):
    args = dict(
        month=OCT, strategy="all", month_start_value=1000.0, target=IncomeTarget(), today=TODAY
    )
    args.update(kw)
    return build_month_pay(list(legs), [], list(values), **args)


def test_a_value_only_month_counts_only_value_lines() -> None:
    p = pay(
        [leg()],
        [value_close(), value_close(closed_at=datetime(2026, 9, 30, 15, 0))],
        strategy="value",
    )
    assert p.strategy == "value"
    assert (p.premium_collected, p.bought_back, p.n_opened) == (0.0, 0.0, 0)
    assert p.value_realised == pytest.approx(120.0)  # September's close is not October's
    assert p.value_n_closed == 1 and p.net == pytest.approx(120.0)
    assert p.progress_pct is None  # the income target is the wheel's wage (ruling 26)


def test_all_keeps_value_on_its_own_line_and_out_of_the_target() -> None:
    options_only = pay([leg()], target=IncomeTarget(mode="fixed", amount=500.0))
    both = pay([leg()], [value_close()], target=IncomeTarget(mode="fixed", amount=500.0))
    assert both.premium_collected == options_only.premium_collected == 235.0
    assert both.net == options_only.net  # value realised is not mixed into premium or net
    assert both.progress_pct == options_only.progress_pct
    assert both.value_realised == pytest.approx(120.0) and both.value_n_closed == 1
    assert options_only.value_realised is None and options_only.value_n_closed == 0
    assert both.value_commissions_complete is False  # value.db holds no commissions: unknown


def buy(**over) -> ValueDayInput:
    base = dict(
        at=datetime(2026, 10, 9, 14, 0),
        symbol="GOOGL",
        side="buy",
        shares=10.0,
        price=98.5,
        reason="tranche 1",
        cause="python",
        proposal_id=7,
        realised_usd=None,
    )
    base.update(over)
    return ValueDayInput(**base)


def test_a_value_buy_is_a_trade_card(api_db) -> None:
    trades = build_day_trades(api_db, [], [], [buy()], day=DAY, strategy="all")
    assert len(trades) == 1
    t = trades[0]
    assert t.key.startswith("value:7:buy:")
    assert (t.kind, t.source, t.action, t.underlying) == ("value", "value", "opened", "GOOGL")
    assert (t.contracts, t.strike, t.capital) == (10, 98.5, 985.0)
    assert t.reason is not None and "tranche 1" in t.reason
    assert [] == [f for f in t.facts if f.source == "claude"]
    # the wheel's and the spreads' scopes never show it
    assert build_day_trades(api_db, [], [], [buy()], day=DAY, strategy="csp") == []
    assert build_day_trades(api_db, [], [], [buy()], day=DAY, strategy="spread") == []


def test_a_claude_caused_sale_is_labelled_as_claudes(api_db) -> None:
    sale = buy(
        at=datetime(2026, 10, 9, 18, 0),
        side="sell",
        reason="claude_no",
        cause="claude",
        proposal_id=9,
        realised_usd=140.0,
        price=112.0,
    )
    (t,) = build_day_trades(api_db, [], [], [sale], day=DAY, strategy="value")
    assert (t.action, t.net_pnl) == ("closed", 140.0)
    assert t.reason is not None and "Claude" in t.reason
    claude_facts = [f for f in t.facts if f.source == "claude"]
    assert len(claude_facts) == 1 and "Claude" in claude_facts[0].text


def test_the_calendar_puts_a_value_sale_on_its_day() -> None:
    cal = build_month_calendar(
        [],
        [],
        [value_close(), value_close(realised_usd=-20.0, closed_at=datetime(2026, 10, 9, 16, 0))],
        month=OCT,
        strategy="value",
    )
    assert [(d.date, d.realized, d.n_closed) for d in cal.days] == [(DAY, 100.0, 2)]
    assert cal.total == 100.0 and cal.strategy == "value"
    # strategy "csp" leaves value out
    assert build_month_calendar([], [], [value_close()], month=OCT, strategy="csp").days == []


def _seed_value_sale() -> None:
    with value_session() as s:
        s.add(
            ValuePositionRow(
                symbol="GOOGL",
                list_name="deep_value",
                status="closed",
                opened_on=date(2026, 10, 1),
                closed_on=DAY,
                plan_json=json.dumps({}),
            )
        )
        s.add(
            ValueProposalRow(
                id=3,
                kind="sell",
                symbol="GOOGL",
                list_name="deep_value",
                shares=10,
                reason="claude_no",
                cause="claude",
                status="done",
                created_at=datetime(2026, 10, 9, 13, 0),
                expires_at=datetime(2026, 10, 10, 13, 0),
            )
        )
        s.add(
            ValueOrderRow(
                symbol="GOOGL",
                list_name="deep_value",
                side="buy",
                shares=10,
                filled=10,
                avg_price=100.0,
                status="filled",
                reason="tranche 1",
                created_at=datetime(2026, 10, 1, 14, 0),
                done_at=datetime(2026, 10, 1, 14, 1),
            )
        )
        s.add(
            ValueOrderRow(
                symbol="GOOGL",
                list_name="deep_value",
                side="sell",
                shares=10,
                filled=10,
                avg_price=112.0,
                status="filled",
                reason="claude_no",
                proposal_id=3,
                created_at=datetime(2026, 10, 9, 14, 0),
                done_at=datetime(2026, 10, 9, 14, 1),
            )
        )


@pytest.fixture()
def vdb(value_book_db, monkeypatch):
    import src.api.value_db as vdb

    monkeypatch.setattr(vdb, "_resolve_path", lambda: str(value_book_db))
    vdb.reset_engine()
    _seed_value_sale()
    yield
    vdb.reset_engine()


@pytest.fixture(autouse=True)
def _no_real_spreads_db(tmp_path, monkeypatch):
    import src.api.spreads_db as sdb

    monkeypatch.setattr(sdb, "_resolve_path", lambda: str(tmp_path / "no-spreads.db"))
    sdb.reset_engine()
    yield
    sdb.reset_engine()


@pytest.mark.parametrize("route", ["month", "day", "calendar"])
def test_strategy_value_reads_the_value_book_on_all_three_routes(client, vdb, route) -> None:
    query = {"month": "month=2026-10", "day": "date=2026-10-09", "calendar": "month=2026-10"}
    r = client.get(f"/pnl/{route}?strategy=value&{query[route]}", headers=OWNER)
    assert r.status_code == 200
    body = r.json()
    assert body["value_available"] is True and body["spreads_available"] is True
    if route == "month":
        assert body["pay"]["strategy"] == "value"
        assert body["pay"]["value_realised"] == pytest.approx(120.0)
    elif route == "day":
        kinds = sorted((t["action"], t["kind"]) for t in body["trades"])
        assert kinds == [("closed", "value")]
        assert body["trades"][0]["net_pnl"] == pytest.approx(120.0)
    else:
        assert body["calendar"]["total"] == pytest.approx(120.0)


def test_a_missing_value_db_is_not_available_and_never_zero(client) -> None:
    for route, q in (
        ("month", "month=2026-10"),
        ("day", "date=2026-10-09"),
        ("calendar", "month=2026-10"),
    ):
        body = client.get(f"/pnl/{route}?strategy=value&{q}", headers=OWNER).json()
        assert body["value_available"] is False
        assert body["spreads_available"] in (True, False)
    pay = client.get("/pnl/month?strategy=value&month=2026-10", headers=OWNER).json()["pay"]
    assert pay["value_realised"] is None
