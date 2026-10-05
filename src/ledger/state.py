"""Ledger-wide ``system_settings`` keys: the change generation the Sheets mirror follows, the
locked account (R8), and feed status the import page reads."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.storage.models import SystemSettingRow
from src.storage.system_settings import get_setting, set_setting

LEDGER_GENERATION_KEY = "ledger_generation"
LEDGER_SYNCED_GENERATION_KEY = "ledger_sheets_synced_generation"
LEDGER_SHEETS_LAST_SYNC_KEY = "ledger_sheets_last_sync"
LEDGER_SHEETS_LAST_ERROR_KEY = "ledger_sheets_last_error"
LEDGER_ACCOUNT_KEY = "ledger_account"
LEDGER_FLEX_LAST_RUN_KEY = "ledger_flex_last_run"
LEDGER_FLEX_LAST_STATUS_KEY = "ledger_flex_last_status"


def _session_value(session: Session, key: str) -> str | None:
    row = session.scalar(select(SystemSettingRow).where(SystemSettingRow.key == key))
    return row.value if row is not None else None


def bump_generation(session: Session) -> None:
    """Mark the ledger changed, inside the caller's transaction."""
    current = _session_value(session, LEDGER_GENERATION_KEY) or "0"
    nxt = int(current) + 1 if current.isdigit() else 1
    set_setting(LEDGER_GENERATION_KEY, str(nxt), session=session)


def read_int_setting(key: str) -> int:
    value = get_setting(key, "0")
    return int(value) if value.isdigit() else 0


def ledger_account(session: Session) -> str | None:
    """The account the ledger tracks: ``ledger.account`` if set, else the locked one, else None."""
    configured = get_config().ledger.account.strip()
    if configured:
        return configured
    locked = (_session_value(session, LEDGER_ACCOUNT_KEY) or "").strip()
    return locked or None


def lock_account(session: Session, account: str) -> None:
    set_setting(LEDGER_ACCOUNT_KEY, account.strip(), session=session)
