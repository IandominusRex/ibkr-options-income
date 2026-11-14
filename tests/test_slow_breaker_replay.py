"""The slow-breaker threshold replay (risk-envelope plan Task 28; spec §3.4.5, ruling E14).

Synthetic net-liquidation series only. The drawdown is the breaker's own measure: the fall from the
highest value of the trailing 20 sessions.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from scripts import slow_breaker_replay as sbr
from src.reporting.replay import drawdown_series
from src.storage import envelope_switches as sw

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _series(start: date, n: int, dips: list[tuple[int, float]], base: float = 100.0) -> sbr.Series:
    """*n* sessions at *base*, each dip a one-session fall of that percent at that index, regained
    the next session (so the trailing 20-session high resets and each dip is its own episode)."""
    days = _weekdays(start, n)
    values = [base] * n
    for i, pct in dips:
        values[i] = base * (1.0 - pct / 100.0)
    return list(zip(days, values, strict=True))


def test_the_drawdown_is_the_breakers_trailing_window_measure() -> None:
    dd = drawdown_series([100.0, 90.0, 95.0, 100.0], 20)
    assert dd == [0.0, 10.0, 5.0, 0.0]
    # a high older than the window no longer counts
    assert drawdown_series([100.0, 50.0, 50.0, 50.0], 2)[-1] == 0.0


def test_episodes_count_each_crossing_once() -> None:
    assert sbr.episodes([0, 9, 9.5, 0, 9, 0], 8) == 2
    assert sbr.episodes([9, 9, 0], 8) == 1  # a series that starts over it is one episode
    assert sbr.episodes([7, 7.9], 8) == 0


def test_threshold_choice_follows_the_rule() -> None:
    # the real series: a 10.5% slide inside Oct-Nov 2026
    real = _series(date(2026, 10, 1), 40, [(25, 10.5)], base=650_000.0)
    # the synthetic panel's first 12 months: three separate 9.5% dips
    synthetic = _series(date(2025, 6, 2), 330, [(40, 9.5), (120, 9.5), (200, 9.5)])
    choice = sbr.choose_threshold(real, synthetic)
    assert choice is not None
    by = {r.threshold: r for r in choice.rows}
    # 8%: trips in the slide, but 3 episodes in the first year: out
    assert by[8].trips_in_slide and by[8].episodes == 3 and not by[8].qualifies
    # 10%: trips (10.5 >= 10), no first-year episode (9.5 < 10): the lowest that qualifies
    assert by[10].qualifies
    # 12% and 15% do not trip in the slide at all
    assert not by[12].trips_in_slide and not by[15].trips_in_slide
    assert choice.value == "10" and not choice.fell_back and choice.slide_basis == "real"


def test_no_qualifying_threshold_falls_back_to_15() -> None:
    # a 7% slide trips none of {8, 10, 12, 15}
    real = _series(date(2026, 10, 1), 40, [(25, 7.0)], base=650_000.0)
    synthetic = _series(date(2025, 6, 2), 330, [(40, 9.5)])
    choice = sbr.choose_threshold(real, synthetic)
    assert choice is not None and choice.value == "15" and choice.fell_back
    result = sbr.e14_result(choice, now=NOW)
    assert result.passed is True and result.value_on_pass == "15"
    assert result.metrics["fell_back_to_15"] == "yes"


def test_a_short_real_series_leaves_the_slide_to_the_synthetic_one() -> None:
    real = _series(date(2026, 11, 9), 3, [(1, 12.0)])  # three sessions: not evidence
    synthetic = _series(
        date(2026, 4, 1), 200, [(150, 11.0)]
    )  # a slide inside Oct-Nov? index 150 ~ Oct 28
    choice = sbr.choose_threshold(real, synthetic)
    assert choice is not None and choice.slide_basis == "synthetic"
    # with neither series there is nothing to say
    assert sbr.choose_threshold([], []) is None
    assert sbr.e14_result(None, now=NOW).passed is None


def test_it_writes_the_e14_result_and_apply_reports_sets_the_threshold(
    tmp_path: Path, monkeypatch
) -> None:
    real = _series(date(2026, 10, 1), 40, [(25, 10.5)], base=650_000.0)
    synthetic = _series(date(2025, 6, 2), 330, [(40, 9.5), (120, 9.5), (200, 9.5)])
    result = sbr.e14_result(sbr.choose_threshold(real, synthetic), now=NOW)
    path = sbr.write_result(result, tmp_path)
    assert path.name == "E14.json"
    assert (result.switch, result.value_on_pass, result.passed) == ("slow_breaker", "10", True)

    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    assert len(sw.apply_reports(tmp_path)) == 1 and sw.get_switch("slow_breaker") == "10"


def test_the_script_reads_a_synthetic_database_read_only(db) -> None:
    import hashlib

    from src.reporting.replay import trading_db_path
    from tests.test_survivability import _seed_book

    _seed_book(db)
    path = trading_db_path()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    text, result = sbr.run(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert "real NLV series: 1 days" in text
    # the seeded panel ends in October: the slide is covered by neither series, so no result
    assert result is None or result.value_on_pass in {"8", "10", "12", "15"}


def test_a_missing_database_writes_nothing(tmp_path: Path) -> None:
    text, result = sbr.run(tmp_path / "absent.db")
    assert result is None and "nothing to replay" in text
