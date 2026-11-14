"""Shared, read-only plumbing for the risk-envelope replays (risk-envelope plan Section H).

The survivability harness, the rule backtests and the in-estate replays all do the same few
things: open a copy of the trading database read-only, read a panel of daily closes and the book
as it stood, pick a strike by delta, measure a drawdown, and write one result file (an
``EnvelopeReportResult``, which ``envelope_switches.apply_reports`` consumes) plus a text report
under ``data/envelope_reports/``.

Everything here reads with plain SQL on a ``mode=ro`` SQLite connection: no session, no write to
any database. The only files written are the result and report files below. A replay never
invents data: a series it cannot read is empty, and the caller turns that into ``passed=None``
(insufficient data), never a PASS.

Deterministic tier on the read side: imports the pure analytics and the schemas, nothing from the
enrichment layer.
"""

from __future__ import annotations

import json
import math
import sqlite3
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scipy.stats import norm

from src.analytics.shock_inputs import _blume, build_inputs
from src.common.config import ROOT, get_config, get_envelope_cfg
from src.common.envelope_types import ShockInputs
from src.common.schemas import AccountSnapshot, EnvelopeReportResult, PositionSnapshot

REPORTS_DIR = ROOT / "data" / "envelope_reports"
_ET = ZoneInfo("America/New_York")

Closes = dict[str, list[tuple[date, float]]]  # symbol -> (day, close), ascending


# --- the databases, read-only ---------------------------------------------------------------


def trading_db_path() -> Path:
    """The configured trading database file (``storage.db_url``), absolute."""
    url = get_config().db_url_abs()
    if not url.startswith("sqlite:///"):
        raise ValueError(f"the replays read a SQLite trading database, not {url!r}")
    return Path(url[len("sqlite:///") :])


def open_ro(path: Path) -> sqlite3.Connection:
    """A read-only connection to *path*; ``FileNotFoundError`` when it does not exist (SQLite's own
    ``mode=ro`` would otherwise say 'unable to open', and a missing file must read as 'no data')."""
    if not path.exists():
        raise FileNotFoundError(str(path))
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _day(raw: object) -> date:
    return date.fromisoformat(str(raw)[:10])


def load_closes(
    con: sqlite3.Connection, symbols: Sequence[str], since: date | None = None
) -> Closes:
    """Daily closes from ``price_history`` for *symbols*, ascending; a symbol with no rows is left
    out (the caller names it as missing)."""
    out: Closes = {}
    for sym in sorted({s.upper() for s in symbols}):
        sql = "SELECT obs_date, close FROM price_history WHERE symbol = ? AND close > 0"
        args: list[object] = [sym]
        if since is not None:
            sql += " AND obs_date >= ?"
            args.append(since.isoformat())
        rows = con.execute(sql + " ORDER BY obs_date", args).fetchall()
        if rows:
            out[sym] = [(_day(r[0]), float(r[1])) for r in rows]
    return out


def close_on(series: Sequence[tuple[date, float]], day: date) -> float | None:
    """The last close on or before *day* (a holiday carries the previous close); None when the
    series starts after *day*."""
    i = bisect_right([d for d, _ in series], day)
    return series[i - 1][1] if i else None


def latest_stored_ivs(con: sqlite3.Connection, symbols: Sequence[str]) -> dict[str, float]:
    """The latest unflagged ``iv_history`` row per symbol (a decimal); a symbol without one is left
    out. Same rule as ``iv_history.latest_iv``."""
    out: dict[str, float] = {}
    for sym in sorted({s.upper() for s in symbols}):
        try:
            row = con.execute(
                "SELECT iv FROM iv_history WHERE symbol = ? AND (flagged IS NULL OR flagged = 0) "
                "ORDER BY obs_date DESC LIMIT 1",
                (sym,),
            ).fetchone()
        except sqlite3.OperationalError:  # a database from before the sanity flag
            row = con.execute(
                "SELECT iv FROM iv_history WHERE symbol = ? ORDER BY obs_date DESC LIMIT 1", (sym,)
            ).fetchone()
        if row is not None and row[0] and float(row[0]) > 0:
            out[sym] = float(row[0])
    return out


def load_snapshot_at(
    con: sqlite3.Connection, when: datetime | None = None
) -> tuple[list[PositionSnapshot], AccountSnapshot, datetime] | None:
    """The newest ``portfolio_snapshots`` row at or before *when* (naive UTC; None = the newest):
    its positions and account block. None when there is none."""
    sql = "SELECT captured_at, account, positions FROM portfolio_snapshots"
    args: list[object] = []
    if when is not None:
        sql += " WHERE captured_at <= ?"
        args.append(when.strftime("%Y-%m-%d %H:%M:%S.%f"))
    row = con.execute(sql + " ORDER BY captured_at DESC, id DESC LIMIT 1", args).fetchone()
    if row is None:
        return None
    try:
        account = AccountSnapshot.model_validate(json.loads(row["account"]))
        positions = [PositionSnapshot.model_validate(p) for p in json.loads(row["positions"])]
    except (ValueError, TypeError):
        return None
    return positions, account, datetime.fromisoformat(str(row["captured_at"]))


def load_nlv_series(con: sqlite3.Connection) -> list[tuple[date, float]]:
    """The account's net liquidation, the last ``portfolio_snapshots`` reading of each ET day,
    ascending. Empty when there are none."""
    last: dict[date, float] = {}
    for row in con.execute(
        "SELECT captured_at, account FROM portfolio_snapshots ORDER BY captured_at, id"
    ):
        try:
            nlv = float(json.loads(row["account"]).get("net_liquidation") or 0.0)
            stamp = datetime.fromisoformat(str(row["captured_at"])).replace(tzinfo=UTC)
        except (ValueError, TypeError, AttributeError):
            continue
        if nlv > 0:
            last[stamp.astimezone(_ET).date()] = nlv
    return sorted(last.items())


def et_day(naive_utc: datetime) -> date:
    """The ET calendar day of a naive-UTC database timestamp."""
    return naive_utc.replace(tzinfo=UTC).astimezone(_ET).date()


def parse_stamp(raw: object) -> datetime:
    """A database timestamp column as a naive datetime."""
    return datetime.fromisoformat(str(raw))


# --- option arithmetic ----------------------------------------------------------------------


def strike_for_delta(
    spot: float, dte: int, iv: float, delta_abs: float, right: str, *, r: float = 0.05
) -> float | None:
    """The strike whose Black-Scholes delta has absolute value *delta_abs* (closed form, same
    ``r`` as ``black_scholes.bs_delta``); None on degenerate inputs."""
    if spot <= 0 or dte <= 0 or iv <= 0 or not 0.0 < delta_abs < 1.0:
        return None
    t = dte / 365.0
    d1 = float(norm.ppf(1.0 - delta_abs)) if right == "P" else float(norm.ppf(delta_abs))
    return float(spot * math.exp(-d1 * iv * math.sqrt(t) + (r + 0.5 * iv * iv) * t))


def drawdown_series(values: Sequence[float], window: int = 20) -> list[float]:
    """Each session's fall from the highest value of the trailing *window* sessions (the current
    one included), as a percent: the slow breaker's own measure (``circuit_breakers._slow_raw``)."""
    out: list[float] = []
    for i, v in enumerate(values):
        peak = max(values[max(0, i - window + 1) : i + 1])
        out.append(max(0.0, (peak - v) / peak * 100.0) if peak > 0 else 0.0)
    return out


def worst_drawdown(values: Sequence[float], window: int = 20) -> float:
    """The worst of ``drawdown_series``, a percent; 0.0 for a series that never falls."""
    return max(drawdown_series(values, window), default=0.0)


def sessions_between(a: date, b: date) -> int:
    """Calendar days from *a* to *b* (the aging ``line_pnl`` takes), never negative."""
    return max(0, (b - a).days)


# --- the result file ------------------------------------------------------------------------


def make_result(
    rid: str,
    *,
    passed: bool | None,
    criterion: str,
    metrics: Mapping[str, float | str | None],
    switch: str,
    value_on_pass: str,
    now: datetime | None = None,
) -> EnvelopeReportResult:
    """One ``EnvelopeReportResult`` (``passed`` None = insufficient data, which changes nothing)."""
    return EnvelopeReportResult(
        id=rid,
        passed=passed,
        criterion=criterion,
        metrics=dict(metrics),
        switch=switch,
        value_on_pass=value_on_pass,
        written_at=now or datetime.now(UTC),
    )


def write_result(result: EnvelopeReportResult, directory: Path | None = None) -> Path:
    """Write ``<id>.json`` under *directory* (default ``data/envelope_reports/``)."""
    target = directory if directory is not None else REPORTS_DIR
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{result.id}.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def write_report(name: str, text: str, directory: Path | None = None) -> Path:
    """Write the human-read report ``<name>_report.txt`` beside the result files. A ``.txt`` on
    purpose: ``apply_reports`` reads every ``*.json`` in the directory as a result file."""
    target = directory if directory is not None else REPORTS_DIR
    target.mkdir(parents=True, exist_ok=True)
    path = target / f"{name}_report.txt"
    path.write_text(text, encoding="utf-8")
    return path


def verdict_word(passed: bool | None) -> str:
    return {True: "PASS", False: "FAIL", None: "NO RESULT (insufficient data)"}[passed]


def daterange(start: date, end: date) -> list[date]:
    """Every calendar day from *start* to *end* inclusive."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# --- today's book, from the panel and the snapshot -------------------------------------------


def log_returns(series: Sequence[tuple[date, float]]) -> dict[date, float]:
    """Daily log returns of a close series, keyed by the later day."""
    out: dict[date, float] = {}
    for (_, a), (d, b) in zip(series, series[1:], strict=False):
        if a > 0 and b > 0:
            out[d] = math.log(b / a)
    return out


def panel_betas(
    closes: Closes, symbols: Sequence[str], *, vs: str = "SPY"
) -> tuple[dict[str, float], set[str]]:
    """Blume betas (0.67 b + 0.33) of *symbols* to *vs* from the panel's last
    ``envelope.beta_sessions`` returns, as ``shock_inputs.betas`` computes them from the store
    (the same ``_blume``); fewer than ``beta_min_sessions`` common sessions is the fallback beta,
    flagged, and SOXX borrows ``soxx_proxy``'s until it has its own."""
    cfg = get_envelope_cfg()
    bench = log_returns(closes.get(vs, []))
    own: dict[str, float | None] = {}

    def beta_of(sym: str) -> float | None:
        if sym not in own:
            own[sym] = _blume(
                log_returns(closes.get(sym, [])), bench, cfg.beta_sessions, cfg.beta_min_sessions
            )
        return own[sym]

    out: dict[str, float] = {}
    flagged: set[str] = set()
    for raw in symbols:
        sym = raw.upper()
        if sym in out:
            continue
        b = beta_of(sym)
        if b is None and sym == "SOXX" and cfg.soxx_proxy:
            b = beta_of(cfg.soxx_proxy.upper())
        if b is None:
            b = cfg.beta_fallback
            flagged.add(sym)
        out[sym] = b
    return out, flagged


@dataclass(frozen=True)
class BookContext:
    """Today's book as the replays see it: the snapshot, the panel and the stored IVs, and the
    ``ShockInputs`` built from them (betas from the panel, never the store)."""

    inputs: ShockInputs
    positions: list[PositionSnapshot]
    account: AccountSnapshot
    captured_at: datetime
    closes: Closes
    ivs: dict[str, float]
    names: list[str]  # the universe's actively_wheeling names
    held: list[str]  # every underlying the book holds
    flagged_betas: set[str]


def actively_wheeling() -> list[str]:
    return [str(s).upper() for s in (get_config().universe.get("actively_wheeling") or [])]


def load_book_context(
    con: sqlite3.Connection,
    *,
    asof: datetime | None = None,
    since: date | None = None,
    extra_symbols: Sequence[str] = (),
) -> BookContext:
    """Today's book (the newest snapshot at or before *asof*), the panel for everything it holds
    plus the actively-wheeling names, SPY, SMH and the governing indexes, and the inputs.

    Raises ``LookupError`` when there is no snapshot (a replay then has nothing to start from)."""
    got = load_snapshot_at(con, asof)
    if got is None:
        raise LookupError("no portfolio snapshot in the trading database")
    positions, account, captured = got
    cfg = get_envelope_cfg()
    held = sorted({(p.underlying or p.symbol).upper() for p in positions})
    names = actively_wheeling()
    governing = {k.upper(): v.upper() for k, v in cfg.governing.items()}
    wanted = sorted(
        {*held, *names, "SPY", "SMH", *governing.values(), *(s.upper() for s in extra_symbols)}
    )
    closes = load_closes(con, wanted, since)
    ivs = latest_stored_ivs(con, wanted)
    spots = {s: series[-1][1] for s, series in closes.items() if series}
    betas, flagged = panel_betas(closes, wanted)
    betas_smh, _ = panel_betas(closes, wanted, vs="SMH")
    inputs = build_inputs(
        positions,
        nlv=account.net_liquidation,
        value_by_name={},
        ivs=ivs,
        spots=spots,
        beta_map=betas,
        beta_smh_map=betas_smh,
        today=et_day(captured),
    )
    return BookContext(inputs, positions, account, captured, closes, ivs, names, held, flagged)
