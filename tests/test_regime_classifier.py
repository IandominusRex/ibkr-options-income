"""The market-regime classifier (Task 1): schemas, config and the pure rules.

Everything here is offline: bars and live prices are injected, never fetched.
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import src.analytics.regime as regime
from src.analytics.regime import (
    ORDER,
    classify_base,
    ease_one,
    escalate_one,
    fetch_daily_inputs,
    fetch_live_inputs,
    get_bars,
    intraday_escalation,
    stricter,
)
from src.common.config import RegimeCfg, RegimeThresholdsCfg, get_regime_cfg
from src.common.schemas import MarketRegime, RegimeInputs

N = MarketRegime.NORMAL
C = MarketRegime.CAUTIOUS
S = MarketRegime.STRESSED
X = MarketRegime.CRISIS


def th() -> RegimeThresholdsCfg:
    return RegimeThresholdsCfg()


# --------------------------------------------------------------------------- #
# classify_base
# --------------------------------------------------------------------------- #


def test_calm_market_is_normal():
    inp = RegimeInputs(
        vol=15.3,
        vol_pct_1y=30,
        term_ratio=0.85,
        index_close=778.0,
        sma50=770.0,
        sma200=720.0,
        drawdown_52w_pct=1.0,
        ret_1m_pct=1.5,
    )
    assert classify_base(inp, th())[0] == N


@pytest.mark.parametrize(
    ("vol", "expected"),
    [(21.9, N), (23.0, C), (30.0, S), (37.0, X)],
)
def test_vol_level_sets_the_fast_regime(vol, expected):
    inp = RegimeInputs(vol=vol, term_ratio=0.9)
    regime_, why = classify_base(inp, th())
    assert regime_ == expected
    if expected != N:
        assert any("VIX" in w for w in why)


def test_backwardation_is_at_least_stressed():
    inp = RegimeInputs(vol=20.0, term_ratio=1.02)
    assert classify_base(inp, th())[0] == S


def test_deep_backwardation_is_crisis():
    inp = RegimeInputs(vol=20.0, term_ratio=1.12)
    assert classify_base(inp, th())[0] == X


def test_slow_signals_add_at_most_one_notch():
    # vol 15 (normal) + drawdown 12% + below the 200-day -> CAUTIOUS, never STRESSED
    inp = RegimeInputs(
        vol=15.0,
        term_ratio=0.9,
        index_close=600.0,
        sma50=640.0,
        sma200=650.0,
        drawdown_52w_pct=12.0,
        ret_1m_pct=-8.0,
    )
    assert classify_base(inp, th())[0] == C
    # ...and on top of a fast CAUTIOUS it makes STRESSED, one notch and no more
    inp2 = inp.model_copy(update={"vol": 23.0})
    assert classify_base(inp2, th())[0] == S


def test_below_sma50_and_falling_is_cautious():
    # Synthetic numbers pin the rule: close 728.95 under the 50-day (745) with a 1-month
    # return of -5.5% fires the slow bump on a calm fast regime. (QQQ's REAL 2026-10-14
    # numbers -- sma50 726.6, ret_1m +3.6%, close above the 50-day -- do not fire it;
    # Task 7 asserts the real outcome from the fixture.)
    inp = RegimeInputs(
        vol=17.0,
        term_ratio=0.90,
        index_close=728.95,
        sma50=745.0,
        sma200=690.0,
        drawdown_52w_pct=4.4,
        ret_1m_pct=-5.5,
    )
    regime_, why = classify_base(inp, th())
    assert regime_ == C
    assert any("slow" in w for w in why)


def test_below_sma50_alone_does_not_fire_the_slow_rule():
    inp = RegimeInputs(
        vol=17.0,
        term_ratio=0.9,
        index_close=740.0,
        sma50=745.0,
        sma200=690.0,
        drawdown_52w_pct=3.0,
        ret_1m_pct=-1.0,
    )
    assert classify_base(inp, th())[0] == N


def test_above_the_averages_with_a_good_month_stays_normal():
    # The shape of QQQ on 2026-10-14: above the 50-day, +3.6% on the month.
    inp = RegimeInputs(
        vol=16.5,
        term_ratio=0.9,
        index_close=740.0,
        sma50=726.6,
        sma200=680.0,
        drawdown_52w_pct=5.0,
        ret_1m_pct=3.6,
    )
    assert classify_base(inp, th())[0] == N


def test_percentile_rule_needs_the_90th_and_vix_20():
    # ruling 39: the 80th percentile fired at VIX 20.0 after a calm year.
    assert classify_base(RegimeInputs(vol=20.0, vol_pct_1y=82, term_ratio=0.9), th())[0] == N
    assert classify_base(RegimeInputs(vol=19.5, vol_pct_1y=95, term_ratio=0.9), th())[0] == N
    assert classify_base(RegimeInputs(vol=21.0, vol_pct_1y=92, term_ratio=0.9), th())[0] == C


def test_spy_week_of_oct_13_stays_normal():
    # SPY close 769.6, VIX 16.9, VIX/VIX3M 0.90 (spec section 19): the market regime did
    # nothing in the damage week, which is why the name-level rules matter more.
    inp = RegimeInputs(
        vol=16.9,
        vol_pct_1y=55,
        term_ratio=0.90,
        index_close=769.6,
        sma50=762.0,
        sma200=720.0,
        drawdown_52w_pct=2.0,
        ret_1m_pct=0.8,
    )
    assert classify_base(inp, th())[0] == N


def test_a_stale_fast_input_is_skipped_never_read_as_calm():
    # vol is stale: the rest of the picture decides, and the skip is named.
    stale_vol = RegimeInputs(
        vol=None,
        term_ratio=0.9,
        index_close=600.0,
        sma50=640.0,
        sma200=650.0,
        drawdown_52w_pct=12.0,
        stale=["vol"],
    )
    regime_, why = classify_base(stale_vol, th())
    assert regime_ == C  # the slow signals alone still imply a notch
    assert "stale:vol" in why
    # a stale vol that happens to hold an old number is ignored too
    old_number = stale_vol.model_copy(update={"vol": 40.0})
    assert classify_base(old_number, th())[0] == C  # not CRISIS from a stale number
    # ...and with no slow signal it is NORMAL, with the skip still named
    calm = RegimeInputs(term_ratio=0.9, stale=["vol", "vol_pct_1y"])
    regime_, why = classify_base(calm, th())
    assert regime_ == N
    assert "stale:vol" in why


# --------------------------------------------------------------------------- #
# intraday_escalation
# --------------------------------------------------------------------------- #


def test_intraday_qqq_minus_2_85_is_stressed():
    inp = RegimeInputs(day_change_pct=-2.85, live_vol=21.0)
    regime_, why = intraday_escalation("QQQ", inp, th())
    assert regime_ == S
    assert why == ["QQQ -2.9% today"]


def test_intraday_spy_minus_1_1_does_nothing():
    inp = RegimeInputs(day_change_pct=-1.1, live_vol=18.0)
    assert intraday_escalation("SPY", inp, th()) == (N, [])


def test_intraday_index_specific_thresholds():
    # SPY stressed at -2.0 / crisis at -3.5; QQQ stressed at -2.5 / crisis at -4.0
    assert intraday_escalation("SPY", RegimeInputs(day_change_pct=-2.0), th())[0] == S
    assert intraday_escalation("SPY", RegimeInputs(day_change_pct=-3.5), th())[0] == X
    assert intraday_escalation("QQQ", RegimeInputs(day_change_pct=-2.0), th())[0] == N
    assert intraday_escalation("QQQ", RegimeInputs(day_change_pct=-4.0), th())[0] == X


def test_live_vix_40_is_crisis():
    assert intraday_escalation("SPY", RegimeInputs(live_vol=40.0), th())[0] == X
    assert intraday_escalation("SPY", RegimeInputs(live_vol=30.0), th())[0] == S
    assert intraday_escalation("SPY", RegimeInputs(live_vol=29.9), th())[0] == N


def test_stale_live_input_cannot_escalate_or_calm():
    inp = RegimeInputs(day_change_pct=-5.0, stale=["day_change_pct"])
    # a stale -5% must not escalate, and the skip is named
    assert intraday_escalation("SPY", inp, th()) == (N, ["stale:day_change_pct"])
    # a stale live VIX of 45 must not escalate either
    inp2 = RegimeInputs(live_vol=45.0, stale=["live_vol"])
    assert intraday_escalation("SPY", inp2, th()) == (N, ["stale:live_vol"])
    # a genuine breach elsewhere still escalates beside a stale field
    inp3 = RegimeInputs(day_change_pct=-5.0, live_vol=41.0, stale=["day_change_pct"])
    regime_, why = intraday_escalation("SPY", inp3, th())
    assert regime_ == X
    assert "stale:day_change_pct" in why


# --------------------------------------------------------------------------- #
# ordering helpers
# --------------------------------------------------------------------------- #


def test_stricter_and_ease_and_escalate_clamp():
    assert ORDER == (N, C, S, X)
    assert stricter(C, S) == S
    assert stricter(X, N) == X
    assert stricter(N, N) == N
    assert escalate_one(N) == C
    assert escalate_one(X) == X  # clamped at the severe end
    assert ease_one(X) == S
    assert ease_one(N) == N  # clamped at the calm end


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #


def test_regime_cfg_defaults_when_block_absent(monkeypatch):
    from src.common.config import get_config

    risk = {k: v for k, v in get_config().risk.items() if k != "regime"}
    monkeypatch.setattr(get_config(), "risk", risk)
    cfg = get_regime_cfg()
    assert cfg.enabled is True
    assert cfg.csp.budget_multiplier[S] == 0.4
    assert cfg.csp.per_trade_fraction[X] == 0.1
    assert cfg.csp.max_new_per_day[N] is None
    assert cfg.csp.max_new_per_day[C] == 6
    assert "TQQQ" in cfg.tech_linked
    assert cfg.thresholds.vol_pct_cautious == 90.0
    assert cfg.thresholds.vol_pct_min_vol == 20.0


def test_regime_cfg_partial_block_fills_the_rest(monkeypatch):
    from src.common.config import get_config

    risk = dict(get_config().risk)
    risk["regime"] = {"csp": {"budget_multiplier": {"crisis": 0.0}}}
    monkeypatch.setattr(get_config(), "risk", risk)
    cfg = get_regime_cfg()
    assert cfg.csp.budget_multiplier[X] == 0.0
    assert cfg.csp.budget_multiplier[C] == 0.7  # untouched regimes keep the default


def test_regime_cfg_rejects_a_fraction_above_one():
    with pytest.raises(ValueError, match="between 0 and 1"):
        RegimeCfg(csp={"per_trade_fraction": {"cautious": 1.2}})
    with pytest.raises(ValueError, match="between 0 and 1"):
        RegimeCfg(csp={"budget_multiplier": {"stressed": -0.1}})


def test_regime_cfg_rejects_unordered_thresholds():
    with pytest.raises(ValueError, match="vol_cautious"):
        RegimeCfg(thresholds={"vol_cautious": 30.0, "vol_stressed": 28.0})
    with pytest.raises(ValueError, match="crisis <= stressed"):
        RegimeCfg(thresholds={"intraday": {"SPY": {"stressed": -3.0, "crisis": -2.0}}})


def test_regime_cfg_rejects_a_mistyped_key():
    # A typo must fail loudly: otherwise pydantic drops it and the shipped default stays in
    # force while the operator believes a limit is set.
    with pytest.raises(ValueError, match="unknown key"):
        RegimeCfg(thresholds={"vol_cautios": 18.0})
    with pytest.raises(ValueError, match="unknown key"):
        RegimeCfg(csp={"per_trade_fractoin": {"stressed": 0.2}})
    with pytest.raises(ValueError, match="unknown key"):
        RegimeCfg(thresholds={"intraday": {"SPY": {"stresed": -2.0, "crisis": -3.5}}})
    with pytest.raises(ValueError, match="unknown key"):
        RegimeCfg(enabld=False)


def test_regime_cfg_key_lists_match_the_model_fields():
    from src.common.config import (
        RegimeCspCfg,
        RegimeIndexIntradayCfg,
        RegimeIntradayCfg,
    )

    for model in (
        RegimeCfg,
        RegimeCspCfg,
        RegimeThresholdsCfg,
        RegimeIntradayCfg,
        RegimeIndexIntradayCfg,
    ):
        assert set(model.KEYS) == set(model.model_fields), model.__name__


def test_shipped_example_block_parses_to_the_documented_values():
    cfg = get_regime_cfg()  # tests run on config/examples/risk_limits.yaml
    assert cfg.enabled is True
    assert cfg.csp.budget_multiplier == {N: 1.0, C: 0.7, S: 0.4, X: 0.1}
    assert cfg.csp.per_trade_fraction == {N: 1.0, C: 0.6, S: 0.3, X: 0.1}
    assert cfg.csp.max_new_per_day == {N: None, C: 6, S: 3, X: 1}
    th_ = cfg.thresholds
    assert (th_.vol_cautious, th_.vol_stressed, th_.vol_crisis) == (22.0, 28.0, 36.0)
    assert th_.intraday.QQQ.stressed == -2.5
    assert th_.intraday.vix_crisis == 40.0
    assert "MARA" in cfg.tech_linked and "TSLL" in cfg.tech_linked


# --------------------------------------------------------------------------- #
# bars and the fetchers
# --------------------------------------------------------------------------- #


def _frame(closes: list[float], end: date, *, tz: str | None = None) -> pd.DataFrame:
    """Daily bars ending on *end*, one per calendar day (the dates, not the weekdays, matter)."""
    idx = pd.DatetimeIndex(
        [pd.Timestamp(end - timedelta(days=len(closes) - 1 - i)) for i in range(len(closes))]
    )
    if tz:
        idx = idx.tz_localize(tz)
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame(
        {"Open": c, "High": c * 1.005, "Low": c * 0.995, "Close": c, "Volume": 1_000_000.0}
    )


def test_get_bars_drops_todays_forming_bar(monkeypatch):
    today = date(2026, 10, 21)
    # the index provider's frame ends with today's forming bar and carries a tz (ET)
    monkeypatch.setattr(
        regime, "_load_raw", lambda symbol: _frame([15.0, 16.0, 17.0], today, tz="America/New_York")
    )
    out = get_bars("^VIX", today=today)
    assert out.index[-1].date() == today - timedelta(days=1)
    assert float(out["Close"].iloc[-1]) == 16.0
    assert out.index.tz is None  # naive and ascending: one shape for every caller
    # the rule holds for stocks too, not only indices
    monkeypatch.setattr(regime, "_load_raw", lambda symbol: _frame([700.0, 701.0], today))
    assert get_bars("SPY", today=today).index[-1].date() == today - timedelta(days=1)


def test_get_bars_never_raises_and_returns_an_empty_frame(monkeypatch):
    def boom(symbol: str) -> pd.DataFrame:
        raise RuntimeError("yfinance is down")

    monkeypatch.setattr(regime, "_load_raw", boom)
    out = get_bars("SPY", today=date(2026, 10, 21))
    assert out.empty


_NOW_RTH = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)  # Wed 11:00 ET
_NOW_CLOSED = datetime(2026, 10, 21, 1, 0, tzinfo=UTC)  # Tue 21:00 ET


def test_fetch_live_inputs_outside_rth_is_stale():
    def never(symbol: str) -> float | None:
        raise AssertionError("no live fetch outside RTH")

    out = fetch_live_inputs("QQQ", 700.0, now=_NOW_CLOSED, last_price=never)
    assert out["day_change_pct"] is None
    assert out["live_vol"] is None
    assert out["index_live"] is None
    assert "day_change_pct" in out["stale"]
    assert "live_vol" in out["stale"]


def test_fetch_live_inputs_in_rth_computes_the_day_change():
    prices = {"QQQ": 680.0, "^VIX": 24.5}
    out = fetch_live_inputs("QQQ", 700.0, now=_NOW_RTH, last_price=prices.get, prior_vol_close=18.0)
    assert out["index_live"] == pytest.approx(680.0)
    assert out["day_change_pct"] == pytest.approx(-2.857, abs=0.01)
    assert out["live_vol"] == pytest.approx(24.5)
    assert out["stale"] == []


def test_live_value_equal_to_the_prior_close_is_stale():
    # ruling 39: yfinance's lastPrice carries no timestamp, so a value that equals the prior
    # close to 4 decimals is a last close served as live.
    prices = {"SPY": 769.6, "^VIX": 16.9}
    out = fetch_live_inputs("SPY", 769.6, now=_NOW_RTH, last_price=prices.get, prior_vol_close=16.9)
    assert out["day_change_pct"] is None
    assert out["index_live"] is None
    assert out["live_vol"] is None
    assert {"index_live", "day_change_pct", "live_vol"} <= set(out["stale"])
    # a 5th-decimal wobble is still "equal to 4 decimals"
    prices2 = {"SPY": 769.60004, "^VIX": 16.9}
    out2 = fetch_live_inputs("SPY", 769.6, now=_NOW_RTH, last_price=prices2.get)
    assert out2["day_change_pct"] is None


def test_a_missing_live_price_is_stale():
    out = fetch_live_inputs("SPY", 769.6, now=_NOW_RTH, last_price=lambda s: None)
    assert out["day_change_pct"] is None and out["live_vol"] is None
    assert {"index_live", "day_change_pct", "live_vol"} <= set(out["stale"])


def test_a_raising_live_price_is_stale_not_fatal():
    def boom(symbol: str) -> float | None:
        raise RuntimeError("fast_info blew up")

    out = fetch_live_inputs("SPY", 769.6, now=_NOW_RTH, last_price=boom)
    assert out["day_change_pct"] is None
    assert "day_change_pct" in out["stale"]


def _bars_for(today: date, *, index_closes, vix_closes, vix3m_closes):
    def bars(symbol: str) -> pd.DataFrame:
        series = {
            "SPY": index_closes,
            "QQQ": index_closes,
            "^VIX": vix_closes,
            "^VIX3M": vix3m_closes,
        }
        closes = series.get(symbol)
        if closes is None:
            return pd.DataFrame()
        return _frame(closes, today - timedelta(days=1))

    return bars


def test_fetch_daily_inputs_from_synthetic_bars():
    today = date(2026, 10, 21)
    rng = np.random.default_rng(7)
    idx = list(700 + np.cumsum(rng.normal(0.4, 3.0, 300)))
    idx[-1] = idx[-1] - 20.0  # a drop on the last day so the 52-week drawdown is real
    vix = [15.0] * 290 + [15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0]
    vix3m = [18.0] * 290 + [18.0, 19.0, 19.0, 19.5, 20.0, 21.0, 22.0, 22.5, 23.0, 23.0]
    bars = _bars_for(today, index_closes=idx, vix_closes=vix, vix3m_closes=vix3m)
    inp = fetch_daily_inputs("SPY", bars=bars, today=today)
    assert inp.index_close == pytest.approx(idx[-1])
    assert inp.sma50 == pytest.approx(float(np.mean(idx[-50:])))
    assert inp.sma200 == pytest.approx(float(np.mean(idx[-200:])))
    assert inp.vol == 24.0
    assert inp.term_ratio == pytest.approx(24.0 / 23.0, abs=1e-3)
    assert inp.vol_pct_1y is not None and inp.vol_pct_1y > 95  # the highest close of the year
    peak = max(idx[-252:])
    assert inp.drawdown_52w_pct == pytest.approx((1 - idx[-1] / peak) * 100, abs=1e-2)
    assert inp.ret_1m_pct == pytest.approx((idx[-1] / idx[-22] - 1) * 100, abs=1e-2)
    assert inp.ret_3m_pct == pytest.approx((idx[-1] / idx[-64] - 1) * 100, abs=1e-2)
    assert inp.rv20 is not None and inp.rv20 > 0
    assert inp.rv_1y_avg is not None and inp.rv_1y_avg > 0
    # the term ratio crossed above 1 on the last day only: no contango streak to ease on
    assert inp.contango_streak == 0
    assert inp.stale == []


def test_contango_streak_counts_consecutive_closes_below_one():
    today = date(2026, 10, 21)
    idx = [700.0 + i for i in range(260)]
    vix = [20.0] * 260
    vix3m = [19.0] * 255 + [22.0, 22.0, 22.0, 22.0, 22.0]  # last five closes in contango
    inp = fetch_daily_inputs(
        "SPY",
        bars=_bars_for(today, index_closes=idx, vix_closes=vix, vix3m_closes=vix3m),
        today=today,
    )
    assert inp.contango_streak == 5
    assert inp.term_ratio is not None and inp.term_ratio < 1.0


def test_missing_vix_frames_are_named_stale_not_calm():
    today = date(2026, 10, 21)
    idx = [700.0 + i for i in range(260)]

    def bars(symbol: str) -> pd.DataFrame:
        return _frame(idx, today - timedelta(days=1)) if symbol == "SPY" else pd.DataFrame()

    inp = fetch_daily_inputs("SPY", bars=bars, today=today)
    assert inp.vol is None and inp.term_ratio is None and inp.vol_pct_1y is None
    assert {"vol", "vol_pct_1y", "term_ratio"} <= set(inp.stale)
    assert inp.index_close is not None  # the index data is still used


def test_old_daily_bars_are_flagged_stale(monkeypatch):
    # yfinance down: the DB store serves a last close from weeks ago. It must not be read
    # as today's calm market.
    today = date(2026, 10, 21)
    old_end = today - timedelta(days=30)
    idx = [700.0 + i for i in range(260)]

    def bars(symbol: str) -> pd.DataFrame:
        return _frame([15.0] * 260 if symbol.startswith("^") else idx, old_end)

    inp = fetch_daily_inputs("SPY", bars=bars, today=today)
    assert inp.index_close is None and inp.vol is None
    assert {"index_close", "vol"} <= set(inp.stale)


def test_fetch_daily_inputs_never_raises():
    def boom(symbol: str) -> pd.DataFrame:
        raise RuntimeError("no network")

    inp = fetch_daily_inputs("QQQ", bars=boom)
    assert inp.index_close is None
    assert "index_close" in inp.stale


# --------------------------------------------------------------------------- #
# the tier
# --------------------------------------------------------------------------- #


def test_regime_module_stays_in_the_deterministic_tier():
    """analytics/regime.py feeds the engine's sizing: it may read price data and nothing from
    the enrichment tier (macro, sentiment, sector context) or the reasoning layer."""
    path = Path(__file__).resolve().parents[1] / "src" / "analytics" / "regime.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
            imported.extend(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
    forbidden = (
        "src.analytics.market_conditions",
        "src.analytics.sentiment",
        "src.analytics.sector_context",
        "src.claude",
        "src.news",
        "src.spreads_ai",
    )
    offenders = [m for m in imported if any(m == f or m.startswith(f + ".") for f in forbidden)]
    assert not offenders, f"regime.py reaches the enrichment tier: {offenders}"
