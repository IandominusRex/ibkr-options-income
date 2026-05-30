"""Deterministic hard-limit gate. NO LLM involvement. The only path to order execution.

Runs twice: once at decision time (here), once again in the execution engine against a
fresh live quote (Phase 7). Purely deterministic — no external calls.
"""

from __future__ import annotations

from src.common.config import get_config
from src.common.schemas import (
    AccountSnapshot,
    PositionSnapshot,
    RiskVerdict,
    Strategy,
    TradeCandidate,
    Verdict,
)


def _strategy_limits(strategy: Strategy) -> dict:
    """Return the strategy-specific limits dict from risk_limits.yaml."""
    return get_config().risk.get(strategy.value, {})


def validate_candidates(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
) -> list[RiskVerdict]:
    """Gate each candidate against hard limits. Returns one RiskVerdict per candidate."""
    if not candidates:
        return []

    cfg = get_config()
    income = cfg.risk.get("income", {})
    portfolio = cfg.risk.get("portfolio", {})

    # Account-level flags — computed once, applied to every candidate.
    margin_usage_pct = (
        account.maintenance_margin / account.net_liquidation * 100
        if account.net_liquidation > 0
        else 0.0
    )
    margin_exceeded = margin_usage_pct > portfolio.get("max_margin_usage_pct", 50.0)

    required_bp = account.net_liquidation * portfolio.get("min_buying_power_buffer_pct", 15.0) / 100
    bp_short = account.buying_power < required_bp

    verdicts: list[RiskVerdict] = []

    for cand in candidates:
        reasons: list[str] = []
        limits = _strategy_limits(cand.strategy)

        # --- Income gates (defense-in-depth; strategies filter these too) ---
        if cand.roc_pct < income.get("min_roc_pct", 1.0):
            reasons.append("roc_below_minimum")

        if cand.annualized_yield_pct < income.get("min_annualized_yield_pct", 12.0):
            reasons.append("yield_below_minimum")

        # --- Strategy-specific DTE + delta range ---
        if limits:
            if not (limits.get("dte_min", 0) <= cand.dte <= limits.get("dte_max", 999)):
                reasons.append("dte_out_of_range")

            if cand.delta is None:
                reasons.append("delta_missing")
            else:
                delta_abs = abs(cand.delta)
                if not (limits.get("delta_min", 0.0) <= delta_abs <= limits.get("delta_max", 1.0)):
                    reasons.append("delta_out_of_range")

        # --- Contract count ---
        if cand.contracts < 1:
            reasons.append("no_contracts")

        # --- Per-ticker concentration ---
        max_ticker_value = account.net_liquidation * portfolio.get("max_pct_per_ticker", 5.0) / 100
        existing_value = sum(
            abs(p.market_value or 0.0)
            for p in positions
            if p.symbol == cand.underlying or p.underlying == cand.underlying
        )
        if existing_value + cand.collateral > max_ticker_value:
            reasons.append("concentration_limit")

        # --- Account-level checks ---
        if margin_exceeded:
            reasons.append("margin_limit")

        if bp_short:
            reasons.append("buying_power_buffer")

        # TODO(Phase 4): earnings blackout requires fund_stats passthrough.
        # TradeCandidate does not carry next_earnings; Phase 5/8 handles this.

        verdicts.append(
            RiskVerdict(
                candidate_id=cand.candidate_id,
                verdict=Verdict.PASS if not reasons else Verdict.REJECT,
                reasons=reasons,
            )
        )

    return verdicts
