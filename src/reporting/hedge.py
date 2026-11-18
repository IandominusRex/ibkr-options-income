"""The bridge hedge's own record (risk-envelope Tasks 36-37; spec §3.10.2, §3.10.11, ruling H2).

Read-only, like the rest of ``src/reporting/``: it reads the hedge book through
``src/common/hedge_view.py`` (``mode=ro``, plain SQL), daily account values through
``account_value.account_value_series`` and the instrument's closes from ``price_history``, and
writes nothing. Measured and shown, never promoted: the bridge sees one or two down legs at most.

``build_report(today)`` -> ``HedgeReport``:

* **premium**: paid, received (sales and cash settlements) and net, against NLV0 and the H3 caps;
* **down legs**: each pre-registered down leg of the instrument (a session whose close is at least
  1 sigma60 below its 60-session high, sigma60 the 60-session standard deviation of daily log
  returns scaled to 60 sessions), with the hedge's value change and the book's change from the
  leg's start to its trough and to its exit, and the **cover ratio** (hedge gain / book loss)
  against no hedge (0). The equal-S10 trim and always-on puts at equal spend need index option
  history the estate does not hold: the record names them and leaves them to the H5 research
  session;
* **execution against mid**: each filled order's average price against the mid it was approved at;
* **R²**: the rolling 60-session R² of daily NLV returns on the instrument's (QQQ's for XND).

``review_record(today)`` is the one-page text H2's review gate posts (at E4, or after 20
zero-size sessions), ending "default: off".
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from src.common import hedge_view

_ET = ZoneInfo("America/New_York")
SIGMA_SESSIONS = 60
R2_SESSIONS = 60
PROXY = {"XND": "QQQ"}


@dataclass(frozen=True, slots=True)
class DownLeg:
    start: date
    trough: date
    exit: date | None  # None while the leg is still open
    index_move_trough_pct: float
    hedge_gain_trough: float | None
    book_change_trough: float | None
    hedge_gain_exit: float | None
    book_change_exit: float | None
    cover_trough: float | None
    cover_exit: float | None


@dataclass
class HedgeReport:
    as_of: date
    programme: dict | None
    paid: float = 0.0
    received: float = 0.0
    nlv0: float | None = None
    open_value: float | None = None
    legs: list[DownLeg] = field(default_factory=list)
    slippage: list[tuple[str, float, float]] = field(default_factory=list)  # (ref, approved, avg)
    r2: float | None = None
    instrument: str | None = None

    @property
    def net(self) -> float:
        return self.paid - self.received


def _flows() -> tuple[float, float]:
    con = hedge_view.connect()
    if con is None:
        return 0.0, 0.0
    try:
        rows = con.execute("SELECT cash FROM hedge_fills").fetchall()
    except sqlite3.Error:
        return 0.0, 0.0
    finally:
        con.close()
    paid = -sum(float(c) for (c,) in rows if float(c) < 0)
    received = sum(float(c) for (c,) in rows if float(c) > 0)
    return paid, received


def _fills_vs_mid() -> list[tuple[str, float, float]]:
    con = hedge_view.connect()
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT order_ref, debit_approved, avg_fill_price, intent FROM hedge_orders "
            "WHERE filled_qty > 0 AND avg_fill_price IS NOT NULL ORDER BY id"
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [(str(r), abs(float(a)), float(f)) for r, a, f, _i in rows]


def _value_by_day() -> dict[date, float]:
    """The hedge book's marked value per ET day (the day's latest mark per position, summed)."""
    con = hedge_view.connect()
    if con is None:
        return {}
    try:
        rows = con.execute(
            "SELECT session_date, hedge_id, value FROM hedge_marks ORDER BY marked_at, id"
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    latest: dict[tuple[date, str], float] = {}
    for d, hid, v in rows:
        latest[(date.fromisoformat(str(d)[:10]), str(hid))] = float(v)
    out: dict[date, float] = {}
    for (d, _hid), v in latest.items():
        out[d] = out.get(d, 0.0) + v
    return out


def _nlv_by_day(now: datetime) -> dict[date, float]:
    from src.reporting.account_value import account_value_series
    from src.storage.db import session_scope

    try:
        series = account_value_series(session_scope, "all", now=now)
    except Exception:
        return {}
    return {p.at.astimezone(_ET).date(): p.value for p in series.points}


def _closes(symbol: str) -> list[tuple[date, float]]:
    from src.storage.price_history import load_bars

    return [(b.obs_date, b.close) for b in load_bars(symbol, limit=400) if b.close > 0]


def down_legs(closes: list[tuple[date, float]]) -> list[tuple[date, date, date | None, float]]:
    """The pre-registered down legs: (start, trough, exit or None, the trough's move from the
    60-session high in percent). A session is in a leg when its close is at least sigma60 below the
    60-session high; consecutive such sessions are one leg."""
    out: list[tuple[date, date, date | None, float]] = []
    current: list[tuple[date, float, float]] = []  # (day, close, high)
    for i in range(SIGMA_SESSIONS, len(closes)):
        window = closes[i - SIGMA_SESSIONS : i + 1]
        rets = [math.log(b[1] / a[1]) for a, b in zip(window, window[1:], strict=False)]
        mean = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1))
        sigma60 = sd * math.sqrt(SIGMA_SESSIONS)
        high = max(c for _, c in window)
        day, close = closes[i]
        if math.log(close / high) <= -sigma60:
            current.append((day, close, high))
        elif current:
            trough = min(current, key=lambda x: x[1])
            out.append((current[0][0], trough[0], day, (trough[1] / trough[2] - 1) * 100))
            current = []
    if current:
        trough = min(current, key=lambda x: x[1])
        out.append((current[0][0], trough[0], None, (trough[1] / trough[2] - 1) * 100))
    return out


def _change(series: dict[date, float], start: date, end: date | None) -> float | None:
    if end is None:
        return None
    before = [d for d in series if d <= start]
    after = [d for d in series if d <= end]
    if not before or not after:
        return None
    return series[max(after)] - series[max(before)]


def _cover(hedge: float | None, book: float | None) -> float | None:
    if hedge is None or book is None or book >= 0:
        return None
    return hedge / -book


def r_squared(xs: list[float], ys: list[float]) -> float | None:
    """R² of a one-variable least-squares fit; None under three points or no variance."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    if sxx <= 0 or syy <= 0:
        return None
    return sxy * sxy / (sxx * syy)


def _returns(series: dict[date, float]) -> dict[date, float]:
    days = sorted(series)
    return {
        b: math.log(series[b] / series[a])
        for a, b in zip(days, days[1:], strict=False)
        if series[a] > 0 and series[b] > 0
    }


def build_report(today: date, *, now: datetime | None = None) -> HedgeReport:
    """The record as of *today* (read-only)."""
    prog = hedge_view.latest_programme()
    instrument = str(prog["instrument"]) if prog else None
    rep = HedgeReport(as_of=today, programme=prog, instrument=instrument)
    rep.nlv0 = float(prog["nlv0"]) if prog else None
    rep.paid, rep.received = _flows()
    marks = hedge_view.marks_today(today) or []
    rep.open_value = sum(m["value"] for m in marks) if marks else None
    rep.slippage = _fills_vs_mid()
    when = now or datetime.combine(today, time(20, 0), tzinfo=UTC)
    nlv = _nlv_by_day(when)
    proxy = PROXY.get(instrument or "", instrument or "QQQ")
    closes = _closes(proxy)
    values = _value_by_day()
    start = date.fromisoformat(str(prog["started_on"])[:10]) if prog else None
    for leg_start, trough, exit_, move in down_legs(closes):
        if start is not None and (exit_ or today) < start:
            continue
        h_t, b_t = _change(values, leg_start, trough), _change(nlv, leg_start, trough)
        h_x, b_x = _change(values, leg_start, exit_), _change(nlv, leg_start, exit_)
        rep.legs.append(
            DownLeg(
                start=leg_start,
                trough=trough,
                exit=exit_,
                index_move_trough_pct=move,
                hedge_gain_trough=h_t,
                book_change_trough=b_t,
                hedge_gain_exit=h_x,
                book_change_exit=b_x,
                cover_trough=_cover(h_t, b_t),
                cover_exit=_cover(h_x, b_x),
            )
        )
    nret, iret = _returns(nlv), _returns(dict(closes))
    common = sorted(set(nret) & set(iret))[-R2_SESSIONS:]
    rep.r2 = r_squared([iret[d] for d in common], [nret[d] for d in common])
    return rep


def _usd(x: float | None) -> str:
    return "n/a" if x is None else (f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}")


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def render(rep: HedgeReport) -> str:
    lines = [f"Bridge hedge record, {rep.as_of:%Y-%m-%d}"]
    if rep.programme is None:
        lines.append("No bridge has started.")
        return "\n".join(lines)
    p = rep.programme
    lines.append(
        f"Instrument {p['instrument']}, started {str(p['started_on'])[:10]}, state {p['state']}, "
        f"NLV0 {_usd(rep.nlv0)}."
    )
    share = f" ({rep.net / rep.nlv0 * 100:.2f}% of NLV0)" if rep.nlv0 else ""
    lines.append(
        f"Premium: paid {_usd(rep.paid)}, received {_usd(rep.received)}, net {_usd(rep.net)}"
        f"{share}. Open positions marked at {_usd(rep.open_value)}."
    )
    if not rep.legs:
        lines.append("Down legs (index >= 1 sigma60 below its 60-session high): none so far.")
    for leg in rep.legs:
        lines.append(
            f"Down leg {leg.start} -> trough {leg.trough} ({leg.index_move_trough_pct:.1f}%), "
            f"exit {leg.exit or 'open'}: hedge {_usd(leg.hedge_gain_trough)} at the trough, "
            f"{_usd(leg.hedge_gain_exit)} at exit; book {_usd(leg.book_change_trough)} / "
            f"{_usd(leg.book_change_exit)}; cover {_pct(leg.cover_trough)} at the trough, "
            f"{_pct(leg.cover_exit)} at exit (no hedge: 0%)."
        )
    lines.append(
        "Against a trim removing the same S10 points and always-on puts at equal spend: not "
        "measured here (no index option history in the estate; the H5 research replay holds them)."
    )
    if rep.slippage:
        worst = max(rep.slippage, key=lambda s: abs(s[2] - s[1]))
        mean = sum(s[2] - s[1] for s in rep.slippage) / len(rep.slippage)
        lines.append(
            f"Execution vs the approved mid: {len(rep.slippage)} fills, mean {mean:+.2f} a "
            f"share, worst {worst[0]} {worst[2] - worst[1]:+.2f}."
        )
    lines.append(
        f"R² of daily NLV on {PROXY.get(rep.instrument or '', rep.instrument)}, last "
        f"{R2_SESSIONS} sessions: {'n/a' if rep.r2 is None else f'{rep.r2:.2f}'}."
    )
    return "\n".join(lines)


def review_record(*, today: date) -> str:
    """H2's one-page review record: the report and the decision it asks for, default off."""
    return (
        render(build_report(today))
        + "\n\nReview (H2): the bridge has reached the end of the glide, or its size rule has "
        "asked for nothing for 20 sessions. Continuing needs a fresh ruling under the same rules, "
        "at no more than 2% of NLV a rolling year. Default: off."
    )
