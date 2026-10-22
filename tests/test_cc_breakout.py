"""The covered-call breakout rule (Task 16; spec section 17, decisions 28 and 39).

After an upside breakout a held name's covered-call strikes are pushed out for a few sessions:
the strike must clear a floor and the delta must stay under a cap. Deterministic only: the
resistance detector (`support_levels.resistance_levels`), the breakout detector
(`analytics/breakout.py`), the pure gate function (`engine/regime_limits.cc_timing_reasons`),
the generator and the Rules Engine. A call is pushed out (when nothing clears the floor and the
delta cap, none is sold on that name that scan); nothing here loosens a strike or sizes.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.analytics.breakout import breakout, cc_floor
from src.analytics.support_levels import resistance_levels
from src.analytics.technicals import _atr14, atr14_series
from src.common.config import (
    CcBreakoutCfg,
    get_cc_timing_cfg,
    get_config,
)
from src.common.market_hours import today_et
from src.common.schemas import (
    CcBreakout,
    FundamentalStats,
    IVStats,
    MarketRegime,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    SizingContext,
    Strategy,
    TechnicalStats,
    Verdict,
)
from src.engine.regime_limits import cc_timing_reasons
from src.engine.risk_engine import validate_candidates
from src.strategies._evaluation import ScreenResult
from src.strategies.covered_call import screen_cc_candidates
from tests.test_engine import _account, _candidate

N = MarketRegime.NORMAL
_EXPIRY = date.today() + timedelta(days=24)


def set_risk(monkeypatch, **blocks) -> None:
    cfg = get_config()
    risk = dict(cfg.risk)
    risk.update(blocks)
    monkeypatch.setattr(cfg, "risk", risk)


# --------------------------------------------------------------------------- #
# Synthetic bars
# --------------------------------------------------------------------------- #


def make_bars(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
    *,
    end: date = date(2026, 10, 19),
) -> pd.DataFrame:
    """Daily bars ending on *end* (business days). High/low default to close +/- 0.5."""
    n = len(closes)
    index = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    close = pd.Series(closes, index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": pd.Series(highs, index=index, dtype=float)
            if highs is not None
            else close + 0.5,
            "Low": pd.Series(lows, index=index, dtype=float) if lows is not None else close - 0.5,
            "Close": close,
            "Volume": pd.Series(volumes, index=index, dtype=float)
            if volumes is not None
            else pd.Series(1_000_000.0, index=index),
        }
    )


def _wave(n: int) -> list[float]:
    """A 20-bar sine around 100 (peaks 102 at i=5 mod 20, troughs 98 at i=15 mod 20)."""
    return [100 + 2 * math.sin(2 * math.pi * i / 20) for i in range(n)]


def wave_bars(n: int) -> pd.DataFrame:
    return make_bars(_wave(n))


def _with_days(base: pd.DataFrame, closes: list[float], volumes: list[float]) -> pd.DataFrame:
    """*base* plus one bar per (close, volume): High/Low close +/- 0.5, dated just after it."""
    start = base.index[-1] + pd.offsets.BDay(1)
    index = pd.bdate_range(start=start, periods=len(closes))
    close = pd.Series(closes, index=index, dtype=float)
    extra = pd.DataFrame(
        {
            "Open": close,
            "High": close + 0.5,
            "Low": close - 0.5,
            "Close": close,
            "Volume": pd.Series(volumes, index=index, dtype=float),
        }
    )
    return pd.concat([base, extra])


def _cfg(**over) -> CcBreakoutCfg:
    return CcBreakoutCfg(**over)


# A 76-bar sine ends at a trough (98, resistance 102.5 above); a 66-bar one ends on a peak (102,
# resistance 102.5 just above). ATR-14 is about 1.1 either way.
TROUGH, PEAK = 76, 66


# --------------------------------------------------------------------------- #
# ATR series
# --------------------------------------------------------------------------- #


def test_atr14_series_last_value_matches_atr14():
    bars = wave_bars(60)
    series = atr14_series(bars["High"], bars["Low"], bars["Close"])
    assert len(series) == 60
    assert round(float(series.iloc[-1]), 4) == _atr14(bars["High"], bars["Low"], bars["Close"])
    # too little history: _atr14 keeps saying None
    short = bars.iloc[:14]
    assert _atr14(short["High"], short["Low"], short["Close"]) is None


# --------------------------------------------------------------------------- #
# Resistance levels
# --------------------------------------------------------------------------- #


def _ramp_with_spikes(spikes: dict[int, float], n: int = 100) -> pd.DataFrame:
    """A gentle ramp 90 -> 100 (no swing highs of its own) with single-bar spike highs."""
    closes = [90 + 10 * i / (n - 1) for i in range(n)]
    highs = [c + 0.5 for c in closes]
    for i, h in spikes.items():
        highs[i] = h
    return make_bars(closes, highs=highs)


def test_resistance_levels_above_spot_nearest_first():
    bars = _ramp_with_spikes({30: 104.0, 55: 108.0, 80: 112.0})
    levels = resistance_levels(bars, spot=100.0, atr=1.0)
    assert levels == [104.0, 108.0, 112.0]
    assert resistance_levels(bars, spot=100.0, atr=1.0, max_levels=2) == [104.0, 108.0]
    # a level at or under the spot is not resistance
    assert resistance_levels(bars, spot=106.0, atr=1.0) == [108.0, 112.0]
    assert resistance_levels(bars, spot=120.0, atr=1.0) == []


def test_close_resistance_levels_merge_to_the_higher():
    bars = _ramp_with_spikes({30: 104.0, 40: 104.3})
    levels = resistance_levels(bars, spot=100.0, atr=1.0)  # 0.3 apart < 0.5 x ATR
    assert levels == [104.3]


@pytest.mark.parametrize(("later_close", "kept"), [(104.5, True), (105.9, False)])
def test_resistance_broken_by_a_later_close_is_dropped(later_close, kept):
    n = 100
    closes = [90 + 10 * i / (n - 1) for i in range(n)]
    highs = [c + 0.5 for c in closes]
    highs[30] = 104.0
    closes[50] = later_close  # a later close, then back on the ramp
    highs[50] = later_close + 0.2
    levels = resistance_levels(make_bars(closes, highs=highs), spot=100.0, atr=1.0)
    assert (104.0 in levels) is kept  # broken = a close more than 1 ATR above the level


def test_resistance_levels_without_enough_history_claim_nothing():
    assert resistance_levels(wave_bars(10), spot=90.0) == []
    assert resistance_levels(pd.DataFrame(), spot=90.0) == []


# --------------------------------------------------------------------------- #
# The breakout detector
# --------------------------------------------------------------------------- #


def _jump_frame(n_base: int, rise: float, vol_mult: float) -> pd.DataFrame:
    base = wave_bars(n_base)
    last = float(base["Close"].iloc[-1])
    return _with_days(base, [last + rise], [vol_mult * 1_000_000.0])


@pytest.mark.parametrize(
    ("n_base", "rise", "vol_mult", "expect"),
    [
        (TROUGH, 5.0, 2.0, True),  # +5.0 > 1.5 ATR, 2x volume, 103 > the 102.5 level
        (PEAK, 1.0, 2.0, False),  # no jump: +1.0 is under 1.5 ATR (103 > 102.5, volume fine)
        (TROUGH, 5.0, 1.0, False),  # no volume: 1x is under 1.5x
        (TROUGH, 3.9, 2.0, False),  # no level: 101.9 does not clear 102.5, nor a 60-session high
    ],
)
def test_breakout_needs_a_jump_volume_and_a_level(n_base, rise, vol_mult, expect):
    out = breakout(_jump_frame(n_base, rise, vol_mult), cfg=_cfg())
    if not expect:
        assert out is None
        return
    assert isinstance(out, CcBreakout)
    assert out.sessions_left == 5
    assert out.broke_level == pytest.approx(102.5)
    assert out.volume_ratio == pytest.approx(2.0, rel=1e-6)
    assert out.jump_pct == pytest.approx(5.0 / 98.0 * 100, rel=1e-3)
    assert out.delta_max == 0.25
    assert out.trigger_close == pytest.approx(103.0, abs=1e-6)
    frame = _jump_frame(n_base, rise, vol_mult)
    assert out.trigger_day == frame.index[-1].date()


def test_breakout_at_a_60_session_high_without_resistance():
    n = 70
    closes = [100 + 0.2 * i for i in range(n)]  # a steady rise: new highs, no swing highs
    base = make_bars(closes)
    assert resistance_levels(base, spot=float(base["Close"].iloc[-1])) == []
    frame = _with_days(base, [closes[-1] + 3.0], [3_000_000.0])
    out = breakout(frame, cfg=_cfg())
    assert out is not None
    assert out.broke_level is None  # no resistance was broken: a 60-session high
    assert out.sessions_left == 5
    # the same jump below the 60-session high is not a breakout
    dipped = base.copy()
    dipped.iloc[-3:, dipped.columns.get_loc("Close")] = closes[-1] - 8.0
    dipped.iloc[-3:, dipped.columns.get_loc("High")] = closes[-1] - 7.5
    dipped.iloc[-3:, dipped.columns.get_loc("Low")] = closes[-1] - 8.5
    again = _with_days(dipped, [closes[-1] - 8.0 + 3.0], [3_000_000.0])
    assert breakout(again, cfg=_cfg()) is None


@pytest.mark.parametrize(
    ("after", "alive"), [(0, True), (3, True), (4, True), (5, False), (6, False)]
)
def test_breakout_expires_after_lookback_sessions(after, alive):
    frame = _jump_frame(TROUGH, 5.0, 2.0)
    trigger = float(frame["Close"].iloc[-1])
    if after:
        frame = _with_days(frame, [trigger] * after, [1_000_000.0] * after)
    out = breakout(frame, cfg=_cfg())
    if not alive:
        assert out is None
        return
    assert out is not None
    assert out.sessions_left == 5 - after
    assert out.trigger_close == pytest.approx(trigger)


def test_breakout_ends_on_a_fade():
    frame = _jump_frame(TROUGH, 5.0, 2.0)
    trigger = float(frame["Close"].iloc[-1])
    atr_trigger = float(atr14_series(frame["High"], frame["Low"], frame["Close"]).iloc[-1])
    # a later close 0.9 ATR under the breakout close: still on
    held = _with_days(frame, [trigger - 0.9 * atr_trigger], [1_000_000.0])
    assert breakout(held, cfg=_cfg()) is not None
    # 1.1 ATR under it: the breakout has faded
    faded = _with_days(frame, [trigger, trigger - 1.1 * atr_trigger], [1_000_000.0] * 2)
    assert breakout(faded, cfg=_cfg()) is None


def test_breakout_needs_history_and_volume():
    assert breakout(wave_bars(20), cfg=_cfg()) is None
    frame = _jump_frame(TROUGH, 5.0, 2.0)
    assert breakout(frame.drop(columns=["Volume"]), cfg=_cfg()) is None
    assert breakout(pd.DataFrame(), cfg=_cfg()) is None


def test_floor_is_the_higher_of_resistance_and_atr():
    # ends at a trough (98): resistance 102.5 is further than price + 1 ATR (about 99.1)
    low = wave_bars(TROUGH)
    atr_low = float(atr14_series(low["High"], low["Low"], low["Close"]).iloc[-1])
    assert cc_floor(low, cfg=_cfg()) == pytest.approx(102.5)
    assert 98 + atr_low < 102.5
    # ends on a peak (102): resistance 102.5 is nearer than price + 1 ATR
    peak = wave_bars(PEAK)
    atr_peak = float(atr14_series(peak["High"], peak["Low"], peak["Close"]).iloc[-1])
    last = float(peak["Close"].iloc[-1])
    assert cc_floor(peak, cfg=_cfg()) == pytest.approx(last + atr_peak)
    assert cc_floor(peak, cfg=_cfg(floor_atr=2.0)) == pytest.approx(last + 2.0 * atr_peak)
    assert cc_floor(wave_bars(10), cfg=_cfg()) is None  # no ATR


def test_the_breakout_floor_strike_is_the_floor():
    frame = _jump_frame(TROUGH, 5.0, 2.0)
    out = breakout(frame, cfg=_cfg())
    assert out is not None
    assert out.floor_strike == pytest.approx(cc_floor(frame, cfg=_cfg()))


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


def test_the_shipped_cc_timing_block():
    cfg = get_cc_timing_cfg().breakout
    assert (cfg.enabled, cfg.lookback_sessions, cfg.jump_atr, cfg.volume_mult) == (
        True,
        5,
        1.5,
        1.5,
    )
    assert (cfg.high_sessions, cfg.fade_atr, cfg.floor_atr, cfg.delta_max) == (60, 1.0, 1.0, 0.25)


def test_a_mistyped_cc_timing_key_is_refused(monkeypatch):
    set_risk(monkeypatch, cc_timing={"breakout": {"lookback_session": 5}})
    with pytest.raises(ValueError, match="unknown key"):
        get_cc_timing_cfg()
    set_risk(monkeypatch, cc_timing={"breakoutt": {}})
    with pytest.raises(ValueError, match="unknown key"):
        get_cc_timing_cfg()


def test_cc_timing_key_lists_match_the_model_fields():
    from src.common.config import CcTimingCfg

    assert set(CcBreakoutCfg.KEYS) == set(CcBreakoutCfg.model_fields)
    assert set(CcTimingCfg.KEYS) == set(CcTimingCfg.model_fields)


def test_breakout_delta_guard_must_exceed_delta_min(monkeypatch):
    # covered_call.delta_min is 0.20 in the shipped config: a 0.20 guard leaves an empty band
    set_risk(monkeypatch, cc_timing={"breakout": {"delta_max": 0.20}})
    with pytest.raises(ValueError, match="delta_min"):
        get_cc_timing_cfg()
    set_risk(monkeypatch, cc_timing={"breakout": {"delta_max": 0.19}})
    with pytest.raises(ValueError, match="delta_min"):
        get_cc_timing_cfg()
    set_risk(monkeypatch, cc_timing={"breakout": {"delta_max": 0.21}})
    assert get_cc_timing_cfg().breakout.delta_max == 0.21


# --------------------------------------------------------------------------- #
# The generator
# --------------------------------------------------------------------------- #


def _breakout(floor: float = 760.0, delta_max: float = 0.25, sessions_left: int = 3) -> CcBreakout:
    return CcBreakout(
        trigger_day=date(2026, 10, 14),
        trigger_close=748.0,
        jump_pct=6.1,
        volume_ratio=2.3,
        broke_level=742.0,
        floor_strike=floor,
        delta_max=delta_max,
        sessions_left=sessions_left,
    )


def _ctx(*, suspended: bool = False, symbol: str = "META", **kw) -> SizingContext:
    return SizingContext(
        regimes={"SPY": N, "QQQ": N},
        suspended=suspended,
        cc_breakout={symbol: kw.get("breakout", _breakout())},
    )


def _meta_call(strike: float, delta: float) -> OptionQuote:
    return OptionQuote(
        underlying="META",
        right=OptionRight.CALL,
        strike=strike,
        expiry=_EXPIRY,
        bid=9.9,
        ask=10.1,
        volume=500,
        open_interest=2000,
        iv=0.30,
        delta=delta,
    )


def _screen_meta(sizing: SizingContext | None, *quotes: OptionQuote) -> ScreenResult:
    return screen_cc_candidates(
        "META",
        list(quotes),
        PositionSnapshot(symbol="META", sec_type="STK", position=200.0, avg_cost=700.0),
        IVStats(symbol="META", current_iv=30.0, iv_rank=65.0),
        TechnicalStats(symbol="META", price=730.0, rsi_14=55.0),
        FundamentalStats(symbol="META"),
        sizing=sizing,
    )


def test_generator_rejects_near_strikes_and_keeps_far_ones():
    near, far = _meta_call(745.0, 0.35), _meta_call(765.0, 0.22)
    out = _screen_meta(_ctx(), near, far)
    assert [c.strike for c in out.passed] == [765.0]  # delta 0.22 is inside the strategy's band too
    assert len(out.rejected) == 1
    rejected, reasons = out.rejected[0]
    assert rejected.strike == 745.0
    assert reasons == ["cc_breakout_strike_floor", "cc_breakout_delta"]
    # the card needs the breakout on both
    assert out.passed[0].cc_breakout == _breakout()
    assert rejected.cc_breakout == _breakout()


def test_generator_with_no_breakout_or_no_context_is_unchanged():
    near = _meta_call(745.0, 0.35)
    for sizing in (None, SizingContext(regimes={"SPY": N, "QQQ": N})):
        out = _screen_meta(sizing, near)
        assert [c.strike for c in out.passed] == [745.0]
        assert out.passed[0].cc_breakout is None


def test_a_breakout_on_another_name_does_not_touch_this_one():
    out = _screen_meta(_ctx(symbol="AAPL"), _meta_call(745.0, 0.35))
    assert [c.strike for c in out.passed] == [745.0]


def test_a_strike_exactly_at_the_floor_and_a_delta_exactly_at_the_cap_pass():
    out = _screen_meta(_ctx(), _meta_call(760.0, 0.25))
    assert [c.strike for c in out.passed] == [760.0]


def test_breakout_rule_switched_off_in_config(monkeypatch):
    set_risk(monkeypatch, cc_timing={"breakout": {"enabled": False}})
    out = _screen_meta(_ctx(), _meta_call(745.0, 0.35))
    assert [c.strike for c in out.passed] == [745.0]


def test_breakout_not_switched_off_by_regime_off(monkeypatch):
    # `/regime off` for today
    out = _screen_meta(_ctx(suspended=True), _meta_call(745.0, 0.35))
    assert out.passed == [] and out.rejected[0][1][0] == "cc_breakout_strike_floor"
    # and `regime.enabled: false`
    set_risk(monkeypatch, regime={"enabled": False})
    out = _screen_meta(_ctx(), _meta_call(745.0, 0.35))
    assert out.passed == [] and out.rejected[0][1][0] == "cc_breakout_strike_floor"


# --------------------------------------------------------------------------- #
# The pure gate function and the Rules Engine
# --------------------------------------------------------------------------- #


def _cc(strike: float = 150.0, delta: float = 0.30, **kw):
    cand = _candidate(strategy=Strategy.COVERED_CALL, right=OptionRight.CALL, delta=delta, **kw)
    cand.strike = strike
    return cand


def test_cc_timing_reasons_for_a_near_strike():
    ctx = SizingContext(regimes={"SPY": N, "QQQ": N}, cc_breakout={"AAPL": _breakout(160.0)})
    assert cc_timing_reasons(ctx, _cc(150.0, 0.30)) == [
        "cc_breakout_strike_floor",
        "cc_breakout_delta",
    ]
    assert cc_timing_reasons(ctx, _cc(170.0, 0.22)) == []
    assert cc_timing_reasons(ctx, _cc(170.0, 0.30)) == ["cc_breakout_delta"]
    assert cc_timing_reasons(ctx, _cc(150.0, 0.22)) == ["cc_breakout_strike_floor"]
    # a missing delta is the generator's / gate's own `delta_missing`, not this rule's
    no_delta = _cc(170.0, 0.22)
    no_delta.delta = None
    assert cc_timing_reasons(ctx, no_delta) == []


def test_cc_timing_reasons_read_the_snapshot_when_there_is_no_context():
    cand = _cc(150.0, 0.30)
    cand.cc_breakout = _breakout(160.0)
    assert cc_timing_reasons(None, cand) == ["cc_breakout_strike_floor", "cc_breakout_delta"]
    # the context's fresher breakout wins over the snapshot's
    ctx = SizingContext(
        regimes={"SPY": N, "QQQ": N}, cc_breakout={"AAPL": _breakout(140.0, delta_max=0.40)}
    )
    assert cc_timing_reasons(ctx, cand) == []
    assert cc_timing_reasons(None, _cc()) == []


def test_gate_rejects_a_near_cc_during_a_breakout():
    ctx = SizingContext(regimes={"SPY": N, "QQQ": N}, cc_breakout={"AAPL": _breakout(160.0)})
    near, far = _cc(150.0, 0.30, candidate_id="near"), _cc(170.0, 0.22, candidate_id="far")
    verdicts = {
        v.candidate_id: v for v in validate_candidates([near, far], _account(), [], sizing=ctx)
    }
    assert verdicts["near"].verdict == Verdict.REJECT
    assert "cc_breakout_strike_floor" in verdicts["near"].reasons
    assert "cc_breakout_delta" in verdicts["near"].reasons
    assert not any(r.startswith("cc_breakout") for r in verdicts["far"].reasons)
    # send time: no fresh context, only the breakout frozen on the snapshot
    frozen = _cc(150.0, 0.30, candidate_id="frozen")
    frozen.cc_breakout = _breakout(160.0)
    out = validate_candidates([frozen], _account(), [], sizing=None)
    assert "cc_breakout_strike_floor" in out[0].reasons


def test_breakout_never_touches_rolls_or_csps():
    ctx = SizingContext(regimes={"SPY": N, "QQQ": N}, cc_breakout={"AAPL": _breakout(160.0)})
    roll = _candidate(strategy=Strategy.ROLL, right=OptionRight.CALL, delta=0.30)
    roll.strike = 150.0
    roll.cc_breakout = _breakout(160.0)
    csp = _candidate(strategy=Strategy.CASH_SECURED_PUT, right=OptionRight.PUT, delta=-0.30)
    csp.cc_breakout = _breakout(160.0)
    assert cc_timing_reasons(ctx, roll) == [] and cc_timing_reasons(ctx, csp) == []
    for cand in (roll, csp):
        out = validate_candidates([cand], _account(), [], sizing=ctx)
        assert not any(r.startswith("cc_breakout") for r in out[0].reasons)


def test_cc_timing_labels_are_in_both_tables():
    from src.api.routers.options import _REASON_LABELS
    from src.notify.formatters import _REJECT_REASON_LABELS

    for code, phrase in (
        ("cc_breakout_strike_floor", "below the strike floor after a breakout"),
        ("cc_breakout_delta", "too close to the money after a breakout"),
    ):
        assert _REJECT_REASON_LABELS[code] == phrase == _REASON_LABELS[code]


def test_the_card_states_the_breakout():
    from src.notify.formatters import format_candidate

    out = _screen_meta(_ctx(), _meta_call(765.0, 0.22))
    text = format_candidate(out.passed[0], None).replace("\\", "")
    assert (
        "Breakout Oct 14 (+6.1%, 2.3× volume, above $742.00): CC strikes at or above $760.00, "
        "delta ≤ 0.25, for 3 more sessions" in text
    )
    high = _breakout()
    high = high.model_copy(update={"broke_level": None, "sessions_left": 1})
    out = _screen_meta(_ctx(breakout=high), _meta_call(765.0, 0.22))
    text = format_candidate(out.passed[0], None).replace("\\", "")
    assert "at a 60-session high" in text and "for 1 more session" in text
    plain = _screen_meta(None, _meta_call(765.0, 0.22))
    assert "Breakout" not in format_candidate(plain.passed[0], None)


# --------------------------------------------------------------------------- #
# The context
# --------------------------------------------------------------------------- #

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)


def _db(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _held(symbol: str, shares: float) -> PositionSnapshot:
    return PositionSnapshot(symbol=symbol, sec_type="STK", position=shares, avg_cost=100.0)


def _build(*, positions, bars=None, for_send=False, symbols=None):
    from src.regime.context import build_sizing_context
    from src.storage.db import session_scope

    with session_scope() as s:
        return build_sizing_context(
            now=NOW,
            session=s,
            for_send=for_send,
            symbols=symbols if symbols is not None else [],
            positions=positions,
            bars=bars,
        )


def test_context_built_when_regime_disabled_but_breakout_enabled(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    set_risk(
        monkeypatch,
        regime={"enabled": False},
        leveraged_sizing={"enabled": False},
        cc_timing={"breakout": {"enabled": True}},
    )
    frame = _jump_frame(TROUGH, 5.0, 2.0)
    ctx = _build(positions=[_held("META", 200)], bars={"META": frame})
    assert ctx is not None
    assert set(ctx.cc_breakout) == {"META"}
    assert ctx.cc_breakout["META"].sessions_left == 5


def test_a_breakout_only_context_carries_no_regime_behaviour(tmp_path, monkeypatch):
    """With the regime and the leveraged-ETF ceiling off, the breakout switch alone still wants a
    context, but it must not bring the same-day loss-exit block or any ladder work with it."""
    _db(tmp_path, monkeypatch)
    import src.regime.context as ctxmod

    monkeypatch.setattr(ctxmod, "loss_exits_today", lambda session, today: ["AAPL"])
    ladder_calls: list[object] = []
    monkeypatch.setattr(ctxmod, "_ladder", lambda *a, **k: ladder_calls.append(1) or ({}, {}, []))
    set_risk(
        monkeypatch,
        regime={"enabled": False},
        leveraged_sizing={"enabled": False},
        cc_timing={"breakout": {"enabled": True}},
    )
    only = _build(
        positions=[_held("META", 200)], symbols=["AAPL"], bars={"META": wave_bars(TROUGH)}
    )
    assert only is not None and only.loss_exit_today == [] and ladder_calls == []
    set_risk(monkeypatch, regime={"enabled": True})
    full = _build(
        positions=[_held("META", 200)], symbols=["AAPL"], bars={"META": wave_bars(TROUGH)}
    )
    assert full is not None and full.loss_exit_today == ["AAPL"] and ladder_calls == [1]


def test_context_is_none_when_every_switch_is_off_including_the_breakout(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    set_risk(
        monkeypatch,
        regime={"enabled": False},
        leveraged_sizing={"enabled": False},
        cc_timing={"breakout": {"enabled": False}},
    )
    assert _build(positions=[_held("META", 200)]) is None


def test_context_breakouts_only_for_names_with_a_round_lot(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    frame = _jump_frame(TROUGH, 5.0, 2.0)
    ctx = _build(
        positions=[_held("META", 99), _held("AAPL", 100), _held("NVDA", 60), _held("NVDA", 60)],
        bars={"META": frame, "AAPL": frame, "NVDA": frame},
    )
    assert ctx is not None
    assert set(ctx.cc_breakout) == {"AAPL", "NVDA"}  # 99 shares cannot write a call; 60 + 60 can


def test_context_without_a_breakout_or_with_no_bars_has_none(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    quiet = wave_bars(TROUGH)
    ctx = _build(positions=[_held("META", 200), _held("AAPL", 200)], bars={"META": quiet})
    assert ctx is not None and ctx.cc_breakout == {}  # AAPL: no bars at all (offline stub)


def test_send_time_context_fetches_no_bars(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    import src.analytics.regime as regime_data

    def boom(*args, **kwargs):
        raise AssertionError("a send-time context must not fetch bars")

    monkeypatch.setattr(regime_data, "get_bars", boom)
    ctx = _build(positions=[_held("META", 200)], for_send=True)
    assert ctx is not None and ctx.cc_breakout == {}


def test_a_failing_bar_load_for_a_held_name_is_no_breakout_not_an_error(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    import src.analytics.regime as regime_data

    def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(regime_data, "get_bars", boom)
    ctx = _build(positions=[_held("META", 200)])
    assert ctx is not None and ctx.cc_breakout == {}


# --------------------------------------------------------------------------- #
# The record (counterfactual table)
# --------------------------------------------------------------------------- #


def _rejected_cc(symbol: str, strike: float, premium: float, reasons: list[str]):
    cand = _cc(strike, 0.30, candidate_id=f"{symbol}-{strike}")
    cand.underlying = symbol
    cand.premium = premium
    cand.contracts = 2
    return cand, reasons


def _rows():
    from src.storage.db import session_scope
    from src.storage.models import SizingActionRow

    with session_scope() as s:
        return [
            SimpleNamespace(
                kind=r.kind,
                key=r.record_key,
                strike=r.strike,
                det=r.deterministic_contracts,
                sent=r.sent_contracts,
                symbol=r.underlying,
                day=r.action_day,
            )
            for r in s.query(SizingActionRow).order_by(SizingActionRow.id).all()
        ]


def test_record_picks_the_highest_premium_breakout_only_reject_per_name(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    from src.regime.actions import record_cc_timing

    both = ["cc_breakout_strike_floor", "cc_breakout_delta"]
    record_cc_timing(
        generator_rejects=[
            _rejected_cc("META", 745.0, 9.0, both),
            _rejected_cc("META", 750.0, 8.0, ["cc_breakout_strike_floor"]),
            _rejected_cc("META", 755.0, 12.0, ["cc_breakout_delta", "roc_below_minimum"]),
            _rejected_cc("AAPL", 200.0, 3.0, ["delta_out_of_range"]),
            _rejected_cc("AMD", 150.0, 5.0, both),
        ]
    )
    rows = _rows()
    assert sorted((r.symbol, r.strike, r.kind) for r in rows) == [
        ("AMD", 150.0, "cc_breakout_floor"),
        ("META", 745.0, "cc_breakout_floor"),  # 755 also failed ROC: not the breakout's doing
    ]
    day = today_et().isoformat()
    assert {r.key for r in rows} == {f"cctiming:META:{day}", f"cctiming:AMD:{day}"}
    assert all(r.det == 2 and r.sent == 0 for r in rows)


def test_record_ignores_puts_and_candidates_without_reasons(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    from src.regime.actions import record_cc_timing

    csp = _candidate(strategy=Strategy.CASH_SECURED_PUT, right=OptionRight.PUT)
    record_cc_timing(generator_rejects=[(csp, ["cc_breakout_delta"]), (_cc(), [])])
    record_cc_timing(generator_rejects=[])
    assert _rows() == []


@pytest.mark.asyncio
async def test_scan_records_one_breakout_row_per_name_per_day(tmp_path, monkeypatch):
    """Two scans, a different near strike rejected only for the breakout each time: one row for
    the name and the ET day, the first contract kept. Nothing else passes either scan."""
    from tests.test_scan_review_reuse import _db_setup, _stub_pipeline

    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod

    monkeypatch.setattr(get_config(), "universe", {"would_own": ["AAPL"], "sectors": {"AAPL": "t"}})
    _stub_pipeline(scanmod, monkeypatch, {"n": 0})
    monkeypatch.setattr(scanmod, "get_positions", lambda ib: [_held("META", 200)])
    monkeypatch.setattr(
        scanmod, "screen_csp_candidates", lambda *a, **k: ScreenResult()
    )  # no CSP, and no CC passes: the "nothing to surface" path
    strikes = iter([745.0, 750.0])

    def screen_cc(symbol, *args, **kwargs):
        if symbol != "META":
            return ScreenResult()
        cand, reasons = _rejected_cc("META", next(strikes), 9.0, ["cc_breakout_strike_floor"])
        return ScreenResult(rejected=[(cand, reasons)], evaluated=1)

    monkeypatch.setattr(scanmod, "screen_cc_candidates", screen_cc)

    await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1")
    await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1")

    rows = _rows()
    assert len(rows) == 1
    assert rows[0].kind == "cc_breakout_floor"
    assert rows[0].key == f"cctiming:META:{today_et().isoformat()}"
    assert rows[0].strike == 745.0  # the day's first contract is the counterfactual
    assert rows[0].sent == 0


def test_the_breakout_survives_the_order_snapshot_round_trip():
    # the snapshot freezes it as JSON: a round trip must give the same model back
    b = _breakout()
    assert CcBreakout.model_validate(b.model_dump(mode="json")) == b


# --------------------------------------------------------------------------- #
# OI-E3: at send time a covered call is held to the breakout's delta cap against the LIVE quote
# (the breakout itself is the copy frozen on the card; no bars are fetched at send time)
# --------------------------------------------------------------------------- #


def _live_call(delta: float | None, *, strike: float = 170.0) -> OptionQuote:
    return OptionQuote(
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=strike,
        expiry=_EXPIRY,
        bid=2.9,
        ask=3.1,
        delta=delta,
    )


def _frozen_cc(delta: float = 0.24, **kw):
    cand = _cc(170.0, delta, **kw)  # a strike above the floor: only the delta can refuse it
    cand.cc_breakout = _breakout(160.0, 0.25)
    return cand


def test_a_call_whose_delta_drifted_over_the_cap_is_refused_at_send_time():
    from src.engine.risk_engine import validate_live_quote

    cand = _frozen_cc(0.24)
    # decision time: the card's own delta clears the cap
    assert validate_candidates([cand], _account(), [], sizing=None)[0].verdict == Verdict.PASS
    # send time: the live quote now says 0.31 (inside the strategy's own 0.20-0.35 band)
    drifted = validate_live_quote(cand, _live_call(0.31))
    assert drifted.verdict == Verdict.REJECT
    assert drifted.reasons == ["cc_breakout_delta"]
    # a live delta at or under the cap passes
    assert validate_live_quote(cand, _live_call(0.24)).verdict == Verdict.PASS
    assert validate_live_quote(cand, _live_call(0.25)).verdict == Verdict.PASS


def test_the_live_delta_check_needs_a_breakout_on_the_card():
    from src.engine.risk_engine import validate_live_quote

    free = _cc(170.0, 0.24)  # no breakout frozen on this card
    assert validate_live_quote(free, _live_call(0.31)).verdict == Verdict.PASS


def test_a_missing_live_delta_does_not_trigger_the_breakout_rule():
    from src.engine.risk_engine import validate_live_quote

    out = validate_live_quote(_frozen_cc(0.24), _live_call(None))
    assert out.verdict == Verdict.PASS, out.reasons


def test_the_live_delta_check_is_for_covered_calls_only():
    from src.engine.risk_engine import validate_live_quote

    roll = _candidate(strategy=Strategy.ROLL, right=OptionRight.CALL, delta=0.24)
    roll.strike = 170.0
    roll.cc_breakout = _breakout(160.0, 0.25)
    assert "cc_breakout_delta" not in validate_live_quote(roll, _live_call(0.31)).reasons
    # a call that carries a roll origin is a roll whatever its strategy says
    from tests.test_engine import _roll_origin

    tagged = _frozen_cc(0.24)
    tagged.roll_from = _roll_origin(OptionRight.CALL, 20)
    assert "cc_breakout_delta" not in validate_live_quote(tagged, _live_call(0.31)).reasons
    put = _candidate(strategy=Strategy.CASH_SECURED_PUT, right=OptionRight.PUT, delta=-0.24)
    put.cc_breakout = _breakout(160.0, 0.25)
    live_put = _live_call(-0.31).model_copy(update={"right": OptionRight.PUT})
    assert "cc_breakout_delta" not in validate_live_quote(put, live_put).reasons


def test_the_live_delta_check_follows_the_breakout_switch(monkeypatch):
    from src.engine.risk_engine import validate_live_quote

    set_risk(monkeypatch, cc_timing={"breakout": {"enabled": False}})
    assert validate_live_quote(_frozen_cc(0.24), _live_call(0.31)).verdict == Verdict.PASS


def test_the_live_delta_check_survives_regime_off():
    """The breakout is not a regime limit: a suspended context changes nothing about it."""
    from src.engine.risk_engine import validate_live_quote

    out = validate_live_quote(_frozen_cc(0.24), _live_call(0.31), sizing=_ctx(suspended=True))
    assert out.reasons == ["cc_breakout_delta"]


async def test_a_drifted_call_is_refused_by_the_executor_and_the_order_says_why(
    tmp_path, monkeypatch
):
    """End to end through `execute_candidate`: the fresh quote's delta reaches the re-gate."""
    from src.common.schemas import OrderState
    from src.execution.executor import execute_candidate
    from src.storage.db import session_scope
    from src.storage.models import OrderRow
    from tests.test_execution import _db_setup, _make_candidate, _make_mock_bot, _make_mock_ib

    _db_setup(tmp_path, monkeypatch)
    mock_cfg = MagicMock()
    mock_cfg.execution.fill_timeout_minutes = 1
    mock_cfg.execution.quote_timeout_seconds = 1.0
    mock_cfg.is_live = False
    monkeypatch.setattr("src.execution.executor.get_config", lambda: mock_cfg)
    cand = _make_candidate().model_copy(
        update={
            "strategy": Strategy.COVERED_CALL,
            "right": OptionRight.CALL,
            "delta": 0.24,
            "cc_breakout": _breakout(160.0, 0.25),
        }
    )
    with session_scope() as s:
        row = OrderRow(candidate_id=cand.candidate_id, state=OrderState.QUEUED)
        s.add(row)
        s.flush()
        order_id = row.id
    ib = _make_mock_ib()
    ticker = ib.reqMktData.return_value
    ticker.bid, ticker.ask = 1.50, 1.60  # the credit is unchanged: only the delta moved
    ticker.modelGreeks.delta = 0.31  # inside the strategy's own 0.20-0.35 band, over the cap

    await execute_candidate(ib, _make_mock_bot(), "99999", order_id, cand)

    with session_scope() as s:
        saved = s.get(OrderRow, order_id)
        assert saved is not None
        assert saved.state == OrderState.REJECTED
        assert "Live re-validation failed" in (saved.detail or "")
    ib.placeOrder.assert_not_called()
