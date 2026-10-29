"""The value process's nightly run (spec §6.8, §6.9, §9.7): score both universes, the followed
names and every shadow name once a session has closed, write the ticker files, run the shadow
record and log the run. ``scripts/run_value.py`` is the thin entrypoint: it gathers the plain
data this module may not fetch itself (earnings dates from news.db, yfinance market facts) and
calls :func:`plan_run` and :func:`run_nightly`.

No IBKR connection and no clientId in Parts 1-4 (clientId 31 arrives with Stage 3). Reads
research.db read-only through ``src/common/value_inputs.py``; writes value.db only. One run is
one transaction: a run that fails leaves value.db as it was, and the next poll retries it.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common import value_inputs as vi
from src.common.config import get_config
from src.common.value_types import Classification, MarketFacts, ValueInputs
from src.common.value_universe import build_value_universe
from src.value import shadow
from src.value.rank import filed_lists, rank_list, rs_cutoff
from src.value.ruleset import ruleset_id
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValueRunRow,
    ValueShadowRow,
    ValueTickerFileRow,
    init_value_db,
    record_run,
    value_session,
)
from src.value.ticker_file import persist

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RunPlan:
    """What tonight's run scores: the session it is for and every name with its universe tag."""

    as_of: date
    tags: dict[str, str]  # symbol -> trading | evidence | lookup
    etfs: set[str] = field(default_factory=set)
    evidence: set[str] = field(default_factory=set)
    classification: dict[str, tuple[str, str]] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return sorted(self.tags)

    @property
    def fetch_names(self) -> list[str]:
        """Names whose yfinance market facts the entrypoint fetches (not the ETFs)."""
        return [n for n in self.names if n not in self.etfs]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def startup_check() -> str | None:
    """Why the process must idle, or None. A frozen ruleset whose rules no longer match (a
    private config/value.yaml from an older version) idles the process instead of crash-looping
    under the supervisor."""
    try:
        ruleset_id(get_config().value)
    except ValueError as exc:
        return str(exc)
    init_value_db()
    return None


def is_due(now_et: datetime, as_of: date | None, last: date | None, run_hour: int) -> bool:
    """A settled session nobody has scored yet, and the hour has come."""
    return as_of is not None and (last is None or as_of > last) and now_et.hour >= run_hour


def last_nightly_as_of(vs: Session) -> date | None:
    return vs.scalar(select(func.max(ValueRunRow.as_of)).where(ValueRunRow.kind == "nightly"))


def followed_names(vs: Session, now: datetime, follow_days: int) -> list[str]:
    """Names looked up outside the universe and viewed within ``follow_days`` (spec §6.9).
    Part 6's surfaces set ``last_viewed_at``; after the window the file stays, unrefreshed."""
    cutoff = now - timedelta(days=follow_days)
    return list(
        vs.scalars(
            select(ValueTickerFileRow.symbol).where(
                ValueTickerFileRow.universe == "lookup",
                ValueTickerFileRow.last_viewed_at.is_not(None),
                ValueTickerFileRow.last_viewed_at >= cutoff,
            )
        )
    )


def shadow_names(vs: Session) -> dict[str, str]:
    """Every name with a pending or open shadow entry, and the universe it entered from: held
    and shadow names stay fresh even after they leave the universe (spec §6.9)."""
    rows = vs.execute(
        select(ValueShadowRow.symbol, ValueShadowRow.universe).where(
            ValueShadowRow.status.in_(("pending", "open"))
        )
    )
    return {symbol: universe for symbol, universe in rows}


def plan_run(now: datetime | None = None, universe: dict[str, Any] | None = None) -> RunPlan | None:
    """Tonight's plan, or None when no newly settled session is waiting. *as_of* is SPY's newest
    bar dated before today (ET): a bar dated today may still be forming."""
    cfg = get_config()
    vcfg = cfg.value
    now = now or _now()
    now_et = now.replace(tzinfo=UTC).astimezone(ZoneInfo(cfg.scheduler.timezone))
    with vi.research_read() as rs:
        if rs is None:
            log.warning("value: research.db not found; nothing to score")
            return None
        as_of = vi.newest_bar_before(rs, shadow.BENCHMARK, now_et.date())
    with value_session() as vs:
        last = last_nightly_as_of(vs)
        if not is_due(now_et, as_of, last, vcfg.service.run_hour_et):
            return None
        assert as_of is not None
        if universe is None:
            from src.common.universe import effective_universe

            universe = effective_universe()
        u = build_value_universe(vcfg, universe)
        tags = {s: u.tag(s) for s in u.all_names()}
        for symbol, entered_from in shadow_names(vs).items():
            tags.setdefault(symbol, entered_from)
        for symbol in followed_names(vs, now, vcfg.ticker_file.follow_days):
            tags.setdefault(symbol, "lookup")
    companies = [s for s in u.all_names() if s not in u.etfs]
    with vi.research_read() as rs:
        assert rs is not None
        have, want = vi.filings_coverage(rs, companies)
    if want and have * 100.0 < want * vcfg.service.min_filings_coverage_pct:
        log.warning(
            "value: waiting for the research sweep: filings for %d of %d names (need %.0f%%)",
            have,
            want,
            vcfg.service.min_filings_coverage_pct,
        )
        return None
    return RunPlan(
        as_of=as_of,
        tags=tags,
        etfs=set(u.etfs),
        evidence=set(u.evidence),
        classification=dict(u.classification),
    )


def load_inputs(
    plan: RunPlan,
    rs: Session,
    *,
    facts: dict[str, MarketFacts],
    earnings: dict[str, date],
    regime: str,
) -> list[ValueInputs]:
    """Every name's scorecard input as of the plan's session (filings filed by then, bars up to
    then). Earnings: news.db first, yfinance's calendar as the fallback (spec §6.6)."""
    spy = vi.read_bars(rs, shadow.BENCHMARK, plan.as_of)
    out: list[ValueInputs] = []
    stale = get_config().value.rules.data_quality.stale_item_days
    for symbol in plan.names:
        cik, payload = vi.read_payload(rs, symbol)
        mf = facts.get(symbol, MarketFacts())
        sector, industry = plan.classification.get(symbol, (None, None))
        out.append(
            ValueInputs(
                symbol=symbol,
                cik=cik,
                as_of=plan.as_of,
                financials=None
                if payload is None
                else vi.build_value_financials(payload, as_of=plan.as_of, stale_item_days=stale),
                price=vi.build_price_series(vi.read_bars(rs, symbol, plan.as_of), spy),
                classification=Classification(
                    sector=sector or mf.sector,
                    industry=industry or mf.industry,
                    source="snapshot" if industry else ("yfinance" if mf.industry else "none"),
                    is_etf=symbol in plan.etfs
                    or mf.quote_type == "ETF"
                    or vi.symbol_is_etf(rs, symbol),
                ),
                yf_market_cap=mf.market_cap,
                next_earnings=earnings.get(symbol, mf.next_earnings),
                regime=regime,
            )
        )
    return out


def run_nightly(
    plan: RunPlan,
    *,
    facts: dict[str, MarketFacts],
    earnings: dict[str, date],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Score, rank, persist the ticker files, run the shadow record and log the run, all in one
    value.db transaction. Returns the run's summary."""
    vcfg = get_config().value
    version, digest = ruleset_id(vcfg)
    started = now or _now()
    regime = vi.load_regime()
    with vi.research_read() as rs:
        if rs is None:
            raise RuntimeError("research.db not found")
        inputs = load_inputs(plan, rs, facts=facts, earnings=earnings, regime=regime)
        cutoff = rs_cutoff([i.price for i in inputs], vcfg.rules.timing.rs_bottom_pct)
        inputs = [i.model_copy(update={"rs_cutoff_6m": cutoff}) for i in inputs]
        cards = [build_scorecard(i, vcfg) for i in inputs]
        deep, growth = rank_list(cards, "deep_value"), rank_list(cards, "quality_growth")
        filed = filed_lists(cards, deep, growth)
        atr = {i.symbol: i.price.atr14 if i.price else None for i in inputs}
        with value_session() as vs:
            for card in cards:
                d, g = deep.get(card.symbol), growth.get(card.symbol)
                tag = plan.tags[card.symbol]
                persist(
                    vs,
                    card,
                    universe=tag,
                    ranks={
                        "deep_value": d.score if d else None,
                        "quality_growth": g.score if g else None,
                    },
                    filed=filed.get(card.symbol),
                    cfg=vcfg.ticker_file,
                    session_row=tag != "lookup",
                )
            vs.flush()
            record = shadow.process(
                vs,
                rs,
                cards,
                tags=plan.tags,
                atr=atr,
                evidence=plan.evidence,
                as_of=plan.as_of,
                cfg=vcfg,
                version=version,
                digest=digest,
                now=started,
            )
            verdicts = {
                name: dict(Counter(c.verdict_for(name) for c in cards))
                for name in ("deep_value", "quality_growth")
            }
            summary = {
                "regime": regime,
                "rs_cutoff_6m": cutoff,
                "verdicts": verdicts,
                "missing_market_cap": sum(
                    1 for i in inputs if not i.classification.is_etf and i.yf_market_cap is None
                ),
                "shadow": asdict(record),
            }
            record_run(
                vs,
                kind="nightly",
                started_at=started,
                finished_at=_now(),
                as_of=plan.as_of,
                ruleset_version=version,
                ruleset_hash=digest,
                names=len(cards),
                rs_cutoff_6m=cutoff,
                summary_json=json.dumps(summary, sort_keys=True),
            )
    log.info("value nightly %s: %d names; %s", plan.as_of, len(cards), json.dumps(summary))
    return summary
