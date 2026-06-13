"""Plain-text formatting of a BacktestResult for the CLI."""

from __future__ import annotations

from src.backtest.engine import BacktestResult


def format_report(result: BacktestResult) -> str:
    """Return a human-readable summary of a backtest run."""
    p = result.params
    lines = [
        f"Backtest — {result.symbol} {result.strategy}",
        f"  Window:        {result.start} → {result.end}",
        f"  Params:        Δ{p.target_delta:.2f} · {p.dte}d · {p.contracts} contract(s) "
        f"· r={p.risk_free_rate:.0%} · comm ${p.commission_per_contract:.2f}",
        f"  Cycles:        {result.num_cycles}",
    ]
    if result.num_cycles == 0:
        lines.append("  (no cycles — insufficient price history for the requested window)")
        return "\n".join(lines)

    iv_note = (
        "stored IV (measures VRP)" if result.iv_source == "stored_iv" else "trailing HV (fair-value proxy)"
    )
    lines += [
        f"  Pricing IV:    {iv_note}",
        f"  Mean VRP:      {result.mean_vrp_pct:+.1f}%  (entry IV − HV; >0 ⇒ options were rich)",
        f"  Premium total: ${result.total_premium:,.0f}",
        f"  Net P&L:       ${result.total_pnl:,.0f}",
        f"  Win rate:      {result.win_rate:.0%}",
        f"  Profit-take:   {result.profit_take_rate:.0%}  (cycles closed early at the 50% rule)",
        f"  Assignment:    {result.assignment_rate:.0%}",
        f"  Capital base:  ${result.capital_base:,.0f}",
        f"  Return on cap: {result.return_on_capital_pct:.1f}%",
        f"  Annualized:    {result.annualized_return_pct:.1f}%",
        f"  Buy & hold:    {result.buy_hold_return_pct:.1f}%  (benchmark, underlying only)",
        f"  Max drawdown:  {result.max_drawdown_pct:.1f}%",
    ]
    return "\n".join(lines)
