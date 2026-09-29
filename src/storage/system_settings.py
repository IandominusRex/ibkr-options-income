"""Runtime key-value system settings backed by the SQLite system_settings table.

Usage:
    from src.storage.system_settings import get_autonomy_level, set_autonomy_level
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.common.schemas import AutonomyLevel
from src.storage.db import session_scope
from src.storage.models import SystemSettingRow

log = logging.getLogger(__name__)

AUTONOMY_LEVEL_KEY = "autonomy_level"
AUTONOMY_WHITELIST_KEY = "autonomy_whitelist"
HALT_KEY = "execution_halted"
HALT_REASON_KEY = "execution_halt_reason"
SCAN_LEASE_KEY = "scan_lease_expiry"
HIGH_WATER_MARK_KEY = "nlv_high_water_mark"
MONITOR_HEARTBEAT_KEY = "monitor_heartbeat"
MONITOR_IBKR_CONNECTED_KEY = "monitor_ibkr_connected"
COMMAND_DRAIN_IBKR_CONNECTED_KEY = "command_drain_ibkr_connected"
SCAN_COMPLETED_KEY = "intraday_scan_completed"
EOD_COMPLETED_KEY = "eod_completed"

# Sortable UTC timestamp (zero-padded) so lexicographic string comparison == chronological.
_LEASE_TS_FMT = "%Y%m%dT%H%M%S.%f"
_LEASE_EXPIRED = "0"  # sentinel < any real timestamp → lease is free
# The lease value is "<expiry-ts>|<owner-token>". The expiry prefix drives the atomic
# acquire (a free lease has an expiry in the past); the owner suffix is a stable per-holder
# token so renew/release are compare-and-swap — a process can only extend or clear a lease it
# still holds, never one another process has since claimed (N7). The owner stays constant
# across heartbeat renewals; only the expiry prefix advances.
_LEASE_SEP = "|"


def get_setting(key: str, default: str = "") -> str:
    try:
        with session_scope() as s:
            row = s.query(SystemSettingRow).filter_by(key=key).first()
            return row.value if row else default
    except Exception:
        log.warning("get_setting(%s) failed", key, exc_info=True)
        return default


def _write_setting(s: Session, key: str, value: str) -> None:
    row = s.query(SystemSettingRow).filter_by(key=key).first()
    if row:
        row.value = value
    else:
        s.add(SystemSettingRow(key=key, value=value))


def set_setting(key: str, value: str, *, session: Session | None = None) -> None:
    try:
        if session is not None:
            _write_setting(session, key, value)
        else:
            with session_scope() as s:
                _write_setting(s, key, value)
    except Exception:
        log.warning("set_setting(%s=%s) failed", key, value, exc_info=True)


def get_autonomy_level() -> AutonomyLevel:
    """Current autonomy rung. Defaults to OBSERVE — the safe rung for a fresh install."""
    raw = get_setting(AUTONOMY_LEVEL_KEY, AutonomyLevel.OBSERVE.value).lower()
    try:
        return AutonomyLevel(raw)
    except ValueError:
        log.warning("Unknown autonomy level %r — falling back to observe", raw)
        return AutonomyLevel.OBSERVE


def set_autonomy_level(level: AutonomyLevel) -> None:
    set_setting(AUTONOMY_LEVEL_KEY, level.value)


def _autonomy_whitelist() -> set[str]:
    raw = get_setting(AUTONOMY_WHITELIST_KEY, "")
    return {s.strip().upper() for s in raw.split(",") if s.strip()}


def set_autonomy_whitelist(symbols: set[str]) -> None:
    set_setting(AUTONOMY_WHITELIST_KEY, ",".join(sorted(symbols)))


def may_auto_open(symbol: str) -> bool:
    """True when the system may open new exposure in *symbol* without a human tap.

    The kill switch overrides every rung — closing risk stays permitted while halted, but
    opening it never is.
    """
    if is_halted():
        return False
    level = get_autonomy_level()
    if level in (AutonomyLevel.OBSERVE, AutonomyLevel.MANUAL):
        return False
    if level == AutonomyLevel.FULL:
        return True
    return symbol.upper() in _autonomy_whitelist()


_AUTONOMY_ORDER = [
    AutonomyLevel.OBSERVE,
    AutonomyLevel.MANUAL,
    AutonomyLevel.WHITELIST,
    AutonomyLevel.FULL,
]


def _evidence_counts() -> tuple[int, int, int]:
    """(fills, order attempts, risk-reducing closes) for the **current mode only**.

    Final review I1 (2026-09-30): ``FillRow`` and ``OrderRow`` both carry ``is_live``, and the
    counts are filtered to ``is_live == get_config().is_live``. Counting every row let a paper
    FULL run with >=20 *paper* fills satisfy ``enforce_live_autonomy_evidence()`` in live mode,
    so FULL carried into live trading on paper evidence alone. Paper history is never live
    evidence; live promotions need live fills. Raises on a DB error — callers decide.
    """
    from sqlalchemy import func, select

    from src.storage.models import FillRow, OrderRow

    live = bool(get_config().is_live)
    with session_scope() as s:
        fills = s.execute(
            select(func.count()).select_from(FillRow).where(FillRow.is_live.is_(live))
        ).scalar_one()
        attempts = s.execute(
            select(func.count()).select_from(OrderRow).where(OrderRow.is_live.is_(live))
        ).scalar_one()
        closes = s.execute(
            select(func.count())
            .select_from(OrderRow)
            .where(OrderRow.is_live.is_(live))
            .where(OrderRow.candidate_id.like("close:%"))
        ).scalar_one()
    return int(fills), int(attempts), int(closes)


def _evidence_blockers(target: AutonomyLevel) -> list[str]:
    """The >=20 fills / >=60% fill rate / >=1 close evidence check for *target*, independent of
    the current rung and of ``automation.paper_skip_promotion_gate``.

    Factored out of ``promotion_blockers`` (Task 12 fix round 1) so
    ``enforce_live_autonomy_evidence`` can ask "does the rung *currently stored* still hold up"
    — which needs the check even when ``target`` equals the current rung, a case
    ``promotion_blockers``'s own demotion/no-op early-return would otherwise short-circuit to
    ``[]`` without ever consulting the fill history.
    """
    blockers: list[str] = []
    try:
        fills, attempts, closes = _evidence_counts()
    except Exception:
        return ["could not read fill history"]

    if target in (AutonomyLevel.WHITELIST, AutonomyLevel.FULL):
        if fills < 20:
            blockers.append(f"needs >=20 fills, has {fills}")
        rate = (fills / attempts) if attempts else 0.0
        if rate < 0.60:
            blockers.append(f"fill rate {rate:.0%} is below the 60% gate")
        if closes < 1:
            blockers.append("no risk-reducing close has fired yet")
    return blockers


def promotion_blockers(target: AutonomyLevel) -> list[str]:
    """Unmet criteria for promoting to *target*. Empty list means promotion is allowed.

    Demotion is always permitted — reducing autonomy needs no evidence. Promotion up a rung
    requires demonstrated evidence: autonomy is arrived at, not switched on.
    """
    if _AUTONOMY_ORDER.index(target) <= _AUTONOMY_ORDER.index(get_autonomy_level()):
        return []

    cfg = get_config()
    if cfg.automation.paper_skip_promotion_gate:
        if cfg.is_live:
            log.warning(
                "automation.paper_skip_promotion_gate is set but LIVE_TRADING=true — ignored"
            )
        else:
            log.warning(
                "Promotion evidence gate SKIPPED (paper-only override) for %s", target.value
            )
            return []

    return _evidence_blockers(target)


def enforce_live_autonomy_evidence() -> AutonomyLevel | None:
    """Demote a stored rung that a live process cannot justify. Call once at the startup of any
    process that acts on the autonomy rung to auto-queue orders (``approval_service`` — before
    its intraday scan loop or order-poll loop starts), before either can run.

    Task 12's ``automation.paper_skip_promotion_gate`` lets a *paper* process promote straight to
    WHITELIST/FULL with no fill evidence. That flag is already ignored — with a warning — by
    ``promotion_blockers`` whenever ``Config.is_live`` is true, but the stored rung itself lives
    in the same ``system_settings`` table, in the same DB file, for both paper and live: nothing
    previously re-checked a rung *already reached* once a process starts in live mode, so
    flipping ``LIVE_TRADING=true`` while ``paper_skip_promotion_gate`` was later turned back off
    would carry a bypass-earned FULL straight into live trading with zero evidence. This closes
    that gap: a live process always re-validates its *current* stored rung against the real
    fill/fill-rate/close evidence (never the bypass — ``_evidence_blockers`` is called directly,
    not through ``promotion_blockers``), and demotes to MANUAL, persistently, if it doesn't hold.

    No-op (returns ``None``) in paper mode, when the stored rung is OBSERVE/MANUAL already (no
    evidence is required at or below MANUAL), or when the evidence does hold. Returns the OLD
    level when it demoted.
    """
    cfg = get_config()
    if not cfg.is_live:
        return None

    current = get_autonomy_level()
    if _AUTONOMY_ORDER.index(current) <= _AUTONOMY_ORDER.index(AutonomyLevel.MANUAL):
        return None

    blockers = _evidence_blockers(current)
    if not blockers:
        return None

    log.warning(
        "LIVE startup: stored autonomy rung %s has no evidence (%s) — demoting to MANUAL",
        current.value.upper(),
        "; ".join(blockers),
    )
    set_autonomy_level(AutonomyLevel.MANUAL)
    return current


def autonomy_progress() -> tuple[int, float, bool]:
    """(fills, fill_rate, has_closed_once) — the same current-mode evidence
    ``promotion_blockers`` checks (``_evidence_counts``), for display in the ``/autonomy``
    status text. Read-only; never used to gate anything itself.
    """
    try:
        fills, attempts, closes = _evidence_counts()
    except Exception:
        return (0, 0.0, False)
    rate = (fills / attempts) if attempts else 0.0
    return (fills, rate, closes >= 1)


def is_halted() -> bool:
    """Return True when the master execution kill switch is engaged.

    When halted, no order is queued or transmitted by either the order-poll loop or the
    intraday loop (manual approvals and auto-trades alike). Persisted so it survives a
    daemon restart — a halt must not silently clear itself. Toggled by `/halt` / `/resume`
    or auto-tripped by the circuit breakers (SYSTEM_REVIEW Phase 2).
    """
    return get_setting(HALT_KEY, "false").lower() == "true"


def set_halted(enabled: bool, reason: str = "") -> None:
    """Engage or release the kill switch, recording why it tripped."""
    set_setting(HALT_KEY, "true" if enabled else "false")
    set_setting(HALT_REASON_KEY, reason if enabled else "")


def get_halt_reason() -> str:
    """Human-readable reason the kill switch is engaged (empty when not halted)."""
    return get_setting(HALT_REASON_KEY, "")


def get_high_water_mark() -> float:
    """Highest net liquidation seen, used by the drawdown circuit breaker."""
    try:
        return float(get_setting(HIGH_WATER_MARK_KEY, "0") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def set_high_water_mark(value: float) -> None:
    set_setting(HIGH_WATER_MARK_KEY, f"{value:.2f}")


def _lease_value(expiry_str: str, owner: str) -> str:
    return f"{expiry_str}{_LEASE_SEP}{owner}"


def acquire_scan_lease(ttl_seconds: int = 600) -> str | None:
    """Try to claim the cross-process scan lease; return the owner token, or None if held.

    A full chain scan consumes most of the account-level ~100 market-data line cap. The
    daemon's in-process ``scan_running`` flag can't see a *separate* process (the morning
    cron vs. the 15-min daemon loop), so two could scan at once and poison each other
    (SYSTEM_REVIEW F5). This lease serialises scans across processes.

    Atomic in two ways: a conditional UPDATE only succeeds when the stored expiry is in the
    past (free lease), and the first-ever INSERT is guarded by the row's unique constraint.
    The returned token must be passed to ``renew_scan_lease`` / ``release_scan_lease`` so those
    are compare-and-swap (N7).
    """
    now = datetime.now(UTC)
    now_str = now.strftime(_LEASE_TS_FMT)
    owner = uuid.uuid4().hex
    new_value = _lease_value((now + timedelta(seconds=ttl_seconds)).strftime(_LEASE_TS_FMT), owner)
    try:
        with session_scope() as s:
            # Free/expired lease → claim it atomically (row-level conditional update). The
            # "<ts>|<owner>" value still sorts by its timestamp prefix vs the suffix-free now_str.
            updated = (
                s.query(SystemSettingRow)
                .filter(SystemSettingRow.key == SCAN_LEASE_KEY, SystemSettingRow.value < now_str)
                .update({SystemSettingRow.value: new_value}, synchronize_session=False)
            )
            if updated == 1:
                return owner
            # Row may not exist yet — first writer wins via the unique constraint.
            exists = s.query(SystemSettingRow).filter_by(key=SCAN_LEASE_KEY).first()
            if exists is None:
                try:
                    with s.begin_nested():
                        s.add(SystemSettingRow(key=SCAN_LEASE_KEY, value=new_value))
                    return owner
                except IntegrityError:
                    return None
            # Row exists and is unexpired → held by someone else.
            return None
    except Exception:
        log.warning("acquire_scan_lease failed", exc_info=True)
        return None


def renew_scan_lease(owner: str | None, ttl_seconds: int = 600) -> bool:
    """Extend the lease expiry, but only if *owner* still holds it (compare-and-swap).

    Called as a heartbeat inside the per-symbol scan loop so a long (~60-symbol) scan can't
    outlive a fixed TTL and let a second scan start mid-run (N7). Returns False if the lease
    was lost (expired and re-claimed by another process) — the caller can keep scanning, but
    its release will correctly no-op rather than clobber the new holder.
    """
    if not owner:
        return False
    suffix = f"{_LEASE_SEP}{owner}"
    new_value = _lease_value(
        (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).strftime(_LEASE_TS_FMT), owner
    )
    try:
        with session_scope() as s:
            row = s.query(SystemSettingRow).filter_by(key=SCAN_LEASE_KEY).first()
            if row is None or not row.value.endswith(suffix):
                return False
            row.value = new_value
            return True
    except Exception:
        log.warning("renew_scan_lease failed", exc_info=True)
        return False


def release_scan_lease(owner: str | None = None) -> None:
    """Release the scan lease — but only if *owner* still holds it (compare-and-swap, N7).

    Without the owner check a slow scan whose lease had already expired and been re-claimed
    would, on finishing, zero out the *new* holder's lease and let a third scan barge in. When
    ``owner`` is None the release is unconditional (legacy/forced reset)."""
    try:
        with session_scope() as s:
            row = s.query(SystemSettingRow).filter_by(key=SCAN_LEASE_KEY).first()
            if row is None:
                if owner is None:
                    s.add(SystemSettingRow(key=SCAN_LEASE_KEY, value=_LEASE_EXPIRED))
                return
            if owner is None or row.value.endswith(f"{_LEASE_SEP}{owner}"):
                row.value = _LEASE_EXPIRED
    except Exception:
        log.warning("release_scan_lease failed", exc_info=True)
