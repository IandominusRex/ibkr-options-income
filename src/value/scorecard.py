"""The scorecard: one pure function from inputs and config to Part 1 of a ticker file.

docs/superpowers/specs/2026-10-28-value-swing-book-design.md §6.3-6.7, §6.9. No I/O: the API
may import this module and compute a ticker file during a request (tests/test_value_fence.py).
"""

from __future__ import annotations

from statistics import median

from src.common.config import ValueCfg
from src.common.schemas import MarketRegime
from src.common.value_types import ValueInputs
from src.value import gates, timing, valuation
from src.value.metrics import Year, cagr, median_of, roic, stdev_of
from src.value.ruleset import ruleset_id
from src.value.schemas import (
    Check,
    CompanyClass,
    Fingerprint,
    GateState,
    ListEvaluation,
    ListName,
    MethodValue,
    ValueScorecard,
    Verdict,
    combine,
)

_FINANCIAL: tuple[CompanyClass, ...] = ("bank", "insurer")


def _regime(inputs: ValueInputs) -> MarketRegime:
    try:
        return MarketRegime(inputs.regime)
    except ValueError:
        return MarketRegime.NORMAL


def fingerprint(inputs: ValueInputs, version: str, digest: str) -> Fingerprint:
    fin, price = inputs.financials, inputs.price
    return Fingerprint(
        latest_accn=fin.latest_accn if fin else None,
        latest_filed=fin.latest_filed if fin else None,
        price_date=price.as_of if price else None,
        price_close=price.close if price else None,
        regime=inputs.regime,
        ruleset_version=version,
        ruleset_hash=digest,
    )


def _ttm(inputs: ValueInputs, item: str) -> float | None:
    point = inputs.financials.ttm.get(item) if inputs.financials else None
    return point.value if point is not None else None


def per_share_count(inputs: ValueInputs, years: list[Year]) -> float | None:
    """The newest weighted diluted count (a 10-Q's, else the last fiscal year's)."""
    fin = inputs.financials
    if fin is not None and fin.shares_latest:
        return fin.shares_latest
    return years[0].shares if years else None


def normalised_fcf(
    inputs: ValueInputs, years: list[Year], company_class: CompanyClass, sbc_share: float
) -> float | None:
    """TTM FCF less *sbc_share* of TTM SBC; for a cyclical, the 5-year median of that margin
    times TTM revenue. Untagged SBC counts as zero."""
    if company_class == "cyclical":
        margins = [
            (y.fcf - sbc_share * (y.sbc or 0.0)) / y.revenue
            for y in years[:5]
            if y.fcf is not None and y.revenue
        ]
        revenue = _ttm(inputs, "revenue")
        if not margins or revenue is None:
            return None
        return median(margins) * revenue
    fcf = gates.ttm_fcf(inputs)
    if fcf is None:
        return None
    return fcf - sbc_share * (_ttm(inputs, "sbc") or 0.0)


def _fcf_ps_series(years: list[Year]) -> list[float | None]:
    return [None if y.fcf is None or not y.shares else y.fcf / y.shares for y in years]


def _verdict(
    health: GateState,
    health_checks: list[Check],
    entry: GateState,
    fair: float | None,
    price: float,
    ceiling: float | None,
    timing_state: GateState,
) -> tuple[Verdict, list[str]]:
    if health == "fail":
        failed = [c.id for c in health_checks if c.state == "fail"]
        return "NO", [f"health gate failed: {', '.join(failed)}"]
    if health == "unknown":
        unknown = [c.id for c in health_checks if c.state == "unknown"]
        return "UNKNOWN", [f"health gate unknown: {', '.join(unknown)}"]
    if entry != "pass":
        return "NO", [f"entry rule {entry}"]
    if fair is None or ceiling is None:
        return "NO", ["no fair value"]
    if price > ceiling:
        return "WAIT", [f"price {price:.2f} above the entry ceiling {ceiling:.2f}"]
    if timing_state != "pass":
        return "WATCH", [f"cheap enough; timing {timing_state}"]
    return "READY", ["healthy, cheap enough, timing passes"]


def _evaluate(
    list_name: ListName,
    *,
    inputs: ValueInputs,
    cfg: ValueCfg,
    health: GateState,
    health_checks: list[Check],
    entry_checks: list[Check],
    methods: list[MethodValue],
    use: tuple[str, ...],
    timing_checks: list[Check],
) -> ListEvaluation:
    rules = cfg.rules
    assert inputs.price is not None
    price = inputs.price.close
    required = getattr(rules.margin_of_safety, list_name)[_regime(inputs)]
    entry = combine(entry_checks) if entry_checks else "pass"
    fair = valuation.fair_value(methods, use)
    mos = None if fair is None else (fair - price) / fair
    ceiling = None if fair is None else fair * (1.0 - required / 100.0)
    timing_state = combine(timing_checks)
    verdict, reasons = _verdict(health, health_checks, entry, fair, price, ceiling, timing_state)
    return ListEvaluation(
        list_name=list_name,
        entry=entry,
        entry_checks=entry_checks,
        methods=methods,
        fair_value=fair,
        required_mos_pct=required,
        margin_of_safety=mos,
        entry_ceiling=ceiling,
        timing=timing_state,
        timing_checks=timing_checks,
        verdict=verdict,
        reasons=reasons,
        mos_review=mos is not None and mos * 100.0 > rules.margin_of_safety.review_above_pct,
    )


def growth_entry_checks(inputs: ValueInputs, years: list[Year], cfg: ValueCfg) -> list[Check]:
    """Spec §6.0: 5-year revenue CAGR >= 10% (or FCF/share CAGR >= 10%), 5-year median ROIC
    >= 15%, gross-margin standard deviation <= 5 points."""
    q = cfg.rules.quality_growth
    rev = cagr([y.revenue for y in years])
    fcf_ps = cagr(_fcf_ps_series(years))
    grows = [g for g in (rev, fcf_ps) if g is not None]
    if not grows:
        growth = Check(id="growth.cagr", state="unknown", threshold=q.revenue_cagr_min_pct)
    else:
        ok = (rev is not None and rev * 100 >= q.revenue_cagr_min_pct) or (
            fcf_ps is not None and fcf_ps * 100 >= q.fcf_ps_cagr_min_pct
        )
        growth = Check(
            id="growth.cagr",
            state="pass" if ok else "fail",
            actual=max(grows) * 100,
            threshold=q.revenue_cagr_min_pct,
            detail=f"revenue {_pct(rev)}, FCF/share {_pct(fcf_ps)}",
        )
    roic_med = median_of([roic(y) for y in years])
    gm_sd = stdev_of([y.gross_margin for y in years])
    return [
        growth,
        gates.check_at_least(
            "growth.roic_median",
            None if roic_med is None else roic_med * 100,
            q.roic_median_min_pct,
        ),
        gates.check_at_most(
            "growth.gross_margin_stdev",
            None if gm_sd is None else gm_sd * 100,
            q.gross_margin_stdev_max_pts,
        ),
    ]


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def build_scorecard(inputs: ValueInputs, cfg: ValueCfg) -> ValueScorecard:
    """Part 1 of the ticker file for one name. Never raises on missing data: it says UNKNOWN."""
    version, digest = ruleset_id(cfg)
    rules = cfg.rules
    card = ValueScorecard(
        symbol=inputs.symbol,
        as_of=inputs.as_of,
        ruleset_version=version,
        ruleset_hash=digest,
        company_class="etf" if inputs.classification.is_etf else "operating",
        classification=inputs.classification,
        data_quality="unknown",
        price=inputs.price.close if inputs.price else None,
        fingerprint=fingerprint(inputs, version, digest),
    )
    if inputs.classification.is_etf:
        return card.model_copy(
            update={"data_quality": "not_applicable", "not_applicable_reason": "ETF"}
        )

    years, shares = gates.build_years_for(inputs)
    dq_checks = gates.data_quality(inputs, years, shares, rules)
    dq = combine(dq_checks)
    company_class = gates.classify(inputs, years, rules)
    count = gates.edgar_shares(inputs)
    edgar_cap = count * inputs.price.close if count and inputs.price else None
    card = card.model_copy(
        update={
            "company_class": company_class,
            "data_quality": dq,
            "data_quality_checks": dq_checks,
            "market_cap_edgar": edgar_cap,
            "adjustments": shares.adjustments,
        }
    )
    if dq != "pass":
        return card
    assert inputs.price is not None

    v = rules.valuation
    nfcf = normalised_fcf(inputs, years, company_class, 1.0)
    gfcf = normalised_fcf(inputs, years, company_class, v.growth_sbc_share)
    per_share = per_share_count(inputs, years)
    nfcf_ps = None if nfcf is None or not per_share else nfcf / per_share
    gfcf_ps = None if gfcf is None or not per_share else gfcf / per_share
    realised = cagr(_fcf_ps_series(years))
    implied = (
        None
        if nfcf_ps is None
        else valuation.implied_growth(
            inputs.price.close, nfcf_ps, v.discount_rate_deep, v.terminal_growth, v.dcf_years
        )
    )
    metrics: dict[str, float | None] = {
        "fcf_ttm": gates.ttm_fcf(inputs),
        "sbc_ttm": _ttm(inputs, "sbc"),
        "revenue_ttm": _ttm(inputs, "revenue"),
        "normalised_fcf_ps": nfcf_ps,
        "growth_fcf_ps": gfcf_ps,
        "per_share_count": per_share,
        "net_debt": gates.net_debt_latest(inputs),
        "roic_median_5y": median_of([roic(y) for y in years]),
        "gross_margin_stdev_5y": stdev_of([y.gross_margin for y in years]),
        "revenue_cagr_5y": cagr([y.revenue for y in years]),
    }
    card = card.model_copy(
        update={
            "metrics": metrics,
            "reverse_dcf_implied_growth": implied,
            "realised_fcf_ps_cagr": realised,
        }
    )
    if company_class == "reit":
        return card.model_copy(update={"not_applicable_reason": "REIT: FFO is not reliably tagged"})
    if company_class not in _FINANCIAL and gates.preprofit(years, rules):
        return card.model_copy(update={"not_applicable_reason": "pre-profit"})

    deep_use: tuple[str, ...]
    if company_class in _FINANCIAL:
        health_checks = gates.financial_health(
            inputs, years, rules, insurer=company_class == "insurer"
        )
        rote_med = median_of(gates.rote_series(years))
        tbv_ps = gates.latest_tbv_per_share(inputs, years)
        metrics["rote_median_5y"] = rote_med
        metrics["tbv_ps"] = tbv_ps
        deep_methods = [valuation.method_ptbv(rote_med, tbv_ps, v)]
        deep_use = ("PTBV",)
    else:
        health_checks = gates.operating_health(
            inputs, years, edgar_cap, rules, cyclical=company_class == "cyclical"
        )
        deep_methods = [
            valuation.method_a(nfcf_ps, v),
            valuation.method_b(nfcf_ps, realised, v),
            valuation.method_c(),
        ]
        deep_use = ("A", "B", "C")
    health = combine(health_checks)
    earnings = timing.earnings_check(inputs.as_of, inputs.next_earnings, rules.timing)
    lists: dict[str, ListEvaluation] = {
        "deep_value": _evaluate(
            "deep_value",
            inputs=inputs,
            cfg=cfg,
            health=health,
            health_checks=health_checks,
            entry_checks=[],
            methods=deep_methods,
            use=deep_use,
            timing_checks=[
                earnings,
                *timing.deep_value_timing(inputs.price, inputs.rs_cutoff_6m, rules.timing),
            ],
        )
    }
    if company_class not in _FINANCIAL:
        lists["quality_growth"] = _evaluate(
            "quality_growth",
            inputs=inputs,
            cfg=cfg,
            health=health,
            health_checks=health_checks,
            entry_checks=growth_entry_checks(inputs, years, cfg),
            methods=[
                valuation.method_d(gfcf_ps, realised, v),
                valuation.method_c(),
                deep_methods[0],
            ],
            use=("D", "C"),
            timing_checks=[earnings, *timing.growth_timing(inputs.price, rules.timing)],
        )
    return card.model_copy(
        update={
            "metrics": metrics,
            "health": health,
            "health_checks": health_checks,
            "lists": lists,
        }
    )
