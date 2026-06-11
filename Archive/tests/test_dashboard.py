# ARCHIVED — original location: tests/test_dashboard.py
# Streamlit dashboard tests. To reinstate: move back to tests/test_dashboard.py.
"""Tests for Phase 10: Streamlit dashboard data helpers.

Pure-function tests run without any DB or Streamlit.
Integration tests use the isolated_db fixture (tmp SQLite, no TWS).
AppTest smoke tests verify each page renders without raising.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.common.schemas import AccountSnapshot, EODSummary

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


def _make_account(nlv: float = 100_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=nlv,
        total_cash=50_000.0,
        buying_power=80_000.0,
        maintenance_margin=5_000.0,
        excess_liquidity=75_000.0,
    )


def _make_eod_summary(**kwargs: object) -> EODSummary:
    defaults: dict = dict(
        date=date.today(),
        realized_pnl=142.50,
        unrealized_pnl=-320.0,
        unrealized_pnl_delta=-85.0,
        fills_today=2,
        open_positions=3,
        net_delta_exposure=-0.28,
        account=_make_account(),
        top_movers=["AAPL", "SPY"],
        tomorrow_watchlist=["AAPL", "SPY", "NVDA"],
    )
    defaults.update(kwargs)
    return EODSummary(**defaults)  # type: ignore[arg-type]


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated in-process SQLite DB wired into src.storage.db."""
    import src.storage.db as _db_mod
    from src.storage.models import Base

    db_url = f"sqlite:///{tmp_path / 'dash_test.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(_db_mod, "_engine", engine)
    monkeypatch.setattr(_db_mod, "_SessionLocal", Session)
    return Session


# ---------------------------------------------------------------------------
# Pure-function tests — no DB, no Streamlit
# ---------------------------------------------------------------------------


class TestJournalRowToPortfolio:
    def test_empty_payload_returns_defaults(self) -> None:
        from dashboard.data import _journal_row_to_portfolio
        from src.storage.models import JournalRow

        row = JournalRow(
            entry_date=date.today(),
            realized_pnl=50.0,
            unrealized_pnl=-10.0,
            narrative="test",
            payload={},
        )
        result = _journal_row_to_portfolio(row)
        assert result["realized_pnl"] == pytest.approx(50.0)
        assert result["nlv"] is None
        assert result["top_movers"] == []

    def test_valid_eod_summary_decoded(self) -> None:
        from dashboard.data import _journal_row_to_portfolio
        from src.storage.models import JournalRow

        eod = _make_eod_summary()
        row = JournalRow(
            entry_date=date.today(),
            realized_pnl=eod.realized_pnl,
            unrealized_pnl=eod.unrealized_pnl,
            payload={"eod_summary": eod.model_dump(mode="json")},
        )
        result = _journal_row_to_portfolio(row)
        assert result["nlv"] == pytest.approx(100_000.0)
        assert result["buying_power"] == pytest.approx(80_000.0)
        assert result["open_positions"] == 3
        assert result["net_delta"] == pytest.approx(-0.28)
        assert result["top_movers"] == ["AAPL", "SPY"]

    def test_corrupt_payload_falls_back_to_row_values(self) -> None:
        from dashboard.data import _journal_row_to_portfolio
        from src.storage.models import JournalRow

        row = JournalRow(
            entry_date=date.today(),
            realized_pnl=99.0,
            unrealized_pnl=0.0,
            payload={"eod_summary": "not a dict"},
        )
        result = _journal_row_to_portfolio(row)
        assert result["realized_pnl"] == pytest.approx(99.0)
        assert result["nlv"] is None


class TestJournalRowToFeedDict:
    def test_fields_present(self) -> None:
        from dashboard.data import _journal_row_to_feed_dict
        from src.storage.models import JournalRow

        eod = _make_eod_summary()
        row = JournalRow(
            entry_date=date.today(),
            realized_pnl=eod.realized_pnl,
            unrealized_pnl=eod.unrealized_pnl,
            narrative="Good day",
            payload={"eod_summary": eod.model_dump(mode="json")},
        )
        d = _journal_row_to_feed_dict(row)
        assert d["Fills"] == 2
        assert d["Positions"] == 3
        assert d["Net Delta"] == pytest.approx(-0.28)
        assert "Good day" in d["Narrative"]

    def test_no_payload_returns_none_for_eod_fields(self) -> None:
        from dashboard.data import _journal_row_to_feed_dict
        from src.storage.models import JournalRow

        row = JournalRow(
            entry_date=date.today(),
            realized_pnl=10.0,
            unrealized_pnl=5.0,
            payload={},
        )
        d = _journal_row_to_feed_dict(row)
        assert d["Fills"] is None
        assert d["Positions"] is None
        assert d["Net Delta"] is None


class TestComputeIVRankTable:
    def _make_data(self) -> dict:
        from dashboard.data import compute_iv_rank_table

        pts = [(date(2024, i, 1), 0.20 + i * 0.005) for i in range(1, 13)]
        by_sym = {"AAPL": pts}
        return {"by_sym": by_sym, "table": compute_iv_rank_table(by_sym)}

    def test_returns_row_per_symbol(self) -> None:
        from dashboard.data import compute_iv_rank_table

        by_sym = {"AAPL": [(date(2024, 1, i), 0.25 + i * 0.01) for i in range(1, 11)]}
        rows = compute_iv_rank_table(by_sym)
        assert len(rows) == 1
        assert rows[0]["Symbol"] == "AAPL"

    def test_iv_rank_100_when_at_max(self) -> None:
        from dashboard.data import compute_iv_rank_table

        pts = [(date(2024, 1, i), float(i) / 100) for i in range(1, 11)]
        by_sym = {"SPY": pts}
        rows = compute_iv_rank_table(by_sym)
        assert rows[0]["IV Rank"] == pytest.approx(100.0)

    def test_iv_rank_0_when_at_min(self) -> None:
        from dashboard.data import compute_iv_rank_table

        # Current IV (last point) is the minimum
        pts = [(date(2024, 1, i), 0.30 - i * 0.01) for i in range(1, 11)]
        by_sym = {"SPY": pts}
        rows = compute_iv_rank_table(by_sym)
        assert rows[0]["IV Rank"] == pytest.approx(0.0)

    def test_empty_symbol_skipped(self) -> None:
        from dashboard.data import compute_iv_rank_table

        rows = compute_iv_rank_table({"AAPL": []})
        assert rows == []

    def test_multiple_symbols_sorted(self) -> None:
        from dashboard.data import compute_iv_rank_table

        by_sym = {
            "SPY": [(date(2024, 1, i), 0.15 + i * 0.005) for i in range(1, 6)],
            "AAPL": [(date(2024, 1, i), 0.25 + i * 0.005) for i in range(1, 6)],
        }
        rows = compute_iv_rank_table(by_sym)
        assert len(rows) == 2
        assert rows[0]["Symbol"] == "AAPL"  # alphabetical
        assert rows[1]["Symbol"] == "SPY"

    def test_flat_iv_yields_zero_rank(self) -> None:
        from dashboard.data import compute_iv_rank_table

        pts = [(date(2024, 1, i), 0.20) for i in range(1, 6)]
        rows = compute_iv_rank_table({"X": pts})
        assert rows[0]["IV Rank"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Integration tests — isolated DB
# ---------------------------------------------------------------------------


class TestGetPortfolioSummary:
    def test_empty_db_returns_empty_portfolio(self, isolated_db) -> None:
        from dashboard.data import get_portfolio_summary

        result = get_portfolio_summary()
        assert result["entry_date"] is None
        assert result["realized_pnl"] == pytest.approx(0.0)
        assert result["nlv"] is None

    def test_journal_row_decoded_correctly(self, isolated_db) -> None:
        from dashboard.data import get_portfolio_summary
        from src.storage.models import JournalRow

        eod = _make_eod_summary(realized_pnl=250.0)
        with isolated_db() as sess:
            sess.add(
                JournalRow(
                    entry_date=date.today(),
                    realized_pnl=eod.realized_pnl,
                    unrealized_pnl=eod.unrealized_pnl,
                    payload={"eod_summary": eod.model_dump(mode="json")},
                )
            )
            sess.commit()

        result = get_portfolio_summary()
        assert result["realized_pnl"] == pytest.approx(250.0)
        assert result["nlv"] == pytest.approx(100_000.0)
        assert result["open_positions"] == 3

    def test_most_recent_journal_used(self, isolated_db) -> None:
        from dashboard.data import get_portfolio_summary
        from src.storage.models import JournalRow

        with isolated_db() as sess:
            sess.add(JournalRow(entry_date=date(2025, 1, 1), realized_pnl=10.0, payload={}))
            eod = _make_eod_summary(realized_pnl=999.0)
            sess.add(
                JournalRow(
                    entry_date=date(2025, 6, 1),
                    realized_pnl=999.0,
                    payload={"eod_summary": eod.model_dump(mode="json")},
                )
            )
            sess.commit()

        result = get_portfolio_summary()
        assert result["realized_pnl"] == pytest.approx(999.0)


class TestGetJournalFeed:
    def test_empty_db_returns_empty_list(self, isolated_db) -> None:
        from dashboard.data import get_journal_feed

        assert get_journal_feed() == []

    def test_returns_newest_first(self, isolated_db) -> None:
        from dashboard.data import get_journal_feed
        from src.storage.models import JournalRow

        with isolated_db() as sess:
            sess.add(JournalRow(entry_date=date(2025, 1, 1), realized_pnl=10.0, payload={}))
            sess.add(JournalRow(entry_date=date(2025, 3, 1), realized_pnl=50.0, payload={}))
            sess.commit()

        feed = get_journal_feed()
        assert feed[0]["Date"] == str(date(2025, 3, 1))
        assert feed[1]["Date"] == str(date(2025, 1, 1))

    def test_limit_respected(self, isolated_db) -> None:
        from dashboard.data import get_journal_feed
        from src.storage.models import JournalRow

        with isolated_db() as sess:
            for i in range(10):
                sess.add(
                    JournalRow(
                        entry_date=date(2025, 1, i + 1),
                        realized_pnl=float(i),
                        payload={},
                    )
                )
            sess.commit()

        assert len(get_journal_feed(limit=3)) == 3


class TestGetCandidates:
    def test_empty_db_returns_empty_list(self, isolated_db) -> None:
        from dashboard.data import get_candidates

        assert get_candidates() == []

    def test_candidates_ordered_by_score_desc(self, isolated_db) -> None:
        from dashboard.data import get_candidates
        from src.storage.models import CandidateRow

        run_id = "run_abc123"
        with isolated_db() as sess:
            for score in [30.0, 80.0, 55.0]:
                sess.add(
                    CandidateRow(
                        candidate_id=f"cid_{score}",
                        run_id=run_id,
                        strategy="covered_call",
                        underlying="AAPL",
                        right="C",
                        strike=185.0,
                        expiry=date(2025, 9, 19),
                        blended_score=score,
                        payload={},
                    )
                )
            sess.commit()

        rows = get_candidates()
        scores = [r["Score"] for r in rows]
        assert scores == sorted(scores, reverse=True)

    def test_risk_verdict_joined(self, isolated_db) -> None:
        from dashboard.data import get_candidates
        from src.storage.models import CandidateRow, RiskVerdictRow

        run_id = "run_xyz"
        with isolated_db() as sess:
            sess.add(
                CandidateRow(
                    candidate_id="cid_1",
                    run_id=run_id,
                    strategy="cash_secured_put",
                    underlying="SPY",
                    right="P",
                    strike=500.0,
                    expiry=date(2025, 9, 19),
                    blended_score=70.0,
                    payload={},
                )
            )
            sess.add(RiskVerdictRow(candidate_id="cid_1", verdict="pass", reasons=[]))
            sess.commit()

        rows = get_candidates()
        assert rows[0]["Risk"] == "pass"


class TestGetOrdersPipeline:
    def test_empty_db_returns_empty_list(self, isolated_db) -> None:
        from dashboard.data import get_orders_pipeline

        assert get_orders_pipeline() == []

    def test_approval_without_order(self, isolated_db) -> None:
        from dashboard.data import get_orders_pipeline
        from src.storage.models import ApprovalRow

        with isolated_db() as sess:
            sess.add(ApprovalRow(candidate_id="cid_1", status="pending"))
            sess.commit()

        rows = get_orders_pipeline()
        assert len(rows) == 1
        assert rows[0]["Approval"] == "pending"
        assert rows[0]["Order State"] == "—"

    def test_fill_totals_aggregated(self, isolated_db) -> None:
        from dashboard.data import get_orders_pipeline
        from src.storage.models import ApprovalRow, FillRow, OrderRow

        with isolated_db() as sess:
            sess.add(ApprovalRow(candidate_id="cid_1", status="approved"))
            sess.add(
                OrderRow(
                    candidate_id="cid_1",
                    state="filled",
                    limit_price=1.50,
                    avg_fill_price=1.48,
                )
            )
            sess.add(
                FillRow(
                    order_id=1,
                    candidate_id="cid_1",
                    filled_qty=2.0,
                    avg_price=1.48,
                    commission=1.30,
                )
            )
            sess.add(
                FillRow(
                    order_id=1,
                    candidate_id="cid_1",
                    filled_qty=1.0,
                    avg_price=1.48,
                    commission=0.65,
                )
            )
            sess.commit()

        rows = get_orders_pipeline()
        assert rows[0]["Filled Qty"] == pytest.approx(3.0)
        assert rows[0]["Commission"] == pytest.approx(1.95)


class TestGetIVHistory:
    def test_empty_db_returns_empty_dict(self, isolated_db) -> None:
        from dashboard.data import get_iv_history_by_symbol

        assert get_iv_history_by_symbol() == {}

    def test_lookback_limits_rows(self, isolated_db) -> None:
        from dashboard.data import get_iv_history_by_symbol
        from src.storage.models import IVHistoryRow

        with isolated_db() as sess:
            for i in range(10):
                sess.add(IVHistoryRow(symbol="AAPL", obs_date=date(2024, 1, i + 1), iv=0.25))
            sess.commit()

        result = get_iv_history_by_symbol(lookback_days=5)
        assert len(result["AAPL"]) == 5

    def test_dates_sorted_ascending(self, isolated_db) -> None:
        from dashboard.data import get_iv_history_by_symbol
        from src.storage.models import IVHistoryRow

        with isolated_db() as sess:
            for i in [3, 1, 2]:
                sess.add(IVHistoryRow(symbol="SPY", obs_date=date(2024, 1, i), iv=0.20))
            sess.commit()

        pts = get_iv_history_by_symbol()["SPY"]
        dates = [d for d, _ in pts]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# AppTest smoke tests — pages render without exceptions
# ---------------------------------------------------------------------------


def _page_path(name: str) -> str:
    from pathlib import Path

    return str(Path(__file__).parents[1] / "dashboard" / "pages" / name)


def _app_path() -> str:
    from pathlib import Path

    return str(Path(__file__).parents[1] / "dashboard" / "app.py")


class TestAppSmoke:
    """Each page should render to completion against an empty isolated DB."""

    def test_home_page(self, isolated_db) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(_app_path(), default_timeout=30)
        at.run()
        assert not at.exception

    def test_portfolio_page(self, isolated_db) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(_page_path("01_portfolio.py"), default_timeout=30)
        at.run()
        assert not at.exception

    def test_candidates_page(self, isolated_db) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(_page_path("02_candidates.py"), default_timeout=30)
        at.run()
        assert not at.exception

    def test_orders_page(self, isolated_db) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(_page_path("03_orders.py"), default_timeout=30)
        at.run()
        assert not at.exception

    def test_journal_page(self, isolated_db) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(_page_path("04_journal.py"), default_timeout=30)
        at.run()
        assert not at.exception

    def test_iv_conditions_page(self, isolated_db) -> None:
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_file(_page_path("05_iv_conditions.py"), default_timeout=30)
        at.run()
        assert not at.exception
