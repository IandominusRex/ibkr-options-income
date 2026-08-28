"""Tests for Phase 6 (Competitive Research Plan fix plan).

F1 — C6 adjusted cost basis wired into the EOD reconciler:
  * mark_campaign_assigned is right-aware (ACB only when shares are acquired).
  * assigned_shorts returns the OpenShort records (with strike) the reconciler feeds to C6.

F2 — C11 reusable, candidate-aware backtest:
  * params_from_candidate maps a TradeCandidate into BacktestParams.
  * run_backtest / backtest_candidate produce a compact result, fail-soft.
  * the strategist prompt injection is gated OFF by default.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.common.market_hours import today_et
from src.common.schemas import (
    FundamentalStats,
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _seed_fill(session, candidate_id: str, action: str, avg_price: float, qty: float) -> None:
    from src.storage.models import FillRow

    session.add(
        FillRow(
            order_id=1,
            candidate_id=candidate_id,
            action=action,
            filled_qty=qty,
            avg_price=avg_price,
            is_live=False,
        )
    )
    session.flush()


def _candidate(
    *,
    strategy: Strategy = Strategy.CASH_SECURED_PUT,
    right: OptionRight = OptionRight.PUT,
    delta: float | None = -0.20,
    dte: int = 30,
    contracts: int = 1,
) -> TradeCandidate:
    return TradeCandidate(
        candidate_id="bt-001",
        strategy=strategy,
        underlying="AAPL",
        right=right,
        strike=150.0,
        expiry=date.today() + timedelta(days=dte),
        contracts=contracts,
        premium=3.0,
        collateral=15_000.0,
        roc_pct=2.0,
        annualized_yield_pct=20.0,
        breakeven=147.0,
        delta=delta,
        dte=dte,
        scores=ScoreCard(symbol="AAPL"),
    )


def _rising_prices(
    n: int = 400, base: float = 100.0, drift: float = 0.0005, wobble: float = 0.02
) -> list[tuple[date, float]]:
    """Daily closes with a gentle drift plus an alternating wobble so trailing HV > 0
    (a flat/linear series prices every premium at ~0 and yields zero cycles)."""
    start = date(2023, 1, 2)
    out: list[tuple[date, float]] = []
    price = base
    for i in range(n):
        price *= 1 + drift
        c = price * (1 + (wobble if i % 2 == 0 else -wobble))
        out.append((start + timedelta(days=i), c))
    return out


# ---------------------------------------------------------------------------
# F1 — mark_campaign_assigned is right-aware
# ---------------------------------------------------------------------------


def test_mark_campaign_assigned_put_computes_acb(tmp_path, monkeypatch):
    """Short PUT assignment acquires shares → adjusted cost basis is computed (regression)."""
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import (
        attach_fill_to_campaign,
        load_campaigns,
        mark_campaign_assigned,
    )
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "cand-001", "SELL", 3.00, 1.0)  # $300 net premium
    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "SELL", 3.00, 1.0)

    mark_campaign_assigned("AAPL", assignment_price=150.0, right="P")

    c = load_campaigns()[0]
    assert c["assigned"] is True
    assert c["adjusted_cost_basis"] == pytest.approx(147.0)  # 150 − 300/100


def test_mark_campaign_assigned_call_skips_acb(tmp_path, monkeypatch):
    """Short CALL assignment calls shares away → flag assigned, leave basis untouched."""
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import (
        attach_fill_to_campaign,
        load_campaigns,
        mark_campaign_assigned,
    )
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "cand-001", "SELL", 2.00, 1.0)
    attach_fill_to_campaign("AAPL", "cand-001", "covered_call", "SELL", 2.00, 1.0)

    mark_campaign_assigned("AAPL", assignment_price=160.0, right="C")

    c = load_campaigns()[0]
    assert c["assigned"] is True
    assert c["adjusted_cost_basis"] is None


def test_mark_campaign_assigned_unknown_right_defaults_to_acb(tmp_path, monkeypatch):
    """No `right` supplied → backward-compatible behaviour (computes ACB)."""
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import (
        attach_fill_to_campaign,
        load_campaigns,
        mark_campaign_assigned,
    )
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "cand-001", "SELL", 3.00, 1.0)
    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "SELL", 3.00, 1.0)

    mark_campaign_assigned("AAPL", assignment_price=150.0)  # no right

    assert load_campaigns()[0]["adjusted_cost_basis"] == pytest.approx(147.0)


# ---------------------------------------------------------------------------
# F1 — assigned_shorts surfaces the strike for the reconciler
# ---------------------------------------------------------------------------


def test_assigned_shorts_returns_records_with_strike(monkeypatch):
    """assigned_shorts returns OpenShort objects (carrying strike) for assigned positions."""
    import src.claude.eval.assignment as amod
    from src.claude.eval.assignment import OpenShort, assigned_candidate_ids, assigned_shorts

    today = date(2024, 1, 19)
    short = OpenShort(
        candidate_id="c1",
        underlying="AAPL",
        right="P",
        strike=180.0,
        expiry=today,
        contracts=2.0,
    )
    current = [
        PositionSnapshot(
            symbol="AAPL", sec_type="STK", position=200.0, avg_cost=0.0, underlying="AAPL"
        )
    ]
    monkeypatch.setattr(amod, "open_shorts_from_ledger", lambda: [short])
    monkeypatch.setattr(amod, "load_latest_position_snapshot", lambda before: [])

    shorts = assigned_shorts(current, today)
    assert len(shorts) == 1
    assert shorts[0].strike == 180.0
    assert shorts[0].right == "P"
    # The id-set helper stays consistent with the richer one.
    assert assigned_candidate_ids(current, today) == {"c1"}


# ---------------------------------------------------------------------------
# F2 — params_from_candidate
# ---------------------------------------------------------------------------


def test_params_from_candidate_maps_put(monkeypatch):
    from src.backtest.on_demand import params_from_candidate

    cand = _candidate(delta=-0.22, dte=28, contracts=3)
    p = params_from_candidate(cand)
    assert p.strategy == "cash_secured_put"
    assert p.target_delta == pytest.approx(0.22)  # abs(delta)
    assert p.dte == 28
    assert p.contracts == 3
    assert p.profit_take_pct is None
    assert p.min_iv_rank is None


def test_params_from_candidate_call_and_overrides():
    from src.backtest.on_demand import params_from_candidate

    cand = _candidate(strategy=Strategy.COVERED_CALL, right=OptionRight.CALL, delta=0.30)
    p = params_from_candidate(cand, profit_take_pct=0.5, min_iv_rank=30.0)
    assert p.strategy == "covered_call"
    assert p.target_delta == pytest.approx(0.30)
    assert p.profit_take_pct == 0.5
    assert p.min_iv_rank == 30.0


def test_params_from_candidate_missing_delta_defaults():
    from src.backtest.on_demand import params_from_candidate

    p = params_from_candidate(_candidate(delta=None))
    assert p.target_delta == pytest.approx(0.30)


# ---------------------------------------------------------------------------
# F2 — run_backtest / summarize / backtest_candidate
# ---------------------------------------------------------------------------


def test_run_backtest_no_history_is_error(monkeypatch):
    import src.backtest.on_demand as od

    monkeypatch.setattr(od, "load_price_series", lambda *a, **k: [])
    out = od.run_backtest("AAPL", od.params_from_candidate(_candidate()))
    assert out.result is None
    assert out.error is not None
    assert "AAPL" in out.error


def test_run_backtest_standard_result(monkeypatch):
    import src.backtest.on_demand as od

    monkeypatch.setattr(od, "load_price_series", lambda *a, **k: _rising_prices())
    out = od.run_backtest("AAPL", od.params_from_candidate(_candidate()))
    assert out.error is None
    assert out.result is not None
    assert out.result.symbol == "AAPL"
    assert out.result.num_cycles > 0


def test_summarize_standard_is_compact(monkeypatch):
    import src.backtest.on_demand as od

    monkeypatch.setattr(od, "load_price_series", lambda *a, **k: _rising_prices())
    out = od.run_backtest("AAPL", od.params_from_candidate(_candidate()))
    text = od.summarize(out)
    assert "Backtest" in text
    assert "Cycles:" in text


def test_summarize_error_passthrough():
    from src.backtest.on_demand import BacktestOutcome, summarize

    assert summarize(BacktestOutcome(error="no data")) == "no data"


def test_backtest_candidate_returns_compact_string(monkeypatch):
    import src.backtest.on_demand as od

    monkeypatch.setattr(od, "load_price_series", lambda *a, **k: _rising_prices())
    text = od.backtest_candidate(_candidate())
    assert "Backtest" in text


def test_backtest_candidate_is_fail_soft(monkeypatch):
    import src.backtest.on_demand as od

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(od, "run_backtest", _boom)
    text = od.backtest_candidate(_candidate())
    assert "unavailable" in text.lower()


# ---------------------------------------------------------------------------
# F2 — strategist prompt injection is gated
# ---------------------------------------------------------------------------


def test_backtest_line_off_by_default(monkeypatch):
    from src.claude.prompts.strategist import _backtest_line
    from src.common.config import get_config

    monkeypatch.setattr(get_config().claude, "backtest_in_prompt", False)
    assert _backtest_line(_candidate()) == ""


def test_backtest_line_on_injects(monkeypatch):
    import src.backtest.on_demand as od
    from src.claude.prompts.strategist import _backtest_line
    from src.common.config import get_config

    monkeypatch.setattr(get_config().claude, "backtest_in_prompt", True)
    monkeypatch.setattr(od, "backtest_candidate", lambda c, **k: "Backtest XYZ summary")
    line = _backtest_line(_candidate())
    assert "Backtest" in line and "XYZ" in line


def test_build_prompt_excludes_backtest_when_off(monkeypatch):
    """Default config: build_prompt produces no backtest line (no network at prompt time)."""
    from src.claude.prompts.strategist import build_prompt
    from src.common.config import get_config
    from src.common.schemas import AccountSnapshot

    monkeypatch.setattr(get_config().claude, "backtest_in_prompt", False)
    acct = AccountSnapshot(
        account="DU1",
        net_liquidation=100_000.0,
        total_cash=50_000.0,
        buying_power=50_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=40_000.0,
    )
    prompt = build_prompt([_candidate()], acct)
    assert "Backtest:" not in prompt


# ---------------------------------------------------------------------------
# D5 — wheel-adjusted cost basis reaches the covered-call gate
# ---------------------------------------------------------------------------


def _cc_quote_at(strike: float, *, dte: int = 20) -> OptionQuote:
    """A single CALL quote priced to clear every CC gate except (pre-fix) cost basis.

    Delta (0.28) and DTE (20) sit mid-band for `covered_call.delta_min/max` (0.20/0.35) and
    `dte_min/max` (7/28). The $5.00/$5.40 market (mid $5.20, spread 7.7% < the 10% liquidity
    cap) is priced above the Black-Scholes-at-HV30 floor for a spot near this strike — verified
    by hand: ``bs_price(147.0, 147.0, 20, 0.22, "C") * 1.10 edge ≈ $3.54 < $5.20`` — so the VRP
    floor (`income.require_vrp_edge`) does not confound the basis-gate assertion this test
    exists to prove.
    """
    return OptionQuote(
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=strike,
        expiry=today_et() + timedelta(days=dte),
        bid=5.00,
        ask=5.40,
        volume=500,
        open_interest=2000,
        iv=0.28,
        delta=0.28,
    )


def test_covered_call_uses_campaign_adjusted_cost_basis(tmp_path, monkeypatch):
    """D5: premium already collected must be visible to the gate deciding on more.

    A CSP on AAPL is assigned at $150 after collecting $4.50/share of premium across the
    campaign, so the wheel's true basis is $145.50 — but the raw IBKR `avg_cost` on the
    resulting stock position is $150.00. A $147 call is genuinely profitable against the
    true basis and must pass; screened against the raw $150 basis it would be rejected as
    below cost.
    """
    from src.storage.campaigns import attach_fill_to_campaign, mark_campaign_assigned
    from src.storage.db import session_scope
    from src.strategies.covered_call import screen_cc_candidates

    _db_setup(tmp_path, monkeypatch)
    # attach_fill_to_campaign rolls up financials from FillRow, not from its own arguments —
    # a real FillRow (as the executor writes on every fill) must exist first, matching the
    # pattern the F1 tests above already use (_seed_fill then attach_fill_to_campaign).
    with session_scope() as s:
        _seed_fill(s, "cand-1", "SELL", 4.50, 1.0)  # $450 net premium on 1 contract
    attach_fill_to_campaign("AAPL", "cand-1", "cash_secured_put", "SELL", 4.50, 1.0)
    mark_campaign_assigned("AAPL", assignment_price=150.0, right="P")

    pos = PositionSnapshot(
        symbol="AAPL", sec_type="STK", position=100, avg_cost=150.0, underlying="AAPL"
    )
    iv_stats = IVStats(symbol="AAPL", current_iv=28.0, iv_rank=55.0, hv_30=22.0)
    tech = TechnicalStats(symbol="AAPL", price=147.0, rsi_14=55.0)
    fund = FundamentalStats(symbol="AAPL")

    result = screen_cc_candidates("AAPL", [_cc_quote_at(147.0)], pos, iv_stats, tech, fund)

    # Adjusted basis is 150.00 - 4.50 = 145.50, so the $147 strike is ABOVE basis and allowed.
    passed_strikes = [c.strike for c in result.passed]
    assert 147.0 in passed_strikes, [r for _, r in result.rejected]
