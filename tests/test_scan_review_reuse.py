"""Tests for S5 — skip the Claude LLM review when the top-candidate set is unchanged.

The 15-min intraday loop re-runs the scan ~26×/session; when the top candidates + their signal
vectors are identical to the prior cycle, the `claude -p` subprocess would return the same review,
so it is skipped and the persisted ClaudeReview is reused. Enrichment-only — never gates anything
(the fence). Manual /scan and the morning cron always review fresh. No TWS/Gateway required.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.common.schemas import (
    AccountSnapshot,
    ClaudeReview,
    IVStats,
    MarketConditions,
    OptionRight,
    ScoreCard,
    Strategy,
    TradeCandidate,
)


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _candidate(candidate_id: str = "c-001", blended_score: float = 90.0) -> TradeCandidate:
    return TradeCandidate(
        candidate_id=candidate_id,
        strategy=Strategy.CASH_SECURED_PUT,
        underlying="AAPL",
        right=OptionRight.PUT,
        strike=180.0,
        expiry=date(2026, 7, 17),
        contracts=1,
        premium=1.50,
        collateral=18_000.0,
        roc_pct=0.83,
        annualized_yield_pct=18.5,
        breakeven=178.5,
        prob_otm=0.72,
        delta=-0.25,
        iv_rank=65.0,
        dte=48,
        scores=ScoreCard(symbol="AAPL", iv_score=70.0),
        blended_score=blended_score,
    )


def _review(candidate_id: str = "c-001") -> ClaudeReview:
    return ClaudeReview(
        candidate_id=candidate_id,
        priority=1,
        recommendation="sell",
        why_attractive="x",
        risks="y",
        tradeoffs="z",
        assignment_considerations="w",
    )


# ---------------------------------------------------------------------------
# _candidates_review_hash / _load_prior_reviews
# ---------------------------------------------------------------------------


class TestReviewHash:
    def test_stable_for_same_input(self):
        from src.orchestrator.scan import _candidates_review_hash

        top = [_candidate()]
        assert _candidates_review_hash(top, 15.0) == _candidates_review_hash(top, 15.0)

    def test_changes_when_a_signal_changes(self):
        from src.orchestrator.scan import _candidates_review_hash

        h1 = _candidates_review_hash([_candidate(blended_score=90.0)], 15.0)
        h2 = _candidates_review_hash([_candidate(blended_score=80.0)], 15.0)
        assert h1 != h2

    def test_changes_with_vix(self):
        from src.orchestrator.scan import _candidates_review_hash

        top = [_candidate()]
        assert _candidates_review_hash(top, 15.0) != _candidates_review_hash(top, 30.0)


class TestLoadPriorReviews:
    def test_returns_persisted_review(self, tmp_path, monkeypatch):
        _db_setup(tmp_path, monkeypatch)
        from src.orchestrator.scan import _load_prior_reviews
        from src.storage.db import session_scope
        from src.storage.models import ClaudeReviewRow

        with session_scope() as s:
            s.add(
                ClaudeReviewRow(
                    candidate_id="c-001",
                    priority=1,
                    recommendation="sell",
                    payload=_review().model_dump(mode="json"),
                )
            )
        got = _load_prior_reviews(["c-001", "c-002"])
        assert "c-002" not in got
        assert got["c-001"].recommendation == "sell"

    def test_returns_most_recent_per_candidate(self, tmp_path, monkeypatch):
        _db_setup(tmp_path, monkeypatch)
        from src.orchestrator.scan import _load_prior_reviews
        from src.storage.db import session_scope
        from src.storage.models import ClaudeReviewRow

        with session_scope() as s:
            for prio in (3, 1):  # later row has priority=1
                r = _review()
                r.priority = prio
                s.add(
                    ClaudeReviewRow(
                        candidate_id="c-001",
                        priority=prio,
                        recommendation="sell",
                        payload=r.model_dump(mode="json"),
                    )
                )
        assert _load_prior_reviews(["c-001"])["c-001"].priority == 1


# ---------------------------------------------------------------------------
# End-to-end: run_scan(intraday=True) reuses, intraday=False always reviews
# ---------------------------------------------------------------------------


def _make_account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=200_000.0,
        total_cash=150_000.0,
        buying_power=120_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=110_000.0,
    )


def _stub_pipeline(scanmod, monkeypatch, review_counter):
    """Stub a one-CSP-candidate pipeline so step 8 (Claude review) always has a stable top set."""
    cand = _candidate()

    monkeypatch.setattr(
        scanmod, "get_account_snapshot_async", AsyncMock(return_value=_make_account())
    )
    monkeypatch.setattr(scanmod, "get_positions", lambda ib: [])
    monkeypatch.setattr(scanmod, "get_market_conditions", lambda: MarketConditions(vix=15.0))

    async def _all_material(all_syms, holds, wo):
        return set(all_syms), {}

    monkeypatch.setattr(scanmod, "_compute_material_symbols", _all_material)

    async def _chain(ib, symbol):
        return [SimpleNamespace(mid=None, greeks_source="ibkr")]  # non-empty so CSP generation runs

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _chain)
    monkeypatch.setattr(scanmod, "persist_chain_quotes", lambda *a, **k: None)
    monkeypatch.setattr(scanmod, "get_iv_stats", lambda symbol, quotes=None: IVStats(symbol=symbol))
    monkeypatch.setattr(
        scanmod,
        "get_technical_stats",
        lambda symbol, **_: SimpleNamespace(symbol=symbol, price=100.0, price_source="yfinance"),
    )
    monkeypatch.setattr(scanmod, "get_fundamental_stats", lambda symbol: SimpleNamespace())

    class _Sent:
        def __init__(self, **k):
            pass

        def score(self, s):
            return None

    monkeypatch.setattr(scanmod, "SentimentScorer", _Sent)
    monkeypatch.setattr(scanmod, "generate_cc_candidates", lambda *a, **k: [])
    monkeypatch.setattr(scanmod, "generate_csp_candidates", lambda *a, **k: [cand])
    monkeypatch.setattr(scanmod, "generate_buy_candidates", lambda *a, **k: [])
    monkeypatch.setattr(scanmod, "score_candidates", lambda cands: cands)
    monkeypatch.setattr(
        scanmod,
        "validate_candidates",
        lambda scored, account, positions: [
            SimpleNamespace(candidate_id=c.candidate_id, verdict=SimpleNamespace(value="pass"))
            for c in scored
        ],
    )
    monkeypatch.setattr(scanmod, "select_top_candidates", lambda passed: passed)
    monkeypatch.setattr(scanmod, "_persist_memory", lambda *a, **k: None)
    monkeypatch.setattr(scanmod, "_persist_ledger", lambda *a, **k: None)
    monkeypatch.setattr(scanmod, "_load_memory", lambda syms: [])
    monkeypatch.setattr(scanmod, "send_candidates", AsyncMock())
    monkeypatch.setattr(scanmod, "send_buy_list", AsyncMock())

    def _fake_review(*a, **k):
        review_counter["n"] += 1
        return [_review()]

    monkeypatch.setattr(scanmod, "review_candidates", _fake_review)
    return cand


@pytest.mark.asyncio
async def test_intraday_reuses_review_when_unchanged(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    monkeypatch.setattr(get_config(), "universe", {"would_own": ["AAPL"], "sectors": {"AAPL": "t"}})
    counter = {"n": 0}
    _stub_pipeline(scanmod, monkeypatch, counter)

    from unittest.mock import MagicMock

    await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1", intraday=True)
    await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1", intraday=True)

    assert counter["n"] == 1  # second cycle reused the persisted review, skipped the LLM


@pytest.mark.asyncio
async def test_full_sweep_always_reviews(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    monkeypatch.setattr(get_config(), "universe", {"would_own": ["AAPL"], "sectors": {"AAPL": "t"}})
    counter = {"n": 0}
    _stub_pipeline(scanmod, monkeypatch, counter)

    from unittest.mock import MagicMock

    await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1")  # intraday=False
    await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1")

    assert counter["n"] == 2  # full sweeps never reuse
