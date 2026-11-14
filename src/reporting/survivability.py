"""The survivability harness (risk-envelope plan Task 26; spec §3.4.6, rulings P1, P2).

Two answers, on the 17-month ``price_history`` panel and today's book:

* **The analytic worst case**: every pre-registered scenario (S10, S20, G10, P20, T20, S-SMH), gross
  and net of long options (H1), the highest of them, and the spreads book at its monthly stop
  (-2% of NLV a month at worst) counted on top.
* **The replays**: *today's book* (shares, option contracts at their moneyness and expiry) facing
  the panel's real daily returns, two ways.

  ``status_quo`` is the unenveloped path: the composition is held constant, every option rolled
  each day at the same moneyness and days to expiry.

  ``aggressive`` is the always-most-aggressive path under the envelope: today's options run to
  their expiries, and every day the agent tries a 0.25-delta 30-day cash-secured put on each
  ``actively_wheeling`` name at the largest size the envelope admits (``max_contracts_under``), with
  the limits gliding as ``envelope_state.limits_on`` says from the day-0 measurement. Each admission
  is re-checked independently (the S10_gross and U_ew after it against the limits of that day): an
  admission that leaves either above its limit *and* raised it is a **violation**.

Option values are Black-Scholes at the stored IV, held constant through the panel; a day's P&L is
``shock.line_pnl`` over the actual return and the elapsed days. No long option, no hedge and no
value-book stock is in the replayed book unless the caller puts it there.

``harness_result`` is P2 **and** P1: no violation and the aggressive path's worst 20-session
drawdown no worse than the status-quo path's, **and** at least ten record sessions
(``EnvelopeSnapshotRow`` rows with ``enforce = 'record'``) with no P1 defect (``envelope_unmeasured``
on more than 20% of a session's evaluated CSPs, or the generator and the gate disagreeing on a
candidate). Too few record sessions is ``passed=None``, never a PASS.

Read-only: the data comes in as plain values or a read-only connection
(``src/reporting/replay.py``); nothing is written here.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Literal

from src.analytics.shock import SCENARIOS, line_pnl, measure
from src.common.envelope_types import BookLine, EnvelopeRoom, ShockInputs
from src.common.schemas import EnvelopeReportResult
from src.engine.envelope import max_contracts_under
from src.reporting.replay import (
    Closes,
    close_on,
    et_day,
    make_result,
    parse_stamp,
    strike_for_delta,
    worst_drawdown,
)
from src.storage.envelope_state import GlideRecord, limits_on, start_levels

SPREADS_MONTH_STOP_PCT = 2.0
MIN_RECORD_SESSIONS = 10
UNMEASURED_SHARE_LIMIT = 0.20
SESSIONS_PER_MONTH = 21
SWITCH = "envelope_enforce"
CRITERION = (
    "P1/P2: zero admissions while S10_gross > L(t) or U_ew > L_ew(t) across the replay, and the "
    "always-most-aggressive replay's worst 20-session drawdown <= the unenveloped path's; and >= 10 "
    "record sessions with no defect (envelope_unmeasured on > 20% of a session's evaluated CSPs, or "
    "the generator and the gate disagreeing on a candidate)"
)
_EPS = 1e-9

Sizer = Callable[[EnvelopeRoom, ShockInputs, BookLine, int], int]


class ReplayUnavailable(Exception):
    """The replay cannot be run on the data it was given (a missing close, beta or IV). The caller
    writes no PASS."""


# --- the analytic worst case ----------------------------------------------------------------


@dataclass(frozen=True)
class WorstCase:
    gross: dict[str, float]  # scenario -> % of NLV lost, no long option counted (H1)
    net: dict[str, float]  # the same with long options counted (display and harness only)
    worst_gross: str
    worst_net: str
    spreads_pct: float
    total_gross_pct: float  # the worst gross scenario plus the spreads book's month
    total_net_pct: float
    uew: float
    unmeasured: tuple[str, ...]


def analytic_worst_case(
    inputs: ShockInputs, *, spreads_month_pct: float = SPREADS_MONTH_STOP_PCT
) -> WorstCase:
    """Every scenario's loss on *inputs*, gross and net, the worst of each, and the spreads book at
    its caps (*spreads_month_pct* of NLV a month, spec §3.4.6) added to the worst."""
    res = measure(inputs)
    gross = {
        "S10": res.s10,
        "S20": res.s20,
        "G10": res.g10,
        "P20": res.p20,
        "T20": res.t20,
        "S_SMH": res.s_smh,
    }
    net = {
        "S10": res.s10_net,
        "S20": res.s20_net,
        "G10": res.g10_net,
        "P20": res.p20_net,
        "T20": res.t20_net,
        "S_SMH": res.s_smh_net,
    }
    assert set(gross) == set(SCENARIOS)
    wg = max(gross, key=lambda k: gross[k])
    wn = max(net, key=lambda k: net[k])
    return WorstCase(
        gross=gross,
        net=net,
        worst_gross=wg,
        worst_net=wn,
        spreads_pct=spreads_month_pct,
        total_gross_pct=gross[wg] + spreads_month_pct,
        total_net_pct=net[wn] + spreads_month_pct,
        uew=res.uew,
        unmeasured=res.unmeasured,
    )


# --- the replay -----------------------------------------------------------------------------


@dataclass
class ReplayResult:
    days: list[date] = field(default_factory=list)
    nlv: list[float] = field(default_factory=list)
    s10: list[float] = field(default_factory=list)
    uew: list[float] = field(default_factory=list)
    opened_lots: int = 0
    opened_contracts: int = 0
    violations: list[str] = field(default_factory=list)
    unmeasured_days: int = 0
    worst20: float = 0.0


@dataclass
class _Pos:
    symbol: str
    kind: str
    qty: float
    strike: float | None = None
    expiry: date | None = None
    iv: float | None = None
    moneyness: float | None = None  # strike / spot, the status-quo path's constant
    dte0: int | None = None
    book: str = "wheel"


def envelope_sizer(room: EnvelopeRoom, inputs: ShockInputs, one: BookLine, hard_max: int) -> int:
    """The production sizing rule: the most contracts ``admits`` passes (P3)."""
    return max_contracts_under(room, inputs, one, hard_max)[0]


def _spot(closes: Closes, symbol: str, day: date) -> float | None:
    series = closes.get(symbol.upper())
    return close_on(series, day) if series else None


def _reference(closes: Closes) -> str:
    if "SPY" in closes:
        return "SPY"
    if not closes:
        raise ReplayUnavailable("no closes at all")
    return max(closes, key=lambda s: len(closes[s]))


def _lines_at(
    positions: Sequence[_Pos], closes: Closes, day: date, *, constant: bool
) -> tuple[list[BookLine], list[str]]:
    """The positions as ``BookLine``s at *day*'s closes, and the symbols with no close."""
    lines: list[BookLine] = []
    missing: list[str] = []
    for p in positions:
        spot = _spot(closes, p.symbol, day)
        if spot is None:
            missing.append(p.symbol)
            continue
        if p.kind == "stock":
            lines.append(BookLine(p.symbol, "stock", p.qty, spot, book=p.book))
            continue
        if constant:
            assert p.moneyness is not None and p.dte0 is not None
            strike, dte = p.moneyness * spot, p.dte0
        else:
            assert p.strike is not None and p.expiry is not None
            strike, dte = p.strike, (p.expiry - day).days
        lines.append(
            BookLine(
                p.symbol,
                p.kind,  # type: ignore[arg-type]
                p.qty,
                spot,
                strike=strike,
                dte=dte,
                iv=p.iv,
                book=p.book,
            )
        )
    return lines, missing


def _room(
    inputs: ShockInputs, glide: GlideRecord | None, day: date
) -> tuple[EnvelopeRoom, float, float]:
    res = measure(inputs)
    s10_lim, uew_lim = limits_on(glide, day) if glide is not None else (1e9, 1e9)
    room = EnvelopeRoom(
        s10_gross=res.s10,
        s10_limit=s10_lim,
        uew=res.uew,
        uew_limit=uew_lim,
        t20_gross=res.t20,
        t20_limit=None,
        enforce="on",
        measured=res.measured,
        reasons_if_unmeasured=tuple(f"unmeasured:{s}" for s in res.unmeasured),
    )
    return room, res.s10, res.uew


def simulate(
    book: ShockInputs,
    closes: Closes,
    ivs: Mapping[str, float],
    *,
    mode: Literal["status_quo", "aggressive"],
    start: date,
    names: Sequence[str] = (),
    glide: GlideRecord | None = None,
    glide_targets: tuple[float, float, int] | None = None,
    sizer: Sizer = envelope_sizer,
    hard_max: int = 10,
    delta: float = 0.25,
    dte: int = 30,
    attempt_every: int = 1,
    spreads_month_pct: float = SPREADS_MONTH_STOP_PCT,
    window: int = 20,
) -> ReplayResult:
    """Today's *book* facing the panel's daily returns from *start* (see the module docstring).

    Raises ``ReplayUnavailable`` when a held name has no close, an option has no IV, or the book's
    day-0 measurement is not fully measured (a harness must not run on a book it cannot value)."""
    ref = _reference(closes)
    days = [d for d, _ in closes[ref] if d >= start]
    if len(days) < 2:
        raise ReplayUnavailable(f"fewer than two sessions from {start} in the panel")
    aggressive = mode == "aggressive"

    positions: list[_Pos] = []
    for ln in book.lines:
        sym = ln.symbol.upper()
        spot0 = _spot(closes, sym, days[0])
        if spot0 is None:
            raise ReplayUnavailable(f"{sym}: no close at the panel start")
        if ln.kind == "stock":
            positions.append(_Pos(sym, "stock", ln.qty, book=ln.book))
            continue
        if not ln.spot > 0 or ln.strike is None or ln.dte is None:
            raise ReplayUnavailable(f"{sym}: an option line with no spot, strike or expiry")
        iv = ln.iv if ln.iv is not None and ln.iv > 0 else ivs.get(sym)
        if iv is None or iv <= 0:
            raise ReplayUnavailable(f"{sym}: no implied volatility")
        m = ln.strike / ln.spot
        positions.append(
            _Pos(
                sym,
                ln.kind,
                ln.qty,
                strike=m * spot0,
                expiry=days[0].fromordinal(days[0].toordinal() + max(1, ln.dte)),
                iv=iv,
                moneyness=m,
                dte0=max(1, ln.dte),
                book=ln.book,
            )
        )

    nlv0 = float(book.nlv)
    out = ReplayResult()
    lines0, missing0 = _lines_at(positions, closes, days[0], constant=not aggressive)
    inputs0 = replace(book, lines=tuple(lines0))
    first = measure(inputs0)
    if missing0 or not first.measured:
        raise ReplayUnavailable(
            f"the book is not fully measured at the panel start: {missing0 or first.unmeasured}"
        )
    if aggressive and glide is None and glide_targets is not None:
        # the glide starts from the day-0 measurement, as the first `on` session starts it (E4/E5)
        s10_target, uew_target, weeks = glide_targets
        s10_start, uew_start = start_levels(first, s10_target=s10_target, uew_target=uew_target)
        glide = GlideRecord(days[0], s10_start, uew_start, weeks, s10_target, uew_target)
    nlv = nlv0
    out.days.append(days[0])
    out.nlv.append(nlv)
    out.s10.append(first.s10)
    out.uew.append(first.uew)

    for i in range(1, len(days)):
        prev, today = days[i - 1], days[i]
        elapsed = max(1, (today - prev).days)
        pnl = 0.0
        prev_lines, _ = _lines_at(positions, closes, prev, constant=not aggressive)
        for ln in prev_lines:
            spot_new = _spot(closes, ln.symbol, today)
            if spot_new is None or not ln.spot > 0:
                continue
            if ln.kind != "stock" and (ln.dte or 0) <= 0:
                continue  # expired before the previous close: already settled
            move = spot_new / ln.spot - 1.0
            got = line_pnl(ln, move, days=elapsed)
            if got is not None:
                pnl += got
        if aggressive:
            positions = [p for p in positions if p.kind == "stock" or (p.expiry or today) > today]
        nlv += pnl
        if i % SESSIONS_PER_MONTH == 0:
            nlv -= spreads_month_pct / 100.0 * nlv0

        today_lines, missing = _lines_at(positions, closes, today, constant=not aggressive)
        if missing:
            out.unmeasured_days += 1
        inputs = replace(book, lines=tuple(today_lines), nlv=max(nlv, 1.0))
        room, s10_now, uew_now = _room(inputs, glide, today)
        if aggressive and names and i % max(1, attempt_every) == 0:
            for sym in names:
                # a short put raises both measures: with either at its limit nothing is admitted
                if room.measured and (
                    room.s10_gross >= room.s10_limit - _EPS or room.uew >= room.uew_limit - _EPS
                ):
                    break
                spot, iv = _spot(closes, sym, today), ivs.get(sym.upper())
                if spot is None or iv is None:
                    continue
                strike = strike_for_delta(spot, dte, iv, delta, "P")
                if strike is None:
                    continue
                one = BookLine(sym.upper(), "short_put", 1.0, spot, strike=strike, dte=dte, iv=iv)
                n = sizer(room, inputs, one, hard_max)
                if n <= 0:
                    continue
                add = replace(one, qty=float(n))
                inputs = replace(inputs, lines=inputs.lines + (add,))
                positions.append(
                    _Pos(
                        sym.upper(),
                        "short_put",
                        float(n),
                        strike=strike,
                        expiry=today.fromordinal(today.toordinal() + dte),
                        iv=iv,
                    )
                )
                after_room, s10_after, uew_after = _room(inputs, glide, today)
                if s10_after > room.s10_limit + _EPS and s10_after > s10_now + _EPS:
                    out.violations.append(
                        f"{today} {sym} x{n}: S10 {s10_after:.2f}% after, limit {room.s10_limit:.2f}%"
                    )
                if uew_after > room.uew_limit + _EPS and uew_after > uew_now + _EPS:
                    out.violations.append(
                        f"{today} {sym} x{n}: U_ew {uew_after:.3f} after, limit {room.uew_limit:.3f}"
                    )
                out.opened_lots += 1
                out.opened_contracts += n
                room, s10_now, uew_now = after_room, s10_after, uew_after
        out.days.append(today)
        out.nlv.append(nlv)
        out.s10.append(s10_now)
        out.uew.append(uew_now)
    out.worst20 = worst_drawdown(out.nlv, window)
    return out


# --- the record evidence (P1) ---------------------------------------------------------------

_ENVELOPE_REASONS = ("shock_budget", "gross_budget", "t20_budget", "envelope_unmeasured")
_Row = tuple[date, str, str, str]  # (action day, candidate id, record key, reason)


def _is_envelope_reason(text: str) -> bool:
    return any(r in text for r in _ENVELOPE_REASONS)


def p1_defects(evaluated_by_day: Mapping[date, int], rows: Sequence[_Row]) -> list[str]:
    """The P1 defects in a run of record sessions.

    *rows* are the ``sizing_actions`` rows of kind ``envelope_record``. A day is a defect when
    ``envelope_unmeasured`` is the refusal on more than 20% of its evaluated CSP candidates, or when
    the generator and the gate disagree: in record mode the generator writes a ``:generator`` row
    for every candidate whose size it would trim and the gate a ``:scan`` or ``:ticker_scan`` row
    for every candidate it would refuse, so the two sets of candidates must be the same.
    """
    defects: list[str] = []
    by_day: dict[date, list[_Row]] = {}
    for row in rows:
        by_day.setdefault(row[0], []).append(row)
    for day in sorted(by_day):
        day_rows = by_day[day]
        unmeasured = {r[1] for r in day_rows if "envelope_unmeasured" in r[3]}
        evaluated = evaluated_by_day.get(day, 0)
        if unmeasured and (evaluated <= 0 or len(unmeasured) / evaluated > UNMEASURED_SHARE_LIMIT):
            defects.append(f"{day}: envelope_unmeasured on {len(unmeasured)} of {evaluated}")
        generator = {
            r[1] for r in day_rows if r[2].endswith(":generator") and _is_envelope_reason(r[3])
        }
        gate = {
            r[1]
            for r in day_rows
            if r[2].endswith((":scan", ":ticker_scan")) and _is_envelope_reason(r[3])
        }
        for cid in sorted(generator ^ gate):
            side = (
                "the generator trims and the gate admits"
                if cid in generator
                else ("the gate refuses and the generator admits")
            )
            defects.append(f"{day}: {cid}: {side}")
    return defects


@dataclass(frozen=True)
class RecordEvidence:
    sessions: int
    defects: list[str]


def read_record_evidence(con: sqlite3.Connection) -> RecordEvidence:
    """The record sessions and their P1 defects, from a read-only trading-DB connection."""
    sessions = {
        et_day(parse_stamp(r[0]))
        for r in con.execute("SELECT captured_at FROM envelope_snapshots WHERE enforce = 'record'")
    }
    evaluated: dict[date, set[str]] = {}
    for r in con.execute(
        "SELECT candidate_id, created_at FROM candidates WHERE strategy = 'cash_secured_put'"
    ):
        evaluated.setdefault(et_day(parse_stamp(r[1])), set()).add(str(r[0]))
    rows: list[_Row] = [
        (date.fromisoformat(str(r[0])[:10]), str(r[1]), str(r[2]), str(r[3]))
        for r in con.execute(
            "SELECT action_day, candidate_id, record_key, reason FROM sizing_actions "
            "WHERE kind = 'envelope_record'"
        )
    ]
    # only the record sessions count: a day outside them is another phase's record
    rows = [r for r in rows if r[0] in sessions]
    return RecordEvidence(
        sessions=len(sessions),
        defects=p1_defects({d: len(v) for d, v in evaluated.items()}, rows),
    )


# --- the verdict ----------------------------------------------------------------------------


def harness_result(
    worst: WorstCase,
    base: ReplayResult,
    aggressive: ReplayResult,
    *,
    record_sessions: int,
    defects: Sequence[str],
    now: datetime | None = None,
    min_record_sessions: int = MIN_RECORD_SESSIONS,
) -> EnvelopeReportResult:
    """The harness verdict (P1/P2). A P2 failure is a FAIL whatever the record says; a P2 pass with
    fewer than *min_record_sessions* record sessions, or a defect among them, is ``passed=None``."""
    no_violation = not aggressive.violations
    drawdown_ok = aggressive.worst20 <= base.worst20 + _EPS
    p2 = no_violation and drawdown_ok
    record_ok = record_sessions >= min_record_sessions and not defects
    if not p2:
        passed: bool | None = False
    elif record_ok:
        passed = True
    else:
        passed = None
    metrics: dict[str, float | str | None] = {
        "p2": "pass" if p2 else "fail",
        "violations": float(len(aggressive.violations)),
        "worst20_status_quo_pct": round(base.worst20, 3),
        "worst20_aggressive_pct": round(aggressive.worst20, 3),
        "opened_lots": float(aggressive.opened_lots),
        "opened_contracts": float(aggressive.opened_contracts),
        "record_sessions": float(record_sessions),
        "record_defects": float(len(defects)),
        "analytic_worst_gross": worst.worst_gross,
        "analytic_worst_gross_pct": round(worst.gross[worst.worst_gross], 3),
        "analytic_with_spreads_pct": round(worst.total_gross_pct, 3),
        "analytic_worst_net_pct": round(worst.net[worst.worst_net], 3),
        "uew": round(worst.uew, 3),
    }
    if p2 and not record_ok:
        metrics["note"] = (
            f"{record_sessions} of {min_record_sessions} record sessions"
            if record_sessions < min_record_sessions
            else f"{len(defects)} P1 defect(s): {'; '.join(list(defects)[:3])}"
        )
    return make_result(
        "harness",
        passed=passed,
        criterion=CRITERION,
        metrics=metrics,
        switch=SWITCH,
        value_on_pass="on",
        now=now,
    )
