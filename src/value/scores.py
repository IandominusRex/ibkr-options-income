"""Piotroski F-score, Altman Z and Beneish M (spec §6.4). Pure: no I/O.

Each takes fiscal years newest first (``src.value.metrics.Year``) and returns the score plus
what it could not compute, so a gate can say UNKNOWN instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.value.metrics import Year


@dataclass(slots=True)
class Score:
    value: float | None
    parts: dict[str, float | None] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def piotroski(years: list[Year], max_missing: int = 2) -> Score:
    """The nine-point F-score for the newest year against the one before.

    Return on assets uses beginning-of-year assets, so three years are needed. A component
    whose inputs are missing scores 0 and is listed; more than *max_missing* missing makes the
    score None. Leverage counts as improved when long-term debt / assets fell, or when the
    company carried none in either year (a debt-free company is not penalised)."""
    if len(years) < 3:
        return Score(None, missing=["fewer than three fiscal years"])
    t, p, pp = years[0], years[1], years[2]
    parts: dict[str, float | None] = {}
    missing: list[str] = []

    def point(name: str, ok: bool | None) -> None:
        if ok is None:
            missing.append(name)
            parts[name] = None
        else:
            parts[name] = 1.0 if ok else 0.0

    roa_t = _div(t.net_income, p.total_assets)
    roa_p = _div(p.net_income, pp.total_assets)
    point("roa_positive", None if roa_t is None else roa_t > 0)
    point("ocf_positive", None if t.ocf is None else t.ocf > 0)
    point("roa_improved", None if roa_t is None or roa_p is None else roa_t > roa_p)
    cfo_ta = _div(t.ocf, p.total_assets)
    point("accruals", None if cfo_ta is None or roa_t is None else cfo_ta > roa_t)
    lev_t = _div(t.long_term_debt or 0.0, t.total_assets)
    lev_p = _div(p.long_term_debt or 0.0, p.total_assets)
    point(
        "leverage_fell",
        None if lev_t is None or lev_p is None else (lev_t < lev_p or (lev_t == 0 and lev_p == 0)),
    )
    cr_t = _div(t.current_assets, t.current_liabilities)
    cr_p = _div(p.current_assets, p.current_liabilities)
    point("liquidity_rose", None if cr_t is None or cr_p is None else cr_t > cr_p)
    point(
        "no_dilution",
        None if t.shares is None or p.shares is None else t.shares <= p.shares,
    )
    gm_t, gm_p = t.gross_margin, p.gross_margin
    point("gross_margin_rose", None if gm_t is None or gm_p is None else gm_t > gm_p)
    at_t = _div(t.revenue, p.total_assets)
    at_p = _div(p.revenue, pp.total_assets)
    point("asset_turnover_rose", None if at_t is None or at_p is None else at_t > at_p)

    if len(missing) > max_missing:
        return Score(None, parts, missing)
    return Score(sum(v for v in parts.values() if v is not None), parts, missing)


def altman_z(year: Year, market_cap: float | None) -> Score:
    """Original Altman Z (public manufacturer):
    1.2 WC/TA + 1.4 RE/TA + 3.3 EBIT/TA + 0.6 MVE/TL + 1.0 Sales/TA.
    Every input is required; any missing one makes it None."""
    ta, tl = year.total_assets, year.total_liabilities
    wc = None
    if year.current_assets is not None and year.current_liabilities is not None:
        wc = year.current_assets - year.current_liabilities
    parts = {
        "wc_ta": _div(wc, ta),
        "re_ta": _div(year.retained, ta),
        "ebit_ta": _div(year.operating_income, ta),
        "mve_tl": _div(market_cap, tl),
        "sales_ta": _div(year.revenue, ta),
    }
    missing = [k for k, v in parts.items() if v is None]
    if missing:
        return Score(None, parts, missing)
    v = {k: float(x) for k, x in parts.items() if x is not None}
    z = 1.2 * v["wc_ta"] + 1.4 * v["re_ta"] + 3.3 * v["ebit_ta"] + 0.6 * v["mve_tl"] + v["sales_ta"]
    return Score(z, parts, [])


_BENEISH_REQUIRED = ("dsri", "gmi", "sgi", "tata")


def beneish_m(years: list[Year]) -> Score:
    """Eight-variable Beneish M for the newest year against the one before:
    -4.84 + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI - 0.172 SGAI
    + 4.679 TATA - 0.327 LVGI.

    DSRI, GMI, SGI and TATA are required (None without them). AQI, DEPI, SGAI and LVGI fall
    back to the neutral 1.0 when their inputs are missing, and are listed."""
    if len(years) < 2:
        return Score(None, missing=["fewer than two fiscal years"])
    t, p = years[0], years[1]

    def ratio(a: float | None, b: float | None) -> float | None:
        return _div(a, b)

    dsri = ratio(ratio(t.receivables, t.revenue), ratio(p.receivables, p.revenue))
    gmi = ratio(p.gross_margin, t.gross_margin)
    sgi = ratio(t.revenue, p.revenue)
    tata = None
    if t.net_income is not None and t.ocf is not None and t.total_assets:
        tata = (t.net_income - t.ocf) / t.total_assets

    def aq(y: Year) -> float | None:
        if y.current_assets is None or y.ppe is None or not y.total_assets:
            return None
        return 1.0 - (y.current_assets + y.ppe) / y.total_assets

    aqi = ratio(aq(t), aq(p))

    def dep_rate(y: Year) -> float | None:
        if y.da is None or y.ppe is None or (y.da + y.ppe) == 0:
            return None
        return y.da / (y.da + y.ppe)

    depi = ratio(dep_rate(p), dep_rate(t))
    sgai = ratio(ratio(t.sga, t.revenue), ratio(p.sga, p.revenue))

    def lev(y: Year) -> float | None:
        if y.current_liabilities is None or not y.total_assets:
            return None
        return (y.current_liabilities + (y.long_term_debt or 0.0)) / y.total_assets

    lvgi = ratio(lev(t), lev(p))
    parts: dict[str, float | None] = {
        "dsri": dsri,
        "gmi": gmi,
        "aqi": aqi,
        "sgi": sgi,
        "depi": depi,
        "sgai": sgai,
        "tata": tata,
        "lvgi": lvgi,
    }
    missing = [k for k, v in parts.items() if v is None]
    if any(parts[k] is None for k in _BENEISH_REQUIRED):
        return Score(None, parts, missing)

    def neutral(name: str) -> float:
        v = parts[name]
        return 1.0 if v is None else v

    m = (
        -4.84
        + 0.920 * neutral("dsri")
        + 0.528 * neutral("gmi")
        + 0.404 * neutral("aqi")
        + 0.892 * neutral("sgi")
        + 0.115 * neutral("depi")
        - 0.172 * neutral("sgai")
        + 4.679 * neutral("tata")
        - 0.327 * neutral("lvgi")
    )
    return Score(m, parts, missing)
