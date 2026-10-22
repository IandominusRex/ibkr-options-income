"""The week-of-2026-10-13 replay: a pass/fail gate for the ladder (ruling 38, spec decision 35).

The week's entries that lost money must be blocked by the rules **as built**, with the anchor and
the loss-exit state built only from the lots the replay itself lets through. Real daily bars
(`tests/fixtures/week_2026_10_13`); the lots are the order snapshots' own numbers, written inline
(read once from the trading database on 2026-10-20; no test reads ``data/``).

    If any of the four is not blocked by the rules as written: STOP, report which and why --
    never loosen, delete, skip or xfail these tests to get green.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from scripts.replay_week import Decision, ReplayLot, replay
from src.common.config import get_config
from src.common.schemas import MarketRegime
from tests.conftest import week_bars

N = MarketRegime.NORMAL
S = MarketRegime.STRESSED


def at(month: int, day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, month, day, hh, mm, tzinfo=UTC)


# --- history: the lots that were open when the week started ---------------------------------
SOXL_130P = ReplayLot(
    label="SOXL 130P 10-08",
    symbol="SOXL",
    strike=130.0,
    contracts=2,
    at=at(10, 8, 17, 48),
    spot=140.19,
    expiry=date(2026, 10, 16),
    close_at=at(10, 13, 13, 34),  # the loss exit
    close_reason="loss_exit",
    history=True,
)
TQQQ_78P = ReplayLot(
    label="TQQQ 78P 10-07",
    symbol="TQQQ",
    strike=78.0,
    contracts=10,
    at=at(10, 7, 13, 51),
    spot=81.79,
    expiry=date(2026, 10, 16),
    close_at=at(10, 14, 15, 15),  # the loss exit
    close_reason="loss_exit",
    history=True,
)

# --- the entries the ladder exists to stop -------------------------------------------------
SOXL_100P = ReplayLot(
    label="SOXL 100P 10-13",
    symbol="SOXL",
    strike=100.0,
    contracts=1,
    at=at(10, 13, 13, 50),
    spot=122.93,
    expiry=date(2026, 11, 6),
    close_at=at(10, 15, 13, 31),
    close_reason="loss_exit",
)
TQQQ_75P = ReplayLot(
    label="TQQQ 75P 10-13",
    symbol="TQQQ",
    strike=75.0,
    contracts=10,
    at=at(10, 13, 16, 2),
    spot=78.12,
    expiry=date(2026, 10, 23),
    close_at=at(10, 14, 16, 18),
    close_reason="loss_exit",
)
TQQQ_70P = ReplayLot(
    label="TQQQ 70P 10-13",
    symbol="TQQQ",
    strike=70.0,
    contracts=2,
    at=at(10, 13, 16, 18),
    spot=78.41,
    expiry=date(2026, 11, 6),
    close_at=at(10, 15, 13, 46),
    close_reason="loss_exit",
)
TQQQ_68P = ReplayLot(
    label="TQQQ 68P 10-14",
    symbol="TQQQ",
    strike=68.0,
    contracts=5,
    at=at(10, 14, 17, 9),
    spot=74.72,
    expiry=date(2026, 10, 30),
    close_at=at(10, 16, 18, 17),
    close_reason="loss_exit",
)
WEEK = [SOXL_130P, TQQQ_78P, SOXL_100P, TQQQ_75P, TQQQ_70P, TQQQ_68P]


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def bars(symbol: str):
    return week_bars(symbol)


def run(lots: list[ReplayLot] | None = None) -> dict[str, Decision]:
    decisions = replay(list(lots if lots is not None else WEEK), bars=bars)
    return {d.lot.label: d for d in decisions}


# --------------------------------------------------------------------------- #
# the market regime that week (the replay drives the real refresh_regime)
# --------------------------------------------------------------------------- #


def regime_on(day: date):
    """The persisted regime after running the real refresh for each day up to *day*."""
    from scripts.replay_week import refresh_day
    from src.regime.refresh import clear_regime_cache

    clear_regime_cache()
    state = None
    d = date(2026, 10, 12)
    while d <= day:
        if d.weekday() < 5:
            state = refresh_day(d, bars)
        d = date.fromordinal(d.toordinal() + 1)
    assert state is not None
    return state


def test_spy_regime_normal_oct_13_to_15():
    for d in (date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)):
        state = regime_on(d)
        assert state.spy.effective == N, (d, state.spy.escalated_by, state.spy.inputs)


def test_qqq_base_regime_on_oct_14_is_what_the_rules_say():
    # with the VIX for both indices (ruling 15): NORMAL -- the VIX stayed in the teens, the curve
    # was in contango and the slow rule does not fire (sma50 under the close, the month up)
    state = regime_on(date(2026, 10, 14))
    assert state.qqq.base == N
    assert state.qqq.effective == N


def test_qqq_escalates_to_stressed_intraday_oct_16():
    # the day's change at the low = Low / prior close - 1 = 707.23 / 728.00 - 1 = -2.85%
    state = regime_on(date(2026, 10, 16))
    assert state.qqq.base == N
    assert state.qqq.effective == S
    assert state.qqq.escalated_by == ["QQQ -2.9% today"]
    assert state.spy.effective == N  # SPY never reached its -2% line


# --------------------------------------------------------------------------- #
# the ladder over the real week
# --------------------------------------------------------------------------- #


def test_soxl_and_tqqq_get_a_zone_after_their_loss_exits():
    out = run()
    soxl = out[SOXL_100P.label]
    assert soxl.zone is not None and soxl.zone.anchor == 140.19
    assert soxl.zone.zone_high <= 140.19 * (1 - 0.05)  # at least the minimum gap below the last lot
    assert "recent_loss_exit" in soxl.triggers or "name_drawdown" in soxl.triggers
    tqqq = out[TQQQ_68P.label]
    assert (
        tqqq.zone is not None and tqqq.zone.anchor == 81.79
    )  # the blocked re-entries never moved it
    assert tqqq.zone.zone_high <= 81.79 * (1 - 0.05)
    assert "recent_loss_exit" in tqqq.triggers


def test_each_later_lot_needs_a_lower_price_than_the_last():
    # hypothetical: a lot inside the first zone is allowed and becomes the anchor; the very next
    # lot at the same price is blocked -- the one after needs a price a gap lower still
    inside = ReplayLot(
        label="TQQQ 72P hypothetical",
        symbol="TQQQ",
        strike=72.0,
        contracts=1,
        at=at(10, 13, 16, 2),
        spot=76.0,
        expiry=date(2026, 10, 23),
    )
    again = ReplayLot(
        label="TQQQ 72P again",
        symbol="TQQQ",
        strike=72.0,
        contracts=1,
        at=at(10, 13, 16, 18),
        spot=76.0,
        expiry=date(2026, 10, 23),
    )
    out = run([SOXL_130P, TQQQ_78P, inside, again])
    assert out[inside.label].allowed is True, out[inside.label].reasons
    second = out[again.label]
    assert second.allowed is False and "scale_in_zone_not_reached" in second.reasons
    assert second.zone is not None and second.zone.anchor == 76.0
    assert second.zone.zone_high <= 76.0 * (1 - 0.05)


# --------------------------------------------------------------------------- #
# THE HARD GATE (ruling 38; spec decision 35)
# --------------------------------------------------------------------------- #
# Each entry is replayed in time order through loss_exit_reason, the triggers, compute_zone and
# scale_in_reason, with the anchor and the loss-exit state built only from lots the replay itself
# let through. Each must be blocked.
# If any of the four is not blocked by the rules as written: STOP, report which and why -- never
# loosen or delete these tests to get green.


def test_replay_blocks_soxl_100p_on_oct_13():
    d = run()[SOXL_100P.label]  # loss_exit_cooldown: the SOXL 130P was stopped at 13:34 UTC
    assert d.allowed is False
    assert "loss_exit_cooldown" in d.reasons


def test_replay_blocks_tqqq_75p_on_oct_13():
    d = run()[TQQQ_75P.label]  # near_money_put on the 78P; spot 78.12 is above the zone
    assert d.allowed is False
    assert "near_money_put" in d.triggers
    assert d.zone is not None and 78.12 > d.zone.zone_high
    assert "scale_in_zone_not_reached" in d.reasons


def test_replay_blocks_tqqq_70p_on_oct_13():
    d = run()[TQQQ_70P.label]  # same trigger; recovery ignores the closes from before the anchor
    assert d.allowed is False
    assert "near_money_put" in d.triggers
    assert d.zone is not None and 78.41 > d.zone.zone_high
    assert "scale_in_zone_not_reached" in d.reasons


def test_replay_blocks_tqqq_68p_on_oct_14():
    d = run()[TQQQ_68P.label]  # loss_exit_cooldown: the 78P was stopped the same day
    assert d.allowed is False
    assert "loss_exit_cooldown" in d.reasons


def test_the_replay_builds_its_state_only_from_lots_it_let_through():
    out = run()
    assert [
        out[k].allowed for k in (SOXL_100P.label, TQQQ_75P.label, TQQQ_70P.label, TQQQ_68P.label)
    ] == [
        False,
        False,
        False,
        False,
    ]
    # nothing blocked ever became an anchor: TQQQ's anchor on Oct 14 is still the 78P (81.79)
    assert out[TQQQ_68P.label].zone is not None and out[TQQQ_68P.label].zone.anchor == 81.79


def test_the_replay_uses_the_shipped_config():
    ladder = get_config().risk["regime"]["ladder"]
    assert ladder["near_money_atr"] == 0.5 and ladder["loss_exit_same_day_block"] is True
