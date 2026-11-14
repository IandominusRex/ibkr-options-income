from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import GexLevels, SpreadCandidate
from src.spreads.menu import breakeven, build_menu, round_trip_cost

NOW = datetime(2026, 10, 7, 15, 5, tzinfo=UTC)
_BASE = get_config().spreads
CFG = _BASE.model_copy(
    update={
        "execution": _BASE.execution.model_copy(
            update={
                "shadow_slippage_per_leg": 0.02,
                "slippage_margin_per_leg": 0.0,  # 0.02 a leg all told: the mechanics, pinned
                "commission_per_contract": 0.65,
            }
        ),
        "exits": _BASE.exits.model_copy(
            update={"profit_take_pct": 50.0, "stop_debit_multiple": 2.0}
        ),
    }
)
LEVELS = GexLevels(
    as_of=NOW,
    spot=663.05,
    net_gex=1.9e9,
    regime="positive",
    flip=660.8,
    put_wall=655.0,
    call_wall=672.0,
    expected_move=6.7,
)


def cand(side: str, short: float, long: float, credit: float) -> SpreadCandidate:
    return SpreadCandidate(
        spread_id=f"{side}{short:g}",
        side=side,
        expiry=date(2026, 10, 7),
        short_strike=short,
        long_strike=long,
        width=5.0,
        credit_mid=credit,
        credit_natural=credit - 0.04,
        short_delta=-0.14 if side == "put" else 0.12,
        spot=663.05,
        quote_time=NOW,
    )


def test_round_trip_cost_is_four_legs_of_slippage_and_commission() -> None:
    assert round_trip_cost(CFG) == pytest.approx(4 * 0.02 + 4 * 0.65 / 100)  # 0.106


def test_breakeven_needs_a_positive_win() -> None:
    assert breakeven(1.0, 3.0) == pytest.approx(0.75)
    assert breakeven(0.0, 3.0) is None and breakeven(-0.1, 3.0) is None


def test_items_carry_both_break_evens_and_their_distances() -> None:
    (a,) = build_menu([(cand("put", 656, 651, 0.42), "baseline", 22)], LEVELS, CFG)
    assert (a.letter, a.position, a.contracts) == ("A", "baseline", 22)
    assert a.credit_after_costs == pytest.approx(0.42 - 0.106)
    assert a.cost_pct_of_credit == pytest.approx(0.106 / 0.42, abs=1e-4)
    assert a.max_loss_per_contract_usd == pytest.approx(458.0)
    assert a.dist_spot_pts == pytest.approx(7.05)
    assert a.dist_em_multiple == pytest.approx(7.05 / 6.7, abs=0.01)
    assert a.beyond_wall_pts == pytest.approx(-1.0)  # one point ABOVE the 655 put wall
    assert a.dist_flip_pts == pytest.approx(4.8)  # 656 is 4.8 below the 660.8 flip: OTM side
    # full loss: win 0.314, loss 4.686; exits: win 0.21 - 0.106, loss 0.42 + 0.106
    assert a.be_full_loss == pytest.approx(4.686 / 5.0, abs=1e-4)
    assert a.be_nominal_exits == pytest.approx(0.526 / 0.63, abs=1e-4)


def test_costs_above_the_profit_take_leave_no_nominal_break_even() -> None:
    (a,) = build_menu([(cand("put", 650, 645, 0.20), "outer", 1)], LEVELS, CFG)
    assert a.be_nominal_exits is None  # 50% of 0.20 = 0.10 < 0.106 costs: no win possible


def test_letters_run_puts_first_then_calls_closest_to_spot_first() -> None:
    menu = build_menu(
        [
            (cand("call", 674, 679, 0.30), "baseline", 1),
            (cand("put", 654, 649, 0.29), "outer", 1),
            (cand("put", 657, 652, 0.55), "inside", 1),
            (cand("put", 656, 651, 0.42), "baseline", 1),
        ],
        LEVELS,
        CFG,
    )
    assert [(i.letter, i.candidate.side, i.candidate.short_strike) for i in menu] == [
        ("A", "put", 657),
        ("B", "put", 656),
        ("C", "put", 654),
        ("D", "call", 674),
    ]


def test_flip_distance_is_signed_toward_the_otm_side_and_none_without_a_flip() -> None:
    put, call = build_menu(
        [(cand("put", 662, 657, 0.5), "baseline", 1), (cand("call", 670, 675, 0.4), "outer", 1)],
        LEVELS,
        CFG,
    )
    assert put.dist_flip_pts == pytest.approx(-1.2)  # 662 is ABOVE the 660.8 flip: inside it
    assert call.dist_flip_pts == pytest.approx(9.2)  # 670 is 9.2 above the flip
    (a,) = build_menu(
        [(cand("put", 656, 651, 0.42), "baseline", 1)],
        LEVELS.model_copy(update={"flip": None}),
        CFG,
    )
    assert a.dist_flip_pts is None


def test_a_menu_larger_than_four_per_side_keeps_every_item() -> None:
    items = [(cand("put", 660 - k, 655 - k, 0.4), "outer", 1) for k in range(6)]
    items += [(cand("call", 666 + k, 671 + k, 0.4), "outer", 1) for k in range(6)]
    menu = build_menu(items, LEVELS, CFG)
    assert [i.letter for i in menu] == list("ABCDEFGHIJKL")
