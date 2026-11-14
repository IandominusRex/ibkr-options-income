"""The shock budget S10_gross <= L(t) at the generator, the gate and send time (risk-envelope
Task 19; spec §3.4.1, rulings E4, H1, H7, P1, P3, Q4).

The generator (`screen_csp_candidates`), the Rules Engine (`validate_candidates`) and the executor
(`execute_candidate`) apply the same `envelope.admits` / `max_contracts_under`, so they must agree.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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
    OrderState,
    SizingContext,
    Strategy,
    TechnicalStats,
    TradeCandidate,
    Verdict,
)
from src.common.universe import invalidate_universe_cache
from src.engine.envelope import admits, candidate_line, max_contracts_under
from src.engine.risk_engine import validate_candidates
from src.strategies.cash_secured_put import screen_csp_candidates
from tests.test_engine import _account, _candidate
from tests.test_risk_engine_roll import roll_from

N = MarketRegime.NORMAL
NAMES = ["BAC", "WFC", "NVDA", "AMD"]
NLV = 500_000.0
_EXPIRY = date.today() + timedelta(days=21)


@pytest.fixture(autouse=True)
def _universe(monkeypatch):
    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": NAMES,
            "actively_wheeling": NAMES,
            "sectors": {n: "financials" for n in NAMES},
            "leveraged_etfs": [],
        },
    )
    invalidate_universe_cache()
    yield
    invalidate_universe_cache()


def ctx() -> SizingContext:
    return SizingContext(regimes={"SPY": N, "QQQ": N}, tech_linked=["NVDA", "AMD"])


def inputs(*lines: BookLine) -> ShockInputs:
    names = set(NAMES) | {"BOOK"} | {ln.symbol for ln in lines}
    return ShockInputs(
        lines=tuple(lines),
        betas={s: 1.0 for s in names},
        betas_smh={s: 1.0 for s in names},
        leverage={},
        governing={},
        tech_linked=frozenset(),
        semis=frozenset(),
        nlv=NLV,
    )


def stock(value: float, symbol: str = "BOOK") -> BookLine:
    return BookLine(symbol=symbol, kind="stock", qty=value / 100.0, spot=100.0)


def room(
    inp: ShockInputs,
    *,
    s10_limit: float = 99.0,
    uew_limit: float = 9.0,
    enforce: str = "on",
    measured: bool = True,
) -> EnvelopeRoom:
    res = measure(inp)
    return EnvelopeRoom(
        s10_gross=res.s10,
        s10_limit=s10_limit,
        uew=res.uew,
        uew_limit=uew_limit,
        t20_gross=res.t20,
        t20_limit=None,
        enforce=enforce,
        measured=measured and res.measured,
        reasons_if_unmeasured=() if measured else ("unmeasured:XYZ",),
    )


def account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=NLV,
        total_cash=400_000.0,
        buying_power=400_000.0,
        maintenance_margin=0.0,
        excess_liquidity=400_000.0,
    )


def quote(symbol: str = "BAC", strike: float = 50.0, iv: float | None = 0.35) -> OptionQuote:
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
        iv=iv,
        underlying_price=60.0,
    )


def screen(symbol: str = "BAC", *, envelope=None, iv: float | None = 0.35):
    return screen_csp_candidates(
        symbol,
        [quote(symbol, iv=iv)],
        account(),
        IVStats(symbol=symbol, iv_rank=50.0, current_iv=35.0, hv_30=20.0),
        TechnicalStats(symbol=symbol, price=60.0),
        FundamentalStats(symbol=symbol, quality_flag=True),
        positions=[],
        sizing=ctx(),
        envelope=envelope,
    )


def gate(cands: list[TradeCandidate], envelope, **kw):
    acct = _account(net_liq=NLV, cash=400_000.0)
    out = validate_candidates(cands, acct, [], sizing=kw.pop("sizing", ctx()), envelope=envelope)
    return {v.candidate_id: v for v in out}


def one_lot_s10(inp: ShockInputs) -> float:
    """S10 points one BAC 50P (21 DTE, 35% IV, spot 60) adds to *inp*."""
    unscreened = screen()  # the shape the generator builds, sized without an envelope
    line = replace(candidate_line(unscreened.passed[0]), qty=1.0)
    return measure(replace(inp, lines=inp.lines + (line,))).s10 - measure(inp).s10


# --------------------------------------------------------------------------- #
# the generator (P3)
# --------------------------------------------------------------------------- #


def test_generator_trims_to_the_room():
    base = inputs(stock(200_000.0))
    one = one_lot_s10(base)
    assert one > 0
    r = room(base, s10_limit=measure(base).s10 + 2.5 * one)
    plain = screen().passed[0]
    assert plain.contracts == 10  # capital alone allows the hard max
    trimmed = screen(envelope=(r, base)).passed[0]
    assert trimmed.contracts == 2
    assert trimmed.collateral == 2 * 50.0 * 100
    assert trimmed.sizing is not None
    assert trimmed.sizing.envelope_from == 10
    assert trimmed.sizing.envelope_binding == "shock_budget"


def test_generator_and_gate_agree():
    base = inputs(stock(200_000.0))
    one = one_lot_s10(base)
    before = measure(base).s10
    for k in (0.5, 1.5, 3.2, 7.9, 40.0):
        env = (room(base, s10_limit=before + k * one), base)
        result = screen(envelope=env)
        if result.passed:
            cand = result.passed[0]
            assert gate([cand], env)[cand.candidate_id].verdict == Verdict.PASS, k
            bigger = cand.model_copy(update={"contracts": cand.contracts + 1})
            if cand.contracts < 10:
                assert "shock_budget" in gate([bigger], env)[cand.candidate_id].reasons, k
        else:
            (cand, reasons), *_ = result.rejected
            assert "shock_budget" in reasons, k
            assert gate([cand], env)[cand.candidate_id].reasons == ["shock_budget"], k


def test_generator_zero_lots_is_rejected_with_the_binding_reason():
    base = inputs(stock(200_000.0))
    env = (room(base, s10_limit=measure(base).s10 + 0.5 * one_lot_s10(base)), base)
    result = screen(envelope=env)
    assert result.passed == []
    (_, reasons), *_ = result.rejected
    assert "shock_budget" in reasons


def test_generator_record_mode_keeps_the_size_and_records(db):
    from src.storage.db import session_scope
    from src.storage.models import SizingActionRow

    base = inputs(stock(200_000.0))
    env = (
        room(base, s10_limit=measure(base).s10 + 2.5 * one_lot_s10(base), enforce="record"),
        base,
    )
    cand = screen(envelope=env).passed[0]
    assert cand.contracts == 10
    assert cand.sizing is not None and cand.sizing.envelope_binding is None
    with session_scope() as s:
        rows = s.query(SizingActionRow).filter_by(kind="envelope_record").all()
        assert [(r.deterministic_contracts, r.sent_contracts) for r in rows] == [(10, 2)]
        assert rows[0].record_key.endswith(":generator")


# --------------------------------------------------------------------------- #
# the gate
# --------------------------------------------------------------------------- #


def _csp(cid: str, underlying: str = "BAC", contracts: int = 1) -> TradeCandidate:
    return _candidate(
        candidate_id=cid, underlying=underlying, contracts=contracts, collateral=5_000.0
    ).model_copy(update={"quote_iv": 0.30, "underlying_price": 160.0})


def test_gate_rejects_above_l_of_t():
    base = inputs(stock(200_000.0))
    before = measure(base).s10
    one = admits_increment(base, _csp("x"))
    env = (room(base, s10_limit=before + 1.5 * one), base)
    assert gate([_csp("a", contracts=1)], env)["a"].verdict == Verdict.PASS
    assert gate([_csp("b", contracts=2)], env)["b"].reasons == ["shock_budget"]


def admits_increment(base: ShockInputs, cand: TradeCandidate) -> float:
    return (
        measure(replace(base, lines=base.lines + (candidate_line(cand),))).s10 - measure(base).s10
    )


def test_above_l_of_t_no_risk_adding_open_passes():
    base = inputs(stock(600_000.0))  # S10 12% against a 10% limit: the book is above L(t)
    env = (room(base, s10_limit=10.0), base)
    out = gate([_csp("a"), _csp("b", "WFC")], env)
    assert out["a"].reasons == ["shock_budget"] and out["b"].reasons == ["shock_budget"]
    assert screen(envelope=env).passed == []


def test_covered_calls_and_rolls_are_not_tested():
    base = inputs(stock(600_000.0))
    env = (room(base, s10_limit=10.0, uew_limit=0.5), base)
    cc = _candidate(
        candidate_id="cc",
        strategy=Strategy.COVERED_CALL,
        right=OptionRight.CALL,
        underlying="BAC",
        delta=0.25,
    )
    origin = roll_from().model_copy(update={"contracts": 1})
    roll = _candidate(
        candidate_id="roll", strategy=Strategy.ROLL, underlying="MARA", dte=10
    ).model_copy(update={"roll_from": origin, "roc_pct": 0.0, "annualized_yield_pct": 0.0})
    out = gate([cc, roll], env)
    assert out["cc"].verdict == Verdict.PASS, out["cc"].reasons
    assert out["roll"].verdict == Verdict.PASS, out["roll"].reasons


def test_missing_live_iv_fails_closed(db):
    """Q4: a book option with no live IV makes the room unmeasured; the gate and the generator
    refuse every opening put with envelope_unmeasured while enforce is on."""
    from src.engine.envelope import room as envelope_room
    from src.storage.envelope_switches import set_switch

    set_switch("envelope_enforce", "on", source="cli")
    held = BookLine(
        symbol="AMD", kind="short_put", qty=1.0, spot=150.0, strike=140.0, dte=20, iv=None
    )
    base = inputs(stock(100_000.0), held)
    r = envelope_room(base, today=date.today())
    assert r.enforce == "on" and r.measured is False
    out = gate([_csp("a")], (r, base))
    assert out["a"].reasons == ["envelope_unmeasured"]
    result = screen(envelope=(r, base))
    assert result.passed == []
    (_, reasons), *_ = result.rejected
    assert "envelope_unmeasured" in reasons
    # a candidate quote with no IV is unmeasured too, on a measured book
    clean = inputs(stock(100_000.0))
    no_iv = screen(envelope=(room(clean), clean), iv=None)
    assert no_iv.passed == []


def test_a_long_put_creates_no_room():
    """H1: a long put lowers S10_net, never S10_gross; the gate reads gross."""
    hedge = BookLine(
        symbol="BOOK", kind="long_put", qty=60.0, spot=100.0, strike=98.0, dte=60, iv=0.25
    )
    plain = inputs(stock(600_000.0))
    hedged = inputs(stock(600_000.0), hedge)
    res = measure(hedged)
    assert res.s10_net < res.s10 - 1.0  # the put does protect the book, net
    assert res.s10 == pytest.approx(measure(plain).s10)  # but not gross
    env = (room(hedged, s10_limit=res.s10 + 0.01), hedged)
    assert gate([_csp("a")], env)["a"].reasons == ["shock_budget"]


def test_off_mode_changes_nothing():
    base = inputs(stock(600_000.0))
    env = (room(base, s10_limit=1.0, uew_limit=0.1, enforce="off"), base)
    assert screen(envelope=env).passed[0].contracts == screen().passed[0].contracts
    assert gate([_csp("a")], env)["a"].verdict == Verdict.PASS


def test_admits_reads_the_same_line_the_gate_builds():
    cand = _csp("a", contracts=3)
    line = candidate_line(cand)
    assert (line.kind, line.qty, line.strike, line.iv, line.spot) == (
        "short_put",
        3.0,
        cand.strike,
        0.30,
        160.0,
    )
    base = inputs(stock(100_000.0))
    assert admits(room(base), base, [line]) == []
    n, binding = max_contracts_under(
        room(base, s10_limit=measure(base).s10 + 0.0001), base, replace(line, qty=1.0), 10
    )
    assert (n, binding) == (0, "shock_budget")


# --------------------------------------------------------------------------- #
# send time
# --------------------------------------------------------------------------- #


async def test_send_time_regate_reprices_at_fresh_live_iv(monkeypatch, tmp_path):
    """The card was admitted at its quote's IV; at send time the fresh quote's IV is far higher,
    so the same lot now breaches L(t) and is not placed."""
    from tests.test_execution import _db_setup, _make_mock_bot, _make_mock_ib

    _db_setup(tmp_path, monkeypatch)
    import src.storage.db as dbmod
    from src.execution import executor
    from src.storage.models import OrderRow

    mock_cfg = MagicMock()
    mock_cfg.execution.fill_timeout_minutes = 1
    mock_cfg.is_live = False
    monkeypatch.setattr("src.execution.executor.get_config", lambda: mock_cfg)

    cand = _csp("send-1", contracts=1).model_copy(update={"quote_iv": 0.20, "strike": 150.0})
    base = inputs(stock(200_000.0))
    at_card = admits_increment(base, cand)
    at_send = admits_increment(base, cand.model_copy(update={"quote_iv": 0.80}))
    assert at_send > at_card
    env = (room(base, s10_limit=measure(base).s10 + (at_card + at_send) / 2), base)
    assert gate([cand], env)["send-1"].verdict == Verdict.PASS  # admitted at the card's IV

    fresh = OptionQuote(
        underlying="AAPL",
        right=OptionRight.PUT,
        strike=150.0,
        expiry=cand.expiry,
        bid=3.0,
        ask=3.1,
        delta=-0.25,
        iv=0.80,
        underlying_price=160.0,
    )
    monkeypatch.setattr(executor, "_fetch_quote", AsyncMock(return_value=(fresh, MagicMock())))
    with dbmod.session_scope() as s:
        row = OrderRow(candidate_id="send-1", state=OrderState.SUBMITTED)
        s.add(row)
        s.flush()
        order_id = row.id
    ib = _make_mock_ib(filled=True)
    await executor.execute_candidate(ib, _make_mock_bot(), "1", order_id, cand, envelope=env)
    with dbmod.session_scope() as s:
        row = s.get(OrderRow, order_id)
        assert row.state == OrderState.REJECTED
        assert "S10" in (row.detail or "")
    ib.placeOrder.assert_not_called()


# --------------------------------------------------------------------------- #
# callers
# --------------------------------------------------------------------------- #


def test_every_production_caller_passes_the_envelope():
    """A caller that forgets ``envelope=`` drops the shock budget silently (with enforce on the
    gate would then refuse every put, so the omission is loud there, but the generator would
    size past the room)."""
    root = Path(__file__).resolve().parents[1] / "src"
    watched = {"validate_candidates", "screen_csp_candidates", "screen_csp", "scan_symbol"}
    offenders: list[str] = []
    seen: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name not in watched:
                continue
            seen.add(name)
            if "envelope" not in {k.arg for k in node.keywords}:
                offenders.append(f"{path.relative_to(root.parent)}:{node.lineno} {name}(...)")
    assert watched <= seen
    assert not offenders, f"callers without envelope=: {offenders}"


def test_an_unreadable_switch_fails_closed(db, monkeypatch):
    """Review Focus 3: a settings table that cannot be read, or an unparseable switch record,
    reads `on` for the gates (never the `record` default, which would admit); live reads the
    default whatever is stored."""
    import src.storage.system_settings as ss
    from src.storage import envelope_switches as sw
    from src.storage.system_settings import set_setting

    assert sw.enforce_mode() == "record"  # nothing stored: the shipped default
    set_setting("envelope_switch:envelope_enforce", "{not json")
    assert sw.enforce_mode() == "on"

    def broken(key: str) -> str | None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(ss, "get_setting_strict", broken)
    assert sw.enforce_mode() == "on"
    monkeypatch.setattr(type(get_config()), "is_live", property(lambda self: True))
    assert sw.enforce_mode() == "record"
