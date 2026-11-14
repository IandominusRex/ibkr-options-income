"""The sleeve replay (E7) and the covered-call floor replay (E12) (risk-envelope plan Task 29).

Synthetic panels only. The signal under the sleeve replay is the production
``analytics.leveraged_entry.les_signal``; the call sizing and S10 are the production functions.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from scripts import cc_floor_replay as cc
from scripts import sleeve_replay as sl
from src.common.envelope_types import ShockInputs
from src.common.schemas import PositionSnapshot
from src.reporting.replay import Closes
from src.storage import envelope_switches as sw

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _panel(n: int, dips: list[tuple[int, int]], *, drift: float = 0.002, dip: float = -0.02):
    """QQQ rising *drift* a day with a *dip* a day for each (start index, length), and TQQQ at three
    times QQQ's daily return, from 2025-06-02."""
    days = _weekdays(date(2025, 6, 2), n)
    down = {i for s, ln in dips for i in range(s, s + ln)}
    qqq, tqqq = [100.0], [40.0]
    for i in range(1, n):
        r = dip if i in down else drift
        qqq.append(qqq[-1] * (1.0 + r))
        tqqq.append(tqqq[-1] * (1.0 + 3.0 * r))
    return days, {
        "QQQ": list(zip(days, qqq, strict=True)),
        "TQQQ": list(zip(days, tqqq, strict=True)),
    }


# --------------------------------------------------------------------------- the sleeve replay

NAMES = {"TQQQ": "QQQ"}
LEV = {"TQQQ": 3}
NLV = 5_000_000.0  # a 3% tier (150k) holds a lot of the synthetic TQQQ (about 40k at 3x leverage)


def test_the_sleeve_replay_finds_the_jul_and_nov_windows() -> None:
    # 330 sessions: a rally above the 200-day, a sharp dip near session 230 (a "July" window) and
    # another near 290 (a "November" one); nothing else is a pullback
    days, closes = _panel(330, [(230, 4), (290, 4)])
    out = sl.replay(closes, {"TQQQ": 0.8}, nlv=NLV, names=NAMES, leverage=LEV)
    assert out.skipped == [] and out.lots, "the sleeve would have opened lots in the dips"
    # the first dip opens the first lot on its first day; the second dip (after the first window's
    # lots have run off) opens another
    first = [lot for lot in out.lots if days[230] <= lot.opened < days[289]]
    second = [lot for lot in out.lots if days[290] <= lot.opened]
    assert first and second, "a lot in each window"
    assert days[230] <= min(lot.opened for lot in out.lots) <= days[233], (
        "nothing opens before the dip"
    )
    assert all(lot.path == "trend" and lot.tier == 3.0 for lot in out.lots)
    # a lot is whole contracts at the tier: 3% of the NLV at 3x leverage; never over the cap, never zero
    for lot in out.lots:
        assert lot.contracts >= 1 and lot.collateral_weighted <= 0.03 * NLV + 1e-6
    # one lot per name per 3 sessions, at most two open at once
    opened = sorted(lot.opened for lot in out.lots)
    assert all((b - a).days >= 3 for a, b in zip(opened, opened[1:], strict=False)), (
        "pace: one lot per name per 3 sessions"
    )
    assert out.peak_open <= 2
    result = sl.e7_result(out, NLV, now=NOW)
    assert result.id == "E7" and (result.switch, result.value_on_pass) == ("leveraged_sleeve", "on")
    assert result.passed in (True, False) and result.metrics["lots"] == float(len(out.lots))


def test_no_lots_is_insufficient() -> None:
    # a straight rally never pulls back: no signal, no lot, no result
    _, closes = _panel(330, [])
    out = sl.replay(closes, {"TQQQ": 0.8}, nlv=1_000_000.0, names=NAMES, leverage=LEV)
    assert out.lots == []
    assert sl.e7_result(out, 1_000_000.0, now=NOW).passed is None
    # a governing index with under 201 bars is skipped and named, not guessed
    _, short = _panel(100, [])
    skipped = sl.replay(short, {"TQQQ": 0.8}, nlv=1_000_000.0, names=NAMES, leverage=LEV)
    assert skipped.lots == [] and skipped.skipped and "TQQQ" in skipped.skipped[0]


def test_a_lot_losing_over_one_percent_of_nlv_fails_e7() -> None:
    lot = sl.Lot(
        "TQQQ",
        "trend",
        3.0,
        date(2026, 7, 1),
        50.0,
        date(2026, 7, 11),
        0.8,
        1,
        1.0,
        3,
        10,
        realised=-12_000.0,
        closed=date(2026, 7, 5),
        how="loss_line",
    )
    ok = sl.Lot(
        "TQQQ",
        "trend",
        3.0,
        date(2026, 8, 1),
        50.0,
        date(2026, 8, 11),
        0.8,
        1,
        1.0,
        3,
        10,
        realised=20_000.0,
        closed=date(2026, 8, 5),
        how="profit_take",
    )
    out = sl.ReplayOut([lot, ok], 1, [], False)
    # total +8k but one lot lost 1.2% of a 1M NLV
    assert sl.e7_result(out, 1_000_000.0, now=NOW).passed is False
    assert sl.e7_result(out, 2_000_000.0, now=NOW).passed is True  # 0.6%: inside the line
    assert sl.e7_result(sl.ReplayOut([lot], 3, [], False), 2_000_000.0, now=NOW).passed is False


def test_the_below_trend_path_fails_closed_without_an_iv_rank() -> None:
    # a selloff under the 200-day: with no IV history the half-tier path cannot open a lot
    days, closes = _panel(330, [(215, 60)], dip=-0.01)
    out = sl.replay(closes, {"TQQQ": 0.8}, nlv=10_000_000.0, names=NAMES, leverage=LEV)
    assert all(lot.path == "trend" for lot in out.lots)


# --------------------------------------------------------------------------- the covered-call floor


def _stock_book(basis: float = 100.0) -> tuple[ShockInputs, list[PositionSnapshot]]:
    from src.common.envelope_types import BookLine

    positions = [
        PositionSnapshot(
            symbol="AAA",
            sec_type="STK",
            position=100.0,
            avg_cost=basis,
            market_price=90.0,
            market_value=9_000.0,
        )
    ]
    inputs = ShockInputs(
        lines=(BookLine("AAA", "stock", 100.0, 90.0),),
        betas={"AAA": 1.0, "SPY": 1.0},
        betas_smh={"AAA": 1.0, "SPY": 1.0},
        leverage={"TQQQ": 3},
        governing={},
        tech_linked=frozenset(),
        semis=frozenset(),
        nlv=100_000.0,
    )
    return inputs, positions


def _series(days: list[date], pts: dict[int, float]) -> list[tuple[date, float]]:
    """Closes linearly interpolated between the (index -> price) points."""
    keys = sorted(pts)
    out: list[tuple[date, float]] = []
    for i, d in enumerate(days):
        lo = max(k for k in keys if k <= i)
        hi = min((k for k in keys if k >= i), default=lo)
        px = pts[lo] if hi == lo else pts[lo] + (pts[hi] - pts[lo]) * (i - lo) / (hi - lo)
        out.append((d, px))
    return out


def _floor_closes() -> Closes:
    """AAA against a 100 basis, three sale dates (sessions 0, 21 and 42): 91 on the first (the 1.00
    floor sells nothing, the others do, and the call expires worthless at 86); 86 on the second (only
    the 0.90 floor sells, into a rally to 108 by its expiry); 108 on the third (every floor sells,
    nothing happens). SPY keeps the calendar."""
    days = _weekdays(date(2025, 6, 2), 70)
    return {
        "SPY": [(d, 100.0) for d in days],
        "AAA": _series(days, {0: 91.0, 20: 91.0, 21: 86.0, 41: 86.0, 42: 108.0, 69: 108.0}),
    }


def test_the_floor_replay_picks_the_lowest_passing_floor() -> None:
    inputs, positions = _stock_book()
    closes = _floor_closes()
    days = cc.sale_days(closes)
    assert len(days) == 3
    holdings = cc.holdings_of(positions, leveraged=False)
    ivs = {"AAA": 0.35}
    by_floor = {
        f: cc.replay_floor(inputs, holdings, closes, ivs, floor=f, delta=cc.DELTA[f], days=days)
        for f in cc.FLOORS
    }
    # the 1.00 floor sells only on the third date; 0.95 adds the 91 date; 0.90 adds the 86 one too
    assert [by_floor[f].calls for f in (1.00, 0.95, 0.90)] == [1, 2, 3]
    # 0.90 sells into the 86 low just before the rally and gives the upside away; 0.95 does not
    assert by_floor[0.95].forgone == by_floor[1.00].forgone == 0.0
    assert by_floor[0.90].forgone > 1_000.0 and by_floor[0.90].called_away == 1
    result = cc.e12_result(by_floor, now=NOW)
    assert result.id == "E12" and result.switch == "cc_basis_floor"
    assert result.passed is True and result.value_on_pass == "0.95"
    assert result.metrics["chosen_floor"] == "0.95"
    # the 0.90 floor is judged and refused on its own numbers
    assert result.metrics["floor_0.90_net_vs_1.00"] < 0  # type: ignore[operator]


def test_a_floor_that_sells_nothing_extra_is_not_chosen() -> None:
    inputs, positions = _stock_book(
        basis=60.0
    )  # a basis far under the spot: every floor sells the same
    closes = _floor_closes()
    days = cc.sale_days(closes)
    holdings = cc.holdings_of(positions, leveraged=False)
    by_floor = {
        f: cc.replay_floor(
            inputs, holdings, closes, {"AAA": 0.35}, floor=f, delta=cc.DELTA[f], days=days
        )
        for f in cc.FLOORS
    }
    result = cc.e12_result(by_floor, now=NOW)
    assert result.passed is False and result.value_on_pass == "1.00"


def test_the_leveraged_carve_out_has_its_own_result() -> None:
    from src.common.envelope_types import BookLine

    days = _weekdays(date(2025, 6, 2), 90)
    closes: Closes = {
        "SPY": [(d, 100.0) for d in days],
        "TQQQ": _series(days, {0: 50.0, 89: 50.0}),  # flat: every call expires worthless
    }
    positions = [
        PositionSnapshot(
            symbol="TQQQ",
            sec_type="STK",
            position=200.0,
            avg_cost=70.0,
            market_price=50.0,
            market_value=10_000.0,
        )
    ]
    inputs = ShockInputs(
        lines=(BookLine("TQQQ", "stock", 200.0, 50.0),),
        betas={"TQQQ": 3.0, "SPY": 1.0},
        betas_smh={"TQQQ": 3.0, "SPY": 1.0},
        leverage={"TQQQ": 3},
        governing={"TQQQ": "QQQ"},
        tech_linked=frozenset(),
        semis=frozenset(),
        nlv=100_000.0,
    )
    lev = cc.holdings_of(positions, leveraged=True)
    assert [h.symbol for h in lev] == ["TQQQ"] and cc.holdings_of(positions, leveraged=False) == []
    r = cc.replay_floor(
        inputs,
        lev,
        closes,
        {"TQQQ": 0.8},
        floor=None,
        delta=cc.LEVERAGED_DELTA,
        days=cc.sale_days(closes),
    )
    # a basis of 70 against a 50 spot: no floor means the calls are sold anyway
    assert r.calls > 0 and r.forgone == 0.0
    own = cc.leveraged_result(r, now=NOW)
    assert own.id == "E12_leveraged" and own.switch == "leveraged_cc_auto"
    assert own.passed is True and own.value_on_pass == "on"
    # independent of E12: with no non-leveraged holding E12 has no calls to judge, whatever this says
    empty = cc.FloorResult(None, 0.0, 0.0, 0, 0, None, 3)
    by_floor = {f: empty for f in cc.FLOORS}
    assert cc.e12_result(by_floor, now=NOW).passed is None
    # and a leveraged replay that gave away more upside than it sold is a FAIL of its own
    losing = cc.FloorResult(None, 500.0, 900.0, 4, 2, None, 3)
    assert cc.leveraged_result(losing, now=NOW).passed is False
    assert cc.leveraged_result(None, now=NOW).passed is None


def test_each_result_applies_through_apply_reports(tmp_path: Path, monkeypatch) -> None:
    inputs, positions = _stock_book()
    closes = _floor_closes()
    days = cc.sale_days(closes)
    holdings = cc.holdings_of(positions, leveraged=False)
    by_floor = {
        f: cc.replay_floor(
            inputs, holdings, closes, {"AAA": 0.35}, floor=f, delta=cc.DELTA[f], days=days
        )
        for f in cc.FLOORS
    }
    cc.write_result(cc.e12_result(by_floor, now=NOW), tmp_path)
    cc.write_result(cc.leveraged_result(None, now=NOW), tmp_path)  # no result: nothing applies

    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    notices = sw.apply_reports(tmp_path)
    assert len(notices) == 1 and sw.get_switch("cc_basis_floor") == "0.95"
    assert sw.get_switch("leveraged_cc_auto") == "off"


# --------------------------------------------------------------------------- the scripts, read-only


def test_both_scripts_read_a_synthetic_database_read_only(db) -> None:
    from src.reporting.replay import trading_db_path
    from tests.test_survivability import _seed_book

    _seed_book(db)
    path = trading_db_path()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    text, res = sl.run(path)
    assert "NLV $100,000" in text and (res is None or res.id == "E7")
    text2, res2 = cc.run(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert res2 is not None and {r.id for r in res2} == {"E12", "E12_leveraged"}
    assert "held stock names" in text2


def test_a_missing_database_writes_nothing(tmp_path: Path) -> None:
    assert sl.run(tmp_path / "absent.db")[1] is None
    assert cc.run(tmp_path / "absent.db")[1] is None


@pytest.mark.parametrize("n", [3])
def test_sale_days_leave_room_to_expire(n: int) -> None:
    closes = _floor_closes()
    days = cc.sale_days(closes)
    last = closes["SPY"][-1][0]
    assert all(d + timedelta(days=cc.DTE) <= last for d in days) and len(days) >= n - 1
