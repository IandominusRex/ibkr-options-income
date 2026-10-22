"""Replay the book's real CSP entries through the ladder and the regime limits (spec section 19).

Two uses of one engine:

* ``tests/test_week_replay.py`` -- the **hard gate** (ruling 38): the week-of-2026-10-13 entries that
  lost money (SOXL 100P, TQQQ 75P / 70P on Oct 13, TQQQ 68P on Oct 14) must be blocked by the rules
  as built, with the anchor and the loss-exit state built **only from the lots the replay itself let
  through**. The lots are written inline in the test; no test reads ``data/``.
* ``python -m scripts.replay_week --db PATH`` -- the same engine over the real entries of a window
  (default 2026-09-30..2026-10-20) read from the trading database **read-only**, printing per entry
  the regime, triggers, zone, the verdict and why, the size before and after, and the leg's P&L
  before and after, then the totals to compare with spec section 19.

What is replayed, in time order, with the real code and nothing re-implemented:

* the market regime each day through ``refresh_regime`` (``classify_base``, ``intraday_escalation``,
  the hysteresis) fed from daily bars; an intraday escalation uses the day's **low** (a look-ahead
  within the day: an entry before the move is judged under the regime of the move);
* ``build_sizing_context`` per entry (triggers, anchor, zone, recovery, loss exits of the day),
  from bars strictly **before** the entry's day;
* ``loss_exit_reason``, ``scale_in_reason``, the bottoming guards, the day's ``daily_limit`` and
  ``per_trade_cap`` (with the leveraged-ETF factor).

What is **not** replayed (first order, as in spec section 19): the regime's budget multiplier and the
guaranteed floor (the book's collateral is not rebuilt), premium / VRP / IV gates (no quotes), and
Claude's cut. Open legs are marked at **intrinsic value** (no option marks are stored), so P&L
figures are an approximation: compare shapes, not cents.

The engine writes to a scratch database only. ``main`` points the storage layer at a temporary file
before replaying; a caller of ``replay`` must have done the same (the tests use their tmp database).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from src.analytics.regime import fetch_daily_inputs
from src.common.config import get_config, get_regime_cfg
from src.common.schemas import (
    MarketRegime,
    OptionRight,
    PositionSnapshot,
    ScaleInZone,
    SizingContext,
)
from src.engine.regime_limits import (
    bottoming_guard,
    daily_limit,
    governing_index,
    loss_exit_reason,
    per_trade_cap,
    scale_in_reason,
    signal_lot,
)
from src.regime.anchors import et_date
from src.regime.context import build_sizing_context
from src.regime.refresh import clear_regime_cache, refresh_regime
from src.storage.db import session_scope
from src.storage.models import FillRow, OrderRow

REPO = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO / "tests" / "fixtures" / "week_2026_10_13"
HARD_MAX = 10  # cash_secured_put.max_contracts

BarsFn = Callable[[str], pd.DataFrame]


# --------------------------------------------------------------------------- #
# inputs and outputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReplayLot:
    """One CSP lot of the real book: an entry to judge, or history that only sets the state."""

    label: str
    symbol: str
    strike: float
    contracts: int
    at: datetime  # when the order was created (UTC, aware): the decision time
    spot: float  # the underlying at the entry (the order snapshot's ``ideal.spot``)
    expiry: date
    close_at: datetime | None = None  # the buy-to-close that ended it (UTC, aware), if any
    close_reason: str | None = None  # "loss_exit" | "profit_take" | "roll" | ...
    delta: float | None = None
    pnl: float | None = None  # realised + marked dollars of the REAL lot, full size
    history: bool = False  # state only (an older lot): never judged


@dataclass
class Decision:
    lot: ReplayLot
    allowed: bool
    reasons: list[str]
    contracts_after: int
    triggers: list[str] = field(default_factory=list)
    zone: ScaleInZone | None = None
    regimes: dict[str, MarketRegime] = field(default_factory=dict)

    @property
    def trimmed(self) -> bool:
        return self.allowed and self.contracts_after < self.lot.contracts

    @property
    def pnl_after(self) -> float | None:
        if self.lot.pnl is None:
            return None
        if not self.allowed:
            return 0.0
        return self.lot.pnl * self.contracts_after / max(self.lot.contracts, 1)


# --------------------------------------------------------------------------- #
# bars
# --------------------------------------------------------------------------- #


def fixture_bars(symbol: str) -> pd.DataFrame:
    """The committed week fixture (``VIX`` / ``^VIX`` and ``VIX3M`` / ``^VIX3M`` included)."""
    path = FIXTURE_DIR / f"{symbol.lstrip('^')}.csv"
    if not path.exists():
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    return pd.read_csv(path, index_col="Date", parse_dates=True)


def _before(frame: pd.DataFrame, day: date) -> pd.DataFrame:
    """Completed sessions strictly before *day*."""
    if frame.empty:
        return frame
    return frame[frame.index < pd.Timestamp(day)]


# --------------------------------------------------------------------------- #
# the regime, day by day
# --------------------------------------------------------------------------- #


def refresh_day(day: date, bars: BarsFn) -> Any:
    """Run the real ``refresh_regime`` for the ET *day* from daily bars (look-ahead: the day's low)."""
    now = datetime(day.year, day.month, day.day, 15, 0, tzinfo=UTC)  # 11:00 ET

    def fetch_daily(index: str) -> Any:
        return fetch_daily_inputs(index, bars=lambda sym: _before(bars(sym), day), today=day)  # type: ignore[arg-type]

    def fetch_live(
        index: str,
        prior_close: float | None,
        *,
        now: datetime,
        prior_vol_close: float | None = None,
    ) -> dict[str, Any]:
        frame = bars(index)
        stamp = pd.Timestamp(day)
        if frame.empty or stamp not in frame.index:
            return {
                "index_live": None,
                "day_change_pct": None,
                "live_vol": None,
                "stale": ["index_live", "day_change_pct", "live_vol"],
            }
        low = float(frame.loc[stamp, "Low"])
        vix = bars("^VIX")
        live_vol = float(vix.loc[stamp, "High"]) if stamp in vix.index else None
        change = round((low / prior_close - 1.0) * 100.0, 4) if prior_close else None
        stale = [n for n, v in (("day_change_pct", change), ("live_vol", live_vol)) if v is None]
        return {
            "index_live": round(low, 4),
            "day_change_pct": change,
            "live_vol": live_vol,
            "stale": stale,
        }

    return refresh_regime(
        now,
        fetch_daily=fetch_daily,
        fetch_live=fetch_live,
        fetch_bars=lambda sym: _before(bars(sym), day),
    )


# --------------------------------------------------------------------------- #
# scratch-database seeding
# --------------------------------------------------------------------------- #


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)


def _seed_lot(session: Any, lot: ReplayLot, contracts: int, seq: int) -> str:
    cid = f"replay{seq:04d}"
    snap = {
        "candidate_id": cid,
        "strategy": "cash_secured_put",
        "underlying": lot.symbol,
        "right": "P",
        "strike": lot.strike,
        "expiry": lot.expiry.isoformat(),
        "contracts": contracts,
        "ideal": {"spot": lot.spot},
    }
    order = OrderRow(
        candidate_id=cid,
        state="filled",
        filled_qty=float(contracts),
        snapshot=snap,
        created_at=_naive(lot.at),
    )
    session.add(order)
    session.flush()
    session.add(
        FillRow(
            order_id=order.id,
            candidate_id=cid,
            action="SELL",
            filled_qty=float(contracts),
            avg_price=1.0,
            filled_at=_naive(lot.at),
        )
    )
    session.flush()
    return cid


def _seed_close(session: Any, cid: str, lot: ReplayLot, contracts: int) -> None:
    """The buy-to-close the way production writes it: no snapshot on the close order."""
    assert lot.close_at is not None
    close = OrderRow(
        candidate_id=f"close:{lot.symbol}:{lot.expiry:%Y%m%d}:{lot.strike:g}:P",
        state="filled",
        filled_qty=float(contracts),
        close_reason=lot.close_reason,
        created_at=_naive(lot.close_at),
    )
    session.add(close)
    session.flush()
    session.add(
        FillRow(
            order_id=close.id,
            candidate_id=cid,
            action="BUY",
            filled_qty=float(contracts),
            avg_price=2.0,
            close_reason=lot.close_reason,
            filled_at=_naive(lot.close_at),
        )
    )
    session.flush()


# --------------------------------------------------------------------------- #
# the replay
# --------------------------------------------------------------------------- #


def replay(lots: list[ReplayLot], *, bars: BarsFn, hard_max: int = HARD_MAX) -> list[Decision]:
    """Judge each non-history lot in time order; return one `Decision` per judged lot.

    State is built only from what the replay let through: a lot enters the scratch database when
    it is allowed (at its trimmed size), and its close (a loss exit, a profit take) when its time
    comes. ``history`` lots are inserted as they were. Needs an isolated storage database (see the
    module docstring).
    """
    clear_regime_cache()
    decisions: list[Decision] = []
    pending: list[tuple[datetime, str, ReplayLot, int]] = []  # (close time, cid, lot, contracts)
    alive: list[tuple[ReplayLot, int]] = []  # lots inserted, with the size that went in
    last_day: date | None = None
    seq = 0

    for lot in sorted(lots, key=lambda x: x.at):
        day = et_date(lot.at)
        with session_scope() as session:
            # closes that happened before this entry (never after it: no look-ahead)
            for item in sorted([p for p in pending if p[0] <= lot.at], key=lambda p: p[0]):
                _seed_close(session, item[1], item[2], item[3])
                pending.remove(item)
        if day != last_day:
            refresh_day(day, bars)
            last_day = day

        if lot.history:
            seq += 1
            with session_scope() as session:
                cid = _seed_lot(session, lot, lot.contracts, seq)
            alive.append((lot, lot.contracts))
            if lot.close_at is not None:
                pending.append((lot.close_at, cid, lot, lot.contracts))
            continue

        positions = [
            PositionSnapshot(
                symbol=f"{a.symbol} {a.expiry:%y%m%d}P",
                sec_type="OPT",
                position=-float(n),
                avg_cost=1.0,
                right=OptionRight.PUT,
                strike=a.strike,
                expiry=a.expiry,
                underlying=a.symbol,
            )
            for a, n in alive
            if (a.close_at is None or a.close_at > lot.at) and a.expiry >= day
        ]
        with session_scope() as session:
            ctx = build_sizing_context(
                now=lot.at,
                session=session,
                symbols=[lot.symbol],
                positions=positions,
                bars={lot.symbol: _before(bars(lot.symbol), day)},
                spots={lot.symbol: lot.spot},
            )
        decision = _judge(lot, ctx, hard_max)
        decisions.append(decision)
        if decision.allowed:
            seq += 1
            with session_scope() as session:
                cid = _seed_lot(session, lot, decision.contracts_after, seq)
            alive.append((lot, decision.contracts_after))
            if lot.close_at is not None:
                pending.append((lot.close_at, cid, lot, decision.contracts_after))
    return decisions


def _judge(lot: ReplayLot, ctx: SizingContext | None, hard_max: int) -> Decision:
    if ctx is None:
        return Decision(lot, True, [], lot.contracts)
    reasons: list[str] = []
    cooldown = loss_exit_reason(ctx, lot.symbol)
    if cooldown:
        reasons.append(cooldown)
    not_reached = scale_in_reason(ctx, lot.symbol, lot.spot)
    if not_reached:
        reasons.append(not_reached)
    elif signal_lot(ctx, lot.symbol, lot.spot):
        guard = bottoming_guard(ctx, lot.symbol, lot.delta)
        if guard:
            reasons.append(guard)
    limit = daily_limit(ctx, lot.symbol)
    if (
        limit is not None
        and ctx.csp_opens_counted.get(governing_index(ctx, lot.symbol), 0) >= limit
    ):
        reasons.append("regime_daily_limit")
    cap = per_trade_cap(ctx, lot.symbol, hard_max)
    if cap == 0:
        reasons.append("regime_ceiling")
    allowed = not reasons
    return Decision(
        lot=lot,
        allowed=allowed,
        reasons=reasons,
        contracts_after=min(lot.contracts, cap) if allowed else 0,
        triggers=list(ctx.name_triggers.get(lot.symbol, [])),
        zone=ctx.scale_in.get(lot.symbol),
        regimes={
            "SPY": ctx.regimes.get("SPY", MarketRegime.NORMAL),
            "QQQ": ctx.regimes.get("QQQ", MarketRegime.NORMAL),
        },
    )


# --------------------------------------------------------------------------- #
# the real book (read-only)
# --------------------------------------------------------------------------- #


def _ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)


def _utc(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def db_bars(db: Path) -> BarsFn:
    """Daily bars: the committed fixture for the index and volatility series, the database's
    ``price_history`` (read-only) for every stock."""
    cache: dict[str, pd.DataFrame] = {}

    def fn(symbol: str) -> pd.DataFrame:
        key = symbol.upper()
        if key not in cache:
            if key in {"SPY", "QQQ", "^VIX", "^VIX3M", "VIX", "VIX3M"}:
                cache[key] = fixture_bars(key)
            else:
                con = _ro(db)
                try:
                    rows = con.execute(
                        "select obs_date, open, high, low, close, volume from price_history "
                        "where symbol = ? order by obs_date",
                        (key,),
                    ).fetchall()
                finally:
                    con.close()
                frame = pd.DataFrame(
                    rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"]
                )
                frame["Date"] = pd.to_datetime(frame["Date"])
                cache[key] = frame.set_index("Date")
        return cache[key]

    return fn


def _mark(bars: BarsFn, symbol: str, on: date) -> float | None:
    frame = bars(symbol)
    if frame.empty:
        return None
    frame = frame[frame.index <= pd.Timestamp(on)]
    return float(frame["Close"].iloc[-1]) if len(frame) else None


def load_lots(db: Path, start: date, end: date, *, bars: BarsFn, asof: date) -> list[ReplayLot]:
    """Every CSP lot filled in [*start* - 30 days, *end*] (older ones are history), from the DB.

    P&L: premium sold less any buy-back, in dollars; what is still open (or expired) is marked at
    intrinsic value on the expiry close, or on *asof* when not yet expired.
    """
    con = _ro(db)
    try:
        orders = con.execute(
            "select id, candidate_id, created_at, filled_qty, snapshot from orders "
            "where filled_qty > 0 and candidate_id not like 'close:%' and snapshot is not null "
            "and created_at >= ? and created_at < ? order by created_at",
            ((start - timedelta(days=30)).isoformat(), (end + timedelta(days=1)).isoformat()),
        ).fetchall()
        lots: list[ReplayLot] = []
        for oid, cid, created, qty, snap_text in orders:
            snap = json.loads(snap_text) if isinstance(snap_text, str) else None
            if not isinstance(snap, dict) or snap.get("strategy") != "cash_secured_put":
                continue
            ideal = snap.get("ideal") or {}
            spot = ideal.get("spot")
            if not spot:
                continue
            sells = con.execute(
                "select filled_qty, avg_price from fills where order_id = ? and action = 'SELL'",
                (oid,),
            ).fetchall()
            buys = con.execute(
                "select filled_qty, avg_price, filled_at, close_reason, commission from fills "
                "where candidate_id = ? and action = 'BUY' order by filled_at",
                (cid,),
            ).fetchall()
            sold = sum(q for q, _ in sells) or float(qty)
            credit = sum(q * p for q, p in sells) if sells else float(qty) * 0.0
            bought = sum(b[0] for b in buys)
            debit = sum(b[0] * b[1] for b in buys)
            commissions = sum((b[4] or 0.0) for b in buys)
            expiry = date.fromisoformat(str(snap["expiry"])[:10])
            strike = float(snap["strike"])
            pnl = (credit - debit) * 100.0 - commissions
            remaining = max(sold - bought, 0.0)
            if remaining > 0:  # still open or expired: marked at intrinsic value
                when = expiry if expiry <= asof else asof
                px = _mark(bars, str(snap["underlying"]), when)
                intrinsic = max(strike - px, 0.0) if px is not None else 0.0
                pnl -= remaining * intrinsic * 100.0
            closed = buys[-1] if buys and bought >= sold - 1e-9 else None
            lots.append(
                ReplayLot(
                    label=f"{snap['underlying']} {strike:g}P {created[5:10]}",
                    symbol=str(snap["underlying"]),
                    strike=strike,
                    contracts=int(round(float(qty))),
                    at=_utc(created) or datetime.now(UTC),
                    spot=float(spot),
                    expiry=expiry,
                    close_at=_utc(closed[2]) if closed else None,
                    close_reason=closed[3] if closed else None,
                    delta=snap.get("delta"),
                    pnl=pnl,
                    history=(_utc(created) or datetime.now(UTC)).date() < start,
                )
            )
        return lots
    finally:
        con.close()


def vrp_rejections(db: Path, start: date, end: date) -> dict[str, int]:
    """CSP candidates on SOXL / TQQQ the VRP gate refused in [start, end] (``premium_below_fair_value``)."""
    con = _ro(db)
    try:
        row = con.execute(
            "select count(*), count(distinct candidate_id), count(distinct run_id || symbol) "
            "from risk_verdicts where strategy = 'cash_secured_put' and symbol in ('SOXL','TQQQ') "
            "and reasons like '%premium_below_fair_value%' and created_at >= ? and created_at < ?",
            (start.isoformat(), (end + timedelta(days=1)).isoformat()),
        ).fetchone()
        total = con.execute(
            "select count(*) from risk_verdicts where strategy = 'cash_secured_put' "
            "and symbol in ('SOXL','TQQQ') and created_at >= ? and created_at < ?",
            (start.isoformat(), (end + timedelta(days=1)).isoformat()),
        ).fetchone()[0]
    finally:
        con.close()
    return {"rows": row[0], "contracts": row[1], "scans": row[2], "evaluated": total}


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #


def _fmt_zone(zone: ScaleInZone | None) -> str:
    return f"{zone.zone_low:.2f}-{zone.zone_high:.2f}" if zone else "-"


def print_report(decisions: list[Decision], *, week_from: date, vrp: dict[str, int] | None) -> None:
    print(
        f"{'entry':<22}{'regime':<12}{'triggers':<26}{'zone':<14}{'verdict':<10}{'size':<8}{'P&L before -> after'}"
    )
    for d in decisions:
        reg = f"{d.regimes.get('SPY', MarketRegime.NORMAL).value[:4]}/{d.regimes.get('QQQ', MarketRegime.NORMAL).value[:4]}"
        verdict = "allowed" if d.allowed else "BLOCKED"
        size = f"{d.lot.contracts}->{d.contracts_after}"
        before = f"{d.lot.pnl:+,.0f}" if d.lot.pnl is not None else "n/a"
        after = f"{d.pnl_after:+,.0f}" if d.pnl_after is not None else "n/a"
        why = "" if d.allowed else " " + ",".join(d.reasons)
        if d.trimmed:
            why = " trimmed"
        print(
            f"{d.lot.label:<22}{reg:<12}{','.join(d.triggers) or '-':<26}{_fmt_zone(d.zone):<14}{verdict:<10}{size:<8}{before} -> {after}{why}"
        )

    judged = decisions
    blocked = [d for d in judged if not d.allowed]
    trimmed = [d for d in judged if d.trimmed]
    before_c = sum(d.lot.contracts for d in judged)
    after_c = sum(d.contracts_after for d in judged)
    pnl_b = sum(d.lot.pnl or 0.0 for d in judged)
    pnl_a = sum(d.pnl_after or 0.0 for d in judged)
    losses_b = sum((d.lot.pnl or 0.0) for d in judged if d.lot.close_reason == "loss_exit")
    losses_a = sum((d.pnl_after or 0.0) for d in judged if d.lot.close_reason == "loss_exit")
    print()
    print(f"entries judged: {len(judged)}  blocked: {len(blocked)}  trimmed: {len(trimmed)}")
    print(f"contracts: {before_c} -> {after_c}")
    print(f"CSP P&L (realised + intrinsic marks): {pnl_b:+,.0f} -> {pnl_a:+,.0f}")
    print(f"loss exits: {losses_b:+,.0f} -> {losses_a:+,.0f}")
    week = [d for d in judged if d.lot.at.date() >= week_from]
    print(
        f"week of {week_from}: {len(week)} entries, {sum(1 for d in week if not d.allowed)} blocked"
    )
    if vrp is not None:
        print(
            "VRP gate (premium_below_fair_value) on SOXL/TQQQ CSPs, the week: "
            f"{vrp['rows']} of {vrp['evaluated']} evaluations, {vrp['contracts']} distinct contracts, "
            f"{vrp['scans']} scan/name pairs"
        )
    cfg = get_regime_cfg().csp
    hard = HARD_MAX
    s, c = MarketRegime.STRESSED, MarketRegime.CAUTIOUS
    fr = get_regime_cfg().csp.per_trade_fraction
    print(
        "an ease stressed -> cautious unlocks: guaranteed floor "
        f"{cfg.floor_new_per_day[s]} -> {cfg.floor_new_per_day[c]} lots/day/index, per-trade ceiling "
        f"{int(hard * fr[s] + 1e-9)} -> {int(hard * fr[c] + 1e-9)} contracts, daily limit "
        f"{cfg.max_new_per_day[s]} -> {cfg.max_new_per_day[c]}"
    )


def isolate_database() -> Path:
    """Point the storage layer at a throwaway SQLite file (never the trading database)."""
    import src.storage.db as dbmod

    tmp = Path(tempfile.mkdtemp(prefix="replay_week_")) / "replay.db"
    get_config().storage.db_url = f"sqlite:////{tmp.as_posix().lstrip('/')}"
    dbmod._engine = None
    dbmod._SessionLocal = None
    dbmod.init_db()
    return tmp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--db", required=True, type=Path, help="income_system.db (opened read-only)"
    )
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 10, 20))
    parser.add_argument("--week-from", type=date.fromisoformat, default=date(2026, 10, 13))
    parser.add_argument("--week-to", type=date.fromisoformat, default=date(2026, 10, 19))
    args = parser.parse_args(argv)

    isolate_database()
    bars = db_bars(args.db)
    lots = load_lots(args.db, args.start, args.end, bars=bars, asof=args.end)
    decisions = replay(lots, bars=bars)
    vrp = vrp_rejections(args.db, args.week_from, args.week_to)
    print_report(decisions, week_from=args.week_from, vrp=vrp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
