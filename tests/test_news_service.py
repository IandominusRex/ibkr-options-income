from __future__ import annotations

import asyncio
from datetime import UTC, datetime


async def test_loop_survives_exceptions_and_beats_heartbeat(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news.service import NewsService
    from src.news.store import state

    svc = NewsService(get_config(), clock=lambda: datetime(2026, 10, 9, 12, tzinfo=UTC))
    calls = {"n": 0}

    def flaky(now):
        calls["n"] += 1
        raise RuntimeError("boom")

    stop = asyncio.Event()
    task = asyncio.create_task(svc._loop("flaky", 0.01, flaky, stop))
    await asyncio.sleep(0.05)
    stop.set()
    await task
    assert calls["n"] >= 2
    assert state.get_state(state.HEARTBEAT_KEY) is not None


async def test_disabled_service_idles(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news.service import NewsService

    cfg = get_config().model_copy(
        update={"news": get_config().news.model_copy(update={"enabled": False})}
    )
    stop = asyncio.Event()
    stop.set()
    await NewsService(cfg).run(stop)  # returns promptly, no loops started
