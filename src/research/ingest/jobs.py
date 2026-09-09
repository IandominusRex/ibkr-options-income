"""Job runner and scheduler for the research worker process.

Holds no IBKR connection. A job that raises is logged and swallowed: one failing source
must not take down the scheduler and every other job with it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.common.config import get_config
from src.research.ingest.materialize import drain_ingest_jobs
from src.research.ingest.quotes import refresh_quotes, refresh_warm_tier
from src.research.ingest.symbols import refresh_symbol_directory
from src.research.store.models import WorkerHeartbeatRow
from src.research.store.session import research_session

log = logging.getLogger(__name__)


def record_heartbeat(last_job: str | None) -> None:
    with research_session() as session:
        row = session.get(WorkerHeartbeatRow, 1)
        now = datetime.now(UTC)
        if row is None:
            session.add(WorkerHeartbeatRow(id=1, beat_at=now, last_job=last_job))
        else:
            row.beat_at = now
            row.last_job = last_job


def read_heartbeat() -> datetime | None:
    with research_session() as session:
        row = session.get(WorkerHeartbeatRow, 1)
        return row.beat_at if row else None


def run_job(name: str, fn: Callable[[], object]) -> bool:
    """Run a job, swallowing failures. Heartbeats only on success."""
    try:
        fn()
    except Exception:
        log.exception("Research job %r failed", name)
        return False
    record_heartbeat(name)
    return True


def build_scheduler() -> BackgroundScheduler:
    cfg = get_config().research.tiers
    sched = BackgroundScheduler(timezone=get_config().scheduler.timezone)

    # Symbol directory: the default 7-day cadence is the Sunday 03:00 cron
    # (clock-aligned, predictable); any other configured cadence falls back to
    # a plain interval from process start. Either way the key is consumed.
    if cfg.directory_refresh_days == 7:
        directory_trigger: CronTrigger | IntervalTrigger = CronTrigger(
            day_of_week="sun", hour=3, minute=0
        )
    else:
        directory_trigger = IntervalTrigger(days=max(1, cfg.directory_refresh_days))
    sched.add_job(
        lambda: run_job("symbols", refresh_symbol_directory),
        directory_trigger,
        id="symbol_directory",
        replace_existing=True,
    )
    sched.add_job(
        lambda: run_job("drain", drain_ingest_jobs),
        IntervalTrigger(seconds=30),
        id="drain_ingest_jobs",
        replace_existing=True,
    )
    # Nightly warm-tier refresh: daily bars + news for watchlisted and recently
    # viewed symbols (the design's warm tier). One job, so the heartbeat covers
    # the whole pass. Per-symbol failures are isolated inside refresh_warm_tier.
    sched.add_job(
        lambda: run_job("warm_refresh", refresh_warm_tier),
        CronTrigger(hour=cfg.warm_refresh_hour_et, minute=0),
        id="warm_refresh",
        replace_existing=True,
    )
    sched.add_job(
        lambda: run_job("quotes", refresh_quotes),
        IntervalTrigger(minutes=15),
        id="refresh_quotes",
        replace_existing=True,
    )
    return sched
