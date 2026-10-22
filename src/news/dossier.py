"""The ticker dossier the news process keeps for every name the book cares about (spec section 16).

One record per name in ``data/news.db`` (``TickerDossierRow``, the newest wins, older rows kept
``dossier.keep_days``), read by the trade, roll and ``/scan`` reviews. It is the name-level
counterpart of the market picture: the state of the name now, not a record of past opinions.

Two halves with a hard line between them:

* **Python** writes every number and recomputes it on every build, with no model call: the kind
  (stock, ETF, leveraged ETF), the numbered facts, the health label from the fundamentals, the
  7-day deterministic sentiment, and the upcoming events (`verify_event_date`: a date is kept
  only when it is written in the cited news). `refresh_facts` is the hourly refresh; it copies
  the model's prose forward unchanged.
* **The model** writes only a short profile, the current story and proposed events. That is
  `build_dossier_prose` (batched, grounded, under its own daily call budget).

Who gets one: ``would_own`` and ``actively_wheeling`` (the effective universe, so web overrides
count) plus every held underlying. A dossier carries **no book** (the trade reviewer's book block
already shows positions), so ``build_ticker_facts`` is always called with no positions.

Enrichment tier: it reaches the Claude-side prompts and the web page, never the engine, execution,
strategies or spreads (`tests/test_news_fence.py`).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import ColumnElement, String, cast, delete, or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.analytics.fundamentals import get_fundamental_stats
from src.common.books import is_spreads_underlying
from src.common.config import (
    NewsCfg,
    NewsDossierCfg,
    NewsDossierHealthCfg,
    get_config,
    get_regime_cfg,
)
from src.common.market_hours import is_trading_day
from src.common.schemas import DossierEvent, DossierFact, FundamentalStats, TickerDossier
from src.common.universe import effective_universe
from src.news.alerts import rank_ticker_clusters
from src.news.collectors import held_underlyings, universe_lists
from src.news.explain import latest_picture_text, validated_call
from src.news.facts import Analytics, build_ticker_facts
from src.news.grounding import extract_numbers, strip_meta_and_advice, strip_ungrounded
from src.news.llm import cap_reached
from src.news.prompts import (
    DOSSIER_SCHEMA,
    DossierPromptEntry,
    dossier_cluster_lines,
    dossier_prompt,
)
from src.news.schemas import (
    ClusterView,
    DossierDraft,
    DossierEventDraft,
    DossierNameDraft,
    EarningsView,
)
from src.news.store import queries
from src.news.store.models import (
    EarningsEventRow,
    NewsClusterRow,
    NewsPostRow,
    StoryTriageRow,
    TickerDossierRow,
)
from src.news.store.queries import aware_utc, naive_utc
from src.news.store.session import news_session
from src.news.store.state import get_state, set_state

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

Kind = Literal["stock", "etf", "leveraged_etf"]
Health = Literal["strong", "ok", "weak", "n/a", "unknown"]

_SENTIMENT_DAYS = 7
_SESSIONS = (("1-month return", 21), ("3-month return", 63))
_EARNINGS_DAYS = 60  # how far ahead the next report date is looked for
_SNIPPET_PAD = 80  # characters of the cited text kept either side of an event date
_SNIPPET_MAX = 200


def _upper(values: object) -> set[str]:
    return {str(x).upper() for x in (values or [])}  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# who, what kind, how healthy
# --------------------------------------------------------------------------- #


def dossier_symbols() -> list[str]:
    """Sorted ``would_own`` + ``actively_wheeling`` + every held underlying, spreads names out."""
    u = effective_universe()
    names = _upper(u.get("would_own")) | _upper(u.get("actively_wheeling")) | held_underlyings()
    return sorted(n for n in names if n and not is_spreads_underlying(n))


def kind_of(symbol: str, fund: FundamentalStats | None) -> Kind:
    """``leveraged_etf`` when listed in ``universe.leveraged_etfs``; ``etf`` when it is an index
    fund (``universe.indexes``) or the fundamentals say it has fund assets; else ``stock``."""
    u = effective_universe()
    sym = symbol.upper()
    if sym in _upper(u.get("leveraged_etfs")):
        return "leveraged_etf"
    if sym in _upper(u.get("indexes")) or (fund is not None and fund.total_assets is not None):
        return "etf"
    return "stock"


def _de_phrase(debt_to_equity: float) -> str:
    return f"debt/equity {debt_to_equity / 100:.1f}x"  # yfinance reports percent: 150 = 1.5x


def health_label(
    fund: FundamentalStats | None, kind: str, cfg: NewsDossierHealthCfg
) -> tuple[Health, list[str]]:
    """``(label, reasons)`` from the fundamentals: ``strong | ok | weak | n/a | unknown``.

    ETFs are ``n/a``. No fundamentals (or none of the quality flag, free cash flow and debt/equity)
    is ``unknown``. ``weak`` when free cash flow is negative or debt/equity is over ``de_weak``;
    ``strong`` when the name passes the quality screen with positive free cash flow and debt/equity
    at or under ``de_strong`` (or unreported); ``ok`` otherwise. Each reason is a short phrase.
    """
    if kind != "stock":
        return "n/a", []
    if fund is None or (
        fund.quality_flag is None and fund.free_cash_flow is None and fund.debt_to_equity is None
    ):
        return "unknown", ["no fundamentals"]
    fcf, de = fund.free_cash_flow, fund.debt_to_equity
    weak: list[str] = []
    if fcf is not None and fcf < 0:
        weak.append("free cash flow negative")
    if de is not None and de > cfg.de_weak:
        weak.append(_de_phrase(de))
    if weak:
        return "weak", weak
    if fund.quality_flag and fcf is not None and fcf > 0 and (de is None or de <= cfg.de_strong):
        return "strong", ["passes the quality screen"]
    reasons: list[str] = []
    if fund.quality_flag is not None:
        reasons.append(
            "passes the quality screen" if fund.quality_flag else "fails the quality screen"
        )
    if de is not None and de > cfg.de_strong:
        reasons.append(_de_phrase(de))
    if fcf is None:
        reasons.append("free cash flow unknown")
    elif fcf == 0:
        reasons.append("free cash flow not positive")
    return "ok", reasons


# --------------------------------------------------------------------------- #
# the numbered facts
# --------------------------------------------------------------------------- #


def _session_return(daily: pd.DataFrame | None, sessions: int) -> float | None:
    """Percent change of the last close over the close *sessions* bars earlier (None: too short)."""
    if daily is None or daily.empty or "Close" not in daily:
        return None
    closes = daily["Close"].dropna()
    if len(closes) <= sessions:
        return None
    then = float(closes.iloc[-1 - sessions])
    return (float(closes.iloc[-1]) / then - 1.0) * 100.0 if then else None


def _next_earnings(session: Session, symbol: str, today: date) -> EarningsView | None:
    rows = queries.earnings_between(
        session, today, today + timedelta(days=_EARNINGS_DAYS), {symbol}
    )
    return rows[0] if rows else None


def _regime_index(symbol: str) -> str | None:
    """The index whose regime governs *symbol*: QQQ for a tech-linked name, else SPY."""
    try:
        return "QQQ" if symbol.upper() in set(get_regime_cfg().tech_linked) else "SPY"
    except Exception:
        log.debug("dossier: regime config unreadable", exc_info=True)
        return None


def build_facts(
    symbol: str,
    *,
    an: Analytics,
    today: date,
    cfg: NewsCfg,
    session: Session,
    now: datetime | None = None,
) -> tuple[list[DossierFact], float | None, int]:
    """``(facts, 7-day mean deterministic sentiment, item count)`` for *symbol*.

    The ticker fact sheet (called with **no positions**: a dossier carries no book) plus 1- and
    3-month returns from the daily bars, the governing regime index and, separately, the mean of
    the deterministic sentiment scores of the last seven days (the same columns
    ``analytics/sentiment.py`` reads). Ids are ``<SYM>:F<n>``.
    """
    sym = symbol.upper()
    sheet = build_ticker_facts(
        sym,
        an=an,
        positions=[],
        lists=universe_lists(sym),
        earnings=_next_earnings(session, sym, today),
        cluster_tags=set(),
        today=today,
        cfg=cfg,
    )
    lines: list[tuple[str, str]] = [(f.label, f.display) for f in sheet.facts]
    try:
        daily: pd.DataFrame | None = an.daily(sym)
    except Exception:
        daily = None
    for label, sessions in _SESSIONS:
        ret = _session_return(daily, sessions)
        if ret is not None:
            lines.append((label, f"{ret:+.1f}% ({sessions} sessions)"))
    index = _regime_index(sym)
    if index is not None:
        lines.append(("Regime index", index))
    facts = [
        DossierFact(id=f"{sym}:F{i}", label=label, display=display)
        for i, (label, display) in enumerate(lines, 1)
    ]
    since = (now or datetime(today.year, today.month, today.day, tzinfo=UTC)) - timedelta(
        days=_SENTIMENT_DAYS
    )
    scores = [row[0] for row in queries.ticker_sentiment_rows(session, sym, since)]
    mean = round(sum(scores) / len(scores), 2) if scores else None
    return facts, mean, len(scores)


# --------------------------------------------------------------------------- #
# the verified event date
# --------------------------------------------------------------------------- #

_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def _month_words(month: int) -> str:
    """A regex alternation for *month*: the full name, its three-letter form (and ``sept``)."""
    full = _MONTHS[month - 1]
    names = {full, full[:3]} | ({"sept"} if month == 9 else set())
    return "(?:" + "|".join(sorted(names, key=len, reverse=True)) + r")"


def verify_event_date(text: str, on: date) -> str | None:
    """The snippet of *text* around the first explicit mention of *on*, or None.

    Accepted spellings (case-insensitive, at word boundaries, each with an optional year that must
    equal ``on.year`` when present): ``October 22``, ``Oct 22``, ``Oct. 22``, ``Oct 22nd``,
    ``22 October``, ``10/22``, ``2026-10-22``. ``Oct 2`` never matches ``Oct 22`` and a relative
    date (``next Tuesday``, ``later this month``) never matches. Python decides whether a date the
    model proposed is real: it must be written in the cluster the model cited.
    """
    month, day = _month_words(on.month), f"0?{on.day}"
    patterns = [
        rf"\b{month}\.?\s+{day}(?:st|nd|rd|th)?(?!\d)(?:,?\s+(\d{{4}}))?",  # Oct 22 / October 22, 2026
        rf"(?<![\w/]){day}(?:st|nd|rd|th)?\s+(?:of\s+)?{month}(?!\w)(?:,?\s+(\d{{4}}))?",  # 22 October
        rf"(?<![\d/.-])0?{on.month}/{day}(?:/(\d{{4}}|\d{{2}}))?(?![\d/])",  # 10/22, 10/22/26
        rf"(?<!\d){on.year}-0?{on.month}-{day}(?!\d)",  # 2026-10-22
    ]
    best: re.Match[str] | None = None
    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            year = m.group(1) if m.re.groups else None
            if year is not None:
                value = int(year)
                value = value + 2000 if len(year) == 2 else value
                if value != on.year:
                    continue
            if best is None or m.start() < best.start():
                best = m
            break  # the first valid mention of this spelling is enough
    if best is None:
        return None
    lo, hi = max(0, best.start() - _SNIPPET_PAD), min(len(text), best.end() + _SNIPPET_PAD)
    return " ".join(text[lo:hi].split())[:_SNIPPET_MAX]


# --------------------------------------------------------------------------- #
# the hourly refresh (no model call)
# --------------------------------------------------------------------------- #


def _fundamentals(symbol: str) -> FundamentalStats | None:
    try:
        return get_fundamental_stats(symbol)
    except Exception:
        log.debug("dossier: fundamentals for %s unavailable", symbol, exc_info=True)
        return None


def _purge(now: datetime, keep_days: int) -> None:
    """Delete rows older than *keep_days*, at most once per ET day."""
    day = now.astimezone(ET).date().isoformat()
    if get_state("dossier_purged_on") == day:
        return
    with news_session() as s:
        s.execute(
            delete(TickerDossierRow).where(
                TickerDossierRow.built_at < naive_utc(now - timedelta(days=keep_days))
            )
        )
    set_state("dossier_purged_on", day, now=now)


def _fresh_row(
    symbol: str,
    prev: TickerDossier | None,
    *,
    now: datetime,
    today: date,
    facts: list[DossierFact],
    sentiment: float | None,
    items: int,
    kind: Kind,
    health: Health,
    why: list[str],
) -> TickerDossier:
    """A numbers-only rebuild: new facts, health and sentiment; the previous prose carried over
    unchanged (events dated before today dropped)."""
    fresh = TickerDossier(
        symbol=symbol,
        version=f"{symbol}@{now.isoformat(timespec='microseconds')}",
        facts_at=now,
        kind=kind,
        health=health,
        health_why=why,
        facts=facts,
        sentiment_7d=sentiment,
        sentiment_items_7d=items,
    )
    if prev is None:
        return fresh
    return fresh.model_copy(
        update={
            "prose_at": prev.prose_at,
            "profile_at": prev.profile_at,
            "profile": prev.profile,
            "story": prev.story,
            "story_evidence": list(prev.story_evidence),
            "events": [e for e in prev.events if e.on >= today],
            "stale": prev.stale,
        }
    )


def refresh_facts(
    now: datetime,
    *,
    an: Analytics | None = None,
    fundamentals: Callable[[str], FundamentalStats | None] | None = None,
) -> int:
    """Rebuild the numbers of every dossier name whose latest build is older than
    ``facts_refresh_min`` (no model call), copying the prose forward. Returns the names rebuilt.

    A name is skipped, never fatal: one failing provider does not stop the others. Rows older than
    ``keep_days`` are deleted once a day. Never raises. *an* and *fundamentals* are injection
    points for tests; production uses the live bundle and ``get_fundamental_stats``.
    """
    cfg = get_config().news
    dcfg = cfg.dossier
    if not dcfg.enabled:
        return 0
    try:
        symbols = dossier_symbols()
    except Exception:
        log.warning("dossier: could not list the names", exc_info=True)
        return 0
    today = now.astimezone(ET).date()
    due_before = now - timedelta(minutes=dcfg.facts_refresh_min)
    bundle = an
    fetch_fund = fundamentals or _fundamentals
    built = 0
    for symbol in symbols:
        try:
            with news_session() as s:
                prev = queries.latest_dossier(s, symbol)
            if prev is not None and aware_utc(prev.facts_at) > due_before:
                continue
            bundle = bundle or Analytics.live()
            fund = fetch_fund(symbol)
            kind = kind_of(symbol, fund)
            health, why = health_label(fund, kind, dcfg.health)
            with news_session() as s:
                facts, sentiment, items = build_facts(
                    symbol, an=bundle, today=today, cfg=cfg, session=s, now=now
                )
            with news_session() as s:
                # The numbers took a while: carry the prose of the newest row *now*, in case a
                # prose build landed meanwhile (it must not be overwritten with the older prose).
                held = _newest(s, symbol)
                d = _fresh_row(
                    symbol,
                    held[1] if held is not None else prev,
                    now=now,
                    today=today,
                    facts=facts,
                    sentiment=sentiment,
                    items=items,
                    kind=kind,
                    health=health,
                    why=why,
                )
                if held is not None:
                    _save(s, held[0], d, now)
                else:
                    s.add(
                        TickerDossierRow(
                            symbol=symbol,
                            version=d.version,
                            built_at=naive_utc(now),
                            payload=d.model_dump(mode="json"),
                        )
                    )
            built += 1
        except Exception:
            log.warning("dossier: facts refresh failed for %s", symbol, exc_info=True)
    try:
        _purge(now, dcfg.keep_days)
    except Exception:
        log.warning("dossier: purge failed", exc_info=True)
    return built


# --------------------------------------------------------------------------- #
# when a name is due
# --------------------------------------------------------------------------- #


def _profile_wanted(last: TickerDossier, now: datetime, cfg: NewsDossierCfg) -> bool:
    return last.profile_at is None or now - aware_utc(last.profile_at) > timedelta(
        days=cfg.profile_days
    )


def _names_in_json(column: Any, symbol: str) -> ColumnElement[bool]:
    """SQL narrowing for a JSON ``tickers`` list: the text match is a prefilter, callers check
    membership exactly."""
    return cast(column, String).contains(f'"{symbol}"', autoescape=True)


def _news_since(s: Session, symbol: str, since: datetime) -> bool:
    """A pile 1 or 2 story naming *symbol* was judged (or promoted late) after *since*."""
    rows = s.scalars(
        select(NewsClusterRow.tickers)
        .join(StoryTriageRow, StoryTriageRow.cluster_id == NewsClusterRow.id)
        .where(
            StoryTriageRow.pile.in_((1, 2)),
            or_(StoryTriageRow.judged_at > since, StoryTriageRow.promoted_at > since),
            _names_in_json(NewsClusterRow.tickers, symbol),
        )
    )
    return any(symbol in (tickers or []) for tickers in rows)


def _alert_since(s: Session, symbol: str, since: datetime) -> bool:
    """A non-digest post about *symbol* (an alert card, a brief) went out after *since*."""
    return (
        s.scalar(
            select(NewsPostRow.id)
            .where(
                NewsPostRow.subject == symbol,
                NewsPostRow.kind.not_like("digest%"),
                NewsPostRow.posted_at > since,
            )
            .limit(1)
        )
        is not None
    )


def _earnings_since(s: Session, symbol: str, since: datetime) -> bool:
    """*symbol*'s earnings were released (first seen) after *since*."""
    return (
        s.scalar(
            select(EarningsEventRow.symbol)
            .where(
                EarningsEventRow.symbol == symbol,
                EarningsEventRow.status == "released",
                EarningsEventRow.released_seen_at > since,
            )
            .limit(1)
        )
        is not None
    )


def dossier_due(symbol: str, last: TickerDossier | None, *, now: datetime, s: Session) -> list[str]:
    """Why *symbol*'s prose should be (re)built now; empty when it should not.

    * ``new`` - no dossier, or one that has never had prose (it then also gets ``profile`` when
      its profile has never been written);
    * ``news`` - a pile 1 or 2 story naming it was judged (or promoted late) after the last prose;
    * ``alert`` - a non-digest post about it went out after the last prose;
    * ``earnings`` - its earnings were released after the last prose;
    * ``profile`` - the profile is missing or older than ``profile_days`` (it is then requested).

    There is no ``age`` reason: old prose is shown labelled with its age, never rebuilt for being
    old (ruling 43). ``news`` and ``profile`` wait until ``prose_min_interval_hours`` have passed
    since the last prose; ``new``, ``alert`` and ``earnings`` never wait. A reader of an old
    news.db without the tables gets no reasons.
    """
    cfg = get_config().news.dossier
    if last is None or last.prose_at is None:
        profile = last is None or _profile_wanted(last, now, cfg)
        return ["new", "profile"] if profile else ["new"]
    since = naive_utc(last.prose_at)
    waiting = now - aware_utc(last.prose_at) < timedelta(hours=cfg.prose_min_interval_hours)
    reasons: list[str] = []
    try:
        if not waiting and _news_since(s, symbol, since):
            reasons.append("news")
        if _alert_since(s, symbol, since):
            reasons.append("alert")
        if _earnings_since(s, symbol, since):
            reasons.append("earnings")
    except OperationalError:
        return []
    if not waiting and _profile_wanted(last, now, cfg):
        reasons.append("profile")
    return reasons


def order_due(items: list[tuple[str, list[str]]]) -> list[tuple[str, list[str]]]:
    """Due names, held ones first, then the ones with more reasons, then by symbol."""
    held = held_underlyings()
    return sorted(items, key=lambda it: (it[0] not in held, -len(it[1]), it[0]))


def in_dossier_window(now: datetime) -> bool:
    """True on a trading day from the pre-market digest time to the close digest time (ET)."""
    et = now.astimezone(ET)
    if not is_trading_day(et.date()):
        return False
    digests = get_config().news.digests

    def at(hhmm: str) -> tuple[int, int]:
        hh, mm = hhmm.split(":")
        return int(hh), int(mm)

    return at(digests.premarket) <= (et.hour, et.minute) <= at(digests.close)


# --------------------------------------------------------------------------- #
# what the model's words may become
# --------------------------------------------------------------------------- #

_CLUSTER_ID = re.compile(r"\bC(\d+)\b")
_CLUSTER_PAREN = re.compile(r"\s*\((?:\s*C\d+\s*,?)+\)")
# A profile may name an index or a leverage multiple: those numbers are part of the name
# (ruling 47), so they are removed before the "no numbers" check.
_NAME_NUMBERS = re.compile(
    r"-?\d(?:\.\d)?x\b|S&P 500|Nasdaq-100|Nasdaq 100|Russell 2000|Dow 30", re.IGNORECASE
)
_EARNINGS_TITLE = re.compile(r"earnings|results|quarter", re.IGNORECASE)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _prose_clean(text: str, refs: list[float] | None, rel_tol: float) -> str | None:
    """*text* if nothing in it had to be trimmed: no ungrounded number (when *refs* is given), no
    advice, no talk about the inputs, no id. None otherwise: a prose field is dropped, not repaired."""
    clean = _norm(text)
    if not clean:
        return None
    kept = clean
    if refs is not None:
        kept, _ = strip_ungrounded(kept, refs, rel_tol)
    kept, _ = strip_meta_and_advice(kept)
    if _norm(kept) != clean or _CLUSTER_ID.search(clean):
        return None
    return clean


def clean_profile(text: str | None) -> str | None:
    """A profile Python accepts, or None. It carries no numbers (a leverage multiple or an index
    name is fine), no advice, no id and no talk about its inputs."""
    if not text or not text.strip():
        return None
    if extract_numbers(_NAME_NUMBERS.sub(" ", text)):
        return None
    return _prose_clean(text, None, 0.0)


def clean_story(
    text: str, evidence: list[str], listed: set[int], refs: list[float], rel_tol: float
) -> tuple[str, list[str]]:
    """``(story, cited clusters)``, both empty when the story fails.

    It must cite at least one listed cluster (in *evidence* or inline); the ids are moved out of
    the prose into the evidence; and no number outside the name's facts, no advice, no talk about
    the inputs and no stray id may remain."""
    cited: list[str] = []
    for raw in evidence:
        m = re.fullmatch(r"C(\d+)", raw.strip())
        if m and int(m.group(1)) in listed and f"C{m.group(1)}" not in cited:
            cited.append(f"C{m.group(1)}")
    for m in _CLUSTER_ID.finditer(text):
        if int(m.group(1)) in listed and f"C{m.group(1)}" not in cited:
            cited.append(f"C{m.group(1)}")
    if not cited:
        return "", []
    prose = _CLUSTER_PAREN.sub("", text)
    prose = _CLUSTER_ID.sub(lambda m: "" if int(m.group(1)) in listed else m.group(0), prose)
    clean = _prose_clean(prose, refs, rel_tol)
    return (clean, cited) if clean else ("", [])


def verified_events(
    drafts: list[DossierEventDraft],
    *,
    shown: dict[int, str],
    kind: str,
    today: date,
    max_days: int,
) -> list[DossierEvent]:
    """The proposed events Python can stand behind. An event must cite a listed cluster whose
    shown text writes its date (`verify_event_date`), fall after today and within *max_days*, not
    be an earnings date (the earnings calendar and blackout already cover those) and not carry
    advice or an id in its title; an ETF keeps none. Ids are assigned later, in date order."""
    if kind != "stock":
        return []
    out: list[DossierEvent] = []
    for d in drafts:
        m = re.fullmatch(r"C(\d+)", d.evidence.strip())
        if not m or int(m.group(1)) not in shown:
            continue
        if not (today < d.on <= today + timedelta(days=max_days)):
            continue
        title = _prose_clean(d.title, None, 0.0)
        if title is None or _EARNINGS_TITLE.search(title):
            continue
        quote = verify_event_date(shown[int(m.group(1))], d.on)
        if quote is None:
            continue
        out.append(
            DossierEvent(id="", title=title, on=d.on, evidence=f"C{m.group(1)}", quote=quote)
        )
    return out


def merge_events(
    symbol: str, previous: list[DossierEvent], new: list[DossierEvent], *, today: date
) -> list[DossierEvent]:
    """Verified events persist until their date (ruling 27): the previous ones still ahead plus
    the new ones, duplicates by (date, evidence) collapsed, ids ``<SYM>:E<n>`` in date order."""
    seen: set[tuple[date, str]] = set()
    merged: list[DossierEvent] = []
    for e in [*(p for p in previous if p.on >= today), *new]:
        key = (e.on, e.evidence)
        if key not in seen:
            seen.add(key)
            merged.append(e)
    merged.sort(key=lambda e: (e.on, e.evidence))
    return [e.model_copy(update={"id": f"{symbol}:E{n}"}) for n, e in enumerate(merged, 1)]


# --------------------------------------------------------------------------- #
# the prose build
# --------------------------------------------------------------------------- #

_MAX_CLUSTERS = 8  # clusters shown per name
_CANDIDATE_CLUSTERS = 16  # fetched before the noise filter and ranking


@dataclass
class _Pending:
    symbol: str
    last: TickerDossier
    reasons: list[str]
    want_profile: bool
    clusters: list[ClusterView]


def _name_clusters(s: Session, symbol: str, now: datetime, cfg: NewsCfg) -> list[ClusterView]:
    since = now - timedelta(days=cfg.dossier.story_window_days)
    found = queries.piled_clusters_for(s, symbol, since, limit=_CANDIDATE_CLUSTERS)
    return rank_ticker_clusters(found, symbol, cfg.tagging.noise_terms)[:_MAX_CLUSTERS]


def _fact_numbers(facts: list[DossierFact]) -> list[float]:
    return [v for f in facts for v, _decimals, _must in extract_numbers(f.display)]


def _newest(s: Session, symbol: str) -> tuple[TickerDossierRow, TickerDossier] | None:
    row = s.scalar(
        select(TickerDossierRow)
        .where(TickerDossierRow.symbol == symbol)
        .order_by(TickerDossierRow.built_at.desc(), TickerDossierRow.id.desc())
        .limit(1)
    )
    if row is None:
        return None
    try:
        return row, TickerDossier.model_validate(row.payload)
    except ValueError:
        return None


def _save(s: Session, row: TickerDossierRow, d: TickerDossier, now: datetime) -> None:
    """Add *d* as a new row that sorts after *row* (the newest) whatever the clocks say."""
    s.add(
        TickerDossierRow(
            symbol=d.symbol,
            version=d.version,
            built_at=max(naive_utc(now), row.built_at),
            payload=d.model_dump(mode="json"),
        )
    )


def _version(symbol: str, now: datetime) -> str:
    return f"{symbol}@{now.isoformat(timespec='microseconds')}:prose"


def _mark_stale(batch: list[_Pending], now: datetime) -> None:
    """The model gave no usable answer: keep each name's prose and say it is stale."""
    with news_session() as s:
        for p in batch:
            if p.last.prose_at is None:
                continue  # nothing was written yet: nothing to mark
            held = _newest(s, p.symbol)
            if held is None:
                continue
            row, current = held
            _save(
                s,
                row,
                current.model_copy(update={"stale": True, "version": _version(p.symbol, now)}),
                now,
            )


def _write_prose(
    batch: list[_Pending],
    out: DossierDraft,
    *,
    now: datetime,
    today: date,
    cfg: NewsCfg,
) -> None:
    """Validate the model's notes against Python's facts and save one new row per name.

    Each row is built from the **newest** stored dossier, read inside this transaction, with only
    the prose fields replaced: a numbers refresh that landed during the model call is kept."""
    by_symbol: dict[str, DossierNameDraft] = {}
    for d in out.names:
        by_symbol.setdefault(d.symbol.strip().upper(), d)
    rel_tol = cfg.grounding.rel_tol
    with news_session() as s:
        for p in batch:
            held = _newest(s, p.symbol)
            if held is None:
                continue
            row, current = held
            draft = by_symbol.get(p.symbol) or DossierNameDraft(symbol=p.symbol)
            shown = {cl.id: "\n".join(dossier_cluster_lines(cl, p.symbol)) for cl in p.clusters}
            story, cited = clean_story(
                draft.story, draft.story_evidence, set(shown), _fact_numbers(p.last.facts), rel_tol
            )
            update: dict[str, object] = {
                "version": _version(p.symbol, now),
                "prose_at": now,
                "story": story,
                "story_evidence": cited,
                "stale": False,
                "events": merge_events(
                    p.symbol,
                    current.events,
                    verified_events(
                        draft.events,
                        shown=shown,
                        kind=current.kind,
                        today=today,
                        max_days=cfg.dossier.max_event_days,
                    ),
                    today=today,
                ),
            }
            profile = clean_profile(draft.profile) if p.want_profile else None
            if profile is not None:
                update["profile"] = profile
                update["profile_at"] = now
            _save(s, row, current.model_copy(update=update), now)


def build_dossier_prose(now: datetime) -> int:
    """Build the model's part (profile, story, events) for every name that is due; returns the
    names built.

    Due names (`dossier_due`) go held first, then by number of reasons, then by symbol, in
    batches of ``batch_size``; one call per batch under the dossier's own daily cap (the rest wait
    for the next loop or the next day). A name with no dossier row yet waits for the numbers
    refresh to create it. A failed call keeps each name's previous prose, marked stale; a name
    whose notes fail Python's checks loses that part (never the previous text); a name the model
    left out gets an empty story. Nothing the model wrote before is sent back to it.
    """
    cfg = get_config().news
    dcfg = cfg.dossier
    if not dcfg.enabled:
        return 0
    try:
        symbols = dossier_symbols()
    except Exception:
        log.warning("dossier: could not list the names", exc_info=True)
        return 0
    today = now.astimezone(ET).date()
    due: list[tuple[str, list[str]]] = []
    latest: dict[str, TickerDossier] = {}
    with news_session() as s:
        for symbol in symbols:
            last = queries.latest_dossier(s, symbol)
            if last is None:
                continue
            reasons = dossier_due(symbol, last, now=now, s=s)
            if reasons:
                due.append((symbol, reasons))
                latest[symbol] = last
    if not due:
        return 0
    ordered = order_due(due)
    picture_text = latest_picture_text(now)
    built = 0
    for start in range(0, len(ordered), dcfg.batch_size):
        if cap_reached(now, "dossier"):
            log.info("dossier: daily call budget spent — %d names wait", len(ordered) - start)
            break
        names = ordered[start : start + dcfg.batch_size]
        with news_session() as s:
            batch = [
                _Pending(
                    symbol,
                    latest[symbol],
                    reasons,
                    _profile_wanted(latest[symbol], now, dcfg),
                    _name_clusters(s, symbol, now, cfg),
                )
                for symbol, reasons in names
            ]
        prompt = dossier_prompt(
            [
                DossierPromptEntry(p.symbol, p.last.kind, p.last.facts, p.clusters, p.want_profile)
                for p in batch
            ],
            picture_text,
        )
        out, _backend = validated_call(
            DossierDraft,
            prompt,
            schema=DOSSIER_SCHEMA,
            prefix="news:dossier",
            now=now,
            purpose="dossier",
        )
        if out is None:
            _mark_stale(batch, now)
            continue
        _write_prose(batch, out, now=now, today=today, cfg=cfg)
        built += len(batch)
    return built
