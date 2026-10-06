"""Ingest: idempotent upsert, order-level twin pass, account lock, book tagging (spec §5.4, R2, R8).

Review Focus 2 (overlapping statements), 3 (paper fills vs real account, ingest side), 4 (ET date
line) are pinned here. Controller rulings F17 (book tagging on ib_order_id backfill) and F20 (a
no-op live ingest leaves no run row) are pinned here too.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.common.schemas import ParsedExecution, ParsedStatement
from src.ledger.activity_csv import parse_activity_csv
from src.ledger.contracts import parse_et_timestamp, parse_option_symbol, stock_contract

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"


def ex(
    symbol: str,
    when: str,
    qty: float,
    price: float,
    *,
    exec_id: str | None = None,
    perm: int | None = None,
    order_id: int | None = None,
    comm: float = -1.0,
    codes: str = "",
    account: str = "U0000001",
    currency: str = "USD",
    utc: datetime | None = None,
) -> ParsedExecution:
    contract = (
        parse_option_symbol(symbol, currency=currency)
        if " " in symbol
        else stock_contract(symbol, currency)
    )
    return ParsedExecution(
        contract=contract,
        trade_time=utc or parse_et_timestamp(when),
        quantity=qty,
        price=price,
        proceeds=-qty * price * contract.multiplier,
        commission=comm,
        codes=codes,
        exec_id=exec_id,
        perm_id=perm,
        ib_order_id=order_id,
        account=account,
        source_kind="exec" if exec_id else "order",
    )


def stmt(*execs: ParsedExecution, account: str | None = "U0000001") -> ParsedStatement:
    return ParsedStatement(account=account, executions=list(execs))


def _rows(db):
    from src.storage.models import BrokerExecutionRow

    with db() as s:
        return list(s.scalars(select(BrokerExecutionRow).order_by(BrokerExecutionRow.id)))


def test_reimporting_the_same_file_is_a_noop(db) -> None:
    from src.ledger.ingest import ingest

    st = parse_activity_csv(FIXTURE.read_text())
    first = ingest(st, source="csv", filename="a.csv")
    second = ingest(parse_activity_csv(FIXTURE.read_text()), source="csv", filename="a.csv")
    assert first.status == "ok" and first.counts["new"] == 15
    assert second.counts.get("new", 0) == 0 and second.counts["duplicate"] == 15
    assert len(_rows(db)) == 15


def test_overlapping_statement_inserts_only_new_rows(db) -> None:
    # Review Focus 2.
    from src.ledger.ingest import ingest

    a = ex("NVDA 18JUL25 170 P", "2025-07-11, 10:00:00", -1, 2.0)
    b = ex("NVDA 25JUL25 165 P", "2025-07-16, 10:00:00", -1, 1.5)
    c = ex("NVDA 01AUG25 160 P", "2025-07-23, 10:00:00", -1, 1.2)
    ingest(stmt(a, b), source="csv")
    result = ingest(stmt(b, c), source="csv")
    assert (result.counts["new"], result.counts["duplicate"]) == (1, 1)
    assert len(_rows(db)) == 3


def test_csv_order_superseded_by_exec_fills_arriving_later(db) -> None:
    from src.ledger.ingest import ingest

    ingest(stmt(ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -2, 1.935)), source="csv")
    r = ingest(
        stmt(
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.93, exec_id="e1", perm=77),
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:01", -1, 1.94, exec_id="e2", perm=77),
        ),
        source="flex",
    )
    rows = _rows(db)
    csv_row = next(x for x in rows if x.source_kind == "order")
    exec_ids = sorted(x.id for x in rows if x.source_kind == "exec")
    assert csv_row.superseded_by == exec_ids[0]
    assert r.counts["superseded"] == 1


def test_exec_fills_first_then_csv_is_superseded_on_arrival(db) -> None:
    from src.ledger.ingest import ingest

    ingest(
        stmt(
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.93, exec_id="e1", perm=77),
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:01", -1, 1.94, exec_id="e2", perm=77),
        ),
        source="flex",
    )
    ingest(stmt(ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -2, 1.935)), source="csv")
    csv_row = next(x for x in _rows(db) if x.source_kind == "order")
    assert csv_row.superseded_by is not None


def test_codes_backfilled_from_csv_onto_live_exec_group(db) -> None:
    # Controller ruling (Task 11): live fills carry no O/C/A/Ep codes — the surviving exec
    # rows pick up the CSV order row's codes when supersede_twins matches them. CSV first.
    from src.ledger.ingest import ingest

    ingest(
        stmt(ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -2, 1.935, codes="C")),
        source="csv",
    )
    ingest(
        stmt(
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.93, exec_id="e1", perm=77),
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:01", -1, 1.94, exec_id="e2", perm=77),
        ),
        source="live",
    )
    exec_rows = [x for x in _rows(db) if x.source_kind == "exec"]
    assert len(exec_rows) == 2
    assert all(x.codes == "C" for x in exec_rows)


def test_codes_backfilled_onto_live_exec_group_arriving_before_csv(db) -> None:
    # Same ruling, reverse arrival order: the live fill (no codes) lands first, then the CSV
    # order row (with codes) arrives and supersedes it — the surviving exec rows still end up
    # with the CSV's codes. The account must already be locked since a live-only ingest with no
    # tracked account is skipped outright (Review Focus 3 / F20).
    from src.ledger.ingest import ingest
    from src.ledger.state import lock_account

    with db() as s:
        lock_account(s, "U0000001")
    ingest(
        stmt(
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.93, exec_id="e1", perm=77),
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:01", -1, 1.94, exec_id="e2", perm=77),
        ),
        source="live",
    )
    ingest(
        stmt(ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -2, 1.935, codes="C")),
        source="csv",
    )
    rows = _rows(db)
    csv_row = next(x for x in rows if x.source_kind == "order")
    exec_rows = [x for x in rows if x.source_kind == "exec"]
    assert csv_row.superseded_by is not None
    assert len(exec_rows) == 2
    assert all(x.codes == "C" for x in exec_rows)


def test_vwap_mismatch_is_not_a_twin(db) -> None:
    from src.ledger.ingest import ingest

    ingest(stmt(ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -2, 1.80)), source="csv")
    ingest(
        stmt(
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.93, exec_id="e1", perm=77),
            ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:01", -1, 1.94, exec_id="e2", perm=77),
        ),
        source="flex",
    )
    assert all(x.superseded_by is None for x in _rows(db))


def test_reimport_does_not_resupersede_via_an_already_consumed_exec_group(db) -> None:
    # Review round 1 finding 2: the twin pass's `used` set is local to one call, so a fresh call
    # (triggered by re-importing the same CSV) must not let an exec group that already consumed
    # one order row in an earlier run "re-match" a second, still-unsuperseded order row sharing
    # its qty/price.
    from src.ledger.activity_csv import number_occurrences
    from src.ledger.ingest import ingest

    ingest(stmt(ex("NVDA", "2025-07-01, 09:00:00", 1, 100.0)), source="csv")  # locks the account

    ingest(
        stmt(ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.9, exec_id="g1", perm=1)),
        source="live",
    )

    def order_rows():
        return [r for r in _rows(db) if r.source_kind == "order" and r.strike == 170]

    st = stmt(
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.9),
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.9),
    )
    number_occurrences(st)
    ingest(st, source="csv")

    assert sum(1 for r in order_rows() if r.superseded_by is not None) == 1
    survivor_id = next(r.id for r in order_rows() if r.superseded_by is None)

    st2 = stmt(
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.9),
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.9),
    )
    number_occurrences(st2)
    ingest(st2, source="csv")

    assert sum(1 for r in order_rows() if r.superseded_by is not None) == 1
    assert next(r for r in order_rows() if r.id == survivor_id).superseded_by is None


def test_two_identical_csv_orders_both_survive(db) -> None:
    from src.ledger.activity_csv import number_occurrences
    from src.ledger.ingest import ingest

    st = stmt(
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.9),
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.9),
    )
    number_occurrences(st)
    assert ingest(st, source="csv").counts["new"] == 2
    assert all(x.superseded_by is None for x in _rows(db))


def test_flex_order_row_twin_of_csv_row_is_superseded(db) -> None:
    from src.ledger.ingest import ingest

    ingest(
        stmt(ex("AMZN 18JUL25 207.5 P", "2025-07-18, 16:20:00", 1, 0.0, codes="C;Ep")), source="csv"
    )
    ingest(
        stmt(ex("AMZN 18JUL25 207.5 P", "2025-07-18, 16:20:02", 1, 0.0, codes="C;Ep")),
        source="flex",
    )
    rows = _rows(db)
    assert rows[0].superseded_by is None and rows[1].superseded_by == rows[0].id


def test_overnight_sgx_live_fill_twins_its_csv_row(db) -> None:
    # Review Focus 4: 03:30 UTC Nov 3 == 22:30 ET Nov 2.
    from src.ledger.ingest import ingest

    ingest(stmt(ex("A17U", "2025-11-02, 22:30:00", 500, 2.77, currency="SGD")), source="csv")
    ingest(
        stmt(
            ex(
                "A17U",
                "",
                500,
                2.77,
                exec_id="x1",
                perm=5,
                currency="SGD",
                utc=datetime(2025, 11, 3, 3, 30, tzinfo=UTC),
            )
        ),
        source="live",
    )
    rows = _rows(db)
    assert {r.trade_date.isoformat() for r in rows} == {"2025-11-02"}
    assert next(r for r in rows if r.source_kind == "order").superseded_by is not None


def test_parse_errors_fail_the_import_and_write_nothing(db) -> None:
    from src.ledger.ingest import ingest

    bad = parse_activity_csv(
        FIXTURE.read_text().replace('"2025-06-17, 10:02:11",-1,', '"2025-06-17, 10:02:11",abc,')
    )
    r = ingest(bad, source="csv")
    assert (r.status, r.reason) == ("failed", "parse_errors")
    assert _rows(db) == []


def test_first_import_locks_the_account_and_a_mismatch_is_refused(db) -> None:
    from src.ledger.ingest import ingest
    from src.ledger.state import ledger_account

    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0)), source="csv")
    with db() as s:
        assert ledger_account(s) == "U0000001"
    r = ingest(
        stmt(ex("NVDA", "2025-07-15, 10:00:00", 1, 100.0, account="DU999"), account="DU999"),
        source="csv",
    )
    assert (r.status, r.reason) == ("failed", "account_mismatch")


def test_live_account_mismatch_is_skipped_with_no_run_row(db) -> None:
    # Review round 1 finding 1: a live fill from a foreign (e.g. paper) account must leave no
    # trace at all once the real account is locked in — not even a failed run row.
    from src.ledger.ingest import ingest
    from src.storage.models import LedgerImportRunRow

    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0)), source="csv")  # locks U0000001
    with db() as s:
        runs_before = s.scalar(select(func.count()).select_from(LedgerImportRunRow))
    rows_before = len(_rows(db))

    r = ingest(
        stmt(
            ex(
                "NVDA",
                "",
                1,
                100.0,
                exec_id="p1",
                account="DU999",
                utc=datetime(2025, 7, 15, 14, tzinfo=UTC),
            ),
            account="DU999",
        ),
        source="live",
    )

    assert (r.status, r.reason) == ("skipped", "account_mismatch")
    with db() as s:
        assert s.scalar(select(func.count()).select_from(LedgerImportRunRow)) == runs_before
    assert len(_rows(db)) == rows_before


def test_live_fills_never_set_the_account_lock(db) -> None:
    # Review Focus 3 (ingest side): a paper session running before the CSV import must not claim the ledger.
    from src.ledger.ingest import ingest
    from src.storage.models import LedgerImportRunRow

    r = ingest(
        stmt(
            ex(
                "NVDA",
                "",
                1,
                100.0,
                exec_id="p1",
                account="DU999",
                utc=datetime(2025, 7, 14, 14, tzinfo=UTC),
            ),
            account="DU999",
        ),
        source="live",
    )
    assert (r.status, r.reason) == ("skipped", "no_ledger_account")
    assert _rows(db) == []
    with db() as s:
        assert s.scalar(select(func.count()).select_from(LedgerImportRunRow)) == 0


def test_system_book_tagging(db) -> None:
    from src.ledger.ingest import ingest
    from src.storage.models import OrderRow

    with db() as s:
        s.add(OrderRow(candidate_id="c1", ib_order_id=55, snapshot={"underlying": "NVDA"}))
    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0)), source="csv")  # locks the account
    ingest(
        stmt(
            ex(
                "NVDA 18JUL25 170 P",
                "",
                -1,
                1.9,
                exec_id="s1",
                perm=9,
                order_id=55,
                utc=datetime(2025, 7, 15, 14, tzinfo=UTC),
            )
        ),
        source="live",
    )
    live = next(r for r in _rows(db) if r.exec_id == "s1")
    assert live.book == "system"


def test_book_tagged_when_ib_order_id_is_backfilled_on_a_duplicate(db) -> None:
    # F17: a Flex-first row (no ib_order_id) later duplicated by a live fill carrying
    # ib_order_id must become book "system", even though the stored row isn't "inserted this run".
    from src.ledger.ingest import ingest
    from src.storage.models import OrderRow

    with db() as s:
        s.add(OrderRow(candidate_id="c2", ib_order_id=77, snapshot=None))
    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0)), source="csv")  # locks the account
    ingest(
        stmt(ex("NVDA 18JUL25 170 P", "2025-07-15, 10:00:00", -1, 1.9, exec_id="s2", perm=9)),
        source="flex",
    )
    row = next(r for r in _rows(db) if r.exec_id == "s2")
    assert row.ib_order_id is None and row.book == "manual"

    ingest(
        stmt(
            ex(
                "NVDA 18JUL25 170 P",
                "2025-07-15, 10:00:00",
                -1,
                1.9,
                exec_id="s2",
                perm=9,
                order_id=77,
            )
        ),
        source="live",
    )
    row = next(r for r in _rows(db) if r.exec_id == "s2")
    assert row.ib_order_id == 77
    assert row.book == "system"


def test_commission_backfilled_on_duplicate(db) -> None:
    from src.ledger.ingest import ingest

    ingest(
        stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0, exec_id="e9", comm=0.0)), source="flex"
    )
    ingest(
        stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0, exec_id="e9", comm=-1.05)), source="flex"
    )
    assert _rows(db)[0].commission == pytest.approx(-1.05)


def test_generation_bumps_only_on_change(db) -> None:
    from src.ledger.ingest import ingest
    from src.ledger.state import LEDGER_GENERATION_KEY, read_int_setting

    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0)), source="csv")
    g1 = read_int_setting(LEDGER_GENERATION_KEY)
    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0)), source="csv")
    assert g1 == 1 and read_int_setting(LEDGER_GENERATION_KEY) == 1


def test_generation_bumps_on_a_backfill_with_no_new_rows(db) -> None:
    # Review round 1 finding 3: a commission backfill on an existing row changes what the
    # Sheets mirror shows, so it must bump the generation even though nothing was inserted.
    from src.ledger.ingest import ingest
    from src.ledger.state import LEDGER_GENERATION_KEY, read_int_setting

    ingest(
        stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0, exec_id="e9", comm=0.0)), source="flex"
    )
    g1 = read_int_setting(LEDGER_GENERATION_KEY)
    ingest(
        stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0, exec_id="e9", comm=-1.05)), source="flex"
    )
    assert read_int_setting(LEDGER_GENERATION_KEY) == g1 + 1


def test_live_noop_ingest_leaves_no_run_row(db) -> None:
    # F20: a source="live" ingest that inserts or changes nothing leaves no run row behind;
    # one that does insert (or changes a stored row) keeps its run row.
    from src.ledger.ingest import ingest
    from src.storage.models import LedgerImportRunRow

    ingest(
        stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0)), source="csv"
    )  # locks the account, 1 run row

    e1 = ex(
        "NVDA 18JUL25 170 P",
        "",
        -1,
        1.9,
        exec_id="s1",
        perm=9,
        utc=datetime(2025, 7, 15, 14, tzinfo=UTC),
    )
    first = ingest(stmt(e1), source="live")
    assert first.status == "ok" and first.run_id is not None and first.counts["new"] == 1

    second = ingest(stmt(e1), source="live")  # exact duplicate: no insert, no backfill, no tag
    assert second.status == "ok" and second.run_id is None
    assert second.counts.get("new", 0) == 0 and second.counts["duplicate"] == 1

    with db() as s:
        assert s.scalar(select(func.count()).select_from(LedgerImportRunRow)) == 2


def test_cli_dry_run_writes_nothing_and_real_run_imports(db, capsys) -> None:
    from scripts.ledger_import import main

    assert main([str(FIXTURE), "--dry-run"]) == 0
    assert _rows(db) == []
    assert main([str(FIXTURE)]) == 0
    assert len(_rows(db)) == 15
    assert '"status": "ok"' in capsys.readouterr().out


def test_exec_duplicate_backfills_codes_so_a_live_close_stays_an_orphan(db) -> None:
    """M1: live fill lands first with no codes; the Flex row for the same execId carries ``C``.
    The duplicate must backfill the codes, or the close would be read as a fake long."""
    from src.ledger.ingest import ingest

    close = "AMZN 10OCT25 215 P"
    live = ex(close, "2025-10-03, 14:45:08", 1, 0.5, exec_id="X1", perm=9, codes="")
    flex = ex(close, "2025-10-03, 14:45:08", 1, 0.5, exec_id="X1", perm=9, codes="C")
    ingest(stmt(live), source="live")
    ingest(stmt(flex), source="flex", filename="flex:q")
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0].codes == "C"
    # a stored code is never overwritten by a later, different one
    ingest(
        stmt(ex(close, "2025-10-03, 14:45:08", 1, 0.5, exec_id="X1", perm=9, codes="O")),
        source="flex",
        filename="flex:q2",
    )
    assert _rows(db)[0].codes == "C"
