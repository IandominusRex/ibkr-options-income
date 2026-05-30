"""Format TradeCandidate + optional ClaudeReview into a Telegram MarkdownV2 message.

Also provides formatters for query commands: positions, account, health, status.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from src.common.schemas import (
    AccountSnapshot,
    ClaudeReview,
    EODSummary,
    OptionRight,
    PositionSnapshot,
    TradeCandidate,
)

_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")

_MAX_MESSAGE_LEN = 4000


def _md(text: str) -> str:
    """Escape all MarkdownV2 special characters."""
    return _ESCAPE_RE.sub(r"\\\1", str(text))


def format_candidate(
    candidate: TradeCandidate,
    review: ClaudeReview | None,
) -> str:
    """Build the human-readable Telegram MarkdownV2 message for one trade candidate."""
    strategy_label = candidate.strategy.value.replace("_", " ").title()
    right_label = "Call" if candidate.right == OptionRight.CALL else "Put"
    contract_value = candidate.premium * 100

    parts: list[str] = [
        f"*{_md(candidate.underlying)} \\- {_md(strategy_label)} \\({_md(right_label)}\\)*",
        (
            f"Strike: \\${_md(f'{candidate.strike:.2f}')} \\| "
            f"Expiry: {_md(str(candidate.expiry))} \\({_md(str(candidate.dte))} DTE\\)"
        ),
        "",
        (
            f"Premium: \\${_md(f'{candidate.premium:.2f}')}/share "
            f"\\(\\${_md(f'{contract_value:.0f}')}/contract\\)"
        ),
        (
            f"ROC: {_md(f'{candidate.roc_pct:.2f}')}% \\| "
            f"Ann\\. Yield: {_md(f'{candidate.annualized_yield_pct:.1f}')}%"
        ),
    ]

    delta_str = f"{candidate.delta:.2f}" if candidate.delta is not None else "N/A"
    iv_str = f"{candidate.iv_rank:.0f}" if candidate.iv_rank is not None else "N/A"
    parts.append(f"Delta: {_md(delta_str)} \\| IV Rank: {_md(iv_str)}")

    parts.append(f"Score: {_md(f'{candidate.blended_score:.1f}')}/100")

    if candidate.rationale_tags:
        tags_str = ", ".join(_md(t) for t in candidate.rationale_tags)
        parts.append(f"Tags: {tags_str}")

    if review is not None:
        conf_str = (
            f" \\| confidence {_md(f'{review.confidence:.0%}')}"
            if review.confidence is not None
            else ""
        )
        parts += [
            "",
            f"*── Claude Analysis \\(Priority {_md(str(review.priority))}\\) ──*",
            f"Decision: *{_md(review.recommendation.upper())}*{conf_str}",
            f"Why attractive: {_md(review.why_attractive)}",
            f"Risks: {_md(review.risks)}",
            f"Tradeoffs: {_md(review.tradeoffs)}",
        ]
        if review.assignment_considerations:
            parts.append(f"Assignment: {_md(review.assignment_considerations)}")
        if review.rolling_considerations:
            parts.append(f"Rolling: {_md(review.rolling_considerations)}")

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text


def format_help() -> str:
    """List all available bot commands."""
    lines = [
        "*IBKR Options Bot \\— Commands*",
        "",
        "/scan \\— Run full pipeline scan \\(CC/CSP/buy opportunities\\)",
        "/status \\— Account \\+ short options \\+ pending approvals",
        "/positions \\— Full portfolio positions with P&L",
        "/account \\— Account balances \\(buying power, net liq, margin\\)",
        "/health \\— System health \\(connections, DB, last scan, open orders\\)",
        "/help \\— Show this message",
    ]
    return "\n".join(lines)


def format_positions(
    positions: list[PositionSnapshot],
    account: AccountSnapshot | None = None,
) -> str:
    """Format full portfolio positions for Telegram."""
    parts: list[str] = ["*Portfolio Positions*"]

    if account:
        parts += [
            "",
            (
                f"Net Liq: \\${_md(f'{account.net_liquidation:,.0f}')} \\| "
                f"BP: \\${_md(f'{account.buying_power:,.0f}')}"
            ),
        ]

    if not positions:
        parts += ["", "No open positions\\."]
        return "\n".join(parts)

    stocks = [p for p in positions if p.sec_type == "STK"]
    options = [p for p in positions if p.sec_type == "OPT"]

    if stocks:
        parts += ["", "*Stocks*"]
        for p in sorted(stocks, key=lambda x: x.symbol):
            price_s = f" @ \\${_md(f'{p.market_price:.2f}')}" if p.market_price else ""
            mv_s = f" \\| MV \\${_md(f'{p.market_value:,.0f}')}" if p.market_value else ""
            if p.unrealized_pnl is not None:
                sign = "+" if p.unrealized_pnl >= 0 else ""
                pnl_s = f" \\| {_md(f'{sign}{p.unrealized_pnl:,.0f}')}"
            else:
                pnl_s = ""
            parts.append(
                f"  {_md(p.symbol)}: {_md(f'{p.position:.0f}')} shares{price_s}{mv_s}{pnl_s}"
            )

    if options:
        parts += ["", "*Options*"]
        for p in sorted(options, key=lambda x: (x.expiry or date.max, x.symbol)):
            side = "SHORT" if p.position < 0 else "LONG"
            qty = abs(int(p.position))
            right_lbl = ("C" if p.right == OptionRight.CALL else "P") if p.right else ""
            strike_s = f"\\${_md(f'{p.strike:.0f}')}" if p.strike else ""
            exp_s = _md(str(p.expiry)) if p.expiry else ""
            dte = (p.expiry - date.today()).days if p.expiry else None
            dte_s = f" \\({_md(str(dte))}d\\)" if dte is not None else ""
            price_s = f" @ \\${_md(f'{p.market_price:.2f}')}" if p.market_price else ""
            if p.unrealized_pnl is not None:
                sign = "+" if p.unrealized_pnl >= 0 else ""
                pnl_s = f" \\| {_md(f'{sign}{p.unrealized_pnl:.0f}')}"
            else:
                pnl_s = ""
            sym = _md(p.underlying or p.symbol.split()[0])
            parts.append(
                f"  {sym} {side} {qty}x {strike_s}{right_lbl} {exp_s}{dte_s}{price_s}{pnl_s}"
            )

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text


def format_account(account: AccountSnapshot) -> str:
    """Format account summary for Telegram."""
    ts = _md(account.captured_at.strftime("%Y-%m-%d %H:%M UTC"))
    parts = [
        "*Account Summary*",
        "",
        f"Net Liquidation:  \\${_md(f'{account.net_liquidation:,.2f}')}",
        f"Total Cash:       \\${_md(f'{account.total_cash:,.2f}')}",
        f"Buying Power:     \\${_md(f'{account.buying_power:,.2f}')}",
        f"Maint\\. Margin:   \\${_md(f'{account.maintenance_margin:,.2f}')}",
        f"Excess Liquidity: \\${_md(f'{account.excess_liquidity:,.2f}')}",
        "",
        f"_Snapshot: {ts}_",
    ]
    return "\n".join(parts)


def format_health(
    ib_exec_ok: bool,
    ib_scan_ok: bool,
    last_scan_at: datetime | None,
    pending_approvals: int,
    open_orders: int,
    db_ok: bool,
) -> str:
    """Format system health status for Telegram."""

    def icon(ok: bool) -> str:
        return "OK" if ok else "FAIL"

    since_str = "never"
    if last_scan_at is not None:
        aware = (
            last_scan_at.replace(tzinfo=UTC) if last_scan_at.tzinfo is None else last_scan_at
        )
        mins = int((datetime.now(UTC) - aware).total_seconds() / 60)
        since_str = f"{mins}m ago"

    parts = [
        "*System Health*",
        "",
        f"IBKR Exec \\(clientId 14\\):  {_md(icon(ib_exec_ok))}",
        f"IBKR Scan \\(clientId 15\\):  {_md(icon(ib_scan_ok))}",
        f"Database:                    {_md(icon(db_ok))}",
        f"Last scan:                   {_md(since_str)}",
        f"Pending approvals:           {_md(str(pending_approvals))}",
        f"Open orders:                 {_md(str(open_orders))}",
    ]
    return "\n".join(parts)


def format_status(
    positions: list[PositionSnapshot],
    account: AccountSnapshot | None,
    pending_approvals: int,
    open_orders: int,
) -> str:
    """Compact status overview: account + short options + pending approvals."""
    parts: list[str] = ["*System Status*"]

    if account:
        total_unr = sum(p.unrealized_pnl or 0.0 for p in positions)
        sign = "+" if total_unr >= 0 else ""
        parts += [
            "",
            f"Net Liq:   \\${_md(f'{account.net_liquidation:,.0f}')}",
            f"BP:        \\${_md(f'{account.buying_power:,.0f}')}",
            f"Unr\\. P&L: {_md(f'{sign}{total_unr:,.0f}')}",
        ]

    stocks = [p for p in positions if p.sec_type == "STK"]
    options = [p for p in positions if p.sec_type == "OPT"]
    short_opts = [p for p in options if p.position < 0]

    parts += [
        "",
        (
            f"Positions: {_md(str(len(stocks)))} stocks, "
            f"{_md(str(len(options)))} options "
            f"\\({_md(str(len(short_opts)))} short\\)"
        ),
    ]

    if short_opts:
        parts += ["", "*Active Short Options*"]
        for p in sorted(short_opts, key=lambda x: x.expiry or date.max):
            right_lbl = ("C" if p.right == OptionRight.CALL else "P") if p.right else ""
            strike_s = f"\\${_md(f'{p.strike:.0f}')}" if p.strike else ""
            dte = (p.expiry - date.today()).days if p.expiry else None
            dte_s = f" {_md(str(dte))}d" if dte is not None else ""
            qty = abs(int(p.position))
            sym = _md(p.underlying or p.symbol.split()[0])
            if p.unrealized_pnl is not None:
                sign = "+" if p.unrealized_pnl >= 0 else ""
                pnl_s = f" {_md(f'{sign}{p.unrealized_pnl:.0f}')}"
            else:
                pnl_s = ""
            parts.append(f"  {sym} {strike_s}{right_lbl}{dte_s} x{qty}{pnl_s}")

    parts += [
        "",
        f"Pending approvals: {_md(str(pending_approvals))}",
        f"Open orders:       {_md(str(open_orders))}",
    ]

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text


def _eod_sign(v: float) -> str:
    return f"+${v:.2f}" if v >= 0 else f"-${abs(v):.2f}"


def format_eod_summary(summary: EODSummary, narrative: str | None) -> str:
    """Build the informational-only Telegram MarkdownV2 EOD message (no approval keyboard)."""
    parts: list[str] = [
        f"*EOD Report \\— {_md(str(summary.date))}*",
        "",
        f"Realized: {_md(_eod_sign(summary.realized_pnl))}",
        (
            f"Unrealized: {_md(_eod_sign(summary.unrealized_pnl))} "
            f"\\(Δ {_md(_eod_sign(summary.unrealized_pnl_delta))}\\)"
        ),
        (
            f"Open positions: {_md(str(summary.open_positions))} \\| "
            f"Net delta: {_md(f'{summary.net_delta_exposure:.2f}')}"
        ),
    ]

    if summary.fills_today > 0:
        parts += ["", f"Fills today: {_md(str(summary.fills_today))}"]

    if summary.top_movers:
        movers_str = ", ".join(_md(s) for s in summary.top_movers)
        parts.append(f"Top movers: {movers_str}")

    if narrative:
        parts += ["", f"_Journal:_ {_md(narrative)}"]

    if summary.tomorrow_watchlist:
        wl_str = ", ".join(_md(s) for s in summary.tomorrow_watchlist)
        parts += ["", f"Tomorrow's watchlist: {wl_str}"]

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text
