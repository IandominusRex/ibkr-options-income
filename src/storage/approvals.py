"""Sweep pending approval cards past their TTL to ``expired`` (R6).

Before this module, the only code path that ever transitioned a ``pending``
:class:`~src.storage.models.ApprovalRow` to ``expired`` was
``src.execution.approval.process_queued_orders`` — and that path only reaches an approval
*after* it has been tapped "Approve" and turned into a queued ``OrderRow``. A card the
operator never acted on (no tap, so no queued order) had no expiry path at all: it sat
``pending`` in the DB forever, long after its own ``expires_at`` had passed. The 2026-09-29
scan-loop post-mortem found 33 such rows (root cause R6, see
``docs/superpowers/plans/2026-09-29-scan-loop-remediation.md``).

``expire_stale_approvals`` closes that gap with one cheap sweep: every ``pending`` row whose
``expires_at`` has passed — or, for a legacy row with no ``expires_at`` at all, whose
``created_at`` is older than ``config/settings.yaml``'s ``approval.ttl_minutes`` — is flipped
to ``expired`` in a single UPDATE. It is called at the top of every
``_order_poll_loop`` iteration in ``src.notify.approval_service`` (so the sweep runs on the
same cadence as order processing, cheaply, regardless of whether the exec IBKR connection is
healthy) and is reused by the ``/expire`` command so there is exactly one implementation of
"flip a stale pending row" in the codebase. It never touches ``approved`` rows: those remain
exclusively ``process_queued_orders``' concern.

Datetime convention: ``ApprovalRow.expires_at``/``decided_at``/``created_at`` are naive
``DateTime`` columns. SQLite's DateTime bind/result processors copy an inbound datetime's wall-
clock components verbatim and ignore ``tzinfo`` entirely, so a value written as
``datetime.now(UTC)`` (aware) round-trips as a naive datetime whose components are UTC (see
``src/execution/approval.py``'s ``_aware`` helper for the read-side counterpart of the same
convention). Comparing an aware `now` straight against that naive column would only work by
accident when the aware value happens to already be UTC; a `now` in any other zone would
compare the wrong wall clock and silently under- or over-expire. ``_to_naive_utc`` normalises
any aware `now` to that same naive-UTC convention before it is used, so the comparison and the
``decided_at`` stamp both line up with what's actually stored.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, update

from src.common.config import get_config
from src.common.schemas import ApprovalStatus
from src.storage.db import session_scope
from src.storage.models import ApprovalRow

logger = logging.getLogger(__name__)


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalise *dt* to the naive-UTC convention ``ApprovalRow``'s DateTime columns store.

    An aware datetime is converted to true UTC and then has its tzinfo stripped; a naive
    datetime is assumed to already be UTC (the codebase-wide convention) and is returned as-is.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def expire_stale_approvals(now: datetime | None = None) -> int:
    """Flip ``pending`` approvals past their TTL to ``expired``. Returns the count flipped.

    A row is stale when either:
      * ``expires_at`` is set and is before *now*, or
      * ``expires_at`` is ``NULL`` (a legacy row predating the TTL column) and ``created_at``
        is older than ``approval.ttl_minutes``.

    Every flipped row also gets ``decided_at=now`` — the point in time the sweep decided the
    card was no longer actionable. ``now`` defaults to the real current time; pass an explicit
    value in tests. Never touches ``approved`` rows — see module docstring.
    """
    naive_now = _to_naive_utc(now if now is not None else datetime.now(UTC))
    ttl_minutes = get_config().approval.ttl_minutes
    null_expiry_cutoff = naive_now - timedelta(minutes=ttl_minutes)

    with session_scope() as session:
        result = session.execute(
            update(ApprovalRow)
            .where(ApprovalRow.status == ApprovalStatus.PENDING)
            .where(
                or_(
                    ApprovalRow.expires_at < naive_now,
                    and_(
                        ApprovalRow.expires_at.is_(None),
                        ApprovalRow.created_at < null_expiry_cutoff,
                    ),
                )
            )
            .values(status=ApprovalStatus.EXPIRED, decided_at=naive_now)
        )
        # rowcount is a CursorResult attribute; mypy only sees the ORM-wrapped result.
        count = getattr(result, "rowcount", 0) or 0

    if count:
        logger.info("expire_stale_approvals: flipped %d pending approval(s) to expired", count)
    return count
