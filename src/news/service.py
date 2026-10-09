"""The news process: asyncio loops over blocking source/LLM work run in threads.

Every loop body is wrapped — an exception is logged and the loop continues (spec §11) —
and every completed iteration beats the heartbeat the watchdog reads (Task 33).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from src.common.config import Config
from src.news.collectors import Collector
from src.news.store.session import init_news_db
from src.news.store.state import touch_heartbeat

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


class NewsService:
    def __init__(self, cfg: Config, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.cfg = cfg
        self.ncfg = cfg.news
        self.clock = clock
        self.collector = Collector(cfg.news)

    async def _loop(
        self, name: str, interval_s: float, fn: Callable[[datetime], object], stop: asyncio.Event
    ) -> None:
        while not stop.is_set():
            now = self.clock()
            try:
                result = fn(now)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                log.exception("news loop %s failed", name)
            try:
                await asyncio.to_thread(touch_heartbeat, self.clock())
            except Exception:
                log.debug("heartbeat write failed", exc_info=True)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_s)
            except TimeoutError:
                pass

    def _threaded(self, fn: Callable[[datetime], object]) -> Callable[[datetime], object]:
        async def run(now: datetime) -> object:
            return await asyncio.to_thread(fn, now)

        return run

    def loops(self) -> list[tuple[str, float, Callable[[datetime], object]]]:
        s = self.ncfg.sources
        return [
            ("rss", s.rss_poll_minutes * 60, self._threaded(self.collector.collect_rss)),
            ("macro", s.macro_poll_minutes * 60, self._threaded(self.collector.collect_macro)),
            (
                "tickers",
                60,
                self._threaded(
                    lambda now: self.collector.collect_ticker_batch(
                        now, batch=self.collector.ticker_batch_size(1)
                    )
                ),
            ),
            (
                "econ_schedule",
                s.econ_poll_minutes * 60,
                self._threaded(self.collector.refresh_econ_schedule),
            ),
            (
                "earnings",
                s.earnings_poll_hours * 3600,
                self._threaded(self.collector.refresh_earnings),
            ),
        ]

    def run_once_ingest(self, now: datetime) -> None:
        self.collector.refresh_econ_schedule(now)
        self.collector.collect_rss(now)
        self.collector.collect_macro(now)

    async def run(self, stop: asyncio.Event) -> None:
        if not self.ncfg.enabled:
            log.info("news: disabled in config/news.yaml — idling")
            await stop.wait()
            return
        await asyncio.to_thread(init_news_db)
        tasks = [asyncio.create_task(self._loop(n, i, f, stop)) for n, i, f in self.loops()]
        await stop.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run(stop: asyncio.Event) -> None:
    from src.common.config import get_config

    await NewsService(get_config()).run(stop)
