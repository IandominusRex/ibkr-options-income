"""Task 8: the triage/picture tables, their Session-parameterised readers and the per-purpose
LLM budget (a share of the daily cap is reserved for triage and picture builds)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.common.schemas import (
    MarketPicture,
    MarketRegime,
    NoiseSummary,
    PictureFact,
    PictureRegime,
    PictureStory,
    SeasonalityView,
)
from src.news import llm
from src.news.store import queries
from src.news.store.models import (
    MarketPictureRow,
    NewsBase,
    NewsClusterRow,
    PictureStoryRow,
    StoryTriageRow,
)
from src.news.store.queries import naive_utc
from src.news.store.session import get_news_engine, news_session
from src.news.store.state import llm_calls

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)
DAY = date(2026, 10, 22)


def _picture(**kw) -> MarketPicture:
    base = dict(
        version=NOW.isoformat(),
        built_at=NOW,
        regimes=[
            PictureRegime(
                index="SPY",
                effective=MarketRegime.NORMAL,
                base=MarketRegime.NORMAL,
                as_of=NOW,
            ),
            PictureRegime(
                index="QQQ",
                effective=MarketRegime.STRESSED,
                base=MarketRegime.CAUTIOUS,
                eased_by_bottoming=False,
                suspended=True,
                as_of=NOW,
            ),
        ],
        regime_source="trading",
        facts=[PictureFact(label="VIX", value="23.4")],
        seasonality=SeasonalityView(month=10, avg_return_pct=1.2, up_share=0.6, years=5),
        events=["FOMC Wed 14:00 ET"],
        stories=[
            PictureStory(
                id=3,
                title="Tariff escalation",
                started_on=date(2026, 10, 12),
                description="Tariff headlines keep the index under its 50-day average.",
                evidence=["C41", "F2"],
            )
        ],
        noise=NoiseSummary(judged=12, not_reviewed=340, promotions=1),
    )
    base.update(kw)
    return MarketPicture(**base)


def _cfg(monkeypatch, **kw) -> None:
    cfg = get_config().news.llm
    for k, v in kw.items():
        monkeypatch.setattr(cfg, k, v)


def test_tables_created_by_init_news_db(news_db) -> None:
    names = set(inspect(get_news_engine()).get_table_names())
    assert {"story_triage", "market_pictures", "picture_stories"} <= names


def test_latest_picture_round_trips_the_schema(news_db) -> None:
    older = _picture(
        version=(NOW - timedelta(hours=5)).isoformat(), built_at=NOW - timedelta(hours=5)
    )
    newest = _picture()
    with news_session() as s:
        for p, stale in ((older, False), (newest, True)):
            s.add(
                MarketPictureRow(
                    built_at=naive_utc(p.built_at),
                    version=p.version,
                    payload=p.model_dump(mode="json"),
                    stale=stale,
                )
            )
    with news_session() as s:
        got = queries.latest_picture(s)
    assert got is not None
    assert got.version == newest.version
    assert got.regimes[1].effective is MarketRegime.STRESSED and got.regimes[1].suspended
    assert got.stories[0].title == "Tariff escalation" and got.stories[0].evidence == ["C41", "F2"]
    assert got.seasonality is not None and got.seasonality.years == 5
    assert got.noise.not_reviewed == 340
    assert (
        got.stale is True
    )  # the row's flag wins: a failed rebuild is stale whatever the JSON says


def test_latest_picture_is_none_when_the_payload_no_longer_validates(news_db) -> None:
    with news_session() as s:
        s.add(
            MarketPictureRow(
                built_at=naive_utc(NOW), version="v", payload={"stories": "oops"}, stale=False
            )
        )
    with news_session() as s:
        assert queries.latest_picture(s) is None


def test_triage_since_joins_the_cluster_and_filters_on_last_seen(news_db) -> None:
    with news_session() as s:
        for cid, age_h in ((1, 2), (2, 40)):
            s.add(
                NewsClusterRow(
                    id=cid,
                    headline=f"headline {cid}",
                    category="macro",
                    first_seen=naive_utc(NOW - timedelta(hours=age_h)),
                    last_seen=naive_utc(NOW - timedelta(hours=age_h)),
                    tickers=[],
                    tags=[],
                )
            )
            s.add(
                StoryTriageRow(
                    cluster_id=cid,
                    pile=3,
                    floor=None,
                    rank=1.5,
                    reason="calendar filler",
                    judged_at=naive_utc(NOW),
                )
            )
        s.add(StoryTriageRow(cluster_id=9, pile=None, rank=0.2))  # no cluster row: skipped
    with news_session() as s:
        got = queries.triage_since(s, NOW - timedelta(hours=16))
    assert [(v.cluster_id, v.headline, v.pile, v.reason) for v in got] == [
        (1, "headline 1", 3, "calendar filler")
    ]


def test_active_stories_returns_only_the_active_ones(news_db) -> None:
    with news_session() as s:
        s.add(
            PictureStoryRow(
                title="live",
                started_on=DAY,
                last_supported_at=naive_utc(NOW),
                cluster_ids=[1, 2],
                active=True,
            )
        )
        s.add(
            PictureStoryRow(
                title="over",
                started_on=DAY,
                last_supported_at=naive_utc(NOW),
                cluster_ids=[3],
                active=False,
                ended_on=DAY,
            )
        )
    with news_session() as s:
        assert [r.title for r in queries.active_stories(s)] == ["live"]


def test_queries_return_empty_on_an_old_news_db(tmp_path) -> None:
    """A news.db written before these tables existed: the API's read-only engine cannot create
    them, so a reader gets 'nothing yet', never an exception."""
    new = {"story_triage", "market_pictures", "picture_stories"}
    engine = create_engine(f"sqlite:///{tmp_path / 'old-news.db'}")
    NewsBase.metadata.create_all(
        engine, tables=[t for name, t in NewsBase.metadata.tables.items() if name not in new]
    )
    with Session(engine) as s:
        assert queries.latest_picture(s) is None
        assert queries.triage_since(s, NOW - timedelta(days=1)) == []
        assert queries.active_stories(s) == []


def test_general_calls_stop_at_the_reserve_picture_calls_do_not(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli", max_calls_per_day=10, reserved_for_picture=4)
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: ("x", None))
    for _ in range(6):
        assert llm.call_llm("p", schema={}, prefix="t", now=NOW) is not None
    # six general calls = max - reserve: the next general call is refused, and says so
    assert llm.cap_reached(NOW) and llm.call_llm("p", schema={}, prefix="t", now=NOW) is None
    assert llm.cap_reached(NOW, purpose="general")
    # the reserve is still there for triage and picture builds
    assert not llm.cap_reached(NOW, purpose="picture")
    for _ in range(4):
        assert llm.call_llm("p", schema={}, prefix="t", now=NOW, purpose="picture") is not None
    assert llm.cap_reached(NOW, purpose="picture")  # the total cap holds for everyone
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW, purpose="picture") is None
    assert llm_calls(DAY) == 10


def test_general_is_counted_separately_from_picture(news_db, monkeypatch) -> None:
    """25 picture calls then general calls: general is allowed until general == 30 or total == 40."""
    _cfg(monkeypatch, backend="cli", max_calls_per_day=40, reserved_for_picture=10)
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: ("x", None))
    for _ in range(25):
        assert llm.call_llm("p", schema={}, prefix="t", now=NOW, purpose="picture")
    assert llm_calls(DAY) == 25 and llm_calls(DAY, "general") == 0
    assert llm_calls(DAY, "picture") == 25
    n = 0
    while llm.call_llm("p", schema={}, prefix="t", now=NOW) is not None:
        n += 1
    assert n == 15  # the total (40) bit before the general share (30) did
    assert llm_calls(DAY) == 40 and llm_calls(DAY, "general") == 15


def test_general_never_loses_the_whole_budget_to_a_big_reserve(news_db, monkeypatch) -> None:
    """A reserve at or above the cap must not silence the writer entirely: at least one general
    call a day is always allowed (while the total cap has room)."""
    _cfg(monkeypatch, backend="cli", max_calls_per_day=3, reserved_for_picture=10)
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: ("x", None))
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW) is not None
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW) is None


def test_a_failed_attempt_still_counts_against_its_purpose(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli_then_ollama", max_calls_per_day=10, reserved_for_picture=2)
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: (None, "cli_error"))
    monkeypatch.setattr(llm, "_ollama", lambda prompt, schema, cfg: "")
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW, purpose="picture") is None
    assert llm_calls(DAY) == 2 and llm_calls(DAY, "picture") == 2 and llm_calls(DAY, "general") == 0


@pytest.mark.parametrize("purpose", ["general", "picture"])
def test_each_purpose_is_counted_under_its_own_key(news_db, monkeypatch, purpose) -> None:
    _cfg(monkeypatch, backend="cli", max_calls_per_day=10, reserved_for_picture=2)
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: ("x", None))
    llm.call_llm("p", schema={}, prefix="t", now=NOW, purpose=purpose)
    other = "picture" if purpose == "general" else "general"
    assert llm_calls(DAY, purpose) == 1 and llm_calls(DAY, other) == 0 and llm_calls(DAY) == 1


def test_example_news_config_carries_the_triage_and_picture_blocks() -> None:
    cfg = get_config().news
    assert cfg.llm.reserved_for_picture == 10 and cfg.llm.max_calls_per_day == 40
    t = cfg.triage
    assert t.enabled and t.batch_size == 40 and t.rth_batch_times == ["10:30", "12:30", "14:30"]
    assert t.promote_index_move_pct == 1.0 and t.promote_ticker_residual_pct == 3.0
    assert t.promote_window_min == 60 and t.max_promotions_per_hour == 2
    p = cfg.picture
    assert p.enabled and p.max_rebuilds_per_day == 4 and p.max_stories == 5
    assert p.story_window_days == 7 and p.story_min_new_clusters == 2
    assert p.story_match_jaccard == 0.3 and p.staleness_hours == 26


def test_triage_and_picture_config_validate() -> None:
    from pydantic import ValidationError

    from src.common.config import NewsPictureCfg, NewsTriageCfg

    with pytest.raises(ValidationError):
        NewsTriageCfg(rth_batch_times=["9:30"])  # zero-padded HH:MM only
    with pytest.raises(ValidationError):
        NewsTriageCfg(batch_size=0)
    with pytest.raises(ValidationError):
        NewsPictureCfg(story_match_jaccard=1.5)
    with pytest.raises(ValidationError):
        NewsPictureCfg(max_stories=0)
