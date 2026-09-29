"""Out-of-process health watchdog — alerts when the trading stack stops doing its job.

Runs as a one-shot every ``watchdog.interval_seconds`` under launchd/cron (``python -m
scripts.watchdog``), **never** inside the processes it watches: the 2026-09-15..22 outage
went unnoticed because the only alerting lived in the process that had stopped. It opens no
IBKR connection (no clientId), reads heartbeats/completion markers from ``system_settings``
and ``iv_history``, and sends plain-text Telegram messages through the raw Bot API so a
MarkdownV2 escaping bug can never silence it (see ``src/notify/formatters.py``'s escaping —
this module deliberately does not use it).

Read-only with respect to trading state; it writes only ``data/watchdog_state.json`` (the
alert state machine below) — no order, no config, no system_settings row.

Limitation: this can only notice the *stack* being unhealthy, not the Mac itself being off
or asleep — a powered-off machine runs no cron/launchd job at all, so no alert fires. Set
``watchdog.deadman_url`` to an external dead-man-switch service (e.g. healthchecks.io) to
close that gap: this module pings it on every run where every check passes, so *that*
service is what notices the pings stopping.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import traceback
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple
from zoneinfo import ZoneInfo

import httpx

from src.common.market_hours import is_rth, is_trading_day, today_et
from src.storage.iv_history import latest_obs_dates
from src.storage.system_settings import (
    EOD_COMPLETED_KEY,
    MONITOR_HEARTBEAT_KEY,
    SCAN_COMPLETED_KEY,
    get_setting,
)

if TYPE_CHECKING:
    from src.common.config import WatchdogCfg

log = logging.getLogger(__name__)

STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "watchdog_state.json"

_ET = ZoneInfo("America/New_York")
_MARKET_OPEN_HOUR, _MARKET_OPEN_MINUTE = 9, 30

# Mirrors COMMAND_DRAIN_HEARTBEAT_KEY in src/notify/command_drain.py — duplicated as a
# literal (the same precedent as src/api/routers/system.py's own ``_DRAIN_HEARTBEAT_KEY``)
# so the watchdog never imports src.notify, which pulls in python-telegram-bot and the whole
# approval-service dependency chain for no reason.
_COMMAND_DRAIN_HEARTBEAT_KEY = "command_drain_heartbeat"


class Check(NamedTuple):
    name: str
    ok: bool
    detail: str


def _age_minutes(iso: str | None, now: datetime) -> float | None:
    if not iso:
        return None
    ts = datetime.fromisoformat(iso)
    ts = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return (now - ts).total_seconds() / 60


def heartbeat_check(name: str, iso: str | None, now: datetime, *, max_age_min: int) -> Check:
    """Generic staleness check for any ISO-8601 heartbeat/completion marker."""
    age = _age_minutes(iso, now)
    if age is None:
        return Check(name, False, f"{name}: no heartbeat recorded")
    if age > max_age_min:
        return Check(name, False, f"{name}: last heartbeat {age:.0f} min ago (limit {max_age_min})")
    return Check(name, True, "")


def scan_loop_check(
    iso: str | None,
    now: datetime,
    *,
    in_rth: bool,
    minutes_since_open: float,
    max_age_min: int,
    grace_min: int,
) -> Check:
    """Fails only during RTH, and only once *grace_min* minutes past the open have elapsed —
    the intraday loop needs its first cycle to complete before ``intraday_scan_completed``
    exists at all, so checking immediately at the open would false-positive every morning."""
    if not in_rth or minutes_since_open < grace_min:
        return Check("scan_loop", True, "")
    age = _age_minutes(iso, now)
    if age is None or age > max_age_min:
        shown = "never" if age is None else f"{age:.0f} min ago"
        return Check(
            "scan_loop",
            False,
            f"scan_loop: last completed intraday scan {shown} (limit {max_age_min} min during RTH)",
        )
    return Check("scan_loop", True, "")


def eod_check(iso: str | None, now_et: datetime, due_hhmm: str, grace_min: int) -> Check:
    """Fails on a trading day, once *due_hhmm* (ET, ``scheduler.eod_report``) plus *grace_min*
    minutes has passed, when ``eod_completed`` is not dated *today* in ET.

    ``eod_completed`` means the EOD run *reached its end* — it says nothing about whether
    every step inside it (the IV backfill, the Telegram send) actually succeeded. IV
    staleness specifically is covered separately by ``iv_history_check``; this check only
    catches the run not finishing (or not starting) at all.

    Mirrors ``scan_loop_check``'s shape: a pure function over an ISO timestamp, a fixed
    ``now`` (already ET here, since the due time is an ET wall-clock time), and thresholds.
    """
    today = now_et.date()
    if not is_trading_day(today):
        return Check("eod", True, "")

    hh, mm = (int(p) for p in due_hhmm.split(":"))
    due = now_et.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(minutes=grace_min)
    if now_et < due:
        return Check("eod", True, "")

    if not iso:
        return Check(
            "eod", False, f"eod: no eod_completed recorded (due {due_hhmm} +{grace_min}m ET)"
        )
    ts = datetime.fromisoformat(iso)
    ts = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    ts_et_date = ts.astimezone(_ET).date()
    if ts_et_date != today:
        return Check(
            "eod",
            False,
            f"eod: last eod_completed {ts_et_date.isoformat()} ET (today is {today.isoformat()})",
        )
    return Check("eod", True, "")


def _trading_days_between(start: date, end: date) -> int:
    """Count of trading sessions strictly after *start* through *end* (inclusive of *end*)."""
    if end <= start:
        return 0
    n = 0
    d = start
    while d < end:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return n


def _universe_symbols() -> set[str]:
    """Indexes ∪ watchlist ∪ would_own.

    Mirrors ``src.orchestrator.eod_report._universe_symbols`` exactly, kept as a local copy
    rather than imported — that module pulls in ``telegram`` and ``ib_async`` at import time,
    which this dependency-thin, no-clientId process has no reason to carry.
    """
    from src.common.universe import effective_universe

    u = effective_universe()
    return set(u.get("indexes", [])) | set(u.get("watchlist", [])) | set(u.get("would_own", []))


def _held_symbols() -> set[str]:
    """Currently-held stock symbols (STK only — options aren't IV-history subjects)."""
    from src.storage.positions import load_latest_position_snapshot

    try:
        return {p.symbol.upper() for p in load_latest_position_snapshot() if p.sec_type == "STK"}
    except Exception:
        log.debug("watchdog: load_latest_position_snapshot failed", exc_info=True)
        return set()


def iv_history_check(now: datetime, max_stale_trading_days: int) -> Check:
    """Universe ∪ held symbols whose latest ``iv_history`` observation is more than
    *max_stale_trading_days* trading sessions old (or missing entirely).

    ``iv_history`` only gets a new row once a day (the EOD IV append), so this check's
    *result* barely changes between watchdog cycles even though the query itself (cheap —
    one grouped `SELECT`) re-runs every cycle. Reported as a single message listing every
    offending symbol, rather than one alert per symbol. The *alert* cadence — at most once
    per ET calendar day while this keeps failing, rather than every ``realert_minutes`` like
    every other check — is enforced by :func:`_alert_due`/:func:`decide_alerts`, not here.
    """
    symbols = sorted(_universe_symbols() | _held_symbols())
    if not symbols:
        return Check("iv_history", True, "")

    today = now.astimezone(_ET).date() if now.tzinfo else today_et()
    latest = latest_obs_dates(symbols)
    stale: list[str] = []
    for sym in symbols:
        d = latest.get(sym)
        if d is None:
            stale.append(f"{sym}(missing)")
            continue
        age = _trading_days_between(d, today)
        if age > max_stale_trading_days:
            stale.append(f"{sym}({age}d)")

    if stale:
        return Check("iv_history", False, f"iv_history: stale/missing IV — {', '.join(stale)}")
    return Check("iv_history", True, "")


def port_check(port: int) -> Check:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return Check("gateway_port", True, "")
    except OSError as exc:
        return Check("gateway_port", False, f"gateway_port: 127.0.0.1:{port} unreachable ({exc})")


def supervisor_check() -> Check:
    r = subprocess.run(["pgrep", "-f", "scripts.start"], capture_output=True, text=True)
    ok = r.returncode == 0 and bool(r.stdout.strip())
    return Check("supervisor", ok, "" if ok else "supervisor: scripts.start is not running")


def _et_date(dt: datetime) -> date:
    dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return dt.astimezone(_ET).date()


def _alert_due(name: str, prev: dict, now: datetime, *, realert_minutes: int) -> bool:
    """Whether a still-failing check is due to alert again this cycle.

    Every check re-sends on a fixed ``realert_minutes`` cadence, *except* ``iv_history``: the
    brief's checks table says it is "evaluated once per day and reported in one message" —
    the shared ``realert_minutes`` (default 60) would otherwise re-fire it roughly hourly all
    day, which is not "once per day". ``iv_history`` instead re-alerts only once the ET
    calendar date has advanced past its last alert's date.
    """
    if not prev.get("failing"):
        return True  # fresh ok→fail transition always alerts
    last_alert = prev.get("last_alert")
    if last_alert is None:
        return True
    last_alert_dt = datetime.fromisoformat(last_alert)
    if name == "iv_history":
        return _et_date(now) != _et_date(last_alert_dt)
    return now - last_alert_dt >= timedelta(minutes=realert_minutes)


def decide_alerts(
    checks: list[Check], state: dict, now: datetime, *, realert_minutes: int
) -> tuple[list[tuple[str, str]], dict]:
    """Decide which checks are due to alert this cycle, and what each check's state *would*
    become if every alert below is actually delivered.

    Pure — makes no Telegram call. Returns ``(alerts, candidate_state)``: ``alerts`` is a list
    of ``(check_name, message)`` pairs due to send this cycle (an ok→fail transition always
    alerts; a still-failing check re-alerts per :func:`_alert_due`; a fail→ok transition sends
    a "recovered" notice). ``candidate_state`` is the full next-state dict *as if* every one of
    those alerts sends successfully.

    Only entries in ``candidate_state`` for names that do **not** appear in ``alerts`` are safe
    to commit unconditionally — those are pure bookkeeping (an already-ok check staying ok, or
    a still-failing check that simply isn't due yet). For a name that *is* in ``alerts``, the
    caller (``main``) must actually attempt the send and only commit that name's
    ``candidate_state`` entry when ``send_telegram`` returns ``True``; on a failed send the
    caller must leave that check's entry exactly as it was before this cycle (i.e. as it was in
    ``state``), so the next cycle sees the alert as still not delivered and retries immediately
    rather than waiting out ``realert_minutes`` (or the once-a-day window) for something that
    was never actually sent. ``state``/``candidate_state`` are the JSON-serialisable
    ``data/watchdog_state.json`` payload — round-trip through ``json.dumps``/``json.loads``
    unchanged (plain str/bool values only).
    """
    alerts: list[tuple[str, str]] = []
    candidate_state = dict(state)
    for c in checks:
        prev = state.get(c.name, {})
        if not c.ok:
            if _alert_due(c.name, prev, now, realert_minutes=realert_minutes):
                detail = c.detail if c.detail.startswith(c.name) else f"{c.name}: {c.detail}"
                alerts.append((c.name, f"⚠️ {detail}"))
                candidate_state[c.name] = {"failing": True, "last_alert": now.isoformat()}
            else:
                candidate_state[c.name] = {**prev, "failing": True}
        else:
            if prev.get("failing"):
                alerts.append((c.name, f"✅ recovered: {c.name}"))
            candidate_state[c.name] = {"failing": False}
    return alerts, candidate_state


def _telegram_target() -> tuple[str, str, str]:
    from src.common.config import get_config

    s = get_config().secrets
    return s.telegram_bot_token, s.telegram_chat_id, s.telegram_thread_scan


def send_telegram(text: str) -> bool:
    """Plain text, no ``parse_mode`` — a MarkdownV2 escaping bug elsewhere must never be able
    to silence the one channel that reports the stack is down."""
    token, chat, thread = _telegram_target()
    if not token or not chat:
        log.error("watchdog: Telegram not configured")
        return False
    body: dict = {"chat_id": chat, "text": f"🐕 Watchdog\n{text}"}
    if thread:
        body["message_thread_id"] = int(thread)
    try:
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json=body, timeout=10)
        return r.status_code == 200
    except httpx.HTTPError:
        log.exception("watchdog: Telegram send failed")
        return False


def run_checks(now: datetime, cfg: WatchdogCfg) -> list[Check]:
    """Compose every check. Reads current heartbeat/completion values with ``get_setting``
    and the full :class:`~src.common.config.Config` (for the gateway port and
    ``scheduler.eod_report``) — *cfg* itself is only the watchdog-specific thresholds."""
    from src.common.config import get_config

    full_cfg = get_config()
    now_et = now.astimezone(_ET) if now.tzinfo else now.replace(tzinfo=UTC).astimezone(_ET)
    in_rth = is_rth(now_et)
    market_open = now_et.replace(
        hour=_MARKET_OPEN_HOUR, minute=_MARKET_OPEN_MINUTE, second=0, microsecond=0
    )
    minutes_since_open = max(0.0, (now_et - market_open).total_seconds() / 60)

    checks = [
        supervisor_check(),
        port_check(full_cfg.ibkr_port),
        heartbeat_check(
            "command_drain",
            get_setting(_COMMAND_DRAIN_HEARTBEAT_KEY) or None,
            now,
            max_age_min=cfg.heartbeat_max_age_minutes,
        ),
    ]

    if in_rth:
        checks.append(
            heartbeat_check(
                "monitor",
                get_setting(MONITOR_HEARTBEAT_KEY) or None,
                now,
                max_age_min=cfg.heartbeat_max_age_minutes,
            )
        )
    else:
        checks.append(Check("monitor", True, ""))

    checks.append(
        scan_loop_check(
            get_setting(SCAN_COMPLETED_KEY) or None,
            now,
            in_rth=in_rth,
            minutes_since_open=minutes_since_open,
            max_age_min=cfg.scan_max_age_minutes,
            grace_min=cfg.scan_grace_minutes,
        )
    )

    checks.append(
        eod_check(
            get_setting(EOD_COMPLETED_KEY) or None,
            now_et,
            full_cfg.scheduler.eod_report,
            cfg.eod_grace_minutes,
        )
    )

    checks.append(iv_history_check(now, cfg.iv_max_stale_trading_days))

    return checks


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main() -> int:
    try:
        from src.common.config import get_config

        cfg = get_config().watchdog
        now = datetime.now(UTC)
        state = _load_state()
        checks = run_checks(now, cfg)
        alerts, candidate_state = decide_alerts(
            checks, state, now, realert_minutes=cfg.realert_minutes
        )

        # Start from the prior state, not the candidate: an alert only gets its candidate
        # entry promoted once `send_telegram` actually confirms delivery below. A check that
        # isn't alerting this cycle (nothing in `alerts` names it) is pure bookkeeping and
        # always safe to commit — it never depended on a Telegram call succeeding.
        new_state = dict(state)
        alerting_names = {name for name, _ in alerts}
        for c in checks:
            if c.name not in alerting_names:
                new_state[c.name] = candidate_state[c.name]

        for name, msg in alerts:
            if send_telegram(msg):
                new_state[name] = candidate_state[name]
            else:
                log.warning(
                    "watchdog: Telegram send failed for %s — leaving state unchanged so "
                    "the next cycle retries immediately",
                    name,
                )

        _save_state(new_state)

        if cfg.deadman_url and all(c.ok for c in checks):
            try:
                httpx.get(cfg.deadman_url, timeout=5)
            except httpx.HTTPError:
                log.warning("watchdog: deadman ping failed", exc_info=True)

        for c in checks:
            (log.info if c.ok else log.warning)(
                "watchdog check %-12s ok=%s %s", c.name, c.ok, c.detail
            )
        return 0
    except Exception:
        log.exception("watchdog: crashed")
        try:
            send_telegram(f"watchdog crashed: {traceback.format_exc()[-500:]}")
        except Exception:
            log.exception("watchdog: failed to send the crash alert too")
        return 1
