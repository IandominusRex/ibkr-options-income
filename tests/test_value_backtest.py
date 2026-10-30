"""Stage 1b (value book spec §12): the point-in-time backtest of Python's rules."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.common.config import get_config
from src.value import backtest as bt
from src.value.scorecard import build_scorecard
from tests.value_fixtures import companyfacts, inputs

CFG = get_config().value
SESSIONS = [d.date() for d in pd.bdate_range("2025-01-01", periods=180)]


def frame(closes: list[float], opens: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "open": opens or closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1e6] * n,
        },
        index=pd.Index(SESSIONS[:n]),
    )


def test_formations_are_each_months_first_session_in_the_window() -> None:
    got = bt.formation_dates(SESSIONS, date(2025, 2, 1), date(2025, 4, 30))
    assert got == [date(2025, 2, 3), date(2025, 3, 3), date(2025, 4, 1)]


def test_inputs_are_the_filings_and_prices_as_they_stood() -> None:
    """Spec §6.2: on 2024-06-03 only the 10-Ks filed by then exist (FY2021-FY2023, the last on
    2024-02-10); the next one, filed 2025-02-10, stands in for the earnings date; the market-cap
    cross-check reads EDGAR's own count (FY2023's 102 million diluted shares) x the close."""
    payload = companyfacts()
    days = [d.date() for d in pd.bdate_range("2023-01-02", "2024-06-28")]
    bars = pd.DataFrame(
        {"open": 30.0, "high": 30.5, "low": 29.5, "close": 30.0, "volume": 1e6},
        index=pd.Index(days),
    )
    spy = bars.copy()
    as_of = date(2024, 6, 3)
    price = bt.price_at(bars, spy, as_of)
    assert price is not None and price.as_of == as_of
    got = bt.inputs_at(
        bt.BacktestName("STDY", "Information Technology", "Application Software"),
        payload,
        price,
        as_of,
        CFG,
        None,
    )
    assert got.financials is not None and len(got.financials.annual) == 3
    assert got.financials.latest_filed == date(2024, 2, 10)
    assert got.next_earnings == date(2025, 2, 10)
    assert got.yf_market_cap == pytest.approx(102e6 * 30.0)
    assert got.regime == "normal"
    card = build_scorecard(got, CFG)
    assert card.data_quality == "unknown"  # three annual periods then, five needed: honest
    assert bt.next_periodic_filing(payload, date(2026, 3, 1)) is None
    assert bt.next_periodic_filing(None, date(2026, 3, 1)) is None


def test_forward_returns_enter_at_the_next_open_and_mark_against_spy() -> None:
    closes = [20.0] * 24 + [22.0] * 156  # 2025-02-03 is SESSIONS[23], the entry SESSIONS[24]
    opens = [20.0] * 25 + [22.0] * 155
    name = frame(closes, opens)
    spy = frame([500.0] * 100 + [510.0] * 80)
    entry, px, rets, spys = bt.forward_returns(name, spy, date(2025, 2, 3))
    assert (entry, px) == (SESSIONS[24], 20.0)
    assert rets == {21: pytest.approx(0.10), 63: pytest.approx(0.10), 126: pytest.approx(0.10)}
    assert spys == {21: 0.0, 63: 0.0, 126: pytest.approx(0.02)}  # SESSIONS[150] is past 100
    short = frame(closes[:60], opens[:60])  # the name's bars stop: later horizons stay unmarked
    _, _, rets, _ = bt.forward_returns(short, spy, date(2025, 2, 3))
    assert rets[21] == pytest.approx(0.10) and rets[63] is None and rets[126] is None
    assert bt.forward_returns(name, spy, SESSIONS[-1]) == (None, None, {}, {})


def test_a_run_scores_each_formation_records_ready_entries_and_the_ranked_record() -> None:
    """Ten names, two formations (2025-02-03 and 2025-03-03). S0 is the cheapest, so it tops
    both lists, and the only one that moves: 20 to 22 from the February entry on."""
    names = [bt.BacktestName(f"S{i}") for i in range(10)]
    price = {f"S{i}": 20.0 + 2 * i for i in range(10)}
    bars = {s: frame([p] * 180) for s, p in price.items()}
    bars["S0"] = frame([20.0] * 24 + [22.0] * 156, [20.0] * 25 + [22.0] * 155)
    spy = frame([500.0] * 180)
    cards = {s: build_scorecard(inputs(symbol=s, close=p), CFG) for s, p in price.items()}
    loaded: list[str] = []
    dates = bt.formation_dates(SESSIONS, date(2025, 2, 1), date(2025, 3, 31))
    result = bt.run(
        names,
        bars=bars,
        spy=spy,
        load_payload=lambda s: loaded.append(s) or None,
        dates=dates,
        cfg=CFG,
        version="v3",
        digest="x",
        score=lambda i, cfg: cards[i.symbol],
    )
    assert loaded == [f"S{i}" for i in range(10)]  # one payload per name, not per date
    assert result.scored == 20 and len(result.dates) == 2
    s0 = [e for e in result.entries if e.symbol == "S0" and e.list_name == "deep_value"]
    assert [(e.signal_date, e.entry_date, e.entry_price) for e in s0] == [
        (date(2025, 2, 3), SESSIONS[24], 20.0),
        (date(2025, 3, 3), SESSIONS[44], 22.0),
    ]
    assert s0[0].returns[21] == pytest.approx(0.10) and s0[1].returns[21] == pytest.approx(0.0)
    assert {e.symbol for e in result.entries if e.list_name == "deep_value"} == {
        f"S{i}" for i in range(8)
    }  # S8 and S9 are WAIT on deep value
    feb = {(r.list_name, r.bucket): r for r in result.ranked if r.formed_on == date(2025, 2, 3)}
    assert feb[("deep_value", "top")].n == 1 and feb[("deep_value", "top")].ret == pytest.approx(
        0.10
    )
    assert feb[("deep_value", "all")].ret == pytest.approx(0.01)  # 10% on one name of ten
    assert feb[("deep_value", "top")].spy_ret == 0.0
    march = [r for r in result.ranked if r.formed_on == date(2025, 3, 3)]
    assert march and all(r.closed_on is None and r.ret is None for r in march)
    text = bt.render(result)
    assert text.splitlines()[0].startswith("== Value book Stage 1b: point-in-time backtest")
    assert "! Prices carry yfinance's survivorship bias" in text
    # 16 deep-value entries over two dates, one of them +10%: a mean of 0.625%; the clustered
    # SE is 0.625% too (two clusters, residual sums +5% and -5%), so t = 1.00.
    assert "deep_value      n 16 (2 dates) mean excess +0.6% t 1.00: the rules beat SPY" in text
