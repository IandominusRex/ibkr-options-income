"""Tests for src.storage.approvals — the R6 stale-approval sweep.

`expire_stale_approvals` is the only code path (besides `process_queued_orders`, which is
scoped to already-approved/queued rows) that ever flips a `pending` ApprovalRow to `expired`.
These tests cover: the brief's own scenario, the NULL-`expires_at` TTL fallback, that
`decided_at` is stamped correctly, and — per the task-8 ruling — that an aware `now` in a
non-UTC zone is normalised before it is compared against the naive-UTC `expires_at` column
(SQLite's DateTime bind/result processors copy wall-clock components verbatim and ignore
tzinfo, so an un-normalised comparison would silently use the wrong wall clock).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def test_expire_stale_approvals_only_touches_pending_past_ttl(db):
    from src.storage.approvals import expire_stale_approvals
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow

    now = datetime(2026, 9, 29, tzinfo=UTC)
    with session_scope() as s:
        s.add_all(
            [
                ApprovalRow(
                    candidate_id="a", status="pending", expires_at=now - timedelta(minutes=1)
                ),
                ApprovalRow(
                    candidate_id="b", status="pending", expires_at=now + timedelta(minutes=30)
                ),
                ApprovalRow(
                    candidate_id="c", status="approved", expires_at=now - timedelta(days=1)
                ),
            ]
        )
    assert expire_stale_approvals(now) == 1
    with session_scope() as s:
        by = {r.candidate_id: r.status for r in s.query(ApprovalRow)}
    assert by == {"a": "expired", "b": "pending", "c": "approved"}


def test_expire_stale_approvals_sets_decided_at(db):
    """`decided_at` is stamped with the normalised (naive-UTC) `now` on every flipped row."""
    from src.storage.approvals import expire_stale_approvals
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow

    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    with session_scope() as s:
        s.add(
            ApprovalRow(candidate_id="a", status="pending", expires_at=now - timedelta(minutes=1))
        )

    assert expire_stale_approvals(now) == 1

    with session_scope() as s:
        row = s.query(ApprovalRow).filter_by(candidate_id="a").one()
        # SQLite DateTime strips tzinfo on read-back; the codebase convention is naive-UTC.
        assert row.decided_at == datetime(2026, 9, 29, 12, 0)


def test_expire_stale_approvals_flips_null_expiry_past_ttl(db):
    """A row with no `expires_at` falls back to `created_at` older than `approval.ttl_minutes`."""
    from src.common.config import get_config
    from src.storage.approvals import expire_stale_approvals
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow

    ttl = get_config().approval.ttl_minutes
    now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    with session_scope() as s:
        s.add_all(
            [
                ApprovalRow(
                    candidate_id="stale-null",
                    status="pending",
                    expires_at=None,
                    created_at=now - timedelta(minutes=ttl + 1),
                ),
                ApprovalRow(
                    candidate_id="fresh-null",
                    status="pending",
                    expires_at=None,
                    created_at=now - timedelta(minutes=1),
                ),
            ]
        )

    assert expire_stale_approvals(now) == 1

    with session_scope() as s:
        by = {r.candidate_id: r.status for r in s.query(ApprovalRow)}
    assert by == {"stale-null": "expired", "fresh-null": "pending"}


def test_expire_stale_approvals_normalises_non_utc_aware_now(db):
    """A `now` expressed in a non-UTC zone must still compare correctly against the stored
    naive-UTC `expires_at` — guards the tz mismatch a raw component-copy bind would hide."""
    from src.storage.approvals import expire_stale_approvals
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow

    utc_now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    with session_scope() as s:
        s.add(
            ApprovalRow(
                candidate_id="x", status="pending", expires_at=utc_now - timedelta(minutes=1)
            )
        )

    # Same instant as utc_now, expressed as 08:00 EDT — a naive component-copy bind (ignoring
    # tzinfo) would compare "08:00" against the stored "11:59" and wrongly conclude not-expired.
    eastern_now = utc_now.astimezone(ZoneInfo("America/New_York"))
    assert expire_stale_approvals(eastern_now) == 1


def test_expire_stale_approvals_default_now_is_current_time(db):
    """No `now` argument uses the real current time — a freshly-created card is left alone."""
    from src.storage.approvals import expire_stale_approvals
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow

    with session_scope() as s:
        s.add(
            ApprovalRow(
                candidate_id="live",
                status="pending",
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
        )

    assert expire_stale_approvals() == 0
