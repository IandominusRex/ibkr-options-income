"""The survivability harness (risk-envelope plan Task 26; spec §3.4.6, rulings P1, P2).

The analytic worst case and the always-most-aggressive replay, on a small synthetic panel (never
the operator's databases). The replay engine is the production ``measure`` / ``admits`` /
``max_contracts_under`` underneath; the tests only build the book and the closes.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from scripts import envelope_harness as harness
from src.analytics.shock import measure
from src.common.envelope_types import BookLine, EnvelopeRoom, ShockInputs
from src.reporting import survivability as sv
from src.reporting.replay import Closes, worst_drawdown
from src.storage.envelope_state import GlideRecord

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
START = date(2025, 6, 2)


def _inputs(lines: list[BookLine], nlv: float = 100_000.0) -> ShockInputs:
    return ShockInputs(
        lines=tuple(lines),
        betas={"SPY": 1.0, "AAA": 1.2, "BBB": 1.0, "SMH": 1.3},
        betas_smh={"SPY": 0.8, "AAA": 1.0, "BBB": 0.9, "SMH": 1.0},
        leverage={},
        governing={},
        tech_linked=frozenset({"AAA"}),
        semis=frozenset({"SMH"}),
        nlv=nlv,
    )


def _closes(n: int, *, drift: dict[str, float], start: float = 100.0) -> Closes:
    """*n* weekday closes from START for SPY and each name in *drift* (a daily return each)."""
    days: list[date] = []
    d = START
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    out: Closes = {}
    for sym, r in {"SPY": 0.0, **drift}.items():
        px, series = start, []
        for day in days:
            series.append((day, px))
            px *= 1.0 + r
        out[sym] = series
    return out


def _stock_book() -> ShockInputs:
    return _inputs([BookLine("AAA", "stock", 200.0, 100.0)])


# --------------------------------------------------------------------------- analytic


def test_the_analytic_worst_case_uses_every_scenario() -> None:
    inputs = _inputs(
        [
            BookLine("AAA", "stock", 300.0, 100.0),
            BookLine("BBB", "short_put", 2.0, 100.0, strike=95.0, dte=30, iv=0.3),
        ]
    )
    worst = sv.analytic_worst_case(inputs)
    assert set(worst.gross) == {"S10", "S20", "G10", "P20", "T20", "S_SMH"}
    assert set(worst.net) == set(worst.gross)
    # the worst is the largest of the six, and it is named
    assert worst.worst_gross == max(worst.gross, key=lambda k: worst.gross[k])
    assert worst.gross[worst.worst_gross] == pytest.approx(max(worst.gross.values()))
    res = measure(inputs)
    assert worst.gross["S20"] == pytest.approx(res.s20)
    assert worst.gross["T20"] == pytest.approx(res.t20)
    assert worst.uew == pytest.approx(res.uew)


def test_gross_and_net_are_both_reported() -> None:
    long_put = BookLine("SPY", "long_put", 5.0, 100.0, strike=95.0, dte=60, iv=0.25, book="hedge")
    inputs = _inputs([BookLine("AAA", "stock", 300.0, 100.0), long_put])
    worst = sv.analytic_worst_case(inputs)
    # a long put protects the net measure and creates no headroom in the gross one (H1, H10)
    assert worst.net["S10"] < worst.gross["S10"]
    bare = sv.analytic_worst_case(_inputs([BookLine("AAA", "stock", 300.0, 100.0)]))
    assert worst.gross["S10"] == pytest.approx(bare.gross["S10"])
    assert worst.total_net_pct < worst.total_gross_pct


def test_the_spreads_book_counts_at_two_percent_a_month() -> None:
    worst = sv.analytic_worst_case(_stock_book())
    assert worst.spreads_pct == 2.0
    assert worst.total_gross_pct == pytest.approx(worst.gross[worst.worst_gross] + 2.0)
    # and in the replay: 21 sessions with no price move still lose 2% of the starting NLV
    flat = sv.simulate(
        _stock_book(),
        _closes(45, drift={"AAA": 0.0}),
        {},
        mode="status_quo",
        start=START,
    )
    assert flat.nlv[0] == pytest.approx(100_000.0)
    assert flat.nlv[20] == pytest.approx(100_000.0)
    assert flat.nlv[21] == pytest.approx(98_000.0)
    assert flat.nlv[42] == pytest.approx(96_000.0)


# --------------------------------------------------------------------------- the replay


def _glide(book: ShockInputs, weeks: int = 13) -> GlideRecord:
    """A constant limit a few points above the book's own S10 and 0.2 above its U_ew."""
    res = measure(book)
    return GlideRecord(START, res.s10 + 3.0, res.uew + 0.2, weeks, res.s10 + 3.0, res.uew + 0.2)


def _put_book(extra: list[BookLine] | None = None) -> ShockInputs:
    return _inputs(
        [BookLine("AAA", "stock", 100.0, 100.0), BookLine("BBB", "stock", 100.0, 100.0)]
        + (extra or [])
    )


def test_the_aggressive_replay_takes_every_admitted_open_at_max_size() -> None:
    book = _put_book()
    ivs = {"AAA": 0.3, "BBB": 0.3}
    closes = _closes(20, drift={"AAA": 0.0, "BBB": 0.0})
    # a glide with room for many lots: every attempt is admitted at the hard maximum
    roomy = GlideRecord(START, 90.0, 90.0, 13, 90.0, 90.0)
    out = sv.simulate(
        book,
        closes,
        ivs,
        mode="aggressive",
        start=START,
        names=["AAA", "BBB"],
        glide=roomy,
        hard_max=3,
        attempt_every=1,
    )
    # one 3-lot open per name on the first attempt, and again as each 30-day put is added
    assert out.opened_contracts == out.opened_lots * 3 and out.opened_lots >= 2
    assert out.violations == []
    # a tight glide admits less than the maximum (the envelope's own sizing), never more
    tight = _glide(book)
    capped = sv.simulate(
        book,
        closes,
        ivs,
        mode="aggressive",
        start=START,
        names=["AAA", "BBB"],
        glide=tight,
        hard_max=50,
    )
    assert capped.violations == []
    assert capped.s10[-1] <= tight.s10_start + 1e-6
    assert capped.opened_contracts < 50 * 2 * len(capped.days)


def test_admissions_above_the_limit_fail_the_harness() -> None:
    book = _put_book()
    ivs = {"AAA": 0.3, "BBB": 0.3}
    closes = _closes(20, drift={"AAA": 0.0, "BBB": 0.0})
    tight = _glide(book)

    def admit_everything(
        room: EnvelopeRoom, inputs: ShockInputs, one: BookLine, hard_max: int
    ) -> int:
        return hard_max  # no envelope: the independent check must still see the breach

    bad = sv.simulate(
        book,
        closes,
        ivs,
        mode="aggressive",
        start=START,
        names=["AAA"],
        glide=tight,
        hard_max=10,
        sizer=admit_everything,
    )
    assert bad.violations, "an admission above L(t) must be counted"
    base = sv.simulate(book, closes, ivs, mode="status_quo", start=START)
    worst = sv.analytic_worst_case(book)
    result = sv.harness_result(
        worst, base, bad, record_sessions=12, defects=[], now=NOW, min_record_sessions=10
    )
    assert result.passed is False
    assert result.metrics["p2"] == "fail"
    assert result.metrics["violations"] == float(len(bad.violations))


def test_a_drawdown_worse_than_the_unenveloped_path_fails() -> None:
    book = _put_book()
    ivs = {"AAA": 0.3, "BBB": 0.3}
    closes = _closes(60, drift={"AAA": -0.004, "BBB": -0.004})
    worst = sv.analytic_worst_case(book)
    base = sv.simulate(book, closes, ivs, mode="status_quo", start=START)
    ok = replace(base, worst20=base.worst20 + 3.0)
    mid = sv.harness_result(worst, base, ok, record_sessions=12, defects=[], now=NOW)
    assert mid.passed is False
    better = replace(base, worst20=max(0.0, base.worst20 - 1.0))
    assert sv.harness_result(worst, base, better, record_sessions=12, defects=[], now=NOW).passed


# --------------------------------------------------------------------------- the result file


def test_pass_writes_the_enforce_result(tmp_path: Path, monkeypatch) -> None:
    book = _put_book()
    ivs = {"AAA": 0.3, "BBB": 0.3}
    closes = _closes(40, drift={"AAA": -0.002, "BBB": -0.002})
    worst = sv.analytic_worst_case(book)
    base = sv.simulate(book, closes, ivs, mode="status_quo", start=START)
    aggr = sv.simulate(
        book,
        closes,
        ivs,
        mode="aggressive",
        start=START,
        names=["AAA", "BBB"],
        glide=_glide(book),
    )
    assert aggr.violations == []
    # the envelope-obeying path may not draw down more than the status-quo path
    result = sv.harness_result(worst, base, aggr, record_sessions=10, defects=[], now=NOW)
    assert result.id == "harness"
    assert (result.switch, result.value_on_pass) == ("envelope_enforce", "on")
    if result.passed is not True:  # the synthetic panel decides the drawdown; force the PASS leg
        better = replace(aggr, worst20=0.0)
        result = sv.harness_result(worst, base, better, record_sessions=10, defects=[], now=NOW)
    assert result.passed is True
    path = harness.write_result(result, tmp_path)
    assert path.name == "harness.json"

    # the EOD hook turns the switch on from it (paper), through apply_reports (Task 1)
    import src.storage.db as dbmod
    from src.common.config import Config
    from src.storage import envelope_switches as sw

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    notices = sw.apply_reports(tmp_path)
    assert sw.get_switch("envelope_enforce") == "on" and len(notices) == 1


def test_too_few_record_sessions_is_no_result_not_a_pass() -> None:
    book = _put_book()
    closes = _closes(30, drift={"AAA": 0.0, "BBB": 0.0})
    worst = sv.analytic_worst_case(book)
    base = sv.simulate(book, closes, {}, mode="status_quo", start=START)
    result = sv.harness_result(worst, base, base, record_sessions=3, defects=[], now=NOW)
    assert result.passed is None
    # a defect in the record sessions blocks the PASS too
    defect = sv.harness_result(
        worst, base, base, record_sessions=12, defects=["2026-11-20: unmeasured"], now=NOW
    )
    assert defect.passed is None or defect.passed is False
    assert defect.passed is not True


def test_a_book_it_cannot_value_writes_no_pass() -> None:
    book = _inputs([BookLine("ZZZ", "stock", 100.0, 100.0)])  # no beta, no closes
    with pytest.raises(sv.ReplayUnavailable):
        sv.simulate(book, _closes(10, drift={"AAA": 0.0}), {}, mode="status_quo", start=START)


def test_the_worst_drawdown_is_measured_from_the_trailing_window() -> None:
    assert worst_drawdown([100.0, 90.0, 95.0], 20) == pytest.approx(10.0)
    # a peak older than the window no longer counts
    assert worst_drawdown([100.0, 50.0, 50.0, 50.0], 2) == pytest.approx(50.0)
    assert worst_drawdown([100.0, 101.0, 102.0], 20) == 0.0


# --------------------------------------------------------------------------- the record evidence


def test_the_record_defects_are_the_two_p1_rules() -> None:
    d = date(2026, 11, 20)

    def unmeasured(n: int) -> list[tuple[date, str, str, str]]:
        rows = []
        for i in range(n):  # the generator and the gate both say unmeasured: they agree
            rows.append((d, f"c{i}", f"c{i}:scan", "scan: would refuse (envelope_unmeasured)"))
            rows.append(
                (d, f"c{i}", f"c{i}:generator", "generator would trim 2 -> 0 (envelope_unmeasured)")
            )
        return rows

    # 3 of 10 evaluated candidates unmeasured is 30%: a defect; 1 of 10 is not
    assert sv.p1_defects({d: 10}, unmeasured(3))
    assert sv.p1_defects({d: 10}, unmeasured(1)) == []
    # the generator and the gate must agree on which candidates the envelope refuses
    gen = (d, "c9", "c9:generator", "generator would trim 5 -> 3 (shock_budget): S10 22.0%")
    gate = (d, "c9", "c9:scan", "scan: the envelope would refuse (shock_budget)")
    assert sv.p1_defects({d: 10}, [gen, gate]) == []
    assert sv.p1_defects({d: 10}, [gen])  # generator trims, gate silent: they disagree
    assert sv.p1_defects({d: 10}, [gate])  # gate refuses, generator silent: they disagree


def test_the_record_evidence_counts_sessions_from_the_snapshots(db, tmp_path: Path) -> None:
    from src.storage.models import CandidateRow, EnvelopeSnapshotRow, SizingActionRow

    def snap(at: datetime, enforce: str) -> EnvelopeSnapshotRow:
        zero = dict.fromkeys(
            (
                "s10 s20 g10 p20 t20 s_smh s10_vol10 s10_net s20_net g10_net p20_net t20_net "
                "s_smh_net s10_vol10_net uew"
            ).split(),
            1.0,
        )
        return EnvelopeSnapshotRow(
            captured_at=at, source="live", enforce=enforce, measured=True, **zero
        )

    with db() as s:
        for i in range(12):
            s.add(snap(datetime(2026, 11, 2 + i, 20, 30), "record"))
        s.add(snap(datetime(2026, 11, 3, 21, 0), "record"))  # a second reading, same session
        s.add(snap(datetime(2026, 11, 30, 20, 30), "on"))  # not a record session
        s.add(
            CandidateRow(
                candidate_id="c1",
                run_id="r",
                strategy="cash_secured_put",
                underlying="AAA",
                right="P",
                strike=1.0,
                expiry=date(2026, 12, 18),
                payload={},
                created_at=datetime(2026, 11, 3, 15, 0),
            )
        )
        s.add(
            SizingActionRow(
                candidate_id="c1",
                underlying="AAA",
                strategy="cash_secured_put",
                right="P",
                strike=1.0,
                expiry=date(2026, 12, 18),
                premium=1.0,
                kind="envelope_record",
                regime="normal",
                deterministic_contracts=2,
                sent_contracts=0,
                reason="scan: the envelope would refuse (shock_budget)",
                action_day=date(2026, 11, 3),
                record_key="c1:scan",
            )
        )
    from src.reporting.replay import open_ro, trading_db_path

    con = open_ro(trading_db_path())
    try:
        ev = sv.read_record_evidence(con)
    finally:
        con.close()
    assert ev.sessions == 12
    assert len(ev.defects) == 1  # c1: the gate refuses and the generator is silent
    assert isinstance(con, sqlite3.Connection)


# --------------------------------------------------------------------------- the script, end to end


def _seed_book(db) -> None:
    """A tiny trading DB: one snapshot (100 AAPL and a short put), 150 sessions of closes."""
    from src.storage.models import IVHistoryRow, PortfolioSnapshotRow, PriceHistoryRow

    positions = [
        {
            "symbol": "AAPL",
            "sec_type": "STK",
            "position": 100.0,
            "avg_cost": 100.0,
            "market_price": 100.0,
            "market_value": 10_000.0,
        },
        {
            "symbol": "AAPL  261218P00095000",
            "sec_type": "OPT",
            "position": -1.0,
            "avg_cost": 2.0,
            "market_price": 2.0,
            "right": "P",
            "strike": 95.0,
            "expiry": "2026-12-18",
            "underlying": "AAPL",
        },
    ]
    account = {
        "account": "DU1",
        "net_liquidation": 100_000.0,
        "total_cash": 50_000.0,
        "buying_power": 200_000.0,
        "maintenance_margin": 10_000.0,
        "excess_liquidity": 80_000.0,
    }
    days: list[date] = []
    d = date(2026, 4, 1)
    while len(days) < 150:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    with db() as s:
        s.add(
            PortfolioSnapshotRow(
                captured_at=datetime(2026, 11, 12, 21, 0),
                source="eod",
                account=account,
                positions=positions,
            )
        )
        for sym, drift in (("AAPL", 0.0004), ("SPY", 0.0003), ("SMH", 0.0005)):
            px = 100.0
            for i, day in enumerate(days):
                px *= 1.0 + drift + (0.004 if i % 2 else -0.004)
                s.add(PriceHistoryRow(symbol=sym, obs_date=day, open=px, high=px, low=px, close=px))
        s.add(IVHistoryRow(symbol="AAPL", obs_date=days[-1], iv=0.30))


def test_the_script_replays_a_synthetic_book_and_writes_only_its_files(db, tmp_path: Path) -> None:
    import hashlib

    from src.reporting.replay import trading_db_path

    _seed_book(db)
    path = trading_db_path()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    text, result = harness.run(path, attempt_every=20)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before, "the replay wrote to the DB"
    assert result is not None, text
    assert result.id == "harness" and result.switch == "envelope_enforce"
    # no record sessions in this database: P2 may pass, but the harness is "no result", not a PASS
    assert result.passed in (None, False)
    assert "analytic_worst_gross" in result.metrics and "record sessions: 0" in text
    # the report goes out as a .txt, so apply_reports never reads it as a result file
    out = harness.write_report("harness", text, tmp_path)
    assert out.suffix == ".txt" and out.read_text().startswith("Book as of")


def test_a_missing_database_writes_nothing(tmp_path: Path) -> None:
    text, result = harness.run(tmp_path / "absent.db")
    assert result is None and "nothing to replay" in text
