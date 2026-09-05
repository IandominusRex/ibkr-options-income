"""Buy candidates round-trip through SQLite, and only the newest full scan is served.

Also covers the single-ticker isolation rule: a ``/scan NVDA`` (run_id prefixed
``scan-``) must never displace the full-scan recommendations list.
"""

from __future__ import annotations

import pytest

from src.common.schemas import BuyCandidate
from src.storage.buy_candidates import (
    SINGLE_TICKER_PREFIX,
    latest_buy_candidates,
    save_buy_candidates,
)


def _cand(symbol: str, score: float) -> BuyCandidate:
    return BuyCandidate(
        symbol=symbol,
        score=score,
        sector="tech",
        iv_rank=45.0,
        quality_flag=True,
        technical_regime="UPTREND",
        rationale="high IV rank, quality passes",
        price=100.0,
        current_iv=52.0,
        hv_30=38.0,
        vrp=14.0,
    )


@pytest.fixture
def db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    return dbmod


def test_save_returns_the_row_count(db) -> None:
    assert save_buy_candidates("run-1", [_cand("NVDA", 80.0), _cand("META", 74.0)]) == 2


def test_round_trip_preserves_the_analysis_context(db) -> None:
    save_buy_candidates("run-1", [_cand("NVDA", 80.0)])
    got = latest_buy_candidates()[0]
    assert got.symbol == "NVDA"
    assert got.vrp == 14.0
    assert got.rationale


def test_results_are_ordered_by_score_descending(db) -> None:
    save_buy_candidates("run-1", [_cand("META", 74.0), _cand("NVDA", 80.0)])
    assert [c.symbol for c in latest_buy_candidates()] == ["NVDA", "META"]


def test_only_the_latest_run_is_returned(db) -> None:
    save_buy_candidates("run-1", [_cand("OLD", 90.0)])
    save_buy_candidates("run-2", [_cand("NEW", 50.0)])
    assert [c.symbol for c in latest_buy_candidates()] == ["NEW"]


def test_saving_an_empty_list_does_not_clear_the_previous_run(db) -> None:
    """A scan that produced nothing must not blank the recommendations page."""
    save_buy_candidates("run-1", [_cand("NVDA", 80.0)])
    assert save_buy_candidates("run-2", []) == 0
    assert [c.symbol for c in latest_buy_candidates()] == ["NVDA"]


def test_empty_table_returns_empty_list_not_an_error(db) -> None:
    assert latest_buy_candidates() == []


def test_single_ticker_run_does_not_displace_the_full_scan(db) -> None:
    """A /scan NVDA must never replace the whole list with one name."""
    save_buy_candidates("run-full", [_cand("NVDA", 80.0), _cand("META", 74.0)])
    save_buy_candidates(f"{SINGLE_TICKER_PREFIX}NVDA-1", [_cand("NVDA", 99.0)])
    got = [c.symbol for c in latest_buy_candidates()]
    assert got == ["NVDA", "META"]
    assert len(got) == 2


def test_limit_caps_the_returned_count(db) -> None:
    save_buy_candidates(
        "run-1",
        [_cand("A", 90.0), _cand("B", 80.0), _cand("C", 70.0)],
    )
    assert [c.symbol for c in latest_buy_candidates(limit=2)] == ["A", "B"]


def test_write_failure_is_swallowed(monkeypatch, db) -> None:
    """Display data must never abort a scan."""
    import src.storage.buy_candidates as mod

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "session_scope", _boom)
    assert save_buy_candidates("run-1", [_cand("NVDA", 80.0)]) == 0


def test_read_failure_returns_empty_list(monkeypatch, db) -> None:
    import src.storage.buy_candidates as mod

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "session_scope", _boom)
    assert latest_buy_candidates() == []
