"""The regime inside the sizer and the Rules Engine (Task 3).

The generator (`screen_csp_candidates`) and the gate (`validate_candidates`) apply the same
pure functions, so they must agree; these tests drive both with a `SizingContext`.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.analytics.shock import measure
from src.common.config import get_config
from src.common.envelope_types import BookLine, EnvelopeRoom, ShockInputs
from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    MarketRegime,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    SizingContext,
    Strategy,
    TechnicalStats,
    TradeCandidate,
    Verdict,
)
from src.common.universe import invalidate_universe_cache
from src.engine.risk_engine import validate_candidates
from src.strategies.cash_secured_put import screen_csp_candidates
from tests.test_engine import _account, _candidate
from tests.test_risk_engine_roll import roll_from

N = MarketRegime.NORMAL
C = MarketRegime.CAUTIOUS
S = MarketRegime.STRESSED
X = MarketRegime.CRISIS

TECH = ["QQQ", "TQQQ", "SOXL", "TSLL", "NVDA", "AMD", "AAPL"]
LEVERAGE = {"TQQQ": 3, "SOXL": 3, "TSLL": 2}
_EXPIRY = date.today() + timedelta(days=21)
# A TQQQ put whose ten lots fit every capital cap at 3x leverage (risk-envelope §3.5, Task 18:
# 10 x $4,000 x 3 = $120k under the 25% large ceiling of $125k), so these tests still see only
# the leveraged ceiling, not the leverage-weighted collateral.
TQQQ_STRIKE = 40.0


def ctx(
    spy: MarketRegime = N,
    qqq: MarketRegime = N,
    *,
    suspended: bool = False,
    opens: dict[str, int] | None = None,
    floors: dict[str, int] | None = None,
    triggers: dict[str, list[str]] | None = None,
) -> SizingContext:
    return SizingContext(
        regimes={"SPY": spy, "QQQ": qqq},
        tech_linked=TECH,
        suspended=suspended,
        leverage=dict(LEVERAGE),
        name_triggers=triggers or {},
        csp_opens_counted=opens or {},
        floor_lots_counted=floors or {},
    )


@pytest.fixture(autouse=True)
def _universe(monkeypatch):
    cfg = get_config()
    names = ["NVDA", "BAC", "WFC", "TQQQ", "AMD", "AAPL"]
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": names,
            "actively_wheeling": names,
            "sectors": {n: "tech" if n in TECH else "financials" for n in names},
            "leveraged_etfs": ["TQQQ"],
        },
    )
    invalidate_universe_cache()
    yield
    invalidate_universe_cache()


def set_risk(monkeypatch, **blocks) -> None:
    cfg = get_config()
    risk = dict(cfg.risk)
    risk.update(blocks)
    monkeypatch.setattr(cfg, "risk", risk)


def set_portfolio(monkeypatch, **overrides) -> None:
    cfg = get_config()
    set_risk(monkeypatch, portfolio={**cfg.risk["portfolio"], **overrides})


# --------------------------------------------------------------------------- #
# generator
# --------------------------------------------------------------------------- #


def _account_gen() -> AccountSnapshot:
    # deployable = 400k - max(20% x 400k, 10k) = 320k; max_csp_collateral 320k at 100%
    return AccountSnapshot(
        account="DU1",
        net_liquidation=500_000.0,
        total_cash=400_000.0,
        buying_power=400_000.0,
        maintenance_margin=0.0,
        excess_liquidity=400_000.0,
    )


def _quote(symbol: str, strike: float = 50.0) -> OptionQuote:
    return OptionQuote(
        underlying=symbol,
        right=OptionRight.PUT,
        strike=strike,
        expiry=_EXPIRY,
        bid=1.0,
        ask=1.05,
        delta=-0.25,
        open_interest=500,
        volume=100,
    )


def _screen(symbol: str, *, positions=None, sizing=None, strike: float = 50.0):
    return screen_csp_candidates(
        symbol,
        [_quote(symbol, strike)],
        _account_gen(),
        IVStats(symbol=symbol, iv_rank=50.0, current_iv=35.0, hv_30=20.0),
        TechnicalStats(symbol=symbol, price=60.0),
        FundamentalStats(symbol=symbol, quality_flag=True),
        positions=positions,
        sizing=sizing,
    )


def _book(collateral: float, underlying: str = "BOOK") -> list[PositionSnapshot]:
    """One short-put position holding *collateral* dollars of CSP collateral."""
    return [
        PositionSnapshot(
            symbol=f"{underlying} 261120P",
            sec_type="OPT",
            position=-10.0,
            avg_cost=1.0,
            right=OptionRight.PUT,
            strike=collateral / 1000.0,
            expiry=date.today() + timedelta(days=30),
            underlying=underlying,
        )
    ]


def test_generator_without_sizing_is_unchanged():
    screen = _screen("NVDA")
    assert [c.contracts for c in screen.passed] == [10]
    assert screen.passed[0].sizing is None


def test_generator_trims_to_the_per_trade_cap_and_records_the_note():
    # NVDA is tech-linked and not a leveraged ETF; QQQ stressed -> floor(10 x 0.3) = 3
    screen = _screen("NVDA", sizing=ctx(N, S))
    assert len(screen.passed) == 1
    c = screen.passed[0]
    assert c.contracts == 3
    assert c.collateral == 3 * 50.0 * 100
    note = c.sizing
    assert note is not None
    assert note.pre_regime_contracts == 10
    assert note.regime == S and note.regime_index == "QQQ"
    assert note.per_trade_cap == 3
    assert note.ceiling_kind == "regime_ceiling"
    assert note.floor_lot is False


def test_generator_trims_a_leveraged_etf_in_a_normal_regime(monkeypatch):
    set_risk(monkeypatch, leveraged_sizing={"csp_mode": "normal"})  # decision 32 (Task 8)
    screen = _screen("TQQQ", sizing=ctx(N, N), strike=TQQQ_STRIKE)
    c = screen.passed[0]
    assert c.contracts == 6  # calm 3x: floor(10 x 0.6)
    assert c.sizing is not None
    assert c.sizing.pre_regime_contracts == 10
    assert c.sizing.leverage == 3 and c.sizing.leverage_tier == "calm"
    assert c.sizing.ceiling_kind == "leveraged_ceiling"


def test_a_stressed_leveraged_etf_is_trimmed_harder(monkeypatch):
    set_risk(monkeypatch, leveraged_sizing={"csp_mode": "normal"})  # decision 32 (Task 8)
    screen = _screen(
        "TQQQ", sizing=ctx(N, N, triggers={"TQQQ": ["recent_loss_exit"]}), strike=TQQQ_STRIKE
    )
    c = screen.passed[0]
    assert c.contracts == 3 and c.sizing is not None and c.sizing.leverage_tier == "stressed"


def test_generator_says_regime_budget_when_only_the_scaled_cap_binds():
    # 310k of CSP collateral already held: 2 more $5k lots fit the unscaled 320k budget, none fit
    # the stressed 40% budget. The stressed floor (1 lot) is already used today.
    screen = _screen("BAC", positions=_book(310_000), sizing=ctx(S, S, floors={"SPY": 1}))
    assert screen.passed == []
    (cand, reasons), *_ = screen.rejected
    assert "regime_budget" in reasons
    assert "no_headroom" not in reasons and "insufficient_cash" not in reasons
    assert cand.sizing is not None and cand.sizing.regime == S


def test_generator_still_says_no_headroom_when_the_unscaled_cap_binds_too():
    screen = _screen("BAC", positions=_book(319_000), sizing=ctx(S, S, floors={"SPY": 1}))
    (_, reasons), *_ = screen.rejected
    assert "no_headroom" in reasons and "regime_budget" not in reasons


def test_generator_sizes_a_floor_lot_when_the_floor_is_open():
    screen = _screen("BAC", positions=_book(310_000), sizing=ctx(S, S))
    assert screen.rejected == []
    c = screen.passed[0]
    # sized min(unscaled fit = 2, per-trade cap = 3) with the unscaled caps
    assert c.contracts == 2
    assert c.sizing is not None and c.sizing.floor_lot is True


def test_generator_rejects_with_regime_ceiling_when_the_ceiling_is_zero(monkeypatch):
    set_risk(monkeypatch, regime={"csp": {"per_trade_fraction": {"crisis": 0.0}}})
    screen = _screen("BAC", sizing=ctx(X, X))
    assert screen.passed == []
    (_, reasons), *_ = screen.rejected
    assert "regime_ceiling" in reasons


def test_suspended_context_applies_no_regime_limit_but_keeps_the_leveraged_ceiling(
    monkeypatch,
):
    set_risk(monkeypatch, leveraged_sizing={"csp_mode": "normal"})  # decision 32 (Task 8)
    assert _screen("NVDA", sizing=ctx(S, S, suspended=True)).passed[0].contracts == 10
    assert (
        _screen("TQQQ", sizing=ctx(S, S, suspended=True), strike=TQQQ_STRIKE).passed[0].contracts
        == 6
    )


# --------------------------------------------------------------------------- #
# gate
# --------------------------------------------------------------------------- #


def _csp(cid: str, underlying: str, *, contracts: int = 1, collateral: float = 5_000.0, **kw):
    return _candidate(
        candidate_id=cid,
        underlying=underlying,
        contracts=contracts,
        collateral=collateral,
        **kw,
    )


def _gate(cands, *, sizing, positions=None, **kw):
    acct = _account(net_liq=500_000.0, cash=400_000.0)
    verdicts = validate_candidates(cands, acct, positions or [], sizing=sizing, **kw)
    return {v.candidate_id: v for v in verdicts}


def test_gate_rejects_over_the_per_trade_cap_with_regime_ceiling():
    out = _gate([_csp("a", "BAC", contracts=5, collateral=25_000.0)], sizing=ctx(S, S))
    assert out["a"].verdict == Verdict.REJECT
    assert out["a"].reasons == ["regime_ceiling"]


def test_gate_names_the_leveraged_ceiling():
    out = _gate([_csp("a", "TQQQ", contracts=8, collateral=40_000.0)], sizing=ctx(N, N))
    assert out["a"].reasons == ["leveraged_ceiling"]


def test_gate_says_regime_budget_when_unscaled_caps_would_pass():
    out = _gate(
        [_csp("a", "BAC")],
        sizing=ctx(S, S, floors={"SPY": 1}),  # the stressed floor is already used
        positions=_book(310_000),
    )
    assert out["a"].verdict == Verdict.REJECT
    assert out["a"].reasons == ["regime_budget"]


def test_gate_scales_the_ticker_risk_cap_by_the_names_regime():
    # 1 lot, $40k collateral, 100% IV, 20 DTE = ~9.4k risk units: under the unscaled 25k cap and
    # over the crisis 10% cap (2.5k).
    cand = _csp("a", "BAC", collateral=40_000.0, current_iv=100.0)
    out = _gate([cand], sizing=ctx(X, X, floors={"SPY": 1}))
    # the regime, not the book, said no: one distinct reason, not concentration_limit
    assert out["a"].reasons == ["regime_budget"]
    normal = _gate([cand], sizing=ctx(N, N))
    assert normal["a"].verdict == Verdict.PASS


def test_gate_enforces_the_daily_csp_limit_across_the_batch():
    cands = [_csp(f"c{i}", u) for i, u in enumerate(["NVDA", "AMD", "AAPL"])]
    out = _gate(cands, sizing=ctx(N, S, opens={"QQQ": 2}))  # stressed limit is 3; two already open
    assert out["c0"].verdict == Verdict.PASS
    assert out["c1"].reasons == ["regime_daily_limit"]
    assert out["c2"].reasons == ["regime_daily_limit"]


def test_daily_limit_is_per_governing_index():
    cands = [_csp("bac", "BAC"), _csp("nvda", "NVDA")]
    out = _gate(cands, sizing=ctx(N, S, opens={"QQQ": 3, "SPY": 9}))
    assert out["bac"].verdict == Verdict.PASS  # SPY is normal: no daily limit
    assert out["nvda"].reasons == ["regime_daily_limit"]  # QQQ stressed, 3 of 3 used


def test_large_position_threshold_never_moves_with_the_regime():
    # Two other names already hold more than the standard ticker collateral cap (so both
    # large-position slots are taken); a third large lot needs a slot in every regime.
    big = _book(60_000, "BIGA") + _book(60_000, "BIGB")
    cand = _csp("a", "BAC", collateral=60_000.0)
    reasons = {}
    for label, c in (("normal", ctx(N, N)), ("crisis", ctx(X, X))):
        reasons[label] = _gate([cand], sizing=c, positions=big)["a"].reasons
    assert "large_position_slot_full" in reasons["normal"]
    assert "large_position_slot_full" in reasons["crisis"]


def test_covered_calls_are_never_regime_limited():
    cc = _candidate(
        candidate_id="cc",
        strategy=Strategy.COVERED_CALL,
        right=OptionRight.CALL,
        underlying="BAC",
        contracts=10,
        collateral=50_000.0,
        delta=0.25,
    )
    out = _gate([cc], sizing=ctx(X, X, opens={"SPY": 9}))
    regime_codes = {"regime_budget", "regime_ceiling", "leveraged_ceiling", "regime_daily_limit"}
    assert not (set(out["cc"].reasons) & regime_codes)


def test_rolls_are_never_regime_limited():
    origin = roll_from().model_copy(update={"contracts": 10})
    roll = _candidate(
        candidate_id="roll", strategy=Strategy.ROLL, underlying="MARA", dte=10, contracts=10
    ).model_copy(update={"roll_from": origin, "roc_pct": 0.0, "annualized_yield_pct": 0.0})
    out = _gate([roll], sizing=ctx(X, X, opens={"SPY": 9, "QQQ": 9}))
    assert out["roll"].verdict == Verdict.PASS, out["roll"].reasons


def test_suspended_context_applies_no_gate_limit_except_the_leveraged_ceiling():
    c = ctx(S, S, suspended=True, opens={"SPY": 9})
    out = _gate(
        [
            _csp("a", "BAC", contracts=5, collateral=25_000.0),
            _csp("t", "TQQQ", contracts=8, collateral=40_000.0),
        ],
        sizing=c,
    )
    assert out["a"].verdict == Verdict.PASS
    assert out["t"].reasons == ["leveraged_ceiling"]


def test_a_gate_call_without_sizing_is_the_old_gate():
    out = validate_candidates(
        [_csp("a", "BAC", contracts=5, collateral=25_000.0)],
        _account(net_liq=500_000.0, cash=400_000.0),
        [],
    )
    assert out[0].verdict == Verdict.PASS


# --------------------------------------------------------------------------- #
# the guaranteed floor (spec decision 31)
# --------------------------------------------------------------------------- #


def test_floor_lets_lots_through_a_full_book_in_crisis(monkeypatch):
    """Review Focus 8: a book at 101% of deployable must not turn a non-normal regime into a
    complete stop. The operator's CSP allocation cap sits above 100%, so the unscaled budget
    still has room; the crisis-scaled one (10%) does not."""
    set_portfolio(monkeypatch, max_csp_allocation_pct_of_deployable=130.0)
    book = _book(323_200)  # 101% of the 320k deployable
    a, b = _csp("a", "BAC"), _csp("b", "WFC")
    out = _gate([a, b], sizing=ctx(X, X), positions=book)
    assert out["a"].verdict == Verdict.PASS
    assert a.contracts == 1 and a.sizing is not None and a.sizing.floor_lot is True
    assert out["b"].verdict == Verdict.REJECT
    assert "regime_budget" in out["b"].reasons
    assert b.sizing is None or b.sizing.floor_lot is False
    # the same book with no regime sizing accepts both (it is the regime that shrinks it)
    plain = _gate([_csp("a2", "BAC"), _csp("b2", "WFC")], sizing=ctx(N, N), positions=book)
    assert plain["a2"].verdict == Verdict.PASS and plain["b2"].verdict == Verdict.PASS


def test_floor_is_limited_to_floor_new_per_day(monkeypatch):
    set_portfolio(monkeypatch, max_csp_allocation_pct_of_deployable=130.0)
    cands = [_csp(f"c{i}", u) for i, u in enumerate(["BAC", "WFC", "NVDA"])]
    # cautious: floor 2 per index per day, daily limit 6. BAC and WFC are SPY-bucket, NVDA QQQ.
    out = _gate(cands, sizing=ctx(C, C), positions=_book(323_200))
    assert out["c0"].verdict == Verdict.PASS and out["c1"].verdict == Verdict.PASS
    # NVDA is a different governing index: it has its own floor of 2
    assert out["c2"].verdict == Verdict.PASS
    more = [_csp(f"d{i}", u) for i, u in enumerate(["BAC", "WFC", "AMD", "AAPL"])]
    out2 = _gate(more, sizing=ctx(C, C), positions=_book(323_200))
    # BAC, WFC use SPY's two lots; AMD, AAPL use QQQ's two
    assert all(out2[k].verdict == Verdict.PASS for k in ("d0", "d1", "d2", "d3"))
    third_spy = [_csp(f"e{i}", u) for i, u in enumerate(["BAC", "WFC", "TQQQ"])]
    out3 = _gate(third_spy, sizing=ctx(C, C, floors={"SPY": 1}), positions=_book(323_200))
    assert out3["e0"].verdict == Verdict.PASS  # SPY's second floor lot
    assert out3["e1"].reasons == ["regime_budget"]  # the floor (2 per index) is used up


def test_floor_never_exceeds_the_unscaled_caps():
    # at the default 100% allocation the 323k book already exceeds the 320k unscaled budget:
    # the floor must not let a lot through that the unscaled gate would refuse
    out = _gate([_csp("a", "BAC")], sizing=ctx(X, X), positions=_book(323_200))
    assert out["a"].verdict == Verdict.REJECT
    assert "csp_allocation_limit" in out["a"].reasons
    assert "regime_budget" not in out["a"].reasons


def test_floor_counts_against_the_daily_limit(monkeypatch):
    set_portfolio(monkeypatch, max_csp_allocation_pct_of_deployable=130.0)
    # stressed: daily limit 3, floor 1. Three already opened today: the floor does not apply.
    out = _gate([_csp("a", "BAC")], sizing=ctx(S, S, opens={"SPY": 3}), positions=_book(323_200))
    assert out["a"].verdict == Verdict.REJECT
    assert "regime_daily_limit" in out["a"].reasons


def test_floor_is_per_governing_index(monkeypatch):
    set_portfolio(monkeypatch, max_csp_allocation_pct_of_deployable=130.0)
    # a QQQ-bucket floor lot was already sent: it does not use SPY's
    cands = [_csp("nvda", "NVDA"), _csp("bac", "BAC")]
    out = _gate(cands, sizing=ctx(S, S, floors={"QQQ": 1}), positions=_book(323_200))
    assert out["nvda"].reasons == ["regime_budget"]
    assert out["bac"].verdict == Verdict.PASS
    assert cands[1].sizing is not None and cands[1].sizing.floor_lot is True


# --------------------------------------------------------------------------- #
# callers, labels, card
# --------------------------------------------------------------------------- #


def test_every_production_caller_passes_sizing():
    """Review Focus 1: a caller that forgets ``sizing=`` silently drops every regime limit."""
    root = Path(__file__).resolve().parents[1] / "src"
    # The covered-call screens join the CSP ones: the breakout rule rides the same context.
    # `scan_symbol` (R10) is the only caller of the screens, and its own ``sizing`` parameter
    # defaults to None: a second caller that forgot the keyword would drop every regime limit and
    # the breakout rule from CSP and covered-call generation with nothing failing (the send-time
    # gate would still apply them, so the cards would just be wrong).
    watched = {
        "validate_candidates",
        "screen_csp_candidates",
        "screen_csp",
        "screen_cc_candidates",
        "screen_cc",
        "scan_symbol",
    }
    offenders: list[str] = []
    seen = 0
    seen_names: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name not in watched:
                continue
            seen += 1
            seen_names.add(name)
            if "sizing" not in {k.arg for k in node.keywords}:
                offenders.append(f"{path.relative_to(root.parent)}:{node.lineno} {name}(...)")
    assert seen >= 7, "the AST walk found too few call sites; the test lost its target"
    assert watched <= seen_names, f"watched names with no call site: {watched - seen_names}"
    assert not offenders, f"callers without sizing=: {offenders}"


def test_new_reason_codes_have_labels_in_both_tables():
    from src.api.routers.options import _REASON_LABELS
    from src.notify.formatters import _REJECT_REASON_LABELS

    for code in ("regime_budget", "regime_ceiling", "leveraged_ceiling", "regime_daily_limit"):
        assert code in _REJECT_REASON_LABELS and code in _REASON_LABELS
        assert _REJECT_REASON_LABELS[code] == _REASON_LABELS[code]
    assert _REJECT_REASON_LABELS["regime_budget"] == "the market regime has shrunk the CSP budget"
    assert _REJECT_REASON_LABELS["leveraged_ceiling"] == "over the size limit for a leveraged ETF"


def _card_text(cand: TradeCandidate) -> str:
    from src.notify.formatters import format_candidate

    return format_candidate(cand, None).replace("\\", "")


def test_the_card_says_why_the_size_was_cut(monkeypatch):
    set_risk(monkeypatch, leveraged_sizing={"csp_mode": "normal"})  # decision 32 (Task 8)
    leveraged = _screen("TQQQ", sizing=ctx(N, N), strike=TQQQ_STRIKE).passed[0]
    assert "Size 6 of 10 (leveraged ETF, 3×, calm)" in _card_text(leveraged)

    stressed_lev = _screen(
        "TQQQ", sizing=ctx(N, N, triggers={"TQQQ": ["recent_loss_exit"]}), strike=TQQQ_STRIKE
    ).passed[0]
    assert "Size 3 of 10 (leveraged ETF, 3×, stressed" in _card_text(stressed_lev)

    regime_trim = _screen("NVDA", sizing=ctx(N, S)).passed[0]
    assert "Size 3 of 10 (QQQ stressed)" in _card_text(regime_trim)

    floor = _screen("BAC", positions=_book(310_000), sizing=ctx(S, S)).passed[0]
    assert "today's guaranteed lot" in _card_text(floor)

    untouched = _screen("NVDA", sizing=ctx(N, N)).passed[0]
    assert "Size " not in _card_text(untouched)
    plain = _screen("NVDA").passed[0]
    assert "Size " not in _card_text(plain)


# --------------------------------------------------------------------------- #
# risk-envelope Task 18: no reason erased (P4); U_ew replaces the nominal gross check
# --------------------------------------------------------------------------- #

ENV_NAMES = ("BAC", "WFC", "NVDA", "AMD", "AAPL", "TQQQ", "QQQ", "HOOD", "BOOK")


def _env_inputs(*lines: BookLine, nlv: float = 500_000.0) -> ShockInputs:
    names = set(ENV_NAMES) | {ln.symbol for ln in lines}
    return ShockInputs(
        lines=tuple(lines),
        betas={s: 1.0 for s in names},
        betas_smh={s: 1.0 for s in names},
        leverage={"TQQQ": 3},
        governing={"TQQQ": "QQQ"},
        tech_linked=frozenset(),
        semis=frozenset(),
        nlv=nlv,
    )


def _stock(symbol: str, value: float) -> BookLine:
    return BookLine(symbol=symbol, kind="stock", qty=value / 100.0, spot=100.0)


def _room(
    inputs: ShockInputs,
    *,
    s10_limit: float = 99.0,
    uew_limit: float = 9.0,
    enforce: str = "on",
) -> EnvelopeRoom:
    res = measure(inputs)
    return EnvelopeRoom(
        s10_gross=res.s10,
        s10_limit=s10_limit,
        uew=res.uew,
        uew_limit=uew_limit,
        t20_gross=res.t20,
        t20_limit=None,
        enforce=enforce,
        measured=res.measured,
    )


def _env_csp(cid: str, underlying: str, **kw) -> TradeCandidate:
    """A one-lot CSP (strike 150: $15k of U_ew) carrying the IV and spot the envelope reads."""
    return _csp(cid, underlying, **kw).model_copy(
        update={"quote_iv": 0.30, "underlying_price": 160.0}
    )


def _over_uew(**room_kw) -> tuple[EnvelopeRoom, ShockInputs]:
    """A book at U_ew 1.40 (the HOOD day) against a 1.36 limit: any new put breaches it."""
    inputs = _env_inputs(_stock("HOOD", 700_000.0))
    return _room(inputs, uew_limit=1.36, **room_kw), inputs


def test_a_floor_lot_cannot_clear_the_gross_budget():
    """C1, the HOOD case: the regime is stressed, the unscaled caps pass, U_ew is over its limit.
    The guaranteed floor used to clear the reasons; now gross_budget stays beside it."""
    used = _gate(
        [_env_csp("a", "BAC")],
        sizing=ctx(S, S, floors={"SPY": 1}),
        positions=_book(310_000),
        envelope=_over_uew(),
    )
    assert used["a"].verdict == Verdict.REJECT
    assert used["a"].reasons == ["regime_budget", "gross_budget"]

    cand = _env_csp("b", "BAC")
    open_floor = _gate([cand], sizing=ctx(S, S), positions=_book(310_000), envelope=_over_uew())
    assert open_floor["b"].verdict == Verdict.REJECT
    assert open_floor["b"].reasons == ["gross_budget"]  # the floor cleared regime_budget only
    assert cand.sizing is None or cand.sizing.floor_lot is False  # no floor lot was taken


def test_combined_name_cap_survives_the_regime_rewrite(monkeypatch):
    """C1: combined_name_cap was replaced by regime_budget and then cleared by a floor lot."""
    import src.engine.risk_engine as risk_engine
    from src.common.books import ValueExposure

    monkeypatch.setattr(
        risk_engine,
        "value_exposure",
        lambda: ValueExposure(active=True, readable=True, by_name={"BAC": 80_000.0}),
    )
    # With an IV the unscaled caps pass (risk units, not the raw-collateral fallback), so the
    # regime rewrites the scaled-budget refusal to regime_budget and the open floor clears it.
    cand = _csp("a", "BAC", current_iv=30.0)
    out = _gate([cand], sizing=ctx(S, S), positions=_book(310_000))
    assert out["a"].verdict == Verdict.REJECT
    assert out["a"].reasons == ["combined_name_cap"]


def test_gross_budget_runs_without_the_value_book(monkeypatch):
    import src.engine.risk_engine as risk_engine
    from src.common.books import ValueExposure

    monkeypatch.setattr(
        risk_engine, "value_exposure", lambda: ValueExposure(active=False, readable=True)
    )
    out = _gate([_env_csp("a", "BAC")], sizing=ctx(N, N), envelope=_over_uew())
    assert out["a"].reasons == ["gross_budget"]
    # the same put on a book under its U_ew limit passes
    calm = _env_inputs(_stock("HOOD", 100_000.0))
    ok = _gate([_env_csp("b", "BAC")], sizing=ctx(N, N), envelope=(_room(calm), calm))
    assert ok["b"].verdict == Verdict.PASS


def test_gross_budget_counts_leveraged_at_leverage():
    """A 3x ETF's put counts at three times its strike in U_ew: a lot that would fit at 1x is
    refused. (No sizing context: the leveraged-sleeve ceiling is not what is under test.)"""
    inputs = _env_inputs(_stock("BOOK", 500_000.0))  # U_ew 1.00
    room = _room(inputs, uew_limit=1.05)  # room for $25k: 1x $15k fits, 3x $45k does not
    one_x = _gate([_env_csp("n", "NVDA")], sizing=None, envelope=(room, inputs))
    three_x = _gate([_env_csp("t", "TQQQ")], sizing=None, envelope=(room, inputs))
    assert one_x["n"].verdict == Verdict.PASS
    assert three_x["t"].reasons == ["gross_budget"]


def test_an_accepted_lot_joins_the_book_for_the_next_candidate():
    inputs = _env_inputs(_stock("BOOK", 500_000.0))
    room = _room(inputs, uew_limit=1.05)  # room for one $15k lot, not two
    out = _gate(
        [_env_csp("a", "BAC"), _env_csp("b", "WFC")], sizing=ctx(N, N), envelope=(room, inputs)
    )
    assert out["a"].verdict == Verdict.PASS
    assert out["b"].reasons == ["gross_budget"]


def test_no_envelope_while_enforce_is_on_fails_closed(monkeypatch):
    import src.storage.envelope_switches as switches

    monkeypatch.setattr(switches, "enforce_mode", lambda: "on")
    out = _gate([_env_csp("a", "BAC")], sizing=ctx(N, N))
    assert out["a"].reasons == ["envelope_unmeasured"]
    monkeypatch.setattr(switches, "enforce_mode", lambda: "record")
    assert _gate([_env_csp("b", "BAC")], sizing=ctx(N, N))["b"].verdict == Verdict.PASS


def test_an_unmeasured_candidate_line_is_refused():
    inputs = _env_inputs(_stock("BOOK", 100_000.0))
    no_iv = _csp("a", "BAC").model_copy(update={"underlying_price": 160.0})  # no quote_iv
    out = _gate([no_iv], sizing=ctx(N, N), envelope=(_room(inputs), inputs))
    assert out["a"].reasons == ["envelope_unmeasured"]


def test_the_wheel_no_longer_reads_max_gross_notional_pct(monkeypatch):
    import src.engine.risk_engine as risk_engine
    from src.common.books import ValueExposure

    set_portfolio(monkeypatch, max_gross_notional_pct=1.0)  # would refuse anything
    monkeypatch.setattr(
        risk_engine,
        "value_exposure",
        lambda: ValueExposure(active=True, readable=True, by_name={"XYZ": 400_000.0}),
    )
    out = _gate([_csp("a", "BAC")], sizing=ctx(N, N))
    assert out["a"].verdict == Verdict.PASS
    root = Path(__file__).resolve().parents[1] / "src"
    for rel in ("engine/risk_engine.py", "strategies/cash_secured_put.py", "engine/capital.py"):
        assert "max_gross_notional_pct" not in (root / rel).read_text(encoding="utf-8"), rel
        assert "gross_notional_cap" not in (root / rel).read_text(encoding="utf-8"), rel


def test_the_value_book_still_reads_it():
    """Ruling Q3 / C2: max_gross_notional_pct stays the value book's fundable gate."""
    from src.value.risk import FUNDABLE, BuyContext, validate

    cfg = get_config()
    ctx_ = BuyContext(
        symbol="KO",
        list_name="core",
        shares=100,
        price=60.0,
        verdict="READY",
        mos=0.4,
        required_mos_pct=20.0,
        mos_review=False,
        health="pass",
        data_quality="pass",
        timing="pass",
        earnings_in_window=False,
        net_liq=100_000.0,
        ceiling=50_000.0,
        book_cost=0.0,
        list_cost=0.0,
        name_cost=0.0,
        holds_name=False,
        positions_open=0,
        wheel_name_exposure=0.0,
        gross_used=99_000.0,
        adv_dollar_20=10_000_000.0,
    )
    reasons = validate(
        ctx_, cfg.value.book, max_gross_notional_pct=100.0, max_combined_name_pct=15.0
    )
    assert "gross_notional_cap" in reasons
    roomy = validate(
        replace(ctx_, gross_used=0.0),
        cfg.value.book,
        max_gross_notional_pct=100.0,
        max_combined_name_pct=15.0,
    )
    assert "gross_notional_cap" not in roomy
    assert FUNDABLE == frozenset({"gross_notional_cap"})
    root = Path(__file__).resolve().parents[1]
    assert "max_gross_notional_pct" in (root / "src/value/live.py").read_text(encoding="utf-8")
    assert "max_gross_notional_pct" in (root / "config/examples/risk_limits.yaml").read_text(
        encoding="utf-8"
    )


def test_record_mode_records_and_admits(db):
    """Record mode admits; the would-block reasons ride on the verdict and the caller writes them
    (inside its own transaction: the approval poll's gate runs inside its write session)."""
    from src.regime.actions import record_envelope_verdicts
    from src.storage.db import session_scope
    from src.storage.models import SizingActionRow

    room, inputs = _over_uew(enforce="record")
    cand = _env_csp("a", "BAC")
    out = _gate([cand], sizing=ctx(N, N), envelope=(room, inputs))
    assert out["a"].verdict == Verdict.PASS
    assert out["a"].envelope_would == ["gross_budget"]
    with session_scope() as s:
        assert s.query(SizingActionRow).count() == 0  # the gate itself writes nothing
    assert record_envelope_verdicts([cand], list(out.values()), where="scan") == 1
    with session_scope() as s:
        rows = s.query(SizingActionRow).filter_by(kind="envelope_record").all()
        assert [(r.record_key, r.deterministic_contracts, r.sent_contracts) for r in rows] == [
            ("a:scan", 1, 0)
        ]
        assert "gross_budget" in rows[0].reason
    off = _gate([_env_csp("b", "BAC")], sizing=ctx(N, N), envelope=_over_uew(enforce="off"))
    assert off["b"].verdict == Verdict.PASS and off["b"].envelope_would == []
    with session_scope() as s:
        assert s.query(SizingActionRow).filter_by(kind="envelope_record").count() == 1


def test_the_gate_grants_the_index_lot_as_the_sizer_does(monkeypatch):
    """Task 21: with both large slots taken, one QQQ lot at 11% of net liq passes the gate (the
    index class), and the same lot on SMH (not in the class) needs a slot."""
    set_portfolio(
        monkeypatch,
        broad_index_etfs=["QQQ"],
        broad_index_etf_collateral_pct=15.0,
        max_large_positions=2,
    )
    big = _book(60_000, "BIGA") + _book(60_000, "BIGB")
    qqq = _csp("q", "QQQ", collateral=55_000.0, current_iv=20.0)
    smh = _csp("s", "SMH", collateral=55_000.0, current_iv=20.0)
    out = _gate([qqq, smh], sizing=ctx(N, N), positions=big)
    assert out["q"].verdict == Verdict.PASS, out["q"].reasons
    assert "large_position_slot_full" in out["s"].reasons
