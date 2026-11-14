"""The tech-linked cap and the stacking rule (risk-envelope Task 25; spec §3.4.4, ruling E15).

Both are pure functions in `engine/regime_limits.py` that the generator (`screen_csp_candidates`)
and the Rules Engine (`validate_candidates`) call, each behind its own switch (``tech_cap``,
``stacking_rule``): on, the cap trims or refuses (``tech_linked_cap``) and the rule halves or blocks
(``stacking_halve``, ``stacking_block``); off, the would-be action is recorded in ``sizing_actions``
(``tech_cap_record``, ``stacking_record``) and nothing changes. Every switch reads off in live.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.common.config import get_config
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
from src.regime.actions import record_envelope_verdicts
from src.strategies.cash_secured_put import screen_csp_candidates
from tests.test_engine import _account, _candidate

N = MarketRegime.NORMAL
NLV = 500_000.0
TECH = ["NVDA", "AMD", "AAPL", "MSFT", "GOOGL", "META", "TQQQ"]
EXPIRY = today_et() + timedelta(days=21)


@pytest.fixture(autouse=True)
def _universe(monkeypatch):
    cfg = get_config()
    names = ["NVDA", "BAC", "TQQQ"]
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


def ctx(*, tech_cap: str = "off", stacking: str = "off", fills: dict[str, int] | None = None):
    return SizingContext(
        regimes={"SPY": N, "QQQ": N},
        tech_linked=TECH,
        leverage={"TQQQ": 3},
        switches={"tech_cap": tech_cap, "stacking_rule": stacking},
        csp_fills_by_name=fills or {},
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


def stock(symbol: str, value: float) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        sec_type="STK",
        position=value / 100.0,
        avg_cost=100.0,
        market_price=100.0,
        market_value=value,
        underlying=symbol,
    )


def short_put(symbol: str, strike: float, *, days: int = 21, qty: float = 1.0) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=f"{symbol} P",
        sec_type="OPT",
        position=-qty,
        avg_cost=1.0,
        right=OptionRight.PUT,
        strike=strike,
        expiry=today_et() + timedelta(days=days),
        underlying=symbol,
    )


def tech_book(total: float = 270_000.0) -> list[PositionSnapshot]:
    """Six tech names at $45k each (every one under the 10% per-ticker cap): 54% of a $500k NLV."""
    names = ["AMD", "AAPL", "MSFT", "GOOGL", "META", "NVDA"]
    return [stock(n, total / len(names)) for n in names]


def screen(symbol: str, sizing, positions, *, strike: float = 150.0, expiry=EXPIRY, price=160.0):
    return screen_csp_candidates(
        symbol,
        [
            OptionQuote(
                underlying=symbol,
                right=OptionRight.PUT,
                strike=strike,
                expiry=expiry,
                bid=3.0,
                ask=3.1,
                delta=-0.25,
                open_interest=500,
                volume=100,
            )
        ],
        account(),
        IVStats(symbol=symbol, iv_rank=50.0, current_iv=35.0, hv_30=20.0),
        TechnicalStats(symbol=symbol, price=price),
        FundamentalStats(symbol=symbol, quality_flag=True),
        positions=positions,
        sizing=sizing,
    )


def card(contracts: int, symbol: str = "NVDA", **extra):
    return _candidate(
        candidate_id="c1",
        underlying=symbol,
        contracts=contracts,
        collateral=15_000.0 * contracts,
        dte=21,
        current_iv=35.0,
    ).model_copy(update={"underlying_price": 160.0, **extra})


def gate(cards, sizing, positions):
    acct = _account(net_liq=NLV, cash=400_000.0)
    return {v.candidate_id: v for v in validate_candidates(cards, acct, positions, sizing=sizing)}


# --------------------------------------------------------------------------- #
# the tech-linked cap
# --------------------------------------------------------------------------- #


def test_tech_cap_blocks_above_sixty_percent_leverage_weighted():
    c = ctx(tech_cap="on")
    book = tech_book()  # 270k = 54% of NLV; the cap is 300k
    # pure: exposure + the new lot, leverage-weighted, against 60% of NLV
    assert (
        rl.tech_cap_reason(
            c, "NVDA", tech_exposure=270_000.0, new_weighted=30_000.0, net_liq=NLV, cap_pct=60.0
        )
        is None
    )  # lands exactly on the cap
    assert (
        rl.tech_cap_reason(
            c, "NVDA", tech_exposure=270_000.0, new_weighted=30_001.0, net_liq=NLV, cap_pct=60.0
        )
        == "tech_linked_cap"
    )
    # not a tech-linked name: never applies
    assert (
        rl.tech_cap_reason(
            c, "BAC", tech_exposure=900_000.0, new_weighted=50_000.0, net_liq=NLV, cap_pct=60.0
        )
        is None
    )
    # the gate: 2 lots (30k) fit, 3 do not
    assert gate([card(2)], c, book)["c1"].verdict == Verdict.PASS
    assert gate([card(3)], c, book)["c1"].reasons == ["tech_linked_cap"]
    # a name outside the list keeps passing the same book
    assert gate([card(3, "BAC")], c, book)["c1"].verdict == Verdict.PASS
    # the generator trims to the room and agrees with the gate
    made = screen("NVDA", c, book).passed[0]
    assert made.contracts == 2
    assert made.sizing is not None and made.sizing.limit_binding == "tech_linked_cap"
    assert gate([made], c, book)[made.candidate_id].verdict == Verdict.PASS
    # a full book gets no lot at all, with the reason
    full = tech_book(300_000.0)
    refused = screen("NVDA", c, full)
    assert refused.passed == []
    assert "tech_linked_cap" in refused.rejected[0][1]


def test_tech_cap_counts_a_leveraged_etf_at_its_leverage():
    c = ctx(tech_cap="on")
    # $90k of TQQQ stock counts as $270k: with the other names at 54% the book is far over
    book = [stock("TQQQ", 90_000.0)]
    assert rl.tech_exposure(c, {"TQQQ": 270_000.0, "BAC": 80_000.0, "NVDA": 10_000.0}) == 280_000.0
    over = gate([card(1)], c, book)["c1"]
    assert over.verdict == Verdict.PASS  # 270k + 15k = 285k <= 300k
    book2 = [stock("TQQQ", 95_000.0)]  # 285k + 15k = 300k: the cap
    assert gate([card(1)], c, book2)["c1"].verdict == Verdict.PASS
    book3 = [stock("TQQQ", 97_000.0)]  # 291k + 15k > 300k
    assert gate([card(1)], c, book3)["c1"].reasons == ["tech_linked_cap"]


def test_tech_cap_off_records_only(db):
    from src.storage.db import session_scope
    from src.storage.models import SizingActionRow

    c = ctx(tech_cap="off")
    book = tech_book()
    cards = [card(3)]
    verdicts = list(
        validate_candidates(cards, _account(net_liq=NLV, cash=400_000.0), book, sizing=c)
    )
    assert verdicts[0].verdict == Verdict.PASS and verdicts[0].reasons == []
    assert verdicts[0].limits_would == ["tech_linked_cap"]
    assert record_envelope_verdicts(cards, verdicts, where="scan") == 1
    made = screen("NVDA", c, book).passed[0]
    assert made.contracts > 2  # the generator keeps its size while the switch is off
    with session_scope() as s:
        rows = s.query(SizingActionRow).filter_by(kind="tech_cap_record").all()
        assert {r.record_key.rsplit(":", 1)[-1] for r in rows} == {"scan", "generator"}
        assert all(r.underlying == "NVDA" for r in rows)


# --------------------------------------------------------------------------- #
# the stacking rule
# --------------------------------------------------------------------------- #

_ACT = dict(overlap_days=7, fills_limit=2)


def _act(shorts, *, spot=160.0, fills=0, days=21):
    return rl.stacking_action(
        expiry=today_et() + timedelta(days=days),
        spot=spot,
        shorts=shorts,
        same_day_fills=fills,
        **_ACT,
    )


def test_stacking_action_is_pure():
    near = (150.0, today_et() + timedelta(days=21))
    assert _act([]) == "none"
    assert _act([near]) == "halve"
    assert _act([(150.0, today_et() + timedelta(days=28))]) == "halve"  # +7 days: inside
    assert _act([(150.0, today_et() + timedelta(days=29))]) == "none"  # +8 days: outside
    assert _act([(150.0, today_et() + timedelta(days=14))]) == "halve"  # -7 days: inside
    assert _act([(150.0, today_et() + timedelta(days=13))]) == "none"
    assert _act([(170.0, today_et() + timedelta(days=90))]) == "block"  # ITM: strike over spot
    assert _act([(170.0, today_et() + timedelta(days=90))], spot=None) == "none"  # unknown spot
    assert _act([], fills=1) == "none" and _act([], fills=2) == "block"
    assert _act([near], fills=2) == "block"  # the stronger action wins


def test_stacking_halves_on_an_overlapping_expiry():
    c = ctx(stacking="on")
    book = [short_put("NVDA", 140.0, days=24)]  # three days from the new expiry
    plain = screen("NVDA", ctx(stacking="off"), book).passed[0].contracts
    halved = screen("NVDA", c, book).passed[0]
    assert plain >= 2 and halved.contracts == plain // 2
    assert halved.sizing is not None and halved.sizing.limit_binding == "stacking_halve"
    assert halved.sizing.limit_from == plain
    # the gate accepts the halved size and refuses a bigger one
    assert gate([halved], c, book)[halved.candidate_id].verdict == Verdict.PASS
    bigger = halved.model_copy(update={"contracts": halved.contracts + 1})
    assert "stacking_halve" in gate([bigger], c, book)[bigger.candidate_id].reasons
    # a short far from the expiry changes nothing
    far = [short_put("NVDA", 140.0, days=60)]
    assert screen("NVDA", c, far).passed[0].contracts == plain
    # a size of one lot halves to nothing: refused with the reason, never rounded up
    full = [short_put("NVDA", 140.0, days=24, qty=7)]  # leaves room for exactly one more lot
    assert [x.contracts for x in screen("NVDA", ctx(stacking="off"), full).passed] == [1]
    one_lot = screen("NVDA", c, full)
    assert one_lot.passed == [] and "stacking_halve" in one_lot.rejected[0][1]


def test_stacking_blocks_on_an_itm_short():
    c = ctx(stacking="on")
    itm = [short_put("NVDA", 175.0, days=60)]  # strike over the 160 spot
    result = screen("NVDA", c, itm)
    assert result.passed == []
    assert "stacking_block" in result.rejected[0][1]
    assert gate([card(1)], c, itm)["c1"].reasons == ["stacking_block"]
    otm = [short_put("NVDA", 140.0, days=60)]
    assert gate([card(1)], c, otm)["c1"].verdict == Verdict.PASS


def test_stacking_blocks_on_two_same_day_fills():
    c1 = ctx(stacking="on", fills={"NVDA": 1})
    c2 = ctx(stacking="on", fills={"NVDA": 2})
    assert gate([card(1)], c1, [])["c1"].verdict == Verdict.PASS
    assert gate([card(1)], c2, [])["c1"].reasons == ["stacking_block"]
    result = screen("NVDA", c2, [])
    assert result.passed == [] and "stacking_block" in result.rejected[0][1]
    # another name's fills do not count
    assert gate([card(1)], ctx(stacking="on", fills={"AMD": 5}), [])["c1"].verdict == Verdict.PASS


def test_stacking_off_records_only(db):
    from src.storage.db import session_scope
    from src.storage.models import SizingActionRow

    c = ctx(stacking="off", fills={"NVDA": 2})
    cards = [card(1)]
    verdicts = validate_candidates(cards, _account(net_liq=NLV, cash=400_000.0), [], sizing=c)
    assert verdicts[0].verdict == Verdict.PASS
    assert verdicts[0].limits_would == ["stacking_block"]
    assert record_envelope_verdicts(cards, verdicts, where="scan") == 1
    made = screen("NVDA", c, [])
    assert made.passed  # the generator keeps its size
    halve = ctx(stacking="off")
    near = [short_put("NVDA", 140.0, days=24)]
    kept = screen("NVDA", halve, near).passed[0]
    assert kept.contracts == screen("NVDA", ctx(stacking="off"), near).passed[0].contracts
    assert kept.sizing is not None and kept.sizing.limit_from is None
    with session_scope() as s:
        rows = s.query(SizingActionRow).filter_by(kind="stacking_record").all()
        assert {r.underlying for r in rows} == {"NVDA"} and len(rows) >= 2
        assert any("halve" in r.reason for r in rows) and any("block" in r.reason for r in rows)


def test_both_switches_read_off_in_live(db, monkeypatch):
    from datetime import UTC, datetime

    from src.common.config import Config
    from src.regime.context import build_sizing_context
    from src.storage.db import session_scope
    from src.storage.envelope_switches import set_switch

    set_switch("tech_cap", "on", source="cli")
    set_switch("stacking_rule", "on", source="cli")
    with session_scope() as s:
        paper = build_sizing_context(now=datetime.now(UTC), session=s, for_send=True)
    assert paper is not None
    assert (paper.switches["tech_cap"], paper.switches["stacking_rule"]) == ("on", "on")
    monkeypatch.setattr(Config, "is_live", property(lambda self: True))
    with session_scope() as s:
        live = build_sizing_context(now=datetime.now(UTC), session=s, for_send=True)
    assert live is not None
    assert (live.switches["tech_cap"], live.switches["stacking_rule"]) == ("off", "off")


def test_the_context_counts_todays_sent_csp_fills_per_name(db):
    from datetime import UTC, datetime

    from src.common.schemas import OrderState
    from src.regime.context import build_sizing_context
    from src.storage.db import session_scope
    from src.storage.models import OrderRow

    def order(cid: str, state: OrderState, name: str) -> OrderRow:
        return OrderRow(
            candidate_id=cid,
            state=state,
            snapshot={"strategy": "cash_secured_put", "underlying": name},
            created_at=datetime.now(UTC),
        )

    with session_scope() as s:
        s.add_all(
            [
                order("a", OrderState.FILLED, "NVDA"),
                order("b", OrderState.SUBMITTED, "NVDA"),
                order("c", OrderState.QUEUED, "NVDA"),  # a card, not a fill
                order("d", OrderState.FILLED, "AMD"),
            ]
        )
    with session_scope() as s:
        built = build_sizing_context(now=datetime.now(UTC), session=s, for_send=False)
    assert built is not None and built.csp_fills_by_name == {"NVDA": 2, "AMD": 1}
