"""Python's fair value (spec §6.5): methods A, B, D and justified P/TBV. Pure: no I/O.

Every input comes from filed history. C (own-history percentile) needs ten years of
point-in-time prices and is absent until they exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from src.common.config import ValueValuationCfg
from src.value.schemas import MethodValue

_GROWTH_LO, _GROWTH_HI = -0.5, 1.0


@dataclass(frozen=True, slots=True)
class Dcf:
    value: float
    terminal_share: float  # present value of the terminal value / the whole


def dcf(base: float, growth: float, rate: float, terminal: float, years: int) -> Dcf | None:
    """Per-share DCF. Year 1 grows at *growth*, fading linearly to *terminal* in the last
    year; the terminal value is the last year's cash flow grown once at *terminal* and
    capitalised at (rate - terminal). None when rate <= terminal (spec §6.5's validator)."""
    if rate <= terminal or years < 2:
        return None
    cash, pv = base, 0.0
    for k in range(1, years + 1):
        g = growth + (terminal - growth) * (k - 1) / (years - 1)
        cash *= 1.0 + g
        pv += cash / (1.0 + rate) ** k
    pv_terminal = cash * (1.0 + terminal) / (rate - terminal) / (1.0 + rate) ** years
    total = pv + pv_terminal
    if total <= 0:
        return None
    return Dcf(value=total, terminal_share=pv_terminal / total)


def implied_growth(
    price: float, base: float, rate: float, terminal: float, years: int
) -> float | None:
    """The year-1 growth (fading to *terminal*) at which the DCF equals *price*. Bisection over
    -50%..100%; None when the base is not positive or the price needs more than 100%."""
    if base <= 0 or price <= 0:
        return None
    lo_v = dcf(base, _GROWTH_LO, rate, terminal, years)
    hi_v = dcf(base, _GROWTH_HI, rate, terminal, years)
    if lo_v is None or hi_v is None:
        return None
    if price <= lo_v.value:
        return _GROWTH_LO
    if price > hi_v.value:
        return None
    lo, hi = _GROWTH_LO, _GROWTH_HI
    for _ in range(80):
        mid = (lo + hi) / 2.0
        v = dcf(base, mid, rate, terminal, years)
        assert v is not None
        if v.value < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def method_a(base_ps: float | None, cfg: ValueValuationCfg) -> MethodValue:
    """Earnings power: normalised, SBC-adjusted FCF per share / (r - g_floor)."""
    inputs = {"fcf_ps": base_ps, "rate": cfg.discount_rate_deep, "g_floor": cfg.g_floor}
    if base_ps is None:
        return MethodValue(method="A", state="absent", detail="no normalised FCF", inputs=inputs)
    if base_ps <= 0:
        return MethodValue(
            method="A", state="absent", detail="normalised FCF not positive", inputs=inputs
        )
    return MethodValue(
        method="A",
        value=base_ps / (cfg.discount_rate_deep - cfg.g_floor),
        state="ok",
        inputs=inputs,
    )


def haircut_growth(realised: float, cfg: ValueValuationCfg) -> float:
    """B's growth: 0.7 x realised (capped at 15%); a negative realised rate is not haircut."""
    capped = min(realised, cfg.realised_cap_deep)
    return capped * cfg.reverse_dcf_haircut if capped > 0 else capped


def method_b(base_ps: float | None, realised: float | None, cfg: ValueValuationCfg) -> MethodValue:
    """The DCF at the haircut growth, r = 9%, fading to 2.5%. Unreliable (dropped) when the
    terminal value is above 75% of the whole."""
    inputs = {"fcf_ps": base_ps, "realised_growth": realised, "rate": cfg.discount_rate_deep}
    if base_ps is None or base_ps <= 0:
        return MethodValue(
            method="B", state="absent", detail="normalised FCF not positive", inputs=inputs
        )
    if realised is None:
        return MethodValue(
            method="B", state="absent", detail="no realised FCF/share growth", inputs=inputs
        )
    g = haircut_growth(realised, cfg)
    inputs["growth"] = g
    out = dcf(base_ps, g, cfg.discount_rate_deep, cfg.terminal_growth, cfg.dcf_years)
    if out is None:
        return MethodValue(
            method="B", state="unreliable", detail="rate at or below terminal growth", inputs=inputs
        )
    inputs["terminal_share"] = out.terminal_share
    if out.terminal_share > cfg.terminal_value_max_share:
        return MethodValue(
            method="B",
            value=out.value,
            state="unreliable",
            detail="terminal value above 75%",
            inputs=inputs,
        )
    return MethodValue(method="B", value=out.value, state="ok", inputs=inputs)


def method_d(base_ps: float | None, realised: float | None, cfg: ValueValuationCfg) -> MethodValue:
    """Growth DCF (quality growth only): FCF less half of SBC, per share, at the realised
    growth capped at 20%, r = 8%, fading to 2.5%."""
    inputs = {"fcf_ps": base_ps, "realised_growth": realised, "rate": cfg.discount_rate_growth}
    if base_ps is None or base_ps <= 0:
        return MethodValue(
            method="D", state="absent", detail="growth-normalised FCF not positive", inputs=inputs
        )
    if realised is None or realised <= 0:
        return MethodValue(
            method="D", state="absent", detail="no positive realised growth", inputs=inputs
        )
    g = min(realised, cfg.realised_cap_growth)
    inputs["growth"] = g
    out = dcf(base_ps, g, cfg.discount_rate_growth, cfg.terminal_growth, cfg.dcf_years)
    if out is None:
        return MethodValue(
            method="D", state="unreliable", detail="rate at or below terminal growth", inputs=inputs
        )
    inputs["terminal_share"] = out.terminal_share
    if out.terminal_share > cfg.terminal_value_max_share:
        return MethodValue(
            method="D",
            value=out.value,
            state="unreliable",
            detail="terminal value above 75%",
            inputs=inputs,
        )
    return MethodValue(method="D", value=out.value, state="ok", inputs=inputs)


def method_c() -> MethodValue:
    return MethodValue(
        method="C", state="absent", detail="needs ten years of point-in-time prices (spec §6.5)"
    )


def method_ptbv(
    rote_median: float | None, tbv_ps: float | None, cfg: ValueValuationCfg
) -> MethodValue:
    """Banks and insurers: justified P/TBV = (ROTE - g) / (r - g) x tangible book per share,
    with g the terminal growth rate and r the deep-value rate."""
    g, r = cfg.terminal_growth, cfg.discount_rate_deep
    inputs = {"rote_median": rote_median, "tbv_ps": tbv_ps, "rate": r, "growth": g}
    if rote_median is None or tbv_ps is None or tbv_ps <= 0:
        return MethodValue(
            method="PTBV", state="absent", detail="ROTE or tangible book missing", inputs=inputs
        )
    if rote_median <= g:
        return MethodValue(
            method="PTBV", state="absent", detail="ROTE at or below growth", inputs=inputs
        )
    return MethodValue(
        method="PTBV", value=(rote_median - g) / (r - g) * tbv_ps, state="ok", inputs=inputs
    )


def fair_value(methods: list[MethodValue], use: tuple[str, ...]) -> float | None:
    """The median of the listed methods that are ``ok`` (two present -> their mean)."""
    vals = [m.value for m in methods if m.method in use and m.state == "ok" and m.value is not None]
    return median(vals) if vals else None
