"""The news process: asyncio loops over blocking source/LLM work run in threads.

Every loop body is wrapped — an exception is logged and the loop continues (spec §11) —
and every completed iteration beats the heartbeat the watchdog reads (Task 33).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.analytics.market_conditions import get_market_conditions
from src.common.config import Config
from src.common.market_hours import is_rth, is_trading_day
from src.common.schemas import MarketConditions
from src.news import triggers as T
from src.news.alerts import AlertContext, build_card, plan_alert
from src.news.collectors import Collector, held_positions, held_underlyings, watch_symbols
from src.news.digests import build_digest, due_digests, gather_inputs
from src.news.facts import Analytics, sigma_move
from src.news.playbook import load_playbook
from src.news.posting import post_card, ticker_chart, update_post
from src.news.publish import Publisher
from src.news.store import queries
from src.news.store.models import EarningsEventRow, EconEventRow, NewsPostRow
from src.news.store.prune import prune
from src.news.store.session import init_news_db, news_session
from src.news.store.state import get_state, set_state, touch_heartbeat
from src.news.tape import Quote, tape

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
Interval = float | Callable[[datetime], float]


def utcnow() -> datetime:
    return datetime.now(UTC)


class NewsService:
    def __init__(self, cfg: Config, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.cfg = cfg
        self.ncfg = cfg.news
        self.clock = clock
        self.collector = Collector(cfg.news)
        self.publisher = Publisher.from_config(cfg)
        self.gate = T.AlertGate(cfg.news.alerts)
        self.an = Analytics.live()
        self.last_movers: list[T.TickerMove] = []
        self._backdrop_cache: tuple[datetime, MarketConditions | None] | None = None

    async def _loop(
        self, name: str, interval_s: Interval, fn: Callable[[datetime], object], stop: asyncio.Event
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
            wait = interval_s(self.clock()) if callable(interval_s) else interval_s
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait)
            except TimeoutError:
                pass

    def _threaded(self, fn: Callable[[datetime], object]) -> Callable[[datetime], object]:
        async def run(now: datetime) -> object:
            return await asyncio.to_thread(fn, now)

        return run

    def loops(self) -> list[tuple[str, Interval, Callable[[datetime], object]]]:
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
            ("econ_actuals", self._econ_interval, self._econ_actuals),
            ("tape", 120, self._tape_alerts),
            ("tickers_sweep", self.ncfg.alerts.ticker_scan_minutes * 60, self._ticker_sweep),
            ("earnings_alerts", 300, self._earnings_alerts),
            ("breaking", 120, self._breaking),
            ("digests", 60, self._digests),
            (
                "prune",
                24 * 3600,
                self._threaded(lambda now: prune(now, retention_days=self.ncfg.retention_days)),
            ),
        ]

    # --- alerts --------------------------------------------------------------------------

    def _backdrop(self, now: datetime) -> MarketConditions | None:
        if self._backdrop_cache and now - self._backdrop_cache[0] < timedelta(minutes=10):
            return self._backdrop_cache[1]
        try:
            b: MarketConditions | None = get_market_conditions()
        except Exception:
            log.debug("news: market backdrop unavailable", exc_info=True)
            b = None
        self._backdrop_cache = (now, b)
        return b

    def _alert_ctx(self, now: datetime, tape_now: dict[str, Quote] | None = None) -> AlertContext:
        return AlertContext(
            cfg=self.cfg,
            an=self.an,
            pb=load_playbook(),
            now=now,
            today=now.astimezone(ET).date(),
            positions=held_positions(),
            held=held_underlyings(),
            universe=set(watch_symbols()),
            backdrop=self._backdrop(now),
            tape=tape_now or {},
        )

    async def _dispatch(
        self,
        cands: list[T.AlertCandidate],
        now: datetime,
        *,
        tape_now: dict[str, Quote] | None = None,
    ) -> list[int]:
        ids: list[int] = []
        day = now.astimezone(ET).date()
        for c in cands:
            if not await asyncio.to_thread(self.gate.admit, c, now=now, day=day):
                continue
            ctx = await asyncio.to_thread(self._alert_ctx, now, tape_now)
            payload = await asyncio.to_thread(build_card, c, ctx)
            act = await asyncio.to_thread(
                plan_alert, c, payload, now=now, max_edits=self.ncfg.alerts.max_edits
            )
            if act.action == "update" and act.post_id is not None:
                await update_post(act.post_id, act.payload, publisher=self.publisher)
                ids.append(act.post_id)
                continue
            chart = None
            if c.kind in ("ticker_move", "earnings") and act.payload.facts is not None:
                chart = await asyncio.to_thread(
                    ticker_chart, c.symbols[0], act.payload.facts, self.an, ctx.positions, ctx.today
                )
            reply_to = None
            if act.action == "reply" and act.post_id is not None:
                with news_session() as s:
                    row = s.get(NewsPostRow, act.post_id)
                    reply_to = row.telegram_message_id if row else None
            ids.append(
                await post_card(
                    act.payload,
                    publisher=self.publisher,
                    cfg=self.cfg,
                    now=now,
                    chart=chart,
                    reply_to=reply_to,
                )
            )
        return ids

    def _econ_interval(self, now: datetime) -> float:
        s = self.ncfg.sources
        if self.collector.in_fast_econ_window(now):
            return float(s.econ_fast_poll_seconds)
        return float(s.econ_poll_minutes * 60)

    async def _econ_actuals(self, now: datetime) -> None:
        keys = await asyncio.to_thread(self.collector.refresh_econ_actuals, now)
        if not keys:
            return
        with news_session() as s:
            evs = [
                queries.econ_view(r)
                for r in (s.get(EconEventRow, k) for k in keys)
                if r is not None and not r.alerted
            ]
        await self._dispatch(T.group_macro_releases(evs, load_playbook()), now)
        with news_session() as s:  # belt-and-braces beside the gate: a restart never re-alerts
            for e in evs:
                row = s.get(EconEventRow, e.event_key)
                if row is not None:
                    row.alerted = True

    async def _tape_alerts(self, now: datetime) -> None:
        day = now.astimezone(ET).date()
        if not is_trading_day(day):
            return
        syms = sorted(set(self.ncfg.alerts.index_symbols) | {"^VIX"})
        tp = await asyncio.to_thread(tape, syms)
        crossed = T.detect_index_levels(tp, self.ncfg.alerts)
        fired = await asyncio.to_thread(self.gate.fired_subjects, "market_move", day)
        new = T.pick_new_levels(crossed, fired)
        for c in crossed:  # mark every crossed level so a later, smaller level never re-alerts
            if c.subject not in fired and c not in new:
                await asyncio.to_thread(self.gate.mark, "market_move", c.subject, day, now)
        vix = tp.get("^VIX")
        vix_cands = T.detect_vix(vix, self.ncfg.alerts) if vix is not None else []
        await self._dispatch(new + vix_cands, now, tape_now=tp)

    async def _ticker_sweep(self, now: datetime) -> None:
        if not is_trading_day(now.astimezone(ET).date()):
            return
        syms = await asyncio.to_thread(watch_symbols)
        tp = await asyncio.to_thread(tape, [*syms, "SPY"])
        spy = tp.get("SPY")
        moves: list[T.TickerMove] = []
        for sym in syms:
            q = tp.get(sym)
            if q is None or q.change_pct is None:
                continue
            ivs = await asyncio.to_thread(self.an.iv, sym)
            iv_pct = (ivs.current_iv or ivs.hv_30) if ivs else None
            abn = q.change_pct - spy.change_pct if spy and spy.change_pct is not None else None
            moves.append(
                T.TickerMove(
                    symbol=sym,
                    change_pct=q.change_pct,
                    abnormal_pct=abn,
                    sigma=sigma_move(abn if abn is not None else q.change_pct, iv_pct),
                )
            )
        self.last_movers = moves
        cands = T.detect_ticker_moves(
            moves, held=held_underlyings(), universe=set(syms), cfg=self.ncfg.alerts
        )
        await self._dispatch(cands, now, tape_now=tp)

    async def _earnings_alerts(self, now: datetime) -> None:
        released = await asyncio.to_thread(self.collector.refresh_earnings, now, days=2)
        if not released:
            return
        with news_session() as s:
            views = [v for sym, d in released for v in queries.earnings_between(s, d, d, {sym})]
        cands = T.detect_earnings(views, held=held_underlyings(), universe=set(watch_symbols()))
        await self._dispatch(cands, now)
        with news_session() as s:
            for sym, d in released:
                row = s.get(EarningsEventRow, (sym, d))
                if row is not None:
                    row.alerted = True

    async def _breaking(self, now: datetime) -> None:
        win = timedelta(minutes=self.ncfg.alerts.geo_reaction_window_min)
        with news_session() as s:
            clusters = [
                c
                for cat in ("geopolitics", "macro", "government", "markets")
                for c in queries.clusters_since(s, now - win, category=cat, limit=20)
            ]
        if not clusters:
            return
        sym = "SPY" if is_rth(now) else "ES=F"
        q = await asyncio.to_thread(tape, [sym])
        reaction = q[sym].change_pct if sym in q else None
        cands = T.detect_breaking(clusters, reaction_pct=reaction, cfg=self.ncfg.alerts)
        await self._dispatch(cands, now, tape_now=q)

    async def _digests(self, now: datetime) -> None:
        sent = {n: get_state(f"digest_sent:{n}") or "" for n in ("premarket", "close", "week")}
        for name in due_digests(now, sent, self.ncfg.digests):
            inp = await asyncio.to_thread(gather_inputs, name, now=now, cfg=self.cfg, an=self.an)
            if name == "close":
                inp.movers = list(self.last_movers)
            payload = build_digest(name, inp)
            await post_card(payload, publisher=self.publisher, cfg=self.cfg, now=now)
            set_state(f"digest_sent:{name}", now.astimezone(ET).date().isoformat())

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
        if self.publisher is not None:
            await self.publisher.send(
                f"📰 News service online (backend: {self.ncfg.llm.backend})", silent=True
            )
        tasks = [asyncio.create_task(self._loop(n, i, f, stop)) for n, i, f in self.loops()]
        await stop.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run(stop: asyncio.Event) -> None:
    from src.common.config import get_config

    await NewsService(get_config()).run(stop)
