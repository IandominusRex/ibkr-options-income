"""Claude's fair value, computed by Python (spec §8.2). Pure: no I/O.

Claude never returns a fair value. It returns **drivers** (growth, terminal growth, discount
rate, normalised FCF margin; sustainable ROTE for banks and insurers), each held to a bound
Python derives from the company's own filed history. Python clamps every driver into its bound
(recording the clamp), runs the arithmetic, drops the result as ``unreliable`` when the terminal
value is more than 75% of the whole (the validator of spec §6.5), and caps it at
``clamp_multiple`` (1.5) x Python's own fair value for the list. The capped value is the one
that is used; the uncapped one is kept for the operator to read. Where Python has no fair value,
Claude's cannot be used either.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.common.config import ValueRulesCfg
from src.common.value_ai_types import DriverBounds, Drivers, Range
from src.value.schemas import ValueScorecard
from src.value.valuation import Dcf

_FINANCIAL = ("bank", "insurer")
HOLD_YEARS = 5  # Claude's growth holds for years 1-5, then fades to terminal by year 10


@dataclass(frozen=True, slots=True)
class ClaudeValue:
    """One list's Claude fair value. ``fair_value`` is the usable (capped) number, None when
    the drivers were unusable (``unreliable`` says why)."""

    fair_value: float | None
    uncapped: float | None = None
    python_fair_value: float | None = None
    clamp_bound: bool = False  # the 1.5x cap set the value (the breaker counts these)
    unreliable: str | None = None
    clamps: list[str] = field(default_factory=list)  # each driver moved into its bound
    drivers: Drivers = field(default_factory=Drivers)  # after clamping
    terminal_share: float | None = None


def bounds_for(card: ValueScorecard, list_name: str, rules: ValueRulesCfg) -> DriverBounds | None:
    """The bounds for one list (spec §8.2's table), or None when the history needed to set them
    is missing (then Claude's drivers cannot be used for that list)."""
    if card.lists.get(list_name) is None:
        return None
    c, v = rules.claude, rules.valuation
    floor = v.discount_rate_deep if list_name == "deep_value" else v.discount_rate_growth
    terminal = Range(lo=c.terminal_min, hi=c.terminal_max)
    discount = Range(lo=floor, hi=c.discount_max)
    m = card.metrics
    if card.company_class in _FINANCIAL:
        rote = m.get("rote_median_5y")
        if rote is None or m.get("tbv_ps") is None:
            return None
        band = c.rote_band_pts / 100.0
        return DriverBounds(
            list_name=list_name,
            method="ptbv",
            terminal=terminal,
            discount=discount,
            rote=Range(lo=rote - band, hi=rote + band),
        )
    prefix = "fcf" if list_name == "deep_value" else "gfcf"
    median, best = m.get(f"{prefix}_margin_median_5y"), m.get(f"{prefix}_margin_best_5y")
    if median is None or best is None or m.get("revenue_ps_ttm") is None:
        return None
    band = c.margin_band_pts / 100.0
    realised = card.realised_fcf_ps_cagr if card.realised_fcf_ps_cagr is not None else 0.0
    growth_hi = max(c.growth_floor, min(c.growth_cap, realised + c.growth_over_realised))
    return DriverBounds(
        list_name=list_name,
        method="dcf",
        growth=Range(lo=c.growth_floor, hi=growth_hi),
        terminal=terminal,
        discount=discount,
        margin=Range(lo=median - band, hi=min(median + band, best)),
    )


def clamp_drivers(drivers: Drivers, bounds: DriverBounds) -> tuple[Drivers | None, list[str]]:
    """Each driver the method needs, moved into its bound; None when one is missing (a
    malformed driver set means no Claude fair value, never a guess)."""
    names = (
        ("rote", "terminal", "discount")
        if bounds.method == "ptbv"
        else ("growth", "terminal", "discount", "margin")
    )
    out: dict[str, float] = {}
    clamps: list[str] = []
    for name in names:
        value = getattr(drivers, name)
        bound: Range | None = getattr(bounds, name)
        if value is None or bound is None:
            return None, clamps
        kept = min(max(value, bound.lo), bound.hi)
        if kept != value:
            clamps.append(f"{name} {value:.4f} -> {kept:.4f}")
        out[name] = kept
    return Drivers(**out), clamps


def two_stage_dcf(
    base: float, growth: float, rate: float, terminal: float, years: int = 10
) -> Dcf | None:
    """Per-share DCF: *growth* for years 1-5, then fading linearly to *terminal* by the last
    year; the terminal value is the last year's cash flow grown once at *terminal* and
    capitalised at (rate - terminal). None when rate <= terminal or the total is not
    positive."""
    if rate <= terminal or years <= HOLD_YEARS:
        return None
    cash, pv = base, 0.0
    for k in range(1, years + 1):
        g = (
            growth
            if k <= HOLD_YEARS
            else growth + (terminal - growth) * (k - HOLD_YEARS) / (years - HOLD_YEARS)
        )
        cash *= 1.0 + g
        pv += cash / (1.0 + rate) ** k
    pv_terminal = cash * (1.0 + terminal) / (rate - terminal) / (1.0 + rate) ** years
    total = pv + pv_terminal
    if total <= 0:
        return None
    return Dcf(value=total, terminal_share=pv_terminal / total)


def claude_fair_value(
    card: ValueScorecard, list_name: str, drivers: Drivers, rules: ValueRulesCfg
) -> ClaudeValue:
    """Spec §8.2: bound, compute, validate and clamp. Lowering is never capped."""
    ev = card.lists.get(list_name)
    python_fv = ev.fair_value if ev is not None else None
    if python_fv is None:
        return ClaudeValue(None, unreliable="Python has no fair value for this list")
    bounds = bounds_for(card, list_name, rules)
    if bounds is None:
        return ClaudeValue(None, python_fair_value=python_fv, unreliable="no history to bound")
    kept, clamps = clamp_drivers(drivers, bounds)
    if kept is None:
        return ClaudeValue(None, python_fair_value=python_fv, unreliable="a driver is missing")
    terminal_share: float | None = None
    if bounds.method == "ptbv":
        assert kept.rote is not None and kept.terminal is not None and kept.discount is not None
        tbv = card.metrics.get("tbv_ps")
        assert tbv is not None  # bounds_for refused a name without it
        if kept.rote <= kept.terminal or tbv <= 0:
            return ClaudeValue(
                None,
                python_fair_value=python_fv,
                unreliable="ROTE at or below growth",
                clamps=clamps,
                drivers=kept,
            )
        uncapped = (kept.rote - kept.terminal) / (kept.discount - kept.terminal) * tbv
    else:
        assert kept.margin is not None and kept.growth is not None
        assert kept.terminal is not None and kept.discount is not None
        revenue_ps = card.metrics.get("revenue_ps_ttm")
        assert revenue_ps is not None  # bounds_for refused a name without it
        base = kept.margin * revenue_ps
        out = (
            None
            if base <= 0
            else two_stage_dcf(
                base, kept.growth, kept.discount, kept.terminal, rules.valuation.dcf_years
            )
        )
        if out is None:
            return ClaudeValue(
                None,
                python_fair_value=python_fv,
                unreliable="the cash flow is not positive",
                clamps=clamps,
                drivers=kept,
            )
        terminal_share = out.terminal_share
        if terminal_share > rules.valuation.terminal_value_max_share:
            return ClaudeValue(
                None,
                uncapped=out.value,
                python_fair_value=python_fv,
                unreliable="terminal value above 75% of the whole",
                clamps=clamps,
                drivers=kept,
                terminal_share=terminal_share,
            )
        uncapped = out.value
    cap = rules.claude.clamp_multiple * python_fv
    return ClaudeValue(
        fair_value=min(uncapped, cap),
        uncapped=uncapped,
        python_fair_value=python_fv,
        clamp_bound=uncapped > cap,
        clamps=clamps,
        drivers=kept,
        terminal_share=terminal_share,
    )
