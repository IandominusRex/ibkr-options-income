"""Alert detection (spec §7.2). Detectors are pure; AlertGate holds the once-per-day and
hourly-cap bookkeeping in data/news.db."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.common.config import NewsAlertsCfg
from src.news.playbook import Playbook
from src.news.schemas import ClusterView, EarningsView, EconEventView
from src.news.store.models import AlertStateRow, NewsPostRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from src.news.tape import Quote

AlertKind = Literal[
    "macro_print", "earnings", "market_move", "vix_spike", "ticker_move", "breaking"
]


class AlertCandidate(BaseModel):
    kind: AlertKind
    subject: str
    critical: bool
    symbols: list[str] = Field(default_factory=list)
    event_keys: list[str] = Field(default_factory=list)
    cluster_ids: list[int] = Field(default_factory=list)
    detail: dict[str, float | str | None] = Field(default_factory=dict)


class TickerMove(BaseModel):
    symbol: str
    change_pct: float | None = None
    abnormal_pct: float | None = None
    sigma: float | None = None


def group_macro_releases(events: list[EconEventView], pb: Playbook) -> list[AlertCandidate]:
    """One card per release time (spec §7.2). A high-impact release alerts and is critical; a
    medium one alerts only when the playbook knows it (claims, ISM services, UoM), and never
    critically. Other medium releases stay on the calendar and in digests."""
    groups: dict[datetime, list[EconEventView]] = {}
    for e in events:
        if e.impact == "High" or pb.match(e.title) is not None:
            groups.setdefault(e.scheduled_at, []).append(e)
    out = []
    for at, evs in sorted(groups.items()):
        ranked = sorted(evs, key=lambda e: pb.priority(m.key) if (m := pb.match(e.title)) else 999)
        out.append(
            AlertCandidate(
                kind="macro_print",
                subject=f"{at:%Y-%m-%dT%H:%M}",
                critical=any(e.impact == "High" for e in evs),
                event_keys=[e.event_key for e in ranked],
                detail={"primary": ranked[0].title},
            )
        )
    return out


def detect_earnings(
    released: list[EarningsView], *, held: set[str], universe: set[str]
) -> list[AlertCandidate]:
    return [
        AlertCandidate(
            kind="earnings", subject=e.symbol, critical=e.symbol in held, symbols=[e.symbol]
        )
        for e in released
        if e.symbol in held or e.symbol in universe
    ]


def detect_index_levels(tape: dict[str, Quote], cfg: NewsAlertsCfg) -> list[AlertCandidate]:
    out = []
    for sym in cfg.index_symbols:
        chg = (tape.get(sym) or Quote(symbol=sym)).change_pct
        if chg is None:
            continue
        for lvl in cfg.index_levels_down:
            if chg <= lvl:
                out.append(
                    AlertCandidate(
                        kind="market_move",
                        subject=f"{sym}:{lvl:+.0f}",
                        critical=lvl <= cfg.critical_index_level,
                        symbols=[sym],
                        detail={"level": lvl, "change_pct": chg},
                    )
                )
        for lvl in cfg.index_levels_up:
            if chg >= lvl:
                out.append(
                    AlertCandidate(
                        kind="market_move",
                        subject=f"{sym}:{lvl:+.0f}",
                        critical=False,
                        symbols=[sym],
                        detail={"level": lvl, "change_pct": chg},
                    )
                )
    return out


def pick_new_levels(cands: list[AlertCandidate], fired: set[str]) -> list[AlertCandidate]:
    best: dict[str, AlertCandidate] = {}
    for c in cands:
        if c.subject in fired:
            continue
        sym = c.symbols[0]
        cur = best.get(sym)
        if cur is None or abs(float(c.detail["level"] or 0)) > abs(float(cur.detail["level"] or 0)):
            best[sym] = c
    return list(best.values())


def detect_vix(q: Quote, cfg: NewsAlertsCfg) -> list[AlertCandidate]:
    out = []
    if q.change_pct is not None and q.change_pct >= cfg.vix_jump_pct:
        out.append(
            AlertCandidate(
                kind="vix_spike",
                subject="VIX:jump",
                critical=True,
                symbols=["^VIX"],
                detail={"change_pct": q.change_pct},
            )
        )
    for lvl in cfg.vix_levels:
        if q.last is not None and q.last >= lvl and (q.prev_close is None or q.prev_close < lvl):
            out.append(
                AlertCandidate(
                    kind="vix_spike",
                    subject=f"VIX:{lvl:.0f}",
                    critical=True,
                    symbols=["^VIX"],
                    detail={"level": lvl, "last": q.last},
                )
            )
    return out


def detect_ticker_moves(
    moves: list[TickerMove], *, held: set[str], universe: set[str], cfg: NewsAlertsCfg
) -> list[AlertCandidate]:
    out = []
    for m in moves:
        if m.sigma is None:
            continue
        is_held = m.symbol in held
        threshold = cfg.held_sigma if is_held else cfg.universe_sigma
        if (is_held or m.symbol in universe) and m.sigma >= threshold:
            out.append(
                AlertCandidate(
                    kind="ticker_move",
                    subject=m.symbol,
                    critical=is_held,
                    symbols=[m.symbol],
                    detail={
                        "change_pct": m.change_pct,
                        "abnormal_pct": m.abnormal_pct,
                        "sigma": m.sigma,
                    },
                )
            )
    return out


def detect_breaking(
    clusters: list[ClusterView], *, reactions: dict[int, float | None], cfg: NewsAlertsCfg
) -> list[AlertCandidate]:
    """*reactions* maps a cluster id to the ES/SPY % move within
    ``geo_reaction_window_min`` of that cluster's first_seen (``reaction.move_after``)."""
    out = []
    for c in clusters:
        mv = reactions.get(c.id)
        if mv is None or abs(mv) < cfg.geo_reaction_pct:
            continue
        if c.source_count >= cfg.geo_min_sources and c.topic_class in cfg.geo_topics:
            out.append(
                AlertCandidate(
                    kind="breaking",
                    subject=f"cluster:{c.id}",
                    critical=True,
                    cluster_ids=[c.id],
                    detail={"reaction_pct": mv},
                )
            )
    return out


class AlertGate:
    def __init__(self, cfg: NewsAlertsCfg) -> None:
        self.cfg = cfg

    def fired_subjects(self, trigger: str, day: date) -> set[str]:
        with news_session() as s:
            return set(
                s.scalars(
                    select(AlertStateRow.subject).where(
                        AlertStateRow.trigger == trigger, AlertStateRow.trade_date == day
                    )
                )
            )

    def mark(self, trigger: str, subject: str, day: date, now: datetime) -> None:
        try:
            with news_session() as s:
                s.add(
                    AlertStateRow(
                        trigger=trigger, subject=subject, trade_date=day, fired_at=naive_utc(now)
                    )
                )
        except IntegrityError:
            pass

    def hourly_noncritical(self, now: datetime) -> int:
        kinds = ("macro_print", "earnings", "market_move", "vix_spike", "ticker_move", "breaking")
        with news_session() as s:
            return int(
                s.scalar(
                    select(func.count(NewsPostRow.id)).where(
                        NewsPostRow.posted_at >= naive_utc(now - timedelta(hours=1)),
                        NewsPostRow.critical.is_(False),
                        NewsPostRow.kind.in_(kinds),
                    )
                )
                or 0
            )

    def admit(self, c: AlertCandidate, *, now: datetime, day: date) -> bool:
        if c.subject in self.fired_subjects(c.kind, day):
            return False
        if not c.critical and self.hourly_noncritical(now) >= self.cfg.max_per_hour:
            return False
        self.mark(c.kind, c.subject, day, now)
        return True
