"""Google Sheet mirror: three (auto) tabs, full rewrite, generation-driven (spec §7)."""

from __future__ import annotations

import asyncio
from pathlib import Path

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


def test_loop_exits_quietly_when_unconfigured(monkeypatch) -> None:
    from src.common.config import get_config
    from src.ledger.sheets_mirror import mirror_configured, sheets_mirror_loop

    monkeypatch.setattr(get_config().secrets, "google_sheets_credentials_path", "")
    assert mirror_configured() is False
    asyncio.run(asyncio.wait_for(sheets_mirror_loop(poll_seconds=0.01), timeout=1))


def test_approval_service_wires_the_mirror() -> None:
    assert "sheets_mirror_loop()" in Path("src/notify/approval_service.py").read_text()
