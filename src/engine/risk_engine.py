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

from datetime import date

from src.common import hedge_view
from src.common.books import (
    HEDGE_CLAUDE_PREFIX,
    HEDGE_ORDER_PREFIX,
    Attribution,
    ValueExposure,
    is_spreads_underlying,
    value_exposure,
)
from src.common.config import RollCfg, get_config, get_envelope_cfg, get_hedge_cfg
from src.common.envelope_types import BookLine, EnvelopeRoom, ShockInputs
from src.common.market_hours import today_et
from src.common.schemas import (
    AccountSnapshot,
    HedgeCandidate,
    HedgeContext,
    HedgeLeg,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RiskVerdict,
    SizingContext,
    StockOrderIntent,
    Strategy,
    TradeCandidate,
    Verdict,
)
from src.engine.capital import (
    Budgets,
    Caps,
    ReleaseCandidate,
    charge,
    index_lot,
    release_reasons,
    resolve_caps,
    risk_units,
    scale_caps,
    seed_budgets,
)
from src.engine.regime_limits import (
    active,
    bottoming_reason,
    bottoming_send_reason,
    bottoming_tag,
    cc_timing_reasons,
    ceiling_kind,
    daily_limit,
    floor_left,
    governing_index,
    leverage_factor,
    live_bottoming_delta_reason,
    live_cc_delta_reason,
    live_ladder_reason,
    loss_exit_reason,
    multipliers,
    per_trade_cap,
    scale_in_reason,
    sizing_note,
    sleeve_contracts,
    sleeve_pace_reason,
    sleeve_path,
    sleeve_room_usd,
    sleeve_window_reason,
    stacking_for,
    switch_on,
    tech_cap_reason,
    tech_exposure,
    vrp_waiver,
)
from src.storage.slow_breaker import csp_budget_fraction as slow_breaker_fraction

_INCOME_STRATEGIES = (Strategy.COVERED_CALL, Strategy.CASH_SECURED_PUT)


def rolls_down_enough(old_strike: float, new_strike: float, net: float, cfg: RollCfg) -> bool:
    """An ITM put roll: a lower strike, and a new assignment cost (strike minus the net credit)
    at least ``csp.itm_min_basis_drop_pct`` under the old strike. The roll constructor
    uses the same rule, so the generator and the gate cannot disagree."""
    if cfg.csp.itm_min_basis_drop_pct is None:
        return True
    cap = old_strike * (1.0 - cfg.csp.itm_min_basis_drop_pct / 100.0)
    return new_strike < old_strike - 1e-9 and new_strike - net <= cap + 1e-9


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


def _cumulative_reasons(
    cand: TradeCandidate,
    sector: str | None,
    caps: Caps,
    budgets: Budgets,
    leverage: int = 1,
) -> list[str]:
    """The pass-2 (shared-budget) reasons *cand* would be rejected for against *caps*.

    Mirrors ``capital._fits`` exactly: the gate must never be looser than the sizer. Pure with
    respect to *budgets* (read only), so it can be run twice, against the regime-scaled caps and
    then the unscaled ones, to tell a regime rejection from a book rejection. *leverage*
    (risk-envelope §3.5) weights the lot's exposure in the per-ticker collateral tally and the CSP
    budget, as ``_fits`` does; cash and risk units are not scaled.
    """
    reasons: list[str] = []
    weighted = cand.collateral * max(1, leverage)
    held = budgets.ticker_collateral.get(cand.underlying, 0.0)
    # --- Cumulative concentration, measured in RISK UNITS. Raw collateral encodes share
    # price, which is not a risk measure: a 10-for-1 split would make a name tradeable
    # overnight with identical risk. Risk units (collateral x IV x sqrt(DTE/365)) put a
    # $65k META put and a $15k MARA put on the same scale. When IV is missing we fall back
    # to a stricter raw-collateral cap.
    #
    # CUMULATIVE per-ticker collateral: this candidate on top of what is already held.
    cum_collateral = held + weighted
    # The index class's one slot-free lot (Task 21), exactly as `_fits` grants it.
    first_index_lot = index_lot(cand.underlying, held, cum_collateral, caps)
    units = risk_units(cand.collateral, cand.current_iv, cand.dte)
    if units is None:
        if cum_collateral > caps.max_ticker_collateral and not first_index_lot:
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
    if cum_collateral > caps.max_ticker_collateral and not first_index_lot:
        if (
            cand.underlying not in budgets.large_tickers
            and len(budgets.large_tickers) >= caps.max_large_positions
        ):
            reasons.append("large_position_slot_full")
        elif cum_collateral > caps.large_ticker_collateral:
            reasons.append("concentration_limit")

    if cand.strategy == Strategy.CASH_SECURED_PUT:
        if budgets.csp_collateral + weighted > caps.max_csp_collateral:
            reasons.append("csp_allocation_limit")
    if budgets.cash_used + cand.collateral > caps.deployable_cash:
        reasons.append("buying_power_buffer")
    return reasons


def _hedge_book_for_clash() -> tuple[set[str] | None, set[tuple[str, str, float, date]]]:
    """The hedge book's open (or working) instruments and contract identities, through the
    read-only ``hedge_view``; ``(None, set())`` when it cannot be read."""
    book = hedge_view.open_hedges()
    if book is None:
        return None, set()
    names = {h.instrument.upper() for h in book}
    keys = {
        (h.instrument.upper(), leg.right, round(float(leg.strike), 4), leg.expiry)
        for h in book
        for leg in h.legs
    }
    return names, keys


def validate_candidates(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    iv_by_symbol: dict[str, float] | None = None,
    *,
    dedupe_same_symbol: bool = True,
    sizing: SizingContext | None = None,
    envelope: tuple[EnvelopeRoom, ShockInputs] | None = None,
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

    *sizing* carries the market regime (`src/regime/context.py`); ``None`` (rolls, tests) means no
    regime behaviour. It only ever touches cash-secured puts: covered calls and rolls are never
    regime-limited, exactly like the income gates above. (The one thing a covered call meets is
    the breakout rule, `cc_timing_reasons`, which has its own switch and also reads the breakout
    frozen on the candidate when there is no context.) With it, a CSP is also held to the
    per-trade ceiling (`regime_ceiling`, or `leveraged_ceiling` for a leveraged ETF), the
    regime-scaled budgets (`regime_budget` when only the scaled cap stops it, i.e. it fits every
    unscaled cap), the day's new-CSP count (`regime_daily_limit`, per governing index), and the
    guaranteed floor: while ``floor_new_per_day`` lots remain, a candidate whose *only* reason is
    `regime_budget` is accepted and tagged ``sizing.floor_lot`` (an in-place update of the
    candidate; the gate returns verdicts only). The generator calls the same functions
    (`src/engine/regime_limits.py`), so the two cannot disagree.

    *envelope* is the risk envelope measured on live IV (risk-envelope Tasks 18-19: the room and
    the book's shock inputs, `src/engine/envelope.py`). Every opening CSP that reaches the shared
    budgets is tested with ``envelope.admits``: ``shock_budget`` (S10_gross after the lot above
    L(t)), ``gross_budget`` (U_ew above its limit), ``t20_budget`` (when the ``t20_limit`` switch is
    on) or ``envelope_unmeasured``. Covered calls and rolls are never tested. The room's
    ``enforce`` decides: ``on`` appends the reasons, ``record`` returns them on the verdict's
    ``envelope_would`` (the caller writes them to ``sizing_actions``, kind ``envelope_record``, in
    its own transaction: the gate writes nothing) and admits, ``off`` does nothing. With no envelope and the
    ``envelope_enforce`` switch ``on``, every opening CSP is refused ``envelope_unmeasured`` (fail
    closed). A lot accepted in the batch joins the book, so later lots are measured with it.

    **No reason is erased (P4).** The value book's ``combined_name_cap`` and the envelope reasons
    are collected apart and appended **after** the regime rewrite (``regime_budget``) and the
    guaranteed floor, so neither can replace or clear them. The wheel's nominal gross cap is
    gone: U_ew (``gross_budget``) replaces it (ruling Q3; the value book's own gate keeps its
    nominal cap as the one refusal released capital can cure).

    A leveraged ETF's exposure counts at its leverage (``leverage_factor``) in the per-ticker and
    CSP budgets, as the generator counts it (§3.5).
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

    # The value book (spec §9.2-§9.3, revision 4): off -> nothing below changes the wheel.
    vx: ValueExposure = value_exposure()
    caps = resolve_caps(account, risk, value_claim=vx.claim, csp_fraction=slow_breaker_fraction())
    sector_of_fn = get_config().universe.get("sectors", {}).get

    def leverage_of(name: str) -> int:
        return leverage_factor(sizing, name) or 1

    budgets: Budgets = seed_budgets(
        positions,
        sector_of_fn,
        iv_by_symbol.get if iv_by_symbol else None,
        caps=caps,
        extra_exposure=vx.by_name,
        leverage_of=leverage_of,
    )
    combined_cap = net_liq * float(portfolio.get("max_combined_name_pct", 15.0)) / 100.0

    # --- Pass 1: per-candidate gates. No shared budget is read or written here, so these
    # can run in any order and never depend on what else is in *candidates*.
    candidate_reasons: dict[str, list[str]] = {}
    # What the tech-linked cap and the stacking rule would refuse while their switch is off (Task 25):
    # never a reason, returned on the verdict and written to ``sizing_actions`` by the caller.
    limits_would: dict[str, list[str]] = {}
    vrp_waived_ids: set[str] = set()  # name-level signal lots the fair-value floor would refuse
    hedge_names, hedge_keys = _hedge_book_for_clash()
    hedge_cfg_names = set(get_hedge_cfg().underlyings)
    for cand in candidates:
        reasons: list[str] = []
        limits = _strategy_limits(cand.strategy)
        # The spreads book owns these underlyings outright (config/spreads.yaml). A web universe
        # override could still put one in front of the wheel; it must never reach an order.
        if is_spreads_underlying(cand.underlying):
            reasons.append("reserved_for_spreads_book")
        # The hedge book (risk-envelope Task 34, spec §3.10.0/§3.10.9, H9): no wheel short in a
        # contract the hedge holds (IBKR nets same-contract positions across clientIds), and no
        # wheel opening on an instrument while a hedge on it is open (the QQQ-route rule: a QQQ
        # put exercised into shares, a same-underlying margin offset). An unreadable hedge book
        # refuses every opening on a hedge underlying (fail closed).
        und = cand.underlying.upper()
        if hedge_names is None:
            if und in hedge_cfg_names:
                reasons.append("hedge_book_unreadable")
        else:
            key = (und, cand.right.value, round(float(cand.strike), 4), cand.expiry)
            if key in hedge_keys:
                reasons.append("hedge_contract_clash")
            if und in hedge_names:
                reasons.append("hedge_qqq_route")
        # Value book (spec §9.2): a name whose share attribution is frozen takes no new put and
        # no new call until a human clears it; with the book on and value.db unreadable, no
        # new put at all (the gross and combined caps cannot be measured: fail closed).
        if vx.active and cand.strategy in (Strategy.CASH_SECURED_PUT, Strategy.COVERED_CALL):
            if cand.underlying.upper() in vx.frozen:
                reasons.append("book_attribution_mismatch")
            if not vx.readable and cand.strategy == Strategy.CASH_SECURED_PUT:
                reasons.append("value_book_unreadable")

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
            # One exemption (OI-B3): a CSP opened on a name-level bottoming signal, which
            # carries its own guards. At scan time the fresh signal decides; at send time, where
            # the context has no signals, the tag frozen on the card does (`vrp_waiver`).
            if income.get("require_vrp_edge", True) and cand.ideal is not None:
                floor = cand.ideal.min_credit
                if floor is not None and floor > 0 and cand.premium < floor:
                    if vrp_waiver(
                        sizing, cand.strategy, cand.underlying, cand.ideal.spot, cand.sizing
                    ):
                        vrp_waived_ids.add(cand.candidate_id)
                    else:
                        reasons.append("premium_below_fair_value")

        # --- IV environment: only sell premium when it's relatively expensive.
        # Enforced only when an IV rank is available (missing history is not a capital
        # risk, just lost optimization — rejecting all would silently zero out scans).
        # Both IV floors are entry-selection filters, not risk limits: a ROLL re-places an
        # exposure the account already carries, so they do not apply to it (2026-10-11).
        is_roll = cand.strategy == Strategy.ROLL
        if (
            not is_roll
            and min_iv_rank is not None
            and cand.iv_rank is not None
            and cand.iv_rank < min_iv_rank
        ):
            reasons.append("iv_rank_below_minimum")

        # --- IV/RV richness gate: sell only when implied vol richly exceeds realized vol.
        # Missing ratio is treated as "data unavailable" — not a capital risk — so it never
        # blocks the scan. Threshold configurable via risk_limits.yaml → iv → min_iv_rv_ratio.
        if (
            not is_roll
            and min_iv_rv is not None
            and cand.iv_rv_ratio is not None
            and cand.iv_rv_ratio < float(min_iv_rv)
        ):
            reasons.append("iv_rv_below_minimum")

        # A leveraged sleeve lot (Task 23): the sleeve's own DTE and delta windows replace the put's.
        is_sleeve = cand.strategy == Strategy.CASH_SECURED_PUT and (
            sleeve_path(sizing, cand.underlying, cand.sizing) is not None
        )

        # --- DTE window (strategy-specific) ---
        if (
            limits
            and not is_sleeve
            and not (limits.get("dte_min", 0) <= cand.dte <= limits.get("dte_max", 999))
        ):
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
                elif (
                    limits
                    and not is_sleeve
                    and not (
                        limits.get("delta_min", 0.0)
                        <= abs(cand.delta)
                        <= limits.get("delta_max", 1.0)
                    )
                ):
                    reasons.append("delta_out_of_range")
        if is_sleeve:
            window = sleeve_window_reason(
                sizing,
                cand.underlying,
                dte=cand.dte,
                delta=cand.delta,
                iv_rank=cand.iv_rank,
                frozen=cand.sizing,
            )
            if window is not None:
                reasons.append(window)

        # --- Max contracts per position ---
        max_contracts = limits.get("max_contracts") if limits else None
        if max_contracts is not None and cand.contracts > max_contracts:
            reasons.append("contracts_exceeds_max")

        # --- Per-trade ceiling from the market regime and, for a leveraged ETF, its smaller
        # ceiling. Cash-secured puts only: a roll or a covered call is never regime-limited.
        if sizing is not None and cand.strategy == Strategy.CASH_SECURED_PUT:
            hard_max = int(limits.get("max_contracts", 10)) if limits else 10
            if cand.contracts > per_trade_cap(sizing, cand.underlying, hard_max, cand.sizing):
                reasons.append(
                    ceiling_kind(sizing, cand.underlying, hard_max, cand.contracts, cand.sizing)
                    or "regime_ceiling"
                )
            # The scale-in ladder (same functions as the sizer): a loss exit on the name earlier
            # today blocks it; a name under the ladder waits for its zone. A missing ``ideal``
            # means no spot to judge, which is data-unavailable and never rejects.
            cooldown = loss_exit_reason(sizing, cand.underlying)
            if cooldown is not None:
                reasons.append(cooldown)
            if cand.ideal is not None:
                not_reached = scale_in_reason(sizing, cand.underlying, cand.ideal.spot)
                if not_reached is not None:
                    reasons.append(not_reached)
                else:
                    # A lot above the zone on a name-level bottoming signal: its guards apply
                    # (delta cap, one signal lot per name per N sessions).
                    guard = bottoming_reason(sizing, cand)
                    if guard is not None:
                        reasons.append(guard)
            # At send time the fresh signals are gone, so the one-lot-per-name guard is read from
            # the tag frozen on the card against the lots recorded when sent. It does not need the
            # card's `ideal`: it is a count of orders, not a price judgement.
            recent = bottoming_send_reason(sizing, cand)
            if recent is not None:
                reasons.append(recent)

        # --- The stacking rule (Task 25): a new put on a name with an in-the-money short or too many
        # sends today is blocked; one near an open short's expiry is halved. The halved size is
        # half the per-trade ceiling's base (the capital-fitted size on the card, up to the regime
        # ceiling), which the sizer's halving of its own smaller size can never exceed.
        if sizing is not None and cand.strategy == Strategy.CASH_SECURED_PUT:
            spot = cand.underlying_price or (cand.ideal.spot if cand.ideal is not None else None)
            stack = stacking_for(
                sizing, cand.underlying, expiry=cand.expiry, spot=spot, positions=positions
            )
            found_stack: str | None = None
            if stack == "block":
                found_stack = "stacking_block"
            elif stack == "halve":
                hard = int(limits.get("max_contracts", 10)) if limits else 10
                pre = cand.sizing.pre_regime_contracts if cand.sizing is not None else hard
                base = min(pre, per_trade_cap(sizing, cand.underlying, hard, cand.sizing))
                if cand.contracts > base // 2:
                    found_stack = "stacking_halve"
            if found_stack is not None:
                if switch_on(sizing, "stacking_rule"):
                    reasons.append(found_stack)
                else:
                    limits_would.setdefault(cand.candidate_id, []).append(found_stack)

        # --- Covered-call breakout (spec section 17): after an upside breakout on a held name
        # a call must sit at or above the strike floor and under the delta cap. A call is
        # pushed out (when nothing on the chain clears both, none is sold on the name that
        # scan); covered calls only (a roll or a put gets no reason), and not a regime limit
        # (`/regime off` leaves it on). At send time there is no fresh context: the copy
        # frozen on the candidate carries it.
        reasons.extend(cc_timing_reasons(sizing, cand))

        # --- Earnings blackout: no short premium that lives through (or just before) earnings.
        # A ROLL is judged only on whether its new expiry runs into earnings: the proximity
        # clause keeps NEW entries away from an announcement, but a roll that expires first
        # moves existing exposure off the event, not onto it (2026-10-11).
        if cand.next_earnings is not None:
            days_to_earnings = (cand.next_earnings - today).days
            near = 0 <= days_to_earnings <= blackout_days and not is_roll
            if cand.next_earnings <= cand.expiry or near:
                reasons.append("earnings_blackout")

        # --- Roll chain limits (config/settings.yaml → roll.limits; human-edited). A roll must
        # carry its origin — without it the executor cannot tell which short it closes.
        if is_roll:
            origin = cand.roll_from
            roll_limits = get_config().roll.limits
            if origin is None:
                reasons.append("roll_origin_missing")
            else:
                if origin.seq > roll_limits.max_rolls_per_chain:
                    reasons.append("roll_limit_reached")
                if (cand.expiry - origin.original_expiry).days > roll_limits.max_extension_days:
                    reasons.append("roll_extension_cap")
                # The roll's economics, re-checked here so all three gates (decision time, the
                # approval queue, send time) enforce the same RollCfg the generator used —
                # not just the generator and the executor (whole-branch review, 2026-10-11).
                roll_cfg = get_config().roll
                is_call = cand.right == OptionRight.CALL
                if origin.allow_debit and not is_call:
                    reasons.append("roll_debit_not_allowed")  # only a keep-shares call may pay
                floor = (
                    -roll_cfg.cc.max_debit
                    if origin.allow_debit and is_call
                    else roll_cfg.new_leg.min_net_credit
                )
                if cand.premium < floor - 1e-9:
                    reasons.append("roll_net_below_floor")
                if (cand.strike < origin.strike) if is_call else (cand.strike > origin.strike):
                    reasons.append("roll_strike_worse")
                if (
                    origin.itm_at_proposal
                    and not is_call
                    and not rolls_down_enough(origin.strike, cand.strike, cand.premium, roll_cfg)
                ):
                    reasons.append("roll_not_rolled_down")
                if cand.contracts != origin.contracts:
                    reasons.append("roll_contracts_mismatch")

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
    #
    # With a regime, a CSP is checked against the regime-SCALED caps first; when that fails, the
    # same checks run against the unscaled caps and, if they pass, the reasons become the single
    # `regime_budget` (the regime, not the book, said no). Budgets are always seeded and charged
    # against the unscaled caps. Names accepted so far are tracked per underlying, so in the
    # deep-dive (``dedupe_same_symbol=False``) the strikes of one name share one daily-count and
    # one floor slot instead of each using a slot.
    accepted_csp: dict[str, str] = {}  # underlying -> governing index, accepted CSPs this batch
    accepted_floor: dict[str, str] = {}  # underlying -> governing index, floor lots this batch
    accepted_signal_lot: set[str] = set()  # names that took a name-level signal lot this batch
    env_check = _EnvelopeCheck(envelope, candidates, representative_ids)
    sleeve_batch_usd = 0.0  # leveraged-weighted sleeve dollars accepted earlier in this batch
    sleeve_batch_lots = 0

    def _others(by_name: dict[str, str], index: str, underlying: str) -> int:
        return sum(1 for name, idx in by_name.items() if idx == index and name != underlying)

    for cand in candidates:
        if cand.candidate_id not in representative_ids:
            continue
        reasons = candidate_reasons[cand.candidate_id]
        sector = _sector_of(cand.underlying)
        is_csp = cand.strategy == Strategy.CASH_SECURED_PUT
        regime_active = sizing is not None and is_csp and active(sizing)

        lev = leverage_of(cand.underlying)
        check_caps = caps
        if regime_active:
            ticker_mult, book_mult = multipliers(sizing, cand.underlying)
            check_caps = scale_caps(caps, ticker=ticker_mult, book=book_mult)
        reasons.extend(_cumulative_reasons(cand, sector, check_caps, budgets, lev))
        # Reasons the regime rewrite and the guaranteed floor below may never replace or clear
        # (ruling P4; C1: on 2026-11-09 a floor lot cleared the gross cap this way). Appended
        # after them.
        hard_reasons: list[str] = []
        if vx.active and is_csp:
            # Spec §9.2: one name across both books, where the value book holds it.
            if vx.by_name.get(cand.underlying.upper(), 0.0) > 0 and (
                budgets.ticker_collateral.get(cand.underlying, 0.0) + cand.collateral > combined_cap
            ):
                hard_reasons.append("combined_name_cap")
        if is_csp:
            hard_reasons.extend(env_check.reasons(cand))
        # The tech-linked cap (Task 25): leverage-weighted tech-linked exposure, after this put,
        # against ``envelope.tech_cap_pct`` of net liquidation. The tally already carries the
        # positions, the value book's stock and every lot accepted earlier in this batch.
        if is_csp and sizing is not None:
            capped = tech_cap_reason(
                sizing,
                cand.underlying,
                tech_exposure=tech_exposure(sizing, budgets.ticker_collateral),
                new_weighted=cand.collateral * lev,
                net_liq=net_liq,
                cap_pct=get_envelope_cfg().tech_cap_pct,
            )
            if capped is not None:
                if switch_on(sizing, "tech_cap"):
                    hard_reasons.append(capped)
                else:
                    limits_would.setdefault(cand.candidate_id, []).append(capped)
        # The leveraged sleeve's pace and cap (Task 23): the LES tier's room, leverage-weighted with
        # everything else the sleeve holds and the lots accepted earlier in this batch, in whole lots.
        sleeve_p = sleeve_path(sizing, cand.underlying, cand.sizing) if is_csp else None
        if sleeve_p is not None:
            pace = sleeve_pace_reason(
                sizing, cand.underlying, positions, batch_lots=sleeve_batch_lots
            )
            if pace is not None:
                hard_reasons.append(pace)
            room_usd = sleeve_room_usd(
                sizing,
                cand.underlying,
                account,
                positions,
                extra_usd=sleeve_batch_usd,
                frozen=cand.sizing,
            )
            if cand.contracts > sleeve_contracts(room_usd, cand.strike, lev):
                hard_reasons.append("sleeve_cap")

        took_floor = False
        if regime_active:
            assert sizing is not None
            if reasons and not _cumulative_reasons(cand, sector, caps, budgets, lev):
                reasons = ["regime_budget"]
            index = governing_index(sizing, cand.underlying)
            limit = daily_limit(sizing, cand.underlying)
            if (
                limit is not None
                and sizing.csp_opens_counted.get(index, 0)
                + _others(accepted_csp, index, cand.underlying)
                >= limit
            ):
                reasons.append("regime_daily_limit")
            if reasons == ["regime_budget"]:
                batch_floor: dict[str, int] = {
                    idx: _others(accepted_floor, idx, cand.underlying) for idx in ("SPY", "QQQ")
                }
                if floor_left(sizing, cand.underlying, batch_floor) > 0:
                    reasons = []
                    took_floor = True
        reasons = reasons + hard_reasons

        # One name-level signal lot per name per batch at send time, in the batch's own order (the
        # first one passes). The send batch's per-name dedupe already leaves a single card per
        # name; this keeps the guard whole when it is off. Decision time is untouched: there the
        # fresh signal, not a tag on the card, says what a signal lot is.
        if (
            sizing is not None
            and sizing.for_send
            and is_csp
            and cand.sizing is not None
            and cand.sizing.bottoming == "name"
            and cand.underlying in accepted_signal_lot
        ):
            reasons.append("bottoming_lot_recent")

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
                leverage=lev,
            )
            if is_csp:
                env_check.accept(cand)
            if sleeve_p is not None:
                sleeve_batch_usd += cand.strike * 100.0 * cand.contracts * lev
                sleeve_batch_lots += 1
            if sizing is not None and is_csp:
                index = governing_index(sizing, cand.underlying)
                accepted_csp[cand.underlying] = index
                if took_floor:
                    accepted_floor[cand.underlying] = index
                note = cand.sizing or sizing_note(
                    sizing,
                    cand.underlying,
                    cand.contracts,
                    int(_strategy_limits(cand.strategy).get("max_contracts", 10)),
                )
                if note is not None:
                    # An in-place tag: the gate returns verdicts only, and the caller's candidate
                    # is what is sized, shown and frozen into the order snapshot. The name's
                    # scale-in zone travels with it: the send-time re-gate checks the live price
                    # against this frozen zone.
                    zone = note.scale_in or sizing.scale_in.get(cand.underlying)
                    spot = cand.ideal.spot if cand.ideal is not None else None
                    # The send-time context carries no signals (no bars): a tag the card already
                    # carries is kept, never erased.
                    tag = bottoming_tag(sizing, cand.underlying, spot) or note.bottoming
                    if tag == "name" and zone is not None:
                        # frozen into the snapshot so the send-time re-gate knows the signal
                        zone = zone.model_copy(update={"bottoming_signal": True})
                    cand.sizing = note.model_copy(
                        update={
                            "floor_lot": took_floor,
                            "scale_in": zone,
                            "bottoming": tag,
                            "vrp_waived": cand.candidate_id in vrp_waived_ids,
                        }
                    )
                    if sizing.for_send and tag == "name":
                        accepted_signal_lot.add(cand.underlying)

    return [
        RiskVerdict(
            candidate_id=cand.candidate_id,
            verdict=Verdict.PASS if not candidate_reasons[cand.candidate_id] else Verdict.REJECT,
            reasons=candidate_reasons[cand.candidate_id],
            envelope_would=env_check.would.get(cand.candidate_id, []),
            limits_would=limits_would.get(cand.candidate_id, []),
        )
        for cand in candidates
    ]


class _EnvelopeCheck:
    """The risk envelope inside one ``validate_candidates`` batch (risk-envelope Tasks 18-19).

    Holds the room and the book, applies ``enforce`` (``on`` refuses, ``record`` keeps the
    would-block reasons in ``would`` for the verdicts and admits, ``off`` does nothing) and adds
    each accepted lot to the book. With no envelope the ``envelope_enforce``
    switch is read once, and only when an opening CSP reaches the shared budgets: ``on`` refuses
    every such CSP ``envelope_unmeasured`` (fail closed); ``record`` and ``off`` have nothing to
    record or test.
    """

    def __init__(
        self,
        envelope: tuple[EnvelopeRoom, ShockInputs] | None,
        candidates: list[TradeCandidate],
        representative_ids: set[str],
    ) -> None:
        self.room: EnvelopeRoom | None = None
        self.inputs: ShockInputs | None = None
        self.mode = "off"
        self._found: dict[str, list[str]] = {}
        self.would: dict[str, list[str]] = {}  # record mode: what ``on`` would have refused
        has_csp = any(
            c.strategy == Strategy.CASH_SECURED_PUT and c.candidate_id in representative_ids
            for c in candidates
        )
        if envelope is not None:
            self.room, self.inputs = envelope
            self.mode = self.room.enforce
        elif has_csp:
            from src.storage.envelope_switches import enforce_mode

            self.mode = enforce_mode()

    def reasons(self, cand: TradeCandidate) -> list[str]:
        """The envelope reasons to append for *cand* (``on`` only)."""
        from src.engine.envelope import UNMEASURED, admits, candidate_line

        if self.mode == "off":
            return []
        if self.room is None or self.inputs is None:
            return [UNMEASURED] if self.mode == "on" else []
        found = admits(self.room, self.inputs, [candidate_line(cand)])
        self._found[cand.candidate_id] = found
        if self.mode == "on":
            return found
        if found:
            self.would[cand.candidate_id] = found
        return []

    def accept(self, cand: TradeCandidate) -> None:
        """An accepted lot joins the book for the rest of the batch. In ``record`` a lot the
        envelope would have refused is left out, so the record shows what ``on`` would do."""
        from src.engine.envelope import candidate_line, with_added

        if self.room is None or self.inputs is None or self._found.get(cand.candidate_id):
            return
        self.room, self.inputs = with_added(self.room, self.inputs, [candidate_line(cand)])


def validate_live_quote(
    candidate: TradeCandidate,
    quote: OptionQuote,
    *,
    sizing: SizingContext | None = None,
) -> RiskVerdict:
    """Second gate: re-check a single candidate against the FRESH live quote at send time.

    Catches the case the decision-time gate cannot see: the option drifted between the
    the scan and execution (e.g. went deep ITM → delta out of range, or the mid
    collapsed). Deterministic. Delta is only enforced when the live quote actually carries
    greeks — missing live greeks degrade to the (already-passed) decision-time gate rather
    than blocking the fill.

    *sizing* is the send-time context (`approval._send_context`); the send path passes it
    explicitly (rolls pass ``None``: they are never regime- or ladder-limited). For a
    cash-secured put it adds the scale-in ladder: ``loss_exit_cooldown`` when the name had a
    loss exit today (including since the card was made), and ``scale_in_zone_not_reached`` when
    the zone frozen into the card is now below the live underlying price (it bounced). For a
    covered call carrying a breakout it adds ``cc_breakout_delta`` when the LIVE delta is over
    the breakout's ``delta_max`` (the strike floor is a property of the card's strike and was
    held at decision time; the delta is what can drift). A cash-secured put whose card is tagged
    as a name-level bottoming signal lot (``sizing.bottoming == "name"``) gets
    ``bottoming_delta_too_high`` when the LIVE delta is over ``bottoming.signal_delta_max``,
    with or without *sizing*.
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

    # The covered-call breakout's delta cap against the LIVE delta (the breakout itself is the
    # copy frozen on the card; the send-time context has none). Not a regime limit: it applies
    # with or without a context.
    if candidate.strategy == Strategy.COVERED_CALL:
        drifted = live_cc_delta_reason(candidate, quote, sizing)
        if drifted is not None:
            reasons.append(drifted)

    # A name-level signal lot's delta cap (`bottoming.signal_delta_max`) against the LIVE delta,
    # read from the tag frozen on the card: it applies with or without a send-time context.
    signal_drift = live_bottoming_delta_reason(candidate, quote)
    if signal_drift is not None:
        reasons.append(signal_drift)

    if sizing is not None and candidate.strategy == Strategy.CASH_SECURED_PUT:
        cooldown = loss_exit_reason(sizing, candidate.underlying)
        if cooldown is not None:
            reasons.append(cooldown)
        not_reached = live_ladder_reason(candidate, quote, sizing)
        if not_reached is not None:
            reasons.append(not_reached)

    return RiskVerdict(
        candidate_id=candidate.candidate_id,
        verdict=Verdict.PASS if not reasons else Verdict.REJECT,
        reasons=reasons,
    )


def _short_calls(positions: list[PositionSnapshot], symbol: str) -> int:
    """The wheel's open short call contracts on *symbol* (each needs 100 shares under it)."""
    return sum(
        int(abs(p.position))
        for p in positions
        if p.sec_type == "OPT"
        and p.right == OptionRight.CALL
        and p.position < 0
        and (p.underlying or p.symbol).upper() == symbol.upper()
    )


def validate_stock_order(
    order: StockOrderIntent,
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    *,
    envelope: tuple[EnvelopeRoom, ShockInputs] | None,
    mid: float | None,
    attribution: Attribution | None,
    les_shares: float = 0.0,
) -> RiskVerdict:
    """The Rules Engine's gate for a stock order (risk-envelope Tasks 31, 32a; rulings P10, L5-L7).

    Deterministic, no LLM, no I/O but config. Run at decision time and again at send time on a
    fresh quote (*mid*), by ``src/execution/stock_orders.py`` and ``src/execution/les.py``.

    * ``les_paper_only``: an LES order in live, tapped or not (L7). ``stock_not_tapped``: a repair
      order without a human tap, at any autonomy level (P10).
    * ``no_shares``, ``reserved_for_spreads_book``, ``stock_no_quote`` (no positive *mid*).
    * A **sell** never crosses books. *attribution* is the name's ``books.attribute`` (broker, the
      wheel's ledger count W, the value book, the LES book): none means ``stock_book_unknown``
      (fail closed). A repair sell may take at most the wheel's own view less 100 shares per open
      short call (``stock_sell_not_wheel_shares`` above the view, so never a value or LES share;
      ``stock_sell_uncovers_call`` into the shares under a call). An LES sell may take at most the
      LES shares held (``stock_sell_not_les_shares``) and never the broker's shares that back the
      wheel's calls once the value book's are set aside (``stock_sell_uncovers_call``). A sell
      lowers risk, so the envelope never blocks one.
    * A **buy** must pass the envelope after it: *envelope* (the room and the book on live IV)
      ``admits`` the shares (``shock_budget``, ``gross_budget``, ``t20_budget``), whatever
      ``envelope_enforce`` reads; no envelope, or an unmeasured one, is ``envelope_unmeasured``.

    *account* is the account snapshot the order is gated against (a buy with no net liquidation
    is unmeasured through the envelope). An empty reason list passes.
    """
    from src.engine.envelope import UNMEASURED, admits

    sym = order.symbol.upper()
    reasons: list[str] = []
    if order.source == "les" and get_config().is_live:
        reasons.append("les_paper_only")
    if order.source == "repair" and not order.tapped:
        reasons.append("stock_not_tapped")
    if order.qty < 1:
        reasons.append("no_shares")
    if is_spreads_underlying(sym):
        reasons.append("reserved_for_spreads_book")
    if mid is None or not mid > 0:
        reasons.append("stock_no_quote")
    if order.side == "SELL":
        calls = _short_calls(positions, sym)
        if attribution is None:
            reasons.append("stock_book_unknown")
        elif order.source == "repair":
            if order.qty > attribution.wheel_view + 1e-9:
                reasons.append("stock_sell_not_wheel_shares")
            elif order.qty > attribution.wheel_view - 100.0 * calls + 1e-9:
                reasons.append("stock_sell_uncovers_call")
        else:
            if order.qty > les_shares + 1e-9:
                reasons.append("stock_sell_not_les_shares")
            elif order.qty > attribution.broker - attribution.value_filled - 100.0 * calls + 1e-9:
                reasons.append("stock_sell_uncovers_call")
    else:
        if envelope is None or not account.net_liquidation > 0 or mid is None or not mid > 0:
            reasons.append(UNMEASURED)
        else:
            room, inputs = envelope
            line = BookLine(
                symbol=sym, kind="stock", qty=float(order.qty), spot=mid, book=order.source
            )
            reasons.extend(admits(room, inputs, [line]))
    return RiskVerdict(
        candidate_id=f"{order.source}:{order.ref_id or sym}",
        verdict=Verdict.PASS if not reasons else Verdict.REJECT,
        reasons=reasons,
    )


HEDGE_QUOTE_MAX_AGE_SECONDS = 60.0  # "fresh" (§3.10.10 item 4): a leg quote at most this old


def _hedge_max_loss_per_share(legs: list[HedgeLeg], debit: float) -> float:
    """The structure's worst loss per share: its debit plus the worst payoff shortfall at expiry
    (checked at every strike and at zero). A long put or a debit put vertical loses its debit."""
    points = [0.0, *(leg.strike for leg in legs)]

    def payoff(s: float) -> float:
        total = 0.0
        for leg in legs:
            intrinsic = max(0.0, leg.strike - s) if leg.right == "P" else max(0.0, s - leg.strike)
            total += intrinsic if leg.action == "BUY" else -intrinsic
        return total

    return debit - min(payoff(s) for s in points)


def _hedge_structure_reasons(cand: HedgeCandidate) -> list[str]:
    reasons: list[str] = []
    longs = [leg for leg in cand.legs if leg.action == "BUY"]
    shorts = [leg for leg in cand.legs if leg.action == "SELL"]
    if any(leg.right != "P" for leg in cand.legs):
        reasons.append("hedge_not_a_put")
    if len(longs) != 1 or len(shorts) > 1:
        reasons.append("hedge_naked_short" if shorts and not longs else "hedge_structure")
    elif shorts:
        long, short = longs[0], shorts[0]
        if short.expiry != long.expiry or short.strike >= long.strike:
            reasons.append("hedge_naked_short")  # a diagonal or a short above the long
    if (cand.kind == "outright") != (not shorts):
        reasons.append("hedge_structure")
    return reasons


def validate_hedge(cand: HedgeCandidate, ctx: HedgeContext) -> RiskVerdict:
    """The Rules Engine's gate for a hedge order (risk-envelope Task 34; spec §3.10.10 item 4).

    Deterministic, no LLM, no I/O but config: run at decision time and again at send time on a
    fresh quote (``src/hedge/executor.py``). Nothing an LLM produces reaches it.

    Every order: ``hedge_paper_only`` in live (the hedge is paper only); ``hedge_claude_reserved``
    for a ``hedge:claude:`` ref (reserved for the Mastermind's paper put budget, refused by this
    build) and also ``hedge_claude_live`` under ``LIVE_TRADING=true``; ``hedge_bad_ref`` without a
    ``hedge:`` ref; ``hedge_underlying`` outside ``hedge.underlyings``; ``no_contracts``;
    ``hedge_quote_one_sided`` / ``hedge_quote_stale`` (two-sided and fresh, every leg);
    ``hedge_not_a_put`` / ``hedge_structure`` / ``hedge_naked_short`` (one long put, at most one
    short put of the same expiry below it, 1:1: no naked short leg).

    A **close** (a sale of what the book holds) lowers risk: beyond the above it is refused only
    ``hedge_close_exceeds_held`` (never more than the position, nor than IBKR holds).

    An **opening**: ``hedge_no_debit`` / ``hedge_max_loss`` (max loss = the debit); the H5 windows
    (``hedge_dte_window``, ``hedge_delta_window``); ``hedge_quote_wide`` (a leg wider than
    ``quote_max_spread_pct`` of mid); the clash rules (``hedge_contract_clash`` in a contract any
    other book holds; ``hedge_qqq_route`` while another book holds a share or a short option on the
    instrument); the H3 budget (``hedge_budget_net``, ``hedge_budget_pace``, ``hedge_budget_open``;
    ``hedge_budget_unmeasured`` with no NLV0 or an unreadable book); ``hedge_delta_cap`` (the
    hedge's beta-weighted delta above ``max_hedge_delta_share`` of the book's;
    ``hedge_book_delta_unmeasured`` when either is unknown); and, unless it is a self-funding roll
    (net debit <= 0, no added contracts), the stress block (``hedge_stress_block``, or
    ``hedge_stress_unmeasured`` with no VIX close), ``hedge_halted`` and ``hedge_slow_breaker``.

    Scoped out of the income gates (ROC, yield, IV rank, IV/RV, ``min_credit``) as rolls are: a
    hedge pays premium. No hedge creates envelope headroom (H1, H10): nothing here or in the
    envelope credits one.
    """
    cfg = get_hedge_cfg()
    reasons: list[str] = []
    ref = cand.order_ref or ""
    if ctx.is_live:
        reasons.append("hedge_paper_only")
    if ref.startswith(HEDGE_CLAUDE_PREFIX):
        reasons.append("hedge_claude_reserved")
        if ctx.is_live:
            reasons.append("hedge_claude_live")
    elif not ref.startswith(HEDGE_ORDER_PREFIX):
        reasons.append("hedge_bad_ref")
    inst = cand.instrument.upper()
    if inst not in cfg.underlyings:
        reasons.append("hedge_underlying")
    if cand.contracts < 1:
        reasons.append("no_contracts")
    reasons += _hedge_structure_reasons(cand)
    for leg in cand.legs:
        if leg.mid is None:
            reasons.append("hedge_quote_one_sided")
            break
    for leg in cand.legs:
        age = (ctx.now - leg.quoted_at).total_seconds() if leg.quoted_at is not None else None
        if age is None or age > HEDGE_QUOTE_MAX_AGE_SECONDS or age < -HEDGE_QUOTE_MAX_AGE_SECONDS:
            reasons.append("hedge_quote_stale")
            break

    if cand.intent == "close":
        held = ctx.held_contracts.get(cand.closes or "", 0.0)
        if cand.closes is None or cand.contracts > held + 1e-9:
            reasons.append("hedge_close_exceeds_held")
        return _hedge_verdict(cand, reasons)

    if not cand.debit > 0:
        reasons.append("hedge_no_debit")
    elif _hedge_max_loss_per_share(cand.legs, cand.debit) > cand.debit + 1e-6 or abs(
        cand.max_loss - cand.cost
    ) > 0.01 * max(1.0, cand.cost):
        reasons.append("hedge_max_loss")
    lo, hi = cfg.dte_window
    if cand.dte is None or not max(lo, cfg.dte_floor) <= cand.dte <= hi:
        reasons.append("hedge_dte_window")
    long = cand.long_leg
    dlo, dhi = cfg.long_delta
    ld = abs(long.delta) if long is not None and long.delta is not None else None
    if ld is None or not (max(dlo, 0.15) - 1e-9 <= ld <= dhi + 1e-9):
        reasons.append("hedge_delta_window")
    for leg in cand.legs:
        m = leg.mid
        if m is not None and leg.ask is not None and leg.bid is not None:
            if (leg.ask - leg.bid) / m * 100.0 > cfg.quote_max_spread_pct + 1e-9:
                reasons.append("hedge_quote_wide")
                break
    clash_ids = set(ctx.other_books_con_ids)
    clash_keys = {(u.upper(), r, round(float(k), 4), e) for u, r, k, e in ctx.other_books_contracts}
    if any(
        (leg.con_id is not None and leg.con_id in clash_ids) or leg.key(inst) in clash_keys
        for leg in cand.legs
    ):
        reasons.append("hedge_contract_clash")
    if inst in {n.upper() for n in ctx.wheel_underlyings}:
        reasons.append("hedge_qqq_route")

    if not ctx.nlv0 > 0 or not ctx.hedge_book_readable:
        reasons.append("hedge_budget_unmeasured")
    else:
        net_cap, pace_cap, open_cap = cfg.budget.caps(ctx.nlv0, ctx.months_elapsed)
        after = ctx.net_premium_spent + cand.cost
        if after > net_cap + 1e-6:
            reasons.append("hedge_budget_net")
        if after > pace_cap + 1e-6:
            reasons.append("hedge_budget_pace")
        if ctx.open_premium_at_cost + cand.cost > open_cap + 1e-6:
            reasons.append("hedge_budget_open")

    per_contract: float | None = None
    if long is not None and cand.spot and ctx.instrument_beta is not None:
        signed = [
            (leg.delta if leg.action == "BUY" else -leg.delta)
            for leg in cand.legs
            if leg.delta is not None
        ]
        if len(signed) == len(cand.legs):
            per_contract = sum(signed) * cand.multiplier * cand.spot * ctx.instrument_beta
    if ctx.book_beta_delta is None or not ctx.book_beta_delta > 0 or per_contract is None:
        reasons.append("hedge_book_delta_unmeasured")
    elif (
        abs(min(0.0, ctx.hedge_beta_delta) + min(0.0, per_contract * cand.contracts))
        > cfg.max_hedge_delta_share * ctx.book_beta_delta + 1e-6
    ):
        reasons.append("hedge_delta_cap")

    if not cand.self_funding_roll:
        s = cfg.stress
        if ctx.vix_close is None or ctx.vxn_close is None or ctx.vxn_p90 is None:
            # fewer than 126 stored ^VXN closes (no p90) is unmeasured, never "calm": no new size
            reasons.append("hedge_stress_unmeasured")
        elif ctx.vix_close >= s.vix_close or ctx.vxn_close >= ctx.vxn_p90:
            reasons.append("hedge_stress_block")
        if ctx.halted:
            reasons.append("hedge_halted")
        if ctx.slow_breaker_tripped:
            reasons.append("hedge_slow_breaker")
    return _hedge_verdict(cand, reasons)


def _hedge_verdict(cand: HedgeCandidate, reasons: list[str]) -> RiskVerdict:
    return RiskVerdict(
        candidate_id=cand.order_ref or cand.hedge_id,
        verdict=Verdict.PASS if not reasons else Verdict.REJECT,
        reasons=list(dict.fromkeys(reasons)),
    )


def validate_release(
    c: ReleaseCandidate,
    *,
    right: OptionRight | None,
    closes_today: int,
    released_today: float,
    net_liq: float,
) -> list[str]:
    """The Rules Engine's gate for a capital-release close (value book spec revision 4): a wheel
    cash-secured put bought back at breakeven or better to fund an approved value buy.
    Deterministic, no LLM. Run at decision time and again at send time on a fresh quote
    (``src/execution/capital_release.py``); an empty list passes. Only a put frees cash, so a
    call is refused; so is a spreads-book contract (the wheel never touches one)."""
    release = get_config().value.book.release.model_dump()
    reasons: list[str] = []
    if get_config().is_live:  # the value book is paper only (Part 5): never a live close
        reasons.append("release_not_paper")
    if right != OptionRight.PUT:
        reasons.append("release_not_csp")
    if is_spreads_underlying(c.underlying):
        reasons.append("reserved_for_spreads_book")
    if c.contracts < 1:
        reasons.append("no_contracts")
    reasons += release_reasons(
        c, release, closes_today=closes_today, released_today=released_today, net_liq=net_liq
    )
    return reasons
