"""Value book service entrypoint (docs/superpowers/specs/2026-10-28-value-swing-book-design.md).

Usage:
    python -m scripts.run_value

No IBKR connection, no clientId (Parts 1-4). Every ``value.service.poll_seconds`` it asks
``src.value.service.plan_run`` whether a settled session is waiting to be scored; when one is
(after ``value.service.run_hour_et``), it gathers the plain data ``src/value/`` may not fetch
itself (``scripts/value_feed.py``: earnings dates, news volume, market facts) and runs the
night, its §7.1 re-evaluations included. Then, with ``value.claude.enabled``, it runs Claude's
queued reads (``src.value.claude_reads.run_queue``) through the analyst in ``src.value_ai``
(spec §8): the operator's requests on every poll, the automatic set after a night, within the
day's caps. Idles when the ruleset check fails.
Runs until SIGINT/SIGTERM. Supervised by scripts.start like the other daemons.

The only module that imports ``src.value_ai`` (spec §5, §16). Never import this file: check it
with ``python -m py_compile``.
"""

import asyncio
import logging
import signal
import threading
from datetime import UTC, datetime

from scripts.value_feed import (
    FactsCache,
    NightRetry,
    earnings_dates,
    news_volume,
    recent_earnings,
)
from src.common.config import get_config
from src.common.logging import setup_logging
from src.common.value_ai_types import AnalystRequest, AnalystResult
from src.value.claude_reads import run_queue
from src.value.service import plan_run, run_nightly, startup_check
from src.value_ai.analyst import Analyst

log = logging.getLogger("value")


_retry = NightRetry()
_facts = FactsCache()
_analyst: Analyst | None = None


def _read(req: AnalystRequest) -> AnalystResult:
    global _analyst
    if _analyst is None:
        _analyst = Analyst.from_config(get_config())
    return asyncio.run(_analyst.read(req, datetime.now(UTC)))


def _claude_tick() -> None:
    """Claude's queued reads (spec §8.5): requests first, then the automatic set, within the
    day's caps. Each read commits on its own; a failed read is recorded, never retried blind."""
    cfg = get_config().value
    if not cfg.claude.enabled:
        return
    summary = run_queue(_read, now=datetime.now(UTC).replace(tzinfo=None), cfg=cfg)
    if any(summary.values()):
        log.info("value: claude reads %s", summary)


def _tick() -> None:
    plan = plan_run()
    if plan is None:
        return
    if not _retry.ready(plan.as_of):
        return  # this session failed within the hour: no refetch of ~1,000 names
    workers = get_config().value.service.market_facts_workers
    log.info("value: scoring %d names for %s", len(plan.names), plan.as_of)
    try:
        facts = _facts.get(plan.as_of, plan.fetch_names, workers)
        run_nightly(
            plan,
            facts=facts,
            earnings=earnings_dates(plan.as_of),
            recent_earnings=recent_earnings(plan.as_of, plan.positions),
            news=news_volume(sorted(plan.positions)),
        )
    except Exception:
        n = _retry.failed(plan.as_of)
        level = logging.CRITICAL if n >= _retry.critical_after else logging.ERROR
        log.log(
            level,
            "value: the nightly run for %s failed (failure %d); retrying in %d s at the earliest",
            plan.as_of,
            n,
            _retry.retry_seconds,
            exc_info=True,
        )
        return
    _retry.succeeded()
    _facts.clear()


def main() -> None:
    setup_logging()
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    problem = startup_check()
    if problem is not None:
        log.critical("value: idle until the config is fixed and the process restarted: %s", problem)
        stop.wait()
        return
    poll = get_config().value.service.poll_seconds
    log.info("value: running; checking for a settled session every %ds", poll)
    while True:
        try:
            _tick()
        except Exception:  # noqa: BLE001 - a failed night is retried at the next poll
            log.exception("value: the nightly run failed; retrying at the next poll")
        try:
            _claude_tick()
        except Exception:  # noqa: BLE001 - a failed read is recorded; the queue waits
            log.exception("value: claude reads failed; the queue waits for the next poll")
        if stop.wait(poll):
            break


if __name__ == "__main__":
    main()
