"""Tests for the bounded Claude-memory injection (N9) in orchestrator/scan.py.

DB tests use tmp_path + SQLite (same pattern as test_eval / test_execution). No IBKR, no CLI.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.common.schemas import OptionRight, ScoreCard, Strategy, TradeCandidate


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _cand(cid: str, strike: float, score: float, underlying: str = "AAPL") -> TradeCandidate:
    return TradeCandidate(
        candidate_id=cid,
        strategy=Strategy.COVERED_CALL,
        underlying=underlying,
        right=OptionRight.CALL,
        strike=strike,
        expiry=date.today() + timedelta(days=30),
        contracts=1,
        premium=1.5,
        collateral=18500.0,
        roc_pct=0.8,
        annualized_yield_pct=10.0,
        breakeven=183.5,
        dte=30,
        scores=ScoreCard(symbol=underlying),
        blended_score=score,
    )


def test_persist_memory_dedupes_per_symbol_strategy_day(tmp_path, monkeypatch):
    """N9: many strikes for the same symbol+strategy collapse to one row/day, keeping the best."""
    _db_setup(tmp_path, monkeypatch)
    from sqlalchemy import select

    from src.orchestrator.scan import _persist_memory
    from src.storage.db import session_scope
    from src.storage.models import ClaudeMemoryRow

    # Two strikes, score-sorted desc as the scan passes them in.
    cands = [_cand("best", 190.0, 80.0), _cand("worse", 185.0, 60.0)]
    _persist_memory(cands, [], [])

    with session_scope() as s:
        rows = list(s.execute(select(ClaudeMemoryRow)).scalars().all())
    assert len(rows) == 1  # collapsed to one (AAPL, covered_call, today)
    assert rows[0].candidate_id == "best"  # highest-ranked candidate kept

    # A re-scan with a new best candidate updates the same row, not a second insert.
    _persist_memory([_cand("newbest", 195.0, 90.0)], [], [])
    with session_scope() as s:
        rows = list(s.execute(select(ClaudeMemoryRow)).scalars().all())
    assert len(rows) == 1
    assert rows[0].candidate_id == "newbest"


def test_load_memory_caps_per_symbol_outcomes_first(tmp_path, monkeypatch):
    """N9: _load_memory keeps at most N rows per symbol, floating recorded outcomes to the top."""
    _db_setup(tmp_path, monkeypatch)
    from src.orchestrator.scan import _MEMORY_ROWS_PER_SYMBOL, _load_memory
    from src.storage.db import session_scope
    from src.storage.models import ClaudeMemoryRow

    today = date.today()
    with session_scope() as s:
        # 6 rows for AAPL: the two oldest carry an outcome; the four newest are open.
        for i in range(6):
            s.add(
                ClaudeMemoryRow(
                    scan_date=today - timedelta(days=i),
                    underlying="AAPL",
                    strategy_type="covered_call",
                    recommendation="sell",
                    priority=1,
                    confidence=0.7,
                    rationale="r",
                    outcome="filled" if i >= 4 else None,
                    candidate_id=f"c{i}",
                )
            )

    loaded = _load_memory(["AAPL"])
    assert len(loaded) == _MEMORY_ROWS_PER_SYMBOL == 3
    # Outcomes float first: the two outcome-bearing rows must be retained.
    with_outcome = [r for r in loaded if r.outcome is not None]
    assert len(with_outcome) == 2
