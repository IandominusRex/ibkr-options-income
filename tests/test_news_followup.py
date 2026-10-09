# tests/test_news_followup.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.common.config import get_config
from src.news import followup as FU
from src.news.explain import ExplainOutcome
from src.news.reaction import AssetMove, Reaction
from src.news.schemas import CardPayload, Explanation, GridRow

REL = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)


def _macro() -> CardPayload:
    return CardPayload(
        kind="macro_print",
        title="CPI hotter than expected",
        emoji="🔴",
        when=REL,
        critical=True,
        grid=[GridRow(asset="stocks", textbook="🔴")],
        grid_note="📈 reaction in ~15 min",
        event_keys=["k1"],
    )


async def _seed(payload) -> int:
    from src.news.posting import post_card

    return await post_card(payload, publisher=None, cfg=get_config(), now=REL)


async def test_macro_waits_for_reaction_then_explains(news_db, monkeypatch) -> None:
    pid = await _seed(_macro())
    incomplete = Reaction(
        release_at=REL,
        window_min=15,
        complete=False,
        moves=[AssetMove(asset="stocks", symbol="ES=F")],
    )
    assert not await FU.complete_post(
        pid,
        _macro(),
        now=REL + timedelta(minutes=10),
        cfg=get_config(),
        publisher=None,
        measure=lambda rel, cfg: incomplete,
    )
    done = Reaction(
        release_at=REL,
        window_min=15,
        complete=True,
        moves=[AssetMove(asset="stocks", symbol="ES=F", move=-1.2, unit="%", arrow="🔴")],
    )
    e = Explanation(
        headline="h",
        what_happened="w",
        read="r",
        bull="b",
        bear="c",
        verdict="priced_in",
        confidence="low",
        evidence=["F1"],
    )
    monkeypatch.setattr(
        FU, "explain_card", lambda *a, **k: ExplainOutcome(e, "cli", False, "explained", None)
    )
    assert await FU.complete_post(
        pid,
        _macro(),
        now=REL + timedelta(minutes=16),
        cfg=get_config(),
        publisher=None,
        measure=lambda rel, cfg: done,
    )
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    with news_session() as s:
        row = s.get(NewsPostRow, pid)
    assert row.stage == "explained" and row.edits == 0
    assert row.payload["grid"][0]["actual"] == "🔴 ES=F -1.20%" and row.payload["grid_note"] is None
    assert row.payload["explanation"]["verdict"] == "priced_in"


async def test_gives_up_waiting_and_marks_pending(news_db, monkeypatch) -> None:
    pid = await _seed(_macro())
    incomplete = Reaction(release_at=REL, window_min=15, complete=False, moves=[])
    monkeypatch.setattr(
        FU,
        "explain_card",
        lambda *a, **k: ExplainOutcome(None, None, False, "fallback", "🧠 unavailable"),
    )
    assert await FU.complete_post(
        pid,
        _macro(),
        now=REL + timedelta(minutes=40),
        cfg=get_config(),
        publisher=None,
        measure=lambda rel, cfg: incomplete,
    )
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    with news_session() as s:
        row = s.get(NewsPostRow, pid)
    assert (
        row.stage == "fallback" and row.payload["grid_note"] == "📈 reaction pending (data delayed)"
    )
    assert row.payload["llm_note"] == "🧠 unavailable"


async def test_pending_posts_lists_only_alert_facts(news_db) -> None:
    pid = await _seed(_macro())
    await _seed(CardPayload(kind="digest_close", title="Close recap", emoji="🗞️", when=REL))
    assert [p for p, _ in FU.pending_posts(REL + timedelta(minutes=1))] == [pid]


async def test_non_macro_explains_immediately_with_cluster_headlines(news_db, monkeypatch) -> None:
    from src.news.schemas import FactSheet
    from src.news.store.models import NewsClusterRow, NewsItemRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    t = naive_utc(REL)
    with news_session() as s:
        cl = NewsClusterRow(
            headline="Nvidia curbs", category="ticker", first_seen=t, last_seen=t, source_count=1
        )
        s.add(cl)
        s.flush()
        cid = cl.id
        s.add(
            NewsItemRow(
                url_hash="u",
                title_hash="t",
                title="Nvidia hit by curbs",
                category="ticker",
                origin="rss",
                fetched_at=t,
                cluster_id=cid,
            )
        )
    sheet = FactSheet()
    sheet.add("Move today", -6.2, "-6.2%")
    card = CardPayload(
        kind="ticker_move",
        subject="NVDA",
        title="NVDA -6.2%",
        emoji="📉",
        when=REL,
        facts=sheet,
        cluster_ids=[cid],
    )
    pid = await _seed(card)
    seen: dict = {}

    def fake_explain(kind, **kw):
        seen.update(kw, kind=kind)
        return ExplainOutcome(None, "cli", False, "fallback", "🧠 unavailable")

    monkeypatch.setattr(FU, "explain_card", fake_explain)
    assert await FU.complete_post(
        pid,
        card,
        now=REL,
        cfg=get_config(),
        publisher=None,
        measure=lambda rel, cfg: (_ for _ in ()).throw(AssertionError("no reaction for tickers")),
    )
    assert seen["kind"] == "ticker_move" and [h.title for h in seen["headlines"]] == [
        "Nvidia hit by curbs"
    ]
    assert seen["fallback_what"] == "-6.2%"
    assert FU.pending_posts(REL + timedelta(minutes=1)) == []
