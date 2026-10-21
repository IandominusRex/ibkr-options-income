"""The bottoming signal (Task 7): look for the opportunity, don't sit out (spec section 6b).

A deterministic sign that a bottom is forming loosens one notch: at the market level the index
regime eases one step at once; at the name level a single lot is allowed at the current zone.
It is plain Python (it loosens a limit, so no LLM may produce it), with strict guards.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.analytics.bottoming import market_bottoming, name_bottoming
from src.analytics.technicals import _atr14, rsi14_series
from src.common.config import RegimeBottomingCfg, get_config, get_regime_cfg
from src.common.schemas import (
    MarketRegime,
    ScaleInZone,
    SizingContext,
    Verdict,
)
from src.common.universe import invalidate_universe_cache
from src.engine.regime_limits import bottoming_reason, scale_in_reason, signal_lot
from src.regime.context import build_sizing_context
from src.regime.refresh import refresh_regime
from src.storage.db import session_scope
from src.storage.models import SizingActionRow
from tests.test_regime_state import QQQ_DOWN_LIVE, Feed, hot
from tests.test_scale_in import put, seed_lot, utc
from tests.test_scale_in_gate import SIZER_ZONE, csp, ctx, gate

N = MarketRegime.NORMAL
C = MarketRegime.CAUTIOUS
S = MarketRegime.STRESSED
X = MarketRegime.CRISIS

DAY1 = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
DAY2 = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)


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


@pytest.fixture(autouse=True)
def _universe(monkeypatch):
    names = ["BAC", "TQQQ"]
    monkeypatch.setattr(
        get_config(),
        "universe",
        {
            "would_own": names,
            "actively_wheeling": names,
            "sectors": {"BAC": "financials", "TQQQ": "index"},
            "leveraged_etfs": ["TQQQ"],
        },
    )
    invalidate_universe_cache()
    yield
    invalidate_universe_cache()


def cfg() -> RegimeBottomingCfg:
    return get_regime_cfg().bottoming


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #


def test_bottoming_block_ships_with_the_documented_values():
    b = cfg()
    assert (b.vix_spike_pct, b.spike_sessions, b.off_peak_pct) == (25.0, 10, 15.0)
    assert (b.rsi_oversold, b.rsi_lookback) == (30.0, 5)
    assert (b.signal_delta_max, b.signal_lot_every_sessions) == (0.25, 3)
    assert set(b.KEYS) == set(RegimeBottomingCfg.model_fields)
    block = get_config().risk["regime"]["bottoming"]  # the example YAML carries every key
    assert set(block) == set(RegimeBottomingCfg.KEYS)


def set_regime(monkeypatch, **bottoming) -> None:
    config = get_config()
    risk = dict(config.risk)
    regime = dict(risk["regime"])
    regime["bottoming"] = {**regime["bottoming"], **bottoming}
    risk["regime"] = regime
    monkeypatch.setattr(config, "risk", risk)


def test_bottoming_delta_guard_must_exceed_delta_min(monkeypatch):
    """Review Focus 11 / ruling 42: a guard at or under the strategy's delta_min is an empty band."""
    set_regime(monkeypatch, signal_delta_max=0.20)  # delta_min is 0.20
    with pytest.raises(ValueError, match="signal_delta_max"):
        get_regime_cfg()
    set_regime(monkeypatch, signal_delta_max=0.19)
    with pytest.raises(ValueError, match="signal_delta_max"):
        get_regime_cfg()
    set_regime(monkeypatch, signal_delta_max=0.21)
    assert get_regime_cfg().bottoming.signal_delta_max == 0.21
    # the other direction: the strategy's delta_min rises to meet the shipped 0.25
    set_regime(monkeypatch, signal_delta_max=0.25)
    config = get_config()
    risk = dict(config.risk)
    risk["cash_secured_put"] = {**risk["cash_secured_put"], "delta_min": 0.25}
    monkeypatch.setattr(config, "risk", risk)
    with pytest.raises(ValueError, match="signal_delta_max"):
        get_regime_cfg()


# --------------------------------------------------------------------------- #
# the market-level signal
# --------------------------------------------------------------------------- #


def frame(closes, lows=None, highs=None, *, start: str = "2026-10-05") -> pd.DataFrame:
    closes = list(closes)
    idx = pd.bdate_range(start, periods=len(closes))
    c = np.array(closes, dtype=float)
    low = np.array(lows if lows is not None else c - 0.5, dtype=float)
    high = np.array(highs if highs is not None else c + 0.5, dtype=float)
    return pd.DataFrame({"Open": c, "High": high, "Low": low, "Close": c, "Volume": 1.0}, index=idx)


# ten sessions: the VIX rises 15 -> 25 (+67%) and starts to retreat; the curve inverts at the peak
VIX = frame([15, 15.5, 16, 17, 19, 22, 25, 24, 22, 20])
VIX3M = frame([20.0] * 10)
# the index sells off to a low on day 7 (lowest close 660, Low 655) and recovers
INDEX = frame(
    [700, 698, 695, 690, 680, 670, 660, 668, 672, 676],
    lows=[699, 697, 694, 689, 679, 669, 655, 662, 667, 671],
)


def market(live_vix=18.0, live_index=662.0, *, vix=VIX, vix3m=VIX3M, index=INDEX):
    return market_bottoming(
        vix=vix, vix3m=vix3m, index=index, live_vix=live_vix, live_index=live_index, cfg=cfg()
    )


def test_market_signal_needs_a_spike_and_a_retreat_and_a_higher_low():
    ok, why = market()
    assert ok is True
    assert why and any("VIX" in w for w in why)
    # not far enough off the peak: 22 is only 12% under 25 (needs 15%)
    assert market(live_vix=22.0)[0] is False
    # the index made a lower low than the selloff's lowest day (Low 655)
    assert market(live_index=650.0)[0] is False
    # no live value is no signal, never a guess
    assert market(live_vix=None)[0] is False
    assert market(live_index=None)[0] is False


def test_market_signal_off_without_a_spike():
    flat = frame([15, 15.2, 15.5, 15.8, 16, 16.5, 17, 16.5, 16, 15.5])  # peak 17 < 15 x 1.25
    ok, why = market(vix=flat, live_vix=14.0)
    assert ok is False and why
    # a peak that came BEFORE the low is a decline, not a spike
    falling = frame([25, 24, 22, 20, 19, 18, 17, 16, 15.5, 15])
    assert market(vix=falling, live_vix=14.0)[0] is False
    assert market(vix=VIX.iloc[:0])[0] is False
    assert market(index=INDEX.iloc[:0])[0] is False


def test_inverted_curve_must_normalise():
    # at the peak the VIX3M was 20 against a VIX of 25 (inverted); live 21 is far enough off the
    # peak (<= 21.25) but 21 / 20 = 1.05 is still inverted
    assert market(live_vix=21.0)[0] is False
    assert market(live_vix=19.0)[0] is True  # 19 / 20 = 0.95
    # a curve that never inverted needs no normalising
    wide = frame([30.0] * 10)
    assert market(live_vix=21.0, vix3m=wide)[0] is True


# --------------------------------------------------------------------------- #
# the name-level signal
# --------------------------------------------------------------------------- #

# a quick drop from 110 into a support near 97, then the first day up
NAME_CLOSES = (
    [104.0, 102, 100, 98.5, 97.5, 98.5, 100, 102, 104, 106]  # an earlier dip: a swing low at 96.5
    + [110.0] * 10
    + [108, 106, 104, 102, 100, 98.5, 97.5, 96.5, 96.0, 98.0]  # the quick drop, then an up day
)
NAME_BARS = frame(
    NAME_CLOSES,
    lows=[c - 1.0 for c in NAME_CLOSES],
    highs=[c + 0.6 for c in NAME_CLOSES],
    start="2026-09-01",
)
NAME_ATR = _atr14(NAME_BARS["High"], NAME_BARS["Low"], NAME_BARS["Close"])
NAME_ZONE = ScaleInZone(
    anchor=100.0,
    anchor_source="order_snapshot",
    zone_low=92.0,
    zone_high=94.0,
    support=93.0,
    min_gap_pct=5.0,
    triggers=["near_money_put"],
)


def name(bars=NAME_BARS, *, supports=(97.0, 93.0), spot=97.4, zone=NAME_ZONE):
    assert NAME_ATR is not None
    return name_bottoming(
        bars=bars,
        zone=zone,
        supports=list(supports),
        spot=spot,
        atr=NAME_ATR,
        band_atr=0.5,
        cfg=cfg(),
    )


def test_the_name_fixture_is_what_the_test_says_it_is():
    rsi = rsi14_series(NAME_BARS["Close"])
    assert rsi.iloc[-5:].min() < 30.0 and rsi.iloc[-1] > rsi.iloc[-2]
    assert float(NAME_BARS["Close"].iloc[-1]) > float(NAME_BARS["High"].iloc[-2])
    assert NAME_ATR is not None and 0.5 * NAME_ATR >= 0.4


def test_name_signal_needs_support_rsi_turn_and_close_above_prior_high():
    ok, why = name()
    assert ok is True and why
    # price not at the support (3.4 away, band 0.5 x ATR)
    assert name(spot=100.8)[0] is False
    # RSI never got oversold: the same bars with a mild slide
    mild = [110.0 - 0.3 * i for i in range(30)]
    mild[-1] = mild[-2] + 0.4
    mild_bars = frame(mild, lows=[c - 1 for c in mild], highs=[c + 0.6 for c in mild])
    assert name(mild_bars, spot=mild[-1])[0] is False
    # the last close is not above the prior day's high
    weak = NAME_BARS.copy()
    weak.iloc[-1, weak.columns.get_loc("Close")] = 96.4
    assert name(weak)[0] is False
    # RSI not turning up: today's RSI below yesterday's
    down = NAME_BARS.copy()
    down.iloc[-1, down.columns.get_loc("Close")] = 95.0
    assert name(down)[0] is False
    # too little history
    assert name(NAME_BARS.iloc[:10])[0] is False


def test_name_signal_off_when_the_support_is_inside_the_zone_already():
    # the only support near the price sits under the zone top: the ladder allows the lot anyway,
    # so there is nothing for a signal to unlock
    assert name(supports=(93.5,), spot=93.7)[0] is False
    assert name(supports=(97.0,), spot=97.4)[0] is True


# --------------------------------------------------------------------------- #
# the refresh: one notch, cancelled by a fresh breach
# --------------------------------------------------------------------------- #


class BarsFeed(Feed):
    """A Feed whose bars switch the market signal on and off."""

    def __init__(self, *, signal: bool = False, **kw) -> None:
        super().__init__(**kw)
        self.signal = signal

    def fetch_bars(self, symbol: str) -> pd.DataFrame:
        if not self.signal:
            return frame([15.0] * 10) if symbol.startswith("^") else INDEX
        return {"^VIX": VIX, "^VIX3M": VIX3M}.get(symbol, INDEX)


SIGNAL_LIVE = {"index_live": 662.0, "day_change_pct": -0.5, "live_vol": 18.0, "stale": []}


def run(now: datetime, feed: BarsFeed):
    return refresh_regime(
        now, fetch_daily=feed.fetch_daily, fetch_live=feed.fetch_live, fetch_bars=feed.fetch_bars
    )


def stressed_feed(base=30.0, *, signal: bool = False) -> BarsFeed:
    live = {"SPY": SIGNAL_LIVE, "QQQ": SIGNAL_LIVE}
    return BarsFeed(signal=signal, daily={"SPY": hot(base), "QQQ": hot(base)}, live=live)


def test_refresh_eases_one_notch_on_the_market_signal():
    feed = stressed_feed()
    first = run(DAY1, feed)
    assert (
        first.qqq.base == S and first.qqq.effective == S and first.qqq.eased_by_bottoming is False
    )

    feed.signal = True
    later = run(DAY1 + timedelta(hours=1), feed)
    assert later.qqq.base == S  # the base is untouched; the effective regime eases
    assert later.qqq.effective == C and later.qqq.eased_by_bottoming is True
    change = later.changes[-1]
    assert (change.index, change.before, change.after) in {("QQQ", S, C), ("SPY", S, C)}
    assert change.why[0].startswith("bottoming:")
    # one notch only, even with the signal still on at the next scan
    again = run(DAY1 + timedelta(hours=2), feed)
    assert again.qqq.effective == C


def test_crisis_eases_to_stressed_never_straight_back_to_normal():
    feed = stressed_feed(40.0)
    first = run(DAY1, feed)
    assert first.qqq.base == X and first.qqq.effective == X
    feed.signal = True
    assert run(DAY1 + timedelta(hours=1), feed).qqq.effective == S


def test_the_signal_does_nothing_in_a_calm_regime():
    feed = BarsFeed(signal=True, live={"SPY": SIGNAL_LIVE, "QQQ": SIGNAL_LIVE})
    state = run(DAY1, feed)
    assert state.qqq.effective == N and state.qqq.eased_by_bottoming is False


def test_signal_ending_restores_the_base_regime_and_says_so():
    feed = stressed_feed()
    run(DAY1, feed)
    feed.signal = True
    assert run(DAY1 + timedelta(hours=1), feed).qqq.effective == C
    feed.signal = False
    state = run(DAY1 + timedelta(hours=2), feed)
    assert state.qqq.effective == S and state.qqq.eased_by_bottoming is False
    assert state.changes[-1].why[0] == "bottoming signal ended"


def test_escalation_cancels_the_easing_for_the_day():
    feed = stressed_feed()
    run(DAY1, feed)
    feed.signal = True
    assert run(DAY1 + timedelta(hours=1), feed).qqq.effective == C

    # a fresh breach: QQQ -2.85% on the day. The easing is cancelled and the escalated regime is back
    feed.live["QQQ"] = {**QQQ_DOWN_LIVE, "live_vol": 18.0}
    breached = run(DAY1 + timedelta(hours=2), feed)
    assert breached.qqq.effective == S and breached.qqq.eased_by_bottoming is False
    assert breached.qqq.bottoming_cancelled_on == date(2026, 10, 21)

    # the bounce is back and the signal holds again: it stays cancelled for the rest of the day
    feed.live["QQQ"] = SIGNAL_LIVE
    still = run(DAY1 + timedelta(hours=3), feed)
    assert still.qqq.effective == S and still.qqq.eased_by_bottoming is False
    assert still.qqq.bottoming_cancelled_on == date(2026, 10, 21)

    # the next trading day starts clean
    nxt = run(DAY2, feed)
    assert nxt.qqq.effective == C and nxt.qqq.eased_by_bottoming is True


def test_an_earlier_escalation_today_is_not_eased_away():
    # QQQ escalated to stressed on the move (base normal); a bottoming signal is not an
    # invitation to relax a regime the tape itself raised today
    feed = BarsFeed(
        signal=True,
        daily={"SPY": hot(30.0), "QQQ": hot(30.0)},
        live={"SPY": SIGNAL_LIVE, "QQQ": {**QQQ_DOWN_LIVE, "live_vol": 18.0}},
    )
    state = run(DAY1, feed)
    assert state.qqq.effective == S
    feed.live["QQQ"] = SIGNAL_LIVE
    assert run(DAY1 + timedelta(hours=1), feed).qqq.effective == S


def test_the_regime_command_says_an_index_was_eased_by_a_bottoming_signal():
    from src.common.schemas import IndexRegime, RegimeInputs, RegimeState
    from src.notify.regime_notice import format_regime_status

    today = date(2026, 10, 21)

    def ir(index: str, effective: MarketRegime, eased: bool) -> IndexRegime:
        return IndexRegime(
            index=index,  # type: ignore[arg-type]
            base=S,
            base_date=today,
            since=today,
            base_since=today,
            effective=effective,
            eased_by_bottoming=eased,
            inputs=RegimeInputs(),
        )

    state = RegimeState(as_of=DAY1, spy=ir("SPY", S, False), qqq=ir("QQQ", C, True))
    text = format_regime_status(state, get_regime_cfg(), suspended=False)
    assert "QQQ: cautious (daily base stressed, eased one notch by a bottoming signal)" in text
    assert "raised today" not in text


# --------------------------------------------------------------------------- #
# the signal lot: guards, tags, record
# --------------------------------------------------------------------------- #


def bottoming_ctx(**kw) -> SizingContext:
    base = ctx(**kw)
    return base.model_copy(update={"name_bottoming": ["BAC"]})


def test_scale_in_reason_lets_a_signal_name_through_the_zone():
    c = bottoming_ctx()
    assert scale_in_reason(c, "BAC", 50.0) is None  # above the zone, but a bottom is forming
    assert signal_lot(c, "BAC", 50.0) is True
    assert signal_lot(c, "BAC", 46.0) is False  # inside the zone: an ordinary ladder lot
    assert signal_lot(c, "TQQQ", 50.0) is False
    assert signal_lot(ctx(), "BAC", 50.0) is False  # no signal, keep waiting
    assert scale_in_reason(ctx(), "BAC", 50.0) == "scale_in_zone_not_reached"
    # the signal does not survive /regime off (the zone is off too) or a loss exit the same day
    assert signal_lot(bottoming_ctx(suspended=True), "BAC", 50.0) is False


def test_signal_lot_guards():
    # delta 0.30 -> too high; 0.23 passes (a real far strike); a recent signal lot -> blocked
    near = csp("near", spot=50.0, delta=-0.30)
    far = csp("far", spot=50.0, delta=-0.23)
    out = gate([near, far], bottoming_ctx())
    assert out["near"].reasons == ["bottoming_delta_too_high"]
    assert out["far"].verdict == Verdict.PASS, out["far"].reasons
    assert bottoming_reason(bottoming_ctx(), far) is None
    assert bottoming_reason(bottoming_ctx(), near) == "bottoming_delta_too_high"

    recent = bottoming_ctx().model_copy(update={"signal_lot_recent": ["BAC"]})
    assert gate([csp("again", spot=50.0, delta=-0.23)], recent)["again"].reasons == [
        "bottoming_lot_recent"
    ]
    # a lot already inside the zone is an ordinary ladder lot: neither guard applies
    inside = csp("inside", spot=46.0, delta=-0.30)
    assert gate([inside], recent)["inside"].verdict == Verdict.PASS
    # and both codes are in both label maps with the same words
    from src.api.routers.options import _REASON_LABELS
    from src.notify.formatters import _REJECT_REASON_LABELS

    for code in ("bottoming_delta_too_high", "bottoming_lot_recent"):
        assert code in _REJECT_REASON_LABELS and _REJECT_REASON_LABELS[code] == _REASON_LABELS[code]


def test_the_sizer_applies_the_same_guards_and_a_real_far_strike_passes():
    signal = bottoming_ctx(zone=SIZER_ZONE)
    for delta, ok in ((-0.23, True), (-0.30, False)):
        result = screen_delta("BAC", 60.0, signal, delta)
        if ok:
            assert result.rejected == [], result.rejected
            note = result.passed[0].sizing
            assert note is not None and note.bottoming == "name"
            assert note.scale_in == SIZER_ZONE.model_copy(update={"bottoming_signal": True})
        else:
            assert result.passed == []
            assert "bottoming_delta_too_high" in result.rejected[0][1]
    # no signal: the ladder blocks the same candidate
    assert (
        "scale_in_zone_not_reached"
        in screen_delta("BAC", 60.0, ctx(SIZER_ZONE), -0.23).rejected[0][1]
    )


def screen_delta(symbol: str, price: float, sizing: SizingContext, delta: float):
    from src.common.schemas import (
        FundamentalStats,
        IVStats,
        OptionQuote,
        OptionRight,
        TechnicalStats,
    )
    from src.strategies.cash_secured_put import screen_csp_candidates
    from tests.test_scale_in_gate import _EXPIRY, _account_gen

    quote = OptionQuote(
        underlying=symbol,
        right=OptionRight.PUT,
        strike=50.0,
        expiry=_EXPIRY,
        bid=1.0,
        ask=1.05,
        delta=delta,
        open_interest=500,
        volume=100,
    )
    return screen_csp_candidates(
        symbol,
        [quote],
        _account_gen(),
        IVStats(symbol=symbol, iv_rank=50.0, current_iv=35.0, hv_30=20.0),
        TechnicalStats(symbol=symbol, price=price),
        FundamentalStats(symbol=symbol, quality_flag=True),
        sizing=sizing,
    )


def test_a_signal_lot_is_tagged_in_the_gate():
    far = csp("far", spot=50.0, delta=-0.23)
    gate([far], bottoming_ctx())
    assert far.sizing is not None and far.sizing.bottoming == "name"
    ordinary = csp("ord", spot=46.0, delta=-0.23)
    gate([ordinary], bottoming_ctx())
    assert ordinary.sizing is not None and ordinary.sizing.bottoming is None


def test_live_regate_does_not_reject_a_signal_lot_above_its_zone():
    """A lot opened above the zone on a name-level signal was validated at decision time; its
    frozen zone must not make the send-time ladder re-check refuse it. The same-day loss-exit
    block still applies."""
    from src.engine.risk_engine import validate_live_quote
    from tests.test_scale_in_gate import ZONE, framed, quote

    cand = framed(ZONE.model_copy(update={"bottoming_signal": True}))
    assert cand.sizing is not None
    cand.sizing = cand.sizing.model_copy(update={"bottoming": "name"})
    send = ctx(zone=None, for_send=True)
    assert (
        validate_live_quote(cand, quote(underlying_price=50.0), sizing=send).verdict == Verdict.PASS
    )
    blocked = ctx(zone=None, loss_exit_today=["BAC"], for_send=True)
    assert validate_live_quote(cand, quote(underlying_price=50.0), sizing=blocked).reasons == [
        "loss_exit_cooldown"
    ]


def test_signal_lot_uses_the_floor_when_the_book_is_full(monkeypatch):
    """The signal changes where the lot may open, never the budget (ruling 34)."""
    from src.common.schemas import OptionRight, PositionSnapshot

    config = get_config()
    risk = dict(config.risk)
    risk["portfolio"] = {**risk["portfolio"], "max_csp_allocation_pct_of_deployable": 130.0}
    monkeypatch.setattr(config, "risk", risk)
    full = [
        PositionSnapshot(
            symbol="BOOK 261120P",
            sec_type="OPT",
            position=-10.0,
            avg_cost=1.0,
            right=OptionRight.PUT,
            strike=323.2,  # $323,200 of collateral: over the stressed 40% budget, under the 130% cap
            expiry=date.today() + timedelta(days=30),
            underlying="BOOK",
        )
    ]
    stressed = bottoming_ctx().model_copy(
        update={"regimes": {"SPY": S, "QQQ": S}, "tech_linked": []}
    )
    cand = csp("sig", spot=50.0, delta=-0.23)
    out = gate([cand], stressed, positions=full)
    assert out["sig"].verdict == Verdict.PASS, out["sig"].reasons
    assert cand.sizing is not None
    assert cand.sizing.floor_lot is True and cand.sizing.bottoming == "name"
    # with the floor already used today the same lot is refused for the regime's budget
    used = stressed.model_copy(update={"floor_lots_counted": {"SPY": 1}})
    refused = gate([csp("sig2", spot=50.0, delta=-0.23)], used, positions=full)
    assert refused["sig2"].reasons == ["regime_budget"]


# --------------------------------------------------------------------------- #
# the context: who has a signal, who had a lot lately
# --------------------------------------------------------------------------- #


def test_the_context_marks_a_name_with_a_signal():
    # the anchor lot, then the quick drop of NAME_BARS into a support near 97 and the first up day
    anchor_day = NAME_BARS.index[-5]
    with session_scope() as s:
        seed_lot(
            s,
            symbol="BAC",
            strike=95.0,
            filled_at=datetime(anchor_day.year, anchor_day.month, anchor_day.day, 15, tzinfo=UTC),
            spot=100.0,
            contracts=2,
            expiry=(anchor_day + pd.Timedelta(days=25)).date(),
        )
        built = build_sizing_context(
            now=datetime.combine(
                NAME_BARS.index[-1].date() + timedelta(days=1), datetime.min.time(), UTC
            ).replace(hour=15),
            session=s,
            symbols=["BAC"],
            positions=[put(95.0, qty=-2, symbol="BAC")],
            bars={"BAC": NAME_BARS},
            spots={"BAC": 97.4},
        )
    assert built is not None
    assert "BAC" in built.scale_in, built.name_triggers
    zone = built.scale_in["BAC"]
    assert zone.zone_high < 97.0  # the support at 97 is above the zone: a level to wait past
    assert built.name_bottoming == ["BAC"]
    assert scale_in_reason(built, "BAC", 97.4) is None


def test_signal_lot_recent_reads_the_record_within_n_sessions():
    # a signal lot on Wed 2026-10-14: with three sessions between lots, Thu and Fri are blocked
    # and Mon 10-19 (three sessions later) is not
    with session_scope() as s:
        s.add(
            SizingActionRow(
                candidate_id="lot",
                underlying="BAC",
                strategy="cash_secured_put",
                right="P",
                strike=150.0,
                expiry=date(2026, 10, 30),
                premium=3.0,
                kind="bottoming_lot",
                regime="stressed",
                deterministic_contracts=1,
                sent_contracts=1,
                action_day=date(2026, 10, 14),
                record_key="lot",
            )
        )

    def recent(day: datetime):
        with session_scope() as s:
            built = build_sizing_context(now=day, session=s, symbols=[], positions=[], bars={})
        assert built is not None
        return built.signal_lot_recent

    assert recent(utc(2026, 10, 14, 17)) == ["BAC"]  # the same day
    assert recent(utc(2026, 10, 15, 17)) == ["BAC"]
    assert recent(utc(2026, 10, 16, 17)) == ["BAC"]
    assert recent(utc(2026, 10, 19, 17)) == []
    # a different kind of record is not a signal lot
    with session_scope() as s:
        s.query(SizingActionRow).update({"kind": "regime_ceiling"})
    assert recent(utc(2026, 10, 15, 17)) == []
