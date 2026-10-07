"""The only writer of the broker_* ledger tables (spec §5.4; revisions R2, R8).

Every feed — Activity Statement CSV, Flex XML, live fills — lands here as a ParsedStatement.
Rows upsert by dedupe key, then an order-level twin pass supersedes duplicates that arrive
from different feeds with different granularity, so arrival order never matters.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.schemas import (
    LedgerImportResult,
    LedgerSource,
    ParsedCashEvent,
    ParsedCorporateAction,
    ParsedExecution,
    ParsedFxRate,
    ParsedStatement,
)
from src.ledger.contracts import et_date
from src.ledger.state import bump_generation, ledger_account, lock_account
from src.storage.db import session_scope
from src.storage.models import (
    BrokerCashEventRow,
    BrokerCorporateActionRow,
    BrokerExecutionRow,
    FxRateRow,
    LedgerImportRunRow,
    OrderRow,
)

log = logging.getLogger(__name__)

_PRICE_TOLERANCE = 0.005
_QTY_TOLERANCE = 1e-6
_MAX_STORED_ERRORS = 200


def _sha(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def execution_dedupe_key(e: ParsedExecution) -> str:
    if e.exec_id:
        return f"exec:{e.exec_id}"
    return "order:" + _sha(
        e.contract.ident,
        e.trade_time.astimezone(UTC).isoformat(),
        f"{e.quantity:g}",
        f"{e.price:.6f}",
        e.occurrence_idx,
    )


def _statement_account(st: ParsedStatement) -> str | None:
    if st.account:
        return st.account
    return next((e.account for e in st.executions if e.account), None)


def _account_refusal(s: Session, st: ParsedStatement, source: LedgerSource) -> str | None:
    tracked = ledger_account(s)
    incoming = _statement_account(st)
    if tracked is None:
        if source == "live":
            return "no_ledger_account"
        if incoming:
            lock_account(s, incoming)
        return None
    if incoming and incoming != tracked:
        return "account_mismatch"
    return None


def _upsert_execution(
    s: Session, e: ParsedExecution, *, source: str, run_id: int
) -> tuple[bool, bool, bool, int]:
    """Upsert one execution/order row.

    Returns ``(created, changed, order_id_tag_candidate, row_id)``. ``changed`` is True if a
    new row was created or an existing row had a field backfilled (commission, perm_id,
    ib_order_id, realized P&L). ``order_id_tag_candidate`` is True when this row just acquired
    an ``ib_order_id`` for the first time — either because it was created with one, or because
    one was backfilled onto an existing row — so the book-tagging pass (F17) considers it even
    though it may not have been inserted in this run.
    """
    key = execution_dedupe_key(e)
    row = s.scalar(select(BrokerExecutionRow).where(BrokerExecutionRow.dedupe_key == key))
    if row is not None:
        changed = False
        order_id_backfilled = False
        if not row.commission and e.commission:
            row.commission = e.commission
            changed = True
        if row.perm_id is None and e.perm_id is not None:
            row.perm_id = e.perm_id
            changed = True
        if row.ib_order_id is None and e.ib_order_id is not None:
            row.ib_order_id = e.ib_order_id
            changed = True
            order_id_backfilled = True
        if row.ibkr_realized_pnl is None and e.ibkr_realized_pnl is not None:
            row.ibkr_realized_pnl = e.ibkr_realized_pnl
            changed = True
        if not row.codes and e.codes:
            row.codes = e.codes
            changed = True
        return False, changed, order_id_backfilled, row.id
    c = e.contract
    new_row = BrokerExecutionRow(
        dedupe_key=key,
        source_kind="exec" if e.exec_id else "order",
        source=source,
        exec_id=e.exec_id,
        perm_id=e.perm_id,
        ib_order_id=e.ib_order_id,
        account=e.account,
        trade_time=e.trade_time.astimezone(UTC).replace(tzinfo=None),
        trade_date=et_date(e.trade_time),
        contract_ident=c.ident,
        underlying=c.underlying,
        sec_type=c.sec_type,
        right=c.right,
        strike=c.strike,
        expiry=c.expiry,
        multiplier=c.multiplier,
        currency=c.currency,
        quantity=e.quantity,
        price=e.price,
        proceeds=e.proceeds,
        commission=e.commission,
        codes=e.codes,
        ibkr_realized_pnl=e.ibkr_realized_pnl,
        occurrence_idx=e.occurrence_idx,
        import_run_id=run_id,
        raw=e.raw,
    )
    s.add(new_row)
    s.flush()
    return True, True, e.ib_order_id is not None, new_row.id


def _same_order(a: BrokerExecutionRow, b: BrokerExecutionRow) -> bool:
    return (
        (a.quantity > 0) == (b.quantity > 0)
        and abs(a.quantity - b.quantity) < _QTY_TOLERANCE
        and abs(a.price - b.price) <= _PRICE_TOLERANCE
    )


def _exec_groups(execs: list[BrokerExecutionRow]) -> list[list[BrokerExecutionRow]]:
    groups: dict[tuple[str, int], list[BrokerExecutionRow]] = defaultdict(list)
    for r in execs:
        key = ("perm", r.perm_id) if r.perm_id is not None else ("row", r.id)
        groups[key].append(r)
    return list(groups.values())


def _best_group(
    order: BrokerExecutionRow, groups: list[list[BrokerExecutionRow]], used: set[int]
) -> int | None:
    best: tuple[float, int] | None = None
    for idx, group in enumerate(groups):
        if idx in used:
            continue
        qty = sum(r.quantity for r in group)
        if abs(qty - order.quantity) >= _QTY_TOLERANCE or qty == 0:
            continue
        vwap = sum(r.quantity * r.price for r in group) / qty
        gap = abs(vwap - order.price)
        if gap <= _PRICE_TOLERANCE and (best is None or gap < best[0]):
            best = (gap, idx)
    return best[1] if best else None


def supersede_twins(s: Session, affected: set[tuple[str, date]]) -> int:
    """Run the R2 twin pass over each affected (contract ident, ET date). Returns rows superseded.

    Exec rows are never themselves marked superseded, so an exec group that already consumed an
    order row in an earlier ingest call reappears, unmarked, on every later call — the query below
    only ever sees the *order* side's history. Without seeding ``used`` from that history, a
    group already spent on one order row would look free again and could wrongly re-match a
    second, still-unsuperseded order row with the same qty/price (found in review round 1).
    """
    superseded = 0
    for ident, day in sorted(affected):
        all_rows = list(
            s.scalars(
                select(BrokerExecutionRow)
                .where(
                    BrokerExecutionRow.contract_ident == ident,
                    BrokerExecutionRow.trade_date == day,
                )
                .order_by(BrokerExecutionRow.id)
            )
        )
        already_consumed = {
            r.superseded_by
            for r in all_rows
            if r.source_kind == "order" and r.superseded_by is not None
        }
        rows = [r for r in all_rows if r.superseded_by is None]
        groups = _exec_groups([r for r in rows if r.source_kind == "exec"])
        used: set[int] = {
            idx for idx, group in enumerate(groups) if min(r.id for r in group) in already_consumed
        }
        survivors: list[BrokerExecutionRow] = []
        for order in (r for r in rows if r.source_kind == "order"):
            idx = _best_group(order, groups, used)
            if idx is None:
                survivors.append(order)
                continue
            used.add(idx)
            order.superseded_by = min(r.id for r in groups[idx])
            # Live fills carry no O/C/A/Ep codes (controller ruling, Task 11): the order row
            # being superseded is the only side that ever has them, so backfill onto whichever
            # survivor rows are still blank. Works regardless of arrival order — a CSV/Flex row
            # superseded by an earlier-arrived exec group hits this exactly the same way.
            if order.codes:
                for r in groups[idx]:
                    if not r.codes:
                        r.codes = order.codes
            superseded += 1
        matched: set[int] = set()
        for i, later in enumerate(survivors):
            for earlier in survivors[:i]:
                if (
                    earlier.id not in matched
                    and earlier.superseded_by is None
                    and earlier.source != later.source
                    and _same_order(earlier, later)
                ):
                    later.superseded_by = earlier.id
                    matched.add(earlier.id)
                    superseded += 1
                    break
    return superseded


def _tag_books(s: Session, row_ids: set[int]) -> int:
    """Tag ``book="system"`` on rows in ``row_ids`` whose ``ib_order_id`` matches a known
    ``OrderRow`` (F17): rows inserted this run, and existing rows whose ``ib_order_id`` was
    backfilled this run (e.g. a Flex-first row later duplicated by a live fill carrying one).
    """
    if not row_ids:
        return 0
    tagged = 0
    rows = s.scalars(
        select(BrokerExecutionRow).where(
            BrokerExecutionRow.id.in_(row_ids), BrokerExecutionRow.ib_order_id.is_not(None)
        )
    )
    for r in rows:
        for order in s.scalars(select(OrderRow).where(OrderRow.ib_order_id == r.ib_order_id)):
            snap = order.snapshot or {}
            if not snap or snap.get("underlying") == r.underlying:
                r.book = "system"
                tagged += 1
                break
    return tagged


def _upsert_cash(s: Session, c: ParsedCashEvent, *, source: str, run_id: int) -> bool:
    key = "cash:" + _sha(
        c.event_type,
        c.event_date,
        c.currency,
        f"{c.amount:.2f}",
        c.underlying or "",
        c.occurrence_idx,
    )
    if s.scalar(select(BrokerCashEventRow.id).where(BrokerCashEventRow.dedupe_key == key)):
        return False
    s.add(
        BrokerCashEventRow(
            dedupe_key=key,
            event_type=c.event_type,
            event_date=c.event_date,
            currency=c.currency,
            amount=c.amount,
            description=c.description,
            underlying=c.underlying,
            source=source,
            import_run_id=run_id,
        )
    )
    s.flush()
    return True


def _upsert_corporate_action(
    s: Session, a: ParsedCorporateAction, *, source: str, run_id: int
) -> bool:
    key = "ca:" + _sha(a.event_date, a.description, a.occurrence_idx)
    if s.scalar(
        select(BrokerCorporateActionRow.id).where(BrokerCorporateActionRow.dedupe_key == key)
    ):
        return False
    s.add(
        BrokerCorporateActionRow(
            dedupe_key=key,
            event_date=a.event_date,
            underlying=a.underlying,
            description=a.description,
            quantity=a.quantity,
            proceeds=a.proceeds,
            source=source,
            import_run_id=run_id,
            raw=a.raw,
        )
    )
    s.flush()
    return True


def _upsert_fx(s: Session, fx: ParsedFxRate, *, source: str) -> None:
    row = s.scalar(
        select(FxRateRow).where(
            FxRateRow.rate_date == fx.rate_date, FxRateRow.currency == fx.currency
        )
    )
    if row is None:
        s.add(
            FxRateRow(
                rate_date=fx.rate_date, currency=fx.currency, usd_rate=fx.usd_rate, source=source
            )
        )
    else:
        row.usd_rate = fx.usd_rate
    s.flush()


def ingest(
    statement: ParsedStatement, *, source: LedgerSource, filename: str | None = None
) -> LedgerImportResult:
    """Write one parsed statement. One transaction; never partially commits trades.

    F20: a ``source="live"`` ingest that neither inserts nor changes anything (a pure
    duplicate) leaves no ``ledger_import_runs`` row behind — the run row is deleted before the
    transaction commits. A live ingest that inserts, supersedes, or backfills/tags an existing
    row keeps its run row, as do all csv/flex runs regardless of outcome.
    """
    errors = statement.errors[:_MAX_STORED_ERRORS]
    with session_scope() as s:
        refusal = "parse_errors" if statement.fatal else _account_refusal(s, statement, source)
        if refusal == "no_ledger_account" or (source == "live" and refusal == "account_mismatch"):
            # Review Focus 3 / F20: a paper (or otherwise foreign-account) live fill must leave
            # no trace at all — no run row, no execution row — same as the no-account-yet case.
            return LedgerImportResult(run_id=None, status="skipped", reason=refusal)
        run = LedgerImportRunRow(
            source=source,
            filename=filename,
            status="running",
            period_start=statement.period_start,
            period_end=statement.period_end,
        )
        s.add(run)
        s.flush()
        if refusal is not None:
            run.status, run.reason, run.finished_at = "failed", refusal, _now()
            run.errors = [e.model_dump() for e in errors]
            return LedgerImportResult(run_id=run.id, status="failed", reason=refusal, errors=errors)

        counts: dict[str, int] = defaultdict(int)
        affected: set[tuple[str, date]] = set()
        touched_ids: set[int] = set()
        any_backfill = False
        for e in statement.executions:
            created, changed, tag_candidate, row_id = _upsert_execution(
                s, e, source=source, run_id=run.id
            )
            counts["new" if created else "duplicate"] += 1
            if created or tag_candidate:
                touched_ids.add(row_id)
            if changed and not created:
                any_backfill = True
            affected.add((e.contract.ident, et_date(e.trade_time)))
        counts["superseded"] = supersede_twins(s, affected)
        counts["system"] = _tag_books(s, touched_ids)
        for c in statement.cash_events:
            counts[
                "cash_new" if _upsert_cash(s, c, source=source, run_id=run.id) else "cash_duplicate"
            ] += 1
        for a in statement.corporate_actions:
            counts[
                "ca_new"
                if _upsert_corporate_action(s, a, source=source, run_id=run.id)
                else "ca_duplicate"
            ] += 1
        for fx in statement.fx_rates:
            _upsert_fx(s, fx, source=source)
        counts["warnings"] = len(statement.errors)

        inserted_or_superseded = bool(
            counts["new"] or counts["superseded"] or counts["cash_new"] or counts["ca_new"]
        )
        touched = inserted_or_superseded or any_backfill or bool(counts["system"])

        if source == "live" and not touched:
            s.delete(run)
            log.info("ledger ingest (%s %s): no-op, discarding run row", source, filename or "")
            return LedgerImportResult(run_id=None, status="ok", counts=dict(counts), errors=errors)

        run.status, run.counts, run.finished_at = "ok", dict(counts), _now()
        run.errors = [e.model_dump() for e in errors]
        if touched:
            # Broader than "inserted or superseded" on purpose (review round 1): a commission/
            # perm_id/ib_order_id backfill or a book retag changes what the Sheets mirror and
            # readers see even with zero new rows, so it must bump the generation too.
            bump_generation(s)
        log.info("ledger ingest (%s %s): %s", source, filename or "", dict(counts))
        return LedgerImportResult(run_id=run.id, status="ok", counts=dict(counts), errors=errors)
