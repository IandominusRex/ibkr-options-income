"""Persist + publish a card (spec §7). The store is written first-class: a post that cannot
reach Telegram is still recorded (the web page shows it)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from src.common.config import ROOT, Config
from src.common.schemas import OptionRight, PositionSnapshot
from src.news.charts import price_chart, save_chart
from src.news.facts import Analytics
from src.news.publish import Publisher
from src.news.quiet import silent_for
from src.news.render import render_card
from src.news.schemas import CardPayload, FactSheet
from src.news.store.models import NewsPostRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session


async def post_card(
    payload: CardPayload,
    *,
    publisher: Publisher | None,
    cfg: Config,
    now: datetime,
    chart: bytes | None = None,
    reply_to: int | None = None,
) -> int:
    silent = silent_for(now, critical=payload.critical, cfg=cfg.news.quiet_hours)
    msg = render_card(payload)
    mid = None
    if publisher is not None:
        mid = await publisher.send(
            msg.text,
            silent=silent,
            preview_url=msg.preview_url,
            show_above=msg.show_above,
            reply_to=reply_to,
        )
    with news_session() as s:
        row = NewsPostRow(
            kind=payload.kind,
            subject=payload.subject,
            telegram_message_id=mid,
            cluster_ids=payload.cluster_ids,
            posted_at=naive_utc(now),
            payload=payload.model_dump(mode="json"),
            silent=silent,
            critical=payload.critical,
            edits=0,
            stage="facts",
        )
        s.add(row)
        s.flush()
        pid = row.id
    if chart:
        path = save_chart(
            chart,
            ROOT / cfg.news.charts_dir
            if not Path(cfg.news.charts_dir).is_absolute()
            else Path(cfg.news.charts_dir),
            pid,
        )
        cmid = (
            await publisher.send_photo(chart, reply_to=mid, silent=True)
            if publisher is not None and mid
            else None
        )
        with news_session() as s:
            row2 = s.get(NewsPostRow, pid)
            assert row2 is not None
            row2.chart_path, row2.chart_message_id = path, cmid
    return pid


async def update_post(
    post_id: int,
    payload: CardPayload,
    *,
    publisher: Publisher | None,
    stage: str | None = None,
    llm_backend: str | None = None,
    count_edit: bool = True,
) -> bool:
    with news_session() as s:
        row = s.get(NewsPostRow, post_id)
        if row is None:
            return False
        mid = row.telegram_message_id
    ok = True
    new_mid = None
    if publisher is not None and mid:
        msg = render_card(payload)
        ok = await publisher.edit(
            mid, msg.text, preview_url=msg.preview_url, show_above=msg.show_above
        )
        if not ok:  # the message is gone (deleted in Telegram): post a fresh card (spec §11)
            new_mid = await publisher.send(
                msg.text, silent=True, preview_url=msg.preview_url, show_above=msg.show_above
            )
            ok = new_mid is not None
    with news_session() as s:
        row = s.get(NewsPostRow, post_id)
        assert row is not None
        if new_mid is not None:
            row.telegram_message_id = new_mid
        row.payload = payload.model_dump(mode="json")
        row.edited_at = naive_utc(datetime.now(UTC))
        if count_edit:
            row.edits += 1
        if stage:
            row.stage = stage
        if llm_backend:
            row.llm_backend = llm_backend
    return ok


def ticker_chart(
    symbol: str, sheet: FactSheet, an: Analytics, positions: list[PositionSnapshot], today: date
) -> bytes | None:
    strikes = []
    for p in positions:
        if (
            (p.underlying or p.symbol).upper() == symbol
            and p.sec_type == "OPT"
            and p.strike
            and p.expiry
        ):
            right = "P" if p.right == OptionRight.PUT else "C"
            strikes.append((p.strike, f"{p.strike:g}{right} {(p.expiry - today).days} DTE"))
    sup = sheet.get("Nearest support")
    res = sheet.get("Nearest resistance")
    return price_chart(
        an.daily(symbol),
        title=symbol,
        support=[sup.value] if sup and sup.value else [],
        resistance=[res.value] if res and res.value else [],
        strikes=strikes,
        event_day=today,
    )
