from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.config import get_config
from src.common.schemas import ChainOption, ChainSnapshot
from src.spreads.gex import (
    build_levels,
    expected_move,
    gamma_flip,
    net_gex,
    regime_at,
    strike_gex,
    walls,
)
from src.spreads.pricing import gamma, years_to_close

NOW = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)  # 10:00 EDT
TODAY = date(2026, 10, 7)
TOMORROW = date(2026, 10, 8)


def _o(strike, right, oi, *, iv=0.40, expiry=TOMORROW, bid=None, ask=None) -> ChainOption:
    return ChainOption(
        strike=strike, right=right, expiry=expiry, open_interest=oi, iv=iv, bid=bid, ask=ask
    )


def test_calls_add_and_puts_subtract() -> None:
    per = strike_gex([_o(100, "C", 1000, iv=0.15), _o(100, "P", 400, iv=0.15)], 100.0, NOW)
    g = gamma(100, 100, years_to_close(NOW, TOMORROW), 0.15)
    assert per[100.0] == pytest.approx(g * 600 * 100 * 100 * 100 * 0.01)


def test_options_without_oi_or_iv_are_ignored() -> None:
    no_iv = ChainOption(strike=101, right="C", expiry=TOMORROW, open_interest=50)
    assert strike_gex([_o(100, "C", 0), no_iv], 100.0, NOW) == {}


def test_walls_pick_the_largest_magnitude_on_each_side_of_spot() -> None:
    assert walls({95: -5, 98: -10, 100: 1, 102: 8, 105: 3}, 100.0) == (102, 98)
    assert walls({}, 100.0) == (None, None)


def test_flip_sits_between_a_put_heavy_floor_and_a_call_heavy_ceiling() -> None:
    opts = [_o(97, "P", 5000), _o(103, "C", 5000)]
    assert net_gex(opts, 97.5, NOW) < 0 < net_gex(opts, 102.5, NOW)
    flip = gamma_flip(opts, 100.0, NOW, 0.03)
    assert flip is not None and 97 < flip < 103


def test_flip_is_none_when_gamma_never_changes_sign() -> None:
    assert gamma_flip([_o(100, "C", 5000)], 100.0, NOW, 0.03) is None


def test_expected_move_is_the_atm_straddle_nearest_spot() -> None:
    opts = [
        _o(690, "C", 1, expiry=TODAY, bid=2.9, ask=3.1),
        _o(690, "P", 1, expiry=TODAY, bid=2.7, ask=2.9),
        _o(695, "C", 1, expiry=TODAY, bid=1.0, ask=1.2),
        _o(695, "P", 1, expiry=TODAY, bid=5.0, ask=5.4),
    ]
    assert expected_move(opts, 690.4, TODAY, 1.0) == pytest.approx(5.8)
    assert expected_move(opts, 690.4, TOMORROW, 1.0) is None


def _spx_chain() -> ChainSnapshot:
    return ChainSnapshot(
        symbol="SPX",
        spot=6900.0,
        as_of=NOW,
        options=[_o(6800, "P", 40_000, expiry=TODAY), _o(7000, "C", 40_000, expiry=TODAY)],
    )


def _xsp_chain() -> ChainSnapshot:
    return ChainSnapshot(
        symbol="XSP",
        spot=690.0,
        as_of=NOW,
        options=[
            _o(690, "C", 10, expiry=TODAY, bid=2.9, ask=3.1),
            _o(690, "P", 10, expiry=TODAY, bid=2.7, ask=2.9),
        ],
    )


def test_build_levels_scales_spx_levels_into_xsp_units() -> None:
    levels = build_levels(_spx_chain(), _xsp_chain(), get_config().spreads, NOW)
    assert levels.put_wall == pytest.approx(680.0)
    assert levels.call_wall == pytest.approx(700.0)
    assert levels.flip is not None and 680.0 < levels.flip < 700.0
    assert levels.expected_move == pytest.approx(5.8)
    assert levels.spot == 690.0
    assert levels.regime in ("positive", "negative")


def test_build_levels_with_no_oi_is_unknown_regime() -> None:
    empty = ChainSnapshot(symbol="SPX", spot=6900.0, as_of=NOW, options=[])
    levels = build_levels(empty, _xsp_chain(), get_config().spreads, NOW)
    assert levels.regime == "unknown" and levels.put_wall is None and levels.flip is None


def test_regime_at_follows_spot_between_the_walls() -> None:
    assert regime_at(_spx_chain(), 681.0, 0.1, NOW) == "negative"
    assert regime_at(_spx_chain(), 699.0, 0.1, NOW) == "positive"


def test_build_levels_uses_the_live_spy_spx_ratio() -> None:
    cfg = get_config().spreads  # gex.scale_to_underlying: null → live ratio
    spy = _xsp_chain().model_copy(update={"symbol": "SPY", "spot": 686.55})  # SPY trails SPX/10
    levels = build_levels(_spx_chain(), spy, cfg, NOW)
    assert levels.scale == pytest.approx(686.55 / 6900.0)
    assert levels.put_wall == pytest.approx(6800.0 * 686.55 / 6900.0)
    pinned = cfg.model_copy(update={"gex": cfg.gex.model_copy(update={"scale_to_underlying": 0.1})})
    assert build_levels(_spx_chain(), spy, pinned, NOW).put_wall == pytest.approx(680.0)
