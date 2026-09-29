"""Tests for the assessment audit trail (src/storage/risk_verdicts.py).

`risk_verdicts` was defined in models.py but never read or written by anything — the schema
for persisting rejections existed while every rejection was still being thrown away. These
cover the wiring, the pruning, and the best-effort contract: an audit-trail failure must never
propagate into a scan.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.schemas import (
    AssessedContract,
    AssessmentStage,
    IdealZone,
    OptionRight,
    ScoreCard,
    Strategy,
    TradeCandidate,
)
from src.storage.risk_verdicts import purge_old_risk_verdicts, record_assessments


@pytest.fixture
def db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    return dbmod


def _cand(cid: str = "c1", *, with_zone: bool = True) -> TradeCandidate:
    zone = (
        IdealZone(
            symbol="AAPL",
            right=OptionRight.PUT,
            dte=30,
            spot=200.0,
            strike_lo=185.0,
            strike_hi=192.0,
            min_credit=3.4,
        )
        if with_zone
        else None
    )
    return TradeCandidate(
        candidate_id=cid,
        strategy=Strategy.CASH_SECURED_PUT,
        underlying="AAPL",
        right=OptionRight.PUT,
        strike=190.0,
        expiry=date(2026, 9, 18),
        contracts=1,
        premium=3.0,
        collateral=19_000.0,
        roc_pct=1.5,
        annualized_yield_pct=18.0,
        breakeven=187.0,
        dte=30,
        blended_score=62.0,
        ideal=zone,
        scores=ScoreCard(symbol="AAPL"),
    )


def _rows(dbmod):
    from src.storage.models import RiskVerdictRow

    with dbmod.session_scope() as s:
        return s.query(RiskVerdictRow).all()


def test_records_one_row_per_assessed_contract(db) -> None:
    record_assessments(
        "run-1",
        [
            AssessedContract(candidate=_cand("a"), stage=AssessmentStage.PASSED),
            AssessedContract(
                candidate=_cand("b"),
                stage=AssessmentStage.GENERATOR,
                reasons=["delta_out_of_range"],
            ),
        ],
    )
    rows = _rows(db)
    assert len(rows) == 2
    by_id = {r.candidate_id: r for r in rows}
    assert by_id["a"].verdict == "pass" and by_id["a"].stage == "passed"
    assert by_id["b"].verdict == "reject" and by_id["b"].reasons == ["delta_out_of_range"]


def test_denormalizes_the_ideal_zone_so_history_stays_readable(db) -> None:
    """Analytics move; a row written today must still be interpretable next month."""
    record_assessments(
        "run-1",
        [AssessedContract(candidate=_cand(), stage=AssessmentStage.RISK_GATE, reasons=["x"])],
    )
    row = _rows(db)[0]
    assert row.ideal_lo == 185.0 and row.ideal_hi == 192.0 and row.min_credit == 3.4
    assert row.symbol == "AAPL" and row.strategy == "cash_secured_put"
    assert row.strike == 190.0 and row.premium == 3.0 and row.blended_score == 62.0


def test_records_the_liquidity_snapshot(db) -> None:
    """Task 7: the quote microstructure behind a liquidity verdict is persisted, not just
    the pass/fail code, so a granular reject (e.g. illiquid_oi_low) can be audited later."""
    cand = _cand().model_copy(
        update={"quote_bid": 1.00, "quote_ask": 1.04, "open_interest": 5, "option_volume": 50}
    )
    record_assessments(
        "run-1",
        [
            AssessedContract(
                candidate=cand, stage=AssessmentStage.GENERATOR, reasons=["illiquid_oi_low"]
            )
        ],
    )
    row = _rows(db)[0]
    assert row.liquidity == {
        "bid": 1.00,
        "ask": 1.04,
        "spread_pct": 3.92,
        "open_interest": 5,
        "volume": 50,
    }


def test_a_contract_without_a_zone_still_records(db) -> None:
    record_assessments(
        "run-1",
        [
            AssessedContract(
                candidate=_cand(with_zone=False), stage=AssessmentStage.TOP_N, reasons=["x"]
            )
        ],
    )
    row = _rows(db)[0]
    assert row.ideal_lo is None and row.min_credit is None


def test_empty_assessment_list_writes_nothing(db) -> None:
    assert record_assessments("run-1", []) == 0
    assert _rows(db) == []


def test_a_write_failure_is_swallowed(monkeypatch) -> None:
    """The audit trail is forensics — losing a row must never abort a scan."""
    import src.storage.risk_verdicts as mod

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "session_scope", _boom)
    assert (
        record_assessments(
            "run-1", [AssessedContract(candidate=_cand(), stage=AssessmentStage.PASSED)]
        )
        == 0
    )


def test_purge_removes_only_old_rows(db) -> None:
    from src.storage.models import RiskVerdictRow

    record_assessments(
        "run-1", [AssessedContract(candidate=_cand("fresh"), stage=AssessmentStage.PASSED)]
    )
    with db.session_scope() as s:
        s.add(
            RiskVerdictRow(
                candidate_id="stale",
                verdict="reject",
                reasons=["x"],
                created_at=datetime.now(UTC) - timedelta(days=30),
            )
        )

    assert purge_old_risk_verdicts(days=14) == 1
    assert [r.candidate_id for r in _rows(db)] == ["fresh"]


def test_purge_failure_is_swallowed(monkeypatch) -> None:
    import src.storage.risk_verdicts as mod

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(mod, "session_scope", _boom)
    assert purge_old_risk_verdicts() == 0


def test_migration_adds_the_new_columns_to_a_legacy_table(tmp_path, monkeypatch) -> None:
    """Deployed DBs already carry the original 3-column risk_verdicts shape."""
    import sqlite3

    import src.storage.db as dbmod
    from src.common.config import Config

    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE risk_verdicts (id INTEGER PRIMARY KEY, candidate_id VARCHAR(64), "
        "verdict VARCHAR(10), reasons JSON, created_at DATETIME)"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{path}")
    dbmod.init_db()

    conn = sqlite3.connect(path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(risk_verdicts)")}
    conn.close()
    assert {
        "run_id",
        "symbol",
        "stage",
        "ideal_lo",
        "ideal_hi",
        "min_credit",
        "liquidity",
    } <= cols
