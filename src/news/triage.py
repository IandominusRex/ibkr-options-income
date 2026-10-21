"""Three-pile triage (spec section 7): Python sorts and floors, one batched model call judges.

The pipeline is deterministic first. ``presort`` ranks every new cluster from trigger hits, held
names, the macro categories, source counts and topic tags, so the model sees a bounded, ranked
batch. The model puts each cluster in a pile (1 shapes the picture, 2 worth telling, 3 noise);
the **floor** then holds whatever it said: a story an alert rule fired on, or one about a held
name, is never below pile 2. Everything outside the batch is stored as *not reviewed*, which is
different from *judged noise*, and the page shows both.

Enrichment tier: it reads the news store and the portfolio's held names, and reaches nothing in
the trading path.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from src.common.config import get_config
from src.common.market_hours import is_trading_day
from src.common.picture_text import render_picture
from src.common.schemas import MarketPicture
from src.news.collectors import held_underlyings
from src.news.explain import validated_call
from src.news.prompts import TRIAGE_SCHEMA, triage_prompt
from src.news.schemas import ClusterView, TriageItem, TriageOutput, TriageView
from src.news.store import queries
from src.news.store.models import NewsClusterRow, NewsPostRow, StoryTriageRow
from src.news.store.queries import aware_utc, naive_utc
from src.news.store.session import news_session
from src.news.store.state import get_state, set_state

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

Floor = Literal["alert", "held"]
STATE_LAST_RUN = "triage_last_run"
STATE_LAST_OK = "triage_last_ok"  # the last time the model's answer was usable
FLOOR_REASON: dict[str, str] = {"alert": "floor: alert rule", "held": "floor: held name"}
_MACRO_CATEGORIES = ("macro", "government", "geopolitics")
_FIRST_RUN_HOURS = 16  # how far back the first run ever (or one after a long outage) looks
_MAX_LOOKBACK_HOURS = 48
_REGATE_HOURS = 48  # a cluster this recent can still gain a floor (a later alert, a new holding)


@dataclass
class TriageCandidate:
    cluster: ClusterView
    floor: Floor | None
    rank: float


def floor_for(
    cluster_id: int, tickers: Iterable[str], *, held: set[str], alerted_ids: set[int]
) -> Floor | None:
    """Why this story may not fall to noise, if it may not: an alert rule fired on it (it was
    posted), else it names a held underlying. The alert reason wins."""
    if cluster_id in alerted_ids:
        return "alert"
    if held.intersection(tickers):
        return "held"
    return None


def presort(
    clusters: list[ClusterView], *, held: set[str], alerted_ids: set[int], limit: int
) -> list[TriageCandidate]:
    """Rank *clusters* and keep the top *limit*. Rank = 3 if an alert fired + 2 if held + the
    source count (capped at 5, scaled to 1) + 1 for a macro-ish category + 1 for a known topic;
    ties go to the cluster seen last."""
    out: list[TriageCandidate] = []
    for c in clusters:
        floor = floor_for(c.id, c.tickers, held=held, alerted_ids=alerted_ids)
        rank = (
            (3.0 if floor == "alert" else 0.0)
            + (2.0 if floor == "held" else 0.0)
            + min(c.source_count, 5) / 5
            + (1.0 if c.category in _MACRO_CATEGORIES else 0.0)
            + (1.0 if c.topic_class != "other" else 0.0)
        )
        out.append(TriageCandidate(cluster=c, floor=floor, rank=rank))
    out.sort(key=lambda t: (-t.rank, -t.cluster.last_seen.timestamp()))
    return out[:limit]


def apply_floor(pile: int, floor: str | None) -> int:
    """Pile 1 is the highest. A floored story is at least pile 2; the model may only move it up."""
    return min(pile, 2) if floor else pile


def triage_due(now: datetime, last_run: datetime | None, times: list[str]) -> bool:
    """True when one of today's ET batch *times* has passed since the last run (trading days only)."""
    et = now.astimezone(ET)
    if not is_trading_day(et.date()):
        return False
    for t in times:
        hh, mm = t.split(":")
        slot = et.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if slot <= et and (last_run is None or aware_utc(last_run) < slot):
            return True
    return False


def ranked_threads(views: list[TriageView], *, limit: int) -> list[int]:
    """Cluster ids a digest shows: pile 1 first, then pile 2, each by rank. A floored story is
    always eligible (a floored cluster nobody gave a pile counts as pile 2); noise and clusters
    nobody reviewed are not shown."""

    def pile(v: TriageView) -> int | None:
        if v.pile is None and v.floor:
            return 2
        return v.pile

    shown = [v for v in views if pile(v) in (1, 2)]
    shown.sort(key=lambda v: (pile(v), -v.rank, v.cluster_id))
    return [v.cluster_id for v in shown[:limit]]


def _state_time(key: str) -> datetime | None:
    raw = get_state(key)
    if not raw:
        return None
    try:
        return aware_utc(datetime.fromisoformat(raw))
    except ValueError:
        return None


def _last_run() -> datetime | None:
    return _state_time(STATE_LAST_RUN)


def triage_ok_since(since: datetime) -> bool:
    """True when the model judged a batch at or after *since*. Without that the stored piles are
    only floors and not-reviewed rows, so a digest keeps its deterministic order instead."""
    last = _state_time(STATE_LAST_OK)
    return last is not None and last >= aware_utc(since)


def _alerted_ids(now: datetime) -> set[int]:
    """Clusters a non-digest post (an alert card) was made for recently."""
    with news_session() as s:
        rows = s.scalars(
            select(NewsPostRow.cluster_ids).where(
                NewsPostRow.posted_at >= naive_utc(now - timedelta(hours=_REGATE_HOURS)),
                NewsPostRow.kind.not_like("digest%"),
            )
        )
        return {int(cid) for ids in rows for cid in (ids or [])}


def _regate(s, now: datetime, *, held: set[str], alerted_ids: set[int]) -> tuple[list[int], int]:
    """Rows stored without a floor whose story has since gained one. Not reviewed (no pile) ones
    come back to be judged; judged-noise ones are lifted to pile 2 on the spot, no call needed.
    Returns (cluster ids to judge again, rows lifted)."""
    rows = s.execute(
        select(StoryTriageRow, NewsClusterRow.tickers)
        .join(NewsClusterRow, NewsClusterRow.id == StoryTriageRow.cluster_id)
        .where(
            StoryTriageRow.floor.is_(None),
            or_(StoryTriageRow.pile.is_(None), StoryTriageRow.pile == 3),
            NewsClusterRow.last_seen >= naive_utc(now - timedelta(hours=_REGATE_HOURS)),
        )
    ).all()
    again: list[int] = []
    lifted = 0
    for row, tickers in rows:
        floor = floor_for(row.cluster_id, tickers or [], held=held, alerted_ids=alerted_ids)
        if floor is None:
            continue
        if row.pile is None:
            again.append(row.cluster_id)
        else:
            row.pile, row.floor = 2, floor
            row.reason = f"{FLOOR_REASON[floor]} (was noise: {row.reason})"[:160]
            lifted += 1
    return again, lifted


def _store(
    s, cand: TriageCandidate, *, pile: int | None, reason: str, judged_at: datetime | None
) -> None:
    row = s.scalar(select(StoryTriageRow).where(StoryTriageRow.cluster_id == cand.cluster.id))
    if row is None:
        row = StoryTriageRow(cluster_id=cand.cluster.id)
        s.add(row)
    row.pile, row.floor, row.rank, row.reason = pile, cand.floor, cand.rank, reason
    row.judged_at = naive_utc(judged_at) if judged_at else None


def run_triage(now: datetime, *, picture: MarketPicture | None) -> int:
    """Triage every cluster not yet in ``story_triage`` (plus ones that gained a floor since).

    The top ``triage.batch_size`` by presort rank go to the model in one call (the picture
    budget); the rest are stored as not reviewed, with their rank. A floored cluster the model
    did not (or could not) judge is stored at pile 2 with the floor as its reason. Returns the
    number of clusters the model judged.
    """
    cfg = get_config().news
    held = held_underlyings()
    alerted = _alerted_ids(now)
    last = _last_run()
    since = max(
        last if last is not None else now - timedelta(hours=_FIRST_RUN_HOURS),
        now - timedelta(hours=_MAX_LOOKBACK_HOURS),
    )
    with news_session() as s:
        clusters = queries.clusters_since(s, since, limit=5000)
        have = set(
            s.scalars(
                select(StoryTriageRow.cluster_id).where(
                    StoryTriageRow.cluster_id.in_([c.id for c in clusters])
                )
            )
        )
        fresh = [c for c in clusters if c.id not in have]
        again_ids, _lifted = _regate(s, now, held=held, alerted_ids=alerted)
        again = [cv for cid in again_ids if (cv := queries.cluster_view(s, cid)) is not None]
    ranked = presort(fresh + again, held=held, alerted_ids=alerted, limit=len(fresh) + len(again))
    batch, rest = ranked[: cfg.triage.batch_size], ranked[cfg.triage.batch_size :]

    answers: dict[int, TriageItem] = {}
    if batch:
        text = (
            render_picture(picture, now=now, staleness_hours=cfg.picture.staleness_hours)
            if picture is not None
            else None
        )
        out, _backend = validated_call(
            TriageOutput,
            triage_prompt(batch, text),
            schema=TRIAGE_SCHEMA,
            prefix="news:triage",
            now=now,
            purpose="picture",
        )
        if out is not None:
            set_state(STATE_LAST_OK, now.astimezone(UTC).isoformat(), now=now)
            ids = {c.cluster.id for c in batch}
            for answer in out.items:
                if answer.cluster_id in ids:
                    answers.setdefault(answer.cluster_id, answer)  # the first answer for an id

    with news_session() as s:
        for cand in batch:
            item = answers.get(cand.cluster.id)
            if item is not None:
                pile = apply_floor(item.pile, cand.floor)
                reason = item.reason
                if cand.floor and pile != item.pile:
                    reason = f"{FLOOR_REASON[cand.floor]} (model: {item.reason})"[:160]
                _store(s, cand, pile=pile, reason=reason, judged_at=now)
            else:
                _store_unjudged(s, cand, now)
        for cand in rest:
            _store_unjudged(s, cand, now)
    set_state(STATE_LAST_RUN, now.astimezone(UTC).isoformat(), now=now)
    return len(answers)


def _store_unjudged(s, cand: TriageCandidate, now: datetime) -> None:
    """No model verdict: a floored story still is pile 2 (the floor is its reason); any other
    stays not reviewed."""
    if cand.floor:
        _store(s, cand, pile=2, reason=FLOOR_REASON[cand.floor], judged_at=now)
    else:
        _store(s, cand, pile=None, reason="", judged_at=None)
