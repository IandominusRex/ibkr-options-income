"""Google Sheet mirror: three (auto) tabs, full rewrite, generation-driven (spec §7)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"


class FakeWriter:
    def __init__(self, fail: bool = False) -> None:
        self.tabs: dict[str, list[list[object]]] = {}
        self.fail = fail

    def write_tab(self, title, rows, *, outcome_column=None) -> None:
        if self.fail:
            raise RuntimeError("quota exceeded")
        self.tabs[title] = rows


def _seed():
    from src.ledger.activity_csv import parse_activity_csv
    from src.ledger.ingest import ingest

    ingest(parse_activity_csv(FIXTURE.read_text()), source="csv")


def test_sync_writes_three_tabs_in_sheet_layout(db) -> None:
    from src.ledger.sheets_mirror import LEDGER_TAB, SUMMARY_TAB, TICKERS_TAB, sync_if_due

    _seed()
    w = FakeWriter()
    assert sync_if_due(writer_factory=lambda: w) is True
    assert set(w.tabs) == {LEDGER_TAB, TICKERS_TAB, SUMMARY_TAB}
    assert w.tabs[LEDGER_TAB][0][:3] == ["Sell/Buy", "Put/Call", "Order Date"]
    assert len(w.tabs[LEDGER_TAB]) == 1 + 6


def test_nothing_to_do_when_generation_unchanged(db) -> None:
    from src.ledger.sheets_mirror import sync_if_due

    _seed()
    w = FakeWriter()
    assert sync_if_due(writer_factory=lambda: w) is True
    w.tabs.clear()
    assert sync_if_due(writer_factory=lambda: w) is False and w.tabs == {}


def test_failure_records_the_error_and_retries_later(db) -> None:
    from src.ledger.sheets_mirror import sync_if_due
    from src.ledger.state import (
        LEDGER_SHEETS_LAST_ERROR_KEY,
        LEDGER_SYNCED_GENERATION_KEY,
        read_int_setting,
    )
    from src.storage.system_settings import get_setting

    _seed()
    assert sync_if_due(writer_factory=lambda: FakeWriter(fail=True)) is False
    assert "quota exceeded" in get_setting(LEDGER_SHEETS_LAST_ERROR_KEY)
    assert read_int_setting(LEDGER_SYNCED_GENERATION_KEY) == 0
    assert sync_if_due(writer_factory=lambda: FakeWriter()) is True
    assert get_setting(LEDGER_SHEETS_LAST_ERROR_KEY) == ""


def test_errors_never_leak_the_sheet_id_or_credentials_path(db, monkeypatch, caplog) -> None:
    """A ConnectionError embeds the Sheets URL (.../v4/spreadsheets/<id>) and a FileNotFoundError
    embeds the credentials path verbatim — neither secret may reach the stored setting the web
    layer displays, or the log (review round 1, finding 1)."""
    from src.common.config import get_config
    from src.ledger.sheets_mirror import sync_if_due
    from src.ledger.state import LEDGER_SHEETS_LAST_ERROR_KEY
    from src.storage.system_settings import get_setting

    secret_sheet_id = "SECRET_SHEET_abc123"
    secret_creds_path = "/Users/ian/.secret/google-creds.json"
    monkeypatch.setattr(get_config().secrets, "ledger_sheet_id", secret_sheet_id)
    monkeypatch.setattr(get_config().secrets, "google_sheets_credentials_path", secret_creds_path)

    class LeakyWriter:
        def write_tab(self, title, rows, *, outcome_column=None) -> None:
            raise ConnectionError(
                f"POST https://sheets.googleapis.com/v4/spreadsheets/{secret_sheet_id}/values "
                f"failed; credentials file {secret_creds_path} could not be read"
            )

    _seed()
    with caplog.at_level(logging.WARNING, logger="src.ledger.sheets_mirror"):
        assert sync_if_due(writer_factory=lambda: LeakyWriter()) is False

    stored = get_setting(LEDGER_SHEETS_LAST_ERROR_KEY)
    assert secret_sheet_id not in stored
    assert secret_creds_path not in stored
    assert "<sheet>" in stored
    assert "<credentials>" in stored

    assert secret_sheet_id not in caplog.text
    assert secret_creds_path not in caplog.text


def test_loop_exits_quietly_when_unconfigured(monkeypatch) -> None:
    from src.common.config import get_config
    from src.ledger.sheets_mirror import mirror_configured, sheets_mirror_loop

    monkeypatch.setattr(get_config().secrets, "google_sheets_credentials_path", "")
    assert mirror_configured() is False
    asyncio.run(asyncio.wait_for(sheets_mirror_loop(poll_seconds=0.01), timeout=1))


async def test_loop_survives_a_cycle_exception_and_cancellation_still_propagates(
    monkeypatch,
) -> None:
    """The controller-mandated guard (review round 1, finding 2): one cycle raising must not
    kill the loop — the next cycle must still run — and ``task.cancel()`` must still surface as
    ``CancelledError`` through the awaited task, so ``approval_service``'s shutdown ``finally``
    can always cancel-and-await it cleanly."""
    import src.ledger.sheets_mirror as mirror

    monkeypatch.setattr(mirror, "mirror_configured", lambda: True)

    calls: list[str] = []

    def flaky_read_int_setting(key: str) -> int:
        calls.append(key)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return 0

    monkeypatch.setattr(mirror, "read_int_setting", flaky_read_int_setting)

    task = asyncio.create_task(mirror.sheets_mirror_loop(poll_seconds=0.0))
    try:
        async with asyncio.timeout(2):
            while len(calls) < 2:
                await asyncio.sleep(0)
        # The first call raised inside the loop's try/except guard; a second call happening at
        # all proves the loop kept cycling instead of dying with that exception.
        assert len(calls) >= 2
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_approval_service_wires_the_mirror() -> None:
    assert "sheets_mirror_loop()" in Path("src/notify/approval_service.py").read_text()


def test_gid_mode_writes_only_the_mapped_tabs(db, monkeypatch) -> None:
    """With ledger.sheets_tabs set, the mirror writes into those gids and nothing else: no
    "(auto)" titles, and an unmapped role (credit spreads, say) is never touched."""
    from src.common.config import get_config
    from src.ledger.sheets_mirror import sync_if_due

    monkeypatch.setattr(
        get_config().ledger,
        "sheets_tabs",
        {"summary": 0, "buy_and_hold": 525, "options": 1142, "tickers": 595},
    )
    _seed()
    w = FakeWriter()
    assert sync_if_due(writer_factory=lambda: w) is True
    assert set(w.tabs) == {0, 525, 1142, 595}
    assert w.tabs[1142][0][:3] == ["Sell/Buy", "Put/Call", "Order Date"]
    assert w.tabs[525][0][:3] == ["Ticker", "Currency", "Shares"]
    assert w.tabs[595][0][0] == "Ticker"
    assert w.tabs[0][-1][0] == "Updated (UTC)"


def test_gid_mode_skips_roles_left_out(db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.ledger.sheets_mirror import sync_if_due

    monkeypatch.setattr(get_config().ledger, "sheets_tabs", {"options": 1142})
    _seed()
    w = FakeWriter()
    assert sync_if_due(writer_factory=lambda: w) is True
    assert set(w.tabs) == {1142}


def test_sheets_tabs_rejects_unknown_roles_and_duplicate_gids() -> None:
    from pydantic import ValidationError

    from src.common.config import LedgerCfg

    with pytest.raises(ValidationError, match="unknown"):
        LedgerCfg(sheets_tabs={"credit_spreads": 5})
    with pytest.raises(ValidationError, match="distinct"):
        LedgerCfg(sheets_tabs={"options": 5, "tickers": 5})


def test_buy_hold_rows_aggregate_open_lots_in_native_currency() -> None:
    from datetime import date
    from types import SimpleNamespace

    from src.common.schemas import LedgerStockLot
    from src.reporting.trade_ledger import BUY_HOLD_HEADER, buy_hold_rows

    def lot(sym, ccy, d, src, rem, cost):
        return LedgerStockLot(
            lot_key=f"{sym}{d}{src}",
            underlying=sym,
            currency=ccy,
            acquired_date=d,
            source=src,
            quantity=rem,
            remaining=rem,
            cost_per_share=cost,
        )

    book = SimpleNamespace(
        tickers=[],
        lots=[
            lot("QQQM", "USD", date(2026, 3, 1), "bought", 10, 200.0),
            lot("QQQM", "USD", date(2026, 5, 1), "assigned", 30, 220.0),
            lot("D05", "SGD", date(2026, 4, 1), "bought", 100, 40.0),
            lot("CSPX", "USD", date(2026, 1, 1), "bought", 0, 600.0),  # fully sold: excluded
        ],
    )
    rows = buy_hold_rows(book)  # type: ignore[arg-type]
    assert rows[0] == BUY_HOLD_HEADER
    assert [r[0] for r in rows[1:]] == ["D05", "QQQM"]
    d05, qqqm = rows[1], rows[2]
    assert d05[1] == "SGD" and d05[2] == 100 and d05[3] == 40.0
    assert qqqm[2] == 40 and qqqm[3] == 215.0 and qqqm[4] == 8600.0 and qqqm[5] == 2
    assert qqqm[6] == "2026-03-01" and qqqm[7] == "assigned 30, bought 10"
