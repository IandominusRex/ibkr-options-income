"""The pure shock engine (risk-envelope plan Task 11; spec §3.4.1-3.4.3, rulings H1, H10, P5, P6).

Full Black-Scholes revaluation, gross (no long option from any source) and net, U_ew, and
fail-closed on a missing input.
"""

from __future__ import annotations

import ast
import math
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from src.analytics import shock
from src.analytics.black_scholes import bs_delta, bs_price
from src.common.envelope_types import BookLine, ShockInputs

ROOT = Path(__file__).resolve().parents[1]
NLV = 100_000.0


def _inputs(*lines: BookLine, **kw) -> ShockInputs:
    base = dict(
        lines=tuple(lines),
        betas={"AMD": 1.5, "NVDA": 1.8, "KO": 0.5, "QQQ": 1.2, "SOXX": 1.6, "SPY": 1.0},
        betas_smh={"NVDA": 1.1, "SOXX": 1.0, "AMD": 1.2},
        leverage={"TQQQ": 3, "SOXL": 3},
        governing={"TQQQ": "QQQ", "SOXL": "SOXX"},
        tech_linked=frozenset({"NVDA", "AMD", "QQQ", "TQQQ"}),
        semis=frozenset({"NVDA", "AMD", "SOXX", "SOXL"}),
        nlv=NLV,
    )
    base.update(kw)
    return ShockInputs(**base)  # type: ignore[arg-type]


def _stock(sym: str, qty: float, spot: float, book: str = "wheel") -> BookLine:
    return BookLine(symbol=sym, kind="stock", qty=qty, spot=spot, book=book)


def _opt(kind, sym="NVDA", *, qty=1.0, spot=105.0, strike=100.0, dte=30, iv=0.40, book="wheel"):
    return BookLine(
        symbol=sym, kind=kind, qty=qty, spot=spot, strike=strike, dte=dte, iv=iv, book=book
    )


def test_stock_loses_beta_times_ten_percent() -> None:
    res = shock.measure(_inputs(_stock("AMD", 100, 200.0)))
    # 100 x $200 x 1.5 x 10% = $3,000 of $100k
    assert res.s10 == pytest.approx(3.0)
    assert res.s20 == pytest.approx(6.0)
    assert res.measured


def test_a_leveraged_etf_moves_at_leverage_times_its_index_beta() -> None:
    inp = _inputs(_stock("TQQQ", 100, 50.0), betas={"TQQQ": 2.0, "QQQ": 1.2})
    assert shock.name_move("TQQQ", -0.10, inp, scenario="S10") == pytest.approx(-0.36)
    # its own beta (2.0) is not what moves it: 3 x 1.2 x 10% of $5,000
    assert shock.measure(inp).s10 == pytest.approx(5_000 * 0.36 / NLV * 100)


def test_a_leveraged_move_is_capped_at_minus_100() -> None:
    inp = _inputs(_stock("SOXL", 100, 50.0), betas={"SOXX": 2.0})
    assert shock.name_move("SOXL", -0.20, inp, scenario="S20") == -1.0  # 3 x 2.0 x 20% = 120%
    assert shock.measure(inp).s20 == pytest.approx(5.0)  # the whole $5,000, no more


def test_a_short_put_is_fully_revalued() -> None:
    put = _opt("short_put", "SPY", spot=105.0, strike=100.0, dte=30, iv=0.40)
    res = shock.measure(_inputs(put))
    now = bs_price(105.0, 100.0, 30, 0.40, "P")
    new = bs_price(94.5, 100.0, 30, 0.40, "P")
    assert now is not None and new is not None
    assert res.s10 == pytest.approx((new - now) * 100 / NLV * 100)


def test_a_covered_call_protects_only_its_premium() -> None:
    """Spec §2.4: in a -10% index move a call's protection is bounded by its premium, far less
    than a delta-linear measure claims."""
    spot, strike, dte, iv = 100.0, 108.0, 30, 0.35
    call = _opt("short_call", "SPY", spot=spot, strike=strike, dte=dte, iv=iv)
    gain = shock.line_pnl(call, -0.10)
    premium = (bs_price(spot, strike, dte, iv, "C") or 0.0) * 100
    delta = bs_delta(spot, strike, dte, iv, "C") or 0.0
    linear = delta * 100 * spot * 0.10
    assert gain is not None and 0 < gain <= premium
    assert gain < 0.8 * linear
    alone = shock.measure(_inputs(_stock("SPY", 100, spot)))
    covered = shock.measure(_inputs(_stock("SPY", 100, spot), call))
    assert alone.s10 - covered.s10 == pytest.approx(gain / NLV * 100)


def test_gross_ignores_every_long_option() -> None:
    """H1/H10: no long option, whoever bought it, changes any gross measure or U_ew."""
    book = (_stock("AMD", 100, 200.0), _opt("short_put", "NVDA", strike=100.0, spot=105.0))
    longs = (
        _opt("long_put", "SPY", qty=5, spot=600.0, strike=560.0, dte=90, iv=0.2, book="hedge"),
        _opt("long_put", "QQQ", qty=2, spot=500.0, strike=470.0, dte=60, iv=0.25, book="claude"),
        _opt("long_call", "AMD", qty=1, spot=200.0, strike=210.0, dte=30, iv=0.5, book="manual"),
        _opt("long_put", "AMD", qty=3, spot=200.0, strike=190.0, dte=45, iv=None, book="manual"),
    )
    plain = shock.measure(_inputs(*book))
    hedged = shock.measure(_inputs(*book, *longs))
    for field in ("s10", "s20", "g10", "p20", "t20", "s_smh", "s10_vol10", "uew"):
        assert getattr(hedged, field) == pytest.approx(getattr(plain, field)), field
    assert hedged.unmeasured == plain.unmeasured == ()  # a long put's missing IV is not gross's


def test_net_counts_long_options() -> None:
    book = _stock("SPY", 1_000, 600.0)
    hedge = _opt("long_put", "SPY", qty=5, spot=600.0, strike=570.0, dte=90, iv=0.2, book="hedge")
    res = shock.measure(_inputs(book, hedge))
    assert res.s10_net < res.s10
    assert res.s20_net < res.s20
    # the long put with no IV is named for the net measures only
    blind = replace(hedge, iv=None)
    res2 = shock.measure(_inputs(book, blind))
    assert res2.unmeasured == () and res2.unmeasured_net == ("SPY",)


def test_t20_moves_tech_linked_twenty_percent() -> None:
    inp = _inputs()
    assert shock.name_move("NVDA", -0.20, inp, scenario="T20") == pytest.approx(-0.20)
    assert shock.name_move("KO", -0.20, inp, scenario="T20") == pytest.approx(0.5 * -0.05)
    assert shock.name_move("TQQQ", -0.20, inp, scenario="T20") == pytest.approx(-0.60)
    # SOXL is not tech_linked here: leverage x SOXX beta x -5%
    assert shock.name_move("SOXL", -0.20, inp, scenario="T20") == pytest.approx(3 * 1.6 * -0.05)


def test_s_smh_uses_smh_betas_for_semis() -> None:
    inp = _inputs()
    assert shock.name_move("NVDA", -0.30, inp, scenario="S_SMH") == pytest.approx(1.1 * -0.30)
    assert shock.name_move("KO", -0.30, inp, scenario="S_SMH") == pytest.approx(0.5 * -0.08)
    assert shock.name_move("SOXL", -0.30, inp, scenario="S_SMH") == pytest.approx(-0.90)
    assert shock.name_move("TQQQ", -0.30, inp, scenario="S_SMH") == pytest.approx(3 * 1.2 * -0.08)


def test_p20_compounds_leveraged_daily() -> None:
    inp = _inputs(betas={"SPY": 1.0})
    step = math.exp(math.log(0.8) / 10) - 1
    lev_move = shock.name_move("TQQQ", -0.20, _inputs(), scenario="P20")
    assert lev_move == pytest.approx((1 + 3 * step) ** 10 - 1)
    assert lev_move != pytest.approx(-0.60)  # daily reset, not 3 x the path's -20%
    assert shock.name_move("SPY", -0.20, inp, scenario="P20") == pytest.approx(-0.20)
    # options are repriced ten days nearer expiry
    put = _opt("short_put", "SPY", spot=105.0, strike=100.0, dte=30, iv=0.40)
    loss, _ = shock.scenario_loss(_inputs(put), "P20", include_long=False)
    now = bs_price(105.0, 100.0, 30, 0.40, "P") or 0.0
    new = bs_price(105.0 * 0.8, 100.0, 20, 0.40, "P") or 0.0
    assert loss == pytest.approx((new - now) * 100 / NLV * 100)


def test_vol_plus_ten_raises_short_put_loss() -> None:
    res = shock.measure(_inputs(_opt("short_put", "NVDA", strike=100.0, spot=105.0)))
    assert res.s10_vol10 > res.s10 > 0


def test_uew_counts_stock_and_put_strike_at_leverage() -> None:
    lines = (
        _stock("AMD", 100, 200.0),  # 20,000
        _stock("TQQQ", 100, 50.0),  # 5,000 x 3
        _opt("short_put", "SOXL", strike=20.0, spot=22.0),  # 2,000 x 3
        _opt("short_put", "NVDA", qty=2, strike=150.0, spot=140.0),  # ITM: at strike, 30,000
        _stock("KO", 50, 60.0, book="value"),  # 3,000, the value book's line
    )
    assert shock.uew(_inputs(*lines)) == pytest.approx(
        (20_000 + 15_000 + 6_000 + 30_000 + 3_000) / NLV
    )


def test_uew_ignores_long_options() -> None:
    book = (_stock("AMD", 100, 200.0),)
    extra = (
        _opt("long_put", "AMD", strike=190.0, spot=200.0, book="hedge"),
        _opt("long_call", "AMD", strike=210.0, spot=200.0, book="manual"),
        _opt("short_call", "AMD", strike=220.0, spot=200.0),
    )
    assert shock.uew(_inputs(*book, *extra)) == pytest.approx(shock.uew(_inputs(*book)))


def test_a_missing_iv_is_unmeasured_not_zero() -> None:
    blind = _opt("short_put", "NVDA", iv=None)
    assert shock.line_pnl(blind, -0.18) is None
    res = shock.measure(_inputs(_stock("AMD", 100, 200.0), blind))
    assert "NVDA" in res.unmeasured and not res.measured
    # a missing beta, a missing spot and an unknown NLV are unmeasured too
    assert "ZZZ" in shock.measure(_inputs(_stock("ZZZ", 10, 5.0))).unmeasured
    assert "AMD" in shock.measure(_inputs(_stock("AMD", 10, 0.0))).unmeasured
    assert "NLV" in shock.measure(_inputs(_stock("AMD", 10, 5.0), nlv=0.0)).unmeasured


def test_no_io() -> None:
    """Structural: the engine and its types import only the standard library and each other."""
    allowed = {"src.common.envelope_types", "src.analytics.black_scholes"}
    for rel in ("src/analytics/shock.py", "src/common/envelope_types.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, rel
                names = [node.module or ""]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                assert top in sys.stdlib_module_names or name in allowed, f"{rel} -> {name}"
