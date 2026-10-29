"""The shadow record's report (value book spec §6.8, §7, §11, §12): clustered errors, the go-live
line, the three policies side by side, the ranked record, postmortems, and the script."""

from __future__ import annotations

from datetime import date, datetime

import pytest

import src.value.store as store
from scripts import value_report
from src.common.config import get_config
from src.value.report import (
    SURVIVORSHIP,
    EntryView,
    EventView,
    LegView,
    RankedView,
    closest_gate,
    clustered_mean,
    go_live_line,
    postmortem,
    ranked_section,
    render,
)
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValueShadowEventRow,
    ValueShadowLegRow,
    ValueShadowRow,
    init_value_db,
    value_session,
)
from tests.value_fixtures import inputs

D1, D2, D3 = date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)


def test_errors_are_clustered_by_entry_date() -> None:
    s = clustered_mean([(D1, 0.10), (D1, 0.06), (D2, -0.02), (D3, 0.04)])
    assert (s.n, s.clusters) == (4, 3)
    assert s.mean == pytest.approx(0.045)
    assert s.se == pytest.approx(0.029288436284649957)  # sqrt(3/2 x 0.00915 / 16)
    assert s.t == pytest.approx(1.5364425591947515)
    one_day = clustered_mean([(D1, 0.10), (D1, 0.06)])
    assert one_day.se is None and one_day.t is None  # one market day is one observation
    assert clustered_mean([]).mean is None


def _entry(i: int, day: date, ret63: float | None, **kw) -> EntryView:
    base = dict(
        id=i,
        track="baseline",
        kind="ready",
        list_name="deep_value",
        symbol=f"N{i}",
        universe="evidence",
        status="open",
        signal_date=day,
        entry_date=day,
        entry_price=100.0,
        fair_value=140.0,
        margin_of_safety=0.29,
        ruleset_version="v2",
        returns={21: 0.01, 63: ret63, 126: None},
        spy={21: 0.0, 63: 0.01 if ret63 is not None else None, 126: None},
    )
    base.update(kw)
    return EntryView(**base)


def test_the_go_live_line_counts_only_the_tracks_ready_entries() -> None:
    entries = [_entry(i, D1, 0.05) for i in range(3)] + [
        _entry(9, D2, 0.05, kind="control_valuation")
    ]
    line = go_live_line(entries, "baseline")
    assert "n 3 of 30 needed" in line and "+4.0%" in line and "not enough entries yet" in line
    many = [_entry(i, [D1, D2, D3][i % 3], -0.02) for i in range(30)]
    assert "at or below zero: do not go live" in go_live_line(many, "baseline")


def test_a_zero_spy_return_is_a_real_return_not_a_missing_one() -> None:
    """Review M4: SPY flat over the horizon is 0.0, not unknown."""
    flat = _entry(1, D1, 0.05, spy={21: 0.0, 63: 0.0, 126: None})
    assert "n 1 of 30 needed" in go_live_line([flat], "baseline")


def test_the_ranked_section_shows_each_bucket_and_the_spread() -> None:
    rows = [
        RankedView(
            formed_on=D1, list_name="deep_value", bucket=b, n=5, closed_on=D3, ret=r, spy_ret=0.01
        )
        for b, r in (("top", 0.03), ("bottom", -0.01), ("all", 0.01))
    ]
    text = "\n".join(ranked_section(rows))
    assert "top     months   1  mean +3.0%/month" in text
    assert "top - bottom: mean +4.0%/month over 1" in text
    assert "no month closed yet" in "\n".join(ranked_section([]))


def test_the_gate_closest_to_wrong_is_the_passing_check_with_least_room() -> None:
    card = build_scorecard(inputs(), get_config().value)
    deep = closest_gate(card, "deep_value")
    assert deep is not None and deep.id == "timing.trend"  # 30.00 vs the 27.52 SMA200: 9.0%
    growth = closest_gate(card, "quality_growth")
    assert growth is not None and growth.id == "timing.not_breaking_down"  # 9.005% < ROIC's 9.04%


def test_a_postmortem_tells_the_whole_story() -> None:
    card = build_scorecard(inputs(), get_config().value)
    e = _entry(1, D1, 0.05, status="closed", scorecard_json=card.model_dump_json())
    legs = [
        LegView(
            shadow_id=1,
            policy="value",
            closed=True,
            exit_date=D3,
            ret=0.2,
            spy_ret=0.05,
            max_drawdown=-0.04,
            sessions=40,
            sells=2,
        )
    ]
    events = [
        EventView(shadow_id=1, policy="value", day=D2, kind="half", price=140.0, fraction=0.5),
        EventView(shadow_id=1, policy="value", day=D3, kind="fill", price=141.0, fraction=0.5),
    ]
    text = "\n".join(postmortem(e, legs, events, 150.0))
    assert "fair value then 140.0 (margin of safety +29.0%), now 150.0" in text
    assert "value: exit 2026-01-07 return +20.0% (SPY +5.0%)" in text
    assert "2026-01-06 half; 2026-01-07 fill 50% @ 141.00" in text
    assert "closest to wrong: timing.trend 30.00 vs bar 27.52" in text


def test_render_leads_with_the_survivorship_caveat_and_marks_the_live_policy() -> None:
    entries = [_entry(1, D1, 0.05)]
    legs = [
        LegView(
            shadow_id=1,
            policy=p,
            closed=True,
            ret=0.1,
            spy_ret=0.02,
            max_drawdown=-0.05,
            sessions=30,
            sells=1,
        )
        for p in ("full", "value", "hold12")
    ]
    text = render(
        entries,
        legs,
        [],
        [],
        fair_values_now={},
        live_policy="value",
        track="baseline",
        postmortems=False,
    )
    assert text.splitlines()[1] == SURVIVORSHIP
    assert "value (live)" in text and "full (diagnostic)" in text and "hold12 (diagnostic)" in text
    assert "63 sessions" in text and "excess +4.0%" in text


@pytest.fixture()
def value_db(tmp_path, monkeypatch):
    monkeypatch.setattr(
        store, "_resolve_url", lambda: f"sqlite:///{(tmp_path / 'value.db').as_posix()}"
    )
    store.reset_engine()
    init_value_db()
    yield
    store.reset_engine()


def test_the_script_reads_value_db_and_prints_the_record(value_db, capsys) -> None:
    card = build_scorecard(inputs(), get_config().value)
    with value_session() as s:
        row = ValueShadowRow(
            track="baseline",
            kind="ready",
            list_name="deep_value",
            symbol="STDY",
            universe="trading",
            signal_date=D1,
            status="closed",
            verdict="READY",
            fingerprint_key="0" * 16,
            ruleset_version="v2",
            ruleset_hash="x",
            scorecard_json=card.model_dump_json(),
            created_at=datetime(2026, 1, 5),
            entry_date=D2,
            entry_price=30.0,
            spy_entry_price=500.0,
            ret_21=0.02,
            spy_21=0.01,
            ret_63=0.05,
            spy_63=0.02,
            ret_126=0.08,
            spy_126=0.03,
        )
        s.add(row)
        s.flush()
        s.add(
            ValueShadowLegRow(
                shadow_id=row.id,
                policy="value",
                state_json="{}",
                closed=True,
                exit_date=D3,
                ret_exit=0.1,
                spy_ret_exit=0.01,
                sessions=3,
                sells=1,
                max_drawdown=-0.02,
            )
        )
        s.add(
            ValueShadowEventRow(
                shadow_id=row.id, policy="value", day=D3, kind="fill", price=33.0, fraction=1.0
            )
        )
    assert value_report.main(["--postmortems"]) == 0
    out = capsys.readouterr().out
    assert SURVIVORSHIP in out
    assert "[baseline · deep_value · ready] 1 entries" in out
    assert "## STDY deep_value #1" in out and "2026-01-07 fill 100% @ 33.00" in out
