"""The Leveraged Entry Signal replay (risk-envelope plan Task 29a; spec §2.7, ruling L8).

Synthetic prices only, through an injected fetch; the signal under test is the production
``analytics.leveraged_entry.les_signal``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import les_replay as lr
from src.common.config import get_regime_cfg
from src.common.schemas import BreadthCount
from src.storage import envelope_switches as sw

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
CFG = get_regime_cfg().leveraged_entry


def _index(n: int, moves: dict[int, float] | None = None, *, drift: float = 0.0008) -> pd.Series:
    """*n* business days from 2000-01-03: *drift* a day with the listed one-day moves."""
    idx = pd.bdate_range("2000-01-03", periods=n)
    px, out = 100.0, []
    for i in range(n):
        px *= 1.0 + (moves or {}).get(i, drift)
        out.append(px)
    return pd.Series(out, index=idx)


def _frame(series: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"Close": series.to_numpy()}, index=series.index)


# --------------------------------------------------------------------------- the formula


def test_synthetic_3x_applies_the_daily_formula() -> None:
    close = pd.Series([100.0, 101.0, 99.99], index=pd.bdate_range("2000-01-03", periods=3))
    got = lr.synthetic_3x(close)
    daily_spread = 0.03 / 252
    assert len(got) == 2
    assert got.iloc[0] == pytest.approx(3 * 0.01 - daily_spread)
    assert got.iloc[1] == pytest.approx(3 * (99.99 / 101.0 - 1.0) - daily_spread)


# --------------------------------------------------------------------------- entry and exit timing


def test_entry_on_the_next_close_after_a_pullback() -> None:
    # 300 sessions of a steady climb, then one -4% day: RSI(2) collapses (a pullback above the 200-day)
    close = _index(320, {300: -0.04})
    arrays = lr.signal_arrays(close, CFG)
    first = int(np.argmax(arrays["pullback"]))
    assert first >= 200 and arrays["up"][first], "a pullback needs the trend gate"
    state = lr.les_state(arrays["pullback"], arrays["break"])
    assert state[first] and not state[first - 1]
    # the signal is read on close `first`, filled on the next close, and first earns the session after
    lag1 = lr.exposure(state, 1)
    assert not lag1[first + 1] and lag1[first + 2]
    assert lr.exposure(state, 0)[first + 1] and not lr.exposure(state, 0)[first]


def test_exit_on_the_second_close_under_sma200() -> None:
    # a long climb, a pullback to enter on, then a collapse through the 200-day and a stay under it
    moves = {260: -0.05, **{i: -0.03 for i in range(270, 290)}}
    close = _index(300, moves)
    arrays = lr.signal_arrays(close, CFG)
    sma = close.rolling(200).mean()
    under = (close < sma).to_numpy()
    # the first session on which two consecutive closes sit under the 200-day, by brute force
    brute = next(i for i in range(201, len(close)) if under[i] and under[i - 1])
    assert int(np.argmax(arrays["break"])) == brute
    state = lr.les_state(arrays["pullback"], arrays["break"])
    assert state[brute - 1] and not state[brute], "LES leaves on that second close"
    held = lr.exposure(state, 1)
    # the sell fills on the close after the second close under it, so that session's return is the last held
    assert held[brute + 1] and not held[brute + 2]
    assert lr.exposure(state, 0)[brute] and not lr.exposure(state, 0)[brute + 1]
    assert not state[brute:].any(), "no re-entry while the index stays under its 200-day"


def test_metrics_are_cagr_drawdown_sharpe_and_time_in_market() -> None:
    idx = pd.bdate_range("2020-01-02", periods=253)  # one year of daily +0.1%
    ret = pd.Series([0.001] * 253, index=idx)
    held = np.array([True] * 200 + [False] * 53)
    m = lr.metrics_of(ret, held)
    assert m.in_market == pytest.approx(200 / 253 * 100)
    assert m.max_dd == pytest.approx(0.0, abs=1e-9)
    assert m.cagr == pytest.approx(((1.001**200) ** (365.25 / (idx[-1] - idx[0]).days) - 1) * 100)
    crash = lr.metrics_of(pd.Series([0.1, -0.5, 0.1], index=idx[:3]), np.array([True] * 3))
    assert crash.max_dd == pytest.approx(-50.0)


# --------------------------------------------------------------------------- the verdict


def _cell(name: str, les_sharpe: float, filt_sharpe: float, les_dd: float, bh_dd: float) -> lr.Cell:
    def m(sharpe: float, dd: float) -> lr.Metrics:
        return lr.Metrics(10.0, dd, sharpe, 50.0, 1000)

    return lr.Cell(
        name,
        {
            "buy_and_hold": m(0.5, bh_dd),
            "filter_200d": m(filt_sharpe, -40.0),
            "les": m(les_sharpe, les_dd),
        },
    )


def test_pass_needs_three_sharpe_cells_and_four_drawdown_cells() -> None:
    good = [_cell(f"c{i}", 0.6, 0.5, -60.0, -80.0) for i in range(4)]
    assert lr.l8_verdict(good) == (True, 4, 4)
    # the scratch result: Sharpe 3 of 4 (one cell below the filter), drawdown 4 of 4 -> PASS
    three = good[:3] + [_cell("c3", 0.7, 0.85, -62.0, -82.0)]
    assert lr.l8_verdict(three) == (True, 3, 4)
    # Sharpe 2 of 4 fails
    two = good[:2] + [_cell("c2", 0.1, 0.5, -60.0, -80.0), _cell("c3", 0.1, 0.5, -60.0, -80.0)]
    assert lr.l8_verdict(two)[0] is False
    # a worse drawdown than buy-and-hold in any one cell fails, whatever the Sharpe
    deep = good[:3] + [_cell("c3", 0.9, 0.5, -90.0, -80.0)]
    assert lr.l8_verdict(deep) == (False, 4, 3)
    # fewer than four cells is no verdict
    assert lr.l8_verdict(good[:3])[0] is None


def test_reproduction_gaps_use_the_spec_table_to_half_a_point() -> None:
    near = lr.Cell(
        "QQQ/TQQQ synthetic",
        {"les": lr.Metrics(11.3, -64.8, 0.47, 50.0, 1000)},  # CAGR 0.4 away, DD 0.2, Sharpe 0.01
    )
    assert lr.reproduction_gaps([near]) == []
    far = lr.Cell("QQQ/TQQQ synthetic", {"les": lr.Metrics(12.0, -65.0, 0.46, 50.0, 1000)})
    gaps = lr.reproduction_gaps([far])
    assert len(gaps) == 1 and "CAGR" in gaps[0]
    # a cell the spec gives no figure for is never a gap
    assert (
        lr.reproduction_gaps([lr.Cell("SOXX/SOXL synthetic", {"buy_and_hold": far.metrics["les"]})])
        == []
    )


def test_a_reproduction_gap_writes_no_verdict_unless_ignored() -> None:
    good = [_cell(f"c{i}", 0.6, 0.5, -60.0, -80.0) for i in range(4)]
    stopped = lr.les_result(good, ["QQQ/TQQQ real les CAGR: 20.0 vs 25.4 in the spec"], now=NOW)
    assert stopped.passed is None and "STOP" in str(stopped.metrics["note"])
    forced = lr.les_result(good, ["gap"], ignore_reproduction=True, now=NOW)
    assert forced.passed is True


def test_writes_the_les_result_file(tmp_path: Path, monkeypatch) -> None:
    good = [_cell(f"c{i}", 0.6, 0.5, -60.0, -80.0) for i in range(4)]
    result = lr.les_result(good, [], now=NOW)
    assert result.id == "LES" and (result.switch, result.value_on_pass) == ("leveraged_entry", "on")
    assert result.passed is True and result.metrics["sharpe_cells"] == 4.0
    path = lr.write_result(result, tmp_path)
    assert path.name == "LES.json"

    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    assert len(sw.apply_reports(tmp_path)) == 1 and sw.get_switch("leveraged_entry") == "on"


# --------------------------------------------------------------------------- the data path


def test_the_price_provider_reaches_past_ten_years() -> None:
    from src.data.yfinance_backend import _period_for_lookback

    assert _period_for_lookback(3_650) == "10y"
    assert (
        _period_for_lookback(lr.LOOKBACK_DAYS) == "max"
    )  # 1999 on needs the provider's whole history


def test_series_are_cached_and_a_missing_one_blocks_the_run(tmp_path: Path) -> None:
    calls: list[str] = []
    px = _index(260)

    def fetch(sym: str) -> pd.DataFrame | None:
        calls.append(sym)
        if sym == "SOXL":
            return None  # the provider has nothing
        frame = _frame(px)
        frame.index = frame.index.tz_localize("America/New_York")  # a provider frame is tz-aware
        return frame

    text, result = lr.run(fetch=fetch, breadth=lambda: [], cache_dir=tmp_path)
    assert result is None and "SOXL" in text and "Nothing written" in text
    assert (tmp_path / "QQQ.csv").exists() and not (tmp_path / "SOXL.csv").exists()
    # a warm cache needs no fetch for the symbols it holds
    calls.clear()
    series = lr.load_series("QQQ", fetch, tmp_path)
    assert series is not None and calls == [] and len(series) == 260 and series.index.tz is None


def test_the_four_cells_run_end_to_end_on_synthetic_series(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    n = 5200  # 2000-01-03 into 2020: spans both the synthetic and the real window

    def path(vol: float) -> pd.Series:
        r = rng.normal(0.0004, vol, n)
        return pd.Series(100.0 * np.cumprod(1.0 + r), index=pd.bdate_range("2000-01-03", periods=n))

    qqq, soxx = path(0.012), path(0.018)
    tq = qqq * 0 + 100.0 * np.cumprod(1.0 + 3.0 * qqq.pct_change().fillna(0.0))
    sl = soxx * 0 + 100.0 * np.cumprod(1.0 + 3.0 * soxx.pct_change().fillna(0.0))
    data = {"QQQ": qqq, "SOXX": soxx, "TQQQ": tq, "SOXL": sl}

    def fetch(sym: str) -> pd.DataFrame | None:
        return _frame(data[sym])

    counts = [
        BreadthCount(
            day=d.date(), adv=60 + int(10 * np.sin(i / 7)), dec=40 - int(10 * np.sin(i / 7))
        )
        for i, d in enumerate(pd.bdate_range("2016-11-01", periods=600))
    ]
    text, result = lr.run(
        fetch=fetch, breadth=lambda: counts, cache_dir=tmp_path, ignore_reproduction=True
    )
    assert result is not None and result.id == "LES"
    assert result.passed in (
        True,
        False,
    )  # the random panel decides; the point is it ran all four cells
    for cell in ("QQQ/TQQQ synthetic", "QQQ/TQQQ real", "SOXX/SOXL synthetic", "SOXX/SOXL real"):
        assert cell in text
    assert "Breadth tiers" in text and "pullback only" in text
