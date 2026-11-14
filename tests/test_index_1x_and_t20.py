"""The index class's budget multipliers and the T20 limit (risk-envelope Task 24; spec §3.8 and §3.4.3,
rulings E10 and H8).

``regime.csp.budget_multiplier_by_class.index_1x`` replaces the old budget multipliers for the
broad-index ETFs while the ``index_1x`` switch is on and is only recorded (``sizing_actions`` kind
``index_1x_record``) while it is off. The T20 scenario becomes an admission test when the ``t20_limit``
switch is on, through the room the envelope builds from that switch.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.config import get_config, get_regime_cfg
from src.common.envelope_types import BookLine, ShockInputs
from src.common.market_hours import today_et
from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    MarketRegime,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    SizingContext,
    TechnicalStats,
    Verdict,
)
from src.common.universe import invalidate_universe_cache
from src.engine import regime_limits as rl
from src.engine.risk_engine import validate_candidates
from src.strategies.cash_secured_put import screen_csp_candidates
from tests.test_engine import _account, _candidate

N, C, S, X = (
    MarketRegime.NORMAL,
    MarketRegime.CAUTIOUS,
    MarketRegime.STRESSED,
    MarketRegime.CRISIS,
)
EXPIRY = today_et() + timedelta(days=21)


@pytest.fixture(autouse=True)
def _universe(monkeypatch):
    cfg = get_config()
    names = ["QQQ", "NVDA", "BAC"]
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": names,
            "actively_wheeling": names,
            "sectors": {"QQQ": "index", "NVDA": "tech", "BAC": "financials", "BOOK": "other"},
            "leveraged_etfs": [],
        },
    )
    invalidate_universe_cache()
    yield
    invalidate_universe_cache()


def ctx(regime: MarketRegime = C, *, index_1x: str = "off") -> SizingContext:
    return SizingContext(
        regimes={"SPY": regime, "QQQ": regime},
        tech_linked=["QQQ", "NVDA"],
        switches={"index_1x": index_1x},
    )


def account() -> AccountSnapshot:
    # deployable = 400k - 20% = 320k: max_csp_collateral 320k at 100%
    return AccountSnapshot(
        account="DU1",
        net_liquidation=500_000.0,
        total_cash=400_000.0,
        buying_power=400_000.0,
        maintenance_margin=0.0,
        excess_liquidity=400_000.0,
    )


def book(collateral: float = 200_000.0) -> list[PositionSnapshot]:
    return [
        PositionSnapshot(
            symbol="BOOK P",
            sec_type="OPT",
            position=-10.0,
            avg_cost=1.0,
            right=OptionRight.PUT,
            strike=collateral / 1000.0,
            expiry=today_et() + timedelta(days=30),
            underlying="BOOK",
        )
    ]


def screen(symbol: str, sizing: SizingContext, *, positions=None, strike: float = 100.0):
    return screen_csp_candidates(
        symbol,
        [
            OptionQuote(
                underlying=symbol,
                right=OptionRight.PUT,
                strike=strike,
                expiry=EXPIRY,
                bid=2.0,
                ask=2.1,
                delta=-0.25,
                open_interest=500,
                volume=100,
            )
        ],
        account(),
        IVStats(symbol=symbol, iv_rank=50.0, current_iv=35.0, hv_30=20.0),
        TechnicalStats(symbol=symbol, price=120.0),
        FundamentalStats(symbol=symbol, quality_flag=True),
        positions=positions if positions is not None else book(),
        sizing=sizing,
    )


# --------------------------------------------------------------------------- #
# index_1x
# --------------------------------------------------------------------------- #


def test_the_class_table_defaults_and_validates():
    table = get_regime_cfg().csp.budget_multiplier_by_class["index_1x"]
    assert (table[N], table[C], table[S], table[X]) == (1.0, 1.0, 0.8, 0.5)
    from src.common.config import RegimeCspCfg

    with pytest.raises(ValueError):
        RegimeCspCfg(budget_multiplier_by_class={"single_names": {"normal": 1.0}})
    with pytest.raises(ValueError):
        RegimeCspCfg(budget_multiplier_by_class={"index_1x": {"stressed": 1.5}})
    partial = RegimeCspCfg(budget_multiplier_by_class={"index_1x": {"crisis": 0.25}})
    assert partial.budget_multiplier_by_class["index_1x"][X] == 0.25
    assert partial.budget_multiplier_by_class["index_1x"][C] == 1.0


def test_index_1x_multipliers_apply_only_when_switched_on():
    # cautious: the old table is 0.7 for the name and the book, the class table 1.0
    assert rl.multipliers(ctx(C, index_1x="off"), "QQQ") == (0.7, 0.7)
    assert rl.multipliers(ctx(C, index_1x="on"), "QQQ") == (1.0, 1.0)
    # stressed and crisis: 0.4 -> 0.8 and 0.1 -> 0.5
    assert rl.multipliers(ctx(S, index_1x="on"), "QQQ") == (0.8, 0.8)
    assert rl.multipliers(ctx(X, index_1x="on"), "QQQ") == (0.5, 0.5)
    assert rl.multipliers(ctx(X, index_1x="off"), "QQQ") == (0.1, 0.1)
    # sized, the generator proposes more under the class table, and the gate agrees
    off = screen("QQQ", ctx(C, index_1x="off")).passed[0]
    on = screen("QQQ", ctx(C, index_1x="on")).passed[0]
    assert (off.contracts, on.contracts) == (2, 6)
    acct = _account(net_liq=500_000.0, cash=400_000.0)

    def gate(card, sizing):
        return validate_candidates([card], acct, book(), sizing=sizing)[0]

    assert gate(on, ctx(C, index_1x="on")).verdict == Verdict.PASS
    # old table, guaranteed floor used up: the same six lots are over the scaled budget
    used_up = ctx(C, index_1x="off").model_copy(update={"floor_lots_counted": {"QQQ": 99}})
    assert gate(on, used_up).reasons == ["regime_budget"]


def test_index_1x_records_while_off(db):
    from src.storage.db import session_scope
    from src.storage.models import SizingActionRow

    cand = screen("QQQ", ctx(C, index_1x="off")).passed[0]
    assert cand.contracts == 2  # the size is unchanged
    with session_scope() as s:
        rows = s.query(SizingActionRow).filter_by(kind="index_1x_record").all()
        assert [(r.underlying, r.deterministic_contracts, r.sent_contracts) for r in rows] == [
            ("QQQ", 2, 6)
        ]
        assert rows[0].record_key.endswith(":generator")
    # switched on there is nothing left to record; a single name never records
    screen("QQQ", ctx(C, index_1x="on"))
    screen("NVDA", ctx(C, index_1x="off"))
    with session_scope() as s:
        assert s.query(SizingActionRow).filter_by(kind="index_1x_record").count() == 1


def test_single_names_keep_the_old_multipliers():
    for name in ("NVDA", "BAC"):
        assert rl.multipliers(ctx(C, index_1x="on"), name) == (0.7, 0.7)
        assert rl.multipliers(ctx(S, index_1x="on"), name) == (0.4, 0.4)
    assert (
        screen("NVDA", ctx(C, index_1x="on")).passed[0].contracts
        == screen("NVDA", ctx(C, index_1x="off")).passed[0].contracts
    )
    assert rl.class_multipliers(ctx(C), "NVDA") is None
    # the regime limits off: nothing is multiplied, class or not
    assert rl.multipliers(ctx(C, index_1x="on").model_copy(update={"suspended": True}), "QQQ") == (
        1.0,
        1.0,
    )


def test_the_index_1x_switch_is_off_in_live(db, monkeypatch):
    from datetime import UTC, datetime

    from src.common.config import Config
    from src.regime.context import build_sizing_context
    from src.storage.db import session_scope
    from src.storage.envelope_switches import set_switch

    set_switch("index_1x", "on", source="cli")
    with session_scope() as s:
        paper = build_sizing_context(now=datetime.now(UTC), session=s, for_send=True)
    assert paper is not None and paper.switches["index_1x"] == "on"
    monkeypatch.setattr(Config, "is_live", property(lambda self: True))
    with session_scope() as s:
        live = build_sizing_context(now=datetime.now(UTC), session=s, for_send=True)
    assert live is not None and live.switches["index_1x"] == "off"


# --------------------------------------------------------------------------- #
# T20 end to end: switch -> room -> generator and gate
# --------------------------------------------------------------------------- #

NLV = 500_000.0


def t20_inputs() -> ShockInputs:
    """A $400k NVDA book (tech-linked, beta 1): S10 8%, T20 16% against a 15% start-level floor."""
    names = {"NVDA", "BOOK"}
    return ShockInputs(
        lines=(BookLine(symbol="NVDA", kind="stock", qty=2_500.0, spot=160.0),),
        betas={s: 1.0 for s in names},
        betas_smh={s: 1.0 for s in names},
        leverage={},
        governing={},
        tech_linked=frozenset({"NVDA"}),
        semis=frozenset(),
        nlv=NLV,
    )


def _csp_card():
    return _candidate(
        candidate_id="nv", underlying="NVDA", contracts=1, collateral=15_000.0
    ).model_copy(update={"quote_iv": 0.40, "underlying_price": 160.0})


def _gate(room_inputs):
    acct = _account(net_liq=NLV, cash=400_000.0)
    sizing = SizingContext(regimes={"SPY": N, "QQQ": N}, tech_linked=["NVDA"])
    return validate_candidates([_csp_card()], acct, [], sizing=sizing, envelope=room_inputs)[0]


def test_t20_limit_gates_only_when_on(db):
    from src.engine.envelope import room as envelope_room
    from src.storage.envelope_switches import set_switch

    set_switch("envelope_enforce", "on", source="cli")
    inputs = t20_inputs()

    off_room = envelope_room(inputs, today=date.today())
    assert off_room.t20_limit is None and off_room.t20_gross > off_room.s10_limit
    assert (
        _gate((off_room, inputs)).verdict == Verdict.PASS
    )  # S10 and U_ew have room; T20 not tested

    set_switch("t20_limit", "on", source="cli")
    on_room = envelope_room(inputs, today=date.today())
    assert on_room.t20_limit == pytest.approx(on_room.s10_limit)
    verdict = _gate((on_room, inputs))
    assert verdict.reasons == ["t20_budget"]  # the book is above L(t) on T20 and the put raises it

    # the generator trims to nothing for the same reason; with the switch off it keeps its size
    def generated(room):
        return screen_csp_candidates(
            "NVDA",
            [
                OptionQuote(
                    underlying="NVDA",
                    right=OptionRight.PUT,
                    strike=150.0,
                    expiry=EXPIRY,
                    bid=3.0,
                    ask=3.1,
                    delta=-0.25,
                    open_interest=500,
                    volume=100,
                    iv=0.40,
                    underlying_price=160.0,
                )
            ],
            _account_for_gen(),
            IVStats(symbol="NVDA", iv_rank=50.0, current_iv=40.0, hv_30=25.0),
            TechnicalStats(symbol="NVDA", price=160.0),
            FundamentalStats(symbol="NVDA", quality_flag=True),
            positions=[],
            sizing=SizingContext(regimes={"SPY": N, "QQQ": N}, tech_linked=["NVDA"]),
            envelope=(room, inputs),
        )

    assert generated(off_room).passed
    refused = generated(on_room)
    assert refused.passed == []
    (_, reasons), *_ = refused.rejected
    assert "t20_budget" in reasons


def _account_for_gen() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=NLV,
        total_cash=400_000.0,
        buying_power=400_000.0,
        maintenance_margin=0.0,
        excess_liquidity=400_000.0,
    )


def test_the_t20_switch_is_off_in_live(db, monkeypatch):
    from src.common.config import Config
    from src.engine.envelope import room as envelope_room
    from src.storage.envelope_switches import set_switch

    set_switch("envelope_enforce", "on", source="cli")
    set_switch("t20_limit", "on", source="cli")
    monkeypatch.setattr(Config, "is_live", property(lambda self: True))
    inputs = t20_inputs()
    assert envelope_room(inputs, today=date.today(), may_start=False).t20_limit is None
