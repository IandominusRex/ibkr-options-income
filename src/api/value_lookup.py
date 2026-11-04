"""A ticker file that is fresh on open (value book Part 6, ruling 24; spec §6.9).

``lookup`` serves ``GET /value/{symbol}``. A stored file whose freshness key equals the key of the
cheap input parts now (the newest accession and bar in research.db, the regime, the ruleset) is
answered as ``stored``. A stale or absent one is computed **now** with the pure
``src.value.scorecard.build_scorecard`` over ``src.common.value_inputs`` (research.db ``mode=ro``,
market facts from yfinance, earnings from news.db read-only), inside the research materialisation
budget, answered as ``computed: "now"``, and one ``value_snapshot`` intent carries the input set it
used to the value process, which persists it. This module never opens value.db for writing and
writes nothing but that one command (through ``src.api.commands``, the API's one write path).

Filings missing from research.db answer ``computed: "pending"`` and queue the research ingest the
research router already uses. Past the budget the stored file (or ``pending``) is answered.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from src.api import commands as api_commands
from src.api import value_db as vdb
from src.api.auth import User
from src.api.models.commands import CommandKind
from src.api.models.value import ValueTickerResponse
from src.api.news_db import news_read_session
from src.api.routers.value import file_out, side_blocks, stored_response
from src.common import value_inputs as vi
from src.common.config import get_config
from src.common.value_freshness import is_current, rules_digest
from src.common.value_types import Classification, MarketFacts, ValueInputs
from src.value.schemas import ValueScorecard
from src.value.scorecard import build_scorecard

log = logging.getLogger(__name__)

BENCHMARK = "SPY"  # src.value.shadow.BENCHMARK (the API may not import it)
EARNINGS_HORIZON_DAYS = 180  # scripts/value_feed.py's window


def _budget() -> float:
    """Seconds a compute may take. Patched in tests."""
    return get_config().research.tiers.materialization_budget_seconds


def _enqueue_ingest(symbol: str, kind: str) -> None:
    """Queue a research ingest job (deduplicated on symbol, kind, pending): the router's path."""
    from src.research.ingest.materialize import enqueue

    enqueue(symbol, kind)


def _within(budget: float, fn: Callable[[], Any]) -> tuple[Any, bool]:
    """Run *fn* on a daemon thread for at most *budget* seconds: ``(value, timed_out)``. A failure
    inside *fn* is ``(None, False)``."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - a failed compute falls back to the stored file
            log.warning("value lookup: compute failed (%s)", exc)

    worker = threading.Thread(target=target, daemon=True, name="value-lookup")
    worker.start()
    worker.join(budget)
    if worker.is_alive():
        return None, True
    return box.get("value"), False


def _next_earnings(symbol: str, as_of: date) -> date | None:
    """The name's earliest earnings date on or after *as_of* from news.db (read-only)."""
    import src.news.store.queries as queries

    with news_read_session() as s:
        if s is None:
            return None
        for e in queries.earnings_between(
            s, as_of, as_of + timedelta(days=EARNINGS_HORIZON_DAYS), {symbol}
        ):
            return e.report_date
    return None


def _compute(
    symbol: str, *, today: date, prior: Classification | None, rs_cutoff: float | None, regime: str
) -> ValueScorecard | None:
    """The scorecard for one name as of the newest settled session, from the same inputs the value
    process uses. ``None`` when research.db has no bar for the name."""
    cfg = get_config().value
    facts: MarketFacts = vi.fetch_market_facts(symbol)
    with vi.research_read() as rs:
        if rs is None:
            return None
        as_of = vi.newest_bar_before(rs, BENCHMARK, today) or vi.newest_bar_before(
            rs, symbol, today + timedelta(days=1)
        )
        if as_of is None:
            return None
        cik, payload = vi.read_payload(rs, symbol)
        stale = cfg.rules.data_quality.stale_item_days
        sector = (prior.sector if prior else None) or facts.sector
        industry = (prior.industry if prior else None) or facts.industry
        inputs = ValueInputs(
            symbol=symbol,
            cik=cik,
            as_of=as_of,
            financials=None
            if payload is None
            else vi.build_value_financials(payload, as_of=as_of, stale_item_days=stale),
            price=vi.build_price_series(
                vi.read_bars(rs, symbol, as_of), vi.read_bars(rs, BENCHMARK, as_of)
            ),
            classification=Classification(
                sector=sector,
                industry=industry,
                source="snapshot"
                if prior and prior.industry
                else ("yfinance" if facts.industry else "none"),
                is_etf=facts.quote_type == "ETF" or vi.symbol_is_etf(rs, symbol),
            ),
            yf_market_cap=facts.market_cap,
            next_earnings=_next_earnings(symbol, as_of) or facts.next_earnings,
            regime=regime,
            rs_cutoff_6m=rs_cutoff,
        )
    return build_scorecard(inputs, cfg)


def lookup(symbol: str, user: User, *, now: datetime | None = None) -> ValueTickerResponse | None:
    """The ticker file for *symbol* as the web shows it, or ``None`` when the name is unknown to
    both value.db and research.db (the route answers 404)."""
    now = now or datetime.now(UTC)
    sym = symbol.upper()
    cfg = get_config()
    with vdb.value_read_session() as s:
        if s is None:
            return ValueTickerResponse(as_of=now, available=False, symbol=sym)
        row = vdb.read_ticker_row(s, sym)
        stored: ValueTickerResponse | None = None
        prior: Classification | None = None
        if row is not None:
            try:
                stored = stored_response(s, row, now)
                prior = ValueScorecard.model_validate_json(row["scorecard_json"]).classification
            except ValueError:
                stored = None  # a card this build cannot read is recomputed, not shown
        rs_cutoff = vdb.last_nightly_rs_cutoff(s)
        blocks = side_blocks(s, sym)
    with vi.research_read() as rs:
        if rs is None:
            return stored  # no research database here: nothing to judge freshness against
        cik, payload = vi.read_payload(rs, sym)
        if cik is None and payload is None:
            return stored  # not a filer research.db knows: the stored file or a 404
        # Read before the inputs, as the night does: a filing landing in between only makes the
        # file stale once.
        parts = vi.current_fingerprint_parts(rs, sym)
    regime = vi.load_regime()
    version = cfg.value.ruleset_version
    digest = rules_digest(cfg.value.rules.model_dump(mode="json"))
    if (
        row is not None
        and stored is not None
        and is_current(row["freshness_json"], parts, regime, version, digest)
    ):
        return stored
    missing = [
        kind
        for kind, absent in (
            ("fundamentals", payload is None),
            ("prices", parts["price_date"] is None),
        )
        if absent
    ]
    if missing:
        for kind in missing:
            _enqueue_ingest(sym, kind)
        if stored is not None:
            return stored.model_copy(update={"computed": "pending"})
        return ValueTickerResponse(as_of=now, available=True, symbol=sym, computed="pending")
    today = now.astimezone(ZoneInfo(cfg.scheduler.timezone)).date()
    card, timed_out = _within(
        _budget(),
        lambda: _compute(sym, today=today, prior=prior, rs_cutoff=rs_cutoff, regime=regime),
    )
    if card is None:
        if stored is not None:
            return stored
        return (
            None
            if not timed_out
            else ValueTickerResponse(as_of=now, available=True, symbol=sym, computed="pending")
        )
    fingerprint = card.fingerprint
    try:
        api_commands.submit(
            kind=CommandKind.VALUE_SNAPSHOT,
            payload={"symbol": sym, "fingerprint": fingerprint.model_dump(mode="json")},
            user=user,
            dedupe_key=f"value_snapshot:{sym}:{fingerprint.key()}",
        )
    except Exception as exc:  # noqa: BLE001 - showing the file never depends on the intent
        log.warning("value lookup: could not queue the snapshot for %s (%s)", sym, exc)
    claude, reevaluations, plan = blocks
    return ValueTickerResponse(
        as_of=now,
        available=True,
        symbol=sym,
        computed="now",
        age_days=vdb.age_days(card.as_of, now),
        file=file_out(card, {}, computed_at=now, universe=row["universe"] if row else None),
        claude=claude,
        reevaluations=reevaluations,
        plan=plan,
    )
