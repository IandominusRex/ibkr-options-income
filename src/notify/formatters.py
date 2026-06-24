"""Format TradeCandidate + optional ClaudeReview into a Telegram MarkdownV2 message.

Provides formatters for:
- Trade candidates with approval buttons
- Query commands: positions, account, health, status, fills history, pending approvals
- Execution notifications: fills, live confirmation, roll alerts
- System events: startup, EOD report
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, date, datetime

from src.common.schemas import (
    AccountSnapshot,
    BuyCandidate,
    ClaudeReview,
    EODSummary,
    FundamentalStats,
    IVStats,
    MarketConditions,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RollAlert,
    RollReview,
    SectorContext,
    TechnicalStats,
    TradeCandidate,
)

_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")

_MAX_MESSAGE_LEN = 4000


def _md(text: str) -> str:
    """Escape all MarkdownV2 special characters."""
    return _ESCAPE_RE.sub(r"\\\1", str(text))


def _icon(ok: bool) -> str:
    return "🟢" if ok else "🔴"


def _candidate_sources(c: TradeCandidate) -> str:
    """MarkdownV2-ready data-source string for one trade candidate."""
    parts = ["IBKR option chain"]
    if c.price_source == "yfinance":
        parts.append("yfinance spot \\(fallback\\)")
    if c.greeks_source != "ibkr":
        parts.append("yfinance Greeks \\(fallback\\)")
    return " · ".join(parts)


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
    vrp_str = f" · VRP {candidate.vrp:+.1f}%" if candidate.vrp is not None else ""
    iv_rv_str = f" · IV/RV {candidate.iv_rv_ratio:.2f}" if candidate.iv_rv_ratio is not None else ""
    parts.append(f"Δ {_md(delta_str)} · IV Rank {_md(iv_str)}{_md(vrp_str)}{_md(iv_rv_str)}")

    premium_read = _premium_read(candidate.iv_rank, candidate.vrp)
    if premium_read is not None:
        parts.append(premium_read)

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

    footer = f"\n_Sources: {_candidate_sources(candidate)}_"
    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text + footer


def _pct(frac: float | None, *, signed: bool = False) -> str | None:
    """Format a fraction as a percent string (0.032 → '3.2%'), or None if missing."""
    if frac is None:
        return None
    sign = "+" if (signed and frac >= 0) else ""
    return f"{sign}{frac * 100:.1f}%"


def _trend_note(c: BuyCandidate) -> str | None:
    """Where price sits vs its moving averages — the 'is this a healthy uptrend' read."""
    if c.price is None:
        return None
    refs: list[str] = []
    if c.sma_50 is not None:
        refs.append("above 50d" if c.price >= c.sma_50 else "below 50d")
    if c.sma_200 is not None:
        refs.append("above 200d" if c.price >= c.sma_200 else "below 200d")
    return ", ".join(refs) if refs else None


_SECTOR_ICON: dict[str, str] = {
    "index": "📈",
    "tech": "💻",
    "semis": "🔬",
    "financials": "🏦",
    "healthcare": "🏥",
    "consumer": "🛒",
    "energy": "⚡",
    "utilities": "🔌",
    "industrials": "🏭",
    "bonds": "📊",
    "commodities": "🏅",
    "biotech": "🧬",
    "crypto": "₿",
}

_SECTOR_LABEL: dict[str, str] = {
    "index": "Indexes & ETFs",
    "tech": "Tech",
    "semis": "Semiconductors",
    "financials": "Financials",
    "healthcare": "Healthcare",
    "consumer": "Consumer",
    "energy": "Energy",
    "utilities": "Utilities",
    "industrials": "Industrials",
    "bonds": "Bonds",
    "commodities": "Commodities",
    "biotech": "Biotech",
    "crypto": "Crypto",
}

# Preferred display order for sectors.
_SECTOR_ORDER = [
    "index",
    "tech",
    "semis",
    "financials",
    "healthcare",
    "consumer",
    "energy",
    "utilities",
    "industrials",
    "bonds",
    "commodities",
    "biotech",
    "crypto",
]


def _build_candidate_card(c: BuyCandidate) -> list[str]:
    """Return MarkdownV2 lines for a single BuyCandidate card (no trailing blank line)."""
    card: list[str] = []

    # Price + premium richness.
    if c.price is not None:
        price_line = f"💵 \\${_md(f'{c.price:,.2f}')}"
        if c.iv_rank is not None:
            price_line += f" · IV Rank *{_md(f'{c.iv_rank:.0f}')}*"
        card.append(f"• {price_line}")

    if c.current_iv is not None and c.hv_30 is not None:
        vrp_pts = f" \\(VRP {_md(f'{c.vrp:+.1f}')}pts\\)" if c.vrp is not None else ""
        card.append(f"• IV {_md(f'{c.current_iv:.1f}')}% vs HV {_md(f'{c.hv_30:.1f}')}%{vrp_pts}")
    elif c.current_iv is not None:
        card.append(f"• IV {_md(f'{c.current_iv:.1f}')}%")

    # Trend context.
    b: list[str] = []
    if c.technical_regime:
        b.append(_md(c.technical_regime))
    trend = _trend_note(c)
    if trend:
        b.append(_md(trend))
    if c.rsi_14 is not None:
        b.append(f"RSI {_md(f'{c.rsi_14:.0f}')}")
    if b:
        card.append("• Trend: " + " · ".join(b))

    # Income/timing context.
    cc: list[str] = []
    ccy = _pct(c.est_monthly_cc_yield)
    if ccy:
        cc.append(f"est\\. CC \\~{_md(ccy)}/mo")
    if c.next_earnings is not None:
        days = (c.next_earnings - date.today()).days
        warn = " ⚠️" if 0 <= days <= 14 else ""
        cc.append(f"earnings {_md(str(days))}d{warn}")
    dy = _pct(c.dividend_yield)
    if dy and c.dividend_yield:
        cc.append(f"div {_md(dy)}")
    if cc:
        card.append("• " + " · ".join(cc))

    # Quality + rationale.
    quality = "✓" if c.quality_flag else ("✗" if c.quality_flag is False else "?")
    card.append(f"• Quality: {quality}")
    if c.rationale:
        card.append(f"_{_md(c.rationale)}_")

    return card


def format_buy_list(candidates: list[BuyCandidate]) -> str:
    """Build the Telegram MarkdownV2 message for the buy-to-own screen.

    Candidates are grouped by sector (up to 10 total), shown in a fixed display order;
    sectors not in the order map appear last, alphabetically.
    """
    if not candidates:
        return ""

    # Group by sector, preserving score-desc order within each sector.
    by_sector: dict[str, list[BuyCandidate]] = defaultdict(list)
    for c in candidates:
        by_sector[c.sector or "other"].append(c)

    # Sort sectors: known order first, then unknown alphabetically.
    known = [s for s in _SECTOR_ORDER if s in by_sector]
    unknown = sorted(s for s in by_sector if s not in _SECTOR_ORDER)
    sector_order = known + unknown

    # Header.
    sector_summary = " · ".join(
        f"{_SECTOR_ICON.get(s, '📌')} {_md(_SECTOR_LABEL.get(s, s))} \\({len(by_sector[s])}\\)"
        for s in sector_order
    )
    lines: list[str] = [
        "🟢 *Buy\\-to\\-Own Candidates*",
        "_Stocks worth owning to sell covered calls against_",
        sector_summary,
        "",
    ]

    rank = 0
    for sector in sector_order:
        sector_candidates = by_sector[sector]
        icon = _SECTOR_ICON.get(sector, "📌")
        label = _SECTOR_LABEL.get(sector, sector)
        count = len(sector_candidates)
        noun = "name" if count == 1 else "names"

        lines.append(f"{icon} *{_md(label)}* \\({count} {noun}\\)")

        for c in sector_candidates:
            rank += 1
            lines.append(f"*{rank}\\. __{_md(c.symbol)}__* — Score *{_md(f'{c.score:.0f}')}/100*")
            lines.extend(_build_candidate_card(c))
            lines.append("")

    text = "\n".join(lines).rstrip()
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return (
        text
        + "\n_Sources: yfinance \\(prices · IV · technicals · fundamentals\\) · IBKR \\(IV rank history\\)_"
    )


def _strat_abbr(strategy_value: str) -> str:
    return {"covered_call": "CC", "cash_secured_put": "CSP"}.get(strategy_value, strategy_value)


def format_unchanged_cards_digest(items: list[tuple[TradeCandidate, str]]) -> str:
    """Compact MarkdownV2 digest replacing full cards for candidates unchanged since a prior,
    still-pending cycle (S6). *items* is a list of (candidate, since-HH:MM) — the existing
    pending approval (with its buttons) is still actionable, so we only nudge, not re-spam.
    """
    if not items:
        return ""
    lines = [f"⏳ *{len(items)} unchanged* — still pending your approval:"]
    for c, since in items:
        label = (
            f"{c.underlying} {_strat_abbr(c.strategy.value)} "
            f"${c.strike:g} {c.expiry.strftime('%b%d')}"
        )
        lines.append(f"• {_md(label)} — _since {_md(since)}_")
    return "\n".join(lines)


def format_screen_unchanged(
    icon: str, label: str, count: int, since: str, noun: str = "name"
) -> str:
    """One-line MarkdownV2 digest for a screen (buy list / CC / CSP candidates) unchanged since
    a prior cycle — replaces the per-screen full send when nothing material has changed."""
    plural = "" if count == 1 else "s"
    return (
        f"{icon} *{_md(label)}* — {count} {noun}{plural} unchanged since {_md(since)} "
        f"\\(no new screens\\)"
    )


def format_screen_empty(icon: str, label: str, reason: str) -> str:
    """One-line + reason MarkdownV2 diagnostic for a screen with zero candidates this cycle —
    the "always send something" troubleshooting signal (Telegram routing plan)."""
    return f"{icon} *{_md(label)}* — no candidates this cycle\n_{_md(reason)}_"


def _position_pnl_pct(p: PositionSnapshot) -> str:
    """Per-position unrealized P&L % (market value vs. cost basis): ``unrealized_pnl /
    abs(avg_cost * position * multiplier)``, multiplier=100 for options, 1 for stock. Returns
    'N/A' if the cost basis is zero (e.g. avg_cost or position is 0)."""
    multiplier = 100 if p.sec_type == "OPT" else 1
    denom = abs(p.avg_cost * p.position * multiplier)
    if denom == 0:
        return "N/A"
    pct = (p.unrealized_pnl or 0.0) / denom * 100
    return f"{_md(f'{pct:+.1f}')}%"


def _format_option_snapshot_line(o: PositionSnapshot, *, show_symbol: bool) -> str:
    """One line for a short option position in the account snapshot — strike, right, expiry,
    DTE, and P&L $/%. Nested under a stock (show_symbol=False) it's prefixed with `└ `;
    standalone (a CSP, show_symbol=True) it leads with the underlying symbol."""
    right_lbl = "C" if o.right == OptionRight.CALL else "P"
    strike_s = f"\\${_md(f'{o.strike:.0f}')}" if o.strike else ""
    exp_s = _md(str(o.expiry)) if o.expiry else ""
    dte = (o.expiry - date.today()).days if o.expiry else None
    dte_s = f" \\({_md(str(dte))}d\\)" if dte is not None else ""
    pnl_s = f" · {_md(_pnl(o.unrealized_pnl or 0.0))} \\({_position_pnl_pct(o)}\\)"
    body = f"{strike_s}{_md(right_lbl)} {exp_s}{dte_s}{pnl_s}"
    if show_symbol:
        sym = _md(o.underlying or o.symbol.split()[0])
        return f"  {sym} {body}"
    return f"  └ {body}"


def format_account_snapshot(
    account: AccountSnapshot, positions: list[PositionSnapshot], updated_at: str
) -> str:
    """Account snapshot for the dedicated Telegram thread: net liq + total unrealized P&L,
    stock holdings (each with any covered calls sold against it nested below), and standalone
    cash-secured puts — each position annotated with its unrealized P&L % (see
    `_position_pnl_pct`). Sent once at 09:00 ET pre-open, then edited in place every cycle with
    an updated `(last updated HH:MM)` footer.
    """
    parts: list[str] = ["📊 *Account Snapshot*", ""]

    total_pnl = sum(p.unrealized_pnl or 0.0 for p in positions)
    total_cost = sum(
        abs(p.avg_cost * p.position * (100 if p.sec_type == "OPT" else 1)) for p in positions
    )
    line = f"💼 Net Liq \\${_md(f'{account.net_liquidation:,.0f}')} · {_md(_pnl(total_pnl))}"
    if total_cost > 0:
        total_pct = total_pnl / total_cost * 100
        line += f" \\({_md(f'{total_pct:+.1f}')}%\\)"
    else:
        line += " \\(N/A\\)"
    parts.append(line)

    stocks = [p for p in positions if p.sec_type == "STK" and p.position > 0]
    shorts = [p for p in positions if p.sec_type == "OPT" and p.position < 0]
    calls = [o for o in shorts if o.right == OptionRight.CALL]
    puts = [o for o in shorts if o.right == OptionRight.PUT]

    if stocks:
        parts += ["", f"*{_md('Stocks')}*"]
        for s in sorted(stocks, key=lambda x: x.symbol):
            mv_s = f" · MV \\${_md(f'{s.market_value:,.0f}')}" if s.market_value else ""
            pnl_s = f" · {_md(_pnl(s.unrealized_pnl or 0.0))} \\({_position_pnl_pct(s)}\\)"
            parts.append(f"{_md(s.symbol)}: {_md(f'{s.position:.0f}')} shares{mv_s}{pnl_s}")
            for c in sorted(calls, key=lambda x: x.expiry or date.max):
                if c.underlying == s.symbol:
                    parts.append(_format_option_snapshot_line(c, show_symbol=False))

    if puts:
        parts += ["", f"*{_md('Cash-Secured Puts')}*"]
        for p in sorted(puts, key=lambda x: (x.expiry or date.max, x.underlying or x.symbol)):
            parts.append(_format_option_snapshot_line(p, show_symbol=True))

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text + f"\n_Source: IBKR · last updated {_md(updated_at)}_"


def format_market_holiday(name: str, next_open_date: date) -> str:
    """MarkdownV2 notification sent at 9:30 ET on NYSE full-day holidays."""
    next_str = next_open_date.strftime("%a %d %b")
    return (
        f"🔴 *Market Holiday — {_md(name)}*\n"
        f"_US markets closed today\\. No scans will run\\._\n"
        f"_Next session: {_md(next_str)}_"
    )


def format_quiet_cycle(
    *,
    skipped: int,
    total: int,
    move_pct: float,
    vix: float | None,
    at: str,
) -> str:
    """Heartbeat for an intraday cycle that surfaced nothing new (S1/S5/S6).

    The 15-min loop otherwise sends *nothing* when no candidate clears the gate and the buy
    list is unchanged — indistinguishable from a dead daemon. This compact message confirms the
    scan ran and explains the silence: most names moved less than the materiality threshold, so
    their option chains were not re-fetched and Claude was not invoked this cycle.
    """
    pct = f"{move_pct * 100:g}"
    head = "🟰 *Quiet cycle* · " + _md(at)
    body = _md(f"{skipped}/{total} names moved <{pct}% — chain re-fetch & Claude skipped.")
    lines = [head, body]
    if vix is not None:
        lines.append(_md(f"VIX {vix:.1f}"))
        src_footer = "_Sources: IBKR \\(price moves\\) · yfinance \\(VIX\\)_"
    else:
        src_footer = "_Sources: IBKR \\(price moves\\)_"
    return "\n".join(lines) + "\n" + src_footer


def format_data_provenance(
    *,
    total_symbols: int,
    chain_ibkr: int,
    chain_failed: int,
    chain_skipped: int,
    spot_ibkr: int,
    spot_yfinance: int,
    spot_unavailable: int,
    greeks_ibkr: int,
    greeks_yfinance: int,
    vix: float | None,
) -> str:
    """End-of-scan summary of where each piece of data actually came from this cycle.

    Sent after the candidate/buy-list messages on a full sweep (manual /scan)
    so an operator can see at a glance which sources were live vs. fell back this run.
    """
    lines = ["📊 *Data sources this scan*", ""]

    chain_bits = [f"{chain_ibkr}/{total_symbols} from IBKR"]
    if chain_failed:
        chain_bits.append(f"{chain_failed} failed/timed out")
    if chain_skipped:
        chain_bits.append(f"{chain_skipped} skipped (immaterial)")
    lines.append(_md(f"Option chains: {', '.join(chain_bits)}"))

    spot_bits = []
    if spot_ibkr:
        spot_bits.append(f"{spot_ibkr} from IBKR chain")
    if spot_yfinance:
        spot_bits.append(f"{spot_yfinance} from yfinance")
    if spot_unavailable:
        spot_bits.append(f"{spot_unavailable} unavailable")
    lines.append(_md(f"Spot prices: {', '.join(spot_bits) if spot_bits else 'none'}"))

    if vix is not None:
        lines.append(_md(f"VIX: {vix:.1f} (yfinance)"))
    else:
        lines.append(_md("VIX: unavailable (yfinance)"))

    if greeks_ibkr or greeks_yfinance:
        greeks_total = greeks_ibkr + greeks_yfinance
        lines.append(
            _md(
                f"Option Greeks: {greeks_ibkr}/{greeks_total} from IBKR, "
                f"{greeks_yfinance} via yfinance Black-Scholes fallback"
            )
        )

    return "\n".join(lines)


# Human-readable labels for the raw risk-gate / filter reason codes surfaced when a
# single-ticker /scan turns up no qualifying option. Codes not listed fall back to a
# de-snake-cased version of the code itself.
_REJECT_REASON_LABELS: dict[str, str] = {
    "iv_rank_below_minimum": "IV rank too low (poor premium)",
    "iv_rv_below_minimum": "IV/RV ratio too low (premium not rich vs realized)",
    "delta_out_of_range": "delta outside target band",
    "delta_missing": "no delta available (illiquid / no Greeks)",
    "delta_sign_mismatch": "delta sign wrong for strategy",
    "dte_out_of_range": "no expiries in the target DTE window",
    "roc_below_minimum": "return-on-capital below floor",
    "yield_below_minimum": "annualized yield below floor",
    "earnings_blackout": "earnings inside the window",
    "no_contracts": "no contracts at the target strike",
    "negative_bid_sentinel": "no real bid (stale / illiquid quote)",
    "buying_power_buffer": "not enough buying-power headroom",
    "concentration_limit": "per-ticker concentration cap hit",
    "sector_limit": "per-sector concentration cap hit",
    "csp_allocation_limit": "total CSP allocation cap hit",
    "margin_limit": "margin limit hit",
    "contracts_exceeds_max": "size exceeds max contracts",
    "score_below_minimum": "blended score below quality floor",
}


def _humanize_reject_reason(code: str) -> str:
    """Map a raw gate/filter reason code to a readable phrase (best-effort)."""
    return _REJECT_REASON_LABELS.get(code, code.replace("_", " "))


def _vix_regime(vix: float) -> str:
    """Short plain-English read of the VIX level for the ticker card."""
    if vix < 15:
        return "calm — premiums thin"
    if vix < 20:
        return "normal"
    if vix < 30:
        return "elevated — richer premium, wider moves"
    return "stressed — rich premium, high tail risk"


def _market_sector_lines(
    mc: MarketConditions | None, sc: SectorContext | None
) -> list[str]:
    """Deterministic '🌐 Market & Sector' block: VIX regime + sector/market returns + rel-strength.

    Returns [] when neither a VIX level nor any sector datum is available, so the section is
    simply omitted rather than rendered empty."""
    body: list[str] = []
    if mc is not None and mc.vix is not None:
        body.append(f"• VIX {_md(f'{mc.vix:.1f}')} — {_md(_vix_regime(mc.vix))}")
    if sc is not None:
        if sc.sector:
            label = sc.sector + (f" / {sc.industry}" if sc.industry else "")
            etf = f" \\({_md(sc.sector_etf)}\\)" if sc.sector_etf else ""
            sect_ret = (
                f" {_md(f'{sc.sector_ret_1mo_pct:+.1f}')}% 1mo"
                if sc.sector_ret_1mo_pct is not None
                else ""
            )
            body.append(f"• {_md(label)}{etf}{sect_ret}")
        if sc.spy_ret_1mo_pct is not None:
            body.append(f"• SPY {_md(f'{sc.spy_ret_1mo_pct:+.1f}')}% 1mo \\(broad market\\)")
        if sc.symbol_ret_1mo_pct is not None:
            rel = ""
            if sc.rel_strength_1mo_pct is not None:
                word = "outperforming" if sc.rel_strength_1mo_pct >= 0 else "underperforming"
                rel = f" · {_md(f'{sc.rel_strength_1mo_pct:+.1f}')}% vs sector \\({word}\\)"
            body.append(
                f"• {_md(sc.symbol)} {_md(f'{sc.symbol_ret_1mo_pct:+.1f}')}% 1mo{rel}"
            )
    if not body:
        return []
    return ["🌐 *Market & Sector*", *body]


def _ticker_review_lines(review: ClaudeReview) -> list[str]:
    """Indented MarkdownV2 lines rendering Claude/Ollama's verdict for a ticker-scan card."""
    conf = (
        f" · {_md(f'{review.confidence:.0%}')} confidence" if review.confidence is not None else ""
    )
    lines = [f"  🤖 *{_md(review.recommendation.upper())}*{conf}"]
    if review.why_attractive:
        lines.append(f"  _{_md(review.why_attractive)}_")
    if review.risks:
        lines.append(f"  ⚠️ {_md(review.risks)}")
    # Assignment is the decision that matters most on a single-name CC/CSP card, so surface the
    # model's read on it here (the full-scan candidate card omits it for brevity).
    if review.assignment_considerations:
        lines.append(f"  📌 {_md(review.assignment_considerations)}")
    return lines


def _reject_reason_line(reasons: list[str] | None) -> str | None:
    """A '_Rejected: …_' line summarizing the top distinct gate reasons, or None."""
    if not reasons:
        return None
    seen: list[str] = []
    for r in reasons:
        label = _humanize_reject_reason(r)
        if label not in seen:
            seen.append(label)
    return "  _Rejected: " + _md(" · ".join(seen[:3])) + "_"


def _near_miss_lines(cand: TradeCandidate, reasons: list[str] | None) -> list[str]:
    """Render the best non-qualifying contract (a 'near miss') so an empty strategy still
    shows the closest strike and exactly what it failed on, rather than going silent."""
    right_lbl = "C" if cand.right == OptionRight.CALL else "P"
    exp_str = cand.expiry.strftime("%b%d")
    lines = [
        "_Closest contract \\(did not qualify\\):_",
        (
            f"  \\${_md(f'{cand.strike:.0f}')}{_md(right_lbl)} · {_md(exp_str)}"
            f" \\({_md(str(cand.dte))}d\\)"
        ),
        (
            f"  \\${_md(f'{cand.premium:.2f}')}/sh"
            f" · ROC {_md(f'{cand.roc_pct:.1f}')}%"
            f" · Score {_md(f'{cand.blended_score:.0f}')}/100 ✗"
        ),
    ]
    reject_line = _reject_reason_line(reasons)
    if reject_line is not None:
        lines.append(reject_line)
    return lines


def _premium_read(iv_rank: float | None, vrp: float | None) -> str | None:
    """One-line plain-English read of the premium-*selling* environment from IV rank + VRP.

    Turns the raw header numbers into a decision: low IV rank / negative VRP means options are
    cheap relative to realized vol (a poor environment for selling premium). Returns a
    MarkdownV2-ready ``💡 _…_`` line, or None when neither input is available. Shared by the
    single-ticker card and the CC/CSP candidate cards (so the 15-min loop shows it too)."""
    bits: list[str] = []
    if iv_rank is not None:
        if iv_rank < 30:
            bits.append("IV rank low — poor premium")
        elif iv_rank < 60:
            bits.append("IV rank moderate")
        else:
            bits.append("IV rank elevated — rich premium")
    if vrp is not None:
        if vrp < 0:
            bits.append("VRP negative — options cheap vs realized")
        else:
            bits.append("VRP positive — premium above realized")
    if not bits:
        return None
    return "💡 _" + _md(" · ".join(bits)) + "_"


def format_near_miss_line(cand: TradeCandidate, reasons: list[str] | None = None) -> str:
    """Plain-text (NOT MarkdownV2) one-liner naming the best contract that *failed* the gate.

    Used by the full-scan empty-screen diagnostic (appended via ``_append_status``, which sends
    plain text), so even a cycle where nothing qualified shows the closest trade and why it was
    rejected — the multi-symbol analogue of the single-ticker near-miss block."""
    right = "C" if cand.right == OptionRight.CALL else "P"
    exp = cand.expiry.strftime("%b%d")
    line = (
        f"↳ closest: {cand.underlying} ${cand.strike:.0f}{right} {exp} ({cand.dte}d)"
        f" ${cand.premium:.2f}/sh · ROC {cand.roc_pct:.1f}% · score {cand.blended_score:.0f}"
    )
    if reasons:
        seen: list[str] = []
        for r in reasons:
            label = _humanize_reject_reason(r)
            if label not in seen:
                seen.append(label)
        line += " — " + " · ".join(seen[:2])
    return line


def _ticker_sources(
    *, quotes_available: bool, tech_stats: TechnicalStats, greeks_fallback: bool, has_review: bool
) -> str:
    """Honest data-source footer for a single-ticker scan: reflects which spot/Greeks source
    actually produced this card's numbers rather than a hardcoded list."""
    parts: list[str] = []
    if quotes_available:
        parts.append("IBKR option chain")
    if tech_stats.price_source == "ibkr":
        parts.append("IBKR spot (parity)")
    else:
        parts.append("yfinance spot")
    if greeks_fallback:
        parts.append("yfinance Greeks (fallback)")
    parts.append("yfinance (IV · technicals · fundamentals)")
    if has_review:
        parts.append("Claude/Ollama review")
    return " · ".join(parts)


def format_ticker_scan_result(
    *,
    ticker: str,
    iv_stats: IVStats,
    tech_stats: TechnicalStats,
    fund_stats: FundamentalStats,
    cc_candidates: list[TradeCandidate],
    csp_candidates: list[TradeCandidate],
    buy_candidate: BuyCandidate | None,
    is_held: bool,
    quotes_available: bool = True,
    reviews: list[ClaudeReview] | None = None,
    cc_reject_reasons: list[str] | None = None,
    csp_reject_reasons: list[str] | None = None,
    cc_near_miss: TradeCandidate | None = None,
    csp_near_miss: TradeCandidate | None = None,
    greeks_fallback: bool = False,
    market_conditions: MarketConditions | None = None,
    sector_context: SectorContext | None = None,
) -> str:
    """Compact Telegram MarkdownV2 summary for a single-ticker /scan TICKER result.

    Sections:
      - Header: price, IV rank, VRP + a plain-English premium-environment read
      - Technicals: trend (vs SMAs), RSI, earnings days
      - Market & Sector: VIX regime + sector/market returns + relative strength (deterministic)
      - Read: the LLM's plain-English synthesis of what the metrics mean + sentiment (if present)
      - Covered Call: best candidate + Claude/Ollama verdict (or near-miss + reason for none)
      - Cash-Secured Put: best candidate + Claude/Ollama verdict (or near-miss + reason for none)
      - Buy-to-Own: score + rationale (omitted if not applicable)
      - Sources footer (honest: reflects the actual spot/Greeks source)

    Args (added for the holistic deep-dive):
        market_conditions: macro snapshot (VIX) — rendered as a plain-English vol-regime line.
        sector_context: how the name's sector and the broad market are trading; rendered as a
            deterministic backdrop line. Both fail-soft — omitted when unavailable.

    Args:
        reviews: optional Claude/Ollama reviews keyed (internally) by candidate_id; the verdict
            for the best CC/CSP is rendered beneath that candidate.
        cc_reject_reasons / csp_reject_reasons: raw gate/filter reason codes for the strategy when
            no candidate qualified — surfaced so the operator sees *why* it was empty.
        cc_near_miss / csp_near_miss: the best-scoring contract that *failed* the gate for the
            strategy; rendered as a "closest contract" block when nothing qualified.
        greeks_fallback: True when any option Greeks fell back to yfinance Black-Scholes (footer).
    """
    review_map = {r.candidate_id: r for r in (reviews or [])}
    lines: list[str] = [f"🔍 *{_md(ticker)} — Ticker Scan*", ""]

    # --- Price / IV header ---
    price = tech_stats.price
    price_str = f"\\${_md(f'{price:,.2f}')}" if price else "N/A"
    iv_rank_str = _md(f"{iv_stats.iv_rank:.0f}") if iv_stats.iv_rank is not None else "N/A"
    vrp_str = f" · VRP {_md(f'{iv_stats.vrp:+.1f}')}%" if iv_stats.vrp is not None else ""
    lines.append(f"💵 {price_str} · IV Rank {iv_rank_str}{vrp_str}")
    premium_read = _premium_read(iv_stats.iv_rank, iv_stats.vrp)
    if premium_read is not None:
        lines.append(premium_read)
    lines.append("")

    # --- Technicals ---
    lines.append("📈 *Technicals*")
    tech_bits: list[str] = []
    if tech_stats.sma_50 is not None and price:
        tech_bits.append("above 50d" if price >= tech_stats.sma_50 else "below 50d")
    if tech_stats.sma_200 is not None and price:
        tech_bits.append("above 200d" if price >= tech_stats.sma_200 else "below 200d")
    if tech_stats.rsi_14 is not None:
        tech_bits.append(f"RSI {_md(f'{tech_stats.rsi_14:.0f}')}")
    if tech_bits:
        lines.append("• " + " · ".join(tech_bits))
    if fund_stats.next_earnings is not None:
        days_to_earn = (fund_stats.next_earnings - date.today()).days
        earn_warn = " ⚠️" if 0 <= days_to_earn <= 14 else ""
        lines.append(f"• Earnings: {_md(str(days_to_earn))}d{earn_warn}")
    lines.append("")

    # --- Market & Sector backdrop (deterministic) ---
    backdrop = _market_sector_lines(market_conditions, sector_context)
    if backdrop:
        lines.extend(backdrop)
        lines.append("")

    # --- LLM Read: plain-English synthesis of what it all means (single-ticker only) ---
    summary = next((r.summary for r in (reviews or []) if r.summary), "")
    if summary:
        lines.append("🧠 *Read*")
        lines.append(f"_{_md(summary)}_")
        lines.append("")

    # --- Covered Call ---
    lines.append("🔵 *Covered Call*")
    if not quotes_available:
        lines.append("_No option chain data — market may be closed_")
    elif not is_held:
        lines.append("_Not held — buy shares first to sell covered calls_")
    elif cc_candidates:
        best_cc = cc_candidates[0]
        right_lbl = "C" if best_cc.right == OptionRight.CALL else "P"
        exp_str = best_cc.expiry.strftime("%b%d")
        contracts_lbl = f" \\({_md(str(int(best_cc.contracts)))} contracts\\)"
        lines.append(
            f"  \\${_md(f'{best_cc.strike:.0f}')}{_md(right_lbl)} · {_md(exp_str)}"
            f" \\({_md(str(best_cc.dte))}d\\){contracts_lbl}"
        )
        lines.append(
            f"  \\${_md(f'{best_cc.premium:.2f}')}/sh"
            f" · ROC {_md(f'{best_cc.roc_pct:.1f}')}%"
            f" · Score {_md(f'{best_cc.blended_score:.0f}')}/100 ✅"
        )
        cc_review = review_map.get(best_cc.candidate_id)
        if cc_review is not None:
            lines.extend(_ticker_review_lines(cc_review))
    else:
        lines.append("_No qualifying CC options_")
        if cc_near_miss is not None:
            lines.extend(_near_miss_lines(cc_near_miss, cc_reject_reasons))
        else:
            reject_line = _reject_reason_line(cc_reject_reasons)
            if reject_line is not None:
                lines.append(reject_line)
    lines.append("")

    # --- Cash-Secured Put ---
    lines.append("🟣 *Cash\\-Secured Put*")
    if not quotes_available:
        lines.append("_No option chain data — market may be closed_")
    elif csp_candidates:
        best_csp = csp_candidates[0]
        right_lbl = "C" if best_csp.right == OptionRight.CALL else "P"
        exp_str = best_csp.expiry.strftime("%b%d")
        contracts_lbl = f" \\({_md(str(int(best_csp.contracts)))} contracts\\)"
        lines.append(
            f"  \\${_md(f'{best_csp.strike:.0f}')}{_md(right_lbl)} · {_md(exp_str)}"
            f" \\({_md(str(best_csp.dte))}d\\){contracts_lbl}"
        )
        lines.append(
            f"  \\${_md(f'{best_csp.premium:.2f}')}/sh"
            f" · ROC {_md(f'{best_csp.roc_pct:.1f}')}%"
            f" · Score {_md(f'{best_csp.blended_score:.0f}')}/100 ✅"
        )
        csp_review = review_map.get(best_csp.candidate_id)
        if csp_review is not None:
            lines.extend(_ticker_review_lines(csp_review))
    else:
        lines.append("_No qualifying CSP options_")
        if csp_near_miss is not None:
            lines.extend(_near_miss_lines(csp_near_miss, csp_reject_reasons))
        else:
            reject_line = _reject_reason_line(csp_reject_reasons)
            if reject_line is not None:
                lines.append(reject_line)
    lines.append("")

    # --- Buy-to-Own ---
    if buy_candidate is not None:
        lines.append("🟢 *Buy\\-to\\-Own*")
        score_str = _md(f"{buy_candidate.score:.0f}")
        lines.append(f"  Score {score_str}/100")
        if buy_candidate.rationale:
            lines.append(f"  _{_md(buy_candidate.rationale)}_")
        lines.append("")

    # --- Sources footer (honest about what actually produced these numbers) ---
    lines.append(
        "_Sources: "
        + _md(
            _ticker_sources(
                quotes_available=quotes_available,
                tech_stats=tech_stats,
                greeks_fallback=greeks_fallback,
                has_review=bool(review_map),
            )
        )
        + "_"
    )

    text = "\n".join(lines)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text


def format_order_notification(
    status: str,
    *,
    underlying: str,
    strategy: str,
    strike: float,
    right: str,
    expiry: date,
    contracts: int,
    order_id: int,
    action: str = "SELL",
    limit_price: float | None = None,
    underlying_price: float | None = None,
    option_mid: float | None = None,
    filled_qty: float | None = None,
    avg_price: float | None = None,
    failure_reason: str | None = None,
    updated_at: str | None = None,
) -> str:
    """Plain-text order status notification for thread 58.

    *status* is one of ``"placed"``, ``"update"``, ``"filled"``, or ``"failed"``.
    *action* is ``"SELL"`` (open) or ``"BUY"`` (close / buy-to-close).
    Returns plain text (no MarkdownV2) so it composes cleanly with timestamped edits.
    """
    strategy_label = strategy.replace("_", " ").title()
    right_label = "Call" if right == "C" else "Put"
    noun = "contract" if contracts == 1 else "contracts"
    is_close = action == "BUY"

    header = {
        "placed": "📬 Order Placed" if not is_close else "📬 Close Order Placed",
        "update": "🔄 Order Pending",
        "filled": "📈 Closed" if is_close else "✅ Opened",
        "failed": "❌ Order Failed",
    }.get(status, f"📋 Order ({status})")

    lines = [
        f"{header} — {underlying} {strategy_label}",
        f"${strike:.0f} {right_label} · {expiry} · {contracts} {noun}",
    ]

    if limit_price is not None:
        total = limit_price * contracts * 100
        lines.append(f"Limit: ${limit_price:.2f}/sh (${total:.0f} total)")

    if status in ("placed", "update"):
        price_parts: list[str] = []
        if underlying_price is not None:
            price_parts.append(f"Underlying: ${underlying_price:.2f}")
        if option_mid is not None:
            price_parts.append(f"Option mid: ${option_mid:.2f}")
        if price_parts:
            lines.append(" | ".join(price_parts))

    if status == "filled" and filled_qty is not None and avg_price is not None:
        total = avg_price * filled_qty * 100
        lines.append(f"Filled {filled_qty:.0f}x @ ${avg_price:.2f}/sh (${total:.0f} total)")

    if status == "failed" and failure_reason:
        lines.append(f"Reason: {failure_reason}")

    if updated_at:
        lines.append(f"[{updated_at}]")

    return "\n".join(lines)


def format_skip_reasons(per_symbol_skip: dict[str, list[str]], *, max_symbols: int = 15) -> str:
    """Compact MarkdownV2 card showing why each scanned symbol produced no approved candidate.

    Shows the top rejection reason(s) per symbol so the operator can see at a glance what
    gates dominated (e.g. iv_rank_below_minimum vs. earnings_blackout vs. dte_out_of_range).
    Limited to *max_symbols* lines to keep the message compact.
    """
    if not per_symbol_skip:
        return ""

    items = sorted(per_symbol_skip.items())
    shown = items[:max_symbols]
    truncated = len(items) - len(shown)

    parts = ["⏸️ *Skipped symbols*", ""]
    for sym, reasons in shown:
        # Show at most 2 reasons per symbol; combine with " · "
        reasons_str = " · ".join(_md(r) for r in reasons[:2])
        if len(reasons) > 2:
            reasons_str += f" \\(\\+{len(reasons) - 2} more\\)"
        parts.append(f"*{_md(sym)}* — {reasons_str}")

    if truncated:
        parts.append(f"_…and {_md(str(truncated))} more symbols_")

    return "\n".join(parts)


def format_pnl_calendar(rows: list[dict], *, days: int = 30) -> str:
    """MarkdownV2 per-day P&L calendar from a list of fill dicts.

    Each dict must have: ``date`` (date), ``cashflow`` (float, signed net premium),
    ``fills`` (int count). Shows the most recent *days* calendar days with any fills.
    """
    if not rows:
        return f"*P&L Calendar \\(last {_md(str(days))} days\\)*\n\n_No fills recorded\\._"

    parts = [f"*P&L Calendar \\(last {_md(str(days))} days\\)*", ""]
    total = 0.0
    for row in rows:
        d = row["date"]
        cf = row["cashflow"]
        n = row["fills"]
        total += cf
        date_str = _md(d.strftime("%b %d"))
        cf_str = _md(_pnl2(cf))
        noun = "fill" if n == 1 else "fills"
        parts.append(f"{date_str}  {cf_str}  _{_md(str(n))} {_md(noun)}_")

    parts += ["", f"*Total: {_md(_pnl2(total))}*"]
    return "\n".join(parts)


def format_profile_status(name: str) -> str:
    """MarkdownV2 message showing the active trading profile and what it means."""
    _DESCRIPTIONS = {
        "default": "Base config — risk\\_limits\\.yaml and scoring\\_weights\\.yaml as written\\.",
        "conservative": "Tighter delta/DTE windows, higher IV/score floors \\(fewer, safer trades\\)\\.",
        "balanced": "Matches the base config defaults — no overrides applied\\.",
        "aggressive": "Wider delta/DTE windows, lower IV/score floors \\(more, riskier trades\\)\\.",
    }
    desc = _DESCRIPTIONS.get(name, _md(name))
    return f"📐 *Active profile: {_md(name)}*\n{desc}"


def format_help() -> str:
    """List all available bot commands."""
    lines = [
        "*IBKR Options Bot — Commands*",
        "",
        "*Scans & trading*",
        "/scan — Run full pipeline scan \\(CC/CSP/buy opportunities\\)",
        "/scan TICKER — Single\\-ticker scan \\(e\\.g\\. /scan AAPL\\)",
        "/pending — List pending approvals with expiry times",
        "/expire — Expire all pending approvals",
        "",
        "*Portfolio*",
        "/status — Account · short options · pending approvals",
        "/positions — Full portfolio positions with P&L",
        "/account — Account balances \\(buying power, net liq, margin\\)",
        "/fills — Recent fills \\(last 7 days\\)",
        "/calendar — Per\\-day P&L calendar \\(last 30 days\\)",
        "/campaigns — Wheel campaigns: P&L threads linking all legs per symbol",
        "/campaigns open — Only open campaigns",
        "",
        "*Automation*",
        "/mode — Show current mode \\(MANUAL/AUTOMATED\\) and toggle",
        "/halt — 🛑 Kill switch: stop all order transmission now",
        "/resume — Release the kill switch and resume execution",
        "",
        "*Profile*",
        "/profile — Show active trading profile",
        "/profile conservative|balanced|aggressive|default — Switch profile",
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
    all_src = ["IBKR option chain"]
    if any(c.price_source == "yfinance" for c in candidates):
        all_src.append("yfinance spot \\(fallback\\)")
    if any(c.greeks_source != "ibkr" for c in candidates):
        all_src.append("yfinance Greeks \\(fallback\\)")
    lines += ["", f"_Sources: {' · '.join(all_src)}_"]
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
    iv_stale: list[tuple[str, int | None]] | None = None,
) -> str:
    """Format system health status for Telegram.

    *iv_stale* (N4): (symbol, age_days|None) for symbols whose iv_history is stale or missing —
    rendered as a warning line since IV rank is both the largest score weight and a hard gate.
    """
    since_str = "never"
    if last_scan_at is not None:
        aware = last_scan_at.replace(tzinfo=UTC) if last_scan_at.tzinfo is None else last_scan_at
        mins = int((datetime.now(UTC) - aware).total_seconds() / 60)
        since_str = f"{mins}m ago"

    iv_ok = not iv_stale
    parts = [
        "*System Health*",
        "",
        f"{_icon(ib_exec_ok)} IBKR Exec \\(clientId 14\\)",
        f"{_icon(ib_scan_ok)} IBKR Scan \\(clientId 15\\)",
        f"{_icon(db_ok)} Database",
        f"{_icon(iv_ok)} IV history",
        "",
        f"Last scan:  {_md(since_str)}",
        f"Pending:    {_md(str(pending_approvals))} approval{'s' if pending_approvals != 1 else ''}",
        f"Orders:     {_md(str(open_orders))} open",
    ]
    if iv_stale:
        shown = ", ".join(
            f"{sym} ({'none' if age is None else f'{age}d'})" for sym, age in iv_stale[:8]
        )
        more = f" \\+{len(iv_stale) - 8} more" if len(iv_stale) > 8 else ""
        parts += [
            "",
            f"⚠️ Stale IV history: {_md(shown)}{more}",
            _md("→ run scripts.backfill_iv or check the EOD job"),
        ]
    return "\n".join(parts)


def format_status(
    positions: list[PositionSnapshot],
    account: AccountSnapshot | None,
    pending_approvals: int,
    open_orders: int,
    scans_run: int | None = None,
    scans_skipped: int | None = None,
) -> str:
    """Compact status overview: account + short options + pending approvals.

    ``scans_run``/``scans_skipped`` (S9, from the intraday loop's per-session counters) surface
    how many 15-min cycles actually ran vs. were lost to an overrun / lease contention, so the
    operator can see intended (~26) vs actual scan count. Omitted when not tracked yet.
    """
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

    if scans_run is not None or scans_skipped is not None:
        run = scans_run or 0
        skipped = scans_skipped or 0
        line = f"🔁 {_md(str(run))} intraday scan{'s' if run != 1 else ''} run"
        if skipped:
            line += f" · ⚠️ {_md(str(skipped))} skipped \\(overrun\\)"
        parts += ["", line]

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
    """Build the EOD report Telegram MarkdownV2 message.

    The numeric block is a ``` code fence ``` so columns actually align in Telegram's proportional
    body font (the old space-padding did not) and needs no per-character MarkdownV2 escaping. The
    narrative is interpretation only — it must not restate these figures (see prompts/eod.py).
    """
    date_str = _md(summary.date.strftime("%b %d, %Y"))
    nlv = summary.account.net_liquidation
    bp = summary.account.buying_power
    pct = (summary.unrealized_pnl_delta / nlv * 100) if nlv else 0.0

    # Monospace metric block — literal text inside a code fence (no MarkdownV2 escaping needed).
    metrics = [
        f"Premium cashflow  {_pnl2(summary.realized_pnl)}",
        (
            f"Unrealized        {_pnl2(summary.unrealized_pnl)}"
            f"  (Δ {_pnl2(summary.unrealized_pnl_delta)} / {pct:+.2f}% NLV)"
        ),
        f"Positions         {summary.open_positions} · Net Δ {summary.net_delta_exposure:+.2f}",
        f"NLV ${nlv:,.0f} · BP ${bp:,.0f}",
    ]
    parts: list[str] = [
        f"*EOD Report — {date_str}*",
        "",
        "```",
        *metrics,
        "```",
    ]

    # Clarify the figure only when there was cashflow to clarify — on a flat $0 / no-fill day the
    # disclaimer is pure noise (N13: it is option premium credits − debits, not a paired realized
    # P&L; assignment stock-leg P&L is excluded).
    if summary.realized_pnl != 0 or summary.fills_today > 0:
        parts.append(_md("(premium cashflow = option credits − debits; excludes assignment P&L)"))

    if summary.fills_today > 0:
        parts += ["", f"Fills today: {_md(str(summary.fills_today))}"]

    if summary.top_movers:
        driver_bits: list[str] = []
        for s in summary.top_movers:
            pnl = summary.mover_pnl.get(s)
            driver_bits.append(f"{_md(s)} {_md(_pnl(pnl))}" if pnl is not None else _md(s))
        parts.append(f"Drivers: {' · '.join(driver_bits)}")

    if narrative:
        parts += ["", f"_{_md(narrative)}_"]

    if summary.tomorrow_watchlist:
        if summary.watchlist_changed:
            wl_str = " · ".join(_md(s) for s in summary.tomorrow_watchlist)
            parts += ["", f"Tomorrow: {wl_str}"]
        else:
            n = len(summary.tomorrow_watchlist)
            parts += ["", f"Tomorrow: {_md(str(n))} names \\(unchanged\\)"]

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text + "\n_Sources: IBKR \\(fills · positions\\)_"


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


def format_roll_fill_confirm(
    underlying: str,
    old_strike: float,
    old_expiry: date,
    new_strike: float,
    new_expiry: date,
    right: str,
    contracts: int,
    net_credit: float,
) -> str:
    """Format a two-leg roll combo fill confirmation for Telegram MarkdownV2."""
    right_label = "Call" if right == "C" else "Put"
    net_total = net_credit * contracts * 100
    qty_str = f"{contracts:.0f}"
    parts = [
        f"🔄 *Rolled — {_md(underlying)} {_md(right_label)}*",
        (
            f"\\${_md(f'{old_strike:.0f}')} {_md(str(old_expiry))}"
            f" → \\${_md(f'{new_strike:.0f}')} {_md(str(new_expiry))}"
        ),
        (
            f"{_md(qty_str)} contract{'s' if contracts != 1 else ''}"
            f" · net credit \\${_md(f'{net_credit:.2f}')}/sh"
            f"  \\(\\${_md(f'{net_total:.0f}')} total\\)"
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
    return text + "\n_Source: IBKR_"


def format_assignment_alert(
    pos: PositionSnapshot,
    quote: OptionQuote,
    alerts: list[RollAlert],
    review: RollReview | None,
) -> str:
    """Format an assignment-risk alert for Telegram MarkdownV2.

    Distinct from roll alerts: frames the decision as roll / close / let-assign
    rather than a generic trigger list.
    """
    right_label = pos.right.value if pos.right else "?"
    strategy = "CC" if right_label == "C" else "CSP"
    strike_str = f"{pos.strike:.0f}" if pos.strike else "?"
    sym = pos.underlying or pos.symbol

    abs_delta = abs(quote.delta) if quote.delta is not None else None
    dte_str = str(alerts[0].dte) if alerts and alerts[0].dte is not None else "?"

    parts: list[str] = [
        f"🔴 *Assignment Risk — {_md(sym)} {_md(strategy)} \\${_md(strike_str)}*",
        f"\\|Δ\\| {_md(f'{abs_delta:.2f}') if abs_delta is not None else '?'} · DTE {_md(dte_str)}",
        "",
        "*Actions to consider:*",
        "• Roll out\\-and\\-up to a later expiry",
        "• Buy to close \\(take the loss\\)",
        "• Let assignment proceed \\(accept stock\\)",
    ]

    if review:
        parts += [
            "",
            "*── Claude ──*",
            f"*{_md(review.recommendation.upper())}*",
        ]
        if review.roll_target or review.rationale:
            parts.append(f"→ {_md(review.roll_target or review.rationale or '')}")
        if review.risks:
            parts.append(f"Risk: {_md(review.risks)}")
    else:
        parts += ["", "_Claude review unavailable — manual evaluation required_"]

    text = "\n".join(parts)
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text + "\n_Source: IBKR_"


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


def format_campaigns(campaigns: list[dict]) -> str:
    """MarkdownV2 summary of wheel-strategy campaigns (C6).

    Each dict should have: symbol, status, opened_date, closed_date, leg_count,
    total_premium_collected, total_debit_paid, net_premium, assigned,
    adjusted_cost_basis, realized_stock_pnl.
    """
    if not campaigns:
        return (
            "*Campaigns*\n\n_No campaigns recorded yet\\. "
            "Campaigns open automatically when the first option fill is recorded for a symbol\\._"
        )

    parts = [f"*Campaigns \\({_md(str(len(campaigns)))}\\)*", ""]

    for c in campaigns:
        symbol = c.get("symbol", "?")
        status = c.get("status", "open")
        opened = c.get("opened_date")
        closed = c.get("closed_date")
        leg_count = c.get("leg_count", 0)
        net = c.get("net_premium", 0.0)
        collected = c.get("total_premium_collected", 0.0)
        paid = c.get("total_debit_paid", 0.0)
        assigned = c.get("assigned", False)
        acb = c.get("adjusted_cost_basis")
        stock_pnl = c.get("realized_stock_pnl")

        status_icon = "🟢" if status == "open" else "⚪"
        assigned_tag = " 📦 assigned" if assigned else ""
        opened_str = opened.strftime("%b %d") if opened else "?"
        closed_str = f" → {closed.strftime('%b %d')}" if closed else ""
        net_str = _pnl(net) if net >= 0 else f"-${abs(net):,.0f}"
        legs_label = f"{leg_count} leg{'s' if leg_count != 1 else ''}"

        parts.append(
            f"{status_icon} *{_md(symbol)}*"
            f"  {_md(opened_str)}{_md(closed_str)}"
            f"  {_md(legs_label)}{_md(assigned_tag)}"
        )
        parts.append(
            f"  Net: {_md(net_str)}  \\(\\+{_md(f'{collected:,.0f}')} \\− {_md(f'{paid:,.0f}')}\\)"
        )
        if acb is not None:
            parts.append(f"  Adj\\. cost basis: \\${_md(f'{acb:.2f}')}/sh")
        if stock_pnl is not None:
            parts.append(f"  Stock leg P&L: {_md(_pnl(stock_pnl))}")
        parts.append("")

    text = "\n".join(parts).rstrip()
    if len(text) > _MAX_MESSAGE_LEN:
        text = text[: _MAX_MESSAGE_LEN - 3] + "\\.\\.\\."
    return text
