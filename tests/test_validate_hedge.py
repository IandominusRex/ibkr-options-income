"""``risk_engine.validate_hedge`` and the clash rules (risk-envelope Task 34; spec §3.10.10 item 4,
§3.10.0, §3.10.6, rulings H3, H5, H6, H9, H10). One test per check; nothing here connects to IBKR."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.schemas import (
    AccountSnapshot,
    HedgeCandidate,
    HedgeContext,
    HedgeLeg,
    OptionRight,
    Strategy,
    TradeCandidate,
)
from src.engine.risk_engine import _INCOME_STRATEGIES, validate_candidates, validate_hedge

NOW = datetime(2026, 11, 18, 16, 0, tzinfo=UTC)
TODAY = date(2026, 11, 18)
EXP = TODAY + timedelta(days=91)
NLV0 = 650_000.0


def leg(action: str = "BUY", strike: float = 560.0, **kw) -> HedgeLeg:
    base = {
        "action": action,
        "strike": strike,
        "expiry": EXP,
        "con_id": 9001 if action == "BUY" else 9002,
        "bid": 5.90 if action == "BUY" else 1.00,
        "ask": 6.10 if action == "BUY" else 1.04,
        "delta": -0.22 if action == "BUY" else -0.05,
        "quoted_at": NOW - timedelta(seconds=5),
    }
    base.update(kw)
    return HedgeLeg(**base)


def cand(*, short: HedgeLeg | None = None, contracts: int = 2, debit: float | None = None, **kw):
    legs = [kw.pop("long", leg())]
    if short is not None:
        legs.append(short)
    d = debit if debit is not None else (6.0 - (1.02 if short else 0.0))
    data = {
        "hedge_id": "h1",
        "order_ref": "hedge:h1",
        "instrument": "QQQ",
        "kind": "vertical" if short else "outright",
        "legs": legs,
        "contracts": contracts,
        "debit": d,
        "max_loss": d * 100 * contracts,
        "spot": 600.0,
        "dte": 91,
    }
    data.update(kw)
    return HedgeCandidate(**data)


def ctx(**kw) -> HedgeContext:
    base = {
        "now": NOW,
        "nlv0": NLV0,
        "months_elapsed": 0.0,
        "vix_close": 18.0,
        "vxn_close": 22.0,
        "vxn_p90": 30.0,
        "book_beta_delta": 1_000_000.0,
        "instrument_beta": 1.1,
    }
    base.update(kw)
    return HedgeContext(**base)


def reasons(c: HedgeCandidate, x: HedgeContext | None = None) -> list[str]:
    return validate_hedge(c, x or ctx()).reasons


def test_a_clean_outright_and_a_clean_vertical_pass() -> None:
    assert reasons(cand()) == []
    assert reasons(cand(short=leg("SELL", 500.0))) == []


# --- H3: the budget caps ------------------------------------------------------------------- #


def test_budget_net_premium_cap() -> None:
    # 1.0% of NLV0 = 6,500; 5,800 already spent + 1,200 is over
    assert "hedge_budget_net" in reasons(cand(), ctx(net_premium_spent=5_800.0, months_elapsed=9))


def test_budget_pace_cap() -> None:
    # month 0: 0.25% x (0 + 2) = 0.5% of NLV0 = 3,250; 2,500 + 1,200 is over
    assert "hedge_budget_pace" in reasons(cand(), ctx(net_premium_spent=2_500.0))
    assert "hedge_budget_pace" not in reasons(
        cand(), ctx(net_premium_spent=2_500.0, months_elapsed=1.0)
    )


def test_budget_open_premium_at_cost_cap() -> None:
    # 0.6% of NLV0 = 3,900; 3,000 open + 1,200 is over
    assert "hedge_budget_open" in reasons(cand(), ctx(open_premium_at_cost=3_000.0))


def test_budget_needs_nlv0() -> None:
    assert "hedge_budget_unmeasured" in reasons(cand(), ctx(nlv0=0.0))


# --- structure ------------------------------------------------------------------------------ #


def test_max_loss_is_the_debit() -> None:
    assert "hedge_max_loss" in reasons(cand(max_loss=50.0))
    assert "hedge_no_debit" in reasons(cand(debit=0.0, max_loss=0.0))


def test_no_naked_short_leg() -> None:
    # a short above the long (a credit structure whose loss exceeds its debit)
    assert "hedge_naked_short" in reasons(cand(short=leg("SELL", 600.0)))
    # a short alone
    assert "hedge_naked_short" in reasons(
        cand(long=leg("SELL", 500.0), kind="outright", debit=1.0, max_loss=200.0)
    )
    # a short of another expiry (a diagonal)
    assert "hedge_naked_short" in reasons(
        cand(short=leg("SELL", 500.0, expiry=EXP + timedelta(days=28)))
    )
    # a call is never a hedge leg
    assert "hedge_not_a_put" in reasons(cand(long=leg(right="C")))


def test_underlying_in_hedge_underlyings() -> None:
    assert "hedge_underlying" in reasons(cand(instrument="SMH"))
    assert "hedge_underlying" not in reasons(cand(instrument="XND"))


# --- the clash rules, both ways ------------------------------------------------------------- #


def test_contract_clash_refuses_a_hedge_in_another_books_contract() -> None:
    assert "hedge_contract_clash" in reasons(cand(), ctx(other_books_con_ids=[9001]))
    key = ("QQQ", "P", 560.0, EXP)
    assert "hedge_contract_clash" in reasons(cand(), ctx(other_books_contracts=[key]))


def _wheel(
    underlying: str, strike: float, expiry: date, strategy=Strategy.CASH_SECURED_PUT
) -> TradeCandidate:
    from tests.test_engine import _candidate

    call = strategy == Strategy.COVERED_CALL
    return _candidate(
        candidate_id=f"{underlying}-{strike}",
        strategy=strategy,
        underlying=underlying,
        right=OptionRight.CALL if call else OptionRight.PUT,
        delta=0.20 if call else -0.20,
    ).model_copy(update={"strike": strike, "expiry": expiry})


ACCOUNT = AccountSnapshot(
    account="DU1",
    net_liquidation=650_000.0,
    total_cash=400_000.0,
    buying_power=1_000_000.0,
    maintenance_margin=50_000.0,
    excess_liquidity=500_000.0,
)


def _hedge_reasons(c: TradeCandidate) -> list[str]:
    (v,) = validate_candidates([c], ACCOUNT, [])
    return [r for r in v.reasons if r.startswith("hedge")]


def test_contract_clash_refuses_a_wheel_short_in_a_hedge_contract(hedge_db) -> None:
    from tests.test_hedge_book import hedge_candidate, seed_open_hedge

    seed_open_hedge(hedge_candidate(instrument="QQQ", strike=560.0))
    assert "hedge_contract_clash" in _hedge_reasons(_wheel("QQQ", 560.0, date(2027, 2, 19)))


def test_qqq_route_refuses_a_wheel_qqq_open_while_a_qqq_hedge_is_open(hedge_db) -> None:
    from tests.test_hedge_book import hedge_candidate, seed_open_hedge

    assert _hedge_reasons(_wheel("QQQ", 540.0, EXP)) == []
    seed_open_hedge(hedge_candidate(instrument="QQQ", strike=560.0))
    assert "hedge_qqq_route" in _hedge_reasons(_wheel("QQQ", 540.0, EXP))
    assert "hedge_qqq_route" in _hedge_reasons(
        _wheel("QQQ", 640.0, EXP, strategy=Strategy.COVERED_CALL)
    )
    assert _hedge_reasons(_wheel("AAPL", 200.0, EXP)) == []


def test_an_xnd_hedge_never_blocks_a_wheel_qqq_open(hedge_db) -> None:
    from tests.test_hedge_book import hedge_candidate, seed_open_hedge

    seed_open_hedge(hedge_candidate(instrument="XND", strike=240.0, con_id=7001))
    assert _hedge_reasons(_wheel("QQQ", 540.0, EXP)) == []


def test_qqq_route_refuses_the_hedge_while_the_wheel_holds_qqq() -> None:
    assert "hedge_qqq_route" in reasons(cand(), ctx(wheel_underlyings=["QQQ"]))
    assert "hedge_qqq_route" not in reasons(cand(instrument="XND"), ctx(wheel_underlyings=["QQQ"]))


# --- H5 windows; the quote ------------------------------------------------------------------ #


def test_dte_window() -> None:
    assert "hedge_dte_window" in reasons(cand(dte=40))
    assert "hedge_dte_window" in reasons(cand(dte=130))
    assert "hedge_dte_window" not in reasons(cand(dte=60))


def test_delta_window() -> None:
    assert "hedge_delta_window" in reasons(cand(long=leg(delta=-0.10)))
    assert "hedge_delta_window" in reasons(cand(long=leg(delta=-0.35)))
    assert "hedge_delta_window" in reasons(cand(long=leg(delta=None)))


def test_quote_within_eight_percent_of_mid() -> None:
    assert "hedge_quote_wide" in reasons(cand(long=leg(bid=5.0, ask=6.0)))  # 18% of mid


def test_quote_two_sided_and_fresh() -> None:
    assert "hedge_quote_one_sided" in reasons(cand(long=leg(bid=None)))
    assert "hedge_quote_stale" in reasons(cand(long=leg(quoted_at=NOW - timedelta(minutes=5))))
    assert "hedge_quote_stale" in reasons(cand(long=leg(quoted_at=None)))


# --- H6: the stress block and the self-funding carve-out ------------------------------------ #


def test_stress_block_on_vix_close() -> None:
    assert "hedge_stress_block" in reasons(cand(), ctx(vix_close=25.0))


def test_stress_block_on_vxn_percentile() -> None:
    assert "hedge_stress_block" in reasons(cand(), ctx(vxn_close=31.0, vxn_p90=30.0))


def test_stress_unknown_fails_closed() -> None:
    assert "hedge_stress_unmeasured" in reasons(cand(), ctx(vix_close=None))


def test_a_missing_vxn_close_or_p90_fails_closed_for_an_opening() -> None:
    # Review fix 1: fewer than 126 stored ^VXN closes means no p90, and that is "unmeasured", not "fine"
    assert "hedge_stress_unmeasured" in reasons(cand(), ctx(vxn_p90=None))
    assert "hedge_stress_unmeasured" in reasons(cand(), ctx(vxn_close=None))
    assert reasons(cand(), ctx(vxn_close=22.0, vxn_p90=30.0)) == []  # known and below: passes


def test_a_missing_vxn_p90_does_not_stop_a_self_funding_roll() -> None:
    roll = cand(roll_of="h0", roll_proceeds=1_300.0, roll_contracts=2)
    assert reasons(roll, ctx(vxn_p90=None)) == []


def test_a_self_funding_roll_passes_the_stress_block() -> None:
    roll = cand(roll_of="h0", roll_proceeds=1_300.0, roll_contracts=2)  # cost 1,200 <= 1,300
    assert reasons(roll, ctx(vix_close=30.0)) == []
    more = cand(contracts=3, roll_of="h0", roll_proceeds=5_000.0, roll_contracts=2)
    assert "hedge_stress_block" in reasons(more, ctx(vix_close=30.0))  # adds contracts
    dearer = cand(roll_of="h0", roll_proceeds=1_000.0, roll_contracts=2)
    assert "hedge_stress_block" in reasons(dearer, ctx(vix_close=30.0))  # net debit > 0


def test_halt_and_slow_breaker_block_new_size() -> None:
    assert "hedge_halted" in reasons(cand(), ctx(halted=True))
    assert "hedge_slow_breaker" in reasons(cand(), ctx(slow_breaker_tripped=True))
    roll = cand(roll_of="h0", roll_proceeds=1_300.0, roll_contracts=2)
    assert reasons(roll, ctx(halted=True, slow_breaker_tripped=True)) == []


# --- delta cap, live, refs, scope ----------------------------------------------------------- #


def test_hedge_delta_at_most_half_the_book_beta_delta() -> None:
    # one contract: 0.22 x 100 x 600 x 1.1 = 14,520 SPY-dollars of short delta
    assert "hedge_delta_cap" in reasons(cand(contracts=2), ctx(book_beta_delta=50_000.0))
    assert "hedge_delta_cap" not in reasons(cand(contracts=2), ctx(book_beta_delta=60_000.0))
    # open hedges count
    assert "hedge_delta_cap" in reasons(
        cand(contracts=2), ctx(book_beta_delta=60_000.0, hedge_beta_delta=-5_000.0)
    )
    assert "hedge_book_delta_unmeasured" in reasons(cand(), ctx(book_beta_delta=None))


def test_hedge_claude_refs_are_refused_and_under_live_trading_named() -> None:
    assert "hedge_claude_reserved" in reasons(cand(order_ref="hedge:claude:c1"))
    live = reasons(cand(order_ref="hedge:claude:c1"), ctx(is_live=True))
    assert {"hedge_claude_reserved", "hedge_claude_live", "hedge_paper_only"} <= set(live)


def test_every_hedge_order_is_refused_in_live() -> None:
    assert "hedge_paper_only" in reasons(cand(), ctx(is_live=True))
    close = cand(intent="close", closes="h0", debit=-5.0, max_loss=0.0)
    assert "hedge_paper_only" in reasons(close, ctx(is_live=True, held_contracts={"h0": 2}))
    assert "hedge_bad_ref" in reasons(cand(order_ref="value:1"))


def test_scoped_out_of_the_income_gates() -> None:
    """A hedge pays premium: it has no ROC, yield, IV-rank, IV/RV or min_credit floor."""
    assert Strategy.HEDGE not in _INCOME_STRATEGIES
    r = reasons(cand())
    for income in ("roc_below_minimum", "yield_below_minimum", "premium_below_fair_value"):
        assert income not in r


def test_a_close_never_sells_more_than_the_book_holds() -> None:
    close = cand(intent="close", closes="h0", debit=-5.0, max_loss=0.0, contracts=3)
    assert "hedge_close_exceeds_held" in reasons(close, ctx(held_contracts={"h0": 2}))
    ok = cand(intent="close", closes="h0", debit=-5.0, max_loss=0.0, contracts=2)
    # a close is risk-reducing: no budget, stress, halt, window or spread check
    assert reasons(ok, ctx(held_contracts={"h0": 2}, vix_close=40.0, halted=True)) == []


@pytest.mark.parametrize("bad", [0, -1])
def test_no_contracts(bad: int) -> None:
    assert "no_contracts" in reasons(cand(contracts=max(bad, 0)))
