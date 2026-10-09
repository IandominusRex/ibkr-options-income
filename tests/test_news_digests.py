# tests/test_news_digests.py
from __future__ import annotations

from datetime import UTC, date, datetime

from src.common.config import NewsDigestCfg
from src.news import digests as D
from src.news.schemas import ClusterView, DigestRead, EarningsView, EconEventView, ItemView
from src.news.tape import Quote
from src.news.triggers import TickerMove

C = NewsDigestCfg()


def test_premarket_due_across_dst_end() -> None:
    # 08:00 ET is 12:00 UTC before 2026-11-01 and 13:00 UTC after.
    assert "premarket" in D.due_digests(datetime(2026, 10, 30, 12, 1, tzinfo=UTC), {}, C)
    assert "premarket" not in D.due_digests(datetime(2026, 11, 2, 12, 1, tzinfo=UTC), {}, C)
    assert "premarket" in D.due_digests(datetime(2026, 11, 2, 13, 1, tzinfo=UTC), {}, C)


def test_sent_today_and_holidays_and_week() -> None:
    now = datetime(2026, 10, 14, 12, 5, tzinfo=UTC)
    assert D.due_digests(now, {"premarket": "2026-10-14"}, C) == []
    assert D.due_digests(datetime(2026, 11, 26, 13, 5, tzinfo=UTC), {}, C) == []  # Thanksgiving
    assert D.due_digests(datetime(2026, 10, 18, 22, 1, tzinfo=UTC), {}, C) == [
        "week"
    ]  # Sunday 18:01 ET


def _inp(**kw) -> D.DigestInputs:
    now = datetime(2026, 10, 14, 20, 30, tzinfo=UTC)
    base = dict(
        now=now,
        tape={
            "SPY": Quote(symbol="SPY", change_pct=-1.2),
            "QQQ": Quote(symbol="QQQ", change_pct=-1.8),
        },
        clusters=[
            ClusterView(
                id=1,
                headline="Fed minutes show split",
                category="macro",
                first_seen=now,
                last_seen=now,
                source_count=3,
                items=[
                    ItemView(
                        title="t",
                        url="https://reuters.com/x",
                        source="Reuters",
                        source_domain="reuters.com",
                    )
                ],
            )
        ],
        econ=[
            EconEventView(
                event_key="k",
                title="CPI m/m",
                scheduled_at=datetime(2026, 10, 15, 12, 30, tzinfo=UTC),
                impact="High",
                forecast="0.3%",
            )
        ],
        earnings=[
            EarningsView(symbol="NVDA", report_date=date(2026, 10, 15), timing="amc", eps_est=2.0)
        ],
        held={"NVDA"},
        positions=[],
        movers=[TickerMove(symbol="PLTR", change_pct=-7.0, abnormal_pct=-5.8, sigma=2.5)],
    )
    base.update(kw)
    return D.DigestInputs(**base)


def test_close_digest_sections() -> None:
    p = D.build_digest("close", _inp())
    titles = [s.title for s in p.sections]
    assert (
        titles[:2] == ["Market", "Top stories"]
        and "Movers" in titles
        and "Tonight / tomorrow" in titles
    )
    assert p.kind == "digest_close"
    movers = next(s for s in p.sections if s.title == "Movers")
    assert "PLTR -7.0%" in movers.items[0].text


def test_reads_attach_to_threads() -> None:
    e = DigestRead(
        cluster_id=1,
        headline="Fed split on cuts",
        read="Split Fed means fewer cuts.",
        verdict="priced_in",
        evidence=["N1"],
    )
    p = D.build_digest("premarket", _inp(thread_order=[[1]], reads={1: e}, regime="risk_off"))
    top = next(s for s in p.sections if s.title == "Overnight")
    assert (
        top.items[0].read == "Split Fed means fewer cuts." and top.items[0].verdict == "priced_in"
    )
    assert p.regime == "risk_off"


def test_week_ahead_flags_earnings_before_expiry() -> None:
    from src.common.schemas import OptionRight, PositionSnapshot

    pos = [
        PositionSnapshot(
            symbol="NVDA",
            sec_type="OPT",
            position=-1,
            avg_cost=1,
            right=OptionRight.PUT,
            strike=165,
            expiry=date(2026, 10, 23),
            underlying="NVDA",
        )
    ]
    p = D.build_digest("week", _inp(positions=pos))
    risk = next(s for s in p.sections if s.title == "Earnings before your expiries")
    assert "NVDA" in risk.items[0].text


def _analytics():
    import pandas as pd

    from src.news.facts import Analytics

    return Analytics(
        technicals=lambda s: None,
        iv=lambda s: None,
        sector=lambda s: None,
        quote=lambda s: Quote(symbol=s),
        daily=lambda s: pd.DataFrame(),
        past_earnings=lambda s: [],
    )


def _seed_store(now: datetime) -> None:
    from datetime import timedelta

    from src.news.store.models import EarningsEventRow, EconEventRow, NewsClusterRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    fresh, stale = naive_utc(now - timedelta(hours=2)), naive_utc(now - timedelta(hours=20))

    def cluster(headline: str, category: str, seen: datetime, n: int) -> NewsClusterRow:
        return NewsClusterRow(
            headline=headline, category=category, first_seen=seen, last_seen=seen, source_count=n
        )

    def econ(key: str, at: datetime) -> EconEventRow:
        return EconEventRow(
            event_key=key,
            title="CPI m/m",
            playbook_key="cpi",
            scheduled_at=naive_utc(at),
            impact="High",
            alerted=False,
        )

    with news_session() as s:
        s.add_all(
            [
                cluster("Fed minutes", "macro", fresh, 3),
                cluster("Lone ticker blurb", "ticker", fresh, 1),
                cluster("Two-source ticker", "ticker", fresh, 2),
                cluster("Yesterday macro", "macro", stale, 5),
                econ("soon", now + timedelta(days=1)),
                econ("far", now + timedelta(days=10)),
                EarningsEventRow(
                    symbol="NVDA",
                    report_date=date(2026, 10, 15),
                    timing="amc",
                    status="scheduled",
                    alerted=False,
                ),
                EarningsEventRow(
                    symbol="AAPL",
                    report_date=date(2026, 11, 5),
                    timing="amc",
                    status="scheduled",
                    alerted=False,
                ),
            ]
        )


def test_gather_inputs_reads_store_and_picks_tape_by_digest(news_db, monkeypatch) -> None:
    import src.news.collectors as col
    import src.news.tape as tp
    from src.common.config import get_config

    now = datetime(2026, 10, 14, 20, 30, tzinfo=UTC)
    _seed_store(now)
    asked: list[list[str]] = []

    def fake_tape(syms, **_):
        asked.append(list(syms))
        return {s: Quote(symbol=s, change_pct=0.5) for s in syms}

    monkeypatch.setattr(tp, "tape", fake_tape)
    monkeypatch.setattr(col, "held_positions", lambda: [])
    monkeypatch.setattr(col, "held_underlyings", lambda: {"NVDA"})
    cfg = get_config()

    close = D.gather_inputs("close", now=now, cfg=cfg, an=_analytics())
    assert {c.headline for c in close.clusters} == {
        "Fed minutes",
        "Two-source ticker",
    }  # lone ticker blurb and 20 h old dropped
    assert [e.event_key for e in close.econ] == ["soon"]
    assert [e.symbol for e in close.earnings] == ["NVDA"]
    assert close.held == {"NVDA"} and close.movers == []
    assert (close.max_threads, close.max_movers) == (
        cfg.news.digests.max_threads,
        cfg.news.digests.max_movers,
    )

    D.gather_inputs("premarket", now=now, cfg=cfg, an=_analytics())
    assert asked == [cfg.news.tape_symbols_rth, cfg.news.tape_symbols_ext]

    week = D.gather_inputs("week", now=now, cfg=cfg, an=_analytics())
    assert "Yesterday macro" in {
        c.headline for c in week.clusters
    }  # the week-ahead looks back 72 h, not 16
