from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest


async def test_loop_survives_exceptions_and_never_beats_on_failure(news_db, monkeypatch) -> None:
    """A loop whose body raises keeps running but must not beat: the watchdog would otherwise
    read a process whose every loop fails as healthy."""
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
    assert state.get_state(state.HEARTBEAT_KEY) is None


async def test_successful_loop_beats_heartbeat_with_breaker_states(news_db, monkeypatch) -> None:
    import json

    import src.news.service as S
    from src.common.config import get_config
    from src.news.service import NewsService
    from src.news.store import state

    monkeypatch.setattr(S, "breaker_states", lambda: {"finnhub": "open", "nasdaq": "closed"})
    svc = NewsService(get_config(), clock=lambda: datetime(2026, 10, 9, 12, tzinfo=UTC))
    stop = asyncio.Event()
    task = asyncio.create_task(svc._loop("ok", 0.01, lambda now: None, stop))
    await asyncio.sleep(0.03)
    stop.set()
    await task
    assert state.get_state(state.HEARTBEAT_KEY) == "2026-10-09T12:00:00+00:00"
    assert json.loads(state.get_state(state.BREAKERS_KEY) or "{}") == {
        "finnhub": "open",
        "nasdaq": "closed",
    }


async def test_disabled_service_idles(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news.service import NewsService

    cfg = get_config().model_copy(
        update={"news": get_config().news.model_copy(update={"enabled": False})}
    )
    stop = asyncio.Event()
    stop.set()
    await NewsService(cfg).run(stop)  # returns promptly, no loops started


def test_prune_keeps_recent_and_posts(news_db) -> None:
    from datetime import timedelta

    from src.news.store.models import NewsItemRow, NewsPostRow
    from src.news.store.prune import prune
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    now = datetime(2026, 10, 14, tzinfo=UTC)
    with news_session() as s:
        for i, age in enumerate((1, 40)):
            s.add(
                NewsItemRow(
                    url_hash=f"u{i}",
                    title_hash=f"t{i}",
                    title="x",
                    category="macro",
                    origin="rss",
                    fetched_at=naive_utc(now - timedelta(days=age)),
                    tickers=[],
                    tags=[],
                )
            )
        s.add(
            NewsPostRow(
                kind="digest_close",
                posted_at=naive_utc(now - timedelta(days=90)),
                payload={},
                cluster_ids=[],
                silent=False,
                critical=False,
                edits=0,
                stage="explained",
            )
        )
    assert prune(now, retention_days=30) == 1
    with news_session() as s:
        assert s.query(NewsItemRow).count() == 1 and s.query(NewsPostRow).count() == 1


async def test_dispatch_posts_admitted_candidates_once(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news import service as S
    from src.news.schemas import CardPayload
    from src.news.triggers import AlertCandidate

    svc = S.NewsService(get_config())
    svc.publisher = None
    monkeypatch.setattr(
        S,
        "build_card",
        lambda c, ctx: CardPayload(
            kind="market_move",
            subject=c.subject,
            title="SPY -2%",
            emoji="🔴",
            when=datetime(2026, 10, 14, 15, tzinfo=UTC),
        ),
    )
    monkeypatch.setattr(svc, "_alert_ctx", lambda now, tape_now=None: None)
    c = AlertCandidate(kind="market_move", subject="SPY:-2", critical=True)
    now = datetime(2026, 10, 14, 15, tzinfo=UTC)
    assert len(await svc._dispatch([c], now)) == 1
    assert await svc._dispatch([c], now) == []


async def test_dispatch_update_edits_existing_post_instead_of_posting(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news import service as S
    from src.news.alerts import AlertAction
    from src.news.schemas import CardPayload
    from src.news.triggers import AlertCandidate

    svc = S.NewsService(get_config())
    svc.publisher = None
    now = datetime(2026, 10, 14, 15, tzinfo=UTC)
    card = CardPayload(kind="market_move", subject="SPY:-2", title="SPY -2%", emoji="🔴", when=now)
    monkeypatch.setattr(S, "build_card", lambda c, ctx: card)
    monkeypatch.setattr(svc, "_alert_ctx", lambda now, tape_now=None: None)
    monkeypatch.setattr(S, "plan_alert", lambda c, p, **kw: AlertAction("update", p, 42))
    updated: list[int] = []

    async def fake_update(pid, payload, **kw):
        updated.append(pid)
        return True

    async def no_post(*a, **kw):
        raise AssertionError("an update must not post a new card")

    monkeypatch.setattr(S, "update_post", fake_update)
    monkeypatch.setattr(S, "post_card", no_post)
    c = AlertCandidate(kind="market_move", subject="SPY:-2", critical=True)
    assert await svc._dispatch([c], now) == [42] and updated == [42]


async def test_tape_marks_smaller_crossed_levels_so_they_never_alert_later(
    news_db, monkeypatch
) -> None:
    from src.common.config import get_config
    from src.news import service as S
    from src.news.tape import Quote

    svc = S.NewsService(get_config())
    svc.publisher = None
    now = datetime(2026, 10, 14, 15, tzinfo=UTC)
    monkeypatch.setattr(S, "tape", lambda syms: {"SPY": Quote(symbol="SPY", change_pct=-3.2)})
    sent: list[list[str]] = []

    async def fake_dispatch(cands, now, *, tape_now=None):
        sent.append([c.subject for c in cands])
        return []

    monkeypatch.setattr(svc, "_dispatch", fake_dispatch)
    await svc._tape_alerts(now)
    fired = svc.gate.fired_subjects("market_move", now.date())
    assert len(sent[0]) == 1  # only the deepest level is offered
    assert {s for s in fired} >= {"SPY:-2"}  # the shallower crossed level is marked, never offered


async def test_digest_loop_posts_once_per_day(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news import service as S
    from src.news.digests import DigestInputs

    svc = S.NewsService(get_config())
    svc.publisher = None
    now = datetime(2026, 10, 14, 12, 5, tzinfo=UTC)  # 08:05 ET, a Wednesday
    monkeypatch.setattr(
        S,
        "gather_inputs",
        lambda name, **kw: DigestInputs(
            now=now, tape={}, clusters=[], econ=[], earnings=[], held=set(), positions=[], movers=[]
        ),
    )
    monkeypatch.setattr(svc, "_backdrop", lambda now: None)
    await svc._digests(now)
    await svc._digests(now)
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    with news_session() as s:
        kinds = [r.kind for r in s.query(NewsPostRow)]
    assert kinds == ["digest_premarket"]


async def test_econ_actuals_marks_alerted_and_never_redispatches(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news import service as S
    from src.news.store.models import EconEventRow
    from src.news.store.session import news_session

    svc = S.NewsService(get_config())
    svc.publisher = None
    now = datetime(2026, 10, 14, 12, 31, tzinfo=UTC)
    with news_session() as s:
        s.add(
            EconEventRow(
                event_key="k1",
                title="CPI m/m",
                playbook_key="cpi",
                scheduled_at=datetime(2026, 10, 14, 12, 30),
                impact="High",
                forecast="0.3%",
                previous="0.2%",
                actual="0.4%",
                surprise_dir="hot",
                alerted=False,
            )
        )
    monkeypatch.setattr(svc.collector, "refresh_econ_actuals", lambda now: ["k1"])
    sent: list[list[str]] = []

    async def fake_dispatch(cands, now, *, tape_now=None):
        sent.append([k for c in cands for k in c.event_keys])
        return []

    monkeypatch.setattr(svc, "_dispatch", fake_dispatch)
    await svc._econ_actuals(now)
    await svc._econ_actuals(now)
    assert sent == [["k1"], []]
    with news_session() as s:
        assert s.get(EconEventRow, "k1").alerted is True


async def test_digest_uses_editor_order_and_reads_or_falls_back(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news import explain as X
    from src.news import service as S
    from src.news.digests import DigestInputs
    from src.news.schemas import ClusterView, DigestRead, EditorOutput, EditorThread

    svc = S.NewsService(get_config())
    svc.publisher = None
    monkeypatch.setattr(svc, "_backdrop", lambda now: None)
    now = datetime(2026, 10, 14, 12, 5, tzinfo=UTC)
    cls = [
        ClusterView(
            id=i,
            headline=f"story {i}",
            category="macro",
            first_seen=now,
            last_seen=now,
            source_count=2,
        )
        for i in (1, 2)
    ]
    captured: list[DigestInputs] = []

    def fake_build(name, inp):
        captured.append(inp)
        from src.news.schemas import CardPayload

        return CardPayload(kind="digest_premarket", title="Pre-market", emoji="🗞️", when=now)

    monkeypatch.setattr(
        S,
        "gather_inputs",
        lambda name, **kw: DigestInputs(
            now=now,
            tape={},
            clusters=list(cls),
            econ=[],
            earnings=[],
            held=set(),
            positions=[],
            movers=[],
        ),
    )
    monkeypatch.setattr(S, "build_digest", fake_build)
    monkeypatch.setattr(
        X,
        "edit_digest",
        lambda c, b, now: EditorOutput(
            regime="risk_off",
            threads=[
                EditorThread(cluster_ids=[2], title="two"),
                EditorThread(cluster_ids=[1], title="one"),
            ],
        ),
    )
    asked: list[list[int]] = []

    def fake_reads(threads, b, now):
        asked.append([t.id for t in threads])
        return {2: DigestRead(cluster_id=2, headline="h", read="r", verdict="priced_in")}

    monkeypatch.setattr(X, "digest_reads", fake_reads)
    await svc._digests(now)
    assert (
        asked == [[2, 1]]
        and captured[0].regime == "risk_off"
        and captured[0].thread_order == [[2], [1]]
    )
    assert set(captured[0].reads) == {2}

    from src.news.store import state
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    with news_session() as s:
        assert [r.stage for r in s.query(NewsPostRow)] == ["explained"]
    state.set_state("digest_sent:premarket", "")
    monkeypatch.setattr(X, "edit_digest", lambda c, b, now: None)
    monkeypatch.setattr(X, "digest_reads", lambda t, b, now: asked.append([x.id for x in t]) or {})
    await svc._digests(now)
    assert asked[-1] == [1, 2] and captured[-1].regime is None
    with news_session() as s:
        assert sorted(r.stage for r in s.query(NewsPostRow)) == ["explained", "fallback"]


async def test_followup_loop_completes_each_pending_post(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news import followup as FU
    from src.news import service as S
    from src.news.schemas import CardPayload

    svc = S.NewsService(get_config())
    svc.publisher = None
    now = datetime(2026, 10, 14, 15, tzinfo=UTC)
    card = CardPayload(kind="ticker_move", title="x", emoji="•", when=now)
    monkeypatch.setattr(FU, "pending_posts", lambda now: [(1, card), (2, card)])
    done: list[int] = []

    async def fake_complete(pid, payload, **kw):
        done.append(pid)
        if pid == 1:
            raise RuntimeError("one bad post must not stop the rest")
        return True

    monkeypatch.setattr(FU, "complete_post", fake_complete)
    await svc._followup(now)
    assert done == [1, 2]


async def test_earnings_alert_loop_polls_only_the_actuals_source(news_db, monkeypatch) -> None:
    """The 5-minute earnings loop asks Finnhub for actuals; the Nasdaq/yfinance calendar refresh
    stays on news.sources.earnings_poll_hours (final review)."""
    from src.common.config import get_config
    from src.news import service as S

    svc = S.NewsService(get_config())
    svc.publisher = None

    def slow_refresh(*a, **k):
        raise AssertionError("the full calendar refresh must not run every 5 minutes")

    monkeypatch.setattr(svc.collector, "refresh_earnings", slow_refresh)
    monkeypatch.setattr(svc.collector, "refresh_earnings_actuals", lambda now: [])
    await svc._earnings_alerts(datetime(2026, 10, 14, 21, tzinfo=UTC))


async def test_breaking_loop_measures_each_story_from_first_seen(news_db, monkeypatch) -> None:
    import pandas as pd

    from src.common.config import get_config
    from src.news import service as S
    from src.news.store.models import NewsClusterRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session
    from src.news.tape import Quote

    now = datetime(2026, 10, 14, 15, 20, tzinfo=UTC)  # 11:20 ET, RTH
    first = now - timedelta(minutes=15)
    with news_session() as s:
        s.add(
            NewsClusterRow(
                headline="Ceasefire agreed",
                category="geopolitics",
                first_seen=naive_utc(first),
                last_seen=naive_utc(now),
                source_domains=["reuters.com", "cnbc.com"],
                source_count=2,
                tickers=[],
                tags=[],
                topic_class="ceasefire",
                title_tokens=[],
            )
        )
    idx = pd.date_range(first - timedelta(minutes=5), now, freq="1min", tz=UTC)
    closes = {"flat": [99.0] * len(idx), "jump": [100.0 if t < first else 100.9 for t in idx]}
    svc = S.NewsService(get_config())
    svc.publisher = None
    sent: list[list[str]] = []

    async def fake_dispatch(cands, now, *, tape_now=None):
        sent.append([c.subject for c in cands])
        return []

    monkeypatch.setattr(svc, "_dispatch", fake_dispatch)
    monkeypatch.setattr(S, "tape", lambda syms: {s: Quote(symbol=s, change_pct=-1.0) for s in syms})
    for shape in ("flat", "jump"):
        frame = pd.DataFrame({"Close": closes[shape]}, index=idx)
        monkeypatch.setattr(
            S,
            "get_intraday_price_provider",
            lambda frame=frame: type("P", (), {"get_intraday": lambda self, *a, **k: frame})(),
        )
        await svc._breaking(now)
    assert sent == [[c] for c in ("cluster:1",)]


async def test_digest_carries_held_back_alerts_once(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news import service as S
    from src.news.digests import gather_inputs
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session
    from src.news.store.state import held_alerts, hold_for_digest

    svc = S.NewsService(get_config())
    svc.publisher = None
    now = datetime(2026, 10, 14, 12, 5, tzinfo=UTC)  # 08:05 ET premarket
    hold_for_digest(now.date(), "ticker_move", "MSFT", "MSFT · +4.1% · 3.2σ", now=now)
    monkeypatch.setattr("src.news.tape.tape", lambda syms: {})
    monkeypatch.setattr("src.news.collectors.held_positions", lambda: [])
    monkeypatch.setattr("src.news.collectors.held_underlyings", lambda: set())
    monkeypatch.setattr(S, "gather_inputs", gather_inputs)
    monkeypatch.setattr(svc, "_backdrop", lambda now: None)
    monkeypatch.setattr(svc, "_rank_digest", lambda inp, now: asyncio.sleep(0))
    await svc._digests(now)
    with news_session() as s:
        payload = s.query(NewsPostRow).one().payload
    assert any(
        sec["title"] == "Also flagged (alert cap)"
        and [i["text"] for i in sec["items"]] == ["MSFT · +4.1% · 3.2σ"]
        for sec in payload["sections"]
    )
    assert held_alerts() == []  # consumed: the next digest does not repeat it
    # Re-detected later the same day while still capped: not held again, so not re-listed.
    hold_for_digest(now.date(), "ticker_move", "MSFT", "MSFT · +5.0% · 3.5σ", now=now)
    assert held_alerts() == []


async def test_ticker_sweep_skips_overnight_and_caches_prior_closes(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news import service as S
    from src.news.tape import Quote

    svc = S.NewsService(get_config())
    calls: list[object] = []

    def fake_tape(syms, *, prev_cache=None):
        calls.append(prev_cache)
        return {s: Quote(symbol=s, change_pct=0.1) for s in syms}

    monkeypatch.setattr(S, "tape", fake_tape)
    monkeypatch.setattr(S, "watch_symbols", lambda: ["NVDA"])
    monkeypatch.setattr(S, "held_underlyings", lambda: set())
    monkeypatch.setattr(svc.an, "iv", lambda sym: None)

    async def no_dispatch(cands, now, *, tape_now=None):
        return []

    monkeypatch.setattr(svc, "_dispatch", no_dispatch)
    await svc._ticker_sweep(datetime(2026, 10, 14, 6, 0, tzinfo=UTC))  # 02:00 ET Wednesday
    assert calls == []
    await svc._ticker_sweep(datetime(2026, 10, 14, 15, 0, tzinfo=UTC))  # 11:00 ET
    assert calls == [svc._prev_close]
    assert svc._sweep_interval(datetime(2026, 10, 14, 15, 0, tzinfo=UTC)) == (
        get_config().news.alerts.ticker_scan_minutes * 60
    )
    assert svc._sweep_interval(datetime(2026, 10, 14, 22, 0, tzinfo=UTC)) == 30 * 60


def test_quote_reads_each_prior_close_once_per_day(monkeypatch) -> None:
    from datetime import date

    import pandas as pd

    import src.news.tape as tape_mod

    ohlcv = {"n": 0}

    class P:
        def get_last_price(self, s):
            return 110.0

        def get_ohlcv(self, s, lookback_days=10):
            ohlcv["n"] += 1
            return pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2026-10-13"]))

    monkeypatch.setattr(tape_mod, "get_price_provider", lambda: P())
    cache: dict = {}
    day = date(2026, 10, 14)
    q1 = tape_mod.quote("NVDA", today=day, prev_cache=cache)
    q2 = tape_mod.quote("NVDA", today=day, prev_cache=cache)
    assert ohlcv["n"] == 1 and q1.change_pct == q2.change_pct == pytest.approx(10.0)
    tape_mod.quote("NVDA", today=day)  # no cache: always fetched
    assert ohlcv["n"] == 2


def test_econ_poll_never_sleeps_past_the_next_release_window(news_db) -> None:
    """Regression (2026-10-09): outside a fast window the econ-actuals loop slept a flat
    `econ_poll_minutes` (60). Started at 13:22 UTC, it slept to 14:22 and skipped the whole
    13:58-14:10 fast window for the 14:00 UoM print. The slow wait must end where the next
    pending release's fast window opens."""
    from src.common.config import get_config
    from src.news import service as S
    from src.news.store.models import EconEventRow
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(
            EconEventRow(
                event_key="2026-10-09T14:00|Prelim UoM Consumer Sentiment",
                title="Prelim UoM Consumer Sentiment",
                playbook_key="umich_sentiment",
                scheduled_at=datetime(2026, 10, 9, 14, 0),
                impact="Medium",
                forecast="47.5",
                alerted=False,
            )
        )
    src_cfg = get_config().news.sources
    svc = S.NewsService(get_config())
    before = timedelta(minutes=src_cfg.econ_fast_window_before_min)

    wait = svc._econ_interval(datetime(2026, 10, 9, 13, 22, tzinfo=UTC))
    window_opens = datetime(2026, 10, 9, 14, 0, tzinfo=UTC) - before
    assert wait == (window_opens - datetime(2026, 10, 9, 13, 22, tzinfo=UTC)).total_seconds()

    # Inside the window: the fast cadence.
    assert svc._econ_interval(datetime(2026, 10, 9, 13, 59, tzinfo=UTC)) == float(
        src_cfg.econ_fast_poll_seconds
    )
    # Nothing pending ahead: the normal slow cadence.
    assert svc._econ_interval(datetime(2026, 10, 9, 15, 0, tzinfo=UTC)) == float(
        src_cfg.econ_poll_minutes * 60
    )
