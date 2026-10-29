"""The rank score (spec §6.8) and the run's relative-strength line (spec §6.6). Pure: no I/O.

Cross-sectional, so it runs over a whole night's scorecards, never inside one. It orders names
within a verdict state, decides which list a name that qualifies for both is filed on, and (Part
2) which healthy names Claude reads first. It never feeds a gate or a size.
"""

from __future__ import annotations

from statistics import mean

from pydantic import BaseModel

from src.common.value_types import PriceSeries
from src.value.schemas import ListName, ValueScorecard


class RankEntry(BaseModel):
    symbol: str
    list_name: ListName
    value_pct: float | None
    quality_pct: float | None
    score: float | None


def percentiles(values: dict[str, float]) -> dict[str, float]:
    """0 for the lowest, 1 for the highest, ties share the average; a lone value is 0.5."""
    n = len(values)
    if n == 0:
        return {}
    if n == 1:
        return {k: 0.5 for k in values}
    ordered = sorted(values.values())
    out: dict[str, float] = {}
    for key, v in values.items():
        less = sum(1 for x in ordered if x < v)
        equal = sum(1 for x in ordered if x == v)
        out[key] = (less + (equal - 1) / 2.0) / (n - 1)
    return out


def _check_actual(card: ValueScorecard, check_id: str) -> float | None:
    for c in card.health_checks:
        if c.id == check_id:
            return c.actual
    return None


def _quality_components(card: ValueScorecard, list_name: ListName) -> dict[str, float]:
    """Higher is better for every component (variabilities are negated)."""
    m = card.metrics
    raw: dict[str, float | None]
    if card.company_class in ("bank", "insurer"):
        sd = _check_actual(card, "bank.rote_stdev")
        raw = {
            "rote_median": m.get("rote_median_5y"),
            "rote_stability": None if sd is None else -sd,
        }
    else:
        gm = m.get("gross_margin_stdev_5y")
        raw = {
            "piotroski": _check_actual(card, "health.piotroski"),
            "roic_median": m.get("roic_median_5y"),
            "margin_stability": None if gm is None else -gm,
        }
        if list_name == "quality_growth":
            raw["revenue_growth"] = m.get("revenue_cagr_5y")
    return {k: v for k, v in raw.items() if v is not None}


def rank_list(cards: list[ValueScorecard], list_name: ListName) -> dict[str, RankEntry]:
    """Rank every scored name on *list_name*: the mean of a value percentile (margin of safety;
    normalised FCF yield where fair value is missing) and a quality percentile (the mean of its
    component percentiles). Data-quality failures and not-applicable names are excluded."""
    pop = [
        c
        for c in cards
        if c.data_quality == "pass" and c.not_applicable_reason is None and list_name in c.lists
    ]
    mos: dict[str, float] = {}
    fcf_yield: dict[str, float] = {}
    for c in pop:
        ev = c.lists[list_name]
        if ev.margin_of_safety is not None:
            mos[c.symbol] = ev.margin_of_safety
        nfcf = c.metrics.get("normalised_fcf_ps")
        if nfcf is not None and c.price:
            fcf_yield[c.symbol] = nfcf / c.price
    mos_pct, yield_pct = percentiles(mos), percentiles(fcf_yield)

    components = {c.symbol: _quality_components(c, list_name) for c in pop}
    names = sorted({k for comp in components.values() for k in comp})
    comp_pct = {
        name: percentiles({s: comp[name] for s, comp in components.items() if name in comp})
        for name in names
    }
    out: dict[str, RankEntry] = {}
    for c in pop:
        value = mos_pct.get(c.symbol, yield_pct.get(c.symbol))
        mine = [comp_pct[n][c.symbol] for n in names if c.symbol in comp_pct[n]]
        quality = mean(mine) if mine else None
        parts = [p for p in (value, quality) if p is not None]
        out[c.symbol] = RankEntry(
            symbol=c.symbol,
            list_name=list_name,
            value_pct=value,
            quality_pct=quality,
            score=mean(parts) if parts else None,
        )
    return out


def filed_lists(
    cards: list[ValueScorecard],
    deep: dict[str, RankEntry],
    growth: dict[str, RankEntry],
) -> dict[str, ListName]:
    """Deep value, unless the name passes health and the quality-growth entry rule and ranks
    higher there (spec §6.0: filed on the list where its rank score is higher)."""
    out: dict[str, ListName] = {}
    for c in cards:
        ev = c.lists.get("quality_growth")
        qualifies = c.health == "pass" and ev is not None and ev.entry == "pass"
        g = growth.get(c.symbol)
        d = deep.get(c.symbol)
        g_score = g.score if g and g.score is not None else None
        d_score = d.score if d and d.score is not None else None
        if qualifies and g_score is not None and (d_score is None or g_score > d_score):
            out[c.symbol] = "quality_growth"
        else:
            out[c.symbol] = "deep_value"
    return out


def rs_cutoff(prices: list[PriceSeries | None], bottom_pct: float) -> float | None:
    """The *bottom_pct* percentile of 6-month return less SPY's across the run (linear
    interpolation between ranks). None with fewer than 10 names."""
    excess = sorted(
        p.ret_6m - p.spy_ret_6m
        for p in prices
        if p is not None and p.ret_6m is not None and p.spy_ret_6m is not None
    )
    if len(excess) < 10:
        return None
    k = (len(excess) - 1) * bottom_pct / 100.0
    lo = int(k)
    hi = min(lo + 1, len(excess) - 1)
    return excess[lo] + (excess[hi] - excess[lo]) * (k - lo)
