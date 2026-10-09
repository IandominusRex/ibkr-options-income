"""Scheduled digests (spec §7.3): pre-market, close recap, week ahead. ET wall-clock schedule,
US trading days only (week-ahead runs on its weekday regardless)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from src.common.config import Config, NewsDigestCfg
from src.common.market_hours import is_trading_day
from src.common.schemas import PositionSnapshot
from src.news.facts import Analytics
from src.news.links import links_for
from src.news.render import SGT
from src.news.schemas import (
    CardKind,
    CardPayload,
    ClusterView,
    DigestItem,
    DigestRead,
    DigestSection,
    EarningsView,
    EconEventView,
)
from src.news.tape import Quote
from src.news.triggers import TickerMove

ET = ZoneInfo("America/New_York")
DigestName = Literal["premarket", "close", "week"]
_KIND: dict[DigestName, CardKind] = {
    "premarket": "digest_premarket",
    "close": "digest_close",
    "week": "digest_week",
}
_TITLE: dict[DigestName, str] = {
    "premarket": "Pre-market brief",
    "close": "Close recap",
    "week": "Week ahead",
}


def _hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def due_digests(now: datetime, sent: dict[str, str], cfg: NewsDigestCfg) -> list[DigestName]:
    et = now.astimezone(ET)
    today = et.date().isoformat()
    out: list[DigestName] = []
    if is_trading_day(et.date()):
        daily: tuple[tuple[DigestName, str], ...] = (
            ("premarket", cfg.premarket),
            ("close", cfg.close),
        )
        for name, at in daily:
            h, m = _hhmm(at)
            if (et.hour, et.minute) >= (h, m) and sent.get(name) != today:
                out.append(name)
    h, m = _hhmm(cfg.week_ahead_time)
    if (
        et.weekday() == cfg.week_ahead_weekday
        and (et.hour, et.minute) >= (h, m)
        and sent.get("week") != today
    ):
        out.append("week")
    return out


@dataclass
class DigestInputs:
    now: datetime
    tape: dict[str, Quote]
    clusters: list[ClusterView]
    econ: list[EconEventView]
    earnings: list[EarningsView]
    held: set[str]
    positions: list[PositionSnapshot]
    movers: list[TickerMove]
    regime: str | None = None
    thread_order: list[list[int]] | None = None
    reads: dict[int, DigestRead] = field(default_factory=dict)
    rank: list[str] = field(default_factory=list)
    max_threads: int = 6
    max_movers: int = 5


def _market(inp: DigestInputs) -> DigestSection:
    parts = [f"{s} {q.change_pct:+.1f}%" for s, q in inp.tape.items() if q.change_pct is not None]
    return DigestSection(title="Market", items=[DigestItem(text=" · ".join(parts) or "No quotes")])


def _stories(inp: DigestInputs, title: str) -> DigestSection:
    by_id = {c.id: c for c in inp.clusters}
    order = inp.thread_order or [[c.id] for c in inp.clusters]
    items = []
    for ids in order[: inp.max_threads]:
        cl = by_id.get(ids[0])
        if cl is None:
            continue
        e = inp.reads.get(ids[0])
        items.append(
            DigestItem(
                text=e.headline if e and e.headline else cl.headline,
                read=e.read if e else None,
                verdict=e.verdict if e else None,
                links=links_for(cl, inp.rank)[:2],
            )
        )
    return DigestSection(title=title, items=items)


def _calendar(inp: DigestInputs, title: str, start: date, end: date) -> DigestSection:
    items = [
        DigestItem(
            text=f"{e.scheduled_at.astimezone(SGT):%a %H:%M} SGT · {e.title} (est {e.forecast or e.consensus or 'n/a'})"
        )
        for e in inp.econ
        if start <= e.scheduled_at.astimezone(ET).date() <= end
    ]
    items += [
        DigestItem(
            text=f"{e.report_date:%a} · {e.symbol} earnings {e.timing.upper()}"
            + (" · HELD" if e.symbol in inp.held else "")
        )
        for e in inp.earnings
        if start <= e.report_date <= end
    ]
    return DigestSection(title=title, items=items)


def _movers(inp: DigestInputs) -> DigestSection:
    ranked = sorted(
        (m for m in inp.movers if m.change_pct is not None),
        key=lambda m: abs(m.change_pct or 0),
        reverse=True,
    )
    return DigestSection(
        title="Movers",
        items=[
            DigestItem(
                text=f"{m.symbol} {m.change_pct:+.1f}%"
                + (f" ({m.abnormal_pct:+.1f}% vs SPY)" if m.abnormal_pct is not None else "")
                + (f" · {m.sigma:.1f}σ" if m.sigma is not None else "")
                + (" · HELD" if m.symbol in inp.held else "")
            )
            for m in ranked[: inp.max_movers]
        ],
    )


def _expiry_risk(inp: DigestInputs) -> DigestSection:
    items = []
    for p in inp.positions:
        if p.sec_type != "OPT" or not p.expiry:
            continue
        sym = (p.underlying or p.symbol).upper()
        for e in inp.earnings:
            if e.symbol == sym and inp.now.astimezone(ET).date() <= e.report_date <= p.expiry:
                items.append(
                    DigestItem(
                        text=f"{sym} reports {e.report_date:%a %d %b} {e.timing.upper()} before your {p.strike:g}{p.right} expiring {p.expiry:%d %b}"
                    )
                )
    return DigestSection(title="Earnings before your expiries", items=items)


def build_digest(name: DigestName, inp: DigestInputs) -> CardPayload:
    today = inp.now.astimezone(ET).date()
    if name == "premarket":
        sections = [_market(inp), _stories(inp, "Overnight"), _calendar(inp, "Today", today, today)]
    elif name == "close":
        tomorrow = today + timedelta(days=1)
        sections = [
            _market(inp),
            _stories(inp, "Top stories"),
            _movers(inp),
            _calendar(inp, "Tonight / tomorrow", today, tomorrow),
        ]
    else:
        sections = [
            _calendar(inp, "This week", today, today + timedelta(days=6)),
            _expiry_risk(inp),
            _stories(inp, "Weekend stories"),
        ]
    return CardPayload(
        kind=_KIND[name],
        title=_TITLE[name],
        emoji="🗞️",
        when=inp.now,
        regime=inp.regime,
        sections=[s for s in sections if s.items],
    )


def gather_inputs(name: DigestName, *, now: datetime, cfg: Config, an: Analytics) -> DigestInputs:
    """Read the store + tape for a digest. Movers come from the service's last ticker sweep."""
    from src.news.collectors import held_positions, held_underlyings
    from src.news.store import queries
    from src.news.store.session import news_session
    from src.news.tape import tape

    since = now - timedelta(hours=16 if name != "week" else 72)
    today = now.astimezone(ET).date()
    with news_session() as s:
        clusters = queries.clusters_since(s, since, limit=30)
        econ = queries.econ_events_between(s, now - timedelta(hours=2), now + timedelta(days=7))
        earnings = queries.earnings_between(s, today, today + timedelta(days=7))
    syms = cfg.news.tape_symbols_rth if name != "premarket" else cfg.news.tape_symbols_ext
    return DigestInputs(
        now=now,
        tape=tape(syms),
        clusters=[c for c in clusters if c.category != "ticker" or c.source_count >= 2],
        econ=econ,
        earnings=earnings,
        held=held_underlyings(),
        positions=held_positions(),
        movers=[],
        rank=cfg.news.source_rank,
        max_threads=cfg.news.digests.max_threads,
        max_movers=cfg.news.digests.max_movers,
    )
