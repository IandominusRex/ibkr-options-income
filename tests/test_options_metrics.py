"""Task 5.5: options-income metrics wired to the analytics tier.

Honest degradation is the point: a universe symbol with real IV history produces a real
iv_rank; an off-universe symbol with none produces None (never a fabricated percentile).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.schemas import FundamentalStats, IVStats
from src.research.checks.metrics import build_metrics


def _db_setup(tmp_path, monkeypatch) -> None:
    """Point the TRADING db (src.storage.db) — home of iv_history — at a scratch sqlite file."""
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


# ── build_metrics: iv_stats wiring ──────────────────────────────────────────────


def test_a_universe_symbol_with_iv_history_produces_a_real_iv_rank(tmp_path, monkeypatch) -> None:
    """The exact path get_iv_stats -> build_metrics for a symbol with seeded observations."""
    _db_setup(tmp_path, monkeypatch)
    from src.analytics.iv import get_iv_stats
    from src.storage.iv_history import append_observation

    today = date.today()
    for i, iv in enumerate([0.20, 0.25, 0.30, 0.35, 0.80]):
        append_observation("SOXL", today - timedelta(days=i), iv)

    iv_stats = get_iv_stats("SOXL")
    metrics = build_metrics(price=45.0, iv_stats=iv_stats)
    assert metrics["iv_rank"] is not None
    assert 0.0 <= metrics["iv_rank"] <= 100.0


def test_an_off_universe_symbol_with_no_iv_history_produces_none(tmp_path, monkeypatch) -> None:
    """No fallback to a made-up percentile — UNKNOWN is the honest answer."""
    _db_setup(tmp_path, monkeypatch)
    from src.analytics.iv import get_iv_stats

    iv_stats = get_iv_stats("ZZZZ_NOT_A_REAL_SYMBOL")
    metrics = build_metrics(price=10.0, iv_stats=iv_stats)
    assert metrics["iv_rank"] is None
    assert metrics["current_iv"] is None
    assert metrics["hv_30"] is None


def test_iv_stats_none_leaves_options_metrics_absent() -> None:
    metrics = build_metrics(price=100.0)
    assert "iv_rank" not in metrics
    assert "current_iv" not in metrics


# ── build_metrics: est_monthly_cc_yield_pct reuses buy_candidates' heuristic ────


def test_est_monthly_cc_yield_pct_reuses_the_buy_candidates_heuristic() -> None:
    from src.strategies.buy_candidates import _est_monthly_cc_yield

    iv_stats = IVStats(symbol="AAPL", current_iv=30.0)
    expected_fraction = _est_monthly_cc_yield(iv_stats)
    assert expected_fraction is not None

    metrics = build_metrics(price=100.0, iv_stats=iv_stats)
    # Percentage points, like every other percentage metric in this module — not a fraction.
    assert metrics["est_monthly_cc_yield_pct"] == pytest.approx(expected_fraction * 100.0)


def test_est_monthly_cc_yield_pct_is_none_without_current_iv() -> None:
    iv_stats = IVStats(symbol="ZZZZ_NOT_A_REAL_SYMBOL")  # no history -> current_iv is None
    metrics = build_metrics(price=100.0, iv_stats=iv_stats)
    assert metrics.get("est_monthly_cc_yield_pct") is None


def test_est_monthly_cc_yield_pct_metric_fn_is_a_passthrough() -> None:
    from src.research.checks.metrics import METRICS

    assert METRICS["est_monthly_cc_yield_pct"]({"est_monthly_cc_yield_pct": 2.5}) == 2.5
    assert METRICS["est_monthly_cc_yield_pct"]({}) is None


# ── build_metrics: days_to_earnings ─────────────────────────────────────────────


def test_days_to_earnings_from_a_known_next_earnings_date() -> None:
    fund = FundamentalStats(symbol="AAPL", next_earnings=date.today() + timedelta(days=12))
    metrics = build_metrics(price=100.0, fundamentals=fund)
    assert metrics["days_to_earnings"] == pytest.approx(12.0, abs=1.0)


def test_days_to_earnings_is_none_without_a_known_earnings_date() -> None:
    """Never a large sentinel that would silently pass the 45-day check."""
    fund = FundamentalStats(symbol="AAPL", next_earnings=None)
    metrics = build_metrics(price=100.0, fundamentals=fund)
    assert metrics["days_to_earnings"] is None


def test_days_to_earnings_past_date_is_none_not_negative() -> None:
    fund = FundamentalStats(symbol="AAPL", next_earnings=date.today() - timedelta(days=5))
    metrics = build_metrics(price=100.0, fundamentals=fund)
    assert metrics["days_to_earnings"] is None


# ── atm_open_interest / atm_spread_pct: still passthroughs, still None ─────────


def test_atm_metrics_stay_none_until_milestone_6_regardless_of_iv_or_fundamentals() -> None:
    iv_stats = IVStats(symbol="AAPL", current_iv=30.0)
    fund = FundamentalStats(symbol="AAPL")
    metrics = build_metrics(price=100.0, iv_stats=iv_stats, fundamentals=fund)
    assert metrics.get("atm_open_interest") is None
    assert metrics.get("atm_spread_pct") is None


# ── build_metrics: ETF fund-data sourcing ───────────────────────────────────────
# Task 5.4's handoff note deferred expense_ratio/aum/avg_volume/inception sourcing to
# 5.5 alongside the options-tier integration, since nothing else in the plan owns it.


def test_etf_fund_metrics_populate_from_fundamental_stats() -> None:
    fund = FundamentalStats(
        symbol="SPY",
        expense_ratio=0.09,
        total_assets=500_000_000_000.0,
        avg_volume=70_000_000.0,
        inception_date=date(1993, 1, 22),
    )
    metrics = build_metrics(price=550.0, is_etf=True, fundamentals=fund)
    assert metrics["expense_ratio"] == 0.09
    assert metrics["total_assets_fund"] == 500_000_000_000.0
    assert metrics["avg_volume"] == 70_000_000.0
    assert metrics["years_since_inception"] > 30

    from src.research.checks.metrics import METRICS

    assert METRICS["aum_usd"](metrics) == 500_000_000_000.0
    assert METRICS["avg_dollar_volume_usd"](metrics) == pytest.approx(550.0 * 70_000_000.0)


def test_etf_fund_metrics_are_none_without_an_inception_date() -> None:
    fund = FundamentalStats(symbol="NEWETF", expense_ratio=0.2)
    metrics = build_metrics(price=50.0, is_etf=True, fundamentals=fund)
    assert metrics["expense_ratio"] == 0.2
    assert metrics["years_since_inception"] is None


def test_a_stock_never_gets_etf_fund_fields_even_with_fundamentals_present() -> None:
    """is_etf=False must gate this, or a stock could accidentally pass fund.* checks."""
    fund = FundamentalStats(symbol="AAPL", expense_ratio=0.09)
    metrics = build_metrics(price=180.0, is_etf=False, fundamentals=fund)
    assert "expense_ratio" not in metrics
    assert "years_since_inception" not in metrics


def test_etf_fund_metrics_absent_without_a_fundamentals_object() -> None:
    metrics = build_metrics(price=550.0, is_etf=True)
    assert "expense_ratio" not in metrics


# ── materialize(): the metrics dict is assembled end to end ────────────────────


def test_materialize_populates_metrics_from_iv_and_fundamentals(tmp_path, monkeypatch) -> None:
    from src.research.ingest.materialize import materialize
    from src.research.store.models import SymbolRow
    from src.research.store.session import init_research_db, research_session

    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()
    with research_session() as s:
        s.add(SymbolRow(symbol="AAPL", cik="0000320193", name="Apple Inc.", is_etf=False))

    monkeypatch.setattr(
        "src.analytics.iv.get_iv_stats",
        lambda symbol: IVStats(symbol=symbol, current_iv=40.0, iv_rank=55.0, hv_30=30.0),
    )
    monkeypatch.setattr(
        "src.analytics.fundamentals.get_fundamental_stats",
        lambda symbol: FundamentalStats(symbol=symbol, next_earnings=date.today() + timedelta(days=50)),
    )

    result = materialize("AAPL")
    assert result.metrics is not None
    assert result.metrics["iv_rank"] == 55.0
    assert result.metrics["current_iv"] == 40.0
    assert result.metrics["hv_30"] == 30.0
    assert result.metrics["days_to_earnings"] == pytest.approx(50.0, abs=1.0)
    assert result.metrics["est_monthly_cc_yield_pct"] is not None


def test_materialize_populates_etf_fund_metrics(tmp_path, monkeypatch) -> None:
    from src.research.ingest.materialize import materialize
    from src.research.store.models import SymbolRow
    from src.research.store.session import init_research_db, research_session

    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()
    with research_session() as s:
        s.add(SymbolRow(symbol="SPY", cik="0000884394", name="SPDR S&P 500", is_etf=True))

    monkeypatch.setattr(
        "src.analytics.iv.get_iv_stats",
        lambda symbol: IVStats(symbol=symbol),
    )
    monkeypatch.setattr(
        "src.analytics.fundamentals.get_fundamental_stats",
        lambda symbol: FundamentalStats(
            symbol=symbol,
            expense_ratio=0.09,
            total_assets=500_000_000_000.0,
            avg_volume=70_000_000.0,
            inception_date=date(1993, 1, 22),
        ),
    )

    result = materialize("SPY")
    assert result.metrics is not None
    assert result.metrics["expense_ratio"] == 0.09
    assert result.metrics["total_assets_fund"] == 500_000_000_000.0
    assert result.metrics["years_since_inception"] > 30


def test_materialize_unknown_symbol_has_no_metrics(tmp_path, monkeypatch) -> None:
    from src.research.ingest.materialize import materialize
    from src.research.store.session import init_research_db, research_session

    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()
    with research_session():
        pass

    result = materialize("NOPE")
    assert result.metrics is None
