"""The shock engine's inputs (risk-envelope plan Task 12; rulings P5, H7, C7).

Blume betas from ``price_history``, the stored-IV read that skips flagged rows, and the
position -> ``BookLine`` builder that counts the value book once.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from src.analytics import shock_inputs as si
from src.common.schemas import OptionRight, PositionSnapshot
from src.storage.price_history import Bar, append_bars

START = date(2025, 1, 1)


def _series(n: int, rets: list[float], start_px: float = 100.0) -> list[Bar]:
    bars, px = [], start_px
    for i in range(n):
        if i:
            px *= math.exp(rets[i - 1])
        d = START + timedelta(days=i)
        bars.append(Bar(d, px, px, px, px, 1_000.0))
    return bars


def _bench(n: int, seed: int = 7) -> list[float]:
    rnd = random.Random(seed)
    return [rnd.gauss(0.0, 0.01) for _ in range(n)]


def test_blume_beta_from_price_history(db) -> None:
    spy = _bench(260)
    append_bars("SPY", _series(261, spy))
    append_bars("AMD", _series(261, [2.0 * r for r in spy]))  # raw beta exactly 2.0
    out, flagged = si.betas(["AMD", "SPY"])
    assert out["AMD"] == pytest.approx(0.67 * 2.0 + 0.33)
    assert out["SPY"] == pytest.approx(1.0)
    assert flagged == set()


def test_short_history_falls_back_and_flags(db) -> None:
    spy = _bench(260)
    append_bars("SPY", _series(261, spy))
    append_bars("NEWCO", _series(100, [1.2 * r for r in spy[-99:]]))
    out, flagged = si.betas(["NEWCO"])
    assert out["NEWCO"] == 1.5 and flagged == {"NEWCO"}
    out2, flagged2 = si.betas(["NOBARS"])
    assert out2["NOBARS"] == 1.5 and flagged2 == {"NOBARS"}


def test_soxx_uses_smh_until_it_has_history(db) -> None:
    spy = _bench(260)
    append_bars("SPY", _series(261, spy))
    append_bars("SMH", _series(261, [1.5 * r for r in spy]))
    append_bars("SOXX", _series(30, [1.7 * r for r in spy[-29:]]))
    out, flagged = si.betas(["SOXX"])
    assert out["SOXX"] == pytest.approx(0.67 * 1.5 + 0.33) and flagged == set()
    # once SOXX has enough history of its own, its own beta is used
    append_bars("SOXX", _series(261, [1.7 * r for r in spy]))
    out2, _ = si.betas(["SOXX"])
    assert out2["SOXX"] != pytest.approx(out["SOXX"])


def _stk(sym: str, qty: float, px: float) -> PositionSnapshot:
    return PositionSnapshot(symbol=sym, sec_type="STK", position=qty, avg_cost=px, market_price=px)


def _put(
    sym: str, strike: float, *, con_id: int, qty: float = -1, dte: int = 30
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=f"{sym} P{strike}",
        sec_type="OPT",
        position=qty,
        avg_cost=1.0,
        right=OptionRight.PUT,
        strike=strike,
        expiry=date(2026, 11, 14) + timedelta(days=dte),
        underlying=sym,
        con_id=con_id,
    )


def _build(positions, **kw):
    base = dict(
        nlv=100_000.0,
        value_by_name={},
        ivs={},
        beta_map={"NVDA": 1.8, "AMD": 1.5},
        beta_smh_map={"NVDA": 1.1, "AMD": 1.2},
        today=date(2026, 11, 14),
    )
    base.update(kw)
    return si.build_inputs(positions, **base)


def test_build_inputs_adds_value_holdings_once(db) -> None:
    """C7: get_positions() already drops value stock, so the value book's holdings come in once,
    from value_by_name, as their own book's line."""
    inp = _build([_stk("NVDA", 100, 180.0)], value_by_name={"NVDA": 9_000.0, "AMD": 0.0})
    nvda = [ln for ln in inp.lines if ln.symbol == "NVDA"]
    assert sorted(ln.book for ln in nvda) == ["value", "wheel"]
    value = next(ln for ln in nvda if ln.book == "value")
    assert value.qty * value.spot == pytest.approx(9_000.0) and value.spot == 180.0
    assert not [ln for ln in inp.lines if ln.symbol == "AMD"]  # a zero holding adds nothing
    # stock-equivalent exposure counted exactly once per book
    from src.analytics.shock import uew

    assert uew(inp) == pytest.approx((18_000 + 9_000) / 100_000)


def test_build_inputs_keys_live_iv_by_con_id_and_never_falls_back(db) -> None:
    positions = [
        _stk("NVDA", 100, 180.0),
        _put("NVDA", 170.0, con_id=11),
        _put("NVDA", 160.0, con_id=12),
    ]
    live = _build(positions, ivs={11: 0.55, 12: None})
    ivs = {ln.con_id: ln.iv for ln in live.lines if ln.kind == "short_put"}
    assert ivs == {11: 0.55, 12: None}  # 12 has no live IV: unmeasured, not the stored value
    stored = _build(positions, ivs={"NVDA": 0.48})
    assert {ln.iv for ln in stored.lines if ln.kind == "short_put"} == {0.48}
    assert all(ln.spot == 180.0 and ln.dte == 30 for ln in stored.lines if ln.kind == "short_put")


def test_stored_iv_skips_flagged_rows(db) -> None:
    from src.storage.db import session_scope
    from src.storage.models import IVHistoryRow

    with session_scope() as s:
        s.add(IVHistoryRow(symbol="QQQ", obs_date=date(2026, 11, 4), iv=0.33, source="ibkr"))
        s.add(
            IVHistoryRow(
                symbol="QQQ", obs_date=date(2026, 11, 5), iv=0.146, source="ibkr", flagged=True
            )
        )
    assert si.stored_ivs(["QQQ", "NONE"]) == {"QQQ": 0.33}


def test_leverage_map_covers_names_out_of_the_universe() -> None:
    lev = si.leverage_map()
    assert lev["TQQQ"] == 3 and lev["UPRO"] == 3  # UPRO left the universe but stays leveraged


def test_the_envelope_block_parses_to_the_shipped_defaults() -> None:
    from src.common.config import RiskEnvelopeCfg, get_envelope_cfg

    cfg = get_envelope_cfg()  # tests run on config/examples/risk_limits.yaml
    assert cfg == RiskEnvelopeCfg()
    assert set(RiskEnvelopeCfg.KEYS) == set(RiskEnvelopeCfg.model_fields)
    assert cfg.governing == {"TQQQ": "QQQ", "SOXL": "SOXX"} and cfg.live_iv_batch == 10
    with pytest.raises(ValueError, match="unknown key"):
        RiskEnvelopeCfg(s10_target=15.0)
    with pytest.raises(ValueError):
        RiskEnvelopeCfg(live_iv_batch=25)  # never more than ten lines at once


def test_betas_cover_the_candidate_universe_not_only_the_book(db, monkeypatch) -> None:
    """A put candidate on a name the book does not hold has a beta, so the envelope measures
    it instead of refusing it ``envelope_unmeasured`` (2026-11-19)."""
    from dataclasses import replace

    from src.analytics.shock import measure
    from src.common.envelope_types import BookLine

    spy = _bench(260)
    append_bars("SPY", _series(261, spy))
    append_bars("SMH", _series(261, [1.4 * r for r in spy]))
    append_bars("NVDA", _series(261, [1.8 * r for r in spy]))
    append_bars("AVGO", _series(261, [1.6 * r for r in spy]))
    monkeypatch.setattr(
        "src.common.universe.effective_universe",
        lambda: {"would_own": ["avgo"], "watchlist": ["QQQ"], "indexes": ["SPY"]},
    )
    assert si.candidate_symbols() == {"AVGO", "QQQ", "SPY"}
    inp = si.build_inputs(
        [_stk("NVDA", 100, 180.0)],
        nlv=100_000.0,
        value_by_name={},
        ivs={},
        today=date(2026, 11, 14),
    )
    assert {"NVDA", "AVGO", "QQQ"} <= set(inp.betas) and "AVGO" in inp.betas_smh
    line = BookLine("AVGO", "short_put", 1.0, 330.0, strike=320.0, dte=30, iv=0.5, book="wheel")
    assert measure(replace(inp, lines=inp.lines + (line,))).measured


def test_an_explicit_beta_map_is_used_as_given(db, monkeypatch) -> None:
    """Tests and replays pass their own betas: the universe is not added to them."""
    monkeypatch.setattr("src.common.universe.effective_universe", lambda: {"would_own": ["AVGO"]})
    inp = _build([_stk("NVDA", 100, 180.0)])
    assert set(inp.betas) == {"NVDA", "AMD"}


def test_an_unreadable_universe_adds_nothing(db, monkeypatch) -> None:
    def boom() -> dict:
        raise RuntimeError("no universe")

    monkeypatch.setattr("src.common.universe.effective_universe", boom)
    assert si.candidate_symbols() == set()
