# tests/test_news_alerts.py
from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from src.common.config import get_config
from src.news import alerts as AL
from src.news.facts import Analytics
from src.news.playbook import load_playbook
from src.news.schemas import ItemView
from src.news.tape import Quote
from src.news.triggers import AlertCandidate

NOW = datetime(2026, 10, 14, 12, 31, tzinfo=UTC)


def _ctx() -> AL.AlertContext:
    an = Analytics(
        technicals=lambda s: None,
        iv=lambda s: None,
        sector=lambda s: None,
        quote=lambda s: Quote(symbol=s, last=100, prev_close=102, change_pct=-1.96),
        daily=lambda s: pd.DataFrame(),
        past_earnings=lambda s: [],
    )
    return AL.AlertContext(
        cfg=get_config(),
        an=an,
        pb=load_playbook(),
        now=NOW,
        today=date(2026, 10, 14),
        positions=[],
        held=set(),
        universe={"NVDA"},
        backdrop=None,
        tape={"SPY": Quote(symbol="SPY", change_pct=-2.1)},
    )


def test_pick_primary_by_rank() -> None:
    items = [
        ItemView(title="a", source_domain="yahoo.com", url="u1"),
        ItemView(title="b", source_domain="reuters.com", url="u2"),
    ]
    assert AL.pick_primary(items, ["reuters.com", "cnbc.com"]).url == "u2"
    assert AL.pick_primary([], ["reuters.com"]) is None


def test_macro_card_has_textbook_grid_and_pending_actual(news_db) -> None:
    from src.news.store.models import EconEventRow
    from src.news.store.session import news_session

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
    c = AlertCandidate(
        kind="macro_print",
        subject="2026-10-14T12:30",
        critical=True,
        event_keys=["k1"],
        detail={"primary": "CPI m/m"},
    )
    p = AL.build_card(c, _ctx())
    assert p.emoji == "🔴" and "hotter" in p.title.lower()
    assert p.headline_line.startswith("CPI m/m 0.4% vs 0.3% est")
    stocks = next(g for g in p.grid if g.asset == "stocks")
    assert stocks.textbook == "🔴" and stocks.actual is None
    assert p.grid_note == "📈 reaction in ~15 min"


def test_cluster_already_posted_becomes_update(news_db) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    first = AL.CardPayload(
        kind="breaking", title="Ceasefire agreed", emoji="🕊️", when=NOW, cluster_ids=[7]
    )
    with news_session() as s:
        s.add(
            NewsPostRow(
                kind="breaking",
                subject="cluster:7",
                telegram_message_id=99,
                cluster_ids=[7],
                posted_at=naive_utc(NOW),
                payload=first.model_dump(mode="json"),
                critical=True,
                silent=False,
                edits=0,
                stage="facts",
            )
        )
    second = AL.CardPayload(
        kind="market_move", title="SPY +2%", emoji="🟢", when=NOW, cluster_ids=[7]
    )
    act = AL.plan_alert(
        AlertCandidate(kind="market_move", subject="SPY:+2", critical=False, cluster_ids=[7]),
        second,
        now=NOW,
        max_edits=3,
    )
    assert act.action == "update" and act.post_id is not None
    assert act.payload.updates and "SPY +2%" in act.payload.updates[0]


def test_update_cap_turns_into_reply(news_db) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    base = AL.CardPayload(kind="breaking", title="x", emoji="•", when=NOW, cluster_ids=[8])
    with news_session() as s:
        s.add(
            NewsPostRow(
                kind="breaking",
                subject="cluster:8",
                telegram_message_id=5,
                cluster_ids=[8],
                posted_at=naive_utc(NOW),
                payload=base.model_dump(mode="json"),
                critical=True,
                silent=False,
                edits=3,
                stage="facts",
            )
        )
    act = AL.plan_alert(
        AlertCandidate(kind="breaking", subject="cluster:8b", critical=True, cluster_ids=[8]),
        base,
        now=NOW,
        max_edits=3,
    )
    assert act.action == "reply"


def _post(
    s, *, kind: str, subject: str, cluster_ids: list[int], payload: AL.CardPayload, edits: int = 0
) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc

    s.add(
        NewsPostRow(
            kind=kind,
            subject=subject,
            telegram_message_id=1,
            cluster_ids=cluster_ids,
            posted_at=naive_utc(NOW),
            payload=payload.model_dump(mode="json"),
            critical=False,
            silent=False,
            edits=edits,
            stage="facts",
        )
    )


def test_same_kind_and_subject_becomes_update(news_db) -> None:
    from src.news.store.session import news_session

    first = AL.CardPayload(
        kind="ticker_move", subject="NVDA", title="NVDA -4.0%", emoji="📉", when=NOW
    )
    with news_session() as s:
        _post(s, kind="ticker_move", subject="NVDA", cluster_ids=[], payload=first)
    new = AL.CardPayload(
        kind="ticker_move", subject="NVDA", title="NVDA -6.0%", emoji="📉", when=NOW
    )
    act = AL.plan_alert(
        AlertCandidate(kind="ticker_move", subject="NVDA", critical=False, symbols=["NVDA"]),
        new,
        now=NOW,
        max_edits=3,
    )
    assert act.action == "update" and "NVDA -6.0%" in act.payload.updates[0]


def test_unrelated_or_stale_post_is_a_new_card(news_db) -> None:
    from datetime import timedelta

    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    old = AL.CardPayload(kind="breaking", title="old", emoji="•", when=NOW, cluster_ids=[9])
    with news_session() as s:
        _post(s, kind="breaking", subject="cluster:3", cluster_ids=[3], payload=old)
        s.add(
            NewsPostRow(
                kind="breaking",
                subject="cluster:9",
                telegram_message_id=2,
                cluster_ids=[9],
                posted_at=naive_utc(NOW - timedelta(days=2)),
                payload=old.model_dump(mode="json"),
                critical=True,
                silent=False,
                edits=0,
                stage="facts",
            )
        )
    new = AL.CardPayload(kind="breaking", title="new", emoji="•", when=NOW, cluster_ids=[9])
    act = AL.plan_alert(
        AlertCandidate(kind="breaking", subject="cluster:9", critical=True, cluster_ids=[9]),
        new,
        now=NOW,
        max_edits=3,
    )
    assert act.action == "new" and act.post_id is None and act.payload is new


def test_market_move_card_lists_the_tape(news_db) -> None:
    c = AlertCandidate(
        kind="market_move",
        subject="SPY:-2",
        critical=False,
        symbols=["SPY"],
        detail={"change_pct": -2.1, "level": -2},
    )
    p = AL.build_card(c, _ctx())
    assert p.title == "SPY -2.1% (crossed -2%)" and p.emoji == "🔴"
    assert p.facts_line == "SPY -2.1%"


def test_breaking_card_takes_primary_source_by_rank(news_db) -> None:
    from src.news.store.models import NewsClusterRow, NewsItemRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    t = naive_utc(NOW)
    with news_session() as s:
        cl = NewsClusterRow(
            headline="Strait of Hormuz closed",
            category="macro",
            first_seen=t,
            last_seen=t,
            source_count=2,
            source_domains=["finance.yahoo.com", "reuters.com"],
            tickers=[],
            tags=[],
            topic_class="geopolitics",
        )
        s.add(cl)
        s.flush()
        cid = cl.id
        for dom, url in (("finance.yahoo.com", "https://y/1"), ("reuters.com", "https://r/1")):
            s.add(
                NewsItemRow(
                    url=url,
                    url_hash=url,
                    title_hash=url,
                    title="Strait of Hormuz closed",
                    source=dom,
                    source_domain=dom,
                    category="macro",
                    origin="rss",
                    fetched_at=t,
                    cluster_id=cid,
                    image_url=f"{url}.png",
                )
            )
    p = AL.build_card(
        AlertCandidate(kind="breaking", subject=f"cluster:{cid}", critical=True, cluster_ids=[cid]),
        _ctx(),
    )
    assert p.title == "Strait of Hormuz closed" and p.cluster_ids == [cid]
    assert p.preview_url == "https://r/1" and p.links[0].name == "reuters.com"


def test_ticker_move_without_cluster_says_no_catalyst(news_db) -> None:
    c = AlertCandidate(kind="ticker_move", subject="NVDA", critical=False, symbols=["NVDA"])
    p = AL.build_card(c, _ctx())
    assert p.title == "NVDA -2.0% · no identifiable catalyst" and p.emoji == "📉"
    assert p.facts is not None and p.facts.get("Move today") is not None
