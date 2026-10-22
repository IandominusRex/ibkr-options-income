"""The dossier's deterministic half (Task 17): who gets one, its kind, health, numbered facts,
the verified event date, and the hourly refresh that copies the prose forward.

Python writes every number and recomputes it on every build; nothing here calls a model.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from src.common.config import NewsDossierHealthCfg, get_config
from src.common.schemas import (
    DossierEvent,
    FundamentalStats,
    IVStats,
    SectorContext,
    TechnicalStats,
)
from src.news import dossier as D
from src.news.facts import Analytics
from src.news.store import queries
from src.news.store.models import TickerDossierRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from src.news.store.state import get_state
from src.news.tape import Quote
from tests.test_dossier_store import dossier, save

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)  # Thu 11:00 ET
TODAY = date(2026, 10, 22)


def an(*, bars: int = 100) -> Analytics:
    """A stub analytics bundle: a steadily rising price, so the returns are known."""
    idx = pd.bdate_range(end=pd.Timestamp(TODAY), periods=bars)
    closes = pd.Series([100.0 + i for i in range(bars)], index=idx)
    daily = pd.DataFrame({"Close": closes})
    last = float(closes.iloc[-1])
    quotes = {
        "SPY": Quote(symbol="SPY", last=600, prev_close=606, change_pct=-1.0),
    }
    return Analytics(
        technicals=lambda s: TechnicalStats(
            symbol=s,
            price=last,
            rsi_14=52.0,
            atr_14=3.0,
            sma_200=last - 5.0,
            support_levels=[last - 8.0],
            resistance_levels=[last + 9.0],
        ),
        iv=lambda s: IVStats(symbol=s, current_iv=40.0, iv_rank=55.0, hv_30=30.0),
        sector=lambda s: SectorContext(symbol=s, sector="Technology", sector_etf="XLK"),
        quote=lambda s: quotes.get(
            s, Quote(symbol=s, last=last, prev_close=last - 2, change_pct=1.0)
        ),
        daily=lambda s: daily,
        past_earnings=lambda s: [],
    )


# --------------------------------------------------------------------------- #
# who gets one, and what kind
# --------------------------------------------------------------------------- #


def test_dossier_symbols_are_universe_plus_held(monkeypatch) -> None:
    monkeypatch.setattr(
        D,
        "effective_universe",
        lambda: {
            "would_own": ["nvda", "META"],
            "actively_wheeling": ["META", "BAC"],
            "watchlist": ["TSLA"],  # watched, not a dossier name
            "indexes": ["QQQ"],
        },
    )
    monkeypatch.setattr(D, "held_underlyings", lambda: {"AMD", "NVDA", "SPY"})
    # AMD is held but in neither list: it is included. SPY is the spreads book's: never.
    assert D.dossier_symbols() == ["AMD", "BAC", "META", "NVDA"]


def test_dossier_symbols_empty_when_nothing_is_configured(monkeypatch) -> None:
    monkeypatch.setattr(D, "effective_universe", lambda: {})
    monkeypatch.setattr(D, "held_underlyings", lambda: set())
    assert D.dossier_symbols() == []


def test_kind_of_leveraged_etf_etf_and_stock(monkeypatch) -> None:
    monkeypatch.setattr(
        D,
        "effective_universe",
        lambda: {"leveraged_etfs": ["TQQQ", "SOXL"], "indexes": ["SPY", "QQQ"]},
    )
    assert D.kind_of("TQQQ", None) == "leveraged_etf"
    assert D.kind_of("tqqq", FundamentalStats(symbol="TQQQ", total_assets=2e10)) == "leveraged_etf"
    assert D.kind_of("QQQ", None) == "etf"  # an index fund, even with no fundamentals
    assert D.kind_of("SMH", FundamentalStats(symbol="SMH", total_assets=1e10)) == "etf"
    assert D.kind_of("META", FundamentalStats(symbol="META", pe_ratio=25.0)) == "stock"
    assert D.kind_of("META", None) == "stock"


HEALTH = NewsDossierHealthCfg(de_strong=100.0, de_weak=200.0)


def f(**kw) -> FundamentalStats:
    return FundamentalStats(symbol="X", **kw)


@pytest.mark.parametrize(
    ("fund", "kind", "expected"),
    [
        (f(quality_flag=True, free_cash_flow=5e9), "etf", ("n/a", [])),
        (f(quality_flag=True), "leveraged_etf", ("n/a", [])),
        (None, "stock", ("unknown", ["no fundamentals"])),
        (f(pe_ratio=20.0), "stock", ("unknown", ["no fundamentals"])),
        (
            f(quality_flag=True, free_cash_flow=-1.0),
            "stock",
            ("weak", ["free cash flow negative"]),
        ),
        (
            f(quality_flag=True, free_cash_flow=5e9, debt_to_equity=240.0),
            "stock",
            ("weak", ["debt/equity 2.4x"]),
        ),
        (
            f(free_cash_flow=-5e8, debt_to_equity=300.0),
            "stock",
            ("weak", ["free cash flow negative", "debt/equity 3.0x"]),
        ),
        (
            f(quality_flag=True, free_cash_flow=5e9, debt_to_equity=80.0),
            "stock",
            ("strong", ["passes the quality screen"]),
        ),
        (
            f(quality_flag=True, free_cash_flow=5e9),
            "stock",
            ("strong", ["passes the quality screen"]),
        ),
        (
            f(quality_flag=True, free_cash_flow=5e9, debt_to_equity=100.0),
            "stock",
            ("strong", ["passes the quality screen"]),
        ),  # exactly at de_strong is still strong
        (
            f(quality_flag=True, free_cash_flow=5e9, debt_to_equity=150.0),
            "stock",
            ("ok", ["passes the quality screen", "debt/equity 1.5x"]),
        ),
        (
            f(quality_flag=True, free_cash_flow=5e9, debt_to_equity=200.0),
            "stock",
            ("ok", ["passes the quality screen", "debt/equity 2.0x"]),
        ),  # exactly at de_weak is not yet weak
        (
            f(quality_flag=False, free_cash_flow=5e9, debt_to_equity=50.0),
            "stock",
            ("ok", ["fails the quality screen"]),
        ),
        (
            f(quality_flag=True, free_cash_flow=0.0, debt_to_equity=50.0),
            "stock",
            ("ok", ["passes the quality screen", "free cash flow not positive"]),
        ),
        (
            f(quality_flag=True, debt_to_equity=50.0),
            "stock",
            ("ok", ["passes the quality screen", "free cash flow unknown"]),
        ),
    ],
)
def test_health_label_rules(fund, kind, expected) -> None:
    assert D.health_label(fund, kind, HEALTH) == expected


def test_the_health_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="de_strong"):
        NewsDossierHealthCfg(de_strong=250.0, de_weak=200.0)


# --------------------------------------------------------------------------- #
# the numbered facts
# --------------------------------------------------------------------------- #


def test_facts_have_prefixed_ids_and_no_book(news_db, monkeypatch) -> None:
    seen: dict[str, object] = {}
    real = D.build_ticker_facts

    def spy(symbol, **kw):
        seen.update(kw)
        return real(symbol, **kw)

    monkeypatch.setattr(D, "build_ticker_facts", spy)
    # a held position exists in the book, and must still never reach a dossier
    monkeypatch.setattr(D, "held_underlyings", lambda: {"META"})
    with news_session() as s:
        facts, sentiment, count = D.build_facts(
            "META", an=an(), today=TODAY, cfg=get_config().news, session=s, now=NOW
        )
    assert seen["positions"] == []  # ruling 24: the book block already shows positions
    assert facts and all(x.id.startswith("META:F") for x in facts)
    assert [x.id for x in facts] == [f"META:F{i}" for i in range(1, len(facts) + 1)]
    labels = [x.label for x in facts]
    assert not any(label.startswith(("Shares", "Position")) for label in labels)
    for must in ("RSI14", "Price vs SMA200", "Nearest resistance", "IV rank", "Universe"):
        assert must in labels, must
    by_label = {x.label: x.display for x in facts}
    # 100 rising bars, +1 a bar from 100 (last close 199). 21 sessions back is 178, 63 back is 136.
    assert by_label["1-month return"] == "+11.8% (21 sessions)"
    assert by_label["3-month return"] == "+46.3% (63 sessions)"
    assert by_label["Regime index"] == "QQQ"  # META is tech-linked
    assert sentiment is None and count == 0  # nothing ingested


def test_the_governing_regime_index_follows_tech_linkage(news_db) -> None:
    with news_session() as s:
        bac, *_ = D.build_facts("BAC", an=an(), today=TODAY, cfg=get_config().news, session=s)
    assert {x.label: x.display for x in bac}["Regime index"] == "SPY"


def test_returns_need_enough_history(news_db) -> None:
    with news_session() as s:
        facts, _, _ = D.build_facts(
            "META", an=an(bars=30), today=TODAY, cfg=get_config().news, session=s
        )
    labels = {x.label for x in facts}
    assert "1-month return" in labels and "3-month return" not in labels


def test_sentiment_is_the_seven_day_mean_of_deterministic_scores(news_db, monkeypatch) -> None:
    got: dict[str, object] = {}

    def rows(s, symbol, since):
        got["since"] = since
        return [
            (0.5, NOW - timedelta(hours=3), 1, "a"),
            (-0.1, NOW - timedelta(days=2), 2, "b"),
            (0.2, NOW - timedelta(days=6), 3, "c"),
        ]

    monkeypatch.setattr(queries, "ticker_sentiment_rows", rows)
    with news_session() as s:
        _, mean, count = D.build_facts(
            "META", an=an(), today=TODAY, cfg=get_config().news, session=s, now=NOW
        )
    assert mean == pytest.approx(0.2) and count == 3
    assert got["since"] == NOW - timedelta(days=7)


# --------------------------------------------------------------------------- #
# the verified event date
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "on", "ok"),
    [
        ("Meta to unveil MUSE at Connect on Oct 22", date(2026, 10, 22), True),
        ("event set for October 22, 2026", date(2026, 10, 22), True),
        ("on 10/22 the company", date(2026, 10, 22), True),
        ("scheduled 2026-10-22", date(2026, 10, 22), True),
        ("on Oct 2 the company", date(2026, 10, 22), False),
        ("event next Tuesday", date(2026, 10, 22), False),
        ("October 22, 2025", date(2026, 10, 22), False),
        # the other spellings the spec lists
        ("keynote Oct. 22 in San Jose", date(2026, 10, 22), True),
        ("keynote on OCT 22nd", date(2026, 10, 22), True),
        ("keynote on 22 October", date(2026, 10, 22), True),
        ("keynote on 22nd of October 2026", date(2026, 10, 22), True),
        ("keynote on October 22 2026", date(2026, 10, 22), True),
        ("keynote 10/22/2026", date(2026, 10, 22), True),
        ("keynote 10/22/26", date(2026, 10, 22), True),
        ("keynote 10/22/2025", date(2026, 10, 22), False),
        # near misses
        ("keynote on October 23", date(2026, 10, 22), False),
        ("keynote on Oct 220", date(2026, 10, 22), False),
        ("keynote on Nov 22", date(2026, 10, 22), False),
        ("keynote on 110/22", date(2026, 10, 22), False),
        ("keynote on 10/22 3pm", date(2026, 10, 22), True),
        ("keynote on 2026-10-23", date(2026, 10, 22), False),
        ("later this month", date(2026, 10, 22), False),
        ("tomorrow at Connect", date(2026, 10, 22), False),
        ("Oct 2 and again on Oct 22", date(2026, 10, 22), True),  # a later valid mention counts
        ("in May", date(2026, 5, 2), False),
        ("on May 2", date(2026, 5, 2), True),
        ("on Sept 9", date(2026, 9, 9), True),
        ("on September 9th", date(2026, 9, 9), True),
    ],
)
def test_verify_event_date(text, on, ok) -> None:
    snippet = D.verify_event_date(text, on)
    assert (snippet is not None) is ok
    if ok:
        assert snippet is not None and len(snippet) <= 200 and snippet in text


def test_the_snippet_is_bounded_and_surrounds_the_date() -> None:
    padding = "word " * 200
    text = f"{padding}the launch event is on Oct 22 at the campus {padding}"
    snippet = D.verify_event_date(text, date(2026, 10, 22))
    assert snippet is not None and len(snippet) <= 200
    assert "Oct 22" in snippet and "launch event" in snippet


# --------------------------------------------------------------------------- #
# the hourly refresh
# --------------------------------------------------------------------------- #


def fund_stub(symbol: str) -> FundamentalStats:
    return FundamentalStats(
        symbol=symbol, quality_flag=True, free_cash_flow=1e9, debt_to_equity=40.0
    )


def latest(symbol: str):
    with news_session() as s:
        return queries.latest_dossier(s, symbol)


def test_facts_refresh_keeps_prose_and_drops_past_events(news_db, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", lambda: ["META"])
    past = DossierEvent(
        id="META:E1",
        title="Earlier event",
        on=TODAY - timedelta(days=1),
        evidence="C1",
        quote="the event was on Oct 21",
    )
    today_ev = DossierEvent(
        id="META:E2", title="Today event", on=TODAY, evidence="C2", quote="on Oct 22"
    )
    future = DossierEvent(
        id="META:E3",
        title="Later event",
        on=TODAY + timedelta(days=7),
        evidence="C3",
        quote="on Oct 29",
    )
    prev = dossier(
        "META",
        NOW - timedelta(hours=2),
        events=[past, today_ev, future],
        stale=True,
        health="unknown",
        facts=[],
    )
    save(prev)

    assert D.refresh_facts(NOW, an=an(), fundamentals=fund_stub) == 1

    got = latest("META")
    assert got is not None
    assert got.facts_at == NOW and got.version != prev.version
    assert got.facts and got.facts[0].id == "META:F1"
    assert (got.kind, got.health) == ("stock", "strong")
    assert got.health_why == ["passes the quality screen"]
    # the prose is copied, not rewritten or refreshed
    assert (got.prose_at, got.profile_at, got.stale) == (prev.prose_at, prev.profile_at, True)
    assert (got.profile, got.story, got.story_evidence) == (
        prev.profile,
        prev.story,
        prev.story_evidence,
    )
    # events dated before today are dropped; today's and later ones stay
    assert [e.id for e in got.events] == ["META:E2", "META:E3"]


def test_a_new_name_gets_facts_and_no_prose(news_db, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", lambda: ["AMD"])
    assert D.refresh_facts(NOW, an=an(), fundamentals=fund_stub) == 1
    got = latest("AMD")
    assert got is not None
    assert got.prose_at is None and got.profile_at is None
    assert (got.profile, got.story, got.events, got.stale) == ("", "", [], False)
    assert got.facts_at == NOW and got.facts


def test_a_fresh_dossier_is_not_refreshed_again(news_db, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", lambda: ["META"])
    monkeypatch.setattr(get_config().news.dossier, "facts_refresh_min", 60)
    assert D.refresh_facts(NOW, an=an(), fundamentals=fund_stub) == 1
    assert D.refresh_facts(NOW + timedelta(minutes=59), an=an(), fundamentals=fund_stub) == 0
    assert D.refresh_facts(NOW + timedelta(minutes=61), an=an(), fundamentals=fund_stub) == 1
    with news_session() as s:
        assert s.query(TickerDossierRow).count() == 2  # one row per build, the latest wins


def test_refresh_is_a_no_op_when_disabled(news_db, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", lambda: ["META"])
    monkeypatch.setattr(get_config().news.dossier, "enabled", False)
    assert D.refresh_facts(NOW, an=an(), fundamentals=fund_stub) == 0
    assert latest("META") is None


def test_one_failing_name_does_not_stop_the_others(news_db, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", lambda: ["AMD", "META"])

    def boom(symbol: str):
        if symbol == "AMD":
            raise RuntimeError("provider down")
        return fund_stub(symbol)

    assert D.refresh_facts(NOW, an=an(), fundamentals=boom) == 1
    assert latest("AMD") is None and latest("META") is not None


def test_rows_older_than_keep_days_are_purged_once_a_day(news_db, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", lambda: ["META"])
    monkeypatch.setattr(get_config().news.dossier, "keep_days", 30)
    old = dossier("AMD", NOW - timedelta(days=40))
    recent = dossier("NVDA", NOW - timedelta(days=10))
    save(old)
    save(recent)
    assert D.refresh_facts(NOW, an=an(), fundamentals=fund_stub) == 1
    assert latest("AMD") is None and latest("NVDA") is not None
    assert get_state("dossier_purged_on") == TODAY.isoformat()
    # the purge ran today: an old row added later in the day waits for tomorrow
    save(dossier("AMD", NOW - timedelta(days=41), version="AMD@old2"))
    D.refresh_facts(NOW + timedelta(hours=2), an=an(), fundamentals=fund_stub)
    assert latest("AMD") is not None
    D.refresh_facts(NOW + timedelta(days=1), an=an(), fundamentals=fund_stub)
    assert latest("AMD") is None


def test_the_fresh_row_is_stored_naive_utc(news_db, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", lambda: ["META"])
    D.refresh_facts(NOW, an=an(), fundamentals=fund_stub)
    with news_session() as s:
        (row,) = s.query(TickerDossierRow).all()
        assert row.built_at == naive_utc(NOW) and row.symbol == "META"


def test_the_refresh_carries_the_newest_prose_not_the_one_it_started_from(
    news_db, monkeypatch
) -> None:
    """The numbers take a while to fetch. A prose build that lands meanwhile must survive: the
    refresh row carries the prose of the newest row at the moment it writes."""
    monkeypatch.setattr(D, "dossier_symbols", lambda: ["META"])
    save(
        dossier(
            "META", NOW - timedelta(hours=2), story="OLD story", prose_at=NOW - timedelta(hours=9)
        )
    )
    bundle = an()
    landed: list[bool] = []

    def quote_that_lets_a_prose_build_land(symbol: str):
        if not landed:  # once: the "other loop" writes a newer row with new prose
            landed.append(True)
            save(
                dossier(
                    "META",
                    NOW + timedelta(minutes=1),
                    story="NEW story",
                    prose_at=NOW + timedelta(minutes=1),
                    version="META@prose",
                )
            )
        return an().quote(symbol)

    bundle.quote = quote_that_lets_a_prose_build_land  # type: ignore[method-assign]
    assert D.refresh_facts(NOW, an=bundle, fundamentals=fund_stub) == 1
    got = latest("META")
    assert got is not None and got.story == "NEW story"
    assert got.prose_at == NOW + timedelta(minutes=1)
    assert got.facts_at == NOW and got.facts  # and the numbers are the fresh ones
