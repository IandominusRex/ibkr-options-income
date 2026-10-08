"""The spreads rules engine — the only gate in front of a spreads order.

Deterministic Python, no LLM, no I/O. It runs twice per trade: at decision time on the
candidate, and again at send time on the same spread repriced from fresh leg quotes
(``executor.SpreadExecutor.open``). Every rejection names its reason; ``approved`` is simply
"no reasons". Sizing lives here too, so nothing outside this module can change a contract count.
"""

from __future__ import annotations

import math

from src.common.config import SpreadsCfg
from src.common.market_hours import is_early_close, is_trading_day, next_session
from src.common.schemas import SpreadCandidate, SpreadRiskContext, SpreadVerdict
from src.spreads.pricing import ET, day_schedule


def size(c: SpreadCandidate, cfg: SpreadsCfg, capital_usd: float) -> int:
    """Contracts whose combined max loss stays within ``max_loss_pct_of_capital`` of the book."""
    per_contract = c.max_loss_per_contract
    if per_contract <= 0 or c.credit_mid <= 0 or capital_usd <= 0:
        return 0
    n = math.floor(cfg.risk.max_loss_pct_of_capital * capital_usd / per_contract)
    return max(0, min(n, cfg.risk.max_contracts))


def validate(c: SpreadCandidate, ctx: SpreadRiskContext, cfg: SpreadsCfg) -> SpreadVerdict:
    r, s = cfg.risk, cfg.selection
    reasons: list[str] = []
    now_et = ctx.now.astimezone(ET)
    today = now_et.date()
    sched = day_schedule(cfg.schedule, today)
    hhmm = now_et.strftime("%H:%M")

    # --- Calendar and clock.
    if not cfg.enabled:
        reasons.append("spreads_disabled")
    if not is_trading_day(today):
        reasons.append("not_trading_day")
    elif sched.skip_early_close_days and is_early_close(today):
        reasons.append("early_close_day")
    for ev in r.events:
        if ev.day == today and (ev.until is None or hhmm < ev.until):
            reasons.append("event_day" if ev.until is None else "event_window")
            break
    if c.side == "call" and r.ex_dividend_dates:
        exdiv = set(r.ex_dividend_dates)
        if today in exdiv or next_session(today) in exdiv:
            reasons.append(
                "ex_dividend_window"
            )  # short American calls get exercised for the dividend
    if not (sched.entry_start <= hhmm < sched.entry_end):
        reasons.append("outside_entry_window")
    if c.expiry != today:
        reasons.append("not_0dte")

    # --- Gamma regime. Negative gamma is traded by default ("allow") and tagged on the
    # position (store.open_position); "skip" turns it back into a rejection.
    lv = ctx.levels
    if lv is None:
        reasons.append("no_levels")
    else:
        if lv.regime == "unknown":
            reasons.append("regime_unknown")
        elif lv.regime == "negative" and cfg.gex.negative_gamma_action == "skip":
            reasons.append("negative_gamma")
        if lv.flip is not None and lv.spot > 0:
            if abs(lv.spot - lv.flip) / lv.spot < cfg.gex.flip_buffer_pct:
                reasons.append("near_gamma_flip")

    # --- Quote quality and economics.
    if (ctx.now - c.quote_time).total_seconds() > r.max_quote_age_seconds:
        reasons.append("stale_quote")
    if abs(c.width - s.width) > 1e-9:
        reasons.append("width_mismatch")
    if c.credit_mid < s.min_credit_pct_of_width * s.width:
        reasons.append("credit_below_min")
    if c.credit_natural <= 0:
        reasons.append("no_natural_credit")
    leg_spreads = [p for p in (c.short_leg_spread_pct, c.long_leg_spread_pct) if p is not None]
    if len(leg_spreads) < 2 or max(leg_spreads) > s.max_leg_spread_pct:
        reasons.append("quote_too_wide")
    if c.short_delta is None:
        reasons.append("no_delta")
    elif abs(c.short_delta) > s.short_delta_max:
        reasons.append("delta_too_high")

    # --- Book-level limits, as shares of the book's capital (starting capital + realized P&L).
    cap = ctx.capital_usd
    if ctx.open_spreads >= r.max_open_spreads:
        reasons.append("max_open_spreads")
    if ctx.trades_today >= r.max_trades_per_day:
        reasons.append("max_trades_per_day")
    if r.one_side_per_day and any(side != c.side for side in ctx.sides_today):
        reasons.append("other_side_traded_today")
    if ctx.realized_pnl_today_usd <= -r.max_daily_loss_pct_of_capital * cap:
        reasons.append("daily_loss_limit")
    n = size(c, cfg, cap)
    if n < 1:
        reasons.append("max_loss_per_trade")
    elif ctx.open_risk_usd + n * c.max_loss_per_contract > r.max_total_risk_pct_of_capital * cap:
        reasons.append("max_total_risk")
    if ctx.excess_liquidity_usd is None:
        reasons.append("account_unknown")
    elif ctx.excess_liquidity_usd < r.min_excess_liquidity_usd:
        reasons.append("excess_liquidity_floor")

    approved = not reasons
    return SpreadVerdict(
        spread_id=c.spread_id, approved=approved, contracts=n if approved else 0, reasons=reasons
    )
