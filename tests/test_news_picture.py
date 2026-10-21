"""Task 10: the market picture the news process builds, and the seasonality it carries."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import select

from src.common.config import get_config
from src.common.schemas import (
    IndexRegime,
    MarketPicture,
    MarketRegime,
    PictureRegime,
    RegimeInputs,
    RegimeState,
    SeasonalityView,
)
from src.news import explain as X
from src.news import picture as P
from src.news.llm import LlmResult
from src.news.schemas import FactSheet, PictureDraft
from src.news.store import queries
from src.news.store.models import (
    EarningsEventRow,
    EconEventRow,
    MarketPictureRow,
    NewsClusterRow,
    PictureStoryRow,
    StoryTriageRow,
)
from src.news.store.queries import naive_utc
from src.news.store.session import news_session

NOW = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)  # Thursday 11:00 ET
DAY = date(2026, 10, 22)


# --- fixtures -----------------------------------------------------------------------------


def _facts() -> FactSheet:
    sh = FactSheet()
    sh.add("SPY", None, "close 560.12 · -3.4% vs 50-day · 8.0% below its 52-week high")  # F1
    sh.add("VIX", 23.4, "VIX 23.4 · VIX/VIX3M 0.93")  # F2
    return sh


def _regimes(source: str = "trading") -> list[PictureRegime]:
    return [
        PictureRegime(
            index=i,
            effective=MarketRegime.CAUTIOUS,
            base=MarketRegime.CAUTIOUS,
            as_of=NOW,
        )
        for i in ("SPY", "QQQ")
    ]


class FakeLlm:
    """Stands in for ``explain.call_llm``: replies with the given stories, records each call."""

    def __init__(self, stories: list[dict] | None, *, fail: bool = False) -> None:
        self.stories = stories or []
        self.fail = fail
        self.calls: list[dict] = []

    def __call__(self, prompt: str, **kw) -> LlmResult | None:
        self.calls.append({"prompt": prompt, **kw})
        if self.fail:
            return None
        return LlmResult(json.dumps({"stories": self.stories}), "cli")


def _seed_cluster(
    cid: int,
    *,
    tickers: tuple[str, ...] = (),
    topic: str = "tariff",
    age_h: float = 6,
    pile: int | None = 1,
    rank: float = 2.0,
    category: str = "macro",
    headline: str | None = None,
) -> None:
    seen = naive_utc(NOW - timedelta(hours=age_h))
    with news_session() as s:
        s.add(
            NewsClusterRow(
                id=cid,
                headline=headline or f"headline {cid}",
                category=category,
                first_seen=seen,
                last_seen=seen,
                source_count=3,
                tickers=list(tickers),
                tags=[],
                topic_class=topic,
            )
        )
        s.add(
            StoryTriageRow(
                cluster_id=cid,
                pile=pile,
                rank=rank,
                reason="r",
                judged_at=seen if pile is not None else None,
            )
        )


def _seed_story(title: str, *, started: date, cluster_ids: list[int], active: bool = True) -> int:
    with news_session() as s:
        row = PictureStoryRow(
            title=title,
            started_on=started,
            last_supported_at=naive_utc(NOW - timedelta(days=1)),
            cluster_ids=cluster_ids,
            active=active,
        )
        s.add(row)
        s.flush()
        return row.id


def _draft(**kw) -> dict:
    base = {
        "story_id": None,
        "title": "Tariff escalation",
        "description": "Tariff headlines keep the index under its 50-day average.",
        "evidence": ["C1", "F1"],
    }
    base.update(kw)
    return base


@pytest.fixture()
def pic(news_db, monkeypatch):
    """A news.db with canned facts, no events and no seasonality; returns the LLM installer."""
    monkeypatch.setattr(P, "picture_facts", lambda now: (_facts(), _regimes(), "trading"))
    monkeypatch.setattr(P, "upcoming_events", lambda now: ["FOMC Wed 14:00 ET"])
    monkeypatch.setattr(P, "month_seasonality", lambda month: None)

    def install(stories=None, *, fail: bool = False) -> FakeLlm:
        fake = FakeLlm(stories, fail=fail)
        monkeypatch.setattr(X, "call_llm", fake)
        return fake

    return install


def _stories_rows() -> dict[int, PictureStoryRow]:
    with news_session() as s:
        return {r.id: r for r in s.scalars(select(PictureStoryRow))}


def _saved() -> MarketPicture:
    with news_session() as s:
        p = queries.latest_picture(s)
    assert p is not None
    return p


# --- the model's drafts: validation -------------------------------------------------------


def test_a_cited_grounded_story_is_kept_and_saved(pic) -> None:
    _seed_cluster(1, tickers=("NVDA",))
    fake = pic([_draft()])
    got = P.build_picture(NOW)
    assert got is not None and len(fake.calls) == 1
    assert [s.title for s in got.stories] == ["Tariff escalation"]
    story = got.stories[0]
    assert story.evidence == ["C1", "F1"] and story.started_on == DAY
    assert story.description.startswith("Tariff headlines")
    assert got.stale is False and got.regime_source == "trading"
    assert got.events == ["FOMC Wed 14:00 ET"]
    assert [f.label for f in got.facts] == ["SPY", "VIX"]
    assert _saved().version == got.version == NOW.isoformat()
    rows = _stories_rows()
    assert [(r.id, r.active, r.cluster_ids) for r in rows.values()] == [(story.id, True, [1])]
    with news_session() as s:
        assert s.scalar(select(StoryTriageRow.story_id).where(StoryTriageRow.cluster_id == 1)) == (
            story.id
        )


def test_uncited_story_is_dropped(pic) -> None:
    _seed_cluster(1)
    pic(
        [
            _draft(evidence=[]),
            _draft(title="Ghost", evidence=["C999", "F99"]),  # ids that do not exist
        ]
    )
    got = P.build_picture(NOW)
    assert got is not None and got.stories == [] and _stories_rows() == {}


def test_invalid_ids_are_removed_but_a_valid_one_keeps_the_story(pic) -> None:
    _seed_cluster(1)
    pic([_draft(evidence=["C1", "C999", "F99", "N1"])])
    got = P.build_picture(NOW)
    assert got is not None and got.stories[0].evidence == ["C1"]


def test_new_story_needs_a_pile_one_cluster(pic) -> None:
    _seed_cluster(1, pile=2)  # worth telling, but it does not shape the picture
    _seed_cluster(2, pile=1)
    pic(
        [
            _draft(title="From a pile 2 cluster", evidence=["C1", "F1"]),
            _draft(title="From a pile 1 cluster", evidence=["C2", "F1"]),
        ]
    )
    got = P.build_picture(NOW)
    assert got is not None and [s.title for s in got.stories] == ["From a pile 1 cluster"]
    # facts alone cannot start a story either
    pic([_draft(title="Facts only", evidence=["F1", "F2"])])
    again = P.build_picture(NOW + timedelta(minutes=5))
    assert again is not None and [s.title for s in again.stories] == []


def test_ungrounded_number_drops_the_story(pic) -> None:
    _seed_cluster(1)
    pic(
        [
            _draft(
                title="Invented number",
                description="The index fell 7.77% on tariff headlines.",  # 7.77 is in no fact
            ),
            _draft(
                title="Grounded number",
                description="The index sits 8.0% below its 52-week high.",  # F1 says 8.0
            ),
        ]
    )
    got = P.build_picture(NOW)
    assert got is not None and [s.title for s in got.stories] == ["Grounded number"]


def test_advice_in_a_description_drops_the_story(pic) -> None:
    _seed_cluster(1)
    pic(
        [
            _draft(
                title="Advice", description="Tariffs weigh on tech. Consider reducing exposure."
            ),
            _draft(title="Prompt talk", description="The facts supplied show a weak tape."),
        ]
    )
    got = P.build_picture(NOW)
    assert got is not None and got.stories == []


def test_ids_in_prose_drop_the_story(pic) -> None:
    _seed_cluster(1)
    pic([_draft(description="Tariffs keep pressure on the index (see F1), says C1.")])
    got = P.build_picture(NOW)
    assert got is not None and got.stories == []


def test_a_number_in_the_title_is_grounded_too(pic) -> None:
    _seed_cluster(1)
    pic([_draft(title="Index down 9.9% on tariffs")])
    got = P.build_picture(NOW)
    assert got is not None and got.stories == []


def test_stories_are_capped_at_max_stories(pic, monkeypatch) -> None:
    monkeypatch.setattr(get_config().news.picture, "max_stories", 2)
    _seed_cluster(1)
    pic([_draft(title=f"Story {i}") for i in range(4)])
    got = P.build_picture(NOW)
    assert got is not None and [s.title for s in got.stories] == ["Story 0", "Story 1"]
    assert len(_stories_rows()) == 2  # a story that is not shown is not created


def test_the_draft_schema_caps_stories_at_five() -> None:
    with pytest.raises(ValueError):
        PictureDraft.model_validate({"stories": [_draft(title=f"s{i}") for i in range(6)]})


# --- continuing stories and previous prose ------------------------------------------------


def test_previous_prose_is_never_in_the_prompt(pic) -> None:
    _seed_cluster(1)
    sid = _seed_story("Tariff escalation", started=date(2026, 10, 15), cluster_ids=[1])
    old = MarketPicture(
        version="v0",
        built_at=NOW - timedelta(hours=6),
        stories=[
            {
                "id": sid,
                "title": "Tariff escalation",
                "started_on": "2026-10-15",
                "description": "OLD PROSE THE MODEL MUST NOT SEE AGAIN",
                "evidence": ["C1"],
            }
        ],
    )
    with news_session() as s:
        s.add(
            MarketPictureRow(
                built_at=naive_utc(old.built_at),
                version=old.version,
                payload=old.model_dump(mode="json"),
                stale=False,
            )
        )
    fake = pic([_draft(story_id=sid)])
    P.build_picture(NOW)
    prompt = fake.calls[0]["prompt"]
    assert f"S{sid} Tariff escalation (since Oct 15)" in prompt  # the identity, title only
    assert "OLD PROSE" not in prompt


def test_a_continued_story_keeps_its_stored_identity(pic) -> None:
    _seed_cluster(1)
    sid = _seed_story("Tariff escalation", started=date(2026, 10, 15), cluster_ids=[1])
    pic([_draft(story_id=sid, title="Renamed by the model", description="A fresh description.")])
    got = P.build_picture(NOW)
    assert got is not None and len(got.stories) == 1
    story = got.stories[0]
    assert (story.id, story.title, story.started_on) == (
        sid,
        "Tariff escalation",
        date(2026, 10, 15),
    )
    assert story.description == "A fresh description."
    assert list(_stories_rows()) == [sid]  # no second row


def test_a_continued_story_that_cites_nothing_valid_is_dropped_from_the_picture(pic) -> None:
    _seed_cluster(1)
    sid = _seed_story("Tariff escalation", started=date(2026, 10, 15), cluster_ids=[1])
    pic([_draft(story_id=sid, evidence=["C999", "N3"])])
    got = P.build_picture(NOW)
    assert got is not None and got.stories == []
    assert (
        _stories_rows()[sid].active is True
    )  # Python still holds it; the model just did not support it


def test_a_continued_story_needs_no_pile_one_cluster_of_its_own(pic) -> None:
    _seed_cluster(1, pile=2)
    sid = _seed_story("Tariff escalation", started=date(2026, 10, 15), cluster_ids=[1])
    pic([_draft(story_id=sid, evidence=["C1"])])
    got = P.build_picture(NOW)
    assert got is not None and [s.id for s in got.stories] == [sid]


def test_the_model_cannot_keep_a_dead_story_alive(pic) -> None:
    """The story is three weeks old and nothing Python can match supports it: it ends, and the
    model naming its id again does not bring it back."""
    _seed_cluster(1, tickers=("AAPL",), topic="other", pile=1)  # unrelated to the story
    sid = _seed_story("Old story", started=date(2026, 10, 1), cluster_ids=[77])
    pic([_draft(story_id=sid, title="Old story", evidence=["F1"])])
    got = P.build_picture(NOW)
    assert got is not None and got.stories == []
    row = _stories_rows()[sid]
    assert row.active is False and row.ended_on == DAY


def test_matching_clusters_attach_and_keep_a_story_alive(pic) -> None:
    _seed_cluster(10, tickers=("NVDA",), topic="tariff", age_h=24 * 9)  # the original, 9 days old
    _seed_cluster(11, tickers=("NVDA",), topic="tariff", age_h=30)
    _seed_cluster(12, tickers=("NVDA",), topic="tariff", age_h=5)
    sid = _seed_story("Chip tariffs", started=date(2026, 10, 1), cluster_ids=[10])
    pic([_draft(story_id=sid, title="Chip tariffs", evidence=["C11", "F1"])])
    got = P.build_picture(NOW)
    assert got is not None and [s.id for s in got.stories] == [sid]
    row = _stories_rows()[sid]
    assert row.active is True and sorted(row.cluster_ids) == [10, 11, 12]
    with news_session() as s:
        assert (
            s.scalar(select(StoryTriageRow.story_id).where(StoryTriageRow.cluster_id == 12)) == sid
        )


def test_noise_clusters_never_support_a_story(pic) -> None:
    _seed_cluster(10, tickers=("NVDA",), topic="tariff", age_h=24 * 9)
    _seed_cluster(11, tickers=("NVDA",), topic="tariff", age_h=30, pile=3)  # judged noise
    _seed_cluster(12, tickers=("NVDA",), topic="tariff", age_h=5, pile=None)  # not reviewed
    sid = _seed_story("Chip tariffs", started=date(2026, 10, 1), cluster_ids=[10])
    pic([])
    P.build_picture(NOW)
    assert _stories_rows()[sid].active is False


# --- the saved picture --------------------------------------------------------------------


def test_llm_failure_saves_a_stale_deterministic_picture(pic, monkeypatch) -> None:
    _seed_cluster(1)
    sid = _seed_story("Tariff escalation", started=date(2026, 10, 15), cluster_ids=[1])
    monkeypatch.setattr(
        P,
        "month_seasonality",
        lambda month: SeasonalityView(month=month, avg_return_pct=1.0, up_share=0.6, years=5),
    )
    pic(fail=True)
    got = P.build_picture(NOW)
    assert got is not None and got.stale is True
    assert [(s.id, s.title, s.description) for s in got.stories] == [
        (sid, "Tariff escalation", "")
    ]  # the previous titles, no prose
    assert got.regimes and got.facts and got.events == ["FOMC Wed 14:00 ET"]
    assert got.seasonality is not None and got.seasonality.years == 5
    assert _saved().stale is True


def test_regime_comes_from_the_trading_record_when_present(news_db, monkeypatch) -> None:
    def ir(index, eff, *, eased=False):
        return IndexRegime(
            index=index,
            base=MarketRegime.CAUTIOUS,
            base_date=DAY,
            since=DAY,
            base_since=DAY,
            effective=eff,
            eased_by_bottoming=eased,
            inputs=RegimeInputs(
                vol=23.4,
                term_ratio=0.93,
                index_close=560.12,
                sma50=580.0,
                sma200=540.0,
                drawdown_52w_pct=8.0,
                ret_1m_pct=-4.2,
                ret_3m_pct=1.5,
            ),
        )

    state = RegimeState(
        as_of=NOW - timedelta(minutes=10),
        spy=ir("SPY", MarketRegime.CAUTIOUS),
        qqq=ir("QQQ", MarketRegime.NORMAL, eased=True),
    )
    monkeypatch.setattr(P, "load_regime_state", lambda: state)
    monkeypatch.setattr(P, "regime_suspended", lambda day: True)
    monkeypatch.setattr(P, "get_market_conditions", lambda: None)
    monkeypatch.setattr(
        P, "fetch_daily_inputs", lambda *a, **k: pytest.fail("the trading record is the source")
    )
    sheet, regimes, source = P.picture_facts(NOW)
    assert source == "trading"
    assert [(r.index, r.effective, r.base, r.eased_by_bottoming, r.suspended) for r in regimes] == [
        ("SPY", MarketRegime.CAUTIOUS, MarketRegime.CAUTIOUS, False, True),
        ("QQQ", MarketRegime.NORMAL, MarketRegime.CAUTIOUS, True, True),
    ]
    assert regimes[0].as_of == state.as_of
    labels = [f.label for f in sheet.facts]
    assert "SPY" in labels and "QQQ" in labels
    spy = sheet.get("SPY")
    assert spy is not None and "560.12" in spy.display and "-3.4% vs 50-day" in spy.display
    assert "8.0% below its 52-week high" in spy.display
    vix, term = sheet.get("VIX"), sheet.get("VIX/VIX3M")
    # no live backdrop: the VIX complex comes from the record's own inputs
    assert vix is not None and "23.4" in vix.display
    assert term is not None and "0.93" in term.display


def test_regime_is_computed_by_the_news_service_when_no_record_exists(news_db, monkeypatch) -> None:
    inp = RegimeInputs(vol=31.0, term_ratio=1.05, index_close=500.0)
    monkeypatch.setattr(P, "load_regime_state", lambda: None)
    monkeypatch.setattr(P, "regime_suspended", lambda day: False)
    monkeypatch.setattr(P, "get_market_conditions", lambda: None)
    monkeypatch.setattr(P, "fetch_daily_inputs", lambda index, **k: inp)
    sheet, regimes, source = P.picture_facts(NOW)
    assert source == "news"
    assert [r.index for r in regimes] == ["SPY", "QQQ"]
    assert all(r.effective is r.base and not r.eased_by_bottoming for r in regimes)
    assert all(
        r.effective in (MarketRegime.STRESSED, MarketRegime.CRISIS) for r in regimes
    )  # VIX 31
    assert regimes[0].as_of == NOW


def test_facts_add_the_rates_and_never_raise(news_db, monkeypatch) -> None:
    from src.common.schemas import MarketConditions

    monkeypatch.setattr(P, "load_regime_state", lambda: None)
    monkeypatch.setattr(P, "regime_suspended", lambda day: False)
    monkeypatch.setattr(P, "fetch_daily_inputs", lambda index, **k: RegimeInputs())
    monkeypatch.setattr(
        P,
        "get_market_conditions",
        lambda: MarketConditions(vix=24.5, vix_term_ratio=0.95, ten_year_yield=4.31),
    )
    # ^TNX quotes the yield x10: 41.9 -> 43.1 over the month is +12bp
    closes = [41.9] + [42.5] * 20 + [43.1]
    monkeypatch.setattr(P, "_ten_year_history", lambda: pd.Series(closes))
    sheet, _regimes_, _src = P.picture_facts(NOW)
    ten, month = sheet.get("10y yield"), sheet.get("10y 1m change")
    assert ten is not None and "4.31%" in ten.display
    assert month is not None and "+12bp" in month.display
    vix, term = sheet.get("VIX"), sheet.get("VIX/VIX3M")
    assert vix is not None and "24.5" in vix.display
    assert term is not None and "0.95" in term.display

    def boom(*a, **k):
        raise RuntimeError("macro source down")

    monkeypatch.setattr(P, "get_market_conditions", boom)
    monkeypatch.setattr(P, "_ten_year_history", boom)
    sheet, regimes, _src = P.picture_facts(NOW)  # still answers: the facts it could build
    assert sheet.get("10y yield") is None and sheet.get("10y 1m change") is None and regimes


def test_noise_summary_counts_the_last_seven_days(pic) -> None:
    for cid, pile in ((1, 3), (2, 3), (3, None), (4, None), (5, None), (6, 2)):
        _seed_cluster(cid, pile=pile, age_h=24)
    _seed_cluster(7, pile=3, age_h=24 * 9)  # too old
    with news_session() as s:
        row = s.scalar(select(StoryTriageRow).where(StoryTriageRow.cluster_id == 6))
        row.promoted_at = naive_utc(NOW - timedelta(hours=2))  # a promotion
        row.promoted_move_pct = -1.4
        # a floored cluster nobody reviewed is not "not reviewed": the floor holds it at pile 2
        s.add(
            NewsClusterRow(
                id=8,
                headline="h8",
                category="ticker",
                first_seen=naive_utc(NOW),
                last_seen=naive_utc(NOW),
                tickers=["AAPL"],
                tags=[],
            )
        )
        s.add(StoryTriageRow(cluster_id=8, pile=None, floor="held", rank=2.0))
    pic([])
    got = P.build_picture(NOW)
    assert got is not None
    assert (got.noise.judged, got.noise.not_reviewed, got.noise.promotions) == (2, 3, 1)


def test_events_list_the_high_impact_releases_and_held_earnings(news_db, monkeypatch) -> None:
    monkeypatch.setattr(P, "held_underlyings", lambda: {"NVDA"})
    with news_session() as s:
        s.add(
            EconEventRow(
                event_key="a",
                title="FOMC rate decision",
                scheduled_at=naive_utc(datetime(2026, 10, 28, 18, 0, tzinfo=UTC)),
                impact="High",
            )
        )
        s.add(
            EconEventRow(
                event_key="b",
                title="Minor survey",
                scheduled_at=naive_utc(datetime(2026, 10, 27, 14, 0, tzinfo=UTC)),
                impact="Medium",
            )
        )
        s.add(
            EconEventRow(
                event_key="c",
                title="Too far ahead",
                scheduled_at=naive_utc(datetime(2026, 11, 20, 14, 0, tzinfo=UTC)),
                impact="High",
            )
        )
        s.add(EarningsEventRow(symbol="NVDA", report_date=date(2026, 10, 29), timing="amc"))
        s.add(EarningsEventRow(symbol="AMD", report_date=date(2026, 10, 27), timing="amc"))
    assert P.upcoming_events(NOW) == [
        "FOMC rate decision Wed Oct 28 14:00 ET",
        "NVDA earnings Thu Oct 29 AMC (held)",
    ]


# --- when to rebuild ----------------------------------------------------------------------


def _add_picture(built_at: datetime, *, version: str | None = None) -> None:
    with news_session() as s:
        s.add(
            MarketPictureRow(
                built_at=naive_utc(built_at),
                version=version or built_at.isoformat(),
                payload=MarketPicture(version="v", built_at=built_at).model_dump(mode="json"),
                stale=False,
            )
        )


def test_the_first_picture_is_due_at_once(news_db) -> None:
    assert P.picture_due(NOW)


def test_picture_due_after_a_digest_slot_has_passed(news_db) -> None:
    # 08:00 ET premarket = 12:00 UTC; 16:30 ET close = 20:30 UTC (EDT)
    _add_picture(datetime(2026, 10, 22, 11, 0, tzinfo=UTC))  # built before the premarket slot
    assert P.picture_due(datetime(2026, 10, 22, 12, 5, tzinfo=UTC))
    assert not P.picture_due(datetime(2026, 10, 22, 11, 30, tzinfo=UTC))  # the slot is ahead
    _add_picture(datetime(2026, 10, 22, 12, 10, tzinfo=UTC))
    assert not P.picture_due(datetime(2026, 10, 22, 19, 0, tzinfo=UTC))  # built after the slot
    assert P.picture_due(datetime(2026, 10, 22, 20, 40, tzinfo=UTC))  # the close slot passed


def test_a_weekend_is_not_a_digest_slot(news_db) -> None:
    _add_picture(datetime(2026, 10, 23, 22, 0, tzinfo=UTC))  # Friday evening
    assert not P.picture_due(datetime(2026, 10, 24, 18, 0, tzinfo=UTC))  # Saturday


def test_a_new_pile_one_judgement_makes_a_picture_due(news_db) -> None:
    _add_picture(datetime(2026, 10, 22, 12, 30, tzinfo=UTC))
    now = datetime(2026, 10, 22, 16, 0, tzinfo=UTC)
    assert not P.picture_due(now)
    _seed_cluster(1, pile=2, age_h=0.5)  # worth telling: does not shape the picture
    assert not P.picture_due(now)
    _seed_cluster(2, pile=1, age_h=0.5)  # judged after the build: shapes it
    assert P.picture_due(now)


def test_picture_due_respects_the_daily_cap(news_db, monkeypatch) -> None:
    monkeypatch.setattr(get_config().news.picture, "max_rebuilds_per_day", 2)
    _add_picture(datetime(2026, 10, 22, 12, 5, tzinfo=UTC))
    _add_picture(datetime(2026, 10, 22, 13, 5, tzinfo=UTC))
    _seed_cluster(1, pile=1, age_h=0.2)  # a fresh pile-1 story ...
    now = datetime(2026, 10, 22, 15, 0, tzinfo=UTC)
    assert not P.picture_due(now)  # ... but two builds today is the cap
    assert P.picture_due(datetime(2026, 10, 23, 12, 30, tzinfo=UTC))  # tomorrow's slot


def test_picture_due_is_off_when_the_picture_is_disabled(news_db, monkeypatch) -> None:
    monkeypatch.setattr(get_config().news.picture, "enabled", False)
    assert not P.picture_due(NOW)


# --- the service loop ---------------------------------------------------------------------


async def test_the_picture_loop_builds_only_when_due(news_db, monkeypatch) -> None:
    from src.news import service as S

    svc = S.NewsService(get_config())
    built: list[datetime] = []
    monkeypatch.setattr(S, "build_picture", lambda n: built.append(n) or None)
    monkeypatch.setattr(S, "picture_due", lambda n: False)
    await svc._picture(NOW)
    assert built == []
    monkeypatch.setattr(S, "picture_due", lambda n: True)
    await svc._picture(NOW)
    assert built == [NOW]


def test_the_picture_loop_is_registered() -> None:
    from src.news import service as S

    names = [n for n, _i, _f in S.NewsService(get_config()).loops()]
    assert "picture" in names


# --- the prompt ---------------------------------------------------------------------------


def test_the_picture_prompt_has_the_facts_titles_clusters_and_the_cautions() -> None:
    from src.news.prompts import picture_prompt
    from src.news.schemas import ClusterView

    cl = ClusterView(
        id=41,
        headline="Tariffs widen to chips",
        category="macro",
        first_seen=NOW,
        last_seen=NOW,
        source_count=4,
        tickers=["NVDA"],
        topic_class="tariff",
    )
    text = picture_prompt(
        _facts(),
        [(7, "Rates repricing", date(2026, 10, 12))],
        [cl],
        ["FOMC Wed 14:00 ET"],
        piles={41: 1},
        max_stories=4,
    )
    assert "F1 SPY: close 560.12" in text
    assert "S7 Rates repricing (since Oct 12)" in text
    assert "C41 [pile 1; macro/tariff, 4 sources, NVDA] Tariffs widen to chips" in text
    assert "FOMC Wed 14:00 ET" in text
    assert "at most 4" in text and "weak signal" in text
    assert "start a new story only from a pile 1 cluster" in text.lower()
    assert "every number must appear in the facts" in text.lower()
    assert '"stories"' in text  # the JSON schema


# --- seasonality ----------------------------------------------------------------------------


def _bars(start: str, end: str, *, up_months: set[int] | None = None) -> pd.DataFrame:
    """Daily bars where each calendar month in *up_months* (every month when None) ends about 2%
    above where it began and every other month about 1% below."""
    idx = pd.bdate_range(start, end)
    close = 100.0
    closes = []
    for ts in idx:
        up = up_months is None or ts.month in up_months
        close *= 1.02 ** (1 / 21) if up else 0.99 ** (1 / 21)
        closes.append(close)
    return pd.DataFrame({"Close": closes}, index=idx)


def test_seasonality_is_none_without_history(monkeypatch) -> None:
    from src.analytics import seasonality as Z

    class Empty:
        def get_ohlcv(self, symbol, lookback_days):
            return pd.DataFrame()

    monkeypatch.setattr(Z, "get_price_provider", lambda: Empty())
    assert Z.month_seasonality(10) is None

    class Down:
        def get_ohlcv(self, symbol, lookback_days):
            raise RuntimeError("provider down")

    monkeypatch.setattr(Z, "get_price_provider", lambda: Down())
    assert Z.month_seasonality(11) is None


def test_seasonality_reports_the_years_it_actually_covers(monkeypatch) -> None:
    from src.analytics import seasonality as Z

    bars = _bars("2020-08-03", "2026-10-22")  # six full Octobers (2020-2025) and a partial 2026

    class Prov:
        def get_ohlcv(self, symbol, lookback_days):
            assert symbol == "SPY"
            return bars

    monkeypatch.setattr(Z, "get_price_provider", lambda: Prov())
    sv = Z.month_seasonality(10)
    assert sv is not None and sv.month == 10
    assert sv.years == 5  # the five most recent completed Octobers, not six, not the partial one
    assert sv.up_share == 1.0 and sv.avg_return_pct == pytest.approx(2.0, abs=0.3)
    # a window that holds only part of the history says so
    from src.common import cache

    cache.clear_all()  # month_seasonality is cached for the day
    short = _bars("2023-09-01", "2026-10-22")  # Octobers 2023, 2024, 2025
    monkeypatch.setattr(Prov, "get_ohlcv", lambda self, symbol, lookback_days: short)
    sv3 = Z.month_seasonality(10, years=5)
    assert sv3 is not None and sv3.years == 3


def test_seasonality_ignores_the_month_still_forming_and_counts_down_years(monkeypatch) -> None:
    from src.analytics import seasonality as Z

    # Octobers rise, Septembers fall; the data ends in October 2026, which must not count
    bars = _bars("2022-08-01", "2026-10-22", up_months={10})

    class Prov:
        def get_ohlcv(self, symbol, lookback_days):
            return bars

    monkeypatch.setattr(Z, "get_price_provider", lambda: Prov())
    oct_ = Z.month_seasonality(10)
    assert oct_ is not None and oct_.years == 4 and oct_.up_share == 1.0  # 2022-2025
    Z_sep = Z.month_seasonality(9)
    assert Z_sep is not None and Z_sep.up_share == 0.0 and Z_sep.avg_return_pct < 0
    with pytest.raises(ValueError):
        Z.month_seasonality(13)
