"""The ticker-dossier table, its Session-parameterised readers and the dossier LLM budget (Task 17).

Spec section 16: the news process keeps one record per name in data/news.db (latest wins, older
rows kept for audit); readers get the latest through ``queries.latest_dossier(s)`` and never
write. The dossier's calls have a budget of their own beside the general and picture ones.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.common.schemas import DossierEvent, DossierFact, TickerDossier
from src.news import llm
from src.news.store import queries
from src.news.store.models import NewsBase, TickerDossierRow
from src.news.store.queries import naive_utc
from src.news.store.session import get_news_engine, news_session
from src.news.store.state import llm_calls

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)
DAY = date(2026, 10, 22)


def dossier(symbol: str = "META", at: datetime = NOW, **kw) -> TickerDossier:
    base = dict(
        symbol=symbol,
        version=f"{symbol}@{at.isoformat()}",
        facts_at=at,
        prose_at=at - timedelta(hours=2),
        profile_at=at - timedelta(days=2),
        kind="stock",
        health="strong",
        health_why=["passes the quality screen"],
        facts=[
            DossierFact(id=f"{symbol}:F1", label="RSI14", display="RSI 52"),
            DossierFact(id=f"{symbol}:F2", label="Price vs SMA200", display="+4.1% vs SMA200"),
        ],
        sentiment_7d=0.12,
        sentiment_items_7d=14,
        profile="A social-media and AI company; ad revenue and capex drive the shares.",
        story="Launching a new glasses line next week (C8123).",
        story_evidence=["C8123"],
        events=[
            DossierEvent(
                id=f"{symbol}:E1",
                title="MUSE launch event",
                on=date(2026, 10, 29),
                evidence="C8123",
                quote="Meta will unveil MUSE at Connect on Oct 29.",
            )
        ],
    )
    base.update(kw)
    return TickerDossier(**base)


def save(d: TickerDossier, *, built_at: datetime | None = None) -> None:
    with news_session() as s:
        s.add(
            TickerDossierRow(
                symbol=d.symbol,
                version=d.version,
                built_at=naive_utc(built_at or d.facts_at),
                payload=d.model_dump(mode="json"),
            )
        )


def _cfg(monkeypatch, **kw) -> None:
    cfg = get_config().news.llm
    for k, v in kw.items():
        monkeypatch.setattr(cfg, k, v)


def test_table_created_and_latest_dossier_round_trips(news_db) -> None:
    assert "ticker_dossiers" in set(inspect(get_news_engine()).get_table_names())
    d = dossier()
    save(d)
    with news_session() as s:
        got = queries.latest_dossier(s, "META")
    assert got == d
    assert got is not None and got.events[0].on == date(2026, 10, 29)
    with news_session() as s:
        assert queries.latest_dossier(s, "NVDA") is None
        assert queries.latest_dossier(s, "meta") == d  # a symbol is matched upper-cased


def test_latest_wins_per_symbol(news_db) -> None:
    old = dossier("META", NOW - timedelta(hours=3), story="old story")
    new = dossier("META", NOW, story="new story")
    amd = dossier("AMD", NOW - timedelta(hours=1))
    for d in (new, old, amd):  # saved out of order: the build time decides, not the row id
        save(d)
    with news_session() as s:
        got = queries.latest_dossiers(s, ["META", "AMD", "NVDA"])
    assert set(got) == {"META", "AMD"}
    assert got["META"].story == "new story"
    assert got["AMD"].symbol == "AMD"
    with news_session() as s:
        assert queries.latest_dossiers(s, []) == {}


def test_a_payload_that_no_longer_validates_reads_as_none(news_db) -> None:
    with news_session() as s:
        s.add(
            TickerDossierRow(
                symbol="META", version="v", built_at=naive_utc(NOW), payload={"facts": "oops"}
            )
        )
    with news_session() as s:
        assert queries.latest_dossier(s, "META") is None
        assert queries.latest_dossiers(s, ["META"]) == {}


def test_queries_return_empty_on_an_old_news_db(tmp_path) -> None:
    """A news.db written before this table existed: the API's read-only engine cannot create
    it, so a reader gets 'nothing yet', never an exception."""
    engine = create_engine(f"sqlite:///{tmp_path / 'old-news.db'}")
    NewsBase.metadata.create_all(
        engine,
        tables=[t for name, t in NewsBase.metadata.tables.items() if name != "ticker_dossiers"],
    )
    with Session(engine) as s:
        assert queries.latest_dossier(s, "META") is None
        assert queries.latest_dossiers(s, ["META", "AMD"]) == {}


# --------------------------------------------------------------------------- #
# The budget
# --------------------------------------------------------------------------- #


def test_dossier_budget_has_its_own_cap_and_general_keeps_thirty(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli", max_calls_per_day=44, reserved_for_picture=10)
    monkeypatch.setattr(get_config().news.dossier, "max_calls_per_day", 4)
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: ("x", None))

    def call(purpose: str):
        return llm.call_llm("p", schema={}, prefix="t", now=NOW, purpose=purpose)

    # the dossier's own cap: four allowed, the fifth refused (and says so)
    assert [call("dossier") is not None for _ in range(5)] == [True] * 4 + [False]
    assert llm.cap_reached(NOW, purpose="dossier")
    assert llm_calls(DAY, "dossier") == 4
    # general keeps its thirty (44 - 10 reserved - 4 dossier): the 31st is refused
    assert [call("general") is not None for _ in range(31)] == [True] * 30 + [False]
    assert llm.cap_reached(NOW, purpose="general")
    # the picture reserve is intact: ten more, then the total (44) bites for everyone
    assert [call("picture") is not None for _ in range(11)] == [True] * 10 + [False]
    assert llm_calls(DAY) == 44
    assert llm.cap_reached(NOW, purpose="picture") and llm.cap_reached(NOW, purpose="dossier")


def test_dossier_calls_never_push_the_total_past_the_cap(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli", max_calls_per_day=6, reserved_for_picture=0)
    monkeypatch.setattr(get_config().news.dossier, "max_calls_per_day", 4)
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: ("x", None))
    for _ in range(5):
        assert llm.call_llm("p", schema={}, prefix="t", now=NOW, purpose="picture")
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW, purpose="dossier")  # 6th: the cap
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW, purpose="dossier") is None
    assert llm_calls(DAY) == 6 and llm_calls(DAY, "dossier") == 1


def test_a_disabled_dossier_gives_its_share_back_to_general(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli", max_calls_per_day=44, reserved_for_picture=10)
    monkeypatch.setattr(get_config().news.dossier, "max_calls_per_day", 4)
    monkeypatch.setattr(get_config().news.dossier, "enabled", False)
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: ("x", None))
    n = 0
    while llm.call_llm("p", schema={}, prefix="t", now=NOW) is not None:
        n += 1
    assert n == 34  # 44 - 10: the dossier's four are not held back
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW, purpose="dossier") is None
