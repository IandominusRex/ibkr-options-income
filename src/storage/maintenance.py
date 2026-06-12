"""Periodic DB maintenance: prune write-only audit tables and back up the system of record.

`option_quotes` is written once per symbol per scan as an audit trail and never read by
production code. In the 15-minute automated loop that is tens of thousands of rows a week.
:func:`purge_old_option_quotes` is invoked from the EOD run to keep a bounded window.

`data/income_system.db` is the system of record — orders, fills, and the entire labeled
learning history. :func:`backup_database` (SYSTEM_REVIEW Phase 2) takes a consistent online
snapshot via SQLite's backup API in the EOD run and rotates to a bounded window so a single
corrupted file or fat-fingered delete can't lose everything.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.common.config import get_config
from src.storage.db import session_scope
from src.storage.models import OptionQuoteRow

log = logging.getLogger(__name__)

_DEFAULT_RETENTION_DAYS = 14
_DEFAULT_BACKUP_KEEP = 7


def _db_file_path() -> Path | None:
    """Resolve the absolute on-disk path of the SQLite DB, or None if not file-backed."""
    url = get_config().db_url_abs()
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    return Path(url[len(prefix) :])


def backup_database(keep: int = _DEFAULT_BACKUP_KEEP) -> Path | None:
    """Write a consistent snapshot of the SQLite DB to ``data/backups/`` and rotate.

    Uses SQLite's online backup API (safe to run while the DB is in use, including WAL mode).
    Keeps the most recent *keep* snapshots. Returns the backup path, or None on failure/no-op.
    """
    src = _db_file_path()
    if src is None or not src.exists():
        log.warning("DB backup skipped — no file-backed SQLite DB at %s", src)
        return None

    backup_dir = src.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    dest = backup_dir / f"{src.stem}_{stamp}.db"

    try:
        with sqlite3.connect(str(src)) as source, sqlite3.connect(str(dest)) as target:
            source.backup(target)
        log.info("DB backup written to %s", dest)
    except Exception:
        log.exception("DB backup failed")
        return None

    # Rotation: keep only the most recent `keep` snapshots.
    try:
        snapshots = sorted(backup_dir.glob(f"{src.stem}_*.db"))
        for stale in snapshots[:-keep] if keep > 0 else []:
            stale.unlink(missing_ok=True)
            log.info("Pruned old DB backup %s", stale.name)
    except Exception:
        log.exception("DB backup rotation failed")

    return dest


def purge_old_option_quotes(retention_days: int = _DEFAULT_RETENTION_DAYS) -> int:
    """Delete option_quotes rows older than *retention_days*. Returns the row count deleted."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    try:
        with session_scope() as s:
            deleted = (
                s.query(OptionQuoteRow)
                .filter(OptionQuoteRow.created_at < cutoff)
                .delete(synchronize_session=False)
            )
        if deleted:
            log.info("Pruned %d option_quotes row(s) older than %d days", deleted, retention_days)
        return int(deleted or 0)
    except Exception:
        log.exception("option_quotes purge failed")
        return 0
