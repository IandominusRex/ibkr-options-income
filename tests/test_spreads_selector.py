from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption, ChainSnapshot, GexLevels
from src.spreads.selector import refresh_candidate, select_candidates, short_boundary

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)  # 10:30 EDT
TODAY = date(2026, 10, 7)
_BASE = get_config().spreads
# Pinned explicitly so a YAML retune never silently changes these tests: width 5, delta cap 0.15,
# min credit 10% of width (0.50), wall buffer 0.1%, expected-move multiple 1.0.
CFG = _BASE.model_copy(
    update={
        "selection": _BASE.selection.model_copy(
            update={
                "width": 5.0,
                "short_delta_max": 0.15,
                "min_credit_pct_of_width": 0.10,
                "wall_buffer_pct": 0.001,
                "em_multiple": 1.0,
            }
        )
    }
)


def q(strike: float, right: str, bid: float | None, ask: float | None, delta: float | None = None):
    return ChainOption(
        strike=strike,
        right=right,
        expiry=TODAY,
        bid=bid,
        ask=ask,
        delta=delta,
        con_id=int(strike * 10) + (1 if right == "C" else 0),
    )


def levels(**kw) -> GexLevels:
    base = dict(
        as_of=NOW,
        spot=690.0,
        net_gex=1e9,
        regime="positive",
        flip=680.0,
        call_wall=700.0,
        put_wall=680.0,
        expected_move=6.0,
    )
    base.update(kw)
    return GexLevels(**base)


def chain(*opts: ChainOption) -> ChainSnapshot:
    return ChainSnapshot(symbol="XSP", spot=690.0, as_of=NOW, options=list(opts))


def test_put_boundary_is_below_both_the_expected_move_and_the_wall() -> None:
    assert short_boundary("put", levels(), CFG) == pytest.approx(680.0 - 0.69)
    assert short_boundary("put", levels(put_wall=687.0), CFG) == pytest.approx(684.0)
    assert short_boundary("call", levels(), CFG) == pytest.approx(700.0 + 0.69)
    assert short_boundary("put", levels(expected_move=None), CFG) is None


def test_picks_the_closest_put_and_call_beyond_the_zone() -> None:
    got = select_candidates(
        chain(
            q(680, "P", 1.10, 1.20, -0.16),  # inside the boundary — never considered
            q(679, "P", 0.80, 0.86, -0.12),
            q(674, "P", 0.20, 0.24, -0.04),
            q(701, "C", 0.70, 0.76, 0.11),
            q(706, "C", 0.14, 0.18, 0.03),
        ),
        levels(),
        CFG,
        NOW,
    )
    put, call = sorted(got, key=lambda c: c.side, reverse=True)
    assert (put.side, put.short_strike, put.long_strike) == ("put", 679, 674)
    assert put.credit_mid == pytest.approx(0.61)
    assert put.credit_natural == pytest.approx(0.56)
    assert put.short_con_id == 6790 and put.long_con_id == 6740
    assert (call.side, call.short_strike, call.long_strike) == ("call", 701, 706)
    assert call.credit_mid == pytest.approx(0.57)


def test_a_short_over_the_delta_cap_is_skipped_for_the_next_strike() -> None:
    (c,) = select_candidates(
        chain(
            q(679, "P", 0.80, 0.86, -0.20),
            q(674, "P", 0.20, 0.24),
            q(678, "P", 0.70, 0.76, -0.11),
            q(673, "P", 0.18, 0.22),
        ),
        levels(),
        CFG.model_copy(update={"selection": CFG.selection.model_copy(update={"sides": ["put"]})}),
        NOW,
    )
    assert (c.short_strike, c.long_strike) == (678, 673)


def test_a_missing_long_leg_moves_to_the_next_strike() -> None:
    (c,) = select_candidates(
        chain(
            q(679, "P", 0.80, 0.86, -0.12),
            q(678, "P", 0.70, 0.76, -0.11),
            q(673, "P", 0.18, 0.22),
        ),
        levels(),
        CFG,
        NOW,
    )
    assert c.short_strike == 678


def test_walk_stops_once_the_credit_is_too_thin() -> None:
    got = select_candidates(
        chain(
            q(679, "P", 0.40, 0.44, -0.08),
            q(674, "P", 0.10, 0.14),
            q(678, "P", 0.35, 0.39, -0.07),
            q(673, "P", 0.08, 0.12),
        ),
        levels(),
        CFG,
        NOW,
    )
    assert got == []


def test_no_expected_move_means_no_candidates() -> None:
    got = select_candidates(
        chain(q(679, "P", 0.80, 0.86, -0.12), q(674, "P", 0.20, 0.24)),
        levels(expected_move=None),
        CFG,
        NOW,
    )
    assert got == []


def test_the_triggered_side_limits_the_walk() -> None:
    both = chain(
        q(679, "P", 0.80, 0.86, -0.12),
        q(674, "P", 0.20, 0.24, -0.04),
        q(701, "C", 0.70, 0.76, 0.11),
        q(706, "C", 0.14, 0.18, 0.03),
    )
    (c,) = select_candidates(both, levels(), CFG, NOW, sides=["call"])
    assert c.side == "call"
    assert select_candidates(both, levels(), CFG, NOW, sides=[]) == []


def test_refresh_reprices_on_fresh_quotes_and_keeps_the_id() -> None:
    (c,) = select_candidates(
        chain(q(679, "P", 0.80, 0.86, -0.12), q(674, "P", 0.20, 0.24)), levels(), CFG, NOW
    )
    later = datetime(2026, 10, 7, 14, 31, tzinfo=UTC)
    fresh = refresh_candidate(c, q(679, "P", 0.70, 0.74, -0.10), q(674, "P", 0.18, 0.22), later)
    assert fresh is not None
    assert fresh.spread_id == c.spread_id
    assert fresh.credit_mid == pytest.approx(0.52) and fresh.quote_time == later
    assert refresh_candidate(c, q(679, "P", 0.70, 0.74), q(674, "P", 0.18, None), later) is None
