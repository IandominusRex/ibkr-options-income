"""Deterministic hard-limit gate. NO LLM involvement. The only path to order execution.

Runs in two places:
  1. Decision time — `validate_candidates` gates the whole ranked batch at once, so
     cumulative limits (per-ticker / per-sector / total-CSP collateral / buying-power
     buffer) are enforced across the set, not just per candidate in isolation.
  2. Order-send time — `validate_live_quote` re-checks a single candidate against the
     fresh live quote (delta drift / collapsed mid) just before transmission.

Purely deterministic — no external calls beyond reading config. Candidates passed to
`validate_candidates` are expected to be pre-sorted by priority (blended_score desc);
the cumulative budgets are consumed greedily in that order.
"""

from __future__ import annotations

from src.common.config import get_config
from src.common.market_hours import today_et
from src.common.profile import get_effective_risk
from src.common.schemas import (
    AccountSnapshot,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RiskVerdict,
    Strategy,
    TradeCandidate,
    Verdict,
)

_INCOME_STRATEGIES = (Strategy.COVERED_CALL, Strategy.CASH_SECURED_PUT)


def _strategy_limits(strategy: Strategy) -> dict:
    """Return the strategy-specific limits dict, merged with any active profile overlay."""
    return get_effective_risk().get(strategy.value, {})


def _sector_of(symbol: str) -> str | None:
    """Resolve a symbol to its sector via universe.yaml `sectors:`. None if unmapped."""
    return get_config().universe.get("sectors", {}).get(symbol)


def _ticker_key(p: PositionSnapshot) -> str:
    return p.underlying or p.symbol


def _seed_exposures(
    positions: list[PositionSnapshot],
) -> tuple[dict[str, float], dict[str, float], float]:
    """Seed per-ticker exposure, per-sector exposure, and existing CSP collateral from
    current positions.

    Exposure measures the capital a position represents toward the concentration caps. For a
    short put that is the assignment liability — strike × 100 × |contracts| — NOT the option's
    tiny |market value| (~1% of notional). Charging it at |MV| (N5) let a ticker with several
    working short puts read as nearly unexposed and slip past the 5%-per-ticker cap. Counting it
    at strike collateral matches exactly how a *new* CSP candidate is charged (cand.collateral),
    so existing and proposed CSPs share one consistent budget. Everything else (long/short stock,
    short calls) is measured at |MV|; short stock has negative MV, hence abs()."""
    ticker_exposure: dict[str, float] = {}
    sector_exposure: dict[str, float] = {}
    csp_collateral = 0.0

    for p in positions:
        key = _ticker_key(p)
        is_short_put = (
            p.sec_type == "OPT" and p.right == OptionRight.PUT and p.position < 0 and p.strike
        )
        if is_short_put:
            # strike is truthy here (guarded above); mypy-safe via `or 0.0`.
            exposure = (p.strike or 0.0) * 100.0 * abs(p.position)
            csp_collateral += exposure
        else:
            exposure = abs(p.market_value or 0.0)
        ticker_exposure[key] = ticker_exposure.get(key, 0.0) + exposure
        sector = _sector_of(key)
        if sector:
            sector_exposure[sector] = sector_exposure.get(sector, 0.0) + exposure

    return ticker_exposure, sector_exposure, csp_collateral


def validate_candidates(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
) -> list[RiskVerdict]:
    """Gate each candidate against hard limits. One RiskVerdict per candidate.

    Candidates should be pre-sorted by priority (blended_score desc). Cumulative
    limits are consumed greedily in that order: an accepted candidate's collateral is
    added to the running tallies so later candidates see the reduced headroom.
    """
    if not candidates:
        return []

    risk = get_effective_risk()
    income = risk.get("income", {})
    portfolio = risk.get("portfolio", {})
    iv_cfg = risk.get("iv", {})
    events = risk.get("events", {})
    today = today_et()

    net_liq = account.net_liquidation
    # Account-level flags — computed once, applied to every candidate.
    margin_usage_pct = account.maintenance_margin / net_liq * 100 if net_liq > 0 else 0.0
    margin_exceeded = margin_usage_pct > portfolio.get("max_margin_usage_pct", 50.0)
    required_bp = net_liq * portfolio.get("min_buying_power_buffer_pct", 15.0) / 100

    max_ticker_value = net_liq * portfolio.get("max_pct_per_ticker", 5.0) / 100
    max_sector_pct = portfolio.get("max_pct_per_sector")
    max_csp_pct = portfolio.get("max_csp_allocation_pct")
    min_iv_rank = iv_cfg.get("min_iv_rank")
    blackout_days = events.get("earnings_blackout_days", 0)

    # Running tallies seeded from existing positions; bp_used counts only NEW collateral
    # (existing positions are already reflected in account.buying_power).
    ticker_exposure, sector_exposure, csp_collateral = _seed_exposures(positions)
    bp_used = 0.0

    verdicts: list[RiskVerdict] = []

    for cand in candidates:
        reasons: list[str] = []
        limits = _strategy_limits(cand.strategy)

        # Covered calls are written against shares the account ALREADY owns. Selling a
        # call adds no new ticker/sector exposure (those shares are already counted in
        # `positions`) and consumes no buying power — it generates premium. Charging CC
        # collateral against the concentration limits and BP buffer double-counts the
        # shares and falsely rejects calls on exactly the large holdings you most want to
        # write against. A ROLL likewise replaces an existing short (the old leg is already
        # counted in `positions`); it is net exposure-neutral, so charging the new leg as
        # fresh exposure would double-count and falsely reject defensive rolls (N20). Only
        # strategies that create NEW exposure (CSPs, via assignment) consume these budgets.
        adds_new_exposure = cand.strategy not in (Strategy.COVERED_CALL, Strategy.ROLL)

        # --- Income quality gates ---
        if cand.roc_pct < income.get("min_roc_pct", 1.0):
            reasons.append("roc_below_minimum")
        if cand.annualized_yield_pct < income.get("min_annualized_yield_pct", 12.0):
            reasons.append("yield_below_minimum")

        # --- IV environment: only sell premium when it's relatively expensive.
        # Enforced only when an IV rank is available (missing history is not a capital
        # risk, just lost optimization — rejecting all would silently zero out scans).
        if min_iv_rank is not None and cand.iv_rank is not None and cand.iv_rank < min_iv_rank:
            reasons.append("iv_rank_below_minimum")

        # --- IV/RV richness gate: sell only when implied vol richly exceeds realized vol.
        # Missing ratio is treated as "data unavailable" — not a capital risk — so it never
        # blocks the scan. Threshold configurable via risk_limits.yaml → iv → min_iv_rv_ratio.
        min_iv_rv = iv_cfg.get("min_iv_rv_ratio")
        if (
            min_iv_rv is not None
            and cand.iv_rv_ratio is not None
            and cand.iv_rv_ratio < float(min_iv_rv)
        ):
            reasons.append("iv_rv_below_minimum")

        # --- DTE window (strategy-specific) ---
        if limits and not (limits.get("dte_min", 0) <= cand.dte <= limits.get("dte_max", 999)):
            reasons.append("dte_out_of_range")

        # --- Delta: required for income strategies regardless of limits-dict presence ---
        if cand.strategy in _INCOME_STRATEGIES:
            if cand.delta is None:
                reasons.append("delta_missing")
            else:
                # Sign check: IBKR returns negative deltas for puts.
                # A wrong-sign value (e.g. delta=+0.25 on a PUT) passes abs() checks
                # but indicates a data error — reject rather than silently accept.
                if cand.right == OptionRight.PUT and cand.delta > 0:
                    reasons.append("delta_sign_mismatch")
                elif cand.right == OptionRight.CALL and cand.delta < 0:
                    reasons.append("delta_sign_mismatch")
                elif limits and not (
                    limits.get("delta_min", 0.0) <= abs(cand.delta) <= limits.get("delta_max", 1.0)
                ):
                    reasons.append("delta_out_of_range")

        # --- Max contracts per position ---
        max_contracts = limits.get("max_contracts") if limits else None
        if max_contracts is not None and cand.contracts > max_contracts:
            reasons.append("contracts_exceeds_max")

        # --- Earnings blackout: no short premium that lives through (or just before) earnings ---
        if cand.next_earnings is not None:
            days_to_earnings = (cand.next_earnings - today).days
            if cand.next_earnings <= cand.expiry or 0 <= days_to_earnings <= blackout_days:
                reasons.append("earnings_blackout")

        # --- Contract count ---
        if cand.contracts < 1:
            reasons.append("no_contracts")

        # --- Cumulative per-ticker concentration (new-exposure strategies only) ---
        sector = _sector_of(cand.underlying)
        proj_ticker = None
        proj_sector = None
        proj_csp = None
        if adds_new_exposure:
            proj_ticker = ticker_exposure.get(cand.underlying, 0.0) + cand.collateral
            if proj_ticker > max_ticker_value:
                reasons.append("concentration_limit")

            # --- Cumulative per-sector concentration (only for mapped symbols) ---
            if sector and max_sector_pct:
                max_sector_value = net_liq * max_sector_pct / 100
                proj_sector = sector_exposure.get(sector, 0.0) + cand.collateral
                if proj_sector > max_sector_value:
                    reasons.append("sector_limit")

            # --- Cumulative total-CSP collateral cap ---
            if cand.strategy == Strategy.CASH_SECURED_PUT and max_csp_pct:
                max_csp_value = net_liq * max_csp_pct / 100
                proj_csp = csp_collateral + cand.collateral
                if proj_csp > max_csp_value:
                    reasons.append("csp_allocation_limit")

        # --- Account-level margin (applies to all) + cumulative BP buffer (new exposure only) ---
        if margin_exceeded:
            reasons.append("margin_limit")
        if adds_new_exposure and account.buying_power - bp_used - cand.collateral < required_bp:
            reasons.append("buying_power_buffer")

        verdict = Verdict.PASS if not reasons else Verdict.REJECT

        # Consume budget only for accepted, new-exposure candidates so later ones see
        # reduced headroom. Covered calls touch none of these tallies.
        if verdict == Verdict.PASS and adds_new_exposure:
            if proj_ticker is not None:
                ticker_exposure[cand.underlying] = proj_ticker
            if sector and proj_sector is not None:
                sector_exposure[sector] = proj_sector
            if proj_csp is not None:
                csp_collateral = proj_csp
            bp_used += cand.collateral

        verdicts.append(
            RiskVerdict(candidate_id=cand.candidate_id, verdict=verdict, reasons=reasons)
        )

    return verdicts


def validate_live_quote(candidate: TradeCandidate, quote: OptionQuote) -> RiskVerdict:
    """Second gate: re-check a single candidate against the FRESH live quote at send time.

    Catches the case the decision-time gate cannot see: the option drifted between the
    the scan and execution (e.g. went deep ITM → delta out of range, or the mid
    collapsed). Deterministic. Delta is only enforced when the live quote actually carries
    greeks — missing live greeks degrade to the (already-passed) decision-time gate rather
    than blocking the fill.
    """
    reasons: list[str] = []

    # Require a real two-sided market: bid and ask both present, ask > 0.
    # Checking quote.mid alone is unsafe — it falls back to quote.last, which can
    # be a stale prior-session print that bears no relation to the current market.
    if quote.ask is None or quote.ask <= 0:
        reasons.append("live_no_mid")
    elif quote.bid is None:
        reasons.append("live_no_mid")
    elif quote.bid < 0:
        # IBKR uses -1.0 as a sentinel for "no bid data". A negative bid would
        # produce a wildly wrong mid-price (e.g. mid = (-1 + 2) / 2 = $0.50).
        reasons.append("negative_bid_sentinel")

    live_cfg = get_effective_risk().get("live_execution", {}) or {}
    is_income = candidate.strategy in _INCOME_STRATEGIES
    cfg = get_config()

    # F6: in LIVE mode, refuse to fill an income trade unless the live quote carries
    # IBKR-sourced greeks. The delta gate below silently degrades when greeks are absent
    # (correct for paper); for real money we require trustworthy live greeks rather than
    # leaning on the scan-time (possibly yfinance-derived) delta.
    if (
        is_income
        and cfg.is_live
        and live_cfg.get("require_ibkr_greeks_when_live", True)
        and (quote.delta is None or quote.greeks_source != "ibkr")
    ):
        reasons.append("live_greeks_required")

    if quote.delta is not None and is_income:
        limits = _strategy_limits(candidate.strategy)
        if limits and not (
            limits.get("delta_min", 0.0) <= abs(quote.delta) <= limits.get("delta_max", 1.0)
        ):
            reasons.append("live_delta_out_of_range")

    # F2: reject when the live mid has collapsed below a floor relative to the approved
    # premium (e.g. an intraday IV crush between approval and execution). We sell income
    # premium at the mid, so a much lower live mid means collecting far less than approved.
    min_ratio = live_cfg.get("min_live_premium_ratio")
    if (
        is_income
        and min_ratio
        and candidate.premium > 0
        and quote.mid is not None
        and quote.mid > 0
        and quote.mid < float(min_ratio) * candidate.premium
    ):
        reasons.append("live_premium_collapse")

    return RiskVerdict(
        candidate_id=candidate.candidate_id,
        verdict=Verdict.PASS if not reasons else Verdict.REJECT,
        reasons=reasons,
    )
