"""Task 10: multi-week stories whose survival Python decides (pure functions)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.news import stories as S
from src.news.schemas import ClusterView
from src.news.store.models import PictureStoryRow

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)  # 11:00 ET on the 22nd


def _cv(
    cid: int, *, tickers: tuple[str, ...] = (), tags: tuple[str, ...] = (), topic: str = "other"
) -> ClusterView:
    return ClusterView(
        id=cid,
        headline=f"headline {cid}",
        category="macro",
        first_seen=NOW,
        last_seen=NOW,
        source_count=2,
        tickers=list(tickers),
        tags=list(tags),
        topic_class=topic,
    )


def _story(sid: int, started: date, cluster_ids: list[int]) -> PictureStoryRow:
    return PictureStoryRow(
        id=sid,
        title=f"story {sid}",
        started_on=started,
        last_supported_at=NOW,
        cluster_ids=cluster_ids,
        active=True,
    )


def test_signature_is_tickers_tags_and_topic_never_title_words() -> None:
    c = _cv(1, tickers=("nvda", "AMD"), tags=("export_controls",), topic="tariff")
    assert S.cluster_signature(c) == {"NVDA", "AMD", "export_controls", "topic:tariff"}
    # an unclassified topic names nothing: two unrelated clusters must not share it
    assert S.cluster_signature(_cv(2, topic="other")) == set()


def test_style_tags_say_how_a_headline_is_written_not_what_it_is_about() -> None:
    c = _cv(1, tickers=("AAPL",), tags=("quantified", "rumor", "forward_looking", "scheduled"))
    assert S.cluster_signature(c) == {"AAPL"}


def test_clusters_attach_by_signature_overlap() -> None:
    tariff = _story(1, date(2026, 10, 12), [10])
    fed = _story(2, date(2026, 10, 14), [20])
    clusters = [
        _cv(10, tickers=("NVDA",), topic="tariff"),  # held by story 1
        _cv(20, tickers=("SPY",), topic="fed"),  # held by story 2
        _cv(11, tickers=("NVDA",), topic="tariff"),  # Jaccard 1.0 with story 1
        _cv(21, topic="fed"),  # 1 of {SPY, topic:fed}: 0.5, attaches to story 2
        _cv(30, tickers=("AAPL",)),  # shares nothing
        _cv(31, tickers=("NVDA",), topic="fed"),  # 1/3 with story 1, 1/3 with story 2: tie -> older
    ]
    got = S.match_clusters([tariff, fed], clusters, jaccard=0.3)
    assert got == {1: [11, 31], 2: [21]}


def test_a_cluster_below_the_threshold_attaches_to_nothing() -> None:
    story = _story(1, date(2026, 10, 12), [10, 11, 12])
    clusters = [
        _cv(10, tickers=("NVDA", "AMD"), topic="tariff"),
        _cv(11, tickers=("TSM", "INTC"), topic="tariff"),
        _cv(12, tickers=("QCOM", "AVGO")),
        _cv(40, tickers=("NVDA",)),  # 1 of the story's 7 tokens
    ]
    assert S.match_clusters([story], clusters, jaccard=0.3) == {}


def test_a_cluster_a_story_already_holds_is_not_attached_again() -> None:
    story = _story(1, date(2026, 10, 12), [10])
    clusters = [_cv(10, tickers=("NVDA",), topic="tariff")]
    assert S.match_clusters([story], clusters, jaccard=0.3) == {}


def test_a_story_whose_clusters_are_unknown_attracts_nothing() -> None:
    story = _story(1, date(2026, 10, 12), [999])  # its clusters have been pruned
    assert S.match_clusters([story], [_cv(40, tickers=("NVDA",))], jaccard=0.1) == {}


def test_a_story_without_new_supporting_clusters_ends() -> None:
    old = _story(1, date(2026, 10, 1), [10, 11])  # 21 days old, outside the 7-day window
    assert not S.story_alive(old, [], now=NOW, window_days=7, min_new=2)
    assert not S.story_alive(old, [10], now=NOW, window_days=7, min_new=2)
    assert S.story_alive(old, [10, 11], now=NOW, window_days=7, min_new=2)
    # the same cluster listed twice is one supporter
    assert not S.story_alive(old, [10, 10], now=NOW, window_days=7, min_new=2)


def test_a_young_story_survives_its_first_window() -> None:
    young = _story(1, date(2026, 10, 18), [10])
    assert S.story_alive(young, [], now=NOW, window_days=7, min_new=2)
    # exactly one window old still counts as young; one day more does not
    edge = _story(2, date(2026, 10, 15), [10])
    assert S.story_alive(edge, [], now=NOW, window_days=7, min_new=2)
    past = _story(3, date(2026, 10, 14), [10])
    assert not S.story_alive(past, [], now=NOW, window_days=7, min_new=2)


def test_story_age_is_counted_in_et_days() -> None:
    """02:00 UTC on the 23rd is still the 22nd in New York: the window must not tick over early."""
    story = _story(1, date(2026, 10, 15), [10])
    late = datetime(2026, 10, 23, 2, 0, tzinfo=UTC)
    assert S.story_alive(story, [], now=late, window_days=7, min_new=2)
