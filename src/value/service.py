"""The value process's nightly run (spec §6.8, §6.9, §9.7): score both universes, the followed
names and every shadow name once a session has closed, write the ticker files, run the shadow
record (with its §7.1 re-evaluations, Part 3) and log the run. ``scripts/run_value.py`` is the
thin entrypoint: it gathers the plain data this module may not fetch itself (earnings dates and
news volume from news.db, yfinance market facts) and calls :func:`plan_run` and
:func:`run_nightly`.

No IBKR connection and no clientId in Parts 1-4 (clientId 31 arrives with Stage 3). Reads
research.db read-only through ``src/common/value_inputs.py``; writes value.db only. One run is
one transaction: a run that fails leaves value.db as it was, and the next poll retries it.

Part 4 (spec §6.7, §8): the night also reads Claude's stored verdicts (recomputing each fair value
on tonight's scorecard), writes the effective verdict of every name and list, checks the breaker,
and queues tomorrow's automatic reads. The reads themselves run after the night commits
(``src/value/claude_reads.py::run_queue``, driven by the entrypoint).
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common import value_inputs as vi
from src.common.config import get_config
from src.common.value_keep_fresh import write_filing_reads, write_keep_fresh
from src.common.value_types import Classification, MarketFacts, NewsVolume, ValueInputs
from src.common.value_universe import build_value_universe
from src.value import claude_verdicts, live, reevaluate, shadow, sizing
from src.value.book import get_state as book_state
from src.value.book import set_state
from src.value.claude_reads import plan_auto_reads, plan_filing_reads
from src.value.rank import filed_lists, rank_list, rs_cutoff
from src.value.residuals import moves
from src.value.ruleset import ruleset_id
from src.value.schemas import Fingerprint, ValueScorecard
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValuePositionRow,
    ValueRunRow,
    ValueShadowRow,
    ValueTickerFileRow,
    init_value_db,
    record_run,
    value_session,
)
from src.value.ticker_file import freshness_json, persist

log = logging.getLogger(__name__)


@dataclass(slots=True)
class RunPlan:
    """What tonight's run scores: the session it is for and every name with its universe tag."""

    as_of: date
    # symbol -> trading | evidence | lookup | held:trading | held:evidence (held: out of the
    # universe but still in the shadow record: scored, never eligible to enter)
    tags: dict[str, str]
    etfs: set[str] = field(default_factory=set)
    evidence: set[str] = field(default_factory=set)
    classification: dict[str, tuple[str, str]] = field(default_factory=dict)
    positions: set[str] = field(default_factory=set)  # open READY entries: re-evaluated tonight

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
    """Every name with a shadow entry the record still carries (pending, open, or frozen for a
    rebase), and the universe it entered from: held and shadow names stay fresh even after they
    leave the universe (spec §6.9)."""
    rows = vs.execute(
        select(ValueShadowRow.symbol, ValueShadowRow.universe).where(
            ValueShadowRow.status.in_(shadow.HELD)
        )
    )
    return {symbol: universe for symbol, universe in rows}


def open_positions(vs: Session) -> set[str]:
    """The names with an open READY entry: the positions §7.1 re-evaluates tonight."""
    return set(
        vs.scalars(
            select(ValueShadowRow.symbol).where(
                ValueShadowRow.status == "open", ValueShadowRow.kind == "ready"
            )
        )
    )


def previous_regime(vs: Session) -> str | None:
    """The regime the last nightly run recorded (trigger 7 fires on a step from it)."""
    row = vs.scalars(
        select(ValueRunRow)
        .where(ValueRunRow.kind == "nightly")
        .order_by(ValueRunRow.as_of.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    regime = json.loads(row.summary_json or "{}").get("regime")
    return regime if isinstance(regime, str) else None


@dataclass(frozen=True)
class BookHooks:
    """What the night's book step reads from the trading side (Part 5), passed in by the
    entrypoint so ``src/value/`` stays free of the trading database's settings: the autonomy
    ladder for buys, the auto-close switch for Python's sells, the kill switch, live or paper."""

    may_auto_open: Callable[[str], bool]
    auto_close: bool
    halted: bool
    is_live: bool


def universe_tag(symbol: str) -> str:
    """``trading`` or ``evidence`` for a name in a universe, else ``lookup`` (spec §6.9)."""
    from src.common.universe import effective_universe

    u = build_value_universe(get_config().value, effective_universe())
    return u.tag(symbol) if symbol in set(u.all_names()) else "lookup"


def score_one(
    vs: Session,
    rs: Session,
    symbol: str,
    *,
    now: datetime,
    fingerprint: dict[str, Any] | None = None,
    tag: str | None = None,
    facts: MarketFacts | None = None,
    next_earnings: date | None = None,
) -> Fingerprint:
    """Score and persist one name (Part 6, rulings 16 and 19): ``value_refresh`` (the newest
    settled session, the regime now) and ``value_snapshot`` (exactly the input set a *fingerprint*
    carries: the price bar's date, the regime and the ruleset; the accession is whatever was filed
    by that date). *tag* is the file's universe (an existing file keeps its own, a new one is
    ``lookup`` unless it is in a universe). Ranks and the filed list stay as the last night had
    them: one name cannot be ranked alone. Returns the stored card's own fingerprint, which the
    caller compares with the one it was given."""
    vcfg = get_config().value
    version, digest = ruleset_id(vcfg)
    carried = Fingerprint.model_validate(fingerprint) if fingerprint else None
    sym = symbol.upper()
    existing = vs.get(ValueTickerFileRow, sym)
    now_et = now.replace(tzinfo=UTC).astimezone(ZoneInfo(get_config().scheduler.timezone))
    as_of = carried.price_date if carried is not None else None
    if as_of is None:
        as_of = vi.newest_bar_before(rs, shadow.BENCHMARK, now_et.date())
    if as_of is None:
        as_of = vi.newest_bar_before(rs, sym, now_et.date() + timedelta(days=1))
    if as_of is None:
        raise ValueError(f"no price bars for {sym}")
    regime = carried.regime if carried is not None else vi.load_regime()
    mf = facts or MarketFacts()
    prior: Classification | None = None
    if existing is not None:
        try:
            prior = ValueScorecard.model_validate_json(existing.scorecard_json).classification
        except ValueError:
            prior = None  # a file written by a test or an older ruleset: classify afresh
    sector = (prior.sector if prior else None) or mf.sector
    industry = (prior.industry if prior else None) or mf.industry
    parts = vi.current_fingerprint_parts(rs, sym)  # before the inputs, as the night does
    cik, payload = vi.read_payload(rs, sym)
    stale = vcfg.rules.data_quality.stale_item_days
    spy = vi.read_bars(rs, shadow.BENCHMARK, as_of)
    last_run = vs.scalars(
        select(ValueRunRow)
        .where(ValueRunRow.kind == "nightly")
        .order_by(ValueRunRow.as_of.desc())
        .limit(1)
    ).first()
    inputs = ValueInputs(
        symbol=sym,
        cik=cik,
        as_of=as_of,
        financials=None
        if payload is None
        else vi.build_value_financials(payload, as_of=as_of, stale_item_days=stale),
        price=vi.build_price_series(vi.read_bars(rs, sym, as_of), spy),
        classification=Classification(
            sector=sector,
            industry=industry,
            source="snapshot"
            if prior and prior.industry
            else ("yfinance" if mf.industry else "none"),
            is_etf=mf.quote_type == "ETF" or vi.symbol_is_etf(rs, sym),
        ),
        yf_market_cap=mf.market_cap,
        next_earnings=next_earnings or mf.next_earnings,
        regime=regime,
        rs_cutoff_6m=last_run.rs_cutoff_6m if last_run is not None else None,
    )
    card = build_scorecard(inputs, vcfg)
    universe = tag or (existing.universe if existing is not None else None) or universe_tag(sym)
    persist(
        vs,
        card,
        universe=universe,
        ranks={
            "deep_value": existing.rank_deep if existing is not None else None,
            "quality_growth": existing.rank_growth if existing is not None else None,
        },
        filed=existing.filed_list if existing is not None else None,
        cfg=vcfg.ticker_file,
        session_row=False,
        freshness=freshness_json(parts, regime, version, digest),
    )
    return card.fingerprint


def held_names(vs: Session) -> set[str]:
    """Names the value book holds (Part 5): scored nightly, kept fresh, read for filings."""
    return set(vs.scalars(select(ValuePositionRow.symbol).where(ValuePositionRow.status == "open")))


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
            # Held but no longer in either universe: scored nightly, never eligible to enter.
            tags.setdefault(symbol, f"held:{entered_from}")
        for symbol in followed_names(vs, now, vcfg.ticker_file.follow_days):
            tags.setdefault(symbol, "lookup")
        for symbol in held_names(vs):
            tags.setdefault(symbol, "held:trading")  # held by the book, out of the universe
        positions = open_positions(vs)
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
        positions=positions,
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
    recent_earnings: dict[str, list[date]] | None = None,
    news: dict[str, NewsVolume] | None = None,
    book: BookHooks | None = None,
) -> dict[str, Any]:
    """Score, rank, persist the ticker files, run the shadow record and log the run, all in one
    value.db transaction. Returns the run's summary. *recent_earnings* (report dates up to the
    session) and *news* (trigger 5) are the plain data §7.1's re-evaluations read."""
    vcfg = get_config().value
    version, digest = ruleset_id(vcfg)
    started = now or _now()
    regime = vi.load_regime()
    with vi.research_read() as rs:
        if rs is None:
            raise RuntimeError("research.db not found")
        # Read before the inputs: a filing or bar landing in between only makes a file stale once.
        parts = {n: vi.current_fingerprint_parts(rs, n) for n in plan.names}
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
                    freshness=freshness_json(parts[card.symbol], regime, version, digest),
                )
            vs.flush()
            review = vcfg.rules.margin_of_safety.review_above_pct
            ops = claude_verdicts.opinions(vs, cards, vcfg.rules)
            claude_night = claude_verdicts.night_counts(cards, plan.tags, ops, review)
            applied = claude_verdicts.applies(vs, vcfg, is_live=get_config().is_live)
            effective = claude_verdicts.persist_effective(
                vs,
                cards,
                ops,
                applied=applied,
                as_of=plan.as_of,
                now=started,
                review_above_pct=review,
            )
            deep_reads = sorted(
                {
                    sym
                    for (sym, _), eff in effective.items()
                    if eff.verdict == "READY" and plan.tags.get(sym) == "trading"
                }
                | held_names(vs)
            )
            tripped = claude_verdicts.check_breaker(vs, vcfg, claude_night, started)
            kill = claude_verdicts.update_kill_triggers(vs, cards, vcfg, plan.as_of)
            queued: dict[str, int] = {}
            if vcfg.claude.enabled:
                queued = plan_auto_reads(vs, started, vcfg)
                queued["filing"] = plan_filing_reads(
                    vs, vi.latest_periodic(rs, deep_reads), started
                )
            stepped = reevaluate.regime_stepped(
                previous_regime(vs), regime, vcfg.rules.reevaluation
            )
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
                earnings=recent_earnings,
                news=news,
                regime_stepped=stepped,
                opinions=ops,
                kill=kill,
            )
            book_summary: dict[str, Any] = {}
            if vcfg.book.enabled and book is not None:
                book_summary = _book_night(
                    vs,
                    rs,
                    cards,
                    effective,
                    plan,
                    book,
                    now=started,
                    cfg=vcfg,
                    held_ctx=shadow.ReevalContext(
                        earnings=recent_earnings or {},
                        news=news or {},
                        regime_stepped=stepped,
                        kill=kill,
                    ),
                    ruleset=(version, digest),
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
                "claude": {**claude_night, "applied": applied, "breaker": tripped, **queued},
                "book": book_summary,
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
            keep_fresh = sorted(set(shadow_names(vs)) | held_names(vs))
    # After the commit: a failed night leaves the previous list in place. The research sweep
    # reads this file to keep held names' bars and filings current (spec §6.9).
    write_keep_fresh(keep_fresh)
    write_filing_reads(deep_reads if vcfg.claude.enabled else [])
    log.info("value nightly %s: %d names; %s", plan.as_of, len(cards), json.dumps(summary))
    return summary


def _held_inputs(
    vs: Session,
    rs: Session,
    by_symbol: dict[str, Any],
    ctx: shadow.ReevalContext,
    plan: RunPlan,
    cfg: Any,
) -> dict[str, live.HeldInputs]:
    """Tonight's §7.1 inputs for each open position, from the same sources the shadow path reads
    (its residual model, the research filing index, the plain data the entrypoint hands in)."""
    rcfg = cfg.rules.reevaluation
    checked = book_state(vs, "held_checked") or {}
    positions = list(vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")))
    if not positions:
        return {}
    symbols = sorted({p.symbol for p in positions})
    etf_for = {
        s: rcfg.sector_etfs.get(
            (by_symbol[s].classification.sector or "") if s in by_symbol else "",
            rcfg.fallback_etf,
        )
        for s in symbols
    }
    market = shadow.load_bars(rs, set(symbols) | set(etf_for.values()), plan.as_of)
    oldest = min(
        date.fromisoformat(checked.get(str(p.id), p.opened_on.isoformat())) for p in positions
    )
    filings = vi.filings_between(rs, symbols, oldest, plan.as_of)
    out: dict[str, live.HeldInputs] = {}
    for symbol in symbols:
        bars = market.get(symbol, [])
        etf = market.get(etf_for[symbol], [])
        found = (
            moves(
                [(b.date, b.close) for b in bars],
                [(b.date, b.close) for b in etf],
                [plan.as_of],
                rcfg,
            )
            if bars
            else {}
        )
        card = by_symbol.get(symbol)
        list_name = next(p.list_name for p in positions if p.symbol == symbol)
        out[symbol] = live.HeldInputs(
            move=found.get(plan.as_of),
            filings=filings.get(symbol, []),
            earnings=ctx.earnings.get(symbol, []),
            news=ctx.news.get(symbol),
            regime_stepped=ctx.regime_stepped,
            kill=ctx.kill.get(symbol, []),
            sessions=[b.date for b in bars],
            verdict_now=card.verdict_for(list_name) if card is not None else None,
        )
    return out


def _book_night(
    vs: Session,
    rs: Session,
    cards: list[Any],
    effective: dict[tuple[str, str], Any],
    plan: RunPlan,
    hooks: BookHooks,
    *,
    now: datetime,
    cfg: Any,
    held_ctx: shadow.ReevalContext | None = None,
    ruleset: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """The night's money step (Part 5): mirror tonight's re-evaluations onto held positions, give
    a held name with no shadow entry the whole §7.1 trigger set (Part 6), set the trend brake,
    step the held plans and propose tonight's buys and sells."""
    by_symbol = {c.symbol: c for c in cards}
    names = held_names(vs) | {s for (s, _), e in effective.items() if e.verdict == "READY"}
    bars = shadow.load_bars(rs, names | {shadow.BENCHMARK}, plan.as_of)
    spy = [(b.date, b.close) for b in bars.get(shadow.BENCHMARK, [])]
    brake = bool(sizing.trend_brake(sizing.month_end_closes(spy)))
    set_state(vs, "trend", {"brake": brake, "as_of": plan.as_of.isoformat()}, now)
    mirrored = live.mirror_reevaluations(vs, plan.as_of, now)
    held_n = live.held_reevaluations(
        vs,
        plan.as_of,
        now,
        inputs=_held_inputs(vs, rs, by_symbol, held_ctx or shadow.ReevalContext(), plan, cfg),
        cfg=cfg,
        ruleset_version=(ruleset or ruleset_id(cfg))[0],
        ruleset_hash=(ruleset or ruleset_id(cfg))[1],
    )
    facts = {}
    going_concern = vi.going_concern_flags(rs, sorted(names), plan.as_of)
    for (symbol, list_name), eff in effective.items():
        fact = shadow.day_facts(
            by_symbol.get(symbol), list_name, going_concern.get(symbol), eff.fair_value
        )
        if fact is not None:
            facts[(symbol, list_name)] = fact
    night = live.plan_night(
        vs,
        cards=by_symbol,
        tags=plan.tags,
        bars=bars,
        facts=facts,
        cfg=cfg,
        portfolio=get_config().risk.get("portfolio", {}),
        now=now,
        today=plan.as_of,
        may_auto_open=hooks.may_auto_open,
        auto_close=hooks.auto_close,
        halted=hooks.halted,
        is_live=hooks.is_live,
        trend_brake=brake,
    )
    return {
        **asdict(night),
        "trend_brake": brake,
        "mirrored": mirrored,
        "held_reevaluations": held_n,
    }
