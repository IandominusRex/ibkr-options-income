"""One-way mirror of the ledger into the operator's Google Sheet (spec §7).

Two modes, chosen by ``ledger.sheets_tabs`` in settings.yaml. With a role -> gid map it writes
into those existing tabs (options ledger, credit-spreads ledger, buy-and-hold holdings, tickers,
dashboard summary) and touches nothing else; with no map it creates and owns three "(auto)" tabs. Either way each tab is
a full rewrite each time, so corrections and outcome overrides always propagate, and a role (or
tab) not listed is never read or written. Driven by the ledger generation counter (src/ledger/state.py):
any ingest or annotation bumps it; the mirror syncs when it is ahead of the last synced value,
at most once per ``ledger.sheets_min_interval_seconds``. Failures are recorded and retried; they
never block ingestion. Unrealized P&L is deliberately not mirrored (no live marks here).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from src.common.config import get_config
from src.common.schemas import LedgerBook
from src.ledger.contracts import ET
from src.ledger.state import (
    LEDGER_GENERATION_KEY,
    LEDGER_SHEETS_LAST_ERROR_KEY,
    LEDGER_SHEETS_LAST_SYNC_KEY,
    LEDGER_SYNCED_GENERATION_KEY,
    read_int_setting,
)
from src.reporting.trade_ledger import (
    SHEET_HEADER,
    TICKER_HEADER,
    build_book,
    buy_hold_rows,
    sheet_row,
    summary_rows,
    ticker_row,
)
from src.storage.db import session_scope
from src.storage.system_settings import set_setting

log = logging.getLogger(__name__)

LEDGER_TAB = "Ledger (auto)"
TICKERS_TAB = "Tickers (auto)"
SUMMARY_TAB = "Summary (auto)"
_OUTCOME_COLUMN = SHEET_HEADER.index("Outcome")
_OUTCOME_COLOURS: dict[str, tuple[float, float, float]] = {
    "Expired": (0.85, 0.94, 0.83),
    "Bought back": (0.90, 0.95, 0.88),
    "Assigned": (0.96, 0.80, 0.80),
    "Called away": (1.00, 0.95, 0.80),
    "Rolled": (0.81, 0.89, 0.97),
    "Open": (0.93, 0.93, 0.93),
    "Pending": (0.93, 0.93, 0.93),
}


TabTarget = str | int  # a tab title (created if missing) or an existing tab's gid


class SheetsWriter(Protocol):
    def write_tab(
        self, target: TabTarget, rows: list[list[Any]], *, outcome_column: int | None = None
    ) -> None: ...


def _outcome_rules(sheet_id: int, column: int) -> list[dict[str, Any]]:
    return [
        {
            "addConditionalFormatRule": {
                "index": 0,
                "rule": {
                    "ranges": [
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "startColumnIndex": column,
                            "endColumnIndex": column + 1,
                        }
                    ],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": label}]},
                        "format": {"backgroundColor": {"red": r, "green": g, "blue": b}},
                    },
                },
            }
        }
        for label, (r, g, b) in _OUTCOME_COLOURS.items()
    ]


class GspreadWriter:
    """The real writer. Needs the spreadsheet shared with the service account's email."""

    def __init__(self, credentials_path: str, sheet_id: str) -> None:
        import gspread

        self._spreadsheet = gspread.service_account(filename=credentials_path).open_by_key(sheet_id)

    def _has_outcome_rules(self, sheet_id: int) -> bool:
        meta = self._spreadsheet.fetch_sheet_metadata()
        return any(
            sh["properties"]["sheetId"] == sheet_id and sh.get("conditionalFormats")
            for sh in meta["sheets"]
        )

    def write_tab(
        self, target: TabTarget, rows: list[list[Any]], *, outcome_column: int | None = None
    ) -> None:
        import gspread
        from gspread.utils import ValueInputOption

        width = max(len(r) for r in rows)
        if isinstance(target, int):
            # A gid names a tab the operator already made; never create one under their feet.
            ws = self._spreadsheet.get_worksheet_by_id(target)
            fresh = not self._has_outcome_rules(ws.id) if outcome_column is not None else False
        else:
            try:
                ws = self._spreadsheet.worksheet(target)
                fresh = False
            except gspread.WorksheetNotFound:
                ws = self._spreadsheet.add_worksheet(title=target, rows=len(rows) + 50, cols=width)
                fresh = True
        ws.clear()
        ws.resize(rows=len(rows) + 50, cols=max(width, ws.col_count))
        ws.update(values=rows, range_name="A1", value_input_option=ValueInputOption.user_entered)
        ws.freeze(rows=1)
        if fresh and outcome_column is not None:
            self._spreadsheet.batch_update({"requests": _outcome_rules(ws.id, outcome_column)})


def _scrub_secrets(message: str) -> str:
    """Redact the configured Sheet id / credentials path from an error message before it is
    logged or stored in ``LEDGER_SHEETS_LAST_ERROR_KEY`` (shown by the web layer).

    Both are secrets (``.env`` only) that can appear verbatim inside an exception's own
    message — a ``requests`` connection error embeds the Sheets API URL
    (``.../v4/spreadsheets/<LEDGER_SHEET_ID>``), and a missing-file error embeds
    ``GOOGLE_SHEETS_CREDENTIALS_PATH`` directly — so the exception text itself must be scrubbed,
    not just avoided by the code that raises it.
    """
    s = get_config().secrets
    for secret, placeholder in (
        (s.ledger_sheet_id, "<sheet>"),
        (s.google_sheets_credentials_path, "<credentials>"),
    ):
        if secret:
            message = message.replace(secret, placeholder)
    return message


def mirror_configured() -> bool:
    s = get_config().secrets
    return bool(s.google_sheets_credentials_path.strip() and s.ledger_sheet_id.strip())


def default_writer() -> SheetsWriter | None:
    if not mirror_configured():
        return None
    s = get_config().secrets
    return GspreadWriter(s.google_sheets_credentials_path, s.ledger_sheet_id)


def sync_once(writer: SheetsWriter, book: LedgerBook) -> None:
    tabs = get_config().ledger.sheets_tabs
    # A credit_spreads tab takes the spreads book's legs out of the options tab; unmapped, every
    # trade stays in options as before.
    split_spreads = "credit_spreads" in tabs
    ledger_rows: list[list[Any]] = [
        SHEET_HEADER,
        *(sheet_row(t) for t in book.trades if not (split_spreads and t.book == "spreads")),
    ]
    spreads_rows: list[list[Any]] = [
        SHEET_HEADER,
        *(sheet_row(t) for t in book.trades if t.book == "spreads"),
    ]
    ticker_rows: list[list[Any]] = [TICKER_HEADER, *(ticker_row(t) for t in book.tickers)]
    summary: list[list[Any]] = [
        *summary_rows(book.summary),
        ["Updated (UTC)", datetime.now(UTC).isoformat()],
    ]
    if not tabs:
        writer.write_tab(LEDGER_TAB, ledger_rows, outcome_column=_OUTCOME_COLUMN)
        writer.write_tab(TICKERS_TAB, ticker_rows)
        writer.write_tab(SUMMARY_TAB, summary)
        return
    if "options" in tabs:
        writer.write_tab(tabs["options"], ledger_rows, outcome_column=_OUTCOME_COLUMN)
    if split_spreads:
        writer.write_tab(tabs["credit_spreads"], spreads_rows, outcome_column=_OUTCOME_COLUMN)
    if "buy_and_hold" in tabs:
        writer.write_tab(tabs["buy_and_hold"], buy_hold_rows(book))
    if "tickers" in tabs:
        writer.write_tab(tabs["tickers"], ticker_rows)
    if "summary" in tabs:
        writer.write_tab(tabs["summary"], summary)


def sync_if_due(*, writer_factory: Callable[[], SheetsWriter | None] = default_writer) -> bool:
    """Sync when the ledger generation is ahead of the last synced one. Returns True on a write."""
    generation = read_int_setting(LEDGER_GENERATION_KEY)
    if generation <= read_int_setting(LEDGER_SYNCED_GENERATION_KEY):
        return False
    try:
        writer = writer_factory()
        if writer is None:
            return False
        with session_scope() as s:
            book = build_book(s, today=datetime.now(ET).date(), snapshot=None)
        sync_once(writer, book)
    except Exception as exc:
        scrubbed = _scrub_secrets(f"{type(exc).__name__}: {exc}")[:500]
        set_setting(LEDGER_SHEETS_LAST_ERROR_KEY, scrubbed)
        log.warning("Google Sheet mirror sync failed (retried on a timer): %s", scrubbed)
        return False
    set_setting(LEDGER_SYNCED_GENERATION_KEY, str(generation))
    set_setting(LEDGER_SHEETS_LAST_SYNC_KEY, datetime.now(UTC).isoformat())
    set_setting(LEDGER_SHEETS_LAST_ERROR_KEY, "")
    return True


async def sheets_mirror_loop(*, poll_seconds: float = 15.0) -> None:
    """Poll the ledger generation counter and mirror to the sheet when it's ahead.

    Mirrors ``live_sweep_loop`` (src/ledger/live.py): a failure anywhere in one cycle's body is
    logged and the loop continues — it must never die, and the ``approval_service`` shutdown
    ``finally`` must always be able to cancel and await it cleanly.
    """
    if not mirror_configured():
        log.info(
            "Google Sheet mirror disabled (GOOGLE_SHEETS_CREDENTIALS_PATH / LEDGER_SHEET_ID not set)"
        )
        return
    min_interval = get_config().ledger.sheets_min_interval_seconds
    last_attempt = float("-inf")
    while True:
        await asyncio.sleep(poll_seconds)
        try:
            if time.monotonic() - last_attempt < min_interval:
                continue
            if read_int_setting(LEDGER_GENERATION_KEY) <= read_int_setting(
                LEDGER_SYNCED_GENERATION_KEY
            ):
                continue
            last_attempt = time.monotonic()
            await asyncio.to_thread(sync_if_due)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(
                "Google Sheet mirror cycle failed — will retry next cycle: %s",
                _scrub_secrets(f"{type(exc).__name__}: {exc}"),
            )
            continue
