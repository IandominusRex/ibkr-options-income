"""The leveraged sleeve (risk-envelope Task 23; spec §3.5 as revised by rev 3, rulings E7, L1-L4).

A leveraged ETF gets a cash-secured put only through the sleeve: above its governing index's
200-day average the LES pullback is the signal, below it only the bottoming + sigma-drawdown path
opens a lot (at half the tier); its DTE and delta windows replace the put's own; the size is the LES
tier's room, leverage-weighted with every other leveraged put and LES share, rounded down. The
generator (`screen_csp_candidates`) and the gate (`validate_candidates`) apply the same functions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.analytics.leveraged_entry import sigma_drawdown
from src.analytics.shock import measure
from src.common.books import LesExposure
from src.common.config import get_config, get_leveraged_sizing_cfg, get_regime_cfg
from src.common.envelope_types import BookLine, EnvelopeRoom, ShockInputs
from src.common.market_hours import today_et
from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    LesSignal,
    MarketRegime,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    SizingContext,
    SizingNote,
    TechnicalStats,
    Verdict,
)
from src.common.universe import invalidate_universe_cache
from src.engine import regime_limits as rl
from src.engine.risk_engine import validate_candidates
from src.strategies.cash_secured_put import screen_csp_candidates
from tests.test_engine import _account, _candidate

N = MarketRegime.NORMAL
NLV = 500_000.0
STRIKE = 40.0  # a TQQQ lot: 40 x 100 x 3 = $12,000 at leverage, 2.4% of a $500k account
TECH = ["QQQ", "TQQQ", "SOXL", "SOXX", "NVDA"]
LEVERAGE = {"TQQQ": 3, "SOXL": 3}


@pytest.fixture(autouse=True)
def _universe(monkeypatch):
    cfg = get_config()
    names = ["NVDA", "TQQQ", "SOXL"]
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": names,
            "actively_wheeling": names,
            "sectors": {n: "tech" for n in names},
            "leveraged_etfs": ["TQQQ", "SOXL"],
        },
    )
    invalidate_universe_cache()
    yield
    invalidate_universe_cache()


def les(
    index: str = "QQQ",
    *,
    trend_up: bool = True,
    pullback: bool = True,
    washout: bool = False,
    tier: float | None = None,
) -> LesSignal:
    return LesSignal(
        asof=today_et(),
        index=index,
        trend_up=trend_up,
        pullback=pullback and trend_up,
        washout=washout and trend_up,
        trend_break=False,
        tier_pct=tier if tier is not None else (6.0 if washout else 3.0 if pullback else 0.0),
    )


def ctx(
    *,
    on: bool = True,
    signal: LesSignal | None = None,
    below_trend: list[str] | None = None,
    recent: list[str] | None = None,
    for_send: bool = False,
    bottoming: bool = False,
) -> SizingContext:
    sig = signal if signal is not None else les()
    return SizingContext(
        regimes={"SPY": N, "QQQ": N},
        tech_linked=TECH,
        leverage=dict(LEVERAGE),
        switches={"leveraged_sleeve": "on" if on else "off"},
        les={sig.index: sig},
        sleeve_below_trend=below_trend or [],
        sleeve_recent=recent or [],
        market_bottoming={"QQQ": bottoming},
        for_send=for_send,
    )


def account(nlv: float = NLV) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=nlv,
        total_cash=nlv * 0.8,
        buying_power=nlv * 0.8,
        maintenance_margin=0.0,
        excess_liquidity=nlv * 0.8,
    )


def short_put(strike: float = STRIKE, qty: float = 1.0, expiry_days: int = 10) -> PositionSnapshot:
    return PositionSnapshot(
        symbol="TQQQ P",
        sec_type="OPT",
        position=-qty,
        avg_cost=1.0,
        right=OptionRight.PUT,
        strike=strike,
        expiry=today_et() + timedelta(days=expiry_days),
        underlying="TQQQ",
    )


def quote(
    *, dte: int = 10, delta: float = -0.17, bid: float = 1.0, ask: float = 1.05
) -> OptionQuote:
    return OptionQuote(
        underlying="TQQQ",
        right=OptionRight.PUT,
        strike=STRIKE,
        expiry=today_et() + timedelta(days=dte),
        bid=bid,
        ask=ask,
        delta=delta,
        open_interest=500,
        volume=100,
    )


def screen(
    sizing: SizingContext | None,
    *,
    positions=None,
    nlv: float = NLV,
    iv_rank: float | None = 60.0,
    **q,
):
    return screen_csp_candidates(
        "TQQQ",
        [quote(**q)],
        account(nlv),
        IVStats(symbol="TQQQ", iv_rank=iv_rank, current_iv=35.0, hv_30=20.0),
        TechnicalStats(symbol="TQQQ", price=60.0),
        FundamentalStats(symbol="TQQQ", quality_flag=True),
        positions=positions,
        sizing=sizing,
    )


def reasons_of(result) -> list[str]:
    assert not result.passed, [c.contracts for c in result.passed]
    (_, reasons), *_ = result.rejected
    return reasons


def sleeve_card(contracts: int = 1, *, dte: int = 10, delta: float = -0.17, path="trend"):
    return _candidate(
        candidate_id="sl",
        underlying="TQQQ",
        contracts=contracts,
        collateral=STRIKE * 100.0 * contracts,
        dte=dte,
        delta=delta,
        iv_rank=60.0,
        current_iv=35.0,
    ).model_copy(
        update={
            "strike": STRIKE,
            "premium": 1.0,
            "sizing": SizingNote(
                pre_regime_contracts=10,
                regime=N,
                regime_index="QQQ",
                per_trade_cap=6,
                budget_multiplier=1.0,
                sleeve=path,
            ),
        }
    )


def gate(cards, sizing, *, positions=None, nlv: float = NLV, envelope=None):
    acct = _account(net_liq=nlv, cash=nlv * 0.8)
    out = validate_candidates(cards, acct, positions or [], sizing=sizing, envelope=envelope)
    return {v.candidate_id: v for v in out}


# --------------------------------------------------------------------------- #
# the switch and the signal
# --------------------------------------------------------------------------- #


def test_the_sleeve_switch_off_closes_it():
    off = ctx(on=False)
    assert rl.sleeve_tier(off, "TQQQ") == 0.0 and not rl.sleeve_lot(off, "TQQQ")
    assert rl.per_trade_cap(off, "TQQQ", 10) == 0
    assert "regime_ceiling" in reasons_of(screen(off))
    assert gate([sleeve_card()], off)["sl"].verdict == Verdict.REJECT
    on = ctx()
    assert rl.per_trade_cap(on, "TQQQ", 10) > 0
    assert [c.contracts for c in screen(on).passed] == [1]
    assert gate([sleeve_card()], on)["sl"].verdict == Verdict.PASS


def test_every_switch_is_off_in_live_so_the_sleeve_is_closed(db, monkeypatch):
    from datetime import UTC, datetime

    from src.common.config import Config
    from src.regime.context import build_sizing_context
    from src.storage.db import session_scope
    from src.storage.envelope_switches import set_switch
    from src.storage.les_state import record_signal

    set_switch("leveraged_sleeve", "on", source="cli")
    record_signal(les())
    with session_scope() as s:
        paper = build_sizing_context(now=datetime.now(UTC), session=s, for_send=True)
    assert paper is not None and paper.switches["leveraged_sleeve"] == "on"
    assert paper.les["QQQ"].tier_pct == 3.0
    monkeypatch.setattr(Config, "is_live", property(lambda self: True))
    with session_scope() as s:
        live = build_sizing_context(now=datetime.now(UTC), session=s, for_send=True)
    assert live is not None and live.switches["leveraged_sleeve"] == "off"
    assert rl.sleeve_tier(live, "TQQQ") == 0.0


def test_a_missing_or_stale_signal_fails_closed(db):
    from src.regime.context import build_sizing_context
    from src.storage.db import session_scope
    from src.storage.envelope_switches import set_switch
    from src.storage.les_state import record_signal

    set_switch("leveraged_sleeve", "on", source="cli")
    with session_scope() as s:
        none_yet = build_sizing_context(now=datetime.now(UTC), session=s, for_send=True)
    assert none_yet is not None and none_yet.les == {}
    assert rl.sleeve_tier(none_yet, "TQQQ") == 0.0
    stale = les().model_copy(update={"asof": today_et() - timedelta(days=9)})
    record_signal(stale)
    with session_scope() as s:
        ctx_stale = build_sizing_context(now=datetime.now(UTC), session=s, for_send=True)
    assert ctx_stale is not None and "QQQ" not in ctx_stale.les


# --------------------------------------------------------------------------- #
# spec §3.5 conditions, one test each
# --------------------------------------------------------------------------- #


def test_condition_1_above_the_200_day_the_les_pullback_is_the_signal():
    pullback = ctx(signal=les())
    assert rl.sleeve_path(pullback, "TQQQ") == "trend" and rl.sleeve_tier(pullback, "TQQQ") == 3.0
    no_pullback = ctx(signal=les(pullback=False))
    assert rl.sleeve_tier(no_pullback, "TQQQ") == 0.0
    assert reasons_of(screen(no_pullback))  # the sleeve is closed: no lot


def test_conditions_2_and_3_do_not_apply_above_the_200_day():
    c = ctx()  # no bottoming signal, no sigma drawdown, a low IV rank
    assert [x.contracts for x in screen(c, iv_rank=10.0).passed] == [1]
    assert gate([sleeve_card()], c)["sl"].verdict == Verdict.PASS


def test_conditions_1_to_3_below_the_200_day_need_bottoming_drawdown_and_iv_rank():
    below = les(trend_up=False)
    closed = ctx(signal=below)  # bottoming + drawdown not established
    assert rl.sleeve_path(closed, "TQQQ") is None
    open_ = ctx(signal=below, below_trend=["TQQQ"])
    assert rl.sleeve_path(open_, "TQQQ") == "below_trend"
    assert rl.sleeve_tier(open_, "TQQQ") == get_regime_cfg().leveraged_entry.tiers.below_trend
    # condition 3: IV rank >= 50, unknown fails closed
    assert "sleeve_window" in reasons_of(screen(open_, iv_rank=40.0, nlv=2_000_000.0))
    assert "sleeve_window" in reasons_of(screen(open_, iv_rank=None, nlv=2_000_000.0))
    assert [c.contracts for c in screen(open_, iv_rank=60.0, nlv=2_000_000.0).passed] == [2]
    low = sleeve_card(path="below_trend").model_copy(update={"iv_rank": 40.0})
    got = gate([low], ctx(signal=below, below_trend=["TQQQ"]), nlv=2_000_000.0)
    assert "sleeve_window" in got["sl"].reasons


def test_the_below_trend_path_at_send_time_reads_the_frozen_tag():
    below = les(trend_up=False)
    send = ctx(signal=below, for_send=True)  # no bars at send time, so no scan-time list
    assert rl.sleeve_path(send, "TQQQ") is None
    frozen = SizingNote(
        pre_regime_contracts=1,
        regime=N,
        regime_index="QQQ",
        per_trade_cap=1,
        budget_multiplier=1.0,
        sleeve="below_trend",
    )
    assert rl.sleeve_path(send, "TQQQ", frozen) == "below_trend"
    # a card tagged "trend" does not pass a below-trend send-time context
    assert rl.sleeve_path(send, "TQQQ", frozen.model_copy(update={"sleeve": "trend"})) is None


def test_condition_4_dte_window_7_to_14():
    c = ctx()
    for dte in (7, 14):
        assert [x.contracts for x in screen(c, dte=dte).passed] == [1], dte
    for dte in (6, 15, 30):
        assert "sleeve_window" in reasons_of(screen(c, dte=dte)), dte
        assert "sleeve_window" in gate([sleeve_card(dte=dte)], c)["sl"].reasons, dte
    # the put's own DTE band is not applied to a sleeve lot
    assert "dte_out_of_range" not in reasons_of(screen(c, dte=30))


def test_condition_5_delta_window_015_to_020():
    c = ctx()
    for delta in (-0.15, -0.17, -0.20):
        assert [x.contracts for x in screen(c, delta=delta).passed] == [1], delta
        assert gate([sleeve_card(delta=delta)], c)["sl"].verdict == Verdict.PASS, delta
    for delta in (-0.12, -0.25):
        assert "sleeve_window" in reasons_of(screen(c, delta=delta)), delta
        assert "sleeve_window" in gate([sleeve_card(delta=delta)], c)["sl"].reasons, delta


def test_condition_6_the_fair_value_floor_applies_to_a_sleeve_lot():
    c = ctx()
    # a credit under Black-Scholes fair value at realised vol is refused, whatever the sleeve says
    from src.analytics.fair_value import compute_ideal_zone, zone_for_contract
    from src.common.schemas import Strategy

    stats = TechnicalStats(symbol="TQQQ", price=41.0)
    iv = IVStats(symbol="TQQQ", iv_rank=60.0, current_iv=35.0, hv_30=60.0)
    zone = compute_ideal_zone(
        symbol="TQQQ",
        right=OptionRight.PUT,
        dte=10,
        spot=41.0,
        tech=stats,
        iv=iv,
        fund=FundamentalStats(symbol="TQQQ", quality_flag=True),
    )
    floor = zone_for_contract(zone, STRIKE, iv).min_credit
    assert floor is not None and floor > 0
    cheap = screen_csp_candidates(
        "TQQQ",
        [quote(bid=0.04, ask=0.06)],
        account(),
        iv,
        stats,
        FundamentalStats(symbol="TQQQ", quality_flag=True),
        positions=[],
        sizing=c,
    )
    assert "premium_below_fair_value" in reasons_of(cheap)
    assert rl.vrp_waiver(c, Strategy.CASH_SECURED_PUT, "TQQQ", 41.0) is False


def test_condition_7_pace_one_lot_per_name_per_3_sessions_and_two_open():
    assert "sleeve_pace" in reasons_of(screen(ctx(recent=["TQQQ"])))
    assert "sleeve_pace" in gate([sleeve_card()], ctx(recent=["TQQQ"]))["sl"].reasons
    c = ctx(signal=les(washout=True))  # the 6% tier has room: only the pace can refuse
    two_open = [short_put(30.0, expiry_days=9), short_put(31.0, expiry_days=9)]
    assert get_leveraged_sizing_cfg().sleeve.max_open_lots == 2
    assert "sleeve_pace" in reasons_of(screen(c, positions=two_open))
    assert "sleeve_pace" in gate([sleeve_card()], c, positions=two_open)["sl"].reasons
    one_open = [short_put(30.0, expiry_days=9)]
    assert [x.contracts for x in screen(c, positions=one_open).passed] == [1]
    # a lot accepted earlier in the same batch counts as open
    a = sleeve_card()
    b = sleeve_card().model_copy(update={"candidate_id": "sl2", "underlying": "SOXL"})
    c = c.model_copy(update={"les": {**c.les, "SOXX": les("SOXX", washout=True)}})
    got = gate([a, b], c, positions=one_open)
    assert got["sl"].verdict == Verdict.PASS and "sleeve_pace" in got["sl2"].reasons


def test_condition_9_the_envelope_is_tested_for_a_sleeve_lot():
    def inputs() -> ShockInputs:
        names = {"BOOK", "TQQQ", "QQQ"}
        return ShockInputs(
            lines=(BookLine(symbol="BOOK", kind="stock", qty=2_000.0, spot=100.0),),
            betas={s: 1.0 for s in names},
            betas_smh={s: 1.0 for s in names},
            leverage={"TQQQ": 3},
            governing={"TQQQ": "QQQ"},
            tech_linked=frozenset(),
            semis=frozenset(),
            nlv=NLV,
        )

    def room(s10_limit: float) -> tuple[EnvelopeRoom, ShockInputs]:
        inp = inputs()
        res = measure(inp)
        return (
            EnvelopeRoom(
                s10_gross=res.s10,
                s10_limit=s10_limit,
                uew=res.uew,
                uew_limit=9.0,
                t20_gross=res.t20,
                t20_limit=None,
                enforce="on",
                measured=res.measured,
                reasons_if_unmeasured=(),
            ),
            inp,
        )

    card = sleeve_card().model_copy(update={"quote_iv": 0.9, "underlying_price": 60.0})
    c = ctx()
    assert gate([card], c, envelope=room(99.0))["sl"].verdict == Verdict.PASS
    tight = gate([card], c, envelope=room(measure(inputs()).s10 + 0.0001))
    assert tight["sl"].reasons == ["shock_budget"]


# --------------------------------------------------------------------------- #
# the cap: the LES tier, leverage-weighted, CSPs and LES shares together
# --------------------------------------------------------------------------- #


def test_tier_caps_csp_and_les_shares_together(monkeypatch):
    c = ctx(signal=les(washout=True))  # 6%: $30k on a $500k account
    acct = account()
    assert rl.sleeve_room_usd(c, "TQQQ", acct, []) == pytest.approx(30_000.0)
    # an open leveraged put: 40 x 100 x 3 = 12,000 of the tier
    assert rl.sleeve_room_usd(c, "TQQQ", acct, [short_put()]) == pytest.approx(18_000.0)
    # LES shares count too, each at its leverage: $2,000 of TQQQ shares = 6,000
    monkeypatch.setattr(rl, "les_exposure", lambda: LesExposure(by_name={"TQQQ": 2_000.0}))
    assert rl.sleeve_room_usd(c, "TQQQ", acct, [short_put()]) == pytest.approx(12_000.0)
    # one lot fits (12,000) and a second does not
    assert rl.sleeve_contracts(12_000.0, STRIKE, 3) == 1
    assert [x.contracts for x in screen(c, positions=[short_put()]).passed] == [1]
    monkeypatch.setattr(rl, "les_exposure", lambda: LesExposure(by_name={"TQQQ": 3_000.0}))
    assert "sleeve_cap" in reasons_of(screen(c, positions=[short_put()]))
    assert "sleeve_cap" in gate([sleeve_card()], c, positions=[short_put()])["sl"].reasons
    # the room is leverage-weighted across names: a SOXL put uses the same tier
    soxl = short_put(50.0).model_copy(update={"underlying": "SOXL", "symbol": "SOXL P"})
    assert rl.sleeve_used_usd(c, [short_put(), soxl]) == pytest.approx(
        12_000.0 + 15_000.0 + 9_000.0
    )


def test_washout_tier_allows_a_second_lot():
    assert [x.contracts for x in screen(ctx(signal=les()), positions=[]).passed] == [1]  # 3%
    assert [x.contracts for x in screen(ctx(signal=les(washout=True))).passed] == [2]  # 6%
    two = sleeve_card(2)
    assert gate([two], ctx(signal=les(washout=True)))["sl"].verdict == Verdict.PASS
    assert "sleeve_cap" in gate([two], ctx())["sl"].reasons  # a 3% tier holds one lot


def test_below_trend_half_tier_rounds_to_zero_lots_at_todays_prices():
    """TQQQ lot ~ 2.8% of NLV at leverage, over the 1.5% half tier: no lot, never a minimum of one."""
    c = ctx(signal=les(trend_up=False), below_trend=["TQQQ"])
    assert rl.sleeve_contracts(rl.sleeve_room_usd(c, "TQQQ", account(650_000.0), []), 56.0, 3) == 0
    assert "sleeve_cap" in reasons_of(screen(c, nlv=650_000.0))
    assert "sleeve_cap" in gate([sleeve_card(path="below_trend")], c, nlv=650_000.0)["sl"].reasons


def test_lots_never_round_up():
    assert rl.sleeve_contracts(11_999.99, STRIKE, 3) == 0
    assert rl.sleeve_contracts(12_000.0, STRIKE, 3) == 1
    assert rl.sleeve_contracts(23_999.0, STRIKE, 3) == 1
    assert rl.sleeve_contracts(0.0, STRIKE, 3) == 0
    assert rl.sleeve_contracts(10_000.0, 0.0, 3) == 0


def test_a_sleeve_reason_is_never_erased_by_the_regime_rewrite():
    """P4: sleeve_cap is appended after the regime rewrite, like the envelope's reasons."""
    got = gate([sleeve_card(3)], ctx())  # three lots into a one-lot tier
    assert "sleeve_cap" in got["sl"].reasons


def test_the_load_check_accepts_the_sleeve_window():
    """The sleeve's 0.15-0.20 delta window sits under cash_secured_put.delta_min (0.20): each
    window is checked on its own, and the regime load check still passes."""
    delta_min = float(get_config().risk["cash_secured_put"]["delta_min"])
    cfg = get_leveraged_sizing_cfg().sleeve
    assert cfg.delta[0] < delta_min and cfg.delta == (0.15, 0.20) and cfg.dte == (7, 14)
    assert get_regime_cfg().bottoming.signal_delta_max > delta_min
    from src.common.config import LeveragedSleeveCfg

    with pytest.raises(ValueError):
        LeveragedSleeveCfg(delta=(0.2, 0.1))
    with pytest.raises(ValueError):
        LeveragedSleeveCfg(delta=(0.0, 0.2))
    with pytest.raises(ValueError):
        LeveragedSleeveCfg(dte=(14, 7))


# --------------------------------------------------------------------------- #
# sigma-60 drawdown (condition 2)
# --------------------------------------------------------------------------- #


def _bars(closes) -> pd.DataFrame:
    idx = pd.date_range(end=today_et(), periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes}, index=idx)


def test_sigma_drawdown_holds_only_far_enough_below_the_60_session_high():
    rng = np.random.default_rng(1)
    base = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 300)))
    flat = _bars(base)
    ok, why = sigma_drawdown(flat, 1.0)
    assert isinstance(ok, bool) and "sigma" in why
    crash = base.copy()
    crash[-1] = crash[-60:].max() * 0.80  # a 20% drop from the 60-session high
    assert sigma_drawdown(_bars(crash), 1.0)[0] is True
    assert sigma_drawdown(_bars(crash), 10.0)[0] is False
    assert sigma_drawdown(_bars(base[:50]), 1.0)[0] is False  # too little history: fail closed
    assert sigma_drawdown(None, 1.0)[0] is False


def test_the_context_finds_the_below_trend_path_from_bars(db, monkeypatch):
    from src.regime.context import _sleeve_below_trend

    rng = np.random.default_rng(2)
    base = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.01, 300)))
    base[-1] = base[-60:].max() * 0.75
    below = les(trend_up=False)
    c = ctx(signal=below, bottoming=True)
    assert _sleeve_below_trend(c, {"QQQ": _bars(base)}) == ["TQQQ"]
    # without the bottoming signal, or with the switch off, nothing opens
    assert _sleeve_below_trend(ctx(signal=below, bottoming=False), {"QQQ": _bars(base)}) == []
    assert (
        _sleeve_below_trend(ctx(signal=below, on=False, bottoming=True), {"QQQ": _bars(base)}) == []
    )
    # above the 200-day the path is not used at all
    assert _sleeve_below_trend(ctx(bottoming=True), {"QQQ": _bars(base)}) == []
