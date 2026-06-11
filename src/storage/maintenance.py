"""Periodic DB maintenance: prune write-only audit tables so SQLite doesn't grow forever.

`option_quotes` is written once per symbol per scan as an audit trail and never read by
production code. In the 15-minute automated loop that is tens of thousands of rows a week.
:func:`purge_old_option_quotes` is invoked from the EOD run to keep a bounded window.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from src.storage.db import session_scope
from src.storage.models import OptionQuoteRow

log = logging.getLogger(__name__)

_DEFAULT_RETENTION_DAYS = 14


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
