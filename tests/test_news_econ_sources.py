from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from src.data.forexfactory_backend import parse_ff
from src.data.nasdaq_backend import NasdaqEconActualsProvider, clean_value, parse_nasdaq_econ

FIX = Path(__file__).parent / "fixtures" / "news"


def test_ff_parses_aware_et_times_and_skips_garbage() -> None:
    items = parse_ff(json.loads((FIX / "ff_thisweek.json").read_text()))
    assert "Broken" not in {i.title for i in items}
    claims = next(i for i in items if i.title == "Unemployment Claims")
    assert claims.scheduled_at.utcoffset().total_seconds() == -4 * 3600
    assert (claims.forecast, claims.previous) == ("200K", "197K")
    assert next(i for i in items if i.title == "FOMC Meeting Minutes").forecast is None


def test_clean_value() -> None:
    assert clean_value("&nbsp;") is None and clean_value(" ") is None and clean_value("") is None
    assert clean_value(None) is None
    assert clean_value(" 1,716K ") == "1,716K"


def test_nasdaq_non_values_and_untimed_rows() -> None:
    rows = parse_nasdaq_econ(
        json.loads((FIX / "nasdaq_econ_2026-10-09.json").read_text()), date(2026, 10, 8)
    )
    assert all(r.et_day == date(2026, 10, 8) for r in rows)
    titles = {r.title: r for r in rows}
    assert "Interest Rate Decision" not in titles  # India filtered out
    assert (
        titles["Initial Jobless Claims"].actual == "197K"
        and titles["Initial Jobless Claims"].et_time == "08:30"
    )
    assert (
        titles["Fed Waller Speaks"].actual is None and titles["Fed Waller Speaks"].consensus is None
    )
    assert titles["Synthetic untimed row"].et_time is None
    assert titles["Synthetic tentative row"].et_time is None


def test_actuals_requests_et_day_plus_offset(monkeypatch) -> None:
    asked: list[str] = []

    def fake_get(url, params, headers, timeout):
        asked.append(params["date"])
        return httpx.Response(
            200,
            json=json.loads((FIX / "nasdaq_econ_2026-10-09.json").read_text()),
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("src.data.nasdaq_backend.httpx.get", fake_get)
    rows = NasdaqEconActualsProvider(date_offset_days=1).actuals(date(2026, 10, 8))
    assert asked == ["2026-10-09"] and rows and rows[0].et_day == date(2026, 10, 8)


def test_probe_infers_offset() -> None:
    from scripts.news_probe import infer_offset

    ff = {date(2026, 10, 8): {"unemployment claims"}}
    nd = {
        date(2026, 10, 8): {"mba mortgage applications"},
        date(2026, 10, 9): {"initial jobless claims", "continuing jobless claims"},
    }
    assert infer_offset(ff, nd, synonyms={"unemployment claims": "initial jobless claims"}) == 1
    assert infer_offset({}, {}, synonyms={}) is None
