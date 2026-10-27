"""The market picture the news process builds and every reader shares (spec section 8).

Deterministic first: Python computes the regimes (from the trading process's record), every
number, the upcoming events, the seasonality and the noise counts, and decides which stories are
alive (``stories.py``). The model is asked once for the stories and a short description each, and
nothing it says is kept unless Python can check it:

* every story must cite at least one id that exists (a cluster of pile 1 or 2 it was shown, or a
  numbered fact), and a **new** story must cite a pile 1 cluster;
* every number in a title or description must come from the fact sheet, and neither may carry
  trading advice, talk about its inputs or contain an id (a story that does is dropped whole);
* a story's identity (id, title, start date) is stored here and carries over; its prose is never
  stored in the story table and never fed back, and the model cannot keep a story alive: Python
  matches clusters to it and ends it when it stops being supported.

If the call fails the previous stories are kept by title, without descriptions, and the picture
is marked stale; the deterministic part is always fresh.

Enrichment tier: it reaches prompts and Telegram cards, never the engine, execution or sizing.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.analytics.market_conditions import get_market_conditions, tnx_divisor
from src.analytics.regime import classify_base, fetch_daily_inputs
from src.analytics.seasonality import month_seasonality
from src.common.config import NewsDigestCfg, get_config, get_regime_cfg
from src.common.market_hours import is_trading_day
from src.common.schemas import (
    MarketConditions,
    MarketPicture,
    NoiseSummary,
    PictureFact,
    PictureRegime,
    PictureStory,
    RegimeInputs,
)
from src.data.factory import get_price_provider
from src.news.collectors import held_underlyings
from src.news.explain import validated_call
from src.news.facts import build_market_facts
from src.news.grounding import strip_meta_and_advice, strip_ungrounded
from src.news.prompts import PICTURE_SCHEMA, picture_prompt
from src.news.schemas import ClusterView, FactSheet, PictureDraft, TriageView
from src.news.store import queries
from src.news.store.models import MarketPictureRow, PictureStoryRow, StoryTriageRow
from src.news.store.queries import aware_utc, naive_utc
from src.news.store.session import news_session
from src.news.stories import match_clusters, story_alive
from src.news.touches import MARKET, touched_since
from src.news.touches import consume as consume_touches
from src.storage.regime_state import load_regime_state, regime_suspended

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

_INDICES: tuple[Literal["SPY", "QQQ"], ...] = ("SPY", "QQQ")
_MAX_EVENTS = 8
_EVENT_DAYS = 7
_PROMPT_CLUSTERS = 40  # the pile 1 and 2 clusters shown to the model, best first
_NOISE_DAYS = 7
_CLUSTER_REF = re.compile(r"^C(\d+)$")
_CLUSTER_IN_PROSE = re.compile(r"\bC\d+\b")


def _safe[T](fn: Callable[[], T], default: T, what: str) -> T:
    """One source of the picture failing must never stop the picture."""
    try:
        return fn()
    except Exception:
        log.warning("news picture: %s unavailable", what, exc_info=True)
        return default


# --- the deterministic facts ----------------------------------------------------------------


def _trend_line(inp: RegimeInputs) -> str | None:
    """One index's trend as one numbered fact: where it is against its averages and its high."""
    if inp.index_close is None:
        return None
    parts = [f"close {inp.index_close:.2f}"]
    if inp.sma50:
        parts.append(f"{(inp.index_close / inp.sma50 - 1) * 100:+.1f}% vs 50-day")
    if inp.sma200:
        parts.append(f"{(inp.index_close / inp.sma200 - 1) * 100:+.1f}% vs 200-day")
    if inp.drawdown_52w_pct is not None:
        parts.append(f"{inp.drawdown_52w_pct:.1f}% below its 52-week high")
    if inp.ret_1m_pct is not None:
        parts.append(f"1-month {inp.ret_1m_pct:+.1f}%")
    if inp.ret_3m_pct is not None:
        parts.append(f"3-month {inp.ret_3m_pct:+.1f}%")
    return " · ".join(parts)


def _ten_year_history() -> pd.Series | None:
    """^TNX closes (see ``tnx_divisor`` for the scale), about two months of them."""
    hist = get_price_provider().get_ohlcv("^TNX", lookback_days=60)
    if hist is None or hist.empty or "Close" not in hist:
        return None
    closes = hist["Close"].dropna().reset_index(drop=True)
    return closes if len(closes) else None


def picture_facts(
    now: datetime,
) -> tuple[FactSheet, list[PictureRegime], Literal["trading", "news"]]:
    """The numbered facts, the two regimes and where the regimes came from.

    The regime is the trading process's persisted record (``regime_source == "trading"``); only
    when none exists is it classified here from the same daily inputs and rules (``"news"``), and
    the picture says so. Never raises: a source that fails leaves its facts out.
    """
    today = now.astimezone(ET).date()
    state = _safe(load_regime_state, None, "the regime record")
    suspended = _safe(lambda: regime_suspended(today), False, "the regime suspension flag")
    inputs: dict[str, RegimeInputs] = {}
    regimes: list[PictureRegime] = []
    source: Literal["trading", "news"]
    if state is not None:
        source = "trading"
        for ir in (state.spy, state.qqq):
            regimes.append(
                PictureRegime(
                    index=ir.index,
                    effective=ir.effective,
                    base=ir.base,
                    eased_by_bottoming=ir.eased_by_bottoming,
                    suspended=suspended,
                    as_of=state.as_of,
                )
            )
            inputs[ir.index] = ir.inputs
    else:
        source = "news"
        thresholds = get_regime_cfg().thresholds
        for index in _INDICES:
            daily = fetch_daily_inputs(index)  # fail-soft: what it could not read is marked stale
            regime, _why = classify_base(daily, thresholds)
            regimes.append(
                PictureRegime(
                    index=index, effective=regime, base=regime, suspended=suspended, as_of=now
                )
            )
            inputs[index] = daily

    sheet = FactSheet()
    for name, inp in inputs.items():
        line = _trend_line(inp)
        if line is not None:
            sheet.add(name, inp.index_close, line)

    backdrop = _safe(get_market_conditions, None, "the macro backdrop")
    if backdrop is None:
        spy = inputs.get("SPY")
        backdrop = MarketConditions(
            vix=spy.vol if spy else None, vix_term_ratio=spy.term_ratio if spy else None
        )
    history = _safe(_ten_year_history, None, "the 10-year history")
    if backdrop.ten_year_yield is None and history is not None:
        backdrop = backdrop.model_copy(
            update={
                "ten_year_yield": round(
                    float(history.iloc[-1]) / tnx_divisor(float(history.iloc[-1])), 2
                )
            }
        )
    for f in build_market_facts({}, backdrop).facts:  # VIX, VIX/VIX3M, the 10-year and its 5 days
        sheet.add(f.label, f.value, f.display)
    if history is not None and len(history) >= 22:
        last = float(history.iloc[-1])
        bp = (last - float(history.iloc[-22])) / tnx_divisor(last) * 100.0
        sheet.add("10y 1m change", round(bp), f"10y {bp:+.0f}bp 1m")
    return sheet, regimes, source


def upcoming_events(now: datetime) -> list[str]:
    """High-impact US releases and held-name earnings in the next seven days, soonest first."""
    today = now.astimezone(ET).date()
    held = held_underlyings()
    items: list[tuple[datetime, str]] = []
    with news_session() as s:
        for e in queries.econ_events_between(s, now, now + timedelta(days=_EVENT_DAYS)):
            if e.impact == "High":
                at = e.scheduled_at.astimezone(ET)
                items.append((at, f"{e.title} {at:%a %b %d %H:%M} ET"))
        for er in queries.earnings_between(s, today, today + timedelta(days=_EVENT_DAYS), held):
            slot = {"bmo": time(8, 0), "amc": time(16, 30)}.get(er.timing, time(12, 0))
            when = datetime.combine(er.report_date, slot, tzinfo=ET)
            timing = f" {er.timing.upper()}" if er.timing in ("bmo", "amc") else ""
            items.append((when, f"{er.symbol} earnings {er.report_date:%a %b %d}{timing} (held)"))
    items.sort(key=lambda t: t[0])
    return [text for _when, text in items[:_MAX_EVENTS]]


def _noise_summary(s: Session, now: datetime) -> NoiseSummary:
    since = now - timedelta(days=_NOISE_DAYS)
    views = queries.triage_since(s, since)
    return NoiseSummary(
        judged=sum(1 for v in views if v.pile == 3),
        # a floored cluster nobody judged is held at pile 2, never "not reviewed"
        not_reviewed=sum(1 for v in views if v.pile is None and not v.floor),
        promotions=sum(1 for v in views if v.promoted_at is not None and v.promoted_at >= since),
    )


# --- when to rebuild ------------------------------------------------------------------------


def _slot_passed(now: datetime, last: datetime, cfg: NewsDigestCfg) -> bool:
    """A pre-market or close digest time (ET, trading days) has passed since *last*."""
    et = now.astimezone(ET)
    if not is_trading_day(et.date()):
        return False
    for at in (cfg.premarket, cfg.close):
        hh, mm = at.split(":")
        slot = et.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if slot <= et and aware_utc(last) < slot:
            return True
    return False


def picture_due(now: datetime) -> bool:
    """Rebuild after a pre-market or close digest time has passed, or when the triage has judged
    a pile 1 cluster since the last build; the first picture is due at once. At most
    ``picture.max_rebuilds_per_day`` builds an ET day."""
    cfg = get_config().news
    if not cfg.picture.enabled:
        return False
    midnight = now.astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    with news_session() as s:
        built_today = (
            s.scalar(
                select(func.count(MarketPictureRow.id)).where(
                    MarketPictureRow.built_at >= naive_utc(midnight)
                )
            )
            or 0
        )
        if built_today >= cfg.picture.max_rebuilds_per_day:
            return False
        last = s.scalar(select(func.max(MarketPictureRow.built_at)))
        if last is None:
            return True
        new_story = s.scalar(
            select(func.count(StoryTriageRow.id)).where(
                StoryTriageRow.pile == 1, StoryTriageRow.judged_at > last
            )
        )
        touched = (
            cfg.dossier.touch_enabled
            and now - aware_utc(last) >= timedelta(minutes=cfg.picture.touch_min_age_min)
            and touched_since(s, MARKET, last)
        )
    return bool(new_story) or bool(touched) or _slot_passed(now, last, cfg.digests)


# --- the model's drafts ---------------------------------------------------------------------


@dataclass
class ValidStory:
    story_id: int | None  # None = a new story
    title: str
    description: str
    evidence: list[str]
    cluster_ids: list[int]  # the clusters it cited (pile 1 or 2, shown to the model)


def _clean(text: str, refs: list[float], rel_tol: float) -> str | None:
    """The text if nothing in it had to be trimmed: every number grounded, no advice, no talk
    about the inputs, no id in the prose. None otherwise: the story is dropped, not repaired."""
    kept, ungrounded = strip_ungrounded(text, refs, rel_tol)
    kept, meta = strip_meta_and_advice(kept)
    kept = kept.strip()
    if ungrounded or meta or not kept or _CLUSTER_IN_PROSE.search(kept):
        return None
    return kept


def validate_drafts(
    draft: PictureDraft,
    *,
    alive_ids: set[int],
    piles: dict[int, int],
    fact_ids: set[str],
    refs: list[float],
    rel_tol: float,
    max_stories: int,
) -> list[ValidStory]:
    """The stories of *draft* that pass Python's checks, in the model's order, at most *max_stories*.

    *piles* maps each cluster the model was shown to its triage pile; *alive_ids* are the
    stories Python still holds alive. A story id the model made up, or one Python has ended, is
    treated as a new story (so it needs a pile 1 cluster): the model cannot revive a story.
    """
    out: list[ValidStory] = []
    used: set[int] = set()
    for d in draft.stories:
        evidence: list[str] = []
        clusters: list[int] = []
        for raw in d.evidence:
            ref = raw.strip()
            m = _CLUSTER_REF.match(ref)
            if m and int(m.group(1)) in piles:
                cid = int(m.group(1))
                if ref not in evidence:
                    evidence.append(ref)
                    clusters.append(cid)
            elif ref in fact_ids and ref not in evidence:
                evidence.append(ref)
        if not evidence:
            continue
        story_id = d.story_id if d.story_id in alive_ids else None
        if story_id is not None:
            if story_id in used:
                continue
            used.add(story_id)
        elif not any(piles.get(cid) == 1 for cid in clusters):
            continue  # a new story must rest on a pile 1 cluster
        title = _clean(d.title, refs, rel_tol)
        description = _clean(d.description, refs, rel_tol)
        if title is None or description is None:
            continue
        out.append(ValidStory(story_id, title, description, evidence, clusters))
    return out[:max_stories]


# --- the build ------------------------------------------------------------------------------


def _alive_stories(
    stories: list[PictureStoryRow],
    attached: dict[int, list[int]],
    window_ids: set[int],
    *,
    now: datetime,
    window_days: int,
    min_new: int,
) -> tuple[list[PictureStoryRow], list[PictureStoryRow]]:
    """(alive, ended): a story lives while enough of its clusters were seen inside the window,
    or while it is younger than the window. Python alone decides this."""
    alive: list[PictureStoryRow] = []
    ended: list[PictureStoryRow] = []
    for st in stories:
        held = set(st.cluster_ids or []) | set(attached.get(st.id, []))
        support = sorted(held & window_ids)
        if story_alive(st, support, now=now, window_days=window_days, min_new=min_new):
            alive.append(st)
        else:
            ended.append(st)
    return alive, ended


def build_picture(now: datetime) -> MarketPicture | None:
    """Build, save and return the market picture (see the module docstring)."""
    cfg = get_config().news
    pcfg = cfg.picture
    today = now.astimezone(ET).date()
    window_start = now - timedelta(days=pcfg.story_window_days)

    sheet, regimes, regime_source = picture_facts(now)
    events: list[str] = _safe(lambda: upcoming_events(now), [], "the event calendar")
    seasonality = _safe(lambda: month_seasonality(today.month), None, "the seasonality")

    with news_session() as s:
        stories = queries.active_stories(s)
        views = queries.triage_since(s, window_start)
        noise = _noise_summary(s, now)
        recent = [v for v in views if v.pile in (1, 2)]
        wanted = {v.cluster_id for v in recent} | {
            cid for st in stories for cid in (st.cluster_ids or [])
        }
        clusters: dict[int, ClusterView] = {}
        for cid in wanted:
            cv = queries.cluster_view(s, cid, max_items=1)
            if cv is not None:
                clusters[cid] = cv

    window_ids = {v.cluster_id for v in recent if v.cluster_id in clusters}
    attached = match_clusters(stories, list(clusters.values()), jaccard=pcfg.story_match_jaccard)
    alive, ended = _alive_stories(
        stories,
        attached,
        window_ids,
        now=now,
        window_days=pcfg.story_window_days,
        min_new=pcfg.story_min_new_clusters,
    )

    ranked: list[TriageView] = sorted(
        (v for v in recent if v.cluster_id in clusters),
        key=lambda v: (v.pile or 9, -v.rank, -clusters[v.cluster_id].last_seen.timestamp()),
    )[:_PROMPT_CLUSTERS]
    piles = {v.cluster_id: int(v.pile or 2) for v in ranked}
    shown = [clusters[v.cluster_id] for v in ranked]

    valid: list[ValidStory] = []
    stale = False
    if alive or shown:
        out, _backend = validated_call(
            PictureDraft,
            picture_prompt(
                sheet,
                [(st.id, st.title, st.started_on) for st in alive],
                shown,
                events,
                piles=piles,
                max_stories=pcfg.max_stories,
            ),
            schema=PICTURE_SCHEMA,
            prefix="news:picture",
            now=now,
            purpose="picture",
        )
        if out is None:
            stale = True
        else:
            valid = validate_drafts(
                out,
                alive_ids={st.id for st in alive},
                piles=piles,
                fact_ids=sheet.ids(),
                refs=sheet.numbers(),
                rel_tol=cfg.grounding.rel_tol,
                max_stories=pcfg.max_stories,
            )

    shown_stories: list[PictureStory] = []
    with news_session() as s:
        for st in alive:  # attachments and support are Python's, whatever the model said
            row = s.get(PictureStoryRow, st.id)
            if row is None:
                continue
            new = attached.get(st.id, [])
            row.cluster_ids = sorted(set(row.cluster_ids or []) | set(new))
            if new or (set(row.cluster_ids) & window_ids):
                row.last_supported_at = naive_utc(now)
            _tag_triage(s, new, row.id)
        for st in ended:
            row = s.get(PictureStoryRow, st.id)
            if row is not None:
                row.active, row.ended_on = False, today
        for v in valid:
            if v.story_id is None:
                row = PictureStoryRow(
                    title=v.title,
                    started_on=today,
                    last_supported_at=naive_utc(now),
                    cluster_ids=sorted(set(v.cluster_ids)),
                    active=True,
                )
                s.add(row)
                s.flush()
                _tag_triage(s, v.cluster_ids, row.id)
            else:
                existing = s.get(PictureStoryRow, v.story_id)
                if existing is None:
                    continue
                row = existing
            shown_stories.append(
                PictureStory(
                    id=row.id,
                    title=row.title,  # identity is stored: the model's title for a known story is ignored
                    started_on=row.started_on,
                    description=v.description,
                    evidence=v.evidence,
                )
            )
        if stale:  # no model: the live stories by title, no prose
            shown_stories = [
                PictureStory(id=st.id, title=st.title, started_on=st.started_on) for st in alive
            ]
        picture = MarketPicture(
            version=now.astimezone(UTC).isoformat(),
            built_at=now,
            regimes=regimes,
            regime_source=regime_source,
            facts=[PictureFact(label=f.label, value=f.display) for f in sheet.facts],
            seasonality=seasonality,
            events=events,
            stories=shown_stories,
            noise=noise,
            stale=stale,
        )
        s.add(
            MarketPictureRow(
                built_at=naive_utc(now),
                version=picture.version,
                payload=picture.model_dump(mode="json"),
                stale=stale,
            )
        )
        consume_touches(s, [MARKET], now)
    return picture


def _tag_triage(s: Session, cluster_ids: list[int], story_id: int) -> None:
    """Record on each cluster's triage row which story it belongs to."""
    if not cluster_ids:
        return
    for row in s.scalars(select(StoryTriageRow).where(StoryTriageRow.cluster_id.in_(cluster_ids))):
        row.story_id = story_id
