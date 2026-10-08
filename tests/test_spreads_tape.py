from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import SessionSnapshot
from src.spreads.tape import SessionTape, trigger

TODAY = date(2026, 10, 7)
_BASE = get_config().spreads
# Pinned explicitly so a YAML retune never silently changes these tests.
CFG = _BASE.model_copy(
    update={
        "selection": _BASE.selection.model_copy(update={"sides": ["put", "call"]}),
        "entry": _BASE.entry.model_copy(
            update={
                "trigger": "move",
                "min_move_em": 0.5,
                "max_move_em": 1.5,
                "stall_minutes": 10,
                "max_tape_age_seconds": 120.0,
            }
        ),
    }
)


def et(hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(2026, 10, 7, h + 4, m, tzinfo=UTC)  # EDT = UTC−4


def snap(
    hhmm: str, last: float, *, high=None, low=None, open_=692.0, prior=693.5
) -> SessionSnapshot:
    return SessionSnapshot(
        as_of=et(hhmm), last=last, open=open_, high=high, low=low, prior_close=prior
    )


def flush_tape() -> SessionTape:
    """Prior close 693.5, opens 692.0, flushes to 689.8 at 09:36, then holds above it."""
    tape = SessionTape(day=TODAY, day_em=5.8)
    tape.observe(snap("09:31", 692.0, high=692.2, low=691.9))
    tape.observe(snap("09:36", 689.8, high=692.2, low=689.8))
    tape.observe(snap("09:41", 690.4, high=692.2, low=689.8))
    return tape


def test_observe_tracks_the_session_and_when_extremes_were_made() -> None:
    tape = flush_tape()
    assert (tape.prior_close, tape.open, tape.high, tape.low) == (693.5, 692.0, 692.2, 689.8)
    assert tape.high_at is None  # 692.2 printed before the first observation
    assert tape.extreme_at("call") == et("09:31")  # unknown → the first observation
    assert tape.low_at == et("09:36") and tape.extreme_at("put") == et("09:36")
    assert tape.last == 690.4 and tape.last_at == et("09:41")
    assert tape.gap_pct() == pytest.approx(692.0 / 693.5 - 1)


def test_drop_counts_the_gap_from_the_prior_close_and_rise_mirrors_it() -> None:
    tape = flush_tape()
    assert tape.drop() == pytest.approx(693.5 - 690.4)
    assert tape.rise() == pytest.approx(690.4 - 689.8)
    assert tape.move_em("put") == pytest.approx((693.5 - 690.4) / 5.8)


def test_a_missing_session_stat_never_wipes_a_known_one() -> None:
    tape = flush_tape()
    tape.observe(SessionSnapshot(as_of=et("09:42"), last=690.5))
    assert (tape.prior_close, tape.open, tape.low) == (693.5, 692.0, 689.8)


def test_puts_arm_only_after_the_flush_has_stalled() -> None:
    tape = flush_tape()
    early = trigger(tape, et("09:41"), CFG)
    assert early.sides == [] and early.reason == "still_moving"
    tape.observe(snap("09:47", 690.0, high=692.2, low=689.8))
    armed = trigger(tape, et("09:47"), CFG)
    assert armed.sides == ["put"] and armed.reason == "armed"
    assert armed.move_em == pytest.approx((693.5 - 690.0) / 5.8)


def test_a_small_move_never_arms() -> None:
    tape = SessionTape(day=TODAY, day_em=5.8)
    tape.observe(snap("09:31", 693.4, high=693.6, low=693.2, open_=693.5))
    tape.observe(snap("09:50", 693.0, high=693.6, low=692.9, open_=693.5))
    t = trigger(tape, et("09:50"), CFG)
    assert t.sides == [] and t.reason == "no_move"


def test_a_runaway_move_is_a_trend_day_and_never_faded() -> None:
    tape = SessionTape(day=TODAY, day_em=4.0)
    tape.observe(snap("09:31", 690.0, high=690.0, low=690.0, open_=690.0, prior=690.0))
    tape.observe(snap("09:40", 682.0, high=690.0, low=682.0, open_=690.0, prior=690.0))
    tape.observe(snap("09:55", 683.0, high=690.0, low=682.0, open_=690.0, prior=690.0))
    t = trigger(tape, et("09:55"), CFG)
    assert t.sides == [] and t.reason == "runaway_move"  # 7 points = 1.75 × the expected move


def test_both_sides_moved_picks_the_most_recent_stalled_extreme() -> None:
    tape = SessionTape(day=TODAY, day_em=6.0)
    tape.observe(snap("09:31", 689.0, high=689.2, low=688.9, open_=690.0, prior=690.0))
    tape.observe(snap("09:33", 686.0, high=689.2, low=686.0, open_=690.0, prior=690.0))
    tape.observe(snap("09:40", 694.0, high=694.0, low=686.0, open_=690.0, prior=690.0))
    tape.observe(snap("10:00", 690.0, high=694.0, low=686.0, open_=690.0, prior=690.0))
    t = trigger(tape, et("10:00"), CFG)
    assert t.sides == ["call"] and t.reason == "armed"  # the 09:40 high is newer than the 09:33 low


def test_always_mode_offers_every_configured_side() -> None:
    always = CFG.model_copy(update={"entry": CFG.entry.model_copy(update={"trigger": "always"})})
    t = trigger(None, et("10:00"), always)
    assert t.sides == ["put", "call"] and t.reason == "always"


# Review Focus 7 — no tape, a stale tape, or no yardstick never arms.
def test_missing_or_stale_inputs_never_arm() -> None:
    assert trigger(None, et("09:47"), CFG).reason == "no_tape"
    tape = flush_tape()
    tape.observe(snap("09:47", 690.0, high=692.2, low=689.8))
    assert trigger(tape, et("09:50"), CFG).reason == "stale_tape"  # 180 s old
    tape.day_em = None
    assert trigger(tape, et("09:47"), CFG).reason == "no_expected_move"


# Review Focus 6 — a restart mid-move waits a full stall window from its first observation.
def test_a_restart_cannot_hurry_an_entry() -> None:
    tape = SessionTape(day=TODAY, day_em=5.8)
    tape.observe(snap("10:00", 690.0, high=692.2, low=689.8))  # the low was made before we started
    assert tape.low_at is None
    assert trigger(tape, et("10:00"), CFG).reason == "still_moving"
    tape.observe(snap("10:05", 690.1, high=692.2, low=689.8))
    assert trigger(tape, et("10:05"), CFG).reason == "still_moving"
    tape.observe(snap("10:10", 690.2, high=692.2, low=689.8))
    assert trigger(tape, et("10:10"), CFG).sides == ["put"]
