"""Which names Claude reads, when, and at what cost (spec §8.3, §8.5).

The queue lives in ``value_claude_reads``. Priority, as the spec orders it: the operator's
requests, then re-evaluations of held names, then filing reads (held and READY names on a new
10-K/10-Q), then the top-ranked healthy names Claude has not read, then stale re-reads. Never the
evidence universe or a shadow position. A name is re-read only when its filings, Python's fair
value (by more than ``stale_fv_pct``) or its age (``max_age_days``) say so, so the steady state is
a handful of reads a day. Caps: ``standard_reads_per_day`` (standard and review reads) and
``deep_reads_per_day`` (filing reads), counted per ET day.

The reads themselves happen in ``run_queue`` through a *reader* the entrypoint passes in
(``scripts/run_value.py`` wraps ``src.value_ai``): this module never imports Claude. Each read is
its own transaction, outside the night's, because a call takes tens of seconds.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.common.config import ValueCfg, get_config
from src.common.value_ai_types import (
    KILL_KINDS,
    AnalystRequest,
    AnalystResult,
    FilingSection,
    Range,
)
from src.common.value_types import FilingEvent, ValueFinancials
from src.value.claude_valuation import bounds_for
from src.value.claude_verdicts import accept
from src.value.schemas import LISTS, ValueScorecard
from src.value.store import (
    ValueClaudeReadRow,
    ValueClaudeVerdictRow,
    ValueReevaluationRow,
    ValueTickerFileRow,
    value_session,
)

log = logging.getLogger(__name__)

PRIORITY = {"request": 0, "review": 1, "filing": 2, "top": 3, "stale": 4}
DEEP_KINDS = ("filing",)
FILING_WAIT_DAYS = 7  # a filing read whose sections never arrive is dropped after a week
Reader = Callable[[AnalystRequest], AnalystResult]
SectionsFor = Callable[[str, str], list[FilingSection]]
FinancialsFor = Callable[[str], ValueFinancials | None]


def _fmt(v: float | None, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%" if pct else f"{v:,.2f}"


def _fmt_m(v: float | None) -> str:
    """Raw US dollars (companyfacts) as millions."""
    return "n/a" if v is None else f"{v / 1e6:,.2f}M"


def render_card(card: ValueScorecard) -> str:
    """The scorecard as labelled numbers for the prompt (unknown is ``n/a``, never zero)."""
    m = card.metrics
    lines = [
        f"{card.symbol} · {card.classification.sector or 'n/a'} / "
        f"{card.classification.industry or 'n/a'} · class {card.company_class} · as of "
        f"{card.as_of} · price {_fmt(card.price)}",
        f"health {card.health}; data quality {card.data_quality}",
        "health checks: "
        + "; ".join(
            f"{c.id.removeprefix('health.')} {c.state} ({_fmt(c.actual)} vs {_fmt(c.threshold)})"
            for c in card.health_checks
        ),
        f"TTM FCF {_fmt_m(m.get('fcf_ttm'))} · SBC {_fmt_m(m.get('sbc_ttm'))} · revenue "
        f"{_fmt_m(m.get('revenue_ttm'))} · revenue/share {_fmt(m.get('revenue_ps_ttm'))}",
        f"5-year revenue CAGR {_fmt(m.get('revenue_cagr_5y'), True)} · FCF/share CAGR "
        f"{_fmt(card.realised_fcf_ps_cagr, True)} · last year's revenue growth "
        f"{_fmt(m.get('revenue_growth_1y'), True)}",
        f"FCF margin (less SBC) 5y median {_fmt(m.get('fcf_margin_median_5y'), True)}, best "
        f"{_fmt(m.get('fcf_margin_best_5y'), True)} · gross margin "
        f"{_fmt(m.get('gross_margin_latest'), True)} · ROIC 5y median "
        f"{_fmt(m.get('roic_median_5y'), True)}",
        f"the price implies {_fmt(card.reverse_dcf_implied_growth, True)} a year of FCF growth "
        "for ten years (reverse DCF)",
    ]
    if m.get("rote_median_5y") is not None:
        lines.append(
            f"ROTE 5y median {_fmt(m.get('rote_median_5y'), True)} · tangible book/share "
            f"{_fmt(m.get('tbv_ps'))}"
        )
    for name, ev in card.lists.items():
        methods = ", ".join(
            f"{x.method} {_fmt(x.value)} ({x.state})" for x in ev.methods if x.state != "absent"
        )
        lines.append(
            f"{name}: Python {card.verdict_for(name)} · fair value {_fmt(ev.fair_value)} "
            f"[{methods or 'no method'}] · required margin {ev.required_mos_pct:g}% · ceiling "
            f"{_fmt(ev.entry_ceiling)} · timing {ev.timing} · entry rule {ev.entry}"
        )
    return "\n".join(lines)


def kill_menu(cfg: ValueCfg) -> dict[str, Range | None]:
    bounds = cfg.rules.claude.kill_bounds
    return {
        k: (Range(lo=bounds[k][0], hi=bounds[k][1]) if k in bounds else None) for k in KILL_KINDS
    }


def _card(vs: Session, symbol: str) -> ValueScorecard | None:
    row = vs.get(ValueTickerFileRow, symbol)
    return None if row is None else ValueScorecard.model_validate_json(row.scorecard_json)


def _healthy_lists(card: ValueScorecard) -> list[str]:
    return [n for n in LISTS if card.verdict_for(n) in ("READY", "WATCH", "WAIT")]


def build_request(
    row: ValueClaudeReadRow,
    card: ValueScorecard,
    cfg: ValueCfg,
    *,
    trigger_text: str = "",
    sections: list[FilingSection] | None = None,
) -> AnalystRequest:
    lists = _healthy_lists(card)
    kind_model = {"standard": "verdict", "filing": "filing", "review": "review"}[row.kind]
    model = getattr(cfg.claude.models, kind_model) or get_config().claude.model
    return AnalystRequest(
        read_id=row.id,
        symbol=row.symbol,
        kind=row.kind,  # type: ignore[arg-type]  # validated against ReadKind
        reason=row.reason,
        lists=lists,
        card_text=render_card(card),
        bounds=[b for n in lists if (b := bounds_for(card, n, cfg.rules)) is not None],
        kill_menu=kill_menu(cfg),
        max_kill_triggers=cfg.rules.claude.max_kill_triggers,
        trigger_text=trigger_text,
        sections=sections or [],
        model=model,
        effort=cfg.claude.effort,
        timeout_seconds=cfg.claude.filing_timeout_seconds
        if row.kind == "filing"
        else cfg.claude.timeout_seconds,
    )


def queue_read(
    vs: Session,
    symbol: str,
    *,
    kind: str,
    reason: str,
    now: datetime,
    accn: str | None = None,
    reevaluation_id: int | None = None,
) -> ValueClaudeReadRow | None:
    """Queue one read unless the same name already has one queued (requests jump the queue by
    priority, they do not stack)."""
    queued = vs.scalars(
        select(ValueClaudeReadRow).where(
            ValueClaudeReadRow.symbol == symbol,
            ValueClaudeReadRow.kind == kind,
            ValueClaudeReadRow.status == "queued",
        )
    ).first()
    if queued is not None:
        if PRIORITY[reason] < queued.priority:
            queued.reason, queued.priority = reason, PRIORITY[reason]
        return None
    row = ValueClaudeReadRow(
        symbol=symbol,
        kind=kind,
        reason=reason,
        priority=PRIORITY[reason],
        status="queued",
        requested_at=now,
        accn=accn,
        reevaluation_id=reevaluation_id,
    )
    vs.add(row)
    vs.flush()
    return row


def _et_day_start(now: datetime) -> datetime:
    """Midnight ET of *now*'s ET day, as naive UTC (the tables' clock)."""
    tz = ZoneInfo(get_config().scheduler.timezone)
    local = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def reads_left(vs: Session, now: datetime, cfg: ValueCfg) -> tuple[int, int]:
    """(standard and review reads left today, filing reads left today)."""
    since = _et_day_start(now)
    rows = vs.execute(
        select(ValueClaudeReadRow.kind, func.count())
        .where(
            ValueClaudeReadRow.read_at.is_not(None),
            ValueClaudeReadRow.read_at >= since,
        )
        .group_by(ValueClaudeReadRow.kind)
    ).all()
    used = {kind: n for kind, n in rows}
    deep = sum(used.get(k, 0) for k in DEEP_KINDS)
    standard = sum(n for k, n in used.items() if k not in DEEP_KINDS)
    return (
        max(0, cfg.claude.standard_reads_per_day - standard),
        max(0, cfg.claude.deep_reads_per_day - deep),
    )


def stale(
    verdict: ValueClaudeVerdictRow, card: ValueScorecard, cfg: ValueCfg, now: datetime
) -> bool:
    """Spec §8.3 "tied to the numbers it saw": a new filing, Python's fair value moved by more
    than ``stale_fv_pct``, or older than ``max_age_days``. Price alone never makes it stale."""
    if card.fingerprint.latest_accn != verdict.accn:
        return True
    ev = card.lists.get(verdict.list_name)
    now_fv, then_fv = (ev.fair_value if ev else None), verdict.python_fair_value
    if (now_fv is None) != (then_fv is None):
        return True
    if now_fv and then_fv and abs(now_fv / then_fv - 1.0) * 100.0 > cfg.claude.stale_fv_pct:
        return True
    return now - verdict.created_at > timedelta(days=cfg.claude.max_age_days)


def plan_auto_reads(vs: Session, now: datetime, cfg: ValueCfg) -> dict[str, int]:
    """After a night: queue the top-ranked unread healthy trading names per list and the stale
    re-reads; drop yesterday's automatic reads the budget never reached. Requests and reviews
    stay queued."""
    for old in vs.scalars(
        select(ValueClaudeReadRow).where(
            ValueClaudeReadRow.status == "queued",
            ValueClaudeReadRow.reason.in_(("top", "stale")),
        )
    ):
        old.status, old.detail = "skipped", "superseded by the next night's plan"
    files = vs.scalars(
        select(ValueTickerFileRow).where(ValueTickerFileRow.universe == "trading")
    ).all()
    latest: dict[str, list[ValueClaudeVerdictRow]] = {}
    for v in vs.scalars(
        select(ValueClaudeVerdictRow).where(
            ValueClaudeVerdictRow.superseded.is_(False), ValueClaudeVerdictRow.backend == "cli"
        )
    ):
        latest.setdefault(v.symbol, []).append(v)
    counts = {"top": 0, "stale": 0}
    picked: set[str] = set()
    for rank_attr, verdict_attr in (
        ("rank_deep", "verdict_deep"),
        ("rank_growth", "verdict_growth"),
    ):
        healthy = [
            f
            for f in files
            if f.health == "pass"
            and getattr(f, verdict_attr) in ("READY", "WATCH", "WAIT")
            and getattr(f, rank_attr) is not None
        ]
        healthy.sort(key=lambda f: (-getattr(f, rank_attr), f.symbol))
        for f in healthy[: cfg.claude.top_per_list]:
            if f.symbol in picked:
                continue
            card = ValueScorecard.model_validate_json(f.scorecard_json)
            seen = latest.get(f.symbol, [])
            if not seen:
                reason = "top"
            elif any(stale(v, card, cfg, now) for v in seen):
                reason = "stale"
            else:
                continue
            if queue_read(vs, f.symbol, kind="standard", reason=reason, now=now) is not None:
                counts[reason] += 1
            picked.add(f.symbol)
    return counts


def plan_filing_reads(vs: Session, latest: dict[str, FilingEvent], now: datetime) -> int:
    """Queue a filing read of each name's newest periodic filing that has not had one (held and
    READY names, spec §8.3: "a filing read on each new 10-K/10-Q"). *latest*: from
    ``value_inputs.latest_periodic`` for the names that qualify tonight."""
    queued = 0
    for symbol, filing in sorted(latest.items()):
        seen = vs.scalars(
            select(ValueClaudeReadRow.id).where(
                ValueClaudeReadRow.symbol == symbol,
                ValueClaudeReadRow.kind == "filing",
                ValueClaudeReadRow.accn == filing.accn,
            )
        ).first()
        if seen is not None:
            continue
        if (
            queue_read(vs, symbol, kind="filing", reason="filing", now=now, accn=filing.accn)
            is not None
        ):
            queued += 1
    return queued


def _review_text(vs: Session, reevaluation_id: int | None) -> str:
    if reevaluation_id is None:
        return ""
    r = vs.get(ValueReevaluationRow, reevaluation_id)
    if r is None:
        return ""
    return (
        f"opened {r.session} ({r.severity}); triggers {r.triggers_json}; plan before "
        f"{r.plan_before_json}; plan after {r.plan_after_json}; verdict at entry "
        f"{r.verdict_at_entry}, now {r.verdict_now or 'n/a'}"
    )


def run_queue(
    reader: Reader,
    *,
    now: datetime,
    cfg: ValueCfg,
    sections_for: SectionsFor | None = None,
    financials_for: FinancialsFor | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run queued reads, best priority first, within today's caps. A filing read whose sections
    are not in research.db yet waits (the research worker fetches them). Returns counts."""
    summary: dict[str, Any] = {"done": 0, "failed": 0, "skipped": 0, "waiting": 0}
    if not cfg.claude.enabled:
        return summary
    with value_session() as vs:
        ids = list(
            vs.scalars(
                select(ValueClaudeReadRow.id)
                .where(ValueClaudeReadRow.status == "queued")
                .order_by(ValueClaudeReadRow.priority, ValueClaudeReadRow.id)
            )
        )
    for read_id in ids[:limit] if limit is not None else ids:
        with value_session() as vs:
            row = vs.get(ValueClaudeReadRow, read_id)
            if row is None or row.status != "queued":
                continue
            standard_left, deep_left = reads_left(vs, now, cfg)
            if (deep_left if row.kind in DEEP_KINDS else standard_left) <= 0:
                continue
            card = _card(vs, row.symbol)
            if card is None or not _healthy_lists(card) and row.kind != "filing":
                row.status, row.detail = "skipped", "no healthy list to read"
                summary["skipped"] += 1
                continue
            sections: list[FilingSection] = []
            if row.kind == "filing":
                sections = sections_for(row.symbol, row.accn or "") if sections_for else []
                if not sections:
                    if now - row.requested_at > timedelta(days=FILING_WAIT_DAYS):
                        row.status, row.detail = "skipped", "the filing's sections never arrived"
                        summary["skipped"] += 1
                    else:
                        summary["waiting"] += 1
                    continue
            req = build_request(
                row,
                card,
                cfg,
                trigger_text=_review_text(vs, row.reevaluation_id),
                sections=sections,
            )
        result = reader(req)  # outside any transaction: a call takes tens of seconds
        with value_session() as vs:
            row = vs.get(ValueClaudeReadRow, read_id)
            card = _card(vs, row.symbol) if row is not None else None
            if row is None or card is None:
                continue
            try:
                done = accept(
                    vs,
                    row,
                    result,
                    card,
                    cfg,
                    now=now,
                    sections=sections,
                    financials=financials_for(row.symbol)
                    if financials_for and row.kind == "filing"
                    else None,
                )
            except Exception as exc:  # noqa: BLE001 - the call is paid for; never re-spend it
                # Review M6: left queued, a crash here re-ran the same Claude call every poll,
                # outside the daily caps (those count committed ``read_at``). Close the read.
                log.exception("value claude read %s %s: accept crashed", row.symbol, row.kind)
                vs.rollback()
                row = vs.get(ValueClaudeReadRow, read_id)
                if row is not None:
                    row.status, row.read_at = "failed", now
                    row.error = type(exc).__name__[:32]
                    row.detail = f"accept crashed: {exc}"[:500]
                summary["failed"] += 1
                continue
            summary["done" if result.reply is not None else "failed"] += 1
            log.info(
                "value claude read %s %s (%s): %s; %d verdict(s), %d trigger(s)",
                row.symbol,
                row.kind,
                row.reason,
                row.status,
                done.verdicts,
                done.triggers,
            )
    return summary
