"""Buy-to-close fills must never be lost or mis-attributed (2026-10-02 TQQQ 74P incident).

The profit-take close for TQQQ 74P was placed, then the Gateway dropped mid-reprice; the
except path marked the order REJECTED even though IBKR held it, IBKR filled it 8s later, and
no reconciliation pass could see it: ``reconcile_orphan_fills`` only recovered SELL entries
with a CandidateRow, and ``reconcile_external_closes`` skips the system's own order ids.
Separately, every profit-take close recorded its BUY fill under the synthetic ``close:`` id,
so the verdict-ledger reconciler and ``/pnl/system`` never saw the debit.

All IB calls are mocked; the DB uses tmp_path SQLite.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.common.schemas import OptionRight, OrderState, PositionSnapshot
from src.storage.models import CandidateRow, FillRow, OrderRow

_EXPIRY = date.today() + timedelta(days=30)
_CLOSE_ID = f"close:TQQQ:{_EXPIRY:%Y%m%d}:74:P"


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _cfg(monkeypatch, module) -> MagicMock:
    cfg = MagicMock()
    cfg.is_live = False
    cfg.execution.fill_timeout_minutes = 5.0
    cfg.execution.reprice_enabled = False
    monkeypatch.setattr(module, "get_config", lambda: cfg)
    return cfg


def _pos() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="TQQQ  261009P00074000",
        sec_type="OPT",
        position=-10.0,
        avg_cost=104.0,
        right=OptionRight.PUT,
        strike=74.0,
        expiry=_EXPIRY,
        underlying="TQQQ",
    )


def _seed_entry(s, candidate_id: str = "entry-tqqq") -> None:
    """The system's own short: a candidate plus its SELL fill on the same contract."""
    s.add(
        CandidateRow(
            candidate_id=candidate_id,
            run_id="r",
            strategy="cash_secured_put",
            underlying="TQQQ",
            right="P",
            strike=74.0,
            expiry=_EXPIRY,
            blended_score=60.0,
            payload={"contracts": 10},
        )
    )
    s.add(OrderRow(id=1, candidate_id=candidate_id, approval_id=1, state="filled", ib_order_id=68))
    s.add(
        FillRow(
            order_id=1,
            candidate_id=candidate_id,
            action="SELL",
            filled_qty=10.0,
            avg_price=1.04,
            ib_exec_id="sell-1",
        )
    )


def _close_ib(*, filled: bool) -> MagicMock:
    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(return_value=[MagicMock(conId=1)])
    trade = MagicMock()
    trade.isDone.return_value = filled
    trade.order.orderId = 136
    trade.orderStatus.filled = 10.0 if filled else 0.0
    trade.orderStatus.avgFillPrice = 0.49 if filled else 0.0
    fill = MagicMock()
    fill.execution.execId = "buy-1"
    fill.commissionReport.commission = 3.40
    trade.fills = [fill] if filled else []
    ib.placeOrder.return_value = trade
    return ib


def _buy_exec(*, order_id: int = 136, strike: float = 74.0, exec_id: str = "buy-1"):
    return SimpleNamespace(
        execution=SimpleNamespace(
            orderId=order_id,
            shares=10.0,
            price=0.49,
            side="BOT",
            execId=exec_id,
            time=datetime.now(UTC),
        ),
        contract=SimpleNamespace(
            symbol="TQQQ",
            secType="OPT",
            right="P",
            strike=strike,
            lastTradeDateOrContractMonth=f"{_EXPIRY:%Y%m%d}",
        ),
        commissionReport=SimpleNamespace(commission=3.395293),
    )


# --- close_short_position ---------------------------------------------------------------


async def test_close_fill_is_attributed_to_the_entry_candidate(tmp_path, monkeypatch):
    """The BUY fill lands on the short it closes, so the verdict ledger and /pnl/system see
    the debit. The OrderRow keeps the synthetic id — it is the idempotency key."""
    _db_setup(tmp_path, monkeypatch)
    import src.execution.position_manager as pm
    import src.storage.db as dbmod

    _cfg(monkeypatch, pm)
    monkeypatch.setattr(pm.asyncio, "sleep", AsyncMock())
    with dbmod.session_scope() as s:
        _seed_entry(s)

    result = await pm.close_short_position(_close_ib(filled=True), _pos(), bid=0.48, ask=0.52)

    assert result.status == "filled"
    with dbmod.session_scope() as s:
        buy = s.query(FillRow).filter_by(action="BUY").one()
        order = s.query(OrderRow).filter_by(candidate_id=_CLOSE_ID).one()
        assert buy.candidate_id == "entry-tqqq"
        assert buy.order_id == order.id


async def test_close_fill_without_a_system_entry_keeps_the_synthetic_id(tmp_path, monkeypatch):
    """A short the system never sold (opened by hand) has no candidate to attribute to."""
    _db_setup(tmp_path, monkeypatch)
    import src.execution.position_manager as pm
    import src.storage.db as dbmod

    _cfg(monkeypatch, pm)
    monkeypatch.setattr(pm.asyncio, "sleep", AsyncMock())

    await pm.close_short_position(_close_ib(filled=True), _pos(), bid=0.48, ask=0.52)

    with dbmod.session_scope() as s:
        assert s.query(FillRow).filter_by(action="BUY").one().candidate_id == _CLOSE_ID


async def test_exception_after_placement_keeps_the_order_active(tmp_path, monkeypatch):
    """A connection drop after placeOrder must not mark the order REJECTED: IBKR still holds
    it. It stays SUBMITTED (so the next cycle can't stack a second buy-to-close that could
    leave the account net long) for reconciliation to resolve."""
    _db_setup(tmp_path, monkeypatch)
    import src.execution.position_manager as pm
    import src.storage.db as dbmod

    cfg = _cfg(monkeypatch, pm)
    cfg.execution.reprice_enabled = True
    cfg.execution.reprice_interval_seconds = 0.0
    cfg.execution.max_reprices = 2
    monkeypatch.setattr(pm.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(
        pm, "_refetch_bid_ask", AsyncMock(side_effect=ConnectionError("Not connected"))
    )

    result = await pm.close_short_position(_close_ib(filled=False), _pos(), bid=0.48, ask=0.52)

    assert result.status == "error"
    with dbmod.session_scope() as s:
        order = s.query(OrderRow).filter_by(candidate_id=_CLOSE_ID).one()
        assert order.state == OrderState.SUBMITTED
        assert order.ib_order_id == 136
        assert "reconcil" in (order.detail or "")

    again = await pm.close_short_position(_close_ib(filled=True), _pos(), bid=0.48, ask=0.52)
    assert again.status == "skipped"


async def test_exception_before_placement_still_rejects(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.execution.position_manager as pm
    import src.storage.db as dbmod

    _cfg(monkeypatch, pm)
    ib = MagicMock()
    ib.qualifyContractsAsync = AsyncMock(side_effect=ConnectionError("Not connected"))

    result = await pm.close_short_position(ib, _pos(), bid=0.48, ask=0.52)

    assert result.status == "error"
    with dbmod.session_scope() as s:
        assert s.query(OrderRow).one().state == OrderState.REJECTED


# --- reconcile_orphan_fills --------------------------------------------------------------


def _recon_setup(tmp_path, monkeypatch, *, state: str, created_at: datetime | None = None):
    _db_setup(tmp_path, monkeypatch)
    import src.execution.reconciliation as rec
    import src.storage.db as dbmod

    _cfg(monkeypatch, rec)
    with dbmod.session_scope() as s:
        _seed_entry(s)
        s.add(
            OrderRow(
                id=23,
                candidate_id=_CLOSE_ID,
                state=state,
                ib_order_id=136,
                limit_price=0.51,
                created_at=created_at or datetime.now(UTC) - timedelta(minutes=2),
            )
        )
    return rec, dbmod


async def test_reconcile_recovers_a_lost_close_fill(tmp_path, monkeypatch):
    rec, dbmod = _recon_setup(tmp_path, monkeypatch, state="submitted")
    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[_buy_exec()])
    bot = AsyncMock()

    await rec.reconcile_orphan_fills(ib, bot, "99999")

    with dbmod.session_scope() as s:
        order = s.get(OrderRow, 23)
        buys = s.query(FillRow).filter_by(action="BUY").all()
        assert order.state == OrderState.FILLED
        assert order.filled_qty == 10.0
        assert abs(order.avg_fill_price - 0.49) < 1e-9
        assert len(buys) == 1
        assert buys[0].candidate_id == "entry-tqqq"  # attributed to the short it closed
        assert buys[0].order_id == 23
        assert buys[0].ib_exec_id == "buy-1"
        assert abs((buys[0].commission or 0) - 3.395293) < 1e-9
    bot.send_message.assert_awaited()


async def test_reconcile_recovers_a_close_marked_rejected_by_the_old_code(tmp_path, monkeypatch):
    """Rows written before this fix say REJECTED; they carry an ib_order_id and are recovered."""
    rec, dbmod = _recon_setup(tmp_path, monkeypatch, state="rejected")
    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[_buy_exec()])

    await rec.reconcile_orphan_fills(ib, AsyncMock(), "99999")

    with dbmod.session_scope() as s:
        assert s.get(OrderRow, 23).state == OrderState.FILLED


async def test_reconcile_ignores_a_reused_order_id_on_another_contract(tmp_path, monkeypatch):
    """IBKR order ids restart after a Gateway restart (orders 32 and 33 both carry 188), so an
    order id alone is not proof — the contract must match too."""
    rec, dbmod = _recon_setup(tmp_path, monkeypatch, state="submitted")
    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[_buy_exec(strike=77.0)])

    await rec.reconcile_orphan_fills(ib, AsyncMock(), "99999")

    with dbmod.session_scope() as s:
        assert s.get(OrderRow, 23).state == OrderState.SUBMITTED
        assert s.query(FillRow).filter_by(action="BUY").count() == 0


async def test_reconcile_expires_a_close_left_working_on_an_earlier_day(tmp_path, monkeypatch):
    """Closes are DAY orders: one still SUBMITTED from a previous ET day with no execution is
    over, so it must stop blocking the next close of the same position."""
    rec, dbmod = _recon_setup(
        tmp_path,
        monkeypatch,
        state="submitted",
        created_at=datetime.now(UTC) - timedelta(days=2),
    )
    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[])

    await rec.reconcile_orphan_fills(ib, AsyncMock(), "99999")

    with dbmod.session_scope() as s:
        assert s.get(OrderRow, 23).state == OrderState.CANCELLED


async def test_reconcile_leaves_todays_working_close_alone(tmp_path, monkeypatch):
    rec, dbmod = _recon_setup(tmp_path, monkeypatch, state="submitted")
    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(return_value=[])

    await rec.reconcile_orphan_fills(ib, AsyncMock(), "99999")

    with dbmod.session_scope() as s:
        assert s.get(OrderRow, 23).state == OrderState.SUBMITTED


# --- a filled close must not block closing a later re-sale of the same contract ----------


async def test_a_new_sale_of_the_same_contract_can_be_closed_again(tmp_path, monkeypatch):
    """The close id is per contract and FILLED counts as active (it stops a stale snapshot
    from stacking a second close), so without a reset a contract sold, closed, and sold
    again could never be auto-closed again: profit-takes and loss exits would silently skip."""
    _db_setup(tmp_path, monkeypatch)
    import src.execution.position_manager as pm
    import src.storage.db as dbmod

    _cfg(monkeypatch, pm)
    monkeypatch.setattr(pm.asyncio, "sleep", AsyncMock())
    with dbmod.session_scope() as s:
        _seed_entry(s)
    first = await pm.close_short_position(_close_ib(filled=True), _pos(), bid=0.48, ask=0.52)
    assert first.status == "filled"

    # Same contract right after the close fills: still blocked (stale-snapshot guard).
    stale = await pm.close_short_position(_close_ib(filled=True), _pos(), bid=0.48, ask=0.52)
    assert stale.status == "skipped"

    # The system sells the same contract again later.
    with dbmod.session_scope() as s:
        s.add(
            CandidateRow(
                candidate_id="entry-tqqq-2",
                run_id="r2",
                strategy="cash_secured_put",
                underlying="TQQQ",
                right="P",
                strike=74.0,
                expiry=_EXPIRY,
                blended_score=60.0,
                payload={"contracts": 10},
            )
        )
        s.add(OrderRow(id=50, candidate_id="entry-tqqq-2", approval_id=2, state="filled"))
        s.add(
            FillRow(
                order_id=50,
                candidate_id="entry-tqqq-2",
                action="SELL",
                filled_qty=10.0,
                avg_price=1.20,
                filled_at=datetime.now(UTC) + timedelta(seconds=5),
            )
        )

    again = await pm.close_short_position(_close_ib(filled=True), _pos(), bid=0.48, ask=0.52)
    assert again.status == "filled"
