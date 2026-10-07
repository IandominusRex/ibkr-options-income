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

from src.common.books import is_spreads_underlying
from src.common.config import get_config
from src.common.market_hours import today_et
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
from src.engine.capital import Budgets, charge, resolve_caps, risk_units, seed_budgets

_INCOME_STRATEGIES = (Strategy.COVERED_CALL, Strategy.CASH_SECURED_PUT)


def _strategy_limits(strategy: Strategy) -> dict:
    """Return the strategy-specific limits dict from `config/risk_limits.yaml`."""
    return get_config().risk.get(strategy.value, {})


def _sector_of(symbol: str) -> str | None:
    """Resolve a symbol to its sector via universe.yaml `sectors:`. None if unmapped."""
    return get_config().universe.get("sectors", {}).get(symbol)


def _select_budget_representatives(
    candidates: list[TradeCandidate], survivor_ids: set[str]
) -> set[str]:
    """Keep exactly one candidate per (underlying, strategy) among *survivor_ids*.

    *candidates* must already be sorted by priority (blended_score desc) — the first
    survivor encountered per group is kept as that group's representative for the shared
    cumulative budgets in pass 2; every later survivor in the same group is left out (the
    caller rejects them with "dedupe_pre_gate"). Pure and side-effect-free so it can be
    tested without any config/account setup.
    """
    seen_groups: set[tuple[str, str]] = set()
    representatives: set[str] = set()
    for cand in candidates:
        if cand.candidate_id not in survivor_ids:
            continue
        key = (cand.underlying, cand.strategy.value)
        if key in seen_groups:
            continue
        seen_groups.add(key)
        representatives.add(cand.candidate_id)
    return representatives


def validate_candidates(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    iv_by_symbol: dict[str, float] | None = None,
    *,
    dedupe_same_symbol: bool = True,
) -> list[RiskVerdict]:
    """Gate each candidate against hard limits. One RiskVerdict per candidate.

    Every ``candidate_id`` in *candidates* must be unique — the per-candidate reason lists
    are keyed by it, so a duplicate id would silently overwrite an earlier candidate's gates.

    Candidates should be pre-sorted by priority (blended_score desc). Two passes:

    1. Per-candidate gates (ROC/yield/VRP, IV rank/RV, DTE, delta, contracts, earnings,
       margin) — independent of every other candidate, no shared state touched.
    2. Cumulative, shared-budget gates (per-ticker/per-sector risk units, the large-position
       slot, total CSP collateral, cash) — evaluated at most ONCE per (underlying, strategy),
       against the single highest-scoring pass-1 survivor in that group. Every other
       survivor in the same group is rejected with "dedupe_pre_gate" *without* being run
       through the shared budgets at all.

    Before this split, EVERY pass-1 survivor for a symbol — a scan can produce a dozen+
    strikes/expiries for one active name — was walked through the cumulative checks
    individually in score order, so a name's own candidates competed against each other for
    its own shared per-ticker budget (2026-09-11 finding: 95 of 96 concentration_limit
    rejects over two weeks were TQQQ, a name the account held zero position in — the
    budget was being spent entirely within single scan cycles, by TQQQ's own siblings). The
    cross-symbol behaviour this cumulative design was built for (D1/Phase B: "multiple
    candidates can't each claim the whole account") is unchanged: representatives from
    different symbols still compete for the shared sector/CSP/cash caps in score order.

    *dedupe_same_symbol* (default ``True``) controls pass 1's grouping only. When ``True``,
    same-symbol candidates are deduped to a single representative before the shared
    cumulative budget runs, as described above — the behaviour every batch caller wants (the
    full scan sweep, and the order-approval re-gate, which deliberately keeps it on so two
    approved-but-unexecuted orders on one underlying cannot both slip through). When
    ``False``, every pass-1 survivor is its own representative and no candidate is ever given
    the "dedupe_pre_gate" reason, restoring the pre-split greedy behaviour: the cumulative
    budgets are still consumed in score order, siblings included. That is what the
    single-ticker deep-dive (`/scan TICKER`, and the promote that reuses its pricing path)
    passes — it is a browse/compare view whose entire purpose is showing the operator every
    strike that individually qualifies, not picking a winner among them. The real
    execution-committing gate for anything promoted out of that view is the order-approval
    re-validation, which runs with the dedupe on.

    *iv_by_symbol* (optional) lets an existing option position charge the RISK-UNIT tallies,
    not just the raw-collateral one. Without it `budgets.ticker_risk` starts empty, so a
    candidate whose own IV is known is measured against a per-ticker/per-sector budget that
    counts nothing already held. Callers that already have IV for the whole portfolio in hand
    pass it (the full scan sweep); callers on a latency-sensitive path where it would cost a
    fresh network round-trip — the order-approval re-validation gate, a single-ticker
    deep-dive — deliberately do not, and rely on the raw-collateral tally instead.
    """
    if not candidates:
        return []

    risk = get_config().risk
    income = risk.get("income", {})
    portfolio = risk.get("portfolio", {})
    iv_cfg = risk.get("iv", {})
    events = risk.get("events", {})
    today = today_et()

    net_liq = account.net_liquidation
    margin_usage_pct = account.maintenance_margin / net_liq * 100 if net_liq > 0 else 0.0
    margin_exceeded = margin_usage_pct > portfolio.get("max_margin_usage_pct", 50.0)

    min_iv_rank = iv_cfg.get("min_iv_rank")
    min_iv_rv = iv_cfg.get("min_iv_rv_ratio")
    blackout_days = events.get("earnings_blackout_days", 0)

    caps = resolve_caps(account, risk)
    sector_of_fn = get_config().universe.get("sectors", {}).get
    budgets: Budgets = seed_budgets(
        positions, sector_of_fn, iv_by_symbol.get if iv_by_symbol else None, caps=caps
    )

    # --- Pass 1: per-candidate gates. No shared budget is read or written here, so these
    # can run in any order and never depend on what else is in *candidates*.
    candidate_reasons: dict[str, list[str]] = {}
    for cand in candidates:
        reasons: list[str] = []
        limits = _strategy_limits(cand.strategy)
        # The spreads book owns these underlyings outright (config/spreads.yaml). A web universe
        # override could still put one in front of the wheel; it must never reach an order.
        if is_spreads_underlying(cand.underlying):
            reasons.append("reserved_for_spreads_book")

        # --- Income quality gates. Scoped to the income strategies: a ROLL is a defensive
        # repair, not an income trade. A roll that pays a debit to move a challenged short
        # out and down has roc_pct = 0.0 by construction and a premium deliberately below
        # the new strike's fair value, so all three floors below would reject EVERY
        # defensive roll — structurally, at the approval-queue re-gate, after the operator
        # already approved it. Rolls carry their own purpose-built economics in
        # `strategies/rolling.py` (max_debit + min_delta_reduction), which remain the real
        # control for them.
        if cand.strategy in _INCOME_STRATEGIES:
            if cand.roc_pct < income.get("min_roc_pct", 1.0):
                reasons.append("roc_below_minimum")
            if cand.annualized_yield_pct < income.get("min_annualized_yield_pct", 12.0):
                reasons.append("yield_below_minimum")

            # --- Variance-risk-premium floor. The income thesis is that implied vol exceeds
            # realised vol; selling at or below Black-Scholes fair value priced at HV30 earns
            # no edge for the risk taken. This replaces the flat ROC floor as the primary gate:
            # max(1% ROC, 12% annualized) was a hidden ~25-30% IV floor that excluded every
            # low-vol diversifier in the universe and pushed every trade to the top of the
            # delta band (D2). Missing zone = data unavailable, never a rejection.
            if income.get("require_vrp_edge", True) and cand.ideal is not None:
                floor = cand.ideal.min_credit
                if floor is not None and floor > 0 and cand.premium < floor:
                    reasons.append("premium_below_fair_value")

        # --- IV environment: only sell premium when it's relatively expensive.
        # Enforced only when an IV rank is available (missing history is not a capital
        # risk, just lost optimization — rejecting all would silently zero out scans).
        if min_iv_rank is not None and cand.iv_rank is not None and cand.iv_rank < min_iv_rank:
            reasons.append("iv_rank_below_minimum")

        # --- IV/RV richness gate: sell only when implied vol richly exceeds realized vol.
        # Missing ratio is treated as "data unavailable" — not a capital risk — so it never
        # blocks the scan. Threshold configurable via risk_limits.yaml → iv → min_iv_rv_ratio.
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

        if margin_exceeded:
            reasons.append("margin_limit")

        candidate_reasons[cand.candidate_id] = reasons

    # --- Select the one representative per (underlying, strategy) allowed to spend the
    # shared cumulative budgets. Every other pass-1 survivor in the same group is rejected
    # right here, before ever touching `budgets` or `caps`. With *dedupe_same_symbol* False
    # every survivor is its own representative, so the loop below appends nothing and pass 2
    # runs for all of them in score order — the pre-split behaviour, verbatim.
    #
    # Only strategies that create NEW exposure are grouped, and are also the only ones pass 2
    # runs at all. Covered calls are written against shares the account ALREADY owns: selling
    # a call adds no new ticker/sector exposure (those shares are already counted in
    # `positions`) and consumes no buying power — it generates premium. Charging CC collateral
    # against the concentration limits and the BP buffer double-counts the shares and falsely
    # rejects calls on exactly the large holdings you most want to write against. A ROLL
    # likewise replaces an existing short (the old leg is already counted in `positions`); it
    # is net exposure-neutral, so charging the new leg as fresh exposure would double-count and
    # falsely reject defensive rolls (N20). Neither ever reaches the shared budget, so there is
    # nothing to dedupe among them either.
    survivor_ids = {
        cand.candidate_id
        for cand in candidates
        if not candidate_reasons[cand.candidate_id]
        and cand.strategy not in (Strategy.COVERED_CALL, Strategy.ROLL)
    }
    representative_ids = (
        _select_budget_representatives(candidates, survivor_ids)
        if dedupe_same_symbol
        else survivor_ids
    )
    for cand in candidates:
        if cand.candidate_id in survivor_ids and cand.candidate_id not in representative_ids:
            candidate_reasons[cand.candidate_id].append("dedupe_pre_gate")

    # --- Pass 2: cumulative, shared-budget gates. Representatives only, walked in the same
    # score-sorted order as *candidates* so cross-symbol competition for the shared
    # sector/CSP/cash budgets is still resolved by priority, exactly as before this split.
    for cand in candidates:
        if cand.candidate_id not in representative_ids:
            continue
        reasons = candidate_reasons[cand.candidate_id]
        sector = _sector_of(cand.underlying)

        # --- Cumulative concentration, measured in RISK UNITS. Raw collateral encodes share
        # price, which is not a risk measure: a 10-for-1 split would make a name tradeable
        # overnight with identical risk. Risk units (collateral x IV x sqrt(DTE/365)) put a
        # $65k META put and a $15k MARA put on the same scale. When IV is missing we fall back
        # to a stricter raw-collateral cap.
        # Mirrors `capital._fits` exactly — the gate must never be looser than the sizer.
        #
        # CUMULATIVE per-ticker collateral: this candidate on top of what is already held.
        cum_collateral = budgets.ticker_collateral.get(cand.underlying, 0.0) + cand.collateral
        units = risk_units(cand.collateral, cand.current_iv, cand.dte)
        if units is None:
            if cum_collateral > caps.max_ticker_collateral:
                reasons.append("concentration_limit")
        else:
            if budgets.ticker_risk.get(cand.underlying, 0.0) + units > caps.max_ticker_risk:
                reasons.append("concentration_limit")
            if sector and budgets.sector_risk.get(sector, 0.0) + units > caps.max_sector_risk:
                reasons.append("sector_limit")

        # Large-position slot: outsized CUMULATIVE exposure in one name is refused unless a
        # slot is free. This is also the raw-collateral backstop on every path that cannot
        # seed `ticker_risk` from live IV (no `iv_by_symbol` — the order-approval re-gate,
        # the single-ticker deep-dive): cumulative per-ticker collateral can never exceed
        # `max_pct_per_ticker_large`, whatever the candidate's own IV says. A ticker already
        # holding a slot (seeded from the book, or claimed by an earlier representative this
        # cycle via `capital.charge`) needs no NEW free slot for another lot on the same name.
        if cum_collateral > caps.max_ticker_collateral:
            if (
                cand.underlying not in budgets.large_tickers
                and len(budgets.large_tickers) >= caps.max_large_positions
            ):
                reasons.append("large_position_slot_full")
            elif cum_collateral > caps.large_ticker_collateral:
                reasons.append("concentration_limit")

        if cand.strategy == Strategy.CASH_SECURED_PUT:
            if budgets.csp_collateral + cand.collateral > caps.max_csp_collateral:
                reasons.append("csp_allocation_limit")
        if budgets.cash_used + cand.collateral > caps.deployable_cash:
            reasons.append("buying_power_buffer")

        # Dedupe: two independent checks above (the ticker-risk breach and the large-slot
        # ceiling) can both append "concentration_limit" for the same candidate. Display
        # already dedupes and PASS/REJECT is unaffected either way, but
        # storage.risk_verdicts persists `reasons` verbatim — collapse here, preserving
        # order and every distinct reason, so a duplicate never reaches the DB. Exactly as
        # the single-pass version always did.
        reasons = list(dict.fromkeys(reasons))
        candidate_reasons[cand.candidate_id] = reasons

        # Consume budget only for accepted candidates so later representatives see reduced
        # headroom. Covered calls and rolls never get here — they are not representatives —
        # so they touch none of these tallies.
        if not reasons:
            charge(
                contracts=cand.contracts,
                unit_collateral=cand.collateral / max(1, cand.contracts),
                current_iv=cand.current_iv,
                dte=cand.dte,
                symbol=cand.underlying,
                sector=sector,
                caps=caps,
                budgets=budgets,
            )

    return [
        RiskVerdict(
            candidate_id=cand.candidate_id,
            verdict=Verdict.PASS if not candidate_reasons[cand.candidate_id] else Verdict.REJECT,
            reasons=candidate_reasons[cand.candidate_id],
        )
        for cand in candidates
    ]


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

    live_cfg = get_config().risk.get("live_execution", {}) or {}
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
