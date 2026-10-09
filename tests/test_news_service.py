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
