"""Tests for the enrichment-layer evaluation: ledger, baseline, reconciler, metrics.

DB tests use tmp_path + SQLite so they never touch production state (same pattern as
test_execution). No IBKR, no Claude CLI.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.schemas import (
    OptionRight,
    ScoreCard,
    Strategy,
    TradeCandidate,
    VerdictOutcome,
    VerdictRecord,
)


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _candidate(cid: str, score: float, underlying: str = "AAPL") -> TradeCandidate:
    return TradeCandidate(
        candidate_id=cid,
        strategy=Strategy.COVERED_CALL,
        underlying=underlying,
        right=OptionRight.CALL,
        strike=185.0,
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


def _record(
    cid: str,
    *,
    claude: str = "sell",
    baseline: str = "sell",
    confidence: float | None = 0.7,
    expiry_days: int = 30,
    underlying: str = "AAPL",
) -> VerdictRecord:
    return VerdictRecord(
        candidate_id=cid,
        run_id="run1",
        scan_date=date.today(),
        underlying=underlying,
        strategy=Strategy.COVERED_CALL,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date.today() + timedelta(days=expiry_days),
        dte=expiry_days,
        signals={"blended_score": 80, "iv_rank": 55, "delta": 0.28, "vrp": 4},
        claude_recommendation=claude,
        claude_priority=1,
        claude_confidence=confidence,
        claude_rationale="because",
        baseline_recommendation=baseline,
        baseline_rank=1,
        baseline_score=80.0,
        agreement=(claude == "sell") == (baseline == "sell"),
    )


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #
def test_baseline_ranks_surfaced_by_score_and_skips_others() -> None:
    from src.claude.eval.baseline import baseline_decisions

    surfaced = [_candidate("a", 60.0), _candidate("b", 90.0), _candidate("c", 75.0)]
    skipped = [_candidate("z", 40.0)]
    decisions = baseline_decisions(surfaced, skipped)

    assert decisions["b"].recommendation == "sell"
    assert decisions["b"].rank == 1  # highest score ranks first
    assert decisions["c"].rank == 2
    assert decisions["a"].rank == 3
    assert decisions["z"].recommendation == "skip"
    assert decisions["z"].rank is None


# --------------------------------------------------------------------------- #
# Ledger
# --------------------------------------------------------------------------- #
def test_ledger_roundtrip(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.claude.eval.ledger import load_records, record_verdicts

    assert record_verdicts([_record("a"), _record("b", underlying="MSFT")]) == 2
    loaded = {r.candidate_id: r for r in load_records()}
    assert set(loaded) == {"a", "b"}
    assert loaded["a"].claude_confidence == 0.7
    assert loaded["a"].signals["iv_rank"] == 55


def test_ledger_upsert_preserves_terminal_outcome(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.claude.eval.ledger import load_records, record_verdicts, update_outcome

    record_verdicts([_record("a")])
    update_outcome(
        "a", VerdictOutcome.EXPIRED_WORTHLESS, realized_pnl=150.0, outcome_date=date.today()
    )
    # Re-scan writes the same candidate again — must NOT reset the recorded outcome.
    record_verdicts([_record("a", claude="wait")])
    row = load_records()[0]
    assert row.outcome == VerdictOutcome.EXPIRED_WORTHLESS
    assert row.realized_pnl == 150.0
    assert row.claude_recommendation == "wait"  # pre-outcome fields still refresh


def test_ledger_freezes_signals_once_order_exists(tmp_path, monkeypatch) -> None:
    """N2b: once an order exists for the candidate, re-scans no longer refresh its signals,
    so the row that gets the realized outcome keeps the scan that produced the fill."""
    _db_setup(tmp_path, monkeypatch)
    from src.claude.eval.ledger import load_records, record_verdicts
    from src.common.schemas import OrderState
    from src.storage.db import session_scope
    from src.storage.models import OrderRow

    record_verdicts([_record("a", claude="sell")])

    # No order yet → a re-scan still refreshes the pre-outcome fields.
    record_verdicts([_record("a", claude="wait")])
    assert load_records()[0].claude_recommendation == "wait"

    # The candidate is approved/queued → an OrderRow now exists.
    with session_scope() as s:
        s.add(OrderRow(candidate_id="a", approval_id=1, state=OrderState.QUEUED))

    # A later re-scan must NOT overwrite the committed scan's signal vector.
    frozen = record_verdicts([_record("a", claude="skip", confidence=0.99)])
    assert frozen == 1  # still attempts the write
    row = load_records()[0]
    assert row.claude_recommendation == "wait"  # frozen, not "skip"
    assert row.claude_confidence == 0.7


# --------------------------------------------------------------------------- #
# Reconciler
# --------------------------------------------------------------------------- #
def _add_fill(candidate_id: str, action: str, qty: float, price: float, commission: float) -> None:
    from src.storage.db import session_scope
    from src.storage.models import FillRow

    with session_scope() as s:
        s.add(
            FillRow(
                order_id=1,
                candidate_id=candidate_id,
                action=action,
                filled_qty=qty,
                avg_price=price,
                commission=commission,
            )
        )


def test_reconcile_expired_worthless(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.claude.eval.ledger import load_records, record_verdicts
    from src.claude.eval.reconcile import reconcile

    record_verdicts([_record("a", expiry_days=-3)])  # already expired (clear of TZ boundary)
    _add_fill("a", "SELL", qty=2, price=1.5, commission=1.3)

    counts = reconcile()
    assert counts.get("expired_worthless") == 1
    row = load_records()[0]
    assert row.outcome == VerdictOutcome.EXPIRED_WORTHLESS
    assert row.realized_pnl == pytest.approx(1.5 * 2 * 100 - 1.3)  # premium kept − commission
    assert row.filled is True
    assert row.contracts == 2


def test_reconcile_closed_early(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.claude.eval.ledger import load_records, record_verdicts
    from src.claude.eval.reconcile import reconcile

    record_verdicts([_record("a", expiry_days=30)])  # not expired, but bought back
    _add_fill("a", "SELL", qty=2, price=1.5, commission=1.0)
    _add_fill("a", "BUY", qty=2, price=0.5, commission=1.0)

    counts = reconcile()
    assert counts.get("closed_early") == 1
    row = load_records()[0]
    assert row.outcome == VerdictOutcome.CLOSED_EARLY
    # credit 300 − debit 100 − commissions 2 = 198
    assert row.realized_pnl == pytest.approx(300 - 100 - 2)


async def test_external_close_flips_expired_to_closed_early(tmp_path, monkeypatch) -> None:
    """F7 end-to-end: a manual TWS close recorded by reconcile_external_closes makes the ledger
    label a past-expiry short CLOSED_EARLY instead of EXPIRED_WORTHLESS with full premium."""
    from unittest.mock import AsyncMock, MagicMock

    _db_setup(tmp_path, monkeypatch)
    from src.claude.eval.ledger import load_records, record_verdicts
    from src.claude.eval.reconcile import reconcile
    from src.execution.reconciliation import reconcile_external_closes
    from src.storage.db import session_scope
    from src.storage.models import CandidateRow, FillRow

    expiry = date.today() - timedelta(days=3)  # already expired
    record_verdicts([_record("a", expiry_days=-3)])
    with session_scope() as s:
        s.add(
            CandidateRow(
                candidate_id="a", run_id="run1", strategy="covered_call", underlying="AAPL",
                right="C", strike=185.0, expiry=expiry, blended_score=80.0, payload={"contracts": 2},
            )
        )
        s.add(FillRow(order_id=1, candidate_id="a", action="SELL", filled_qty=2, avg_price=2.0))

    # Without a recorded close, the position would be EXPIRED_WORTHLESS. Record the manual close:
    ib = MagicMock()
    ib.reqExecutionsAsync = AsyncMock(
        return_value=[
            type(
                "F",
                (),
                {
                    "execution": type("E", (), {"execId": "tws1", "shares": 2.0, "price": 0.40, "side": "BOT"})(),
                    "contract": type(
                        "C",
                        (),
                        {"symbol": "AAPL", "right": "C", "strike": 185.0,
                         "lastTradeDateOrContractMonth": expiry.strftime("%Y%m%d"), "secType": "OPT"},
                    )(),
                    "commissionReport": type("R", (), {"commission": 1.0})(),
                },
            )()
        ]
    )
    await reconcile_external_closes(ib, AsyncMock(), "99999")

    counts = reconcile()
    assert counts.get("closed_early") == 1
    row = load_records()[0]
    assert row.outcome == VerdictOutcome.CLOSED_EARLY
    # credit 2.0*2*100=400 − debit 0.40*2*100=80 − commission 1 = 319
    assert row.realized_pnl == pytest.approx(400 - 80 - 1)


def test_reconcile_assigned_when_flagged(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.claude.eval.ledger import load_records, record_verdicts
    from src.claude.eval.reconcile import reconcile

    record_verdicts([_record("a", expiry_days=-3)])
    _add_fill("a", "SELL", qty=1, price=2.0, commission=0.0)

    reconcile(assigned_candidate_ids=["a"])
    assert load_records()[0].outcome == VerdictOutcome.ASSIGNED


def test_reconcile_still_open_stamps_fill(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.claude.eval.ledger import load_records, record_verdicts
    from src.claude.eval.reconcile import reconcile

    record_verdicts([_record("a", expiry_days=30)])
    _add_fill("a", "SELL", qty=1, price=2.0, commission=0.0)

    counts = reconcile()
    assert counts == {}  # no terminal outcome yet
    row = load_records()[0]
    assert row.outcome == VerdictOutcome.STILL_OPEN
    assert row.filled is True
    assert row.entry_premium == pytest.approx(2.0)


def test_reconcile_user_rejected(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.claude.eval.ledger import load_records, record_verdicts
    from src.claude.eval.reconcile import reconcile
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow

    record_verdicts([_record("a", expiry_days=30)])
    with session_scope() as s:
        s.add(ApprovalRow(candidate_id="a", status="rejected"))

    counts = reconcile()
    assert counts.get("user_rejected") == 1
    assert load_records()[0].outcome == VerdictOutcome.USER_REJECTED


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def _closed(cid: str, *, claude: str, pnl: float, conf: float) -> VerdictRecord:
    r = _record(cid, claude=claude, confidence=conf, expiry_days=-1)
    r.filled = True
    r.outcome = VerdictOutcome.EXPIRED_WORTHLESS if pnl > 0 else VerdictOutcome.CLOSED_EARLY
    r.realized_pnl = pnl
    r.outcome_date = date.today()
    return r


def test_metrics_edge_and_calibration() -> None:
    from src.claude.eval.metrics import evaluate

    # Claude said sell on the two winners and wait on the loser → its filter should beat
    # the baseline (which trades all three).
    records = [
        _closed("w1", claude="sell", pnl=200.0, conf=0.8),
        _closed("w2", claude="sell", pnl=100.0, conf=0.8),
        _closed("l1", claude="wait", pnl=-300.0, conf=0.2),
    ]
    ev = evaluate(records)

    assert ev.n_closed == 3
    assert ev.baseline.n_trades == 3
    assert ev.follow_claude.n_trades == 2
    assert ev.baseline.mean_pnl == pytest.approx((200 + 100 - 300) / 3)
    assert ev.follow_claude.mean_pnl == pytest.approx(150.0)
    assert ev.edge_per_trade > 0  # Claude's skip avoided the loser
    assert ev.brier_score is not None


def test_metrics_empty_is_not_zero_skill() -> None:
    from src.claude.eval.metrics import evaluate

    ev = evaluate([])
    assert ev.n_closed == 0
    assert ev.edge_per_trade is None
    assert any("empty" in n.lower() for n in ev.notes)


def test_metrics_by_period_groups_by_month() -> None:
    from src.claude.eval.metrics import evaluate_by_period

    r1 = _closed("a", claude="sell", pnl=100.0, conf=0.7)
    r1.outcome_date = date(2026, 4, 15)
    r2 = _closed("b", claude="sell", pnl=50.0, conf=0.7)
    r2.outcome_date = date(2026, 5, 20)
    periods = dict(evaluate_by_period([r1, r2]))
    assert set(periods) == {"2026-04", "2026-05"}
