"""Live executions from the exec process's IBKR connection into the ledger (spec §5.3).

``ib_async`` objects are converted to ``ParsedExecution`` here and nowhere else. Everything is
best-effort: a failure here is logged and never propagates into order handling. Fills only ever
land once a CSV/Flex import has locked the ledger account (R8), so a paper session can't
pollute — or claim — the real account's ledger.

Two feeds into the same ``ingest_fills``:

- :func:`attach_live_hook` subscribes to ``commissionReportEvent`` (fires after the fill, once
  the commission is known) so normal fills are recorded promptly, at any hour.
- :func:`live_sweep_loop` periodically reuses ``reqExecutions`` (via the exec process's own
  bounded wrapper, ``src.execution.reconciliation._req_executions_bounded``) to catch anything
  the event subscription missed. Per spec §5.3 the sweep itself only runs during RTH — the
  commission-report hook is unaffected by that gate.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC
from typing import Any

from src.common.config import get_config
from src.common.market_hours import is_rth
from src.common.schemas import LedgerContract, ParsedExecution, ParsedStatement
from src.ledger.contracts import parse_ibkr_date, stock_contract
from src.ledger.ingest import ingest
from src.ledger.state import ledger_account
from src.storage.db import session_scope

log = logging.getLogger(__name__)

_UNSET = sys.float_info.max / 2  # IB reports "no value" as sys.float_info.max


def _value(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if abs(v) >= _UNSET else v


def fill_to_execution(fill: Any) -> ParsedExecution | None:
    """One ``ib_async`` ``Fill`` -> ``ParsedExecution``, or None for a non-STK/OPT leg (combos)."""
    c, ex, rep = fill.contract, fill.execution, getattr(fill, "commissionReport", None)
    sec = getattr(c, "secType", "")
    if sec not in ("OPT", "STK"):
        return None
    currency = c.currency or "USD"
    contract: LedgerContract
    if sec == "OPT":
        multiplier = float(c.multiplier or 100)
        contract = LedgerContract(
            underlying=c.symbol,
            sec_type="OPT",
            currency=currency,
            right="P" if str(c.right).upper().startswith("P") else "C",
            strike=float(c.strike),
            expiry=parse_ibkr_date(str(c.lastTradeDateOrContractMonth)[:8]),
            multiplier=multiplier,
        )
    else:
        multiplier = 1.0
        contract = stock_contract(c.symbol, currency)
    qty = float(ex.shares) * (1 if ex.side == "BOT" else -1)
    ts = ex.time if ex.time.tzinfo else ex.time.replace(tzinfo=UTC)
    commission = _value(getattr(rep, "commission", None)) if rep is not None else None
    return ParsedExecution(
        contract=contract,
        trade_time=ts,
        quantity=qty,
        price=float(ex.price),
        proceeds=-qty * float(ex.price) * multiplier,
        commission=-abs(commission) if commission else 0.0,
        exec_id=ex.execId,
        perm_id=int(ex.permId) or None,
        ib_order_id=int(ex.orderId) or None,
        account=ex.acctNumber or None,
        ibkr_realized_pnl=_value(getattr(rep, "realizedPNL", None)) if rep is not None else None,
        source_kind="exec",
    )


def ingest_fills(fills: list[Any]) -> int:
    """Ingest fills for the tracked account only. Returns new rows written.

    Fills for any other account (e.g. a paper session running while the ledger tracks the real
    account — Review Focus 3) are dropped before ``ingest`` is ever called, so they leave no
    trace at all, not even a failed import run.
    """
    with session_scope() as s:
        tracked = ledger_account(s)
    if tracked is None:
        return 0
    execs = [e for f in fills if (e := fill_to_execution(f)) is not None and e.account == tracked]
    if not execs:
        return 0
    result = ingest(ParsedStatement(account=tracked, executions=execs), source="live")
    return result.counts.get("new", 0) if result.status == "ok" else 0


_hook_tasks: set[asyncio.Task[Any]] = set()


def _log_hook_result(task: asyncio.Task[Any]) -> None:
    _hook_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.warning(
            "ledger live hook failed — ignored (never affects order handling)",
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def on_commission_report(trade: Any, fill: Any, report: Any) -> None:
    """``ib.commissionReportEvent`` handler. Must never raise into order handling.

    The SQLite write runs in a worker thread (a contended write lock can block for up to
    ``busy_timeout``), so the handler only schedules it and returns immediately.
    """
    try:
        task = asyncio.get_running_loop().create_task(asyncio.to_thread(ingest_fills, [fill]))
        _hook_tasks.add(task)
        task.add_done_callback(_log_hook_result)
    except Exception:
        log.exception("ledger live hook failed — ignored (never affects order handling)")


async def _req_executions_bounded(ib: Any, label: str) -> list[Any] | None:
    """The exec process's bounded ``reqExecutions``, imported on first use: importing it at
    module load would drag the execution layer (and, through it, the enrichment layer's
    outcome memory) into every process that only attaches the commission-report hook — the
    spreads service among them."""
    from src.execution.reconciliation import _req_executions_bounded as bounded

    return await bounded(ib, label)


def attach_live_hook(ib: Any) -> None:
    """Subscribe to commission reports (they arrive after the fill, with the commission known)."""
    ib.commissionReportEvent += on_commission_report


async def _sweep_once(ib: Any) -> int | None:
    """One sweep cycle's body. Returns the new-row count, or None if the cycle was skipped
    (outside RTH, not connected, or ``reqExecutions`` failed/timed out).

    F7a: ``_req_executions_bounded`` returns ``None`` on failure/timeout, which must never be
    read as "no executions" (an empty list) — that distinction is why this returns ``None``
    too, rather than folding it into a ``0`` new-rows result.
    """
    if not is_rth():
        return None
    if ib is None or not ib.isConnected():
        return None
    fills = await _req_executions_bounded(ib, "ledger live sweep")
    if fills is None:
        return None
    try:
        return await asyncio.to_thread(ingest_fills, list(fills))
    except Exception:
        log.warning("ledger sweep failed to ingest — will retry next cycle", exc_info=True)
        return None


async def live_sweep_loop(ib: Any, *, interval_minutes: float | None = None) -> None:
    """Every few minutes during RTH, ingest whatever ``reqExecutions`` returns (catches events
    the commission-report hook missed). The hook itself keeps recording fills at any hour —
    only this periodic sweep is RTH-gated (spec §5.3).
    """
    minutes = (
        interval_minutes if interval_minutes is not None else get_config().ledger.live_sweep_minutes
    )
    while True:
        await asyncio.sleep(minutes * 60)
        try:
            new = await _sweep_once(ib)
        except asyncio.CancelledError:
            raise
        except Exception:
            # _sweep_once already guards its own ingest call, but is_rth()/ib.isConnected()/
            # get_config() are unguarded — a surprise there must not kill this task, since the
            # approval service's shutdown `finally` awaits it outside a CancelledError suppress
            # and would otherwise re-raise whatever killed the loop, skipping app/IBKR shutdown.
            log.warning("ledger sweep cycle failed — will retry next cycle", exc_info=True)
            continue
        if new:
            log.info("ledger sweep: %d new execution(s)", new)
