"""Tests for two-leg combo roll execution (IMPROVEMENT_PLAN Phase 4).

A roll is sent as a single BAG combo: BUY-to-close the old short + SELL-to-open the new
short, atomically. These tests cover the combo builder's pricing convention, short
resolution, the new-leg re-gate + net-credit floor, the two-FillRow accounting, and
cancel-on-timeout. All IB calls are mocked; the DB uses a tmp_path SQLite.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schemas import (
    OptionRight,
    OrderState,
    PositionSnapshot,
    ScoreCard,
    Strategy,
    TradeCandidate,
)
from src.execution.order_builder import build_combo_roll_order
from src.execution.roll_executor import (
    _resolve_short_to_close,
    execute_roll,
)
from src.storage.models import CandidateRow, FillRow, OrderRow

_TODAY = date.today()
_OLD_EXPIRY = _TODAY + timedelta(days=14)
_NEW_EXPIRY = _TODAY + timedelta(days=42)


# --------------------------------------------------------------------------- #
# Fixtures / mock builders
# --------------------------------------------------------------------------- #
def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _no_sleep(monkeypatch) -> None:
    import src.execution.roll_executor as rx

    monkeypatch.setattr(rx.asyncio, "sleep", AsyncMock())


def _short() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="AAPL  PUT",
        sec_type="OPT",
        position=-2.0,
        avg_cost=1.50,
        right=OptionRight.PUT,
        strike=185.0,
        expiry=_OLD_EXPIRY,
        underlying="AAPL",
    )


def _roll_candidate(premium: float = 1.00) -> TradeCandidate:
    return TradeCandidate(
        candidate_id="roll:AAPL:P:180:x",
        strategy=Strategy.ROLL,
        underlying="AAPL",
        right=OptionRight.PUT,
        strike=180.0,
        expiry=_NEW_EXPIRY,
        contracts=2,
        premium=premium,  # approved NET credit per share
        collateral=180.0 * 2 * 100,
        roc_pct=0.55,
        annualized_yield_pct=14.0,
        breakeven=179.0,
        delta=-0.25,
        dte=(_NEW_EXPIRY - _TODAY).days,
        scores=ScoreCard(symbol="AAPL"),
    )


def _ticker(bid: float, ask: float, delta: float, iv: float = 0.30) -> MagicMock:
    t = MagicMock()
    t.bid = bid
    t.ask = ask
    g = MagicMock()
    g.delta = delta
    g.impliedVol = iv
    t.modelGreeks = g
    return t


def _leg_fill(conid: int, action: str, price: float, shares: float, commission: float) -> MagicMock:
    f = MagicMock()
    f.contract.conId = conid
    f.execution.shares = shares
    f.execution.price = price
    f.execution.execId = f"{action}.{conid}"
    f.commissionReport.commission = commission
    return f


_OPEN_CONID = 1001  # new short (sell-to-open) — qualified first in execute_roll
_CLOSE_CONID = 1002  # old short (buy-to-close) — qualified second


def _make_ib(
    new_mid: tuple[float, float],
    old_mid: tuple[float, float],
    *,
    filled: bool = True,
    fill_qty: float = 2.0,
) -> MagicMock:
    """Build a mock IB. _fetch_leg is called new-first then old-first, so qualify/reqMktData
    side_effects are ordered [open, close]."""
    ib = MagicMock()
    open_qual = MagicMock()
    open_qual.conId = _OPEN_CONID
    close_qual = MagicMock()
    close_qual.conId = _CLOSE_CONID
    ib.qualifyContractsAsync = AsyncMock(side_effect=[[open_qual], [close_qual]])

    new_t = _ticker(new_mid[0], new_mid[1], delta=-0.25)
    old_t = _ticker(old_mid[0], old_mid[1], delta=-0.55)
    ib.reqMktData = MagicMock(side_effect=[new_t, old_t])
    ib.cancelMktData = MagicMock()

    trade = MagicMock()
    trade.isDone.return_value = filled
    trade.order.orderId = 555
    trade.orderStatus.filled = fill_qty if filled else 0.0
    trade.orderStatus.avgFillPrice = -(new_mid[0] + new_mid[1]) / 2 + (old_mid[0] + old_mid[1]) / 2
    trade.orderStatus.status = "Filled" if filled else "Submitted"
    if filled:
        nm = (new_mid[0] + new_mid[1]) / 2
        om = (old_mid[0] + old_mid[1]) / 2
        trade.fills = [
            _leg_fill(_OPEN_CONID, "SELL", nm, fill_qty, 0.65),
            _leg_fill(_CLOSE_CONID, "BUY", om, fill_qty, 0.65),
        ]
    else:
        trade.fills = []
    ib.placeOrder.return_value = trade
    ib.cancelOrder = MagicMock()
    return ib


def _seed_order(candidate: TradeCandidate) -> int:
    from src.storage.db import session_scope

    with session_scope() as s:
        row = OrderRow(
            candidate_id=candidate.candidate_id,
            approval_id=None,
            state=OrderState.SUBMITTED,
            is_live=False,
            detail="queued for roll",
        )
        s.add(row)
        s.flush()
        return row.id


# --------------------------------------------------------------------------- #
# Pure-function units
# --------------------------------------------------------------------------- #
def test_combo_builder_credit_is_negative_limit():
    combo, order = build_combo_roll_order("AAPL", _CLOSE_CONID, _OPEN_CONID, 2, net_credit=1.00)
    assert combo.secType == "BAG"
    assert len(combo.comboLegs) == 2
    buy, sell = combo.comboLegs
    assert (buy.conId, buy.action) == (_CLOSE_CONID, "BUY")
    assert (sell.conId, sell.action) == (_OPEN_CONID, "SELL")
    assert order.action == "BUY"
    assert order.totalQuantity == 2
    assert order.lmtPrice == -1.00  # credit → negative net debit


def test_combo_builder_rejects_bad_inputs():
    with pytest.raises(ValueError):
        build_combo_roll_order("AAPL", 0, _OPEN_CONID, 2, net_credit=1.0)
    with pytest.raises(ValueError):
        build_combo_roll_order("AAPL", _CLOSE_CONID, _OPEN_CONID, 0, net_credit=1.0)


def test_resolve_short_picks_nearest_dated_match():
    near = _short()
    far = _short().model_copy(update={"expiry": _TODAY + timedelta(days=30), "strike": 190.0})
    other = _short().model_copy(update={"right": OptionRight.CALL})
    cand = _roll_candidate()
    chosen = _resolve_short_to_close([far, near, other], cand)
    assert chosen is near
    # No short earlier than the new expiry → None.
    assert _resolve_short_to_close([], cand) is None


# --------------------------------------------------------------------------- #
# Full execute_roll path
# --------------------------------------------------------------------------- #
async def test_roll_fills_writes_two_legs(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    _no_sleep(monkeypatch)
    import src.execution.roll_executor as rx

    monkeypatch.setattr(rx, "get_positions", lambda ib: [_short()])

    cand = _roll_candidate(premium=1.00)
    order_id = _seed_order(cand)
    # new mid 1.80, old mid 0.80 → net credit 1.00 (>= 0.80 floor).
    ib = _make_ib(new_mid=(1.78, 1.82), old_mid=(0.78, 0.82))
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await execute_roll(ib, bot, "chat", order_id, cand)

    ib.placeOrder.assert_called_once()
    from src.storage.db import session_scope

    with session_scope() as s:
        order = s.get(OrderRow, order_id)
        fills = s.query(FillRow).order_by(FillRow.action).all()
        assert order.state == OrderState.FILLED
        assert len(fills) == 2
        buy = next(f for f in fills if f.action == "BUY")
        sell = next(f for f in fills if f.action == "SELL")
        assert sell.candidate_id == cand.candidate_id
        assert sell.entry_iv == pytest.approx(0.30)
        # No original CandidateRow → synthetic close attribution.
        assert buy.candidate_id.startswith("roll-close:AAPL:")


async def test_roll_close_leg_attributed_to_original_short(tmp_path, monkeypatch):
    """When the short was opened by the system, the BUY-close fill is recorded under the
    original candidate_id so the verdict ledger labels it closed_early."""
    _db_setup(tmp_path, monkeypatch)
    _no_sleep(monkeypatch)
    import src.execution.roll_executor as rx

    monkeypatch.setattr(rx, "get_positions", lambda ib: [_short()])

    from src.storage.db import session_scope

    orig_id = "cash_secured_put:AAPL:P:185:orig"
    with session_scope() as s:
        s.add(
            CandidateRow(
                candidate_id=orig_id,
                run_id="r1",
                strategy="cash_secured_put",
                underlying="AAPL",
                right="P",
                strike=185.0,
                expiry=_OLD_EXPIRY,
                payload={},
            )
        )
        s.add(
            FillRow(
                order_id=1,
                candidate_id=orig_id,
                action="SELL",
                filled_qty=2.0,
                avg_price=1.50,
            )
        )

    cand = _roll_candidate()
    order_id = _seed_order(cand)
    ib = _make_ib(new_mid=(1.78, 1.82), old_mid=(0.78, 0.82))
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await execute_roll(ib, bot, "chat", order_id, cand)

    with session_scope() as s:
        buy = s.query(FillRow).filter(FillRow.action == "BUY").one()
        assert buy.candidate_id == orig_id


async def test_roll_rejected_on_credit_collapse(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    _no_sleep(monkeypatch)
    import src.execution.roll_executor as rx

    monkeypatch.setattr(rx, "get_positions", lambda ib: [_short()])

    cand = _roll_candidate(premium=1.00)
    order_id = _seed_order(cand)
    # new mid 1.80, old mid 1.20 → net 0.60 < 0.80 * 1.00 floor → collapse.
    ib = _make_ib(new_mid=(1.78, 1.82), old_mid=(1.18, 1.22))
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await execute_roll(ib, bot, "chat", order_id, cand)

    ib.placeOrder.assert_not_called()
    from src.storage.db import session_scope

    with session_scope() as s:
        order = s.get(OrderRow, order_id)
        assert order.state == OrderState.REJECTED
        assert "collapse" in (order.detail or "")
        assert s.query(FillRow).count() == 0


async def test_roll_rejected_on_net_debit(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    _no_sleep(monkeypatch)
    import src.execution.roll_executor as rx

    monkeypatch.setattr(rx, "get_positions", lambda ib: [_short()])

    cand = _roll_candidate(premium=1.00)
    order_id = _seed_order(cand)
    # new mid 0.80 < old mid 1.00 → net debit.
    ib = _make_ib(new_mid=(0.78, 0.82), old_mid=(0.98, 1.02))
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await execute_roll(ib, bot, "chat", order_id, cand)

    ib.placeOrder.assert_not_called()
    from src.storage.db import session_scope

    with session_scope() as s:
        assert s.get(OrderRow, order_id).state == OrderState.REJECTED


async def test_roll_rejected_when_no_matching_short(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    _no_sleep(monkeypatch)
    import src.execution.roll_executor as rx

    monkeypatch.setattr(rx, "get_positions", lambda ib: [])  # no positions

    cand = _roll_candidate()
    order_id = _seed_order(cand)
    ib = _make_ib(new_mid=(1.78, 1.82), old_mid=(0.78, 0.82))
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await execute_roll(ib, bot, "chat", order_id, cand)

    ib.placeOrder.assert_not_called()
    ib.qualifyContractsAsync.assert_not_called()
    from src.storage.db import session_scope

    with session_scope() as s:
        assert s.get(OrderRow, order_id).state == OrderState.REJECTED


async def test_roll_cancels_on_timeout(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    _no_sleep(monkeypatch)
    import src.execution.roll_executor as rx

    monkeypatch.setattr(rx, "get_positions", lambda ib: [_short()])
    # Force the fill deadline to be already past.
    real_cfg = rx.get_config()
    cfg = MagicMock()
    cfg.is_live = False
    cfg.execution.fill_timeout_minutes = 0.0
    cfg.risk = real_cfg.risk
    monkeypatch.setattr(rx, "get_config", lambda: cfg)

    cand = _roll_candidate()
    order_id = _seed_order(cand)
    ib = _make_ib(new_mid=(1.78, 1.82), old_mid=(0.78, 0.82), filled=False)
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await execute_roll(ib, bot, "chat", order_id, cand)

    ib.cancelOrder.assert_called_once()
    from src.storage.db import session_scope

    with session_scope() as s:
        assert s.get(OrderRow, order_id).state == OrderState.CANCELLED
        assert s.query(FillRow).count() == 0


async def test_roll_reprice_steps_toward_market(tmp_path, monkeypatch):
    """With chase enabled, an unfilled roll combo is repriced toward live market credit (C5)."""
    _db_setup(tmp_path, monkeypatch)
    _no_sleep(monkeypatch)
    import src.execution.roll_executor as rx

    monkeypatch.setattr(rx, "get_positions", lambda ib: [_short()])
    cfg = MagicMock()
    cfg.is_live = False
    cfg.execution.fill_timeout_minutes = 1
    cfg.execution.reprice_enabled = True
    cfg.execution.reprice_interval_seconds = 0.0
    cfg.execution.max_reprices = 1
    cfg.execution.reprice_step_pct = 0.34
    cfg.risk = {"live_execution": {"min_live_premium_ratio": 0.80}}
    monkeypatch.setattr(rx, "get_config", lambda: cfg)
    # Fresh leg quotes: new=(1.68,1.72) → mid 1.70; old=(0.78,0.82) → mid 0.80
    # fresh_net_credit = 0.90 → combo_ask_lmt = -0.90
    monkeypatch.setattr(rx, "_refetch_bid_ask", AsyncMock(side_effect=[(1.68, 1.72), (0.78, 0.82)]))

    cand = _roll_candidate(premium=1.00)
    order_id = _seed_order(cand)
    # Initial: new mid 1.80, old mid 0.80 → net credit 1.00, lmtPrice = -1.00.
    ib = _make_ib(new_mid=(1.78, 1.82), old_mid=(0.78, 0.82), filled=True)
    calls: dict[str, int] = {"n": 0}

    def _isdone() -> bool:
        calls["n"] += 1
        return calls["n"] >= 3  # False×2 (while + reprice guard), then True

    ib.placeOrder.return_value.isDone.side_effect = _isdone
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await execute_roll(ib, bot, "chat", order_id, cand)

    # Two placeOrder calls: initial combo + one reprice.
    assert ib.placeOrder.call_count == 2
    from src.storage.db import session_scope

    with session_scope() as s:
        row = s.get(OrderRow, order_id)
        # reprice_limit("BUY", -1.00, ask=-0.90, step=0.34) → -1.00+0.034 = -0.966 → -0.97
        assert row.limit_price == pytest.approx(-0.97)


async def test_roll_reprice_floor_not_breached(tmp_path, monkeypatch):
    """Ceiling on the BAG lmtPrice prevents accepting less than min_live_premium_ratio credit (C5)."""
    _db_setup(tmp_path, monkeypatch)
    _no_sleep(monkeypatch)
    import src.execution.roll_executor as rx

    monkeypatch.setattr(rx, "get_positions", lambda ib: [_short()])
    cfg = MagicMock()
    cfg.is_live = False
    cfg.execution.fill_timeout_minutes = 1
    cfg.execution.reprice_enabled = True
    cfg.execution.reprice_interval_seconds = 0.0
    cfg.execution.max_reprices = 1
    cfg.execution.reprice_step_pct = 1.0  # full step so the ceiling binds clearly
    cfg.risk = {"live_execution": {"min_live_premium_ratio": 0.80}}
    monkeypatch.setattr(rx, "get_config", lambda: cfg)
    # Fresh market drops to $0.70 credit (< floor 0.80 × 1.00 = $0.80).
    # ceiling_lmt = -0.80; reprice must cap at -0.80, not go above.
    monkeypatch.setattr(rx, "_refetch_bid_ask", AsyncMock(side_effect=[(1.48, 1.52), (0.78, 0.82)]))

    cand = _roll_candidate(premium=1.00)
    order_id = _seed_order(cand)
    ib = _make_ib(new_mid=(1.78, 1.82), old_mid=(0.78, 0.82), filled=True)
    calls: dict[str, int] = {"n": 0}

    def _isdone() -> bool:
        calls["n"] += 1
        return calls["n"] >= 3

    ib.placeOrder.return_value.isDone.side_effect = _isdone
    bot = MagicMock()
    bot.send_message = AsyncMock()

    await execute_roll(ib, bot, "chat", order_id, cand)

    assert ib.placeOrder.call_count == 2
    from src.storage.db import session_scope

    with session_scope() as s:
        row = s.get(OrderRow, order_id)
        # fresh_net_credit = 1.50 - 0.80 = 0.70; combo_ask_lmt = -0.70
        # reprice_limit("BUY", -1.00, ask=-0.70, step=1.0, ceiling=-0.80):
        #   target = -0.70, min(-0.70, -0.80) = -0.80 → ceiling holds minimum $0.80 credit
        assert row.limit_price == pytest.approx(-0.80)
