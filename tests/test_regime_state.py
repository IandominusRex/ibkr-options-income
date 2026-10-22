"""Persisted regime state, the refresh rules and the unsent-change queue (Task 2).

The trading database is a tmp file; the data fetchers are injected, so nothing here touches
the network.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.schemas import (
    IndexRegime,
    MarketRegime,
    RegimeChange,
    RegimeInputs,
    RegimeState,
)

N = MarketRegime.NORMAL
C = MarketRegime.CAUTIOUS
S = MarketRegime.STRESSED
X = MarketRegime.CRISIS

# Wed 2026-10-21 11:00 ET (RTH), then the following trading days and a Saturday.
DAY1 = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
DAY2 = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
DAY3 = datetime(2026, 10, 23, 15, 0, tzinfo=UTC)
SAT = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)
MON = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
TUE = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config
    from src.regime.refresh import clear_regime_cache

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    clear_regime_cache()
    yield
    clear_regime_cache()


def calm(streak: int = 5) -> RegimeInputs:
    return RegimeInputs(
        vol=15.0,
        vol_pct_1y=30,
        term_ratio=0.85,
        contango_streak=streak,
        index_close=700.0,
        sma50=690.0,
        sma200=650.0,
        drawdown_52w_pct=1.0,
        ret_1m_pct=2.0,
    )


def hot(vol: float = 40.0) -> RegimeInputs:
    return calm(streak=0).model_copy(update={"vol": vol, "term_ratio": 0.95})


CALM_LIVE = {"index_live": 701.0, "day_change_pct": 0.14, "live_vol": 15.2, "stale": []}
QQQ_DOWN_LIVE = {"index_live": 680.0, "day_change_pct": -2.85, "live_vol": 21.0, "stale": []}


class Feed:
    """Injected fetchers that record how often they were called."""

    def __init__(self, daily=None, live=None) -> None:
        self.daily = daily or {"SPY": calm(), "QQQ": calm()}
        self.live = live or {"SPY": CALM_LIVE, "QQQ": CALM_LIVE}
        self.daily_calls: list[str] = []
        self.live_calls: list[tuple[str, float | None]] = []

    def fetch_daily(self, index: str) -> RegimeInputs:
        self.daily_calls.append(index)
        return self.daily[index]

    def fetch_live(self, index: str, prior_close, *, now, prior_vol_close=None) -> dict:
        self.live_calls.append((index, prior_close))
        return dict(self.live[index])


def refresh(now: datetime, feed: Feed) -> RegimeState:
    from src.regime.refresh import refresh_regime

    return refresh_regime(now, fetch_daily=feed.fetch_daily, fetch_live=feed.fetch_live)


def _state(spy=N, qqq=N, *, base_date=date(2026, 10, 21), changes=None) -> RegimeState:
    def ir(index: str, r: MarketRegime) -> IndexRegime:
        return IndexRegime(
            index=index,  # type: ignore[arg-type]
            base=r,
            base_date=base_date,
            since=base_date,
            base_since=base_date,
            effective=r,
            inputs=calm(),
        )

    return RegimeState(as_of=DAY1, spy=ir("SPY", spy), qqq=ir("QQQ", qqq), changes=changes or [])


def _change(index="QQQ", before=N, after=S, sent=False) -> RegimeChange:
    return RegimeChange(index=index, before=before, after=after, why=["t"], at=DAY1, sent=sent)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #


def test_state_round_trips_through_system_settings():
    from src.storage.regime_state import load_regime_state, save_regime_state

    assert load_regime_state() is None
    st = _state(spy=C, qqq=S, changes=[_change()])
    save_regime_state(st)
    back = load_regime_state()
    assert back == st
    assert back is not None and back.qqq.effective == S and back.qqq.base_date == date(2026, 10, 21)


def test_a_corrupt_state_reads_as_none_not_an_error():
    from src.storage.regime_state import STATE_KEY, load_regime_state
    from src.storage.system_settings import set_setting

    set_setting(STATE_KEY, "{not json")
    assert load_regime_state() is None


def test_unsent_changes_round_trip():
    from src.storage.regime_state import (
        load_regime_state,
        mark_changes_sent,
        save_regime_state,
        unsent_changes,
    )

    assert unsent_changes() == []
    mark_changes_sent()  # nothing stored: a no-op, not an error
    save_regime_state(
        _state(changes=[_change(sent=True), _change("SPY", N, C), _change("QQQ", S, C)])
    )
    pending = unsent_changes()
    assert [c.index for c in pending] == ["SPY", "QQQ"]
    mark_changes_sent()
    assert unsent_changes() == []
    state = load_regime_state()
    assert state is not None and len(state.changes) == 3  # kept, only flagged sent


def test_mark_sent_leaves_a_change_appended_while_the_notice_was_in_flight():
    from src.storage.regime_state import mark_changes_sent, save_regime_state, unsent_changes

    first, second = _change("SPY", N, C), _change("QQQ", N, S)
    save_regime_state(_state(changes=[first]))
    in_flight = unsent_changes()
    save_regime_state(_state(changes=[first, second]))  # the order poll refreshed meanwhile
    mark_changes_sent(in_flight)
    assert [c.index for c in unsent_changes()] == ["QQQ"]


def test_suspension_lasts_until_the_next_trading_day():
    from src.storage.regime_state import regime_suspended, resume_regime, suspend_regime

    wed, thu = date(2026, 10, 21), date(2026, 10, 22)
    assert regime_suspended(wed) is False
    suspend_regime(wed)
    assert regime_suspended(wed) is True
    assert regime_suspended(thu) is False  # the next day's base is back under the limits
    resume_regime()
    assert regime_suspended(wed) is False


def test_concurrent_updates_do_not_lose_a_write():
    """Ruling 41: the scan thread and the order poll's to_thread both write the state."""
    from src.storage.regime_state import load_regime_state, save_regime_state, update_regime_state

    save_regime_state(_state())

    def appender(index: str):
        def fn(cur: RegimeState | None) -> RegimeState:
            assert cur is not None
            time.sleep(0.05)  # widen the window in which an unlocked writer would be overwritten
            return cur.model_copy(update={"changes": [*cur.changes, _change(index, N, S)]})

        return fn

    threads = [
        threading.Thread(target=update_regime_state, args=(appender(i),)) for i in ("SPY", "QQQ")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    final = load_regime_state()
    assert final is not None
    assert sorted(c.index for c in final.changes) == ["QQQ", "SPY"]


# --------------------------------------------------------------------------- #
# refresh
# --------------------------------------------------------------------------- #


def test_first_refresh_writes_state_and_one_change_per_index():
    from src.storage.regime_state import load_regime_state

    feed = Feed(daily={"SPY": hot(30.0), "QQQ": hot(30.0)})
    state = refresh(DAY1, feed)
    assert state.spy.base == S and state.qqq.base == S
    assert state.spy.effective == S
    assert sorted(c.index for c in state.changes) == ["QQQ", "SPY"]
    for c in state.changes:
        assert (c.before, c.after, c.sent) == (N, S, False)
        assert any("VIX 30.0" in w for w in c.why)
    assert load_regime_state() == state  # persisted, not just returned
    assert state.spy.base_since == date(2026, 10, 21) and state.spy.since == date(2026, 10, 21)


def test_first_refresh_on_a_calm_market_records_no_change():
    state = refresh(DAY1, Feed())
    assert state.spy.effective == N and state.qqq.effective == N
    assert state.changes == []


def test_base_recomputed_once_per_day():
    feed = Feed()
    refresh(DAY1, feed)
    refresh(DAY1 + timedelta(minutes=15), feed)
    refresh(DAY1 + timedelta(minutes=30), feed)
    assert sorted(feed.daily_calls) == ["QQQ", "SPY"]  # once per index, never again that day
    assert len(feed.live_calls) == 6  # live inputs are fetched on every call
    # ...and the live fetch measures against the stored daily close, not a refetch
    assert all(prior == 700.0 for _, prior in feed.live_calls)
    refresh(DAY2, feed)
    assert sorted(feed.daily_calls) == ["QQQ", "QQQ", "SPY", "SPY"]  # a new ET day refetches


def test_intraday_escalation_is_sticky_within_the_day():
    feed = Feed(live={"SPY": CALM_LIVE, "QQQ": QQQ_DOWN_LIVE})
    state = refresh(DAY1, feed)
    assert state.qqq.base == N and state.qqq.effective == S
    assert state.qqq.escalated_by == ["QQQ -2.9% today"]
    assert state.spy.effective == N
    assert [(c.index, c.after) for c in state.changes] == [("QQQ", S)]
    # the market bounces and the live input turns calm: the regime does not relax mid-day
    feed.live["QQQ"] = CALM_LIVE
    later = refresh(DAY1 + timedelta(hours=2), feed)
    assert later.qqq.effective == S
    assert later.qqq.escalated_by == ["QQQ -2.9% today"]
    assert len(later.changes) == 1  # no second notice for the same regime


def test_escalation_can_rise_but_never_fall_within_the_day():
    feed = Feed(live={"SPY": CALM_LIVE, "QQQ": QQQ_DOWN_LIVE})
    refresh(DAY1, feed)
    feed.live["QQQ"] = {**QQQ_DOWN_LIVE, "day_change_pct": -4.5}
    state = refresh(DAY1 + timedelta(minutes=30), feed)
    assert state.qqq.effective == X
    feed.live["QQQ"] = {**QQQ_DOWN_LIVE, "day_change_pct": -2.6}
    assert refresh(DAY1 + timedelta(hours=1), feed).qqq.effective == X


def test_restart_keeps_the_intraday_escalation():
    """Review Focus 3: a restart mid-day must not relax an escalated regime."""
    from src.regime.refresh import clear_regime_cache
    from src.storage.regime_state import load_regime_state

    feed = Feed(live={"SPY": CALM_LIVE, "QQQ": QQQ_DOWN_LIVE})
    refresh(DAY1, feed)
    # "new process": nothing in memory survives, only the database
    clear_regime_cache()
    assert load_regime_state() is not None
    fresh_feed = Feed(live={"SPY": CALM_LIVE, "QQQ": CALM_LIVE})  # the bounce is already in
    state = refresh(DAY1 + timedelta(hours=1), fresh_feed)
    assert state.qqq.effective == S
    assert fresh_feed.daily_calls == []  # the daily base was read from the state, not refetched


def test_a_stale_live_input_cannot_relax_an_escalated_regime():
    feed = Feed(live={"SPY": CALM_LIVE, "QQQ": QQQ_DOWN_LIVE})
    refresh(DAY1, feed)
    feed.live["QQQ"] = {
        "index_live": None,
        "day_change_pct": None,
        "live_vol": None,
        "stale": ["index_live", "day_change_pct", "live_vol"],
    }
    state = refresh(DAY1 + timedelta(hours=1), feed)
    assert state.qqq.effective == S
    assert "day_change_pct" in state.qqq.inputs.stale


def test_a_stricter_daily_base_takes_effect_at_once():
    feed = Feed()
    refresh(DAY1, feed)
    feed.daily = {"SPY": hot(30.0), "QQQ": hot(30.0)}
    state = refresh(DAY2, feed)
    assert state.spy.base == S and state.spy.effective == S
    assert state.spy.base_since == date(2026, 10, 22)
    assert state.spy.since == date(2026, 10, 22)


def test_next_day_base_eases_only_after_contango_streak_and_min_days():
    feed = Feed(daily={"SPY": hot(40.0), "QQQ": hot(40.0)})
    state = refresh(DAY1, feed)
    assert state.spy.base == X

    # day 2: calm numbers but only one contango close: the base stands
    feed.daily = {"SPY": calm(streak=1), "QQQ": calm(streak=1)}
    assert refresh(DAY2, feed).spy.base == X

    # a long streak is not enough on its own: the base has been CRISIS for 1 day, minimum is 2
    feed.daily = {"SPY": calm(streak=5), "QQQ": calm(streak=5)}
    state = refresh(DAY2 + timedelta(hours=1), feed)  # same ET day: daily base is not recomputed
    assert state.spy.base == X

    # day 3: streak 5 and 2 days since the base last changed: eases (one notch)
    state = refresh(DAY3, feed)
    assert state.spy.base == S
    assert state.spy.base_since == date(2026, 10, 23)


def test_easing_is_one_notch_at_a_time():
    feed = Feed(daily={"SPY": hot(40.0), "QQQ": hot(40.0)})
    refresh(DAY1, feed)
    feed.daily = {"SPY": calm(streak=6), "QQQ": calm(streak=6)}
    refresh(DAY2, feed)
    state = refresh(DAY3, feed)
    assert state.spy.base == S  # CRISIS -> STRESSED, never straight to NORMAL
    assert state.spy.effective == S
    # the Saturday refresh classifies nothing (market closed)
    refresh(SAT, feed)
    # Monday: 3 days since the last base change: one more notch
    state = refresh(MON, feed)
    assert state.spy.base == C
    # Tuesday: only 1 day since: the clock restarted, so no further easing yet
    state = refresh(TUE, feed)
    assert state.spy.base == C


def test_intraday_escalation_expires_at_the_next_day():
    """Ruling 40: a single -2.85% QQQ day must not hold tech names restricted for days."""
    feed = Feed(live={"SPY": CALM_LIVE, "QQQ": QQQ_DOWN_LIVE})
    state = refresh(DAY1, feed)
    assert state.qqq.effective == S and state.qqq.base == N
    feed.live["QQQ"] = CALM_LIVE
    state = refresh(DAY2, feed)  # daily inputs calm, live calm
    assert state.qqq.effective == N
    assert state.qqq.escalated_by == []
    assert state.qqq.since == date(2026, 10, 22)
    assert [(c.index, c.before, c.after) for c in state.changes] == [
        ("QQQ", N, S),
        ("QQQ", S, N),
    ]


def test_a_non_trading_day_does_not_recompute_the_base():
    feed = Feed()
    refresh(DAY3, feed)  # Friday
    feed.daily_calls.clear()
    state = refresh(SAT, feed)
    assert feed.daily_calls == []  # the market is closed: nothing new to classify
    assert state.spy.base_date == date(2026, 10, 24)  # but the day is rolled over
    assert state.spy.effective == N


def test_a_weekend_refresh_expires_fridays_intraday_escalation():
    feed = Feed(live={"SPY": CALM_LIVE, "QQQ": QQQ_DOWN_LIVE})
    state = refresh(DAY3, feed)  # Friday: QQQ -2.9% on the day
    assert state.qqq.effective == S
    feed.live["QQQ"] = CALM_LIVE
    state = refresh(SAT, feed)  # a new ET day, even though no session was classified
    assert state.qqq.effective == N and state.qqq.escalated_by == []
    assert [c.after for c in state.changes if c.index == "QQQ"] == [S, N]


def test_missing_inputs_keep_the_last_known_regime():
    """Review Focus 2: yfinance down must not make the regime read as calm."""
    from src.storage.regime_state import save_regime_state

    prev = _state(spy=C, qqq=S, base_date=date(2026, 10, 20))
    save_regime_state(prev)
    nothing = RegimeInputs(stale=["index_close", "vol", "vol_pct_1y", "term_ratio"])
    feed = Feed(daily={"SPY": nothing, "QQQ": nothing})
    state = refresh(DAY1, feed)
    assert state.spy.effective == C and state.qqq.effective == S
    assert state.spy.base_date == date(2026, 10, 20)  # not marked as computed today
    assert state.changes == []
    # ...and it retries on the next call, since today's base was never computed
    refresh(DAY1 + timedelta(minutes=15), feed)
    assert feed.daily_calls.count("SPY") == 2


def test_a_raising_fetch_keeps_the_last_known_regime():
    from src.storage.regime_state import save_regime_state

    save_regime_state(_state(spy=C, qqq=S, base_date=date(2026, 10, 20)))
    feed = Feed()

    def boom(index: str) -> RegimeInputs:
        raise RuntimeError("provider down")

    from src.regime.refresh import refresh_regime

    state = refresh_regime(DAY1, fetch_daily=boom, fetch_live=feed.fetch_live)
    assert state.spy.effective == C and state.qqq.effective == S


def test_no_data_and_no_state_is_normal_flagged_and_retried():
    nothing = RegimeInputs(stale=["index_close", "vol", "vol_pct_1y", "term_ratio"])
    feed = Feed(daily={"SPY": nothing, "QQQ": nothing})
    state = refresh(DAY1, feed)
    assert state.spy.effective == N and state.spy.escalated_by == ["no_data"]
    assert state.changes == []
    refresh(DAY1 + timedelta(minutes=15), feed)
    assert feed.daily_calls.count("SPY") == 2  # still retried: the base was not "computed today"


def test_refresh_cached_reuses_within_max_age(monkeypatch):
    import src.regime.refresh as mod

    calls: list[datetime] = []

    def fake_refresh(now, **kw):
        calls.append(now)
        return _state()

    monkeypatch.setattr(mod, "refresh_regime", fake_refresh)
    first = mod.refresh_regime_cached(DAY1)
    second = mod.refresh_regime_cached(DAY1 + timedelta(seconds=5))
    assert first is second and len(calls) == 1
    # an expired entry refreshes again
    assert mod.refresh_regime_cached(DAY1 + timedelta(minutes=5), max_age_s=0.0) is not None
    assert len(calls) == 2


def test_refresh_cached_falls_back_to_the_last_known_state(monkeypatch):
    import src.regime.refresh as mod
    from src.storage.regime_state import save_regime_state

    save_regime_state(_state(spy=C))

    def boom(now, **kw):
        raise RuntimeError("db locked")

    monkeypatch.setattr(mod, "refresh_regime", boom)
    state = mod.refresh_regime_cached(DAY1)
    assert state is not None and state.spy.effective == C
