"""Tests for assignment auto-detection via position diffing (SYSTEM_REVIEW Phase 4)."""

from __future__ import annotations

from datetime import date, timedelta

from src.claude.eval.assignment import OpenShort, detect_assignments
from src.common.schemas import OptionRight, PositionSnapshot

_TODAY = date(2026, 7, 17)


def _stk(underlying: str, qty: float) -> PositionSnapshot:
    return PositionSnapshot(symbol=underlying, sec_type="STK", position=qty, avg_cost=0.0,
                            underlying=underlying)


def _opt(underlying: str, right: str, strike: float, expiry: date, qty: float = -2.0) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=f"{underlying}  OPT", sec_type="OPT", position=qty, avg_cost=0.0,
        right=OptionRight(right), strike=strike, expiry=expiry, underlying=underlying,
    )


def _short(cid="c1", underlying="AAPL", right="P", strike=180.0, expiry=_TODAY, contracts=2.0) -> OpenShort:
    return OpenShort(candidate_id=cid, underlying=underlying, right=right, strike=strike,
                     expiry=expiry, contracts=contracts)


# --------------------------------------------------------------------------- #
# detect_assignments (pure)
# --------------------------------------------------------------------------- #


def test_csp_assignment_detected_when_shares_appear():
    # Short put gone at expiry; we were put 200 shares (2 contracts).
    short = _short(right="P", contracts=2.0)
    prior = []  # no shares before
    current = [_stk("AAPL", 200.0)]  # shares appeared, option gone
    assert detect_assignments([short], prior, current, _TODAY) == {"c1"}


def test_cc_assignment_detected_when_shares_called_away():
    # Short call gone at expiry; our 200 shares were called away.
    short = _short(right="C", contracts=2.0)
    prior = [_stk("AAPL", 200.0), _opt("AAPL", "C", 180.0, _TODAY)]
    current = []  # shares gone, option gone
    assert detect_assignments([short], prior, current, _TODAY) == {"c1"}


def test_put_expired_worthless_not_assigned():
    # Short put gone, but no shares appeared → expired worthless, not assigned.
    short = _short(right="P", contracts=2.0)
    assert detect_assignments([short], [], [], _TODAY) == set()


def test_call_expired_worthless_still_holding_shares():
    # Short call gone, but we still hold the same shares → expired worthless.
    short = _short(right="C", contracts=2.0)
    prior = [_stk("AAPL", 200.0)]
    current = [_stk("AAPL", 200.0)]
    assert detect_assignments([short], prior, current, _TODAY) == set()


def test_not_yet_expired_is_skipped():
    short = _short(right="P", expiry=_TODAY + timedelta(days=3))
    current = [_stk("AAPL", 200.0)]
    assert detect_assignments([short], [], current, _TODAY) == set()


def test_option_still_present_is_skipped():
    # The short option is still in the book (not yet processed) → not terminal.
    short = _short(right="P", strike=180.0, expiry=_TODAY)
    current = [_stk("AAPL", 200.0), _opt("AAPL", "P", 180.0, _TODAY)]
    assert detect_assignments([short], [], current, _TODAY) == set()


def test_partial_stock_move_below_threshold_not_assigned():
    # 2 contracts expect ~200 shares; only 100 appeared → not a clean assignment match.
    short = _short(right="P", contracts=2.0)
    assert detect_assignments([short], [], [_stk("AAPL", 100.0)], _TODAY) == set()


def test_only_matching_underlying_counts():
    short = _short(right="P", underlying="AAPL", contracts=1.0)
    # Shares appeared in a DIFFERENT name → not this short's assignment.
    assert detect_assignments([short], [], [_stk("MSFT", 100.0)], _TODAY) == set()


# --------------------------------------------------------------------------- #
# snapshot persistence
# --------------------------------------------------------------------------- #


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def test_snapshot_save_load_roundtrip(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.positions import load_latest_position_snapshot, save_position_snapshot

    save_position_snapshot(_TODAY, [_stk("AAPL", 200.0), _opt("AAPL", "P", 180.0, _TODAY)])
    loaded = load_latest_position_snapshot()
    assert len(loaded) == 2
    assert {p.sec_type for p in loaded} == {"STK", "OPT"}


def test_snapshot_before_filter_returns_prior_day(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.positions import load_latest_position_snapshot, save_position_snapshot

    save_position_snapshot(_TODAY - timedelta(days=1), [_stk("AAPL", 100.0)])
    save_position_snapshot(_TODAY, [_stk("AAPL", 300.0)])
    prior = load_latest_position_snapshot(before=_TODAY)
    assert len(prior) == 1 and prior[0].position == 100.0


def test_snapshot_upsert_is_idempotent(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.db import session_scope
    from src.storage.models import PositionSnapshotRow
    from src.storage.positions import save_position_snapshot

    save_position_snapshot(_TODAY, [_stk("AAPL", 100.0)])
    save_position_snapshot(_TODAY, [_stk("AAPL", 200.0)])  # same day → overwrite, not append
    with session_scope() as s:
        rows = s.query(PositionSnapshotRow).all()
        assert len(rows) == 1 and rows[0].payload[0]["position"] == 200.0


def test_load_empty_when_no_snapshot(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.positions import load_latest_position_snapshot

    assert load_latest_position_snapshot() == []


# --------------------------------------------------------------------------- #
# end-to-end: auto-detect → ledger labels ASSIGNED
# --------------------------------------------------------------------------- #


async def test_eod_autodetect_marks_ledger_assigned(tmp_path, monkeypatch):
    """A short put put-to-us is auto-detected and the ledger labels it ASSIGNED, not expired."""
    _db_setup(tmp_path, monkeypatch)

    from src.claude.eval.assignment import assigned_candidate_ids
    from src.claude.eval.ledger import load_records, record_verdicts
    from src.claude.eval.reconcile import reconcile
    from src.common.schemas import OptionRight as _R
    from src.common.schemas import Strategy, VerdictOutcome, VerdictRecord
    from src.storage.db import session_scope
    from src.storage.models import FillRow
    from src.storage.positions import save_position_snapshot

    entry_day = date.today()
    expiry = entry_day + timedelta(days=5)
    rec = VerdictRecord(
        candidate_id="p1", run_id="r", scan_date=entry_day, underlying="AAPL",
        strategy=Strategy.CASH_SECURED_PUT, right=_R.PUT, strike=180.0, expiry=expiry, dte=5,
        signals={}, claude_recommendation="sell", baseline_recommendation="sell",
    )
    record_verdicts([rec])
    with session_scope() as s:
        s.add(FillRow(order_id=1, candidate_id="p1", action="SELL", filled_qty=2, avg_price=2.0))

    # First reconcile (not yet expired) stamps filled=True / still_open.
    reconcile()
    assert load_records()[0].outcome == VerdictOutcome.STILL_OPEN

    # Prior snapshot: pre-assignment, no shares. (dated before the eval day)
    save_position_snapshot(entry_day, [])

    # Day after expiry: the put was assigned → we now hold 200 shares, the option is gone.
    eval_day = expiry + timedelta(days=1)
    current = [_stk("AAPL", 200.0)]
    assigned = assigned_candidate_ids(current, today=eval_day)
    assert assigned == {"p1"}

    reconcile(today=eval_day, assigned_candidate_ids=assigned)
    assert load_records()[0].outcome == VerdictOutcome.ASSIGNED
