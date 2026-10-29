"""The exit engine (spec §7): a deterministic state machine, one leg per policy. Pure: no I/O.

Evaluated once a day on the close; a sale the close signals fills at the next session's open.
Three policies run side by side on every shadow entry (spec §7):

- ``full``: the initial stop, the half-way arm into a Chandelier trail, half sold at fair
  value with the trail tightened, the peak signals, the thesis exits;
- ``value`` (pre-registered as the live policy): half sold at fair value; the rest only on a
  thesis exit, a fair value re-marked below the price, or the catastrophe stop;
- ``hold12``: 252 sessions, earlier only on a thesis exit or the catastrophe stop.

Every exit that would send without a tap reads **Python's** fair value only (revision 3). The
half-sale target reads the effective fair value (Python's on the baseline track; Claude's
clamped value on Part 4's track). An exit only the effective value would fire is a ``proposal``
event: it waits for a tap and sells nothing. Fair value is re-marked only when a new filing lands
(a new accession). §7.1's shock stops and re-evaluations are Part 3.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Literal

from pydantic import BaseModel

from src.common.config import ValueExitsCfg
from src.common.value_types import DayBar

Policy = Literal["full", "value", "hold12"]
POLICIES: tuple[Policy, Policy, Policy] = ("full", "value", "hold12")
EventKind = Literal[
    "arm",
    "half",
    "stop",
    "trail",
    "peak",
    "thesis",
    "remark",
    "remark_below",
    "catastrophe",
    "time",
    "proposal",
    "fill",
]
_DONE = 1e-9

Sell = Callable[[float, "EventKind", str], None]
Note = Callable[["EventKind", str], None]


class DayFacts(BaseModel):
    """What the night's scorecard says about the name. ``effective_fair_value`` equals Python's
    on the baseline track; Part 4's Claude track sets its own."""

    python_fair_value: float | None = None
    effective_fair_value: float | None = None
    latest_accn: str | None = None
    piotroski: float | None = None
    altman_z: float | None = None


class ExitEvent(BaseModel):
    day: date
    kind: EventKind
    price: float | None = None
    fraction: float = 0.0  # of the original position
    detail: str = ""


class LegState(BaseModel):
    """One policy's simulated holding of one shadow entry. Fractions are of the original
    position; ``proceeds`` is the sum of fraction x fill price."""

    policy: Policy
    entry_date: date
    entry_price: float
    fair_value: float | None  # Python's, re-marked only on a new filing
    effective_fair_value: float | None
    fv_accn: str | None
    stop: float | None = None
    armed: bool = False
    half_sold: bool = False
    above_fv_seen: bool = False  # a close at or above PYTHON's fair value (not the effective one)
    peak_proposed: bool = False  # the effective-only crossing has been noted once
    last_close: float | None = None  # the last stepped close: the split guard's reference
    rsi_hot: bool = False
    highest_close: float
    sessions: int = 0
    remaining: float = 1.0
    proceeds: float = 0.0
    pending: float = 0.0  # the fraction to sell at the next session's open
    pending_reason: str = ""
    sells: int = 0
    closed: bool = False
    exit_date: date | None = None
    peak_value: float = 1.0  # position value / cost, at its best close
    max_drawdown: float = 0.0  # a fraction, <= 0

    def exit_return(self) -> float | None:
        """Return over cost once every share is sold; None while any is held."""
        return self.proceeds / self.entry_price - 1.0 if self.closed else None


def open_leg(
    policy: Policy,
    *,
    entry_date: date,
    entry_price: float,
    atr14: float | None,
    fair_value: float | None,
    effective_fair_value: float | None,
    fv_accn: str | None,
    cfg: ValueExitsCfg,
) -> LegState:
    """The plan written at entry (spec §7). ``full`` starts with the initial stop: cost - 3 x
    ATR(14), never more than 15% below cost (the 15% floor alone when ATR is unknown)."""
    stop: float | None = None
    if policy == "full":
        floor = entry_price * (1.0 - cfg.initial_stop_max_pct / 100.0)
        stop = floor if atr14 is None else max(entry_price - cfg.initial_stop_atr * atr14, floor)
    return LegState(
        policy=policy,
        entry_date=entry_date,
        entry_price=entry_price,
        fair_value=fair_value,
        effective_fair_value=effective_fair_value,
        fv_accn=fv_accn,
        stop=stop,
        highest_close=entry_price,
    )


def step(
    state: LegState, day: DayBar, facts: DayFacts | None, cfg: ValueExitsCfg
) -> tuple[LegState, list[ExitEvent]]:
    """Advance one leg by one session: fill yesterday's signal at today's open, then read
    today's close. Never mutates *state*."""
    if state.closed:
        return state, []
    s = state.model_copy()
    events: list[ExitEvent] = []

    if s.pending > _DONE:
        price = day.open if day.open is not None else day.close
        fraction = min(s.pending, s.remaining)
        s.proceeds += fraction * price
        s.remaining -= fraction
        s.sells += 1
        events.append(
            ExitEvent(
                day=day.date, kind="fill", price=price, fraction=fraction, detail=s.pending_reason
            )
        )
        s.pending, s.pending_reason = 0.0, ""
        if s.remaining <= _DONE:
            s.remaining, s.closed, s.exit_date = 0.0, True, day.date
            return s, events

    close = day.close
    s.last_close = close
    s.sessions += 1
    s.highest_close = max(s.highest_close, close)
    value = (s.proceeds + s.remaining * close) / s.entry_price
    s.peak_value = max(s.peak_value, value)
    s.max_drawdown = min(s.max_drawdown, value / s.peak_value - 1.0)

    def sell(fraction: float, kind: EventKind, detail: str) -> None:
        s.pending = min(max(s.pending, fraction), s.remaining)
        s.pending_reason = kind
        events.append(
            ExitEvent(day=day.date, kind=kind, price=close, fraction=s.pending, detail=detail)
        )

    def note(kind: EventKind, detail: str) -> None:
        events.append(ExitEvent(day=day.date, kind=kind, price=close, detail=detail))

    # A new filing re-marks fair value, up or down (spec §7). Price and news never do.
    remarked = False
    if (
        facts is not None
        and facts.latest_accn is not None
        and facts.latest_accn != s.fv_accn
        and facts.python_fair_value is not None
    ):
        old = s.fair_value
        s.fair_value, s.fv_accn = facts.python_fair_value, facts.latest_accn
        s.effective_fair_value = (
            facts.effective_fair_value
            if facts.effective_fair_value is not None
            else facts.python_fair_value
        )
        remarked = True
        note("remark", f"fair value {old} -> {s.fair_value} ({facts.latest_accn})")

    # Thesis exits: every policy, Python's numbers only.
    if facts is not None:
        if facts.piotroski is not None and facts.piotroski <= cfg.thesis_piotroski_max:
            sell(s.remaining, "thesis", f"F-score {facts.piotroski:.0f}")
            return s, events
        if facts.altman_z is not None and facts.altman_z < cfg.thesis_altman_z_below:
            sell(s.remaining, "thesis", f"Altman Z {facts.altman_z:.2f}")
            return s, events
    bar = cfg.thesis_fv_below_price_pct / 100.0
    below_trend = day.sma50 is not None and close < day.sma50
    # Only on a session that re-marked fair value from a new filing (review I5): a static value
    # sitting below a price that ran past it is the ride, not an exit (ruling 14).
    if remarked and below_trend and s.fair_value is not None and s.fair_value < close * bar:
        sell(s.remaining, "thesis", f"fair value {s.fair_value:.2f} below {bar:.0%} of the price")
        return s, events
    if below_trend and s.effective_fair_value is not None and s.effective_fair_value < close * bar:
        note("proposal", "the effective fair value alone is below 90% of the price: a tap")

    if s.policy == "full":
        _full(s, close, day, cfg, sell, note)
    elif s.policy == "value":
        floor = s.entry_price * (1.0 - cfg.catastrophe_stop_pct / 100.0)
        if close <= floor:
            sell(s.remaining, "catastrophe", f"close {close:.2f} <= {floor:.2f}")
        elif remarked and s.fair_value is not None and s.fair_value < close:
            sell(s.remaining, "remark_below", f"re-marked {s.fair_value:.2f} below the price")
        else:
            if remarked and s.effective_fair_value is not None and s.effective_fair_value < close:
                note("proposal", "the effective fair value alone was re-marked below the price")
            _half_at_fair_value(s, close, cfg, sell)
    else:
        floor = s.entry_price * (1.0 - cfg.catastrophe_stop_pct / 100.0)
        if close <= floor:
            sell(s.remaining, "catastrophe", f"close {close:.2f} <= {floor:.2f}")
        elif s.sessions >= cfg.hold12_sessions:
            sell(s.remaining, "time", f"{s.sessions} sessions")
    return s, events


def _half_at_fair_value(s: LegState, close: float, cfg: ValueExitsCfg, sell: Sell) -> None:
    target = s.effective_fair_value
    if not s.half_sold and target is not None and close >= target:
        s.half_sold = True
        sell(cfg.half_sell_pct / 100.0, "half", f"close {close:.2f} >= fair value {target:.2f}")


def _full(
    s: LegState, close: float, day: DayBar, cfg: ValueExitsCfg, sell: Sell, note: Note
) -> None:
    if s.stop is not None and close < s.stop:
        kind: EventKind = "trail" if s.armed else "stop"
        sell(s.remaining, kind, f"close {close:.2f} < stop {s.stop:.2f}")
        return
    fv = s.fair_value
    if (
        not s.armed
        and fv is not None
        and fv > s.entry_price
        and close >= s.entry_price + cfg.arm_at_pct / 100.0 * (fv - s.entry_price)
    ):
        s.armed = True
        if s.stop is None or s.stop < s.entry_price:
            s.stop = s.entry_price  # armed: never below breakeven, even when ATR is unknown (M3)
        note("arm", f"close {close:.2f} past the half-way mark to {fv:.2f}")
    _half_at_fair_value(s, close, cfg, sell)
    # The peak signal and the 2 x ATR tightening sell without a tap, so they read Python's fair
    # value only (revision 3); a price that crossed just the effective value is one proposal.
    if fv is not None and close >= fv:
        s.above_fv_seen = True
    elif (
        s.effective_fair_value is not None
        and close >= s.effective_fair_value
        and not s.peak_proposed
    ):
        s.peak_proposed = True
        note("proposal", "the effective fair value alone is reached: a tap, no peak exit")
    if not s.armed:
        return
    k = cfg.trail_atr_after_half if s.half_sold and s.above_fv_seen else cfg.trail_atr
    if day.atr14 is not None:
        chandelier = max(s.highest_close - k * day.atr14, s.entry_price)
        if s.stop is None or chandelier > s.stop:
            s.stop = chandelier  # a stop is never lowered
    if day.rsi14 is not None and day.rsi14 > cfg.peak_rsi_high:
        s.rsi_hot = True
    off_peak = s.above_fv_seen and day.sma20 is not None and close < day.sma20
    rsi_turn = s.rsi_hot and day.rsi14 is not None and day.rsi14 < cfg.peak_rsi_cross
    if off_peak:
        sell(s.remaining, "peak", "a close below the 20-day SMA after fair value")
    elif rsi_turn:
        sell(s.remaining, "peak", f"RSI(14) back through {cfg.peak_rsi_cross:.0f}")


def benchmark_return(
    fills: list[tuple[date, float]], benchmark_open: dict[date, float], entry: float
) -> float | None:
    """What the same fractions would have made in the benchmark, bought at the entry session's
    open and sold at each fill's open. None when any fill date has no benchmark bar."""
    if entry <= 0 or not fills:
        return None
    proceeds = 0.0
    for day, fraction in fills:
        px = benchmark_open.get(day)
        if px is None:
            return None
        proceeds += fraction * px
    return proceeds / entry - 1.0
