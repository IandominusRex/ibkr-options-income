"""The scale-in ladder in the sizer, the Rules Engine and the send-time re-gate (Task 6).

The generator (`screen_csp_candidates`) and the gate (`validate_candidates`) apply the same
pure functions from `src/engine/regime_limits.py`, and `validate_live_quote` re-checks the
card's frozen zone against the fresh underlying price. CSPs only.
"""

from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.common.config import get_config
from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IdealZone,
    IVStats,
    MarketRegime,
    OptionQuote,
    OptionRight,
    ScaleInZone,
    SizingContext,
    SizingNote,
    Strategy,
    TechnicalStats,
    TradeCandidate,
    Verdict,
)
from src.common.universe import invalidate_universe_cache
from src.engine.regime_limits import live_ladder_note
from src.engine.risk_engine import validate_candidates, validate_live_quote
from src.regime.context import build_sizing_context
from src.storage.db import session_scope
from src.strategies.cash_secured_put import screen_csp_candidates
from tests.test_engine import _account, _candidate
from tests.test_scale_in import bars_before, put, seed_lot, utc

N = MarketRegime.NORMAL
S = MarketRegime.STRESSED

ZONE = ScaleInZone(
    anchor=100.0,
    anchor_source="order_snapshot",
    zone_low=45.0,
    zone_high=47.0,
    support=46.0,
    min_gap_pct=5.0,
    triggers=["near_money_put"],
)
# the sizer tests price a $50 put against a spot in the high 50s: its zone sits just under 60
SIZER_ZONE = ScaleInZone(
    anchor=63.0,
    anchor_source="order_snapshot",
    zone_low=57.0,
    zone_high=59.0,
    support=58.0,
    min_gap_pct=5.0,
    triggers=["near_money_put"],
)
_EXPIRY = date.today() + timedelta(days=21)


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


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


def ctx(
    zone: ScaleInZone | None = ZONE,
    *,
    symbol: str = "BAC",
    suspended: bool = False,
    loss_exit_today: list[str] | None = None,
    spot_at_send: dict[str, float] | None = None,
    for_send: bool = False,
) -> SizingContext:
    return SizingContext(
        regimes={"SPY": N, "QQQ": N},
        tech_linked=["TQQQ"],
        suspended=suspended,
        leverage={"TQQQ": 3},
        scale_in={symbol: zone} if zone is not None else {},
        loss_exit_today=loss_exit_today or [],
        spot_at_send=spot_at_send or {},
        for_send=for_send,
    )


def csp(cid: str, underlying: str = "BAC", *, spot: float | None = 50.0, **kw) -> TradeCandidate:
    cand = _candidate(candidate_id=cid, underlying=underlying, collateral=5_000.0, **kw)
    if spot is not None:
        cand.ideal = IdealZone(symbol=underlying, right=OptionRight.PUT, dte=cand.dte, spot=spot)
    return cand


def gate(cands: list[TradeCandidate], sizing: SizingContext | None, positions=None):
    acct = _account(net_liq=500_000.0, cash=400_000.0)
    return {
        v.candidate_id: v for v in validate_candidates(cands, acct, positions or [], sizing=sizing)
    }


# --------------------------------------------------------------------------- #
# decision-time gate
# --------------------------------------------------------------------------- #


def test_gate_blocks_a_lot_above_the_zone():
    out = gate([csp("a", spot=50.0)], ctx())
    assert out["a"].verdict == Verdict.REJECT
    assert out["a"].reasons == ["scale_in_zone_not_reached"]


def test_gate_allows_a_lot_inside_the_zone():
    cand = csp("a", spot=46.5)
    out = gate([cand], ctx())
    assert out["a"].verdict == Verdict.PASS, out["a"].reasons
    # and below it (the price fell through): allowed too
    assert gate([csp("b", spot=40.0)], ctx())["b"].verdict == Verdict.PASS


def test_gate_does_not_check_a_name_without_a_zone_or_a_candidate_without_ideal():
    assert gate([csp("a", spot=50.0)], ctx(zone=None))["a"].verdict == Verdict.PASS
    assert gate([csp("b", spot=None)], ctx())["b"].verdict == Verdict.PASS  # no ideal: data gap
    assert gate([csp("c", spot=50.0)], None)["c"].verdict == Verdict.PASS  # no context at all


def test_gate_blocks_after_a_loss_exit_whatever_the_zone_says():
    out = gate([csp("a", spot=40.0)], ctx(loss_exit_today=["BAC"]))
    assert out["a"].verdict == Verdict.REJECT
    assert "loss_exit_cooldown" in out["a"].reasons
    assert "scale_in_zone_not_reached" not in out["a"].reasons  # below the zone: only the cooldown
    # a different name is not blocked
    assert (
        gate([csp("b", "BAC", spot=40.0)], ctx(loss_exit_today=["SOXL"]))["b"].verdict
        == Verdict.PASS
    )


def test_regime_off_lifts_the_zone_but_not_the_same_day_loss_exit_block():
    off = ctx(suspended=True, loss_exit_today=["BAC"])
    out = gate([csp("a", spot=50.0), csp("b", "TQQQ", spot=50.0)], off)
    assert "scale_in_zone_not_reached" not in out["a"].reasons
    assert "loss_exit_cooldown" in out["a"].reasons
    assert gate([csp("c", spot=50.0)], ctx(suspended=True))["c"].verdict == Verdict.PASS


def test_near_money_put_fires_the_ladder_not_a_block():
    # Operator decisions 21 and 35: a near-the-money 78P is held. It does not stop the name; the
    # next lot is accepted at the next zone down, and refused above it.
    with session_scope() as s:
        seed_lot(
            s,
            symbol="TQQQ",
            strike=78.0,
            filled_at=utc(2026, 10, 7, 13, 51),
            spot=81.79,
            contracts=10,
            expiry=date(2026, 10, 16),
        )
        built = build_sizing_context(
            now=utc(2026, 10, 13, 16, 2),
            session=s,
            symbols=["TQQQ"],
            positions=[put(78.0, qty=-10)],
            bars={"TQQQ": bars_before("TQQQ", date(2026, 10, 13))},
            spots={"TQQQ": 78.12},
        )
    assert built is not None
    zone = built.scale_in["TQQQ"]
    inside = csp("in", "TQQQ", spot=(zone.zone_low + zone.zone_high) / 2)
    above = csp("up", "TQQQ", spot=78.12)
    out = gate([inside, above], built)
    assert out["in"].verdict == Verdict.PASS, out["in"].reasons
    assert out["up"].reasons == ["scale_in_zone_not_reached"]
    # the zone travels on the candidate the gate accepted, into the frozen snapshot
    assert inside.sizing is not None and inside.sizing.scale_in == zone


def test_ladder_never_applies_to_rolls_or_ccs():
    cc = csp("cc", strategy=Strategy.COVERED_CALL, right=OptionRight.CALL, delta=0.25, spot=50.0)
    roll = csp("roll", strategy=Strategy.ROLL, spot=50.0)
    out = gate([cc, roll], ctx(loss_exit_today=["BAC"]))
    for cid in ("cc", "roll"):
        assert "scale_in_zone_not_reached" not in out[cid].reasons
        assert "loss_exit_cooldown" not in out[cid].reasons


# --------------------------------------------------------------------------- #
# the sizer
# --------------------------------------------------------------------------- #


def _account_gen() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=500_000.0,
        total_cash=400_000.0,
        buying_power=400_000.0,
        maintenance_margin=0.0,
        excess_liquidity=400_000.0,
    )


def screen(symbol: str, price: float, sizing: SizingContext | None):
    quote = OptionQuote(
        underlying=symbol,
        right=OptionRight.PUT,
        strike=50.0,
        expiry=_EXPIRY,
        bid=1.0,
        ask=1.05,
        delta=-0.25,
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


def test_sizer_rejects_above_the_zone_and_names_the_reason():
    result = screen("BAC", 60.0, ctx(SIZER_ZONE))
    assert result.passed == []
    (cand, reasons), *_ = result.rejected
    assert "scale_in_zone_not_reached" in reasons
    assert cand.sizing is not None and cand.sizing.scale_in == SIZER_ZONE


def test_sizer_passes_inside_the_zone_and_copies_the_zone_to_the_candidate():
    result = screen("BAC", 58.0, ctx(SIZER_ZONE))
    assert result.rejected == []
    note = result.passed[0].sizing
    assert note is not None and note.scale_in == SIZER_ZONE


def test_sizer_applies_the_same_day_loss_exit_block_and_regime_off_lifts_only_the_zone():
    blocked = screen("BAC", 58.0, ctx(SIZER_ZONE, loss_exit_today=["BAC"]))
    assert blocked.passed == []
    assert "loss_exit_cooldown" in blocked.rejected[0][1]
    off = screen("BAC", 60.0, ctx(SIZER_ZONE, suspended=True, loss_exit_today=["BAC"]))
    assert off.rejected[0][1].count("loss_exit_cooldown") == 1
    assert "scale_in_zone_not_reached" not in off.rejected[0][1]
    lifted = screen("BAC", 60.0, ctx(SIZER_ZONE, suspended=True))
    assert lifted.rejected == [] and len(lifted.passed) == 1


def test_sizer_and_gate_agree_on_a_ladder_block():
    generator = screen("BAC", 60.0, ctx(SIZER_ZONE))
    assert "scale_in_zone_not_reached" in generator.rejected[0][1]
    # a card that slipped past the generator is still stopped by the gate, with the same reason
    assert gate([csp("a", spot=60.0)], ctx(SIZER_ZONE))["a"].reasons == [
        "scale_in_zone_not_reached"
    ]


# --------------------------------------------------------------------------- #
# the send-time re-gate
# --------------------------------------------------------------------------- #


def quote(*, underlying_price: float | None = None) -> OptionQuote:
    return OptionQuote(
        underlying="BAC",
        right=OptionRight.PUT,
        strike=150.0,
        expiry=_EXPIRY,
        bid=2.95,
        ask=3.05,
        delta=-0.20,
        underlying_price=underlying_price,
    )


def framed(zone: ScaleInZone | None = ZONE) -> TradeCandidate:
    cand = _candidate(candidate_id="live", underlying="BAC")
    cand.sizing = SizingNote(
        pre_regime_contracts=1,
        regime=N,
        regime_index="SPY",
        per_trade_cap=10,
        budget_multiplier=1.0,
        scale_in=zone,
    )
    return cand


def test_live_regate_blocks_when_the_underlying_bounced_above_the_zone():
    send = ctx(zone=None, for_send=True)  # the send-time context carries no zone: the card's does
    bounced = validate_live_quote(framed(), quote(underlying_price=50.0), sizing=send)
    assert bounced.verdict == Verdict.REJECT
    assert bounced.reasons == ["scale_in_zone_not_reached"]
    inside = validate_live_quote(framed(), quote(underlying_price=46.0), sizing=send)
    assert inside.verdict == Verdict.PASS, inside.reasons


def test_live_regate_uses_spot_at_send_without_an_underlying_price():
    # ruling 48: the quote carries no underlying price (paper fallback greeks)
    bounced = validate_live_quote(
        framed(), quote(), sizing=ctx(zone=None, spot_at_send={"BAC": 50.0}, for_send=True)
    )
    assert bounced.reasons == ["scale_in_zone_not_reached"]
    inside = validate_live_quote(
        framed(), quote(), sizing=ctx(zone=None, spot_at_send={"BAC": 46.0}, for_send=True)
    )
    assert inside.verdict == Verdict.PASS
    # no price anywhere: not re-checked, and the order detail says so
    send = ctx(zone=None, for_send=True)
    assert validate_live_quote(framed(), quote(), sizing=send).verdict == Verdict.PASS
    assert live_ladder_note(framed(), quote(), send) == "ladder not re-checked: no underlying price"
    # a price (or no zone) means there is nothing to note
    assert live_ladder_note(framed(), quote(underlying_price=46.0), send) is None
    assert live_ladder_note(framed(zone=None), quote(), send) is None


def test_live_regate_rejects_after_a_loss_exit_since_the_card():
    send = ctx(zone=None, loss_exit_today=["BAC"], for_send=True)
    verdict = validate_live_quote(framed(zone=None), quote(), sizing=send)
    assert verdict.verdict == Verdict.REJECT and verdict.reasons == ["loss_exit_cooldown"]
    # regime off does not lift it
    off = ctx(zone=None, suspended=True, loss_exit_today=["BAC"], for_send=True)
    assert validate_live_quote(framed(zone=None), quote(), sizing=off).reasons == [
        "loss_exit_cooldown"
    ]


def test_live_regate_without_sizing_is_unchanged_and_ignores_rolls_and_calls():
    assert validate_live_quote(framed(), quote(underlying_price=50.0)).verdict == Verdict.PASS
    roll = _candidate(candidate_id="r", strategy=Strategy.ROLL)
    assert validate_live_quote(roll, quote(), sizing=ctx(loss_exit_today=["AAPL"])).verdict == (
        Verdict.PASS
    )
    cc = framed()
    cc = cc.model_copy(update={"strategy": Strategy.COVERED_CALL, "right": OptionRight.CALL})
    off_zone = ctx(zone=None, spot_at_send={"BAC": 50.0}, loss_exit_today=["BAC"], for_send=True)
    reasons = validate_live_quote(cc, quote(underlying_price=50.0), sizing=off_zone).reasons
    assert "scale_in_zone_not_reached" not in reasons and "loss_exit_cooldown" not in reasons


# --------------------------------------------------------------------------- #
# the executor and the callers
# --------------------------------------------------------------------------- #


async def test_the_executor_hands_the_send_context_to_the_live_regate(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from src.common.schemas import OrderState
    from src.storage.models import OrderRow
    from tests.test_execution import _db_setup, _make_mock_bot, _make_mock_ib

    _db_setup(tmp_path, monkeypatch)
    mock_cfg = MagicMock()
    mock_cfg.execution.fill_timeout_minutes = 1
    mock_cfg.execution.quote_timeout_seconds = 1.0
    mock_cfg.is_live = False
    monkeypatch.setattr("src.execution.executor.get_config", lambda: mock_cfg)
    with session_scope() as session:
        order = OrderRow(candidate_id="live", state=OrderState.QUEUED)
        session.add(order)
        session.flush()
        order_id = order.id

    from src.execution.executor import execute_candidate

    mock_ib = _make_mock_ib()
    mock_ib.reqMktData.return_value.modelGreeks.undPrice = 50.0  # bounced above the 47 zone top
    candidate = framed()
    candidate = candidate.model_copy(update={"strike": 150.0})
    await execute_candidate(
        mock_ib,
        _make_mock_bot(),
        "99999",
        order_id,
        candidate,
        sizing=ctx(zone=None, for_send=True),
    )
    with session_scope() as s:
        row = s.get(OrderRow, order_id)
    assert row.state == OrderState.REJECTED
    assert "next lower entry zone" in row.detail
    mock_ib.placeOrder.assert_not_called()


def test_every_send_path_caller_passes_sizing():
    """Review Focus 1, send side: a caller that forgets ``sizing=`` silently drops the ladder."""
    root = Path(__file__).resolve().parents[1] / "src"
    watched = {"validate_live_quote", "execute_candidate"}
    offenders: list[str] = []
    seen = 0
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
            if "sizing" not in {k.arg for k in node.keywords}:
                offenders.append(f"{path.relative_to(root.parent)}:{node.lineno} {name}(...)")
    assert seen >= 3, "the AST walk found too few call sites; the test lost its target"
    assert not offenders, f"send-path callers without sizing=: {offenders}"


def test_the_roll_executor_passes_no_sizing_on_purpose():
    text = (Path(__file__).resolve().parents[1] / "src/execution/roll_executor.py").read_text(
        encoding="utf-8"
    )
    assert "validate_live_quote(candidate, new_quote, sizing=None)" in text


# --------------------------------------------------------------------------- #
# labels, card, the record
# --------------------------------------------------------------------------- #


def test_new_reason_codes_have_the_same_label_in_both_tables():
    from src.api.routers.options import _REASON_LABELS
    from src.notify.formatters import _REJECT_REASON_LABELS

    for code in ("scale_in_zone_not_reached", "loss_exit_cooldown"):
        assert code in _REJECT_REASON_LABELS and code in _REASON_LABELS
        assert _REJECT_REASON_LABELS[code] == _REASON_LABELS[code]
    assert (
        _REJECT_REASON_LABELS["scale_in_zone_not_reached"]
        == "the price has not reached the next lower entry zone"
    )
    assert _REJECT_REASON_LABELS["loss_exit_cooldown"] == "a loss exit on this name earlier today"


def _card_text(cand: TradeCandidate) -> str:
    from src.notify.formatters import format_candidate

    return format_candidate(cand, None).replace("\\", "")


def test_the_card_shows_the_next_lot_zone():
    zoned = ScaleInZone(
        anchor=50.7,
        anchor_source="order_snapshot",
        zone_low=47.10,
        zone_high=49.20,
        support=48.15,
        min_gap_pct=5.0,
        triggers=["near_money_put"],
    )
    text = _card_text(framed(zoned))
    assert "Next lot zone $47.10–$49.20 (support $48.15, 5.0% below the last lot)" in text
    no_support = zoned.model_copy(update={"support": None})
    assert "Next lot zone $47.10–$49.20 (5.0% below the last lot)" in _card_text(framed(no_support))
    assert "Next lot zone" not in _card_text(framed(zone=None))


def test_ladder_blocks_are_recorded_once_per_name_kind_and_day():
    from src.regime.actions import record_scan_actions
    from src.storage.models import SizingActionRow

    blocked = csp("a", spot=50.0)
    again = csp("b", spot=51.0)
    loss = csp("c", "TQQQ", spot=50.0)
    rejects = [
        (blocked, ["scale_in_zone_not_reached"]),
        (again, ["scale_in_zone_not_reached"]),
        (loss, ["loss_exit_cooldown", "scale_in_zone_not_reached"]),
    ]
    for _ in range(2):  # two scans in a day
        record_scan_actions(top=[], scored=[], verdicts={}, generator_rejects=rejects)
    with session_scope() as s:
        rows = s.query(SizingActionRow).order_by(SizingActionRow.underlying).all()
    assert [(r.underlying, r.kind, r.sent_contracts) for r in rows] == [
        ("BAC", "scale_in_zone", 0),
        ("TQQQ", "loss_exit_cooldown", 0),
    ]


def test_a_reject_with_another_reason_besides_the_ladder_is_not_recorded_as_a_ladder_block():
    from src.regime.actions import record_scan_actions
    from src.storage.models import SizingActionRow

    mixed = csp("a", spot=50.0)
    record_scan_actions(
        top=[],
        scored=[],
        verdicts={},
        generator_rejects=[(mixed, ["scale_in_zone_not_reached", "roc_below_minimum"])],
    )
    with session_scope() as s:
        assert s.query(SizingActionRow).count() == 0


# --------------------------------------------------------------------------- #
# OI-E4: the ladder's blocks are recorded even when nothing else passes the generator
# --------------------------------------------------------------------------- #


def _ladder_rows() -> list[tuple[str, str, int]]:
    from src.storage.models import SizingActionRow

    with session_scope() as s:
        rows = s.query(SizingActionRow).order_by(SizingActionRow.underlying).all()
        return [(r.underlying, r.kind, r.sent_contracts) for r in rows]


@pytest.mark.asyncio
async def test_a_scan_where_the_ladder_stops_every_csp_still_records_the_blocks(monkeypatch):
    """Every CSP is stopped by the ladder or the loss-exit block, nothing else passes the
    generator: `record_scan_actions` used to run only when some candidate passed, so these scans
    recorded nothing and the 4-week ladder review would have missed the blocks that matter most."""
    from unittest.mock import MagicMock

    import src.orchestrator.scan as scanmod
    from src.strategies._evaluation import ScreenResult
    from tests.test_scan_review_reuse import _stub_pipeline

    _stub_pipeline(scanmod, monkeypatch, {"n": 0})
    blocked = {
        "BAC": (csp("zone", "BAC", spot=50.0), ["scale_in_zone_not_reached"]),
        "TQQQ": (csp("loss", "TQQQ", spot=50.0), ["loss_exit_cooldown"]),
    }

    def screen_csp(symbol, *args, **kwargs):
        cand, reasons = blocked[symbol]
        return ScreenResult(rejected=[(cand, reasons)], evaluated=1)

    monkeypatch.setattr(scanmod, "screen_csp_candidates", screen_csp)
    monkeypatch.setattr(scanmod, "screen_cc_candidates", lambda *a, **k: ScreenResult())

    await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1")

    assert _ladder_rows() == [("BAC", "scale_in_zone", 0), ("TQQQ", "loss_exit_cooldown", 0)]

    # a second scan the same ET day: the same names, kinds and day add nothing
    await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1")
    assert _ladder_rows() == [("BAC", "scale_in_zone", 0), ("TQQQ", "loss_exit_cooldown", 0)]
