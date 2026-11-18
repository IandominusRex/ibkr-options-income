"""The bridge hedge's record and review (risk-envelope Task 37; spec §3.10.2, §3.10.11, H2).

``src/reporting/hedge.py`` is read-only; ``scripts/hedge_report.py`` prints it and, with
``--review``, posts the one-page record. Nothing here connects to IBKR."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from src.hedge import store
from src.reporting import hedge as report
from tests.test_hedge_book import hedge_candidate, seed_open_hedge

TODAY = date(2026, 11, 18)


def test_premium_paid_received_and_net(hedge_db) -> None:
    store.start_programme(instrument="QQQ", started_on=TODAY, nlv0=650_000.0, glide_end=None)
    hid = seed_open_hedge(hedge_candidate(contracts=2, debit=6.0))
    store.record_fill(hedge_id=hid, qty=-1, price=9.0)
    rep = report.build_report(TODAY)
    assert (rep.paid, rep.received, rep.net) == (1200.0, 900.0, 300.0)
    text = report.render(rep)
    assert "net $300" in text and "(0.05% of NLV0)" in text


def test_no_bridge_says_so(hedge_db) -> None:
    assert "No bridge has started" in report.render(report.build_report(TODAY))


def test_execution_against_the_approved_mid(hedge_db) -> None:
    store.start_programme(instrument="QQQ", started_on=TODAY, nlv0=650_000.0, glide_end=None)
    cand = hedge_candidate(debit=6.0)
    oid = store.record_order(cand, limit_price=6.0)
    store.update_order(oid, state="filled", filled_qty=2, avg_fill_price=6.15)
    rep = report.build_report(TODAY)
    assert rep.slippage == [("hedge:h20261118-a", 6.0, 6.15)]
    assert "mean +0.15 a share" in report.render(rep)


def _closes(path: list[float]) -> list[tuple[date, float]]:
    start = date(2026, 1, 1)
    return [(start + timedelta(days=i), c) for i, c in enumerate(path)]


def test_down_legs_are_one_sigma60_below_the_60_session_high() -> None:
    calm = [100.0 * (1 + 0.002 * math.sin(i)) for i in range(80)]
    slide = [calm[-1] * (1 - 0.03 * k) for k in range(1, 8)]  # -3% a session for 7 sessions
    rebound = [slide[-1] * (1 + 0.05 * k) for k in range(1, 6)]
    legs = report.down_legs(_closes(calm + slide + rebound))
    assert len(legs) == 1
    start, trough, exit_, move = legs[0]
    assert start < trough and exit_ is not None and trough < exit_
    assert move < -15.0
    assert report.down_legs(_closes(calm)) == []


def test_cover_ratio_and_r_squared() -> None:
    assert report._cover(500.0, -2000.0) == pytest.approx(0.25)
    assert report._cover(500.0, 100.0) is None  # no loss: no cover ratio
    xs = [0.01, -0.02, 0.015, -0.005, 0.02]
    assert report.r_squared(xs, [2 * x for x in xs]) == pytest.approx(1.0)
    assert report.r_squared(xs[:2], xs[:2]) is None


def test_a_leg_reads_the_hedge_and_the_book_from_their_own_records(hedge_db, monkeypatch) -> None:
    store.start_programme(
        instrument="QQQ", started_on=date(2026, 1, 1), nlv0=650_000.0, glide_end=None
    )
    calm = [100.0 * (1 + 0.002 * math.sin(i)) for i in range(80)]
    slide = [calm[-1] * (1 - 0.03 * k) for k in range(1, 8)]
    rebound = [slide[-1] * (1 + 0.05 * k) for k in range(1, 6)]
    closes = _closes(calm + slide + rebound)
    ((start, trough, exit_, _),) = report.down_legs(closes)
    monkeypatch.setattr(report, "_closes", lambda symbol: closes)
    nlv = {d: 650_000.0 for d, _ in closes}
    nlv.update({trough: 600_000.0, exit_: 630_000.0})
    monkeypatch.setattr(report, "_nlv_by_day", lambda now: nlv)
    values = {start: 1_000.0, trough: 13_500.0, exit_: 6_000.0}
    monkeypatch.setattr(report, "_value_by_day", lambda: values)
    (leg,) = report.build_report(exit_ + timedelta(days=1)).legs
    assert leg.cover_trough == pytest.approx(12_500.0 / 50_000.0)
    assert leg.cover_exit == pytest.approx(5_000.0 / 20_000.0)


def test_review_record_ends_default_off(hedge_db) -> None:
    store.start_programme(instrument="XND", started_on=TODAY, nlv0=650_000.0, glide_end=None)
    text = report.review_record(today=TODAY)
    assert text.rstrip().endswith("Default: off.")
    assert "fresh ruling" in text and "2% of NLV a rolling year" in text


def test_the_script_prints_and_posts_only_with_review(hedge_db, monkeypatch, capsys) -> None:
    from scripts import hedge_report

    posted: list[str] = []

    async def notice(text: str, **kw: object) -> bool:
        posted.append(text)
        return True

    monkeypatch.setattr("src.notify.notices.send_notice", notice)
    monkeypatch.setattr(hedge_report, "today_et", lambda: TODAY)
    assert hedge_report.main([]) == 0
    assert posted == [] and "Bridge hedge record" in capsys.readouterr().out
    assert hedge_report.main(["--review"]) == 0
    assert len(posted) == 1 and "Default: off." in posted[0]


def test_the_report_module_is_read_only() -> None:
    from pathlib import Path

    text = Path("src/reporting/hedge.py").read_text()
    for writer in ("session.add", "session.merge", "session.delete", "session.commit", "INSERT"):
        assert writer not in text
    assert "src.claude" not in text and "src.hedge" not in text


def test_marks_feed_the_value_series(hedge_db) -> None:
    hid = seed_open_hedge(hedge_candidate(contracts=2))
    store.record_mark(
        session_date=TODAY,
        hedge_id=hid,
        contracts=2,
        mark=7.0,
        source="captured",
        marked_at=datetime(2026, 11, 18, 16, 0, tzinfo=UTC),
    )
    assert report._value_by_day() == {TODAY: 1400.0}
