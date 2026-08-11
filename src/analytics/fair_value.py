"""Where a short option *ought* to be written, and for how much.

The chain tells you which strikes exist and the delta filter tells you which are admissible.
Neither tells you which one you actually want, nor what the contract is worth. This module
answers both, deterministically:

  * **strike zone** — an expected-move band, snapped to the symbol's own support/resistance
    and trend levels, widened for earnings and quality risk, floored at cost basis for a
    covered call.
  * **min_credit** — Black-Scholes fair value priced at *realised* vol (HV30) plus a required
    edge, floored by the configured ROC/yield gates. Below it you are selling variance for
    free; the whole premium-selling thesis is that IV exceeds RV.
  * **action_price / buy_below** — the underlying level that makes the write attractive, and
    the level at which acquiring shares is sensible.

**Tier: deterministic.** ``zone_fit`` can optionally feed ``technical_score``, so this module
may read technicals, IV, fundamentals and Black-Scholes — and nothing else. It must never
import ``sentiment``, ``sector_context``, ``market_conditions`` or anything under
``src.claude``: those are enrichment-tier and may not influence ranking. Asserted by
``tests/test_eval_skills.py``.

**Never a gate.** The Rules Engine (``engine/risk_engine.py``) remains the sole path to an
order. Nothing here rejects a candidate; it only describes and (optionally) ranks.

Fail-soft throughout: every input is optional, every field degrades to ``None`` independently,
and ``IdealZone.confidence`` reports how much of the derivation actually had data.
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta

from src.analytics.black_scholes import bs_price
from src.common.config import get_config
from src.common.market_hours import today_et
from src.common.schemas import (
    FundamentalStats,
    IdealZone,
    IVStats,
    OptionRight,
    TechnicalStats,
)

log = logging.getLogger(__name__)

# Fallbacks used when the `ideal_zone:` block is absent from risk_limits.yaml.
_DEFAULTS: dict[str, float] = {
    # Calibrated against the traded delta bands, not picked by feel: a 0.15-0.30 delta put
    # sits at ~0.34-0.93 expected moves and a 0.20-0.35 delta call at ~0.48-1.17, measured
    # with Black-Scholes across the spot/IV/DTE range this universe spans. See the derivation
    # note in risk_limits.yaml. Getting this wrong is not cosmetic — a band placed outside the
    # range actually screened would report every real candidate as "outside the ideal zone".
    "em_lo_mult": 0.30,
    "em_hi_mult": 1.20,
    "earnings_widen_mult": 0.25,
    "support_pull_pct": 3.0,
    "min_credit_edge_pct": 10.0,
    "buy_margin_of_safety_pct": 8.0,
}


def compute_ideal_zone(
    *,
    symbol: str,
    right: OptionRight,
    dte: int,
    spot: float,
    tech: TechnicalStats,
    iv: IVStats,
    fund: FundamentalStats,
    cost_basis: float | None = None,
    today: date | None = None,
) -> IdealZone:
    """Return the ideal strike band, credit floor and action levels for a short *right*.

    Args:
        symbol: Underlying ticker (carried through for display).
        right: ``CALL`` for a covered call, ``PUT`` for a cash-secured put.
        dte: Days to expiration of the contract being considered.
        spot: Underlying price at scan time.
        tech / iv / fund: The per-symbol analytics triple already computed by every scan.
        cost_basis: Average share cost, covered calls only. Clamps the band at
            ``cost_basis × min_strike_vs_basis`` so the zone never advises writing below basis.
        today: Injectable for deterministic tests; defaults to the ET trading date.

    Never raises — a degenerate input yields an ``IdealZone`` with ``confidence="low"`` and
    ``None`` fields rather than an exception.
    """
    zone = IdealZone(symbol=symbol, right=right, dte=dte, spot=spot)
    try:
        return _compute(zone, right, dte, spot, tech, iv, fund, cost_basis, today or today_et())
    except Exception:  # pragma: no cover - defensive; analytics must never break a scan
        log.warning("compute_ideal_zone: failed for %s — returning empty zone", symbol)
        return zone


def zone_for_contract(
    zone: IdealZone, strike: float, iv: IVStats, *, cost_basis: float | None = None
) -> IdealZone:
    """Return *zone* with its credit floor repriced at the strike actually on offer.

    ``compute_ideal_zone`` prices ``min_credit`` at the band's *anchor* strike, which is the
    right number for the abstract zone ("what is a contract in this band worth?") but the
    wrong one to compare a specific contract's premium against: option value falls steeply
    with moneyness, so a call further OTM than the anchor is cheaper for entirely correct
    reasons. Comparing it to the anchor's floor labelled it "below fair value" while it was
    in fact trading at a multiple of its own — a $250C at $2.31 against a $1.13 floor.

    The band, the anchors and the underlying levels are strike-independent and carried over
    unchanged; only ``min_credit``/``credit_anchors`` are re-derived. Cheap enough to call
    per candidate — the expensive part of the zone is the band, which is cached per DTE by
    the strategy generators.

    *cost_basis* is the covered-call share basis, forwarded so the ROC/yield component of the
    floor divides by the same denominator the CC gate does (see ``min_credit_for``). Omit it
    for a CSP, whose ROC is measured against the strike.
    """
    roc_basis = cost_basis if zone.right == OptionRight.CALL else strike
    min_credit, anchors = min_credit_for(zone.spot, strike, zone.dte, iv, zone.right, roc_basis)
    return zone.model_copy(update={"min_credit": min_credit, "credit_anchors": anchors})


# --------------------------------------------------------------------------- #
# Derivation
# --------------------------------------------------------------------------- #


def _compute(
    zone: IdealZone,
    right: OptionRight,
    dte: int,
    spot: float,
    tech: TechnicalStats,
    iv: IVStats,
    fund: FundamentalStats,
    cost_basis: float | None,
    today: date,
) -> IdealZone:
    cfg = _zone_cfg()
    is_call = right == OptionRight.CALL
    inputs_present = 0

    # 1. Expected move — the unit everything else is expressed in.
    vol_pct = _first_positive(iv.current_iv, iv.hv_30)
    if spot <= 0 or dte <= 0 or vol_pct is None:
        return zone  # nothing derivable without a spot, a horizon and a vol
    em = spot * (vol_pct / 100.0) * math.sqrt(dte / 365.0)
    zone.expected_move = round(em, 2)
    inputs_present += 1

    # 2. Base band, in expected moves either side of spot.
    lo_mult, hi_mult = cfg["em_lo_mult"], cfg["em_hi_mult"]
    if is_call:
        lo, hi = spot + em * lo_mult, spot + em * hi_mult
    else:
        lo, hi = spot - em * hi_mult, spot - em * lo_mult
    anchors = [f"{vol_pct:.0f}% vol → 1σ ±${em:.2f} over {dte}d"]

    # 3. Snap toward the symbol's own structure. This is the first consumer of
    #    TechnicalStats.support_levels / resistance_levels, which until now were computed on
    #    every scan and read by nothing.
    levels = tech.resistance_levels if is_call else tech.support_levels
    relevant = [lv for lv in levels if (lv > spot if is_call else lv < spot)]
    snapped = _snap_to_level(lo, hi, relevant, cfg["support_pull_pct"])
    if snapped is not None:
        lo, hi, level = snapped
        anchors.append(f"{'resistance' if is_call else 'support'} ${level:.2f}")
        inputs_present += 1
        # Snapping translates the band to land on the level, which can drag the *inner* edge
        # through spot: AAPL at 232.40 with resistance at 248.10 produced a 232.54 floor — a
        # 0.53-delta covered call rendering as "✓ in zone". Moneyness is non-linear, so a
        # translation that preserves dollar width does not preserve the delta profile the
        # width is meant to encode. Clamp the inner edge back to the base cushion and let the
        # band stretch to reach the level instead.
        if is_call:
            lo = max(lo, spot + em * lo_mult)
            hi = max(hi, lo)
        else:
            hi = min(hi, spot - em * lo_mult)
            lo = min(lo, hi)

    # 4. Earnings / quality adjustments — push further OTM when the tail is fatter.
    if _event_inside(fund.next_earnings, today, dte):
        widen = em * cfg["earnings_widen_mult"]
        lo, hi = (lo + widen, hi + widen) if is_call else (lo - widen, hi - widen)
        anchors.append(f"earnings {fund.next_earnings:%b %d} inside DTE → +{widen:.2f} cushion")
    if not is_call and fund.quality_flag is False:
        widen = em * cfg["earnings_widen_mult"]
        lo, hi = lo - widen, hi - widen
        anchors.append("fails quality screen → deeper OTM")
    # A covered call written below the next ex-dividend invites early assignment for the
    # dividend; nudge the band up so the shares are less likely to be called before it.
    if is_call and _event_inside(fund.ex_dividend_date, today, dte):
        lo = max(lo, spot + em)
        hi = max(hi, lo)
        anchors.append(f"ex-div {fund.ex_dividend_date:%b %d} inside DTE → keep further OTM")

    # 5. Cost-basis floor (covered calls only) — reuses the existing min_strike_vs_basis policy
    #    rather than inventing a second one.
    if is_call and cost_basis is not None and cost_basis > 0:
        basis_floor = cost_basis * _min_strike_vs_basis()
        if lo < basis_floor:
            lo = basis_floor
            hi = max(hi, basis_floor)
            anchors.append(f"floored at basis ${basis_floor:.2f}")

    zone.strike_lo = round(lo, 2)
    zone.strike_hi = round(hi, 2)

    # 6. Anchor within the band: prefer a trend level sitting inside it, else the midpoint.
    anchor = (lo + hi) / 2
    for label, sma in (("50d SMA", tech.sma_50), ("200d SMA", tech.sma_200)):
        if sma is not None and lo <= sma <= hi:
            anchor = sma
            anchors.append(f"anchored to {label} ${sma:.2f}")
            inputs_present += 1
            break
    zone.strike_anchor = round(anchor, 2)
    zone.strike_anchors = anchors

    # 7. Credit floor for the band as a whole, priced at the anchor strike. Callers holding a
    #    specific contract should re-price it with `zone_for_contract` — comparing an offered
    #    premium against the anchor's floor mislabels every strike away from the anchor.
    zone.min_credit, zone.credit_anchors = min_credit_for(
        spot, anchor, dte, iv, right, cost_basis if is_call else anchor
    )
    if zone.min_credit is not None:
        inputs_present += 1

    # 8. Underlying levels.
    zone.action_price, zone.action_note = _action_level(
        spot, anchor, em, is_call, (lo_mult + hi_mult) / 2
    )
    zone.buy_below, zone.buy_anchors = _buy_below(spot, tech, fund, cfg)
    if zone.buy_below is not None:
        inputs_present += 1

    zone.confidence = "high" if inputs_present >= 4 else "medium" if inputs_present >= 2 else "low"
    return zone


def min_credit_for(
    spot: float,
    strike: float,
    dte: int,
    iv: IVStats,
    right: OptionRight,
    roc_basis: float | None = None,
) -> tuple[float | None, list[str]]:
    """Least credit per share worth accepting at *strike*.

    Fair value is Black-Scholes priced at **realised** vol (HV30), not implied: that is the
    price at which the trade carries no variance-risk premium. The floor is that plus a
    required edge, and never below what the configured ROC / annualized-yield gates demand —
    so the number is always at least as strict as the gate the candidate must clear anyway.

    *roc_basis* is the denominator the ROC/yield gates actually divide by, and it differs by
    strategy: a CSP's ROC is ``premium/strike`` but a covered call's is ``premium/avg_cost``
    (see the generators). Defaulting it to *strike* — as this did for both — inflated the CC
    floor whenever the strike sat above the basis, which is the normal case for a covered
    call, and made the floor *rise* with strike while fair value fell.
    """
    anchors: list[str] = []
    risk = get_config().risk
    edge = 1.0 + _num(_zone_cfg()["min_credit_edge_pct"]) / 100.0
    basis = roc_basis if roc_basis is not None and roc_basis > 0 else strike

    floors: list[float] = []
    hv = iv.hv_30
    if hv is not None and hv > 0 and strike > 0:
        fair = bs_price(spot, strike, dte, hv / 100.0, right.value)
        if fair is not None and fair > 0:
            floors.append(fair * edge)
            anchors.append(f"fair value ${fair:.2f} at HV30 {hv:.0f}% +{(edge - 1) * 100:.0f}%")

    income = risk.get("income", {})
    min_roc = _num(income.get("min_roc_pct"))
    min_yield = _num(income.get("min_annualized_yield_pct"))
    if min_roc and basis > 0:
        floors.append(basis * min_roc / 100.0)
    if min_yield and basis > 0 and dte > 0:
        floors.append(basis * (min_yield / 100.0) * (dte / 365.0))
    if min_roc or min_yield:
        anchors.append(f"ROC/yield gates ({min_roc:.1f}% / {min_yield:.0f}% ann.)")

    if not floors:
        return None, anchors
    return round(max(floors), 2), anchors


def _action_level(
    spot: float, anchor: float, em: float, is_call: bool, mid_mult: float
) -> tuple[float | None, str | None]:
    """The underlying level at which *anchor* would sit mid-band.

    Measured with the **midpoint of the configured band** (``mid_mult``), not a hard 1σ: the
    band spans 0.30-1.20σ, so demanding a full expected move of cushion would flag perfectly
    well-placed contracts as needing a better entry. When spot already gives at least that
    cushion the note says so rather than implying you should wait.
    """
    if em <= 0 or mid_mult <= 0:
        return None, None
    level = anchor + em * mid_mult if not is_call else anchor - em * mid_mult
    if level <= 0:
        return None, None
    satisfied = spot >= level if not is_call else spot <= level
    gap_pct = abs(spot - level) / level * 100.0
    side = "≤" if is_call else "≥"
    kind = "call" if is_call else "put"
    state = (
        "cushion already met"
        if satisfied
        else f"spot is {gap_pct:.1f}% the wrong side — less cushion than the zone assumes"
    )
    note = f"spot {side} ${level:.2f} puts the ${anchor:.2f} {kind} mid-band ({state})"
    return round(level, 2), note


def _buy_below(
    spot: float, tech: TechnicalStats, fund: FundamentalStats, cfg: dict[str, float]
) -> tuple[float | None, list[str]]:
    """Share-acquisition level: the **nearest** value anchor below spot, not the deepest.

    Deliberately the highest qualifying level rather than the lowest. Taking the minimum
    produces a technically-conservative number that is often 25-30% below spot (the lower
    quartile of a 52-week range usually wins), which is not a level anyone acts on. The
    nearest anchor is where the name first goes on sale by its own structure; the deeper
    levels stay visible in the returned anchor list, ordered nearest-first.
    """
    candidates: list[tuple[float, str]] = []
    supports = [lv for lv in tech.support_levels if 0 < lv < spot]
    if supports:
        level = max(supports)  # nearest support below spot
        candidates.append((level, f"support ${level:.2f}"))
    if tech.sma_50 is not None and 0 < tech.sma_50 < spot:
        candidates.append((tech.sma_50, f"50d SMA ${tech.sma_50:.2f}"))
    if fund.target_mean_price is not None and fund.target_mean_price > 0:
        haircut = fund.target_mean_price * (1 - _num(cfg["buy_margin_of_safety_pct"]) / 100.0)
        candidates.append(
            (haircut, f"analyst mean ${fund.target_mean_price:.2f} less margin of safety")
        )
    if fund.fifty_two_week_low is not None and fund.fifty_two_week_high is not None:
        lo, hi = fund.fifty_two_week_low, fund.fifty_two_week_high
        if 0 < lo < hi:
            level = lo + (hi - lo) * 0.25  # lower quartile of the 52-week range
            candidates.append((level, f"lower quartile of 52w ${lo:.2f}–${hi:.2f}"))
    # An anchor at or above spot is meaningless as a "buy below" level — a discounted analyst
    # target on a beaten-down name, or the 52-week quartile on one trading near its low, can
    # both land above the current price. Drop them rather than advise buying at a premium.
    actionable = [(level, note) for level, note in candidates if 0 < level < spot]
    if not actionable:
        return None, []
    ordered = sorted(actionable, key=lambda c: c[0], reverse=True)  # nearest spot first
    return round(ordered[0][0], 2), [note for _, note in ordered]


# --------------------------------------------------------------------------- #
# Ranking hook (optional, default-off)
# --------------------------------------------------------------------------- #


def zone_fit_score(strike: float, zone: IdealZone | None) -> float | None:
    """0-100 for how well *strike* sits inside *zone*, or None when not derivable.

    100 inside the band, decaying with distance from the nearer edge measured in expected
    moves. Consumed by ``strategies/_scoring.technical_score`` under the ``zone_fit`` weight,
    which ships at 0.0 — so by default this changes no ranking at all.
    """
    if zone is None or zone.strike_lo is None or zone.strike_hi is None:
        return None
    if zone.expected_move is None or zone.expected_move <= 0:
        return None
    if zone.strike_lo <= strike <= zone.strike_hi:
        return 100.0
    distance = zone.strike_lo - strike if strike < zone.strike_lo else strike - zone.strike_hi
    # One full expected move outside the band scores 0.
    return round(max(0.0, 100.0 * (1.0 - distance / zone.expected_move)), 4)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _zone_cfg() -> dict[str, float]:
    raw = get_config().risk.get("ideal_zone", {}) or {}
    return {k: _num(raw.get(k, default)) for k, default in _DEFAULTS.items()}


def _min_strike_vs_basis() -> float:
    cc = get_config().risk.get("covered_call", {}) or {}
    return _num(cc.get("min_strike_vs_basis", 1.0))


def _num(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        f = float(value)  # type: ignore[arg-type]
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _first_positive(*values: float | None) -> float | None:
    for v in values:
        if v is not None and v > 0 and math.isfinite(v):
            return float(v)
    return None


def _event_inside(event: date | None, today: date, dte: int) -> bool:
    """True when *event* falls within the option's remaining life."""
    if event is None or dte <= 0:
        return False
    return today <= event <= today + timedelta(days=dte)


def _snap_to_level(
    lo: float, hi: float, levels: list[float], pull_pct: float
) -> tuple[float, float, float] | None:
    """Shift the band so its nearer edge lands on the closest level within *pull_pct*.

    Returns ``(lo, hi, level)`` when a level was close enough to snap to, else ``None``.
    The band keeps its width — it is translated, not stretched, so the delta profile the
    width encodes is preserved.
    """
    if not levels or lo <= 0:
        return None
    width = hi - lo
    best_gap = pull_pct
    best_lo: float | None = None
    best_level: float | None = None
    for level in levels:
        for edge, new_lo in ((lo, level), (hi, level - width)):
            if edge <= 0:
                continue
            gap_pct = abs(level - edge) / edge * 100.0
            if gap_pct <= best_gap:
                best_gap, best_lo, best_level = gap_pct, new_lo, level
    if best_lo is None or best_level is None:
        return None
    return best_lo, best_lo + width, best_level
