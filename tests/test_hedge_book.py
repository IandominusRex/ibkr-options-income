"""The hedge book: its own tables, its view, attribution and the reconciler skip (risk-envelope
Task 33; spec §3.10.9-§3.10.10 items 3, 7, 9, 10; ruling H9).

Every broker object here is a fake; nothing connects to IBKR."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from src.common.schemas import HedgeCandidate, HedgeLeg, ParsedExecution, ParsedStatement
from src.ledger.contracts import parse_option_symbol, stock_contract

EXP = date(2027, 2, 19)


def hedge_candidate(
    hedge_id: str = "h20261118-a",
    *,
    instrument: str = "QQQ",
    con_id: int = 9001,
    strike: float = 560.0,
    contracts: int = 2,
    debit: float = 6.0,
    short: tuple[float, int] | None = None,
    **kw,
) -> HedgeCandidate:
    legs = [HedgeLeg(action="BUY", strike=strike, expiry=EXP, con_id=con_id, bid=5.9, ask=6.1)]
    if short is not None:
        legs.append(
            HedgeLeg(action="SELL", strike=short[0], expiry=EXP, con_id=short[1], bid=1.0, ask=1.1)
        )
    return HedgeCandidate(
        hedge_id=hedge_id,
        order_ref=kw.pop("order_ref", f"hedge:{hedge_id}"),
        instrument=instrument,
        kind="vertical" if short else "outright",
        legs=legs,
        contracts=contracts,
        debit=debit,
        max_loss=debit * 100 * contracts,
        **kw,
    )


def seed_open_hedge(cand: HedgeCandidate | None = None, *, filled: int | None = None) -> str:
    """An opening order and its fill, written through the hedge package's own store."""
    from src.hedge import store

    cand = cand or hedge_candidate()
    oid = store.record_order(cand, limit_price=cand.debit)
    n = cand.contracts if filled is None else filled
    if n:
        store.record_fill(
            hedge_id=cand.hedge_id, qty=n, price=cand.debit, order_id=oid, exec_id="hx1"
        )
        store.update_order(oid, state="filled", filled_qty=n, avg_fill_price=cand.debit)
    return cand.hedge_id


# --------------------------------------------------------------------------- #
# Item 9: the reconciler never books a hedge buy as a manual close
# --------------------------------------------------------------------------- #


async def test_reconcile_external_closes_skips_hedge_refs(db) -> None:
    from src.execution.reconciliation import reconcile_external_closes
    from src.storage.models import CandidateRow, FillRow, OrderRow

    with db() as s:  # a wheel short on the very contract the hedge buys
        s.add(
            CandidateRow(
                candidate_id="csp-1",
                run_id="r",
                strategy="cash_secured_put",
                underlying="QQQ",
                right="P",
                strike=560.0,
                expiry=EXP,
                blended_score=70.0,
                payload={"contracts": 2},
            )
        )
        s.add(OrderRow(id=1, candidate_id="csp-1", approval_id=1, state="filled"))
        s.add(FillRow(order_id=1, candidate_id="csp-1", action="SELL", filled_qty=2, avg_price=7))

    def buy(exec_id: str, ref: str) -> SimpleNamespace:
        return SimpleNamespace(
            execution=SimpleNamespace(
                execId=exec_id, orderId=5, shares=2.0, price=6.0, side="BOT", orderRef=ref
            ),
            contract=SimpleNamespace(
                symbol="QQQ",
                right="P",
                strike=560.0,
                lastTradeDateOrContractMonth=EXP.strftime("%Y%m%d"),
                secType="OPT",
            ),
            commissionReport=SimpleNamespace(commission=1.3),
        )

    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(
        return_value=[buy("hx1", "hedge:h1"), buy("hx2", "hedge:claude:c1")]
    )
    bot = AsyncMock()
    await reconcile_external_closes(ib, bot, "1")
    with db() as s:
        assert s.query(FillRow).filter_by(candidate_id="csp-1", action="BUY").count() == 0
    bot.send_message.assert_not_awaited()

    # the same execution without a hedge ref is still a manual close (the skip is that narrow)
    ib.reqExecutionsAsync = AsyncMock(return_value=[buy("mx1", "")])
    await reconcile_external_closes(ib, bot, "1")
    with db() as s:
        assert s.query(FillRow).filter_by(candidate_id="csp-1", action="BUY").count() == 1


def test_orphan_fill_matching_refuses_a_hedge_execution() -> None:
    from src.execution.reconciliation import _exec_matches_candidate

    cand = SimpleNamespace(underlying="QQQ", right="P", strike=560.0, expiry=EXP)
    fill = SimpleNamespace(
        execution=SimpleNamespace(orderId=7, side="SLD", orderRef="hedge:h1"),
        contract=SimpleNamespace(
            symbol="QQQ",
            secType="OPT",
            right="P",
            strike=560.0,
            lastTradeDateOrContractMonth=EXP.strftime("%Y%m%d"),
        ),
    )
    assert _exec_matches_candidate(fill, cand, 7) is False  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Item 10: attribution
# --------------------------------------------------------------------------- #


def _item(symbol: str, con_id: int, *, strike: float = 560.0, position: float = 2.0):
    contract = SimpleNamespace(
        symbol=symbol,
        localSymbol=f"{symbol} 270219P{strike:g}",
        secType="OPT",
        right="P",
        strike=strike,
        lastTradeDateOrContractMonth=EXP.strftime("%Y%m%d"),
        conId=con_id,
    )
    return SimpleNamespace(
        contract=contract,
        position=position,
        averageCost=600.0,
        marketPrice=6.0,
        marketValue=1200.0,
        unrealizedPNL=0.0,
    )


def test_get_positions_drops_hedge_positions_by_default(hedge_db) -> None:
    from src.ibkr.portfolio import get_positions

    seed_open_hedge(hedge_candidate(con_id=9001))  # a QQQ hedge: dropped by conId
    ib = MagicMock()
    ib.portfolio.return_value = [
        _item("XND", 7001, strike=240.0),  # XND: the hedge book's by underlying
        _item("QQQ", 9001),  # the hedge's own contract
        _item("QQQ", 9002, strike=600.0, position=-1.0),  # a wheel QQQ short stays
        _item("AAPL", 3001, strike=200.0, position=-1.0),
    ]
    wheel = get_positions(ib)
    assert sorted((p.underlying, p.con_id) for p in wheel) == [("AAPL", 3001), ("QQQ", 9002)]
    truth = get_positions(ib, include_hedge=True)
    assert {p.con_id for p in truth} == {7001, 9001, 9002, 3001}


def _opt_exec(sym: str, qty: float, *, exec_id: str, ref: str | None, oid: int | None = None):
    contract = parse_option_symbol(sym, multiplier=100.0)
    return ParsedExecution(
        contract=contract,
        trade_time=datetime(2026, 11, 18, 15, 0, tzinfo=UTC),
        quantity=qty,
        price=6.0,
        proceeds=-qty * 600.0,
        exec_id=exec_id,
        account="U0000001",
        source_kind="exec",
        order_ref=ref,
        ib_order_id=oid,
        codes="O",
    )


def test_ledger_tags_book_hedge_by_ref_and_underlying(db) -> None:
    from src.common.books import is_hedge_order_ref, is_hedge_underlying
    from src.ledger.ingest import ingest
    from src.storage.models import BrokerExecutionRow, OrderRow

    with db() as s:  # a wheel order whose id collides with the hedge's (clientId 32 vs 14)
        s.add(
            OrderRow(
                candidate_id="opt-1",
                state="filled",
                ib_order_id=77,
                snapshot={"underlying": "QQQ"},
            )
        )
    ingest(
        ParsedStatement(
            account="U0000001",
            executions=[
                _opt_exec("QQQ 19FEB27 560 P", 2, exec_id="q1", ref="hedge:h1", oid=77),
                _opt_exec("XND 19FEB27 240 P", 1, exec_id="x1", ref=None),  # a CSV row: no ref
                _opt_exec("QQQ 19FEB27 600 P", -1, exec_id="w1", ref=None, oid=77),
            ],
        ),
        source="flex",
    )
    with db() as s:
        books = {r.exec_id: r.book for r in s.scalars(select(BrokerExecutionRow))}
    assert books == {"q1": "hedge", "x1": "hedge", "w1": "system"}
    assert is_hedge_order_ref("hedge:claude:c1") and is_hedge_order_ref("hedge:h1")
    assert not is_hedge_order_ref("value:1") and not is_hedge_order_ref(None)
    assert is_hedge_underlying("XND") and not is_hedge_underlying("QQQ")


def test_wheel_shares_ignore_hedge_rows(db) -> None:
    from src.ledger.ingest import ingest
    from src.storage.wheel_shares import wheel_shares

    def stock(qty: float, exec_id: str, ref: str | None) -> ParsedExecution:
        return ParsedExecution(
            contract=stock_contract("QQQ", "USD"),
            trade_time=datetime(2026, 11, 18, 15, 0, tzinfo=UTC),
            quantity=qty,
            price=600.0,
            proceeds=-qty * 600.0,
            exec_id=exec_id,
            account="U0000001",
            source_kind="exec",
            order_ref=ref,
        )

    # 100 wheel shares; 100 shares a QQQ hedge's exercise would deliver (hedge ref)
    ingest(
        ParsedStatement(
            account="U0000001",
            executions=[stock(100, "w1", None), stock(-100, "h1", "hedge:h1")],
        ),
        source="flex",
    )
    assert wheel_shares(["QQQ"])["QQQ"].shares == 100


def test_trade_ledger_pairs_a_long_open_and_close() -> None:
    """§3.10.10's [U]: the FIFO pairs a bought put and its sale into one closed "Buy" trade."""
    from src.ledger.contracts import et_date, parse_et_timestamp
    from src.reporting.trade_ledger import LedgerExec, build_option_trades, group_orders

    def ex(when: str, qty: float, price: float, codes: str, row: int) -> LedgerExec:
        contract = parse_option_symbol("QQQ 19FEB27 560 P", multiplier=100.0)
        ts = parse_et_timestamp(when)
        return LedgerExec(
            row_id=row,
            contract=contract,
            trade_time=ts,
            trade_date=et_date(ts),
            quantity=qty,
            price=price,
            proceeds=-qty * price * 100.0,
            commission=-1.3,
            codes=codes,
            perm_id=None,
            book="manual",
            ibkr_realized_pnl=None,
        )

    trades, orphans = build_option_trades(
        group_orders(
            [
                ex("2026-11-18, 10:30:00", 2, 6.00, "O", 1),
                ex("2027-01-15, 11:00:00", -2, 9.50, "C", 2),
            ]
        ),
        today=date(2027, 1, 20),
    )
    assert orphans == []
    (t,) = trades
    assert (t.side, t.right, t.lots, t.outcome) == ("Buy", "P", 2.0, "Sold")
    assert t.premium == pytest.approx(-1200.0)
    assert t.capital == pytest.approx(1200.0)  # a long's capital is what it cost
    assert t.net_pnl == pytest.approx(-1200.0 - 1.3 + 1900.0 - 1.3)


def test_trade_ledger_leaves_hedge_executions_to_the_hedge_report(db) -> None:
    from src.ledger.ingest import ingest
    from src.reporting.trade_ledger import load_execs

    ingest(
        ParsedStatement(
            account="U0000001",
            executions=[
                _opt_exec("XND 19FEB27 240 P", 1, exec_id="x1", ref="hedge:h1"),
                _opt_exec("QQQ 19FEB27 600 P", -1, exec_id="w1", ref=None),
            ],
        ),
        source="flex",
    )
    with db() as s:
        assert [e.contract.underlying for e in load_execs(s)] == ["QQQ"]


# --------------------------------------------------------------------------- #
# Config: XND is the hedge book's alone
# --------------------------------------------------------------------------- #


def _config(**overrides):
    from src.common.config import Config, get_config

    base = get_config()
    fields = {name: getattr(base, name) for name in Config.model_fields}
    fields.update(overrides)
    return Config(**fields)


def test_config_refuses_xnd_in_the_universe_or_spreads_book() -> None:
    from src.common.config import get_config

    base = get_config()
    universe = {**base.universe, "watchlist": [*(base.universe.get("watchlist") or []), "XND"]}
    with pytest.raises(ValidationError, match="hedge.underlyings"):
        _config(universe=universe)

    spreads = base.spreads.model_copy(
        update={"book_underlyings": [*base.spreads.book_underlyings, "XND"]}
    )
    with pytest.raises(ValidationError, match="hedge.underlyings"):
        _config(spreads=spreads)
    _config()  # the shipped example loads

    # QQQ, a universe name, is allowed (the QQQ-route rule keeps the books apart instead)
    assert "QQQ" in {s.upper() for v in base.universe.values() if isinstance(v, list) for s in v}
    assert "QQQ" in base.risk["hedge"]["underlyings"]


# --------------------------------------------------------------------------- #
# Item 7: own tables; the view is read-only
# --------------------------------------------------------------------------- #


def test_hedge_view_opens_read_only(hedge_db) -> None:
    from src.common import hedge_view

    hid = seed_open_hedge()
    (h,) = hedge_view.open_hedges() or []
    assert (h.hedge_id, h.instrument, h.contracts, h.cost) == (hid, "QQQ", 2.0, 1200.0)
    assert hedge_view.hedge_con_ids() == frozenset({9001})
    assert hedge_view.spend() == pytest.approx(1200.0)
    con = hedge_view.connect()
    assert con is not None
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        con.execute("DELETE FROM hedge_orders")
    con.close()


def test_hedge_view_on_a_missing_file_is_an_empty_book(monkeypatch, tmp_path) -> None:
    from src.common import hedge_view

    monkeypatch.setattr(hedge_view, "_path", lambda: tmp_path / "none.db")
    assert hedge_view.open_hedges() == []
    assert hedge_view.hedge_con_ids() == frozenset()
    assert hedge_view.pnl_today(date(2026, 11, 18)) == 0.0


def test_a_sale_closes_the_position(hedge_db) -> None:
    from src.common import hedge_view
    from src.hedge import store

    hid = seed_open_hedge()
    store.record_fill(hedge_id=hid, qty=-2, price=9.0)
    assert hedge_view.open_hedges() == []
    assert hedge_view.spend() == pytest.approx(1200.0 - 1800.0)


def test_the_wheels_orders_and_fills_never_hold_a_hedge_row(hedge_db) -> None:
    import src.storage.db as dbmod
    from src.storage.models import FillRow, HedgeFillRow, HedgeOrderRow, OrderRow

    seed_open_hedge()
    with dbmod.session_scope() as s:
        assert s.query(OrderRow).count() == 0 and s.query(FillRow).count() == 0
        assert s.query(HedgeOrderRow).count() == 1 and s.query(HedgeFillRow).count() == 1
        (o,) = s.query(HedgeOrderRow).all()
        assert o.order_ref == "hedge:h20261118-a" and o.legs[0]["con_id"] == 9001
