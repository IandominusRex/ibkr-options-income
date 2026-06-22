"""Backtest-on-demand for a specific candidate's parameters (C11).

This is the importable core behind the ``scripts.backtest_candidate`` CLI **and** the
strategist-prompt injection (``claude.backtest_in_prompt``). It maps a live ``TradeCandidate``'s
parameters into a ``BacktestParams`` and runs the v2 harness, returning a compact result the
operator/strategist can read at decision time.

Fence note (CLAUDE.md): the backtest is **enrichment for verdict + ranking only**. Nothing here is
imported from ``engine/``, ``execution/``, or the sizing path — it reaches Claude solely through the
prompt builder, exactly like promoted skills. Keep it that way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.backtest.data import load_earnings_dates, load_iv_series, load_price_series
from src.backtest.earnings import EarningsCycleBacktestResult, simulate_earnings_cycles
from src.backtest.engine import BacktestParams, BacktestResult, simulate
from src.backtest.report import compact_report, format_earnings_cycle_report
from src.common.logging import get_logger
from src.common.schemas import TradeCandidate

log = get_logger(__name__)


@dataclass(frozen=True)
class BacktestOutcome:
    """Either a standard or earnings-cycle result, or a human message when nothing ran."""

    result: BacktestResult | None = None
    earnings_result: EarningsCycleBacktestResult | None = None
    error: str | None = None  # set when no backtest could be produced (no history etc.)


def params_from_candidate(
    cand: TradeCandidate,
    *,
    profit_take_pct: float | None = None,
    min_iv_rank: float | None = None,
    commission_per_contract: float = 0.65,
) -> BacktestParams:
    """Map a live candidate's parameters into a ``BacktestParams``.

    Delta/DTE/contracts come straight off the candidate. ``profit_take_pct`` and ``min_iv_rank``
    are decision knobs the caller supplies (e.g. from config) since they are not candidate fields;
    when omitted they default to the candidate's own IV-rank gate being off and no profit-take.
    """
    return BacktestParams(
        strategy=cand.strategy.value,
        target_delta=abs(cand.delta) if cand.delta is not None else 0.30,
        dte=cand.dte,
        contracts=cand.contracts,
        commission_per_contract=commission_per_contract,
        profit_take_pct=profit_take_pct,
        min_iv_rank=min_iv_rank,
    )


def run_backtest(
    symbol: str,
    params: BacktestParams,
    *,
    start: date | None = None,
    end: date | None = None,
    period: str = "2y",
    earnings: bool = False,
    blackout_before: int = 14,
    blackout_after: int = 3,
    vol_crush_dte: int | None = None,
) -> BacktestOutcome:
    """Load history, run the requested simulation, and return a ``BacktestOutcome``.

    Pure orchestration over the existing harness — never raises; failures surface as
    ``BacktestOutcome.error`` so prompt injection and the CLI degrade gracefully.
    """
    try:
        prices = load_price_series(symbol, start=start, end=end, period=period)
    except Exception as exc:  # defensive — loader already swallows, but stay total
        return BacktestOutcome(error=f"price load failed for {symbol}: {exc}")
    if not prices:
        return BacktestOutcome(error=f"No price history for {symbol} — nothing to backtest.")

    # Load the stored IV series only when a v2 feature needs it (matches the CLI).
    iv_series: list[float | None] | None = None
    if params.min_iv_rank is not None or params.profit_take_pct is not None:
        from src.storage.db import init_db

        init_db()
        iv_series = load_iv_series(symbol, [d for d, _ in prices])
        if not any(v is not None for v in iv_series):
            iv_series = None  # fall back to trailing-HV pricing

    if earnings:
        earnings_dates = load_earnings_dates(symbol)
        if not earnings_dates:
            return BacktestOutcome(
                error=f"No earnings dates found for {symbol} — cannot run earnings-cycle backtest."
            )
        ec = simulate_earnings_cycles(
            symbol,
            prices,
            params,
            earnings_dates,
            blackout_before=blackout_before,
            blackout_after=blackout_after,
            vol_crush_dte=vol_crush_dte,
            iv_series=iv_series,
        )
        return BacktestOutcome(earnings_result=ec)

    result = simulate(symbol, prices, params, iv_series=iv_series)
    return BacktestOutcome(result=result)


def summarize(outcome: BacktestOutcome) -> str:
    """Compact text for an outcome — the form injected into prompts / printed by the CLI."""
    if outcome.error is not None:
        return outcome.error
    if outcome.earnings_result is not None:
        return format_earnings_cycle_report(outcome.earnings_result)
    if outcome.result is not None:
        return compact_report(outcome.result)
    return "Backtest produced no result."


def backtest_candidate(
    cand: TradeCandidate,
    *,
    period: str = "2y",
    profit_take_pct: float | None = None,
    min_iv_rank: float | None = None,
) -> str:
    """Candidate → params → backtest → compact summary, in one call.

    This is the Claude-invocable action: ``strategist.build_prompt`` calls it (gated behind
    ``claude.backtest_in_prompt``) so the reasoning layer sees how the exact strike/DTE/delta
    behaved historically before it ranks the trade. Returns a one-block string, never raises.
    """
    try:
        params = params_from_candidate(
            cand, profit_take_pct=profit_take_pct, min_iv_rank=min_iv_rank
        )
        outcome = run_backtest(cand.underlying, params, period=period)
        return summarize(outcome)
    except Exception as exc:
        log.warning("backtest_candidate failed for %s: %s", cand.underlying, exc)
        return f"Backtest unavailable for {cand.underlying}."
