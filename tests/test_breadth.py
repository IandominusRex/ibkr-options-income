"""The Nasdaq-100 breadth oscillator and its data feed (risk-envelope Task 10a, ruling L2).

`src/analytics/breadth.py` is pure (counts in, oscillator out); `src/data/breadth_backend.py` is
the thetrading.tools fetch (mocked here: no test touches the network); `src/storage/les_state.py`
keeps the counts. Spec §3.5.1: RANA = (adv - dec) / (adv + dec) x 1000, osc = EMA(0.10) -
EMA(0.05) of RANA with `adjust=False`.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src.analytics.breadth import count_from_closes, merge_counts, oscillator, rana
from src.common.schemas import BreadthCount

D0 = date(2026, 9, 1)


def bc(i: int, adv: int, dec: int, *, source: str = "tt", unch: int = 0) -> BreadthCount:
    return BreadthCount(day=D0 + timedelta(days=i), adv=adv, dec=dec, unch=unch, source=source)  # type: ignore[arg-type]


FIVE = [bc(0, 60, 40), bc(1, 50, 50), bc(2, 30, 70), bc(3, 20, 80), bc(4, 45, 55)]


def test_rana_is_the_ratio_adjusted_difference():
    assert rana(60, 40) == 200.0
    assert rana(50, 50) == 0.0
    assert rana(30, 70) == -400.0
    assert rana(0, 0) is None  # nothing moved: no ratio


def test_rana_and_ema_match_a_hand_computed_series():
    """5 rows, alpha 0.10 / 0.05, `adjust=False`, no warm-up: each EMA starts on the first RANA.

    RANA = 200, 0, -400, -600, -100.
    fast: 200, 180, 122, 49.8, 34.82      slow: 200, 190, 160.5, 122.475, 111.35125
    osc : 0, -10, -38.5, -72.675, -76.53125
    """
    out = oscillator(FIVE, warm_up=0)
    assert out == pytest.approx([0.0, -10.0, -38.5, -72.675, -76.53125])


def test_warm_up_rows_are_none():
    out = oscillator(FIVE, warm_up=3)
    assert out[:3] == [None, None, None]
    # the EMAs ran through the warm-up rows: the same numbers as without the warm-up
    assert out[3:] == pytest.approx([-72.675, -76.53125])


def test_a_day_with_no_movers_leaves_the_emas_alone():
    counts = [bc(0, 60, 40), bc(1, 0, 0), bc(2, 50, 50)]
    out = oscillator(counts, warm_up=0)
    assert out[1] is None  # no ratio that day
    # the third row continues from the first row's state, as if the empty day were absent
    assert out[2] == pytest.approx(oscillator([bc(0, 60, 40), bc(2, 50, 50)], warm_up=0)[1])


def test_the_input_order_does_not_matter():
    assert oscillator(list(reversed(FIVE)), warm_up=0) == pytest.approx(oscillator(FIVE, warm_up=0))


def test_own_count_from_closes():
    prev = {"A": 10.0, "B": 10.0, "C": 10.0, "D": 10.0, "E": 10.0}
    today = {"A": 11.0, "B": 9.0, "C": 10.0, "D": 12.0, "F": 5.0}
    # A, D up; B down; C unchanged; E has no close today and F none yesterday: counted in neither
    assert count_from_closes(prev, today) == (2, 1, 1)
    assert count_from_closes({}, today) == (0, 0, 0)
    # a NaN or non-positive close is a missing close
    assert count_from_closes({"A": 10.0, "B": 10.0}, {"A": float("nan"), "B": 0.0}) == (0, 0, 0)


def test_sources_disagreeing_by_more_than_10_flags_and_uses_own():
    tt = [bc(0, 60, 40), bc(1, 60, 40), bc(2, 55, 45)]
    own = [
        bc(0, 60, 40, source="own"),  # identical: no flag, the history keeps its tt row
        bc(1, 55, 45, source="own"),  # RANA 100 against 200: a gap of 100 points
        bc(3, 50, 50, source="own"),  # a date only we have
    ]
    merged, flagged = merge_counts(tt, own, gap=10.0)
    assert flagged == {D0 + timedelta(days=1)}
    by_day = {c.day: c for c in merged}
    assert by_day[D0].source == "tt"
    assert by_day[D0 + timedelta(days=1)].source == "own"  # the gap: our count wins
    assert by_day[D0 + timedelta(days=1)].adv == 55
    assert by_day[D0 + timedelta(days=2)].source == "tt"  # tt only
    assert by_day[D0 + timedelta(days=3)].source == "own"  # own only
    assert [c.day for c in merged] == sorted(by_day)  # ascending, one row a day
    # an adv<->unchanged disagreement of one stock is inside the 10-point band: not flagged
    merged2, flagged2 = merge_counts([bc(0, 60, 40)], [bc(0, 59, 40, source="own")], gap=10.0)
    assert flagged2 == set() and merged2[0].source == "tt"


# --------------------------------------------------------------------------- #
# the thetrading.tools feed (mocked)
# --------------------------------------------------------------------------- #

SAMPLE = [
    {"date": "2026-11-03", "ndx_advancing": 61, "ndx_declining": 39, "other": 1},
    {"date": "2026-11-04", "ndx_advancing": 40, "ndx_declining": 58},
    {"date": "2026-11-05", "ndx_advancing": None, "ndx_declining": 50},  # a gap: skipped
    {"date": "not-a-date", "ndx_advancing": 1, "ndx_declining": 1},  # junk: skipped
]


class FakeResponse:
    def __init__(self, payload, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_the_feed_parses_the_published_fields(monkeypatch):
    from src.data import breadth_backend

    seen: dict = {}

    def fake_get(url, timeout=None, **kw):
        seen["url"], seen["timeout"] = url, timeout
        return FakeResponse(SAMPLE)

    monkeypatch.setattr(breadth_backend.httpx, "get", fake_get)
    out = breadth_backend.TheTradingToolsBreadth().history()
    assert seen["url"] == "https://www.thetrading.tools/data/market_breadth/ad_line.json"
    assert seen["timeout"] == 30
    assert [(c.day, c.adv, c.dec, c.source) for c in out] == [
        (date(2026, 11, 3), 61, 39, "tt"),
        (date(2026, 11, 4), 40, 58, "tt"),
    ]


def test_the_feed_accepts_a_wrapped_list(monkeypatch):
    from src.data import breadth_backend

    monkeypatch.setattr(
        breadth_backend.httpx, "get", lambda *a, **k: FakeResponse({"data": SAMPLE[:2]})
    )
    assert len(breadth_backend.TheTradingToolsBreadth().history()) == 2


@pytest.mark.parametrize("failure", ["raises", "http_error", "not_json", "wrong_shape"])
def test_a_failing_feed_is_an_empty_list_and_a_warning(monkeypatch, caplog, failure):
    from src.data import breadth_backend

    def fake_get(*a, **k):
        if failure == "raises":
            raise TimeoutError("slow")
        if failure == "http_error":
            return FakeResponse([], status=503)
        if failure == "not_json":

            class Bad(FakeResponse):
                def json(self):
                    raise json.JSONDecodeError("x", "y", 0)

            return Bad([])
        return FakeResponse({"unexpected": 1})

    monkeypatch.setattr(breadth_backend.httpx, "get", fake_get)
    with caplog.at_level("WARNING"):
        assert breadth_backend.TheTradingToolsBreadth().history() == []
    assert any("breadth" in r.getMessage().lower() for r in caplog.records)


def test_the_provider_comes_from_the_factory_and_only_there(monkeypatch):
    from src.data import factory

    factory.get_breadth_provider.cache_clear()
    provider = factory.get_breadth_provider()
    assert provider.__class__.__name__ == "TheTradingToolsBreadth"
    assert factory.get_breadth_provider() is provider  # cached process-wide
    factory.get_breadth_provider.cache_clear()


def test_the_closes_provider_returns_dates_to_symbol_closes(monkeypatch):
    """The own count's input: one batched download, shaped {date: {symbol: close}}."""
    import pandas as pd

    from src.data import yfinance_backend

    idx = pd.to_datetime(["2026-11-04", "2026-11-05"])
    frame = pd.DataFrame(
        {("Close", "AAA"): [10.0, 11.0], ("Close", "BBB"): [20.0, float("nan")]}, index=idx
    )
    frame.columns = pd.MultiIndex.from_tuples(frame.columns)
    monkeypatch.setattr(yfinance_backend, "_download_closes", lambda symbols, period: frame)
    out = yfinance_backend.closes(["AAA", "BBB"], days=3)
    assert out == {
        date(2026, 11, 4): {"AAA": 10.0, "BBB": 20.0},
        date(2026, 11, 5): {"AAA": 11.0},  # a NaN close is a missing close
    }


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #


@pytest.fixture
def db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def test_counts_are_idempotent_and_the_oscillator_is_stored(db):
    from src.storage import les_state

    assert les_state.record_counts(FIVE) == 5
    assert les_state.record_counts(FIVE) == 0  # a re-run inserts nothing
    own = [bc(4, 44, 56, source="own")]
    assert les_state.record_counts(own) == 1  # same day, another source: its own row
    assert [c.source for c in les_state.load_counts("own")] == ["own"]
    assert len(les_state.load_counts()) == 6

    merged, flagged = merge_counts(
        les_state.load_counts("tt"), les_state.load_counts("own"), gap=10.0
    )
    osc = oscillator(merged, warm_up=0)
    les_state.record_oscillator(merged, osc, flagged)
    recent = les_state.latest_osc(3)
    assert [d for d, _ in recent] == [D0 + timedelta(days=i) for i in (2, 3, 4)]
    assert recent[-1][1] == pytest.approx(osc[-1])
    # the flagged day (own 44/56 = -120 against tt -100: a 20 point gap) is marked
    assert les_state.flagged_days() == {D0 + timedelta(days=4)}


def test_a_signal_round_trips(db):
    from src.common.schemas import LesSignal
    from src.storage import les_state

    sig = LesSignal(
        asof=date(2026, 11, 13),
        index="QQQ",
        trend_up=True,
        pullback=True,
        washout=True,
        trend_break=False,
        tier_pct=6.0,
        reasons=["trend", "pullback", "washout"],
    )
    les_state.record_signal(sig)
    les_state.record_signal(sig)  # idempotent for (asof, index)
    assert les_state.latest_signal("QQQ") == sig
    assert les_state.latest_signal("SOXX") is None
    # a later run the same evening, with a fresher breadth count, replaces that row
    fresher = sig.model_copy(update={"washout": False, "tier_pct": 3.0})
    les_state.record_signal(fresher)
    assert les_state.latest_signal("QQQ") == fresher
    # a signal with no date cannot be keyed: nothing is stored
    assert les_state.record_signal(sig.model_copy(update={"asof": None})) is False


# --------------------------------------------------------------------------- #
# the constituent list
# --------------------------------------------------------------------------- #


def components_page(n: int, *, with_table: bool = True) -> str:
    rows = "".join(
        f"<tr><td><a href='/wiki/Co{i}'>Company {i}</a></td><td>T{i:03d}</td><td>Tech</td></tr>"
        for i in range(n)
    )
    table = (
        "<table class='wikitable sortable'><tr><th>Company</th><th>Ticker</th><th>Sector</th></tr>"
        f"{rows}</table>"
        if with_table
        else ""
    )
    return (
        f"<html><body><table class='infobox'><tr><th>Index</th></tr></table>{table}</body></html>"
    )


def test_the_components_table_is_read_by_its_ticker_column():
    from scripts.breadth import parse_components

    page = components_page(101)
    tickers = parse_components(page)
    assert len(tickers) == 101 and tickers[0] == "T000" and tickers[-1] == "T100"
    assert parse_components(components_page(0, with_table=False)) == []  # no components table


def test_a_refresh_writes_the_list_only_for_100_to_102_tickers(tmp_path):
    from scripts.breadth import refresh_constituents
    from src.storage.les_state import load_constituents

    target = tmp_path / "breadth_constituents.yaml"
    assert refresh_constituents(components_page(101), path=target) == 101
    assert len(load_constituents(target)) == 101
    text = target.read_text()
    assert "as_of:" in text and "source:" in text and "ndx:" in text
    # a page without the table, or with the wrong count, writes nothing and says why
    other = tmp_path / "other.yaml"
    for page in (components_page(0, with_table=False), components_page(99), components_page(103)):
        with pytest.raises(RuntimeError, match="expected 100-102"):
            refresh_constituents(page, path=other)
    assert not other.exists()


def test_a_missing_constituent_file_is_an_empty_list_not_a_guess(tmp_path):
    from src.storage.les_state import load_constituents

    assert load_constituents(tmp_path / "nope.yaml") == []
    bad = tmp_path / "bad.yaml"
    bad.write_text("ndx: not-a-list\n")
    assert load_constituents(bad) == []


# --------------------------------------------------------------------------- #
# the nightly run (providers faked: no network)
# --------------------------------------------------------------------------- #


class FakeBreadth:
    def __init__(self, counts):
        self._counts = counts

    def history(self):
        return self._counts


class FakeCloses:
    def __init__(self, closes):
        self._closes = closes
        self.calls: list[tuple[list[str], int]] = []

    def closes(self, symbols, days=3):
        self.calls.append((list(symbols), days))
        return self._closes


def seed_bars(symbol: str, closes: list[float], last: date) -> None:
    from src.storage.price_history import Bar, append_bars

    days = pd.bdate_range(end=pd.Timestamp(last), periods=len(closes))
    append_bars(symbol, [Bar(d.date(), c, c, c, c, 0.0) for d, c in zip(days, closes, strict=True)])


def test_the_nightly_run_records_counts_the_oscillator_and_both_signals(db, monkeypatch, tmp_path):
    from src.orchestrator import eod_report
    from src.storage import les_state

    last = date(2026, 11, 13)
    prev = date(2026, 11, 12)
    # 70 sessions of tt history ending the day before the last bar (our own count supplies the last)
    history = [
        BreadthCount(day=d.date(), adv=45 + (i % 3), dec=55 - (i % 3), source="tt")
        for i, d in enumerate(pd.bdate_range(end=pd.Timestamp(prev), periods=70))
    ]
    constituents = [f"N{i:03d}" for i in range(100)]
    path = tmp_path / "c.yaml"
    path.write_text("ndx: [" + ", ".join(constituents) + "]\n")
    monkeypatch.setattr(les_state, "CONSTITUENTS_PATH", path)
    closes = {
        prev: {s: 10.0 for s in constituents},
        last: {s: (11.0 if i < 30 else 9.0) for i, s in enumerate(constituents)},
    }
    fake_closes = FakeCloses(closes)
    monkeypatch.setattr("src.data.factory.get_breadth_provider", lambda: FakeBreadth(history))
    monkeypatch.setattr("src.data.factory.get_closes_provider", lambda: fake_closes)
    seed_bars("QQQ", list(np.linspace(100, 200, 300)), last)
    seed_bars("SOXX", list(np.linspace(100, 150, 300)), last)

    out = eod_report.record_breadth_and_les()

    assert out["tt_new"] == 70 and out["own_new"] == 1
    assert fake_closes.calls == [(constituents, 3)]
    own = les_state.load_counts("own")
    assert [(c.day, c.adv, c.dec) for c in own] == [(last, 30, 70)]
    recent = les_state.latest_osc(5)
    assert recent and recent[-1][0] == last  # the oscillator reaches the last session
    for index in ("QQQ", "SOXX"):
        sig = les_state.latest_signal(index)
        assert sig is not None and sig.asof == last and sig.trend_up is True
    # re-running changes nothing: every insert is idempotent
    again = eod_report.record_breadth_and_les()
    assert again["tt_new"] == 0 and again["own_new"] == 0


def test_the_nightly_run_without_a_constituent_list_uses_the_history_alone(
    db, monkeypatch, tmp_path
):
    from src.orchestrator import eod_report
    from src.storage import les_state

    monkeypatch.setattr(les_state, "CONSTITUENTS_PATH", tmp_path / "missing.yaml")
    fake_closes = FakeCloses({})
    monkeypatch.setattr(
        "src.data.factory.get_breadth_provider",
        lambda: FakeBreadth([BreadthCount(day=D0, adv=50, dec=50, source="tt")]),
    )
    monkeypatch.setattr("src.data.factory.get_closes_provider", lambda: fake_closes)
    out = eod_report.record_breadth_and_les()
    assert out["tt_new"] == 1 and out["own_new"] == 0
    assert fake_closes.calls == []  # no list, no download
    assert les_state.latest_signal("QQQ") is None  # no bars: no signal, and nothing invented


def test_a_thin_own_count_is_not_recorded(db, monkeypatch, tmp_path):
    """Fewer than 90% of the constituents with a close on either day: the count would be a
    distortion, so it is skipped (the history alone feeds the oscillator)."""
    from src.orchestrator import eod_report
    from src.storage import les_state

    constituents = [f"N{i:03d}" for i in range(100)]
    path = tmp_path / "c.yaml"
    path.write_text("ndx: [" + ", ".join(constituents) + "]\n")
    monkeypatch.setattr(les_state, "CONSTITUENTS_PATH", path)
    last, prev = date(2026, 11, 13), date(2026, 11, 12)
    closes = {
        prev: {s: 10.0 for s in constituents},
        last: {s: 11.0 for s in constituents[:80]},  # 20 constituents have no close today
    }
    monkeypatch.setattr("src.data.factory.get_breadth_provider", lambda: FakeBreadth([]))
    monkeypatch.setattr("src.data.factory.get_closes_provider", lambda: FakeCloses(closes))
    out = eod_report.record_breadth_and_les()
    assert out["own_new"] == 0 and les_state.load_counts("own") == []


def test_the_test_suite_never_reaches_the_breadth_network():
    """conftest points both providers at empty fakes; a test that needs data patches its own."""
    from src.data import factory

    assert factory.get_breadth_provider().history() == []
    assert factory.get_closes_provider().closes(["AAPL"], days=3) == {}
