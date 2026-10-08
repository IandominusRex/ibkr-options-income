"""The session tape and the entry trigger — OPG's "sell after the move", as rules.

The service samples the traded index every tick (``SessionSnapshot``: last price plus IBKR's
open / high / low / prior-close session stats) into a ``SessionTape``. ``trigger`` then decides
which side, if any, may be sold right now:

- a put spread only after price has dropped at least ``entry.min_move_em`` × the day's expected
  move below the higher of the prior close and today's high (so a gap down counts), and has
  made no new low for ``entry.stall_minutes``;
- a call spread only after the mirror-image rise has stalled;
- never against a move beyond ``entry.max_move_em`` × (a trend day: OPG's first loss);
- one side at a time: when both qualify, the side whose extreme is the most recent.

When the tape cannot say when the current high or low was made (the service started after it
printed), the stall clock starts at the first observation, so a restart can only delay an entry.
Pure: no IBKR, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from src.common.config import SpreadsCfg
from src.common.schemas import SessionSnapshot, SpreadSide, SpreadTrigger

_EPS = 1e-9
# When no side arms, the most informative reason is reported.
_RANK = {"no_move": 0, "still_moving": 1, "runaway_move": 2}


@dataclass
class SessionTape:
    """One ET session of the traded index, as this process has seen it."""

    day: date
    day_em: float | None = None  # the day's first expected move: the trigger's yardstick
    prior_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    high_at: datetime | None = None  # None: made before the first observation
    low_at: datetime | None = None
    first_seen: datetime | None = None
    last: float | None = None
    last_at: datetime | None = None

    def observe(self, snap: SessionSnapshot) -> None:
        first = self.first_seen is None
        if first:
            self.first_seen = snap.as_of
        if snap.prior_close is not None and snap.prior_close > 0:
            self.prior_close = snap.prior_close
        if snap.open is not None and snap.open > 0:
            self.open = snap.open
        hi = snap.last if snap.high is None else max(snap.high, snap.last)
        lo = snap.last if snap.low is None else min(snap.low, snap.last)
        if self.high is None or hi > self.high + _EPS:
            # On the first read, a session high above the last print was made at an unknown
            # earlier time. Any later new high was made since the previous read.
            self.high = hi
            self.high_at = snap.as_of if not first or snap.last >= hi - _EPS else None
        if self.low is None or lo < self.low - _EPS:
            self.low = lo
            self.low_at = snap.as_of if not first or snap.last <= lo + _EPS else None
        self.last, self.last_at = snap.last, snap.as_of

    def drop(self) -> float | None:
        """How far price sits below the higher of the prior close and today's high (≥ 0)."""
        if self.last is None or self.high is None:
            return None
        top = self.high if self.prior_close is None else max(self.high, self.prior_close)
        return max(0.0, top - self.last)

    def rise(self) -> float | None:
        """How far price sits above the lower of the prior close and today's low (≥ 0)."""
        if self.last is None or self.low is None:
            return None
        bottom = self.low if self.prior_close is None else min(self.low, self.prior_close)
        return max(0.0, self.last - bottom)

    def move_em(self, side: SpreadSide) -> float | None:
        """The move a *side* would sell against, in units of the day's expected move."""
        move = self.drop() if side == "put" else self.rise()
        if move is None or not self.day_em or self.day_em <= 0:
            return None
        return move / self.day_em

    def gap_pct(self) -> float | None:
        if self.open is None or not self.prior_close:
            return None
        return self.open / self.prior_close - 1.0

    def extreme_at(self, side: SpreadSide) -> datetime | None:
        """When the low (puts) or high (calls) was made; the first observation when unknown."""
        at = self.low_at if side == "put" else self.high_at
        return at if at is not None else self.first_seen


def trigger(tape: SessionTape | None, now: datetime, cfg: SpreadsCfg) -> SpreadTrigger:
    """Which side may be sold now. ``entry.trigger: always`` offers every configured side."""
    e = cfg.entry
    if e.trigger == "always":
        return SpreadTrigger(sides=list(cfg.selection.sides), reason="always")
    if tape is None or tape.last_at is None:
        return SpreadTrigger(reason="no_tape")
    if (now - tape.last_at).total_seconds() > e.max_tape_age_seconds:
        return SpreadTrigger(reason="stale_tape")
    if not tape.day_em or tape.day_em <= 0:
        return SpreadTrigger(reason="no_expected_move")
    armed: list[tuple[datetime, float, SpreadSide]] = []
    reason = "no_move"
    best: float | None = None
    for side in cfg.selection.sides:
        m = tape.move_em(side)
        if m is None:
            continue
        best = m if best is None else max(best, m)
        if m < e.min_move_em:
            continue
        if e.max_move_em is not None and m > e.max_move_em:
            why = "runaway_move"
        else:
            at = tape.extreme_at(side)
            if at is not None and (now - at).total_seconds() >= e.stall_minutes * 60:
                armed.append((at, m, side))
                continue
            why = "still_moving"
        if _RANK[why] > _RANK[reason]:
            reason = why
    if not armed:
        return SpreadTrigger(reason=reason, move_em=best)
    _, m, side = max(armed, key=lambda a: (a[0], a[1]))
    return SpreadTrigger(sides=[side], reason="armed", move_em=m)
