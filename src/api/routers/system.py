"""System status: per-subsystem health for the left-rail status card, plus a log tail
per daemon. Read-only, owner-only — the same sensitivity class as /options/controls,
since this surfaces internal operational detail (log lines, heartbeat ages) rather than
research data. See docs/superpowers/specs/2026-09-23-web-system-status-card-design.md.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query

from src.api.deps import OwnerUser, ResearchDb, TradingDb
from src.api.models.common import Envelope, as_utc_opt
from src.api.settings_read import parse_setting_dt, read_setting
from src.common.config import ROOT, get_config
from src.data.breaker import breaker_states
from src.research.ingest.jobs import read_heartbeat
from src.storage.system_settings import (
    COMMAND_DRAIN_IBKR_CONNECTED_KEY,
    MONITOR_HEARTBEAT_KEY,
    MONITOR_IBKR_CONNECTED_KEY,
)

router = APIRouter(prefix="/system", tags=["system"])

# See routers/options.py's own `_DRAIN_HEARTBEAT_KEY` — the API layer duplicates this one
# literal rather than importing the daemon module (src.notify.command_drain) that owns
# it, matching that existing precedent.
_DRAIN_HEARTBEAT_KEY = "command_drain_heartbeat"

State = Literal["ok", "degraded", "unknown", "down"]

# name -> real log file path (scripts/start.py's SERVICES dict). Fixed allowlist: a path
# is never built from the request. "api" is deliberately absent — no status row reads
# its own log (design doc §2).
_LOG_FILES: dict[str, Path] = {
    "approval": ROOT / "logs" / "approval.log",
    "monitor": ROOT / "logs" / "monitor.log",
    "research": ROOT / "logs" / "research.log",
}

_MAX_LOG_LINES = 150

# Matches src/common/logging.py's plain file formatter:
# "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s". \s* around the level name
# tolerates the -8s left-justify padding without hardcoding an exact width.
_LEVEL_PATTERN: dict[str, re.Pattern[str]] = {
    "warn": re.compile(r"\|\s*(WARNING|ERROR|CRITICAL)\s*\|"),
    "info": re.compile(r"\|\s*(INFO|WARNING|ERROR|CRITICAL)\s*\|"),
}

# 2x the fastest research-worker job's cadence (drain_ingest_jobs, a 30s IntervalTrigger
# in src/research/ingest/jobs.py) — the same "2x cadence" staleness rule /options/
# controls applies to the drain heartbeat, hand-derived since that 30s interval is a
# literal in jobs.py, not a config value.
_RESEARCH_WORKER_MAX_AGE = timedelta(minutes=2)


class SystemRow(Envelope):
    key: str
    label: str
    state: State
    detail: str
    log_key: str | None = None


class SystemStatusResponse(Envelope):
    rows: list[SystemRow]


class SystemLogResponse(Envelope):
    name: str
    level: Literal["warn", "info"]
    lines: list[str]


def _heartbeat_row(
    now: datetime,
    *,
    key: str,
    label: str,
    heartbeat: datetime | None,
    max_age: timedelta,
    log_key: str | None,
) -> SystemRow:
    if heartbeat is None:
        return SystemRow(
            as_of=now, key=key, label=label, state="unknown",
            detail="not yet reporting", log_key=log_key,
        )
    age = now - heartbeat
    if age <= max_age:
        return SystemRow(
            as_of=now, key=key, label=label, state="ok",
            detail=f"last heartbeat {int(age.total_seconds())}s ago", log_key=log_key,
        )
    return SystemRow(
        as_of=now, key=key, label=label, state="down",
        detail=f"last heartbeat {int(age.total_seconds())}s ago (stale)", log_key=log_key,
    )


def _worst(states: list[State]) -> State:
    rank = {"ok": 0, "degraded": 1, "unknown": 1, "down": 2}
    return max(states, key=lambda s: rank[s])


def _ibkr_leg(
    heartbeat: datetime | None, max_age: timedelta, connected_raw: str | None
) -> tuple[State, str]:
    if heartbeat is None:
        return "unknown", "not yet reporting"
    if datetime.now(UTC) - heartbeat > max_age:
        return "down", "heartbeat stale"
    if connected_raw == "true":
        return "ok", "connected"
    return "down", "disconnected"


@router.get("/status", response_model=SystemStatusResponse)
def system_status(
    _user: OwnerUser, trading_db: TradingDb, research_db: ResearchDb
) -> SystemStatusResponse:
    now = datetime.now(UTC)
    cfg = get_config()
    rows: list[SystemRow] = []

    try:
        trading_db.execute(sa.text("SELECT 1"))
        rows.append(
            SystemRow(as_of=now, key="trading_db", label="Trading DB", state="ok",
                       detail="reachable", log_key=None)
        )
    except Exception:
        rows.append(
            SystemRow(as_of=now, key="trading_db", label="Trading DB", state="down",
                       detail="unreachable", log_key=None)
        )

    try:
        research_db.execute(sa.text("SELECT 1"))
        rows.append(
            SystemRow(as_of=now, key="research_db", label="Research DB", state="ok",
                       detail="reachable", log_key=None)
        )
    except Exception:
        rows.append(
            SystemRow(as_of=now, key="research_db", label="Research DB", state="down",
                       detail="unreachable", log_key=None)
        )

    providers = breaker_states()
    provider_states: list[State] = []
    open_names: list[str] = []
    half_open_names: list[str] = []
    for name, state in providers.items():
        if state == "open":
            provider_states.append("down")
            open_names.append(name)
        elif state == "half_open":
            provider_states.append("degraded")
            half_open_names.append(name)
        else:
            provider_states.append("ok")
    if not provider_states:
        rows.append(
            SystemRow(as_of=now, key="data_providers", label="Data providers", state="ok",
                       detail="no providers registered", log_key=None)
        )
    else:
        worst = _worst(provider_states)
        if worst == "ok":
            detail = "no breakers tripped"
        elif open_names and half_open_names:
            detail = f"{', '.join(open_names)} open, {', '.join(half_open_names)} recovering"
        elif open_names:
            detail = f"{', '.join(open_names)} open"
        else:
            detail = f"{', '.join(half_open_names)} recovering"
        rows.append(
            SystemRow(as_of=now, key="data_providers", label="Data providers", state=worst,
                       detail=detail, log_key=None)
        )

    drain_hb = parse_setting_dt(read_setting(trading_db, _DRAIN_HEARTBEAT_KEY))
    drain_max_age = timedelta(seconds=cfg.execution.poll_interval_seconds * 2)
    rows.append(
        _heartbeat_row(now, key="command_drain", label="Command drain (approval_service)",
                        heartbeat=drain_hb, max_age=drain_max_age, log_key="approval")
    )

    monitor_hb = parse_setting_dt(read_setting(trading_db, MONITOR_HEARTBEAT_KEY))
    monitor_max_age = timedelta(seconds=cfg.scheduler.intraday_poll_seconds * 2)
    rows.append(
        _heartbeat_row(now, key="intraday_monitor", label="Intraday monitor",
                        heartbeat=monitor_hb, max_age=monitor_max_age, log_key="monitor")
    )

    worker_hb = as_utc_opt(read_heartbeat())
    rows.append(
        _heartbeat_row(now, key="research_worker", label="Research worker",
                        heartbeat=worker_hb, max_age=_RESEARCH_WORKER_MAX_AGE,
                        log_key="research")
    )

    drain_connected_raw = read_setting(trading_db, COMMAND_DRAIN_IBKR_CONNECTED_KEY)
    monitor_connected_raw = read_setting(trading_db, MONITOR_IBKR_CONNECTED_KEY)
    drain_leg_state, drain_leg_detail = _ibkr_leg(drain_hb, drain_max_age, drain_connected_raw)
    monitor_leg_state, monitor_leg_detail = _ibkr_leg(
        monitor_hb, monitor_max_age, monitor_connected_raw
    )
    rows.append(
        SystemRow(
            as_of=now,
            key="ibkr_connection",
            label="IBKR connection",
            state=_worst([drain_leg_state, monitor_leg_state]),
            detail=(
                f"approval_service: {drain_leg_detail}; "
                f"intraday_monitor: {monitor_leg_detail}"
            ),
            log_key=None,
        )
    )

    return SystemStatusResponse(as_of=now, rows=rows)


@router.get("/{name}/log", response_model=SystemLogResponse)
def system_log(
    name: str,
    _user: OwnerUser,
    level: Literal["warn", "info"] = Query("warn"),
    lines: int = Query(100, ge=1, le=_MAX_LOG_LINES),
) -> SystemLogResponse:
    now = datetime.now(UTC)
    path = _LOG_FILES.get(name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown system {name!r}")
    if not path.exists():
        return SystemLogResponse(as_of=now, name=name, level=level, lines=[])

    pattern = _LEVEL_PATTERN[level]
    matched: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if pattern.search(line):
                matched.append(line.rstrip("\n"))
    return SystemLogResponse(as_of=now, name=name, level=level, lines=matched[-lines:])
