"""Format TradeCandidate + optional ClaudeReview into a Telegram MarkdownV2 message.

Provides formatters for:
- Trade candidates with approval buttons
- Query commands: positions, account, health, status, fills history, pending approvals
- Execution notifications: fills, live confirmation, roll alerts
- System events: startup, EOD report
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from src.common.schemas import (
    AccountSnapshot,
    ClaudeReview,
    EODSummary,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RollAlert,
    RollReview,
    TradeCandidate,
)

_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")

_MAX_MESSAGE_LEN = 4000


def _md(text: str) -> str:
    """Escape all MarkdownV2 special characters."""
    return _ESCAPE_RE.sub(r"\\\1", str(text))


def _icon(ok: bool) -> str:
    return "🟢" if ok else "🔴"


def _pnl(v: float) -> str:
    """Format a P&L value with no decimals, e.g. +$1,234 or -$567."""
    return f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"


def _pnl2(v: float) -> str:
    """Format a P&L value with two decimal places."""
    return f"+${v:,.2f}" if v >= 0 else f"-${abs(v):,.2f}"


def format_candidate(
    candidate: TradeCandidate,
    review: ClaudeReview | None,
) -> str:
    """Build the Telegram MarkdownV2 message for one trade candidate."""
    strategy_label = candidate.strategy.value.replace("_", " ").title()
    right_label = "Call" if candidate.right == OptionRight.CALL else "Put"
    contract_value = candidate.premium * 100

    parts: list[str] = [
        f"*{_md(candidate.underlying)} — {_md(strategy_label)}*",
        (
            f"\\${_md(f'{candidate.strike:.0f}')} {_md(right_label)}"
            f" · {_md(str(candidate.expiry))} \\({_md(str(candidate.dte))}d\\)"
        ),
        "",
        f"💰 \\${_md(f'{candidate.premium:.2f}')}/sh · \\${_md(f'{contract_value:.0f}')}/contract",
        (
            f"ROC {_md(f'{candidate.roc_pct:.2f}')}%"
            f" · Ann\\. {_md(f'{candidate.annualized_yield_pct:.1f}')}%"
        ),
    ]

    delta_str = f"{candidate.delta:.2f}" if candidate.delta is not None else "N/A"
    iv_str = f"{candidate.iv_rank:.0f}" if candidate.iv_rank is not None else "N/A"
    vrp_str = (
        f" · VRP {candidate.vrp:+.1f}%"
        if candidate.vrp is not None
        else ""
    )
    parts.append(f"Δ {_md(delta_str)} · IV Rank {_md(iv_str)}{_md(vrp_str)}")

    score_line = f"Score *{_md(f'{candidate.blended_score:.1f}')}*/100"
    if candidate.rationale_tags:
        tags_str = " · ".join(_md(t) for t in candidate.rationale_tags)
        score_line += f"   _{tags_str}_"
    parts.append(score_line)

    if review is not None:
        conf_str = (
            f" · {_md(f'{review.confidence:.0%}')} confidence"
            if review.confidence is not None
            else ""
        )
        rec = review.recommendation.upper()
        parts += [
            "",
            f"*── Claude \\(Priority {_md(str(review.priority))}\\) ──*",
            f"*{_md(rec)}*{conf_str}",
            f"Why: {_md(review.why_attractive)}",
            f"Risk: {_md(review.risks)}",
            f"Tradeoff: {_md(review.tradeoffs)}",
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
        "*IBKR Options Bot — Commands*",
        "",
        "*Scans & trading*",
        "/scan — Run full pipeline scan \\(CC/CSP/buy opportunities\\)",
        "/pending — List pending approvals with expiry times",
        "/expire — Expire all pending approvals",
        "",
        "*Portfolio*",
        "/status — Account · short options · pending approvals",
        "/positions — Full portfolio positions with P&L",
        "/account — Account balances \\(buying power, net liq, margin\\)",
        "/fills — Recent fills \\(last 7 days\\)",
        "",
        "*Automation*",
        "/mode — Show current mode \\(MANUAL/AUTOMATED\\) and toggle",
        "",
        "*System*",
        "/health — Connections, DB, last scan, open orders",
        "/help — Show this message",
    ]
    return "\n".join(lines)


def format_mode_status(is_automated: bool) -> str:
    """Show the current trading mode and a brief description of what it means."""
    if is_automated:
        mode = "🤖 *AUTOMATED*"
        desc = (
            "_Trades execute autonomously during RTH\\._\n"
            "_Positions close automatically at 50% profit\\._\n"
            "_Scans run every 15 minutes \\— no approval required\\._"
        )
    else:
        mode = "👤 *MANUAL*"
        desc = (
            "_All trades require your Approve/Reject tap\\._\n"
            "_Profit targets trigger alerts only \\— no auto\\-close\\._"
        )
    return f"*Trading Mode:* {mode}\n\n{desc}"


def format_auto_trade_notification(candidates: list[TradeCandidate]) -> str:
    """Summary notification sent when trades are auto-queued in AUTOMATED mode."""
    n = len(candidates)
    lines = [f"🤖 *Auto\\-queued {_md(str(n))} trade{'s' if n != 1 else ''}*", ""]
    for c in candidates:
        right = "Call" if c.right == OptionRight.CALL else "Put"
        strat = c.strategy.value.replace("_", " ").title()
        vrp_part = f" VRP{c.vrp:+.1f}%" if c.vrp is not None else ""
        lines.append(
            f"• *{_md(c.underlying)}* {_md(strat)} \\${_md(f'{c.strike:.0f}')} {_md(right)}"
            f" {_md(str(c.expiry))} \\({_md(str(c.dte))}d\\)"
            f" — score {_md(f'{c.blended_score:.0f}')}/100{_md(vrp_part)}"
        )
    lines += ["", "_The risk gate re\\-validates each order before execution\\._"]
    return "\n".join(lines)[:_MAX_MESSAGE_LEN]


def format_profit_alert(
    symbol: str,
    underlying: str,
    entry_price: float,
    current_mid: float,
    profit_pct: float,
) -> str:
    """Profit-target alert sent in MANUAL mode when 50% threshold is reached."""
    captured = profit_pct * 100
    lines = [
        f"💰 *Profit target reached — {_md(symbol)}*",
        f"Underlying: {_md(underlying)}",
        f"Entry \\(sold at\\): \\${_md(f'{entry_price:.2f}')}",
        f"Current mid \\(cost to close\\): \\${_md(f'{current_mid:.2f}')}",
        f"Premium captured: *{_md(f'{captured:.0f}')}%*",
        "",
        "_Consider buying to close this position to lock in the gain\\._",
    ]
    return "\n".join(lines)


def format_auto_close_result(
    symbol: str,
    qty: int,
    limit_price: float,
    filled_qty: float,
    avg_price: float,
) -> str:
    """Notification for an automated buy-to-close order result."""
    if filled_qty > 0:
        return (
            f"🤖 *Auto\\-close filled* — {_md(symbol)}\n"
            f"Bought {_md(str(qty))} × {_md(symbol)} @ \\${_md(f'{avg_price:.2f}')}"
        )
    return (
        f"⚠️ *Auto\\-close NOT filled* — {_md(symbol)}\n"
        f"Limit \\${_md(f'{limit_price:.2f}')} placed but did not fill — check IBKR manually\\."
    )


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
                f"Net Liq \\${_md(f'{account.net_liquidation:,.0f}')} · "
                f"BP \\${_md(f'{account.buying_power:,.0f}')}"
            ),
        ]

    if not positions:
        parts += ["", "_No open positions_"]
        return "\n".join(parts)

    stocks = [p for p in positions if p.sec_type == "STK"]
    options = [p for p in positions if p.sec_type == "OPT"]

    if stocks:
        parts += ["", "*Stocks*"]
        for p in sorted(stocks, key=lambda x: x.symbol):
            price_s = f" @ \\${_md(f'{p.market_price:.2f}')}" if p.market_price else ""
            mv_s = f" · MV \\${_md(f'{p.market_value:,.0f}')}" if p.market_value else ""
            if p.unrealized_pnl is not None:
                pnl_s = f" · {_md(_pnl(p.unrealized_pnl))}"
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
            pnl_s = f" · {_md(_pnl(p.unrealized_pnl))}" if p.unrealized_pnl is not None else ""
            sym = _md(p.underlying or p.symbol.split()[0])
            parts.append(
                f"  {sym} {_md(side)} {_md(str(qty))}× {strike_s}{_md(right_lbl)}"
                f" {exp_s}{dte_s}{price_s}{pnl_s}"
            )

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text


def format_account(account: AccountSnapshot) -> str:
    """Format account balances for Telegram."""
    ts = _md(account.captured_at.strftime("%b %d %H:%M UTC"))
    parts = [
        "*Account Summary*",
        "",
        f"💼 Net Liq      \\${_md(f'{account.net_liquidation:,.0f}')}",
        f"💵 Cash          \\${_md(f'{account.total_cash:,.0f}')}",
        f"⚡ Buying Power  \\${_md(f'{account.buying_power:,.0f}')}",
        f"🔒 Maint\\. Margin \\${_md(f'{account.maintenance_margin:,.0f}')}",
        f"✅ Excess Liq\\.  \\${_md(f'{account.excess_liquidity:,.0f}')}",
        "",
        f"_{ts}_",
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
    since_str = "never"
    if last_scan_at is not None:
        aware = last_scan_at.replace(tzinfo=UTC) if last_scan_at.tzinfo is None else last_scan_at
        mins = int((datetime.now(UTC) - aware).total_seconds() / 60)
        since_str = f"{mins}m ago"

    parts = [
        "*System Health*",
        "",
        f"{_icon(ib_exec_ok)} IBKR Exec \\(clientId 14\\)",
        f"{_icon(ib_scan_ok)} IBKR Scan \\(clientId 15\\)",
        f"{_icon(db_ok)} Database",
        "",
        f"Last scan:  {_md(since_str)}",
        f"Pending:    {_md(str(pending_approvals))} approval{'s' if pending_approvals != 1 else ''}",
        f"Orders:     {_md(str(open_orders))} open",
    ]
    return "\n".join(parts)


def format_status(
    positions: list[PositionSnapshot],
    account: AccountSnapshot | None,
    pending_approvals: int,
    open_orders: int,
) -> str:
    """Compact status overview: account + short options + pending approvals."""
    parts: list[str] = ["*Status Overview*"]

    if account:
        total_unr = sum(p.unrealized_pnl or 0.0 for p in positions)
        parts += [
            "",
            (
                f"💼 \\${_md(f'{account.net_liquidation:,.0f}')} net liq · "
                f"\\${_md(f'{account.buying_power:,.0f}')} BP"
            ),
            f"Unr\\. P&L: {_md(_pnl(total_unr))}",
        ]

    stocks = [p for p in positions if p.sec_type == "STK"]
    options = [p for p in positions if p.sec_type == "OPT"]
    short_opts = [p for p in options if p.position < 0]

    parts += [
        "",
        (
            f"{_md(str(len(stocks)))} stock{'s' if len(stocks) != 1 else ''} · "
            f"{_md(str(len(options)))} option{'s' if len(options) != 1 else ''}"
            f" \\({_md(str(len(short_opts)))} short\\)"
        ),
    ]

    if short_opts:
        parts += ["", "*Short Options*"]
        for p in sorted(short_opts, key=lambda x: x.expiry or date.max):
            right_lbl = ("C" if p.right == OptionRight.CALL else "P") if p.right else ""
            strike_s = f"\\${_md(f'{p.strike:.0f}')}" if p.strike else ""
            dte = (p.expiry - date.today()).days if p.expiry else None
            dte_s = f" {_md(str(dte))}d" if dte is not None else ""
            qty = abs(int(p.position))
            sym = _md(p.underlying or p.symbol.split()[0])
            pnl_s = f" {_md(_pnl(p.unrealized_pnl))}" if p.unrealized_pnl is not None else ""
            parts.append(f"  {sym} {strike_s}{_md(right_lbl)}{dte_s} ×{_md(str(qty))}{pnl_s}")

    parts += [
        "",
        f"⏳ {_md(str(pending_approvals))} pending · {_md(str(open_orders))} open orders",
    ]

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text


def format_startup(
    ib_exec_ok: bool,
    ib_scan_ok: bool,
    db_ok: bool,
    mode: str,
    services: list[str],
) -> str:
    """Format system startup notification for Telegram."""
    mode_icon = "🔴" if mode == "LIVE" else "📄"
    service_lines = "\n".join(f"  • {_md(s)}" for s in services)
    parts = [
        f"*IBKR Bot Started — {_md(mode)} MODE* {mode_icon}",
        "",
        f"{_icon(ib_exec_ok)} IBKR Exec",
        f"{_icon(ib_scan_ok)} IBKR Scan",
        f"{_icon(db_ok)} Database",
        "",
        "*Services*",
        service_lines,
    ]
    return "\n".join(parts)


def format_eod_summary(summary: EODSummary, narrative: str | None) -> str:
    """Build the EOD report Telegram MarkdownV2 message."""
    date_str = _md(summary.date.strftime("%b %d, %Y"))
    parts: list[str] = [
        f"*EOD Report — {date_str}*",
        "",
        f"💰 Realized:    {_md(_pnl2(summary.realized_pnl))}",
        (
            f"📊 Unrealized:  {_md(_pnl2(summary.unrealized_pnl))}"
            f"  \\(Δ {_md(_pnl2(summary.unrealized_pnl_delta))}\\)"
        ),
        (
            f"📋 Positions:   {_md(str(summary.open_positions))}"
            f" · Net Δ {_md(f'{summary.net_delta_exposure:.2f}')}"
        ),
    ]

    if summary.fills_today > 0:
        parts += ["", f"Fills today: {_md(str(summary.fills_today))}"]

    if summary.top_movers:
        movers_str = " · ".join(_md(s) for s in summary.top_movers)
        parts.append(f"Movers: {movers_str}")

    if narrative:
        parts += ["", f"_{_md(narrative)}_"]

    if summary.tomorrow_watchlist:
        wl_str = " · ".join(_md(s) for s in summary.tomorrow_watchlist)
        parts += ["", f"Tomorrow: {wl_str}"]

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text


def format_fill_confirm(
    underlying: str,
    strategy: str,
    strike: float,
    right: str,
    expiry: date,
    filled_qty: float,
    avg_price: float,
) -> str:
    """Format an order fill confirmation for Telegram MarkdownV2."""
    strategy_label = strategy.replace("_", " ").title()
    right_label = "Call" if right == "C" else "Put"
    contract_total = avg_price * filled_qty * 100
    qty_str = f"{filled_qty:.0f}"

    parts = [
        f"✅ *Filled — {_md(underlying)} {_md(strategy_label)}*",
        (f"\\${_md(f'{strike:.0f}')} {_md(right_label)} · {_md(str(expiry))}"),
        (
            f"{_md(qty_str)} contract{'s' if filled_qty != 1 else ''}"
            f" @ \\${_md(f'{avg_price:.2f}')}/sh"
            f"  \\(\\${_md(f'{contract_total:.0f}')} total\\)"
        ),
    ]
    return "\n".join(parts)


def format_live_confirm_request(
    underlying: str,
    strike: float,
    right: str,
    expiry: date,
    contracts: int,
) -> str:
    """Format the live order confirmation request for Telegram MarkdownV2."""
    right_label = "Call" if right == "C" else "Put"
    parts = [
        "⚠️ *LIVE Order — Confirmation Required*",
        "",
        (f"{_md(underlying)} \\${_md(f'{strike:.0f}')} {_md(right_label)} · {_md(str(expiry))}"),
        f"{_md(str(contracts))} contract{'s' if contracts != 1 else ''}",
        "",
        "Tap *CONFIRM LIVE* or let it expire to cancel\\.",
    ]
    return "\n".join(parts)


def format_roll_alert(
    pos: PositionSnapshot,
    quote: OptionQuote,
    alerts: list[RollAlert],
    review: RollReview | None,
) -> str:
    """Format a roll alert for Telegram MarkdownV2."""
    right_label = pos.right.value if pos.right else "?"
    strategy = "CC" if right_label == "C" else "CSP"
    strike_str = f"{pos.strike:.0f}" if pos.strike else "?"
    sym = pos.underlying or pos.symbol
    triggers_str = " \\+ ".join(_md(a.trigger) for a in alerts)

    parts: list[str] = [
        f"⚠️ *Roll Alert — {_md(sym)} {_md(strategy)} \\${_md(strike_str)}*",
        f"Triggers: {triggers_str}",
        "",
    ]

    for alert in alerts:
        parts.append(f"• {_md(alert.detail)}")

    meta: list[str] = []
    if quote.delta is not None:
        meta.append(f"Δ {_md(f'{quote.delta:.2f}')}")
    if quote.dte:
        meta.append(f"DTE {_md(str(quote.dte))}")
    if quote.iv is not None:
        meta.append(f"IV {_md(f'{quote.iv:.1%}')}")
    if meta:
        parts += ["", " · ".join(meta)]

    if review:
        roll_info = review.roll_target or review.rationale
        parts += [
            "",
            "*── Claude ──*",
            f"*{_md(review.recommendation.upper())}*",
        ]
        if roll_info:
            parts.append(f"→ {_md(roll_info)}")
        if review.risks:
            parts.append(f"Risk: {_md(review.risks)}")
    else:
        parts += ["", "_Claude review unavailable — manual evaluation required_"]

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text


def format_pending_approvals(pending: list[dict]) -> str:
    """Format a list of pending approvals for Telegram MarkdownV2.

    Each dict should have: underlying, strategy, right, strike, expiry,
    blended_score, expires_at (datetime | None).
    """
    count = len(pending)
    if count == 0:
        return "*Pending Approvals*\n\n_No pending approvals\\._"

    parts = [f"*Pending Approvals \\({_md(str(count))}\\)*", ""]

    now = datetime.now(UTC)
    for i, item in enumerate(pending, 1):
        underlying = item.get("underlying", "?")
        strategy = item.get("strategy", "?")
        right = item.get("right", "?")
        strike = item.get("strike", 0.0)
        expiry = item.get("expiry")
        score = item.get("blended_score", 0.0)
        expires_at = item.get("expires_at")

        strategy_label = strategy.replace("_", " ").title() if strategy else "?"
        right_label = "Call" if right == "C" else "Put"
        expiry_str = f" · {expiry}" if expiry else ""

        expires_str = ""
        if expires_at is not None:
            aware = expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at
            mins_left = int((aware - now).total_seconds() / 60)
            if mins_left > 0:
                expires_str = f"expires in {mins_left}m"
            else:
                expires_str = "expired"

        parts.append(
            f"*{_md(str(i))}\\.* {_md(underlying)} {_md(strategy_label)}"
            f" \\${_md(f'{strike:.0f}')} {_md(right_label)}{_md(expiry_str)}"
        )
        meta_parts = [f"Score {_md(f'{score:.1f}')}"]
        if expires_str:
            meta_parts.append(_md(expires_str))
        parts.append(f"   _{' · '.join(meta_parts)}_")

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text


def format_fills_history(fills: list[dict]) -> str:
    """Format recent fills for Telegram MarkdownV2.

    Each dict should have: filled_at, underlying, strategy, right, strike,
    expiry, filled_qty, avg_price, action ('SELL'|'BUY'), is_live (bool).
    """
    if not fills:
        return "*Recent Fills*\n\n_No fills in the last 7 days\\._"

    parts = [f"*Recent Fills \\({_md(str(len(fills)))}\\)*", ""]

    for item in fills:
        filled_at: datetime = item.get("filled_at", datetime.now(UTC))
        underlying = item.get("underlying", "?")
        strategy = item.get("strategy", "?")
        right = item.get("right", "?")
        strike = item.get("strike", 0.0)
        filled_qty = item.get("filled_qty", 0.0)
        avg_price = item.get("avg_price", 0.0)
        action = item.get("action", "SELL")
        is_live = item.get("is_live", False)

        right_label = "C" if right == "C" else "P"
        date_str = filled_at.strftime("%b %d")
        total = avg_price * filled_qty * 100
        credit_str = _pnl(total) if action == "SELL" else f"-${total:,.0f}"
        live_tag = " 🔴" if is_live else ""

        strategy_short = (
            "CC" if "covered" in strategy else "CSP" if "put" in strategy else strategy[:4].upper()
        )

        parts.append(
            f"{_md(date_str)}  *{_md(underlying)}* {_md(strategy_short)}"
            f" \\${_md(f'{strike:.0f}')}{_md(right_label)}"
            f"  {_md(str(int(filled_qty)))}× @ \\${_md(f'{avg_price:.2f}')}"
            f"  _{_md(credit_str)}{_md(live_tag)}_"
        )

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text
