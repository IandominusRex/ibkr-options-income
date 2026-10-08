"""Broker ↔ DB reconciliation: recover orders/fills the daemon may have missed.

Extracted from ``approval_service`` (SYSTEM_REVIEW structural finding — the notify layer
should not own broker reconciliation). Two recovery paths, both strictly additive against
the broker (they only reset stuck local state or record *proven* fills — never cancel or
resubmit, so they cannot cause a double trade):

* :func:`recover_orphan_orders` — SUBMITTED rows with no ``ib_order_id`` (claimed by a prior
  process that crashed before ``placeOrder``) are reset to QUEUED so the poll loop retries.
* :func:`reconcile_orphan_fills` — orders *with* an ``ib_order_id`` whose fill event was lost
  get their FillRow back-filled from ``reqExecutions``. Covers SUBMITTED rows (fill lost in a
  socket drop) **and** REJECTED/CANCELLED rows that still carry an ``ib_order_id`` (N8): the
  executor's except path marks an order REJECTED when its monitor loop throws — e.g. a
  ``cancelOrder`` on a dropped socket — but the SELL may already have filled at the broker, so
  that fill must still be recovered (otherwise: a live short with no FillRow, invisible to
  profit-take, with no entry IV and a mislabelled ledger). Pre-placement cancels (TTL expiry,
  re-validation REJECT) carry no ``ib_order_id`` and are correctly ignored. Run at startup
  **and** periodically from the intraday loop (SYSTEM_REVIEW F7) so a fill that lands during a
  mid-session reconnect is recovered on the next cycle, not only on the next restart.
* :func:`reconcile_external_closes` — a *manual* buy-to-close in TWS (which the roll alerts
  explicitly invite, since rolls are alert-only) writes no FillRow, so the verdict-ledger
  reconciler would mislabel the position ``expired_worthless`` with the full premium as P&L,
  and EOD cashflow would omit the debit. This records such BUY executions as a BUY FillRow
  attributed to the **original short's** ``candidate_id`` (so the ledger sees a close and labels
  it ``closed_early``), keyed by IBKR ``execId`` for idempotency (SYSTEM_REVIEW F7).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ib_async import IB
from sqlalchemy import select

from src.claude.memory import FILLED, record_outcome
from src.common.config import get_config
from src.common.schemas import OrderState
from src.storage.db import session_scope
from src.storage.models import CandidateRow, FillRow, OrderRow
from src.storage.orders import open_short_candidate_id

log = logging.getLogger(__name__)

# ``reqExecutionsAsync`` resolves on the broker's ``execDetailsEnd`` event. On a half-dead
# socket — TWS accepted the connection but has no upstream link to IBKR (Error 1100) — that
# event never arrives and the bare ``await`` hangs *forever*. Because reconciliation runs in
# the approval-service startup critical path (before the intraday-scan task is created), such
# a hang silently stops the 15-min scan loop from ever arming. Bound every executions request
# so a dead connection raises instead of blocking the whole service.
_REQ_EXECUTIONS_TIMEOUT_SECONDS = 30.0


async def _req_executions_bounded(ib: IB, context: str) -> list[Any] | None:
    """``ib.reqExecutionsAsync()`` with a hard timeout. Returns None on failure/timeout.

    A returned None means the caller must abort its reconciliation pass — never treat it as
    "no executions" (which would be an empty list), since that distinction matters for the
    additive recovery logic.
    """
    try:
        return await asyncio.wait_for(
            ib.reqExecutionsAsync(), timeout=_REQ_EXECUTIONS_TIMEOUT_SECONDS
        )
    except TimeoutError:
        log.error(
            "%s: reqExecutions timed out after %.0fs (likely a half-dead TWS socket) — "
            "skipping this reconciliation pass",
            context,
            _REQ_EXECUTIONS_TIMEOUT_SECONDS,
        )
        return None
    except Exception:
        log.exception("%s: reqExecutions failed", context)
        return None


def recover_orphan_orders() -> None:
    """Reset SUBMITTED orders with no IB order id back to QUEUED (crash before placeOrder)."""
    with session_scope() as s:
        orphans = (
            s.query(OrderRow)
            .filter(OrderRow.state == OrderState.SUBMITTED, OrderRow.ib_order_id.is_(None))
            .all()
        )
        for o in orphans:
            o.state = OrderState.QUEUED
            log.warning("Recovered orphan order id=%s to QUEUED", o.id)


def _expiry_to_date(yyyymmdd: str) -> date | None:
    if not yyyymmdd or len(yyyymmdd) < 8:
        return None
    try:
        return date(int(yyyymmdd[0:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))
    except (ValueError, TypeError):
        return None


def _exec_matches_candidate(fill: object, candidate: CandidateRow, ib_order_id: int | None) -> bool:
    """True if an IBKR Fill corresponds to the opening (SELL) order for *candidate*.

    Primary match is the broker order id (stable within a clientId session); falls back to a
    contract match (right / strike / expiry) so a fill is still recovered after an id churn
    across a full restart. Either way the underlying must match: order ids are only unique per
    clientId, so an execution from another clientId on the same login — the spreads book's
    clientId 30, trading SPY — can carry the same id as a stuck wheel order.
    """
    execution = getattr(fill, "execution", None)
    contract = getattr(fill, "contract", None)
    if execution is None or contract is None:
        return False

    if getattr(contract, "symbol", None) != candidate.underlying:
        return False

    if ib_order_id is not None and getattr(execution, "orderId", None) == ib_order_id:
        return True
    right = str(getattr(contract, "right", "") or "")[:1].upper()
    if right and candidate.right and right != candidate.right[:1].upper():
        return False
    if candidate.strike and abs(float(getattr(contract, "strike", 0.0)) - candidate.strike) > 1e-3:
        return False
    exp = _expiry_to_date(str(getattr(contract, "lastTradeDateOrContractMonth", "")))
    if candidate.expiry and exp is not None and exp != candidate.expiry:
        return False
    # Opening income trades are sells; ignore buy-side executions (e.g. a buy-to-close).
    side = str(getattr(execution, "side", "") or "").upper()
    return side in ("", "SLD")


# Order states eligible for fill recovery: a placed order (has ib_order_id) that may have
# filled at the broker before the local row reached a terminal-fill state. REJECTED/CANCELLED
# are included for N8 (executor except path); FILLED/PARTIAL are excluded (already recorded).
_RECOVERABLE_STATES = (OrderState.SUBMITTED, OrderState.REJECTED, OrderState.CANCELLED)


async def reconcile_orphan_fills(ib: IB, bot: object, chat_id: str) -> None:
    """Recover SELL fills that landed while the service was disconnected or after a failure.

    For any recoverable order (SUBMITTED, or REJECTED/CANCELLED with an ``ib_order_id`` — N8)
    with a matching execution and no FillRow, record the fill, mark the order FILLED/PARTIAL,
    and notify. Idempotent (skips orders that already have a FillRow), so it is safe to run
    repeatedly — at startup and on the intraday cadence.
    """
    with session_scope() as s:
        rows = (
            s.query(OrderRow)
            .filter(OrderRow.state.in_(_RECOVERABLE_STATES), OrderRow.ib_order_id.isnot(None))
            .all()
        )
        orphans = [(o.id, o.candidate_id, o.ib_order_id) for o in rows]
        created = {o.id: o.created_at for o in rows}
        already_filled = {
            fid
            for (fid,) in s.query(FillRow.order_id).filter(
                FillRow.order_id.in_([o.id for o in rows] or [-1])
            )
        }
    orphans = [o for o in orphans if o[0] not in already_filled]
    if not orphans:
        return

    fills = await _req_executions_bounded(ib, "Fill reconciliation")
    if fills is None:
        return

    # An execution is claimable by at most one order. Drop executions already recorded
    # (by execId), and never let the contract-match fallback hand an execution to an order
    # other than the one IBKR says placed it: a cancelled attempt and its re-queued retry share
    # a candidate and a contract, so the fallback alone gave the retry's fill to the cancelled
    # order too (2026-10-01: GOOGL order 15 recorded order 17's 2 @ 2.98 a second time).
    with session_scope() as s:
        claimed_exec_ids = {
            e for (e,) in s.query(FillRow.ib_exec_id).filter(FillRow.ib_exec_id.isnot(None))
        }
        known_ib_order_ids = {
            i for (i,) in s.query(OrderRow.ib_order_id).filter(OrderRow.ib_order_id.isnot(None))
        }

    def _claimable(f: Any, ib_order_id: int | None) -> bool:
        ex = getattr(f, "execution", None)
        if getattr(ex, "execId", None) in claimed_exec_ids:
            return False
        exec_order_id = getattr(ex, "orderId", None)
        return exec_order_id == ib_order_id or exec_order_id not in known_ib_order_ids

    is_live = bool(get_config().is_live)
    recovered = 0
    close_orphans = [o for o in orphans if o[1].startswith(_CLOSE_PREFIX)]
    orphans = [o for o in orphans if not o[1].startswith(_CLOSE_PREFIX)]
    for order_id, candidate_id, ib_order_id in close_orphans:
        if ib_order_id is not None and await _recover_close_fill(
            order_id,
            candidate_id,
            ib_order_id,
            created[order_id],
            [f for f in fills if _claimable(f, ib_order_id)],
            claimed_exec_ids,
            is_live,
            bot,
            chat_id,
        ):
            recovered += 1
    for order_id, candidate_id, ib_order_id in orphans:
        with session_scope() as s:
            cand = s.execute(
                select(CandidateRow).where(CandidateRow.candidate_id == candidate_id)
            ).scalar_one_or_none()
            if cand is None:
                continue
            matched = [
                f
                for f in fills
                if _claimable(f, ib_order_id) and _exec_matches_candidate(f, cand, ib_order_id)
            ]
            if not matched:
                continue
            claimed_exec_ids.update(
                e for f in matched if (e := getattr(f.execution, "execId", None)) is not None
            )

            total_qty = 0.0
            notional = 0.0
            commission = 0.0
            exec_id = None
            for f in matched:
                ex = f.execution
                shares = float(getattr(ex, "shares", 0.0) or 0.0)
                price = float(getattr(ex, "price", 0.0) or 0.0)
                total_qty += shares
                notional += shares * price
                exec_id = getattr(ex, "execId", exec_id)
                cr = getattr(f, "commissionReport", None)
                c = getattr(cr, "commission", None) if cr is not None else None
                if c:
                    commission += float(c)
            if total_qty <= 0:
                continue
            avg_price = notional / total_qty

            order = s.get(OrderRow, order_id)
            if order is None or order.state not in _RECOVERABLE_STATES:
                continue
            payload = cand.payload or {}
            contracts = float(payload.get("contracts", total_qty))
            order.state = OrderState.FILLED if total_qty >= contracts else OrderState.PARTIAL
            order.filled_qty = total_qty
            order.avg_fill_price = avg_price
            order.detail = "Recovered from reqExecutions"
            s.add(
                FillRow(
                    order_id=order_id,
                    candidate_id=candidate_id,
                    action="SELL",
                    filled_qty=total_qty,
                    avg_price=avg_price,
                    commission=commission or None,
                    ib_exec_id=exec_id,
                    is_live=is_live,
                )
            )
        record_outcome(candidate_id, FILLED)
        recovered += 1
        log.warning(
            "Fill reconciliation: recovered fill for order_id=%s candidate=%s qty=%.0f @ %.2f",
            order_id,
            candidate_id,
            total_qty,
            avg_price,
        )
        try:
            await bot.send_message(  # type: ignore[attr-defined]
                chat_id=chat_id,
                text=(
                    f"♻️ Recovered a missed fill: {cand.underlying} "
                    f"{total_qty:.0f} @ {avg_price:.2f} (order_id={order_id})."
                ),
            )
        except Exception:
            log.exception("Fill reconciliation: failed to notify for order_id=%s", order_id)

    if recovered:
        log.warning("Fill reconciliation: recovered %d missed fill(s)", recovered)


_CLOSE_PREFIX = "close:"
_ET = ZoneInfo("America/New_York")


def _parse_close_id(candidate_id: str) -> tuple[str, date, float, str] | None:
    """``close:{underlying}:{YYYYMMDD}:{strike}:{right}`` → its contract, or None."""
    parts = candidate_id.split(":")
    if len(parts) != 5:
        return None
    expiry = _expiry_to_date(parts[2])
    try:
        strike = float(parts[3])
    except ValueError:
        return None
    if expiry is None or parts[4] not in ("C", "P"):
        return None
    return parts[1], expiry, strike, parts[4]


def _as_utc(ts: datetime | None) -> datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _is_close_execution(
    f: Any, ib_order_id: int, contract: tuple[str, date, float, str], placed_at: datetime | None
) -> bool:
    """A BOT execution of *this* close order: order id AND contract must both match.

    The order id alone is not proof: IBKR order ids restart after a Gateway restart
    (2026-10-05/06: two different closes both carry 188).
    """
    ex = getattr(f, "execution", None)
    con = getattr(f, "contract", None)
    if ex is None or con is None or getattr(ex, "orderId", None) != ib_order_id:
        return False
    if str(getattr(ex, "side", "") or "").upper() != "BOT":
        return False
    underlying, expiry, strike, right = contract
    if getattr(con, "symbol", None) != underlying:
        return False
    if str(getattr(con, "right", "") or "")[:1].upper() != right:
        return False
    if abs(float(getattr(con, "strike", 0.0) or 0.0) - strike) > 1e-3:
        return False
    if _expiry_to_date(str(getattr(con, "lastTradeDateOrContractMonth", ""))) != expiry:
        return False
    exec_time = _as_utc(getattr(ex, "time", None))
    placed = _as_utc(placed_at)
    return not (exec_time and placed and exec_time < placed - timedelta(minutes=1))


async def _recover_close_fill(
    order_id: int,
    candidate_id: str,
    ib_order_id: int,
    placed_at: datetime | None,
    fills: list[Any],
    claimed_exec_ids: set[str],
    is_live: bool,
    bot: object,
    chat_id: str,
) -> bool:
    """Record a buy-to-close the system placed but lost track of (2026-10-02 TQQQ 74P).

    ``close_short_position`` leaves an order SUBMITTED when it errors after placeOrder (older
    rows say REJECTED; a timeout cancel can also race a fill). Its BUY execution is the
    system's own order id, so ``reconcile_external_closes`` deliberately skips it — this is
    the only pass that can record it. The fill goes on the short it closes. A close still
    SUBMITTED from an earlier ET day with no execution was a DAY order that ended unfilled:
    mark it CANCELLED so it stops blocking the next close of that position.
    """
    contract = _parse_close_id(candidate_id)
    if contract is None:
        return False
    matched = [f for f in fills if _is_close_execution(f, ib_order_id, contract, placed_at)]
    if not matched:
        placed = _as_utc(placed_at)
        if placed is not None and placed.astimezone(_ET).date() < datetime.now(_ET).date():
            with session_scope() as s:
                order = s.get(OrderRow, order_id)
                if order is not None and order.state == OrderState.SUBMITTED:
                    order.state = OrderState.CANCELLED
                    order.detail = "DAY close order ended with no execution (reconciliation)"
                    log.warning(
                        "Fill reconciliation: close order_id=%s from an earlier day had no "
                        "execution; marked cancelled",
                        order_id,
                    )
        return False

    total_qty = sum(float(getattr(f.execution, "shares", 0.0) or 0.0) for f in matched)
    if total_qty <= 0:
        return False
    notional = sum(
        float(getattr(f.execution, "shares", 0.0) or 0.0)
        * float(getattr(f.execution, "price", 0.0) or 0.0)
        for f in matched
    )
    avg_price = notional / total_qty
    commission = 0.0
    for f in matched:
        cr = getattr(f, "commissionReport", None)
        c = getattr(cr, "commission", None) if cr is not None else None
        if c:
            commission += float(c)
    exec_id = getattr(matched[-1].execution, "execId", None)
    underlying, expiry, strike, right = contract
    with session_scope() as s:
        order = s.get(OrderRow, order_id)
        if order is None or order.state not in _RECOVERABLE_STATES:
            return False
        fill_candidate = (
            open_short_candidate_id(s, underlying, right, strike, expiry) or candidate_id
        )
        order.state = OrderState.FILLED
        order.filled_qty = total_qty
        order.avg_fill_price = avg_price
        order.detail = "Recovered close fill from reqExecutions"
        s.add(
            FillRow(
                order_id=order_id,
                candidate_id=fill_candidate,
                action="BUY",
                filled_qty=total_qty,
                avg_price=avg_price,
                commission=commission or None,
                ib_exec_id=exec_id,
                is_live=is_live,
            )
        )
    claimed_exec_ids.update(
        e for f in matched if (e := getattr(f.execution, "execId", None)) is not None
    )
    log.warning(
        "Fill reconciliation: recovered close fill for order_id=%s %s qty=%.0f @ %.2f",
        order_id,
        candidate_id,
        total_qty,
        avg_price,
    )
    try:
        await bot.send_message(  # type: ignore[attr-defined]
            chat_id=chat_id,
            text=(
                f"♻️ Recovered a missed close: bought back {total_qty:.0f} {underlying} "
                f"{strike:g}{right} @ {avg_price:.2f} (order_id={order_id})."
            ),
        )
    except Exception:
        log.exception("Fill reconciliation: failed to notify for order_id=%s", order_id)
    return True


def _net_short_qty(session, candidate_id: str) -> float:
    """Σ SELL qty − Σ BUY qty for a candidate. > 0 means the short is still (partly) open."""
    rows = session.execute(
        select(FillRow.action, FillRow.filled_qty).where(FillRow.candidate_id == candidate_id)
    ).all()
    sold = sum(q for a, q in rows if (a or "SELL").upper() == "SELL")
    bought = sum(q for a, q in rows if (a or "SELL").upper() == "BUY")
    return float(sold - bought)


def _buy_option_executions(fills: list) -> list:
    """IBKR Fill objects that are option buy-to-close executions (secType OPT, side BOT)."""
    out = []
    for f in fills:
        ex = getattr(f, "execution", None)
        contract = getattr(f, "contract", None)
        if ex is None or contract is None:
            continue
        if str(getattr(contract, "secType", "") or "").upper() != "OPT":
            continue
        if str(getattr(ex, "side", "") or "").upper() != "BOT":
            continue
        out.append(f)
    return out


async def reconcile_external_closes(ib: IB, bot: object, chat_id: str) -> None:
    """Record manual buy-to-close executions (done outside the system) as BUY FillRows.

    For each option BUY execution not already recorded (idempotent on IBKR ``execId``), find the
    original short position — a candidate with a SELL fill on the same contract that is still net
    short — and write a BUY FillRow under *that* candidate_id. This flips the ledger outcome from
    ``expired_worthless`` to ``closed_early`` and makes EOD cashflow include the debit (F7).

    Strictly additive: it only records proven broker executions; it never places or cancels.
    """
    fills = await _req_executions_bounded(ib, "External-close reconciliation")
    if fills is None:
        return

    buys = _buy_option_executions(fills)
    if not buys:
        return

    is_live = bool(get_config().is_live)
    recovered: list[tuple[str, float, float]] = []  # (symbol, qty, price) for notification

    with session_scope() as s:
        recorded_exec_ids = {
            e for (e,) in s.query(FillRow.ib_exec_id).filter(FillRow.ib_exec_id.isnot(None))
        }
        # Orders the system placed itself (profit-take/loss-exit closes, rolls). Their fills are
        # recorded by their own code path, which stores one execId per order — so a close that
        # fills across several executions leaves the others "unrecorded" here (2026-10-02: a
        # GOOGL loss-exit filled 1+1; the second execution was re-recorded as a manual close).
        own_ib_order_ids = {
            i for (i,) in s.query(OrderRow.ib_order_id).filter(OrderRow.ib_order_id.isnot(None))
        }
        for f in buys:
            ex = f.execution
            exec_id = getattr(ex, "execId", None)
            if not exec_id or exec_id in recorded_exec_ids:
                continue  # already recorded (incl. system auto-closes) → never double-count
            exec_order_id = getattr(ex, "orderId", None)
            if exec_order_id and exec_order_id in own_ib_order_ids:
                continue  # one of our own orders, not a manual close

            contract = f.contract
            symbol = getattr(contract, "symbol", None)
            right = str(getattr(contract, "right", "") or "")[:1].upper()
            strike = float(getattr(contract, "strike", 0.0) or 0.0)
            expiry = _expiry_to_date(str(getattr(contract, "lastTradeDateOrContractMonth", "")))
            shares = float(getattr(ex, "shares", 0.0) or 0.0)
            price = float(getattr(ex, "price", 0.0) or 0.0)
            if (
                not symbol
                or right not in ("C", "P")
                or strike <= 0
                or expiry is None
                or shares <= 0
            ):
                continue

            # Match to a candidate we actually sold on this exact contract.
            candidates = (
                s.execute(
                    select(CandidateRow)
                    .join(FillRow, FillRow.candidate_id == CandidateRow.candidate_id)
                    .where(
                        CandidateRow.underlying == symbol,
                        CandidateRow.right == right,
                        CandidateRow.expiry == expiry,
                        FillRow.action == "SELL",
                    )
                )
                .scalars()
                .all()
            )
            cand = next(
                (c for c in candidates if abs((c.strike or 0.0) - strike) < 1e-3),
                None,
            )
            if cand is None:
                continue  # we never sold this contract → not a close of one of our shorts
            if _net_short_qty(s, cand.candidate_id) <= 0:
                continue  # already fully bought back

            cr = getattr(f, "commissionReport", None)
            commission = float(getattr(cr, "commission", 0.0) or 0.0) if cr is not None else 0.0
            entry_order = (
                s.execute(
                    select(OrderRow)
                    .where(OrderRow.candidate_id == cand.candidate_id)
                    .order_by(OrderRow.created_at.desc())
                )
                .scalars()
                .first()
            )
            s.add(
                FillRow(
                    order_id=entry_order.id if entry_order is not None else 0,
                    candidate_id=cand.candidate_id,
                    action="BUY",
                    filled_qty=shares,
                    avg_price=price,
                    commission=commission or None,
                    ib_exec_id=exec_id,
                    is_live=is_live,
                )
            )
            recorded_exec_ids.add(exec_id)
            recovered.append((symbol, shares, price))
            log.warning(
                "External-close reconciliation: recorded manual buy-to-close %s %s %.0f @ %.2f "
                "(candidate=%s execId=%s)",
                symbol,
                right,
                shares,
                price,
                cand.candidate_id,
                exec_id,
            )

    for symbol, qty, price in recovered:
        try:
            await bot.send_message(  # type: ignore[attr-defined]
                chat_id=chat_id,
                text=(
                    f"♻️ Recorded a manual close detected at the broker: {symbol} "
                    f"bought {qty:.0f} @ {price:.2f}. Ledger + EOD cashflow updated."
                ),
            )
        except Exception:
            log.exception("External-close reconciliation: failed to notify for %s", symbol)

    if recovered:
        log.warning("External-close reconciliation: recorded %d manual close(s)", len(recovered))
