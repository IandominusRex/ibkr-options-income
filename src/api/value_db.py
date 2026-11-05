"""Read-only access to data/value.db for the web API (value book Part 6, Task 13).

The value fence lets ``src/api`` import only ``src.value.scorecard`` and ``src.value.schemas``
(tests/test_value_fence.py), so this module opens the file itself with SQLite ``mode=ro`` and reads
it with plain SQL, as ``spreads_db.py`` does for the spreads book. It is the only module in
``src/api`` that names ``value_db_url_abs``. It yields ``None`` when the file does not exist yet or
cannot be opened, so a route answers ``available: false`` instead of a 500. Every reader returns
``None`` when its read failed (a missing table on an older file) and a plain empty value when the
table is there and holds nothing: unknown is never zero.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config
from src.common.value_commands import proposal_fingerprint
from src.common.value_cost import RunningCost
from src.reporting.day import ValueDayInput
from src.reporting.pay import ValuePayInput

log = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None

LISTS = ("deep_value", "quality_growth")
_WORKING = ("pending", "submitted", "partial")
_REEVAL_OPEN_DAYS = 10
ABOVE_KILLS = ("net_debt_to_ebitda_above", "dilution_above")
BELOW_KILLS = ("revenue_growth_below", "gross_margin_below")


def _resolve_path() -> str:
    """Filesystem path of data/value.db. Patched in tests."""
    url = get_config().value_db_url_abs()
    return url[len("sqlite:///") :] if url.startswith("sqlite:///") else url


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


@contextmanager
def value_read_session() -> Iterator[Session | None]:
    global _engine, _SessionLocal
    path = _resolve_path()
    if not Path(path).exists():
        yield None
        return
    s: Session | None = None
    try:
        if _engine is None:
            _engine = create_engine(
                f"sqlite:///file:{path}?mode=ro&uri=true",
                future=True,
                connect_args={"timeout": 5},
            )
            _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
        assert _SessionLocal is not None
        s = _SessionLocal()
        # Reads the schema page: `SELECT 1` never touches the file, so a file that is not a
        # SQLite database would pass it and then read as an empty book.
        s.execute(text("SELECT count(*) FROM sqlite_master"))
    except Exception as exc:  # noqa: BLE001 - a /value route degrades, never 500s
        log.debug("api value_db: cannot open %s: %s", path, exc)
        if s is not None:
            s.close()
        yield None
        return
    try:
        yield s
    finally:
        s.rollback()
        s.close()


# --- small helpers -------------------------------------------------------------------------------


def _rows(session: Session, sql: str, params: dict[str, Any] | None = None) -> list[dict] | None:
    """Plain-SQL rows as dicts, or None when the read failed (a missing table or column)."""
    try:
        return [dict(r._mapping) for r in session.execute(text(sql), params or {})]
    except Exception as exc:  # noqa: BLE001 - the caller decides what unreadable means
        log.debug("api value_db: read failed: %s", exc)
        session.rollback()
        return None


def columns_of(session: Session, table: str) -> set[str]:
    """Column names of a table; empty when the table does not exist (an older file)."""
    try:
        return {str(r[1]) for r in session.execute(text(f"PRAGMA table_info({table})"))}
    except Exception:  # noqa: BLE001
        session.rollback()
        return set()


def dt(raw: Any) -> datetime | None:
    """SQLite's stored text as a naive-UTC datetime (None stays None)."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def day(raw: Any) -> date | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def jsonish(raw: Any, default: Any) -> Any:
    """A JSON column read through plain SQL comes back as text."""
    if raw is None or raw == "":
        return default
    if isinstance(raw, dict | list):
        return raw
    try:
        return json.loads(str(raw))
    except ValueError:
        return default


def age_days(as_of: date | None, now: datetime) -> int | None:
    return None if as_of is None else max(0, (now.date() - as_of).days)


def next_exit(plan_json: Any) -> dict[str, Any] | None:
    """A held position's next exit from its stored plan: the half sale at the effective fair value
    until it is made, then the stop (the live policy is ``value``); None when the plan holds
    neither."""
    plan = jsonish(plan_json, {})
    if not isinstance(plan, dict):
        return None
    target = plan.get("effective_fair_value") or plan.get("fair_value")
    if not plan.get("half_sold") and isinstance(target, int | float):
        return {"kind": "sell_half", "level": float(target)}
    stop = plan.get("stop")
    if isinstance(stop, int | float):
        return {"kind": "stop", "level": float(stop)}
    return None


# --- /value/top ----------------------------------------------------------------------------------


def read_top(session: Session, list_name: str, limit: int = 10) -> list[dict] | None:
    """The trading universe's names on one list by the effective verdict: READY, then WATCH, then
    WAIT, each by rank (higher is better). Each row carries the effective figures, the baseline's
    reasons and the highest entry ceiling among the name's lists (the value-suggested put ceiling)."""
    if list_name not in LISTS:
        return []
    rank = "rank_deep" if list_name == "deep_value" else "rank_growth"
    rows = _rows(
        session,
        "SELECT t.symbol, t.price, t.as_of, t.computed_at, t.scorecard_json, "
        "e.verdict, e.decided_by, e.fair_value, e.entry_ceiling, e.margin_of_safety, "
        "(SELECT MAX(x.entry_ceiling) FROM value_effective x WHERE x.symbol = t.symbol "
        " AND x.verdict IN ('READY', 'WATCH', 'WAIT') AND x.entry_ceiling IS NOT NULL) "
        "AS put_ceiling "
        "FROM value_ticker_files t JOIN value_effective e "
        "ON e.symbol = t.symbol AND e.list_name = :list "
        "WHERE t.universe = 'trading' AND e.verdict IN ('READY', 'WATCH', 'WAIT') "
        "ORDER BY CASE e.verdict WHEN 'READY' THEN 0 WHEN 'WATCH' THEN 1 ELSE 2 END, "
        f"t.{rank} DESC, t.symbol LIMIT :n",
        {"list": list_name, "n": int(limit)},
    )
    if rows is None:
        return None
    for r in rows:
        card = jsonish(r.pop("scorecard_json"), {})
        evaluation = (card.get("lists") or {}).get(list_name) or {}
        r["reasons"] = [str(x) for x in (evaluation.get("reasons") or [])][:3]
    return rows


# --- /value/book and /value/positions --------------------------------------------------------------


def _orders(session: Session) -> list[dict] | None:
    return _rows(
        session,
        "SELECT symbol, list_name, side, shares, filled, avg_price, limit_price, status, "
        "created_at FROM value_orders ORDER BY created_at, id",
    )


def book_state(session: Session) -> dict[str, dict]:
    """The book's small key/value state (snapshot, high_water, trend), parsed."""
    rows = _rows(session, "SELECT key, value FROM value_book_state") or []
    return {str(r["key"]): jsonish(r["value"], {}) for r in rows}


def used_usd(orders: list[dict]) -> float:
    """What the book holds and is buying, in dollars: each name's filled shares at their running
    average cost, plus the unfilled remainder of its working buys at their limits (the book's
    ``totals``, which folds the same orders through the same ``RunningCost``, oldest first)."""
    names: dict[str, tuple[RunningCost, list[float]]] = {}  # symbol -> (cost, [net, working])
    for o in orders:
        rc, acc = names.setdefault(str(o["symbol"]), (RunningCost(), [0.0, 0.0]))
        filled = float(o["filled"] or 0.0)
        if o["side"] == "buy":
            rc.buy(filled, float(o["avg_price"] or 0.0))
            acc[0] += filled
            if o["status"] in _WORKING:
                acc[1] += max(0.0, float(o["shares"] or 0.0) - filled) * float(
                    o["limit_price"] or 0.0
                )
        else:
            rc.sell(filled)
            acc[0] -= filled
    total = 0.0
    for rc, (net, work) in names.values():
        avg = rc.avg
        total += (max(0.0, net) * avg if avg is not None else 0.0) + work
    return total


def read_positions(session: Session, status: str) -> list[dict] | None:
    """Open or closed positions with shares, average cost, the last mark, the next exit and the
    realised dollars (None until a sale has filled), newest first."""
    positions = _rows(
        session,
        "SELECT id, symbol, list_name, status, opened_on, closed_on, plan_json, decided_by "
        "FROM value_positions WHERE status = :s ORDER BY id DESC",
        {"s": status},
    )
    if positions is None:
        return None
    orders = _orders(session) or []
    marks = {
        str(r["symbol"]).upper(): r["mark"]
        for r in (_rows(session, "SELECT symbol, mark FROM value_attribution") or [])
        if r["mark"] is not None
    }
    out: list[dict] = []
    for p in positions:
        opened, closed = day(p["opened_on"]), day(p["closed_on"])
        lo = datetime.combine(opened, datetime.min.time()) - timedelta(days=1) if opened else None
        hi = datetime.combine(closed, datetime.min.time()) + timedelta(days=2) if closed else None
        rc = RunningCost()
        bought = sold = 0.0
        realised: float | None = 0.0
        last_avg: float | None = None
        for o in orders:
            if o["symbol"] != p["symbol"] or o["list_name"] != p["list_name"]:
                continue
            at = dt(o["created_at"])
            if at is None or (lo is not None and at < lo) or (hi is not None and at >= hi):
                continue
            filled = float(o["filled"] or 0.0)
            price = float(o["avg_price"] or 0.0)
            if o["side"] == "buy":
                bought += filled
                rc.buy(filled, price)
                last_avg = rc.avg
            else:
                sold += filled
                held = rc.qty
                avg = rc.sell(filled)
                if avg is None or realised is None:
                    realised = None  # a sale with no cost behind it: unknown, never 0
                else:
                    realised += min(filled, held) * (price - avg)  # never more than was held
                last_avg = avg if avg is not None else last_avg
        avg_cost = rc.avg if rc.qty > 0 else last_avg
        out.append(
            {
                "id": int(p["id"]),
                "symbol": str(p["symbol"]),
                "list_name": str(p["list_name"]),
                "status": str(p["status"]),
                "opened_on": opened,
                "closed_on": closed,
                "shares": max(0.0, bought - sold),
                "avg_cost": avg_cost,
                "mark": marks.get(str(p["symbol"]).upper()),
                "next_exit": next_exit(p["plan_json"]) if p["status"] == "open" else None,
                "realised_usd": realised if sold > 0 else None,
                "decided_by": str(p["decided_by"] or "python"),
                "plan_json": p["plan_json"],
            }
        )
    return out


def read_proposals(session: Session) -> list[dict] | None:
    """Pending, approved, funding and sent proposals, oldest first, each with the fingerprint a
    tap must carry back (``value_commands.proposal_fingerprint`` of the row)."""
    rows = _rows(
        session,
        "SELECT id, kind, symbol, list_name, shares, price, cost_usd, reason, cause, needs_tap, "
        "status, created_at, expires_at FROM value_proposals "
        "WHERE status IN ('pending', 'approved', 'funding', 'sent') ORDER BY id",
    )
    if rows is None:
        return None
    out: list[dict] = []
    for r in rows:
        created, expires = dt(r["created_at"]), dt(r["expires_at"])
        if created is None or expires is None:
            continue
        r["created_at"], r["expires_at"] = created, expires
        r["needs_tap"] = bool(r["needs_tap"])
        r["fingerprint"] = proposal_fingerprint(
            int(r["id"]), str(r["kind"]), str(r["symbol"]), float(r["shares"]), created
        )
        out.append(r)
    return out


def read_funding(session: Session) -> list[dict] | None:
    rows = _rows(
        session,
        "SELECT id, proposal_id, symbol, needed_usd, created_at, expires_at "
        "FROM value_funding_requests WHERE status = 'open' ORDER BY id",
    )
    if rows is None:
        return None
    for r in rows:
        r["created_at"], r["expires_at"] = dt(r["created_at"]), dt(r["expires_at"])
    return rows


def read_orders(session: Session) -> list[dict]:
    return _orders(session) or []


# --- /value/{symbol} -----------------------------------------------------------------------------


def read_ticker_row(session: Session, symbol: str) -> dict | None:
    """The stored ticker file's columns (the full scorecard included), or None."""
    cols = columns_of(session, "value_ticker_files")
    fresh = "freshness_json" if "freshness_json" in cols else "NULL AS freshness_json"
    rows = _rows(
        session,
        "SELECT symbol, computed_at, as_of, universe, scorecard_json, last_viewed_at, "
        f"{fresh} FROM value_ticker_files WHERE symbol = :s",
        {"s": symbol.upper()},
    )
    return rows[0] if rows else None


def read_effective(session: Session, symbol: str) -> dict[str, dict]:
    """The effective verdict per list: who decided it and the figures the gate reads."""
    rows = (
        _rows(
            session,
            "SELECT list_name, verdict, decided_by, python_verdict, claude_verdict, fair_value, "
            "entry_ceiling, margin_of_safety, mos_review FROM value_effective WHERE symbol = :s",
            {"s": symbol.upper()},
        )
        or []
    )
    return {str(r["list_name"]): r for r in rows}


def read_claude(session: Session, symbol: str) -> dict | None:
    """What Claude read for a name, labelled as Claude's; None when nothing was stored. The stored
    drivers are the ones Python kept after clamping; ``clamps`` says what it moved."""
    sym = symbol.upper()
    verdicts = _rows(
        session,
        "SELECT v.list_name, v.verdict, v.why, v.drivers_json, v.clamps_json, v.fair_value, "
        "v.uncapped, v.python_fair_value, v.clamp_bound, v.unreliable, v.backend, v.created_at "
        "FROM value_claude_verdicts v WHERE v.symbol = :s AND v.superseded = 0 "
        "ORDER BY v.list_name",
        {"s": sym},
    )
    notes = _rows(
        session,
        "SELECT profile, why_cheap, thesis, bear_case, review_state, review_why, backend, "
        "created_at FROM value_claude_notes WHERE symbol = :s ORDER BY id DESC LIMIT 1",
        {"s": sym},
    )
    if not verdicts and not notes:
        return None
    triggers = (
        _rows(
            session,
            "SELECT kind, threshold, active, last_state, last_actual, fired_on "
            "FROM value_kill_triggers WHERE symbol = :s AND active = 1 ORDER BY id",
            {"s": sym},
        )
        or []
    )
    facts = (
        _rows(
            session,
            "SELECT f.kind, f.value, f.unit, f.quote, f.accn, f.item, f.created_at "
            "FROM value_claude_facts f WHERE f.symbol = :s AND f.grounded = 1 "
            "ORDER BY f.id DESC LIMIT 12",
            {"s": sym},
        )
        or []
    )
    read = _rows(
        session,
        "SELECT MAX(read_at) AS read_at FROM value_claude_reads WHERE symbol = :s "
        "AND status = 'done'",
        {"s": sym},
    )
    return {
        "verdicts": verdicts or [],
        "notes": notes[0] if notes else None,
        "kill_triggers": triggers,
        "facts": facts,
        "read_at": dt(read[0]["read_at"]) if read else None,
    }


def read_reevaluations(session: Session, symbol: str, limit: int = 10) -> list[dict]:
    """A held name's re-evaluations, newest first (a shadow entry's are hypothetical and not
    returned)."""
    rows = (
        _rows(
            session,
            "SELECT id, list_name, session, last_session, severity, triggers_json, "
            "plan_before_json, plan_after_json, review_state, position_id FROM "
            "value_reevaluations WHERE symbol = :s AND position_id IS NOT NULL "
            "ORDER BY id DESC LIMIT :n",
            {"s": symbol.upper(), "n": int(limit)},
        )
        or []
    )
    return rows


def last_nightly_rs_cutoff(session: Session) -> float | None:
    """The last nightly run's 6-month relative-strength cutoff (the lookup scores with it)."""
    rows = _rows(
        session,
        "SELECT rs_cutoff_6m FROM value_runs WHERE kind = 'nightly' ORDER BY as_of DESC LIMIT 1",
    )
    if not rows or rows[0]["rs_cutoff_6m"] is None:
        return None
    return float(rows[0]["rs_cutoff_6m"])


# --- Home's money: the value book's fills as the reporting builders' plain inputs ----------------


def read_fills(session: Session) -> list[dict] | None:
    """Every filled value order, oldest first, with the proposal's reason and cause and, for a
    sale, the realised dollars: proceeds less the shares' running average cost (the buys filled
    up to that sale, less the shares earlier sales took out of the average). A fill with no price is left out:
    unknown cannot be shown as a trade."""
    rows = _rows(
        session,
        "SELECT o.id, o.symbol, o.list_name, o.side, o.filled, o.avg_price, o.reason AS order_reason, "
        "o.proposal_id, o.created_at, o.sent_at, o.done_at, p.reason AS proposal_reason, "
        "p.cause AS proposal_cause FROM value_orders o "
        "LEFT JOIN value_proposals p ON p.id = o.proposal_id "
        "WHERE o.filled > 0 AND o.avg_price IS NOT NULL ORDER BY o.created_at, o.id",
    )
    if rows is None:
        return None
    out: list[dict] = []
    held: dict[tuple[str, str], RunningCost] = {}  # (symbol, list) -> the running average cost
    for r in rows:
        key = (str(r["symbol"]), str(r["list_name"]))
        filled, price = float(r["filled"]), float(r["avg_price"])
        at = dt(r["done_at"]) or dt(r["sent_at"]) or dt(r["created_at"])
        if at is None:
            continue
        realised: float | None = None
        rc = held.setdefault(key, RunningCost())
        if r["side"] == "buy":
            rc.buy(filled, price)
        else:
            on_hand = rc.qty
            avg = rc.sell(filled)  # the shares sold leave the average (a re-entry starts afresh)
            if avg is not None:
                realised = min(filled, on_hand) * (price - avg)  # never more than was held
        out.append(
            {
                "at": at,
                "symbol": str(r["symbol"]),
                "side": "buy" if r["side"] == "buy" else "sell",
                "shares": filled,
                "price": price,
                "reason": str(r["proposal_reason"] or r["order_reason"] or ""),
                "cause": "claude" if r["proposal_cause"] == "claude" else "python",
                "proposal_id": None if r["proposal_id"] is None else int(r["proposal_id"]),
                "realised_usd": realised,
            }
        )
    return out


def read_value_pay_inputs() -> list[ValuePayInput] | None:
    """Each value sale's realised P&L by the date it filled; None when value.db could not be read
    (absent, not a database, or no orders table). value.db holds no commissions: those are None."""
    with value_read_session() as s:
        if s is None:
            return None
        fills = read_fills(s)
    if fills is None:
        return None
    return [
        ValuePayInput(
            closed_at=f["at"],
            symbol=f["symbol"],
            realised_usd=f["realised_usd"],
            commissions_usd=None,
        )
        for f in fills
        if f["side"] == "sell" and f["realised_usd"] is not None
    ]


def read_value_day_inputs() -> list[ValueDayInput] | None:
    """Every value fill with its reason and cause, for Home's day cards; None when unreadable."""
    with value_read_session() as s:
        if s is None:
            return None
        fills = read_fills(s)
    if fills is None:
        return None
    return [ValueDayInput(**f) for f in fills]
