"""Value book service entrypoint (docs/superpowers/specs/2026-10-28-value-swing-book-design.md).

Usage:
    python -m scripts.run_value

No IBKR connection in Parts 1-4; clientId 31 (``ibkr.client_ids.value``) from Part 5. Every ``value.service.poll_seconds`` it asks
``src.value.service.plan_run`` whether a settled session is waiting to be scored; when one is
(after ``value.service.run_hour_et``), it gathers the plain data ``src/value/`` may not fetch
itself (``scripts/value_feed.py``: earnings dates, news volume, market facts) and runs the
night, its §7.1 re-evaluations included. Then, with ``value.claude.enabled``, it runs Claude's
queued reads (``src.value.claude_reads.run_queue``) through the analyst in ``src.value_ai``
(spec §8): the operator's requests on every poll, the automatic set after a night, within the
day's caps. With ``value.book.enabled`` (Part 5, paper only) it also passes the night the trading
side's autonomy, auto-close and halt state, and during RTH runs the book's cycle on clientId 31
every ``book.cycle_minutes`` (``src.value.stage3``: reconcile, sells, buys funded by capital
release), its hourly check, and sends the book's messages. Idles when the ruleset check fails;
the book idles in live (``LIVE_TRADING=true``).
Runs until SIGINT/SIGTERM. Supervised by scripts.start like the other daemons.

The only module that imports ``src.value_ai`` (spec §5, §16). Never import this file: check it
with ``python -m py_compile``.
"""

import asyncio
import logging
import signal
import threading
import time
from datetime import UTC, date, datetime, timedelta

import src.common.value_inputs as vi
from scripts.value_feed import (
    FactsCache,
    NightRetry,
    earnings_dates,
    news_volume,
    recent_earnings,
)
from src.common.config import get_config
from src.common.logging import setup_logging
from src.common.value_ai_types import AnalystRequest, AnalystResult, FilingSection
from src.common.value_types import MarketFacts, ValueFinancials
from src.value.claude_reads import run_queue
from src.value.service import BookHooks, plan_run, run_nightly, startup_check
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


def _sections(symbol: str, accn: str) -> list[FilingSection]:
    with vi.research_read() as rs:
        return [] if rs is None else vi.filing_sections(rs, accn)


def _financials(symbol: str) -> ValueFinancials | None:
    """The filings as known today, for grounding's XBRL check (spec §8.2)."""
    stale = get_config().value.rules.data_quality.stale_item_days
    with vi.research_read() as rs:
        if rs is None:
            return None
        _, payload = vi.read_payload(rs, symbol)
    if payload is None:
        return None
    return vi.build_value_financials(payload, as_of=datetime.now(UTC).date(), stale_item_days=stale)


def _book_hooks() -> BookHooks | None:
    """The trading side's switches for the night's book step (Part 5), read here so src/value
    never opens the trading database's settings itself."""
    cfg = get_config()
    if not cfg.value.book.enabled:
        return None
    from src.storage.system_settings import is_halted, may_auto_open

    return BookHooks(
        may_auto_open=may_auto_open,
        auto_close=cfg.automation.auto_close_enabled,
        halted=is_halted(),
        is_live=cfg.is_live,
    )


_last_cycle: datetime | None = None
_last_hourly: datetime | None = None


def _in_rth(now_utc: datetime) -> bool:
    from zoneinfo import ZoneInfo

    from src.common.market_hours import is_early_close, is_trading_day

    et = now_utc.replace(tzinfo=UTC).astimezone(ZoneInfo("America/New_York"))
    close = 13 if is_early_close(et.date()) else 16
    minutes = et.hour * 60 + et.minute
    return is_trading_day(et.date()) and 9 * 60 + 35 <= minutes < close * 60 - 5


def _book_tick() -> None:
    """Stage 3's RTH cycle (paper only)."""
    global _last_cycle, _last_hourly
    cfg = get_config()
    if not cfg.value.book.enabled:
        return
    if cfg.is_live:
        log.critical("value: the book idles in live (paper only until a live plan exists)")
        return
    now = datetime.now(UTC).replace(tzinfo=None)
    if not _in_rth(now):
        return
    if _last_cycle is not None and now - _last_cycle < timedelta(
        minutes=cfg.value.book.cycle_minutes
    ):
        return
    hourly = _last_hourly is None or now - _last_hourly >= timedelta(hours=1)
    import src.value.notify as notify
    import src.value.stage3 as stage3

    msgs = asyncio.run(stage3.run_cycle(cfg, now=now, hourly=hourly))
    _last_cycle = now
    if hourly:
        _last_hourly = now
    if msgs:
        asyncio.run(notify.send(msgs))


_last_between: float = 0.0
BETWEEN_MIN_SECONDS = 5.0


def _between(*, force: bool = False) -> None:
    """Drain the operator's taps (and post the cards due) between the slow steps. The night, the
    Claude queue and the RTH cycle run on this thread and each can take minutes; the trading
    side expires a pending value command after ``approval.ttl_minutes``, so a tap must not wait
    out the whole slow tick. Throttled (a queue of skipped reads would otherwise drain per item)
    unless *force*; a failure waits for the main loop's next drain."""
    global _last_between
    now = time.monotonic()
    if not force and now - _last_between < BETWEEN_MIN_SECONDS:
        return
    _last_between = now
    try:
        _drain_commands()
    except Exception:  # noqa: BLE001 - commands wait for the next drain
        log.exception("value: the between-steps command drain failed")
    try:
        _post_outbox()
    except Exception:  # noqa: BLE001 - a card not posted is posted at the next tick
        log.exception("value: the between-steps card outbox failed")


def _claude_tick() -> None:
    """Claude's queued reads (spec §8.5): requests first, then the automatic set, within the
    day's caps. Each read commits on its own; a failed read is recorded, never retried blind."""
    cfg = get_config().value
    if not cfg.claude.enabled:
        return
    summary = run_queue(
        _read,
        now=datetime.now(UTC).replace(tzinfo=None),
        cfg=cfg,
        sections_for=_sections,
        financials_for=_financials,
        between=_between,
    )
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
            book=_book_hooks(),
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
    if get_config().value.telegram.digest_enabled:
        try:
            _post_digest()
        except Exception:  # noqa: BLE001 - the digest is a courtesy; the night already committed
            log.exception("value: the nightly digest failed")


def _market_one(symbol: str) -> tuple[MarketFacts, date | None]:
    """One name's yfinance facts and next earnings date, for the read-side commands (a refresh or
    a snapshot scores a single name). Both fall back to empty: a missing fact is UNKNOWN."""
    facts = vi.fetch_market_facts(symbol)
    try:
        return facts, earnings_dates(datetime.now(UTC).date()).get(symbol)
    except Exception:  # noqa: BLE001 - news.db is optional here
        return facts, None


def _drain_commands() -> int:
    """Claim the value kinds from app_commands, apply each in value.db, mark it (spec §9.7, ruling 1). The trading
    DB is imported here only: importing this script loads no wheel layer (the fence's probe)."""
    import src.value.commands as vcmd  # not `from src.value import`: the fence's ast reads that as src.value
    from src.common.value_commands import VALUE_KINDS
    from src.storage.app_commands import mark_applied, mark_failed, pending_commands
    from src.storage.db import session_scope
    from src.value.store import init_value_db, value_session

    cfg = get_config()
    # a command older than the approval TTL is the trading drain's sweep to expire, never ours to
    # apply: the state it meant to change has moved on (final review M2)
    cutoff = datetime.now(UTC) - timedelta(minutes=cfg.approval.ttl_minutes)
    with session_scope() as s:
        rows: list[vcmd.CommandTuple] = [
            (c.id, c.kind, dict(c.payload or {}), c.requested_by or "web", c.confirm_token)
            for c in pending_commands(s, only_kinds=VALUE_KINDS)
            if (c.created_at.replace(tzinfo=UTC) if c.created_at.tzinfo is None else c.created_at)
            >= cutoff
        ]
        s.commit()
    if not rows:
        return 0
    init_value_db()

    def _apply(kind: str, payload: dict, by: str) -> dict:
        now = datetime.now(UTC).replace(tzinfo=None)
        with value_session() as vs:  # commits on exit, rolls back a refused tap
            return vcmd.apply(
                vs,
                kind,
                payload,
                requested_by=by,
                now=now,
                live=cfg.is_live,
                research=vi.research_read,
                market=_market_one,
            )

    def _mark(cid: int, result: dict | None, reason: str | None, detail: dict | None) -> None:
        with session_scope() as s:
            if reason is None:
                mark_applied(s, cid, result or {})
            else:
                mark_failed(s, cid, reason, detail)
            s.commit()

    outcomes = vcmd.drain(rows, _apply, _mark)
    replies = vcmd.replies(outcomes)
    if replies:
        from src.value.notify import send

        asyncio.run(send(replies))
    return len(outcomes)


def _post_outbox() -> int:
    """Post the cards that are due (proposals, Major re-evaluations, the trim, a freeze) once each
    (Part 6, rulings 11 and 14). Reads value.db and sends in one short transaction, marks the keys
    that went out in a second, so a failed send is retried at the next tick."""
    import src.value.notify as notify
    import src.value.outbox as outbox
    from src.value.store import init_value_db, value_session

    cfg = get_config().value
    now = datetime.now(UTC).replace(tzinfo=None)
    init_value_db()
    with value_session() as vs:
        cards = outbox.due(vs, now, cfg)
    if not cards:
        return 0
    sent = asyncio.run(notify.send_cards(cards))
    if sent:
        with value_session() as vs:
            outbox.mark_posted(vs, sent, now)
    return len(sent)


def _post_digest() -> int:
    """The night's one digest message (Part 6, ruling 13), after the run and the book's night step.
    ``since`` is the last digest sent; an empty night sends nothing but still moves it on."""
    import src.value.digest as digest
    import src.value.notify as notify
    from src.value.store import value_session

    cfg = get_config().value
    now = datetime.now(UTC).replace(tzinfo=None)
    with value_session() as vs:
        since = digest.last_sent(vs) or now - timedelta(days=1)
        d = digest.compose(vs, since=since, now=now, cfg=cfg)
    sent = asyncio.run(notify.send([d.text])) if d.text else 0
    if d.text is None or sent:
        with value_session() as vs:
            digest.mark_sent(vs, d, now)
    return sent


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
    cfg = get_config().value
    poll, fast = cfg.service.poll_seconds, cfg.telegram.commands_poll_seconds
    log.info("value: running; commands every %ds, a settled session every %ds", fast, poll)
    last_slow = time.monotonic() - poll  # the first tick runs the slow work at once
    while True:
        try:
            _drain_commands()
        except Exception:  # noqa: BLE001 - commands wait for the next tick
            log.exception("value: the command drain failed; retrying at the next tick")
        try:
            _post_outbox()
        except Exception:  # noqa: BLE001 - a card not posted is posted at the next tick
            log.exception("value: the card outbox failed; retrying at the next tick")
        if time.monotonic() - last_slow >= poll:
            last_slow = time.monotonic()
            try:
                _tick()
            except Exception:  # noqa: BLE001 - a failed night is retried at the next poll
                log.exception("value: the nightly run failed; retrying at the next poll")
            _between(force=True)  # the night can take minutes: taps first
            try:
                _claude_tick()
            except Exception:  # noqa: BLE001 - a failed read is recorded; the queue waits
                log.exception("value: claude reads failed; the queue waits for the next poll")
            _between(force=True)  # reads take minutes too: taps before the cycle sends orders
            try:
                _book_tick()
            except Exception:  # noqa: BLE001 - a failed cycle sends nothing; the next one retries
                log.exception("value: the book cycle failed; retrying at the next poll")
            _between(force=True)
        if stop.wait(fast):
            break


if __name__ == "__main__":
    main()
