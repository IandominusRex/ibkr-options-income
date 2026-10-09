"""Build and post an on-demand ticker brief (spec §7.5.2). Runs only in the news process."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from src.news.alerts import ticker_card
from src.news.followup import complete_post
from src.news.posting import post_card, ticker_chart
from src.news.triggers import AlertCandidate

if TYPE_CHECKING:
    from src.news.service import NewsService


async def build_brief(symbol: str, *, svc: NewsService, now: datetime) -> int:
    await asyncio.to_thread(svc.collector.collect_symbol, symbol, now)
    ctx = await asyncio.to_thread(svc._alert_ctx, now, None)
    cand = AlertCandidate(kind="ticker_move", subject=symbol, critical=True, symbols=[symbol])
    payload = await asyncio.to_thread(ticker_card, cand, ctx, kind="brief")
    payload = payload.model_copy(update={"critical": True})
    chart = None
    if payload.facts is not None and ctx is not None:
        chart = await asyncio.to_thread(
            ticker_chart, symbol, payload.facts, ctx.an, ctx.positions, ctx.today
        )
    pid = await post_card(payload, publisher=svc.publisher, cfg=svc.cfg, now=now, chart=chart)
    await complete_post(pid, payload, now=now, cfg=svc.cfg, publisher=svc.publisher)
    return pid
