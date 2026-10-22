"""Dossier prose builds (Task 18): when a name is due, the batched model call, grounding, the
verified events and the daily call budget.

Python decides everything the model's words may become. A profile with a number, a story with no
cited cluster or an ungrounded figure, an event whose date is not written in the cited news: each
is dropped by Python, never repaired, and the previous story is never fed back or kept. No test
makes a real model call: ``call_llm`` is faked.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.config import get_config
from src.common.schemas import DossierEvent, DossierFact, TickerDossier
from src.news import dossier as D
from src.news import llm
from src.news.llm import LlmResult
from src.news.store import queries
from src.news.store.models import (
    EarningsEventRow,
    NewsClusterRow,
    NewsItemRow,
    NewsPostRow,
    StoryTriageRow,
    TickerDossierRow,
)
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from src.news.store.state import llm_calls

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)  # Thu 11:00 ET
TODAY = date(2026, 10, 22)
HOUR = timedelta(hours=1)


# --------------------------------------------------------------------------- #
# seeding
# --------------------------------------------------------------------------- #


def facts_for(symbol: str) -> list[DossierFact]:
    return [
        DossierFact(id=f"{symbol}:F1", label="RSI14", display="RSI 52"),
        DossierFact(id=f"{symbol}:F2", label="Price vs SMA200", display="+4.1% vs SMA200"),
        DossierFact(id=f"{symbol}:F3", label="IV rank", display="IV rank 55"),
    ]


def event(symbol: str, n: int, *, on: date, evidence: str = "C900", title: str = "Old event"):
    return DossierEvent(
        id=f"{symbol}:E{n}", title=title, on=on, evidence=evidence, quote="written down earlier"
    )


def seed(
    symbol: str = "META",
    *,
    kind: str = "stock",
    prose_ago: timedelta | None = timedelta(hours=10),
    profile_ago: timedelta | None = timedelta(days=1),
    facts_ago: timedelta = HOUR,
    **kw,
) -> TickerDossier:
    at = NOW - facts_ago
    base = dict(
        symbol=symbol,
        version=f"{symbol}@{at.isoformat(timespec='microseconds')}",
        facts_at=at,
        prose_at=None if prose_ago is None else NOW - prose_ago,
        profile_at=None if profile_ago is None else NOW - profile_ago,
        kind=kind,
        health="strong" if kind == "stock" else "n/a",
        health_why=[],
        facts=facts_for(symbol),
        profile="OLDPROFILE the business as it was described before.",
        story="OLDSTORY what was happening before.",
        story_evidence=["C900"],
        events=[],
    )
    if prose_ago is None:
        base.update(profile="", story="", story_evidence=[])
    base.update(kw)
    d = TickerDossier(**base)
    with news_session() as s:
        s.add(
            TickerDossierRow(
                symbol=symbol,
                version=d.version,
                built_at=naive_utc(at),
                payload=d.model_dump(mode="json"),
            )
        )
    return d


def latest(symbol: str) -> TickerDossier:
    with news_session() as s:
        got = queries.latest_dossier(s, symbol)
    assert got is not None
    return got


def add_cluster(
    cid: int,
    *,
    tickers: list[str],
    headline: str = "Meta plans a glasses launch",
    pile: int | None = 2,
    age: timedelta = timedelta(hours=3),
    judged_ago: timedelta | None = HOUR,
    items: list[tuple] | None = None,
    promoted_ago: timedelta | None = None,
) -> None:
    seen = NOW - age
    with news_session() as s:
        s.add(
            NewsClusterRow(
                id=cid,
                headline=headline,
                category="ticker",
                first_seen=naive_utc(seen),
                last_seen=naive_utc(seen),
                source_domains=["reuters.com"],
                source_count=2,
                tickers=tickers,
                tags=[],
                topic_class="other",
                title_tokens=[],
            )
        )
        for i, (title, summary, *own) in enumerate(items or []):
            s.add(
                NewsItemRow(
                    url_hash=f"u{cid}-{i}",
                    title_hash=f"t{cid}-{i}",
                    title=title,
                    summary=summary,
                    category="ticker",
                    origin="rss",
                    fetched_at=naive_utc(seen),
                    published_at=naive_utc(seen),
                    tickers=own[0] if own else tickers,
                    tags=[],
                    cluster_id=cid,
                )
            )
        s.add(
            StoryTriageRow(
                cluster_id=cid,
                pile=pile,
                rank=1.0,
                reason="x",
                judged_at=None if judged_ago is None else naive_utc(NOW - judged_ago),
                promoted_at=None if promoted_ago is None else naive_utc(NOW - promoted_ago),
            )
        )


def add_post(*, subject: str, kind: str = "ticker_move", ago: timedelta = HOUR) -> None:
    with news_session() as s:
        s.add(
            NewsPostRow(
                kind=kind,
                subject=subject,
                posted_at=naive_utc(NOW - ago),
                cluster_ids=[],
                payload={},
            )
        )


def add_earnings(symbol: str, *, seen_ago: timedelta | None, status: str = "released") -> None:
    with news_session() as s:
        s.add(
            EarningsEventRow(
                symbol=symbol,
                report_date=TODAY,
                timing="amc",
                status=status,
                released_seen_at=None if seen_ago is None else naive_utc(NOW - seen_ago),
            )
        )


_LATEST = object()


def due(symbol: str = "META", *, last=_LATEST) -> list[str]:
    with news_session() as s:
        return D.dossier_due(symbol, latest(symbol) if last is _LATEST else last, now=NOW, s=s)


# --------------------------------------------------------------------------- #
# a fake model
# --------------------------------------------------------------------------- #


@dataclass
class FakeLlm:
    """Stands in for ``call_llm`` as ``explain.validated_call`` sees it."""

    answer: Callable[[str], dict] | dict | None = None
    fail: bool = False
    calls: list[dict] = field(default_factory=list)

    def __call__(self, prompt, *, schema, prefix, now, purpose="general"):
        self.calls.append({"prompt": prompt, "prefix": prefix, "purpose": purpose, "now": now})
        if self.fail:
            return None
        body = self.answer(prompt) if callable(self.answer) else (self.answer or {"names": []})
        return LlmResult(json.dumps(body), "cli")


@pytest.fixture()
def fake(monkeypatch) -> FakeLlm:
    f = FakeLlm()
    monkeypatch.setattr("src.news.explain.call_llm", f)
    monkeypatch.setattr(D, "latest_picture_text", lambda now: None)
    monkeypatch.setattr(D, "held_underlyings", lambda: set())
    return f


def names_answer(*names: dict) -> dict:
    return {"names": list(names)}


def one_name(symbol: str = "META", **kw) -> dict:
    return {"symbol": symbol, **kw}


def symbols(*names: str) -> Callable[[], list[str]]:
    return lambda: list(names)


# --------------------------------------------------------------------------- #
# when a name is due
# --------------------------------------------------------------------------- #


def test_due_reasons_new_news_alert_earnings_profile(news_db) -> None:
    seed("META")
    assert due("META") == []  # old prose, fresh profile, nothing new: not due

    # new: no dossier at all, or one that has never had prose
    assert due("AMD", last=None) == ["new", "profile"]
    seed("NVDA", prose_ago=None, profile_ago=None)
    assert due("NVDA") == ["new", "profile"]
    seed("AAPL", prose_ago=None, profile_ago=timedelta(days=1))
    assert due("AAPL") == ["new"]

    # news: a pile 1 or 2 cluster naming the name, judged after the last prose
    add_cluster(101, tickers=["META"], pile=2, judged_ago=HOUR)
    assert due("META") == ["news"]


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("pile1", ["news"]),
        ("pile3", []),
        ("unjudged", []),
        ("other_name", []),
        ("judged_before_prose", []),
        ("promoted_after_prose", ["news"]),
        ("alert", ["alert"]),
        ("alert_other_name", []),
        ("digest_post", []),
        ("earnings_released", ["earnings"]),
        ("earnings_released_before_prose", []),
        ("earnings_scheduled_only", []),
        ("profile_old", ["profile"]),
        ("profile_never", ["profile"]),
        ("profile_exactly_at_limit", []),
    ],
)
def test_each_due_reason_in_isolation(news_db, setup, expected) -> None:
    profile_ago = timedelta(days=1)
    if setup == "profile_old":
        profile_ago = timedelta(days=8)
    elif setup == "profile_never":
        profile_ago = None
    elif setup == "profile_exactly_at_limit":
        profile_ago = timedelta(days=7)
    seed("META", prose_ago=timedelta(hours=10), profile_ago=profile_ago)
    if setup == "pile1":
        add_cluster(101, tickers=["META"], pile=1)
    elif setup == "pile3":
        add_cluster(101, tickers=["META"], pile=3)
    elif setup == "unjudged":
        add_cluster(101, tickers=["META"], pile=None, judged_ago=None)
    elif setup == "other_name":
        add_cluster(101, tickers=["AMD"], pile=2)
    elif setup == "judged_before_prose":
        add_cluster(101, tickers=["META"], pile=2, judged_ago=timedelta(hours=12))
    elif setup == "promoted_after_prose":
        add_cluster(
            101, tickers=["META"], pile=2, judged_ago=timedelta(hours=12), promoted_ago=HOUR
        )
    elif setup == "alert":
        add_post(subject="META", kind="ticker_move", ago=HOUR)
    elif setup == "alert_other_name":
        add_post(subject="AMD", kind="ticker_move", ago=HOUR)
    elif setup == "digest_post":
        add_post(subject="META", kind="digest_close", ago=HOUR)
    elif setup == "earnings_released":
        add_earnings("META", seen_ago=HOUR)
    elif setup == "earnings_released_before_prose":
        add_earnings("META", seen_ago=timedelta(hours=12))
    elif setup == "earnings_scheduled_only":
        add_earnings("META", seen_ago=None, status="scheduled")
    assert due("META") == expected


def test_old_prose_alone_is_not_due(news_db) -> None:
    seed("META", prose_ago=timedelta(hours=30), profile_ago=timedelta(days=1))
    assert due("META") == []  # ruling 43: no `age` reason; old prose is shown labelled, not rebuilt


def test_news_reason_waits_for_the_min_interval(news_db) -> None:
    seed("META", prose_ago=timedelta(hours=2), profile_ago=timedelta(days=9))
    add_cluster(101, tickers=["META"], pile=2, judged_ago=timedelta(minutes=30))
    assert due("META") == []  # `news` and `profile` both wait for six hours since the prose
    add_post(subject="META", ago=timedelta(minutes=20))
    assert due("META") == ["alert"]  # an alert is never held back
    add_earnings("META", seen_ago=timedelta(minutes=10))
    assert due("META") == ["alert", "earnings"]
    # once the interval has passed the held-back reasons come back, in a fixed order
    with news_session() as s:
        got = D.dossier_due("META", latest("META"), now=NOW + timedelta(hours=5), s=s)
    assert got == ["news", "alert", "earnings", "profile"]


# --------------------------------------------------------------------------- #
# the profile
# --------------------------------------------------------------------------- #


def test_a_leveraged_etf_profile_may_say_3x_and_nasdaq_100(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("TQQQ"))
    seed("TQQQ", kind="leveraged_etf", prose_ago=None, profile_ago=None)
    fake.answer = names_answer(
        one_name(
            "TQQQ",
            profile="A 3x daily leveraged fund on the Nasdaq-100; it moves with large tech shares.",
        )
    )
    assert D.build_dossier_prose(NOW) == 1
    got = latest("TQQQ")
    assert got.profile.startswith("A 3x daily leveraged fund on the Nasdaq-100")
    assert got.profile_at == NOW


@pytest.mark.parametrize(
    "text",
    [
        "A fund with 100 holdings that tracks large shares.",  # a number
        "Founded in 1998, it sells advertising.",  # a year
        "It earns 20% margins.",  # a percent
        "Buy this stock for steady income.",  # advice
        "The facts supplied show a software maker.",  # talk about the inputs
        "A cloud company (F3).",  # an id in prose
    ],
)
def test_profile_with_a_number_or_advice_keeps_the_previous_profile(
    news_db, fake, monkeypatch, text
) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    before = seed(
        "META", prose_ago=None, profile_ago=timedelta(days=9), profile="OLD profile text."
    )
    fake.answer = names_answer(one_name("META", profile=text))
    assert D.build_dossier_prose(NOW) == 1
    got = latest("META")
    assert got.profile == "OLD profile text."
    assert got.profile_at == before.profile_at  # unchanged: the profile is asked again next time


def test_a_clean_profile_replaces_the_old_one_and_stamps_profile_at(
    news_db, fake, monkeypatch
) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META", prose_ago=None, profile_ago=timedelta(days=9), profile="OLD profile text.")
    fake.answer = names_answer(
        one_name("META", profile="A social media and AI company; ad revenue drives the shares.")
    )
    D.build_dossier_prose(NOW)
    got = latest("META")
    assert got.profile == "A social media and AI company; ad revenue drives the shares."
    assert got.profile_at == NOW


def test_an_unrequested_profile_is_ignored(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    before = seed("META", prose_ago=None, profile_ago=timedelta(days=1), profile="KEEP this one.")
    fake.answer = names_answer(one_name("META", profile="A different company description."))
    D.build_dossier_prose(NOW)
    got = latest("META")
    assert got.profile == "KEEP this one." and got.profile_at == before.profile_at
    assert "PROFILE requested: no" in fake.calls[0]["prompt"]


# --------------------------------------------------------------------------- #
# the story
# --------------------------------------------------------------------------- #


def story_setup(monkeypatch, *, items=None) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META", prose_ago=timedelta(hours=10))
    add_cluster(
        101,
        tickers=["META"],
        headline="Meta plans a glasses launch",
        items=items
        or [("Meta to unveil MUSE glasses at Connect on Oct 29", "Event at its campus on Oct 29.")],
    )


def build_story(fake, story: str, evidence: list[str] | None = None) -> TickerDossier:
    fake.answer = names_answer(one_name("META", story=story, story_evidence=evidence or []))
    D.build_dossier_prose(NOW)
    return latest("META")


def test_a_cited_grounded_story_is_kept_with_its_evidence(news_db, fake, monkeypatch) -> None:
    story_setup(monkeypatch)
    got = build_story(fake, "Meta is preparing a glasses launch.", ["C101"])
    assert got.story == "Meta is preparing a glasses launch."
    assert got.story_evidence == ["C101"]
    assert got.prose_at == NOW and got.stale is False


def test_inline_cluster_ids_move_to_the_evidence(news_db, fake, monkeypatch) -> None:
    story_setup(monkeypatch)
    got = build_story(fake, "Meta is preparing a glasses launch (C101).")
    assert got.story == "Meta is preparing a glasses launch."
    assert got.story_evidence == ["C101"]


@pytest.mark.parametrize(
    ("story", "evidence"),
    [
        ("Meta is preparing a glasses launch.", []),  # cites nothing
        ("Meta is preparing a glasses launch.", ["C555"]),  # a cluster that was not listed
        ("Meta is preparing a glasses launch.", ["F1"]),  # a fact, not a cluster
        ("Meta added $5.2 billion of buybacks.", ["C101"]),  # a figure not in the facts
        ("Meta grew 12% in the quarter.", ["C101"]),  # a percent not in the facts
        ("Meta is launching glasses. Buy the dip here.", ["C101"]),  # advice in a sentence
        ("The headlines supplied say Meta is launching glasses.", ["C101"]),  # about the inputs
    ],
)
def test_uncited_or_ungrounded_story_is_dropped(
    news_db, fake, monkeypatch, story, evidence
) -> None:
    story_setup(monkeypatch)
    got = build_story(fake, story, evidence)
    assert got.story == "" and got.story_evidence == []  # never the previous story either
    assert "OLDSTORY" not in got.story
    assert got.prose_at == NOW  # the build happened; only this name's story failed


def test_a_story_may_use_a_number_that_is_in_the_facts(news_db, fake, monkeypatch) -> None:
    story_setup(monkeypatch)
    got = build_story(fake, "The shares sit with RSI 52 while the launch nears.", ["C101"])
    assert got.story.startswith("The shares sit with RSI 52")


# --------------------------------------------------------------------------- #
# events
# --------------------------------------------------------------------------- #


def draft_event(title: str, on: str, evidence: str = "C101") -> dict:
    return {"title": title, "on": on, "evidence": evidence}


@pytest.mark.parametrize(
    "bad",
    [
        draft_event("Invented date", "2026-10-30"),  # "Oct 30" is nowhere in the cluster
        draft_event("Unlisted cluster", "2026-10-29", "C555"),
        draft_event("Malformed evidence", "2026-10-29", "101"),
        draft_event("Past event", "2026-10-22"),  # the date is written there, but not after today
        draft_event("Far event", "2026-12-15"),  # written there, but beyond max_event_days (45)
    ],
)
def test_event_without_the_date_in_its_cluster_is_dropped(news_db, fake, monkeypatch, bad) -> None:
    story_setup(
        monkeypatch,
        items=[
            (
                "Meta to unveil MUSE glasses at Connect on Oct 29",
                "Event at its campus on Oct 29. A note from Oct 22. Another due Dec 15.",
            )
        ],
    )
    fake.answer = names_answer(
        one_name("META", events=[draft_event("MUSE launch event", "2026-10-29"), bad])
    )
    D.build_dossier_prose(NOW)
    (e,) = latest("META").events
    assert (e.id, e.title, e.on, e.evidence) == (
        "META:E1",
        "MUSE launch event",
        date(2026, 10, 29),
        "C101",
    )
    assert "Oct 29" in e.quote and len(e.quote) <= 200


def test_an_event_date_must_be_in_what_the_model_was_shown(news_db, fake, monkeypatch) -> None:
    """The cited cluster's text is what the prompt showed: its headline and the first two items.
    A date that only the third item states was never in front of the model."""
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META")
    add_cluster(
        101,
        tickers=["META"],
        headline="Meta plans a glasses launch",
        items=[("First item", None), ("Second item", None), ("Third item: keynote on Nov 5", None)],
    )
    fake.answer = names_answer(one_name("META", events=[draft_event("Keynote", "2026-11-05")]))
    D.build_dossier_prose(NOW)
    assert latest("META").events == []
    assert "Nov 5" not in fake.calls[0]["prompt"]


@pytest.mark.parametrize(
    "title", ["Q3 earnings call", "Quarterly results", "Third quarter update", "EARNINGS day"]
)
def test_earnings_events_are_dropped(news_db, fake, monkeypatch, title) -> None:
    story_setup(monkeypatch)
    fake.answer = names_answer(
        one_name(
            "META",
            events=[
                draft_event(title, "2026-10-29"),
                draft_event("MUSE launch event", "2026-10-29"),
            ],
        )
    )
    D.build_dossier_prose(NOW)
    assert [e.title for e in latest("META").events] == ["MUSE launch event"]


@pytest.mark.parametrize("kind", ["etf", "leveraged_etf"])
def test_etf_events_are_dropped(news_db, fake, monkeypatch, kind) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("QQQ"))
    seed("QQQ", kind=kind, prose_ago=timedelta(hours=10))
    add_cluster(102, tickers=["QQQ"], headline="Nasdaq event on Oct 29", pile=2)
    fake.answer = names_answer(
        one_name("QQQ", events=[draft_event("Index event", "2026-10-29", "C102")])
    )
    D.build_dossier_prose(NOW)
    assert latest("QQQ").events == []


def test_an_event_title_with_advice_or_ids_is_dropped(news_db, fake, monkeypatch) -> None:
    story_setup(monkeypatch)
    fake.answer = names_answer(
        one_name(
            "META",
            events=[
                draft_event("Buy before the launch", "2026-10-29"),
                draft_event("Launch (C101)", "2026-10-29"),
                draft_event("Glasses launch", "2026-10-29"),
            ],
        )
    )
    D.build_dossier_prose(NOW)
    assert [e.title for e in latest("META").events] == ["Glasses launch"]


def test_verified_events_persist_until_their_date(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed(
        "META",
        prose_ago=timedelta(hours=10),
        events=[
            event("META", 1, on=TODAY - timedelta(days=1), title="Yesterday"),
            event("META", 2, on=TODAY, title="Today", evidence="C800"),
            event("META", 3, on=date(2026, 11, 12), title="Later", evidence="C801"),
        ],
    )
    add_cluster(101, tickers=["META"], headline="Glasses event on Oct 29 and a keynote on Nov 12")
    fake.answer = names_answer(
        one_name(
            "META",
            events=[
                draft_event("New event", "2026-10-29"),
                draft_event("Later again", "2026-11-12", "C101"),  # same date, other evidence
            ],
        )
    )
    D.build_dossier_prose(NOW)
    got = latest("META").events
    # the old events are never fed to the model, yet those still ahead are kept (ruling 27); a
    # past one is gone; ids follow the date order (ties by evidence)
    assert [(e.id, e.title, e.on, e.evidence) for e in got] == [
        ("META:E1", "Today", TODAY, "C800"),
        ("META:E2", "New event", date(2026, 10, 29), "C101"),
        ("META:E3", "Later again", date(2026, 11, 12), "C101"),
        ("META:E4", "Later", date(2026, 11, 12), "C801"),
    ]
    assert "Yesterday" not in [e.title for e in got]
    assert "Later" not in fake.calls[0]["prompt"] and "Today" not in fake.calls[0]["prompt"]


def test_duplicate_events_collapse_by_date_and_evidence(news_db, fake, monkeypatch) -> None:
    story_setup(monkeypatch)
    fake.answer = names_answer(
        one_name(
            "META",
            events=[
                draft_event("MUSE launch event", "2026-10-29"),
                draft_event("MUSE launch (again)", "2026-10-29"),
            ],
        )
    )
    D.build_dossier_prose(NOW)
    assert [e.title for e in latest("META").events] == ["MUSE launch event"]
    # and a rebuild that finds the same event does not stack it on the one already held
    seed_after = latest("META")
    assert len(seed_after.events) == 1
    fake.answer = names_answer(
        one_name("META", events=[draft_event("MUSE launch event", "2026-10-29")])
    )
    D.build_dossier_prose(NOW + timedelta(hours=7))
    assert len(latest("META").events) == 1


# --------------------------------------------------------------------------- #
# the call: prompt, purpose, failure
# --------------------------------------------------------------------------- #


def test_previous_prose_is_never_in_the_prompt(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed(
        "META",
        prose_ago=timedelta(hours=10),
        profile_ago=timedelta(days=9),
        profile="SECRETPROFILE words",
        story="SECRETSTORY words",
        events=[event("META", 1, on=date(2026, 11, 3), title="SECRETEVENT")],
    )
    add_cluster(101, tickers=["META"])
    D.build_dossier_prose(NOW)
    prompt = fake.calls[0]["prompt"]
    for secret in ("SECRETPROFILE", "SECRETSTORY", "SECRETEVENT", "OLDSTORY", "OLDPROFILE"):
        assert secret not in prompt
    # but the numbers and the news are
    assert "META:F2 Price vs SMA200: +4.1% vs SMA200" in prompt
    assert "C101 Meta plans a glasses launch" in prompt
    assert "PROFILE requested: yes" in prompt


def test_the_prompt_lists_only_this_names_recent_pile_1_and_2_clusters(
    news_db, fake, monkeypatch
) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META")
    add_cluster(101, tickers=["META"], headline="Pile two story", pile=2)
    add_cluster(102, tickers=["META"], headline="Pile one story", pile=1)
    add_cluster(103, tickers=["META"], headline="Noise story", pile=3)
    add_cluster(104, tickers=["AMD"], headline="Another name story", pile=2)
    add_cluster(105, tickers=["META"], headline="Old story", pile=2, age=timedelta(days=9))
    add_cluster(106, tickers=["META"], headline="Not reviewed story", pile=None, judged_ago=None)
    D.build_dossier_prose(NOW)
    prompt = fake.calls[0]["prompt"]
    assert "Pile two story" in prompt and "Pile one story" in prompt
    for absent in ("Noise story", "Another name story", "Old story", "Not reviewed story"):
        assert absent not in prompt


def test_at_most_eight_clusters_are_shown_pile_1_first(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META")
    add_cluster(101, tickers=["META"], headline="Pile one story", pile=1, age=timedelta(hours=9))
    for n in range(102, 114):  # twelve pile 2 clusters, the oldest last
        add_cluster(
            n, tickers=["META"], headline=f"Extra story {n}", pile=2, age=timedelta(hours=n - 100)
        )
    D.build_dossier_prose(NOW)
    prompt = fake.calls[0]["prompt"]
    shown = [line for line in prompt.splitlines() if line.startswith("C1")]
    assert len(shown) == 8
    assert shown[0].startswith("C101 ")  # pile 1 first, whatever its age
    assert "Extra story 102" in prompt and "Extra story 108" in prompt  # the newest pile 2
    assert "Extra story 109" not in prompt and "Extra story 113" not in prompt


def test_cluster_items_in_the_prompt_are_short_and_name_the_symbol_first(
    news_db, fake, monkeypatch
) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META")
    add_cluster(
        101,
        tickers=["META"],
        items=[
            ("Unrelated item A", None, ["AMD"]),  # does not name META: shown only if none do
            ("Meta item B", "x" * 400),
            ("Meta item C", None),
            ("Meta item D", None),
        ],
    )
    D.build_dossier_prose(NOW)
    prompt = fake.calls[0]["prompt"]
    assert "Meta item B" in prompt and "Meta item C" in prompt  # the two that name META
    assert "Unrelated item A" not in prompt and "Meta item D" not in prompt
    assert "x" * 200 in prompt and "x" * 201 not in prompt  # a summary is cut at 200 characters


def test_the_picture_is_framing_in_the_prompt(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    monkeypatch.setattr(D, "latest_picture_text", lambda now: "=== MARKET PICTURE ===\nSPY: normal")
    seed("META", prose_ago=None)
    D.build_dossier_prose(NOW)
    prompt = fake.calls[0]["prompt"]
    assert "=== MARKET PICTURE ===" in prompt and "Context for framing only" in prompt


def test_dossier_calls_use_the_dossier_purpose(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META", prose_ago=None)
    D.build_dossier_prose(NOW)
    assert [(c["purpose"], c["prefix"]) for c in fake.calls] == [("dossier", "news:dossier")]


def test_llm_failure_keeps_previous_prose_marked_stale(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META", "AMD"))
    prev = seed("META", prose_ago=timedelta(hours=10))
    add_cluster(101, tickers=["META"])  # news since the last prose: META is due
    seed("AMD", prose_ago=None)  # no prose to keep: nothing to mark
    fake.fail = True
    assert D.build_dossier_prose(NOW) == 0
    got = latest("META")
    assert got.stale is True
    assert (got.story, got.profile, got.prose_at, got.profile_at) == (
        prev.story,
        prev.profile,
        prev.prose_at,
        prev.profile_at,
    )
    assert got.facts == prev.facts
    amd = latest("AMD")
    assert amd.stale is False and amd.prose_at is None
    # a later successful build clears the mark
    fake.fail = False
    fake.answer = names_answer(one_name("META", story=""))
    D.build_dossier_prose(NOW + timedelta(hours=7))
    assert latest("META").stale is False


def test_an_unparseable_answer_is_a_failure_too(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META", prose_ago=timedelta(hours=10))
    add_cluster(101, tickers=["META"])
    fake.answer = {"names": "oops"}
    assert D.build_dossier_prose(NOW) == 0
    assert latest("META").stale is True
    assert len(fake.calls) == 2  # one retry showing the validation error


def test_a_name_the_model_leaves_out_gets_an_empty_story_not_a_retry_loop(
    news_db, fake, monkeypatch
) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META", "AMD"))
    seed("META", prose_ago=timedelta(hours=10))
    seed("AMD", prose_ago=timedelta(hours=10))
    add_cluster(101, tickers=["META"])
    add_cluster(102, tickers=["AMD"], headline="AMD ships a chip")
    fake.answer = names_answer(
        one_name("AMD", story="AMD ships a new chip.", story_evidence=["C102"])
    )
    assert D.build_dossier_prose(NOW) == 2
    meta = latest("META")
    assert (meta.story, meta.prose_at, meta.stale) == ("", NOW, False)
    assert latest("AMD").story == "AMD ships a new chip."
    # not due again at once
    fake.calls.clear()
    D.build_dossier_prose(NOW + timedelta(minutes=10))
    assert fake.calls == []


def test_an_answer_for_an_unknown_symbol_is_ignored(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META", prose_ago=timedelta(hours=10))
    add_cluster(101, tickers=["META"])
    fake.answer = names_answer(
        one_name("ZZZZ", story="Invented.", story_evidence=["C101"]),
        one_name("META", story="Meta is launching glasses.", story_evidence=["C101"]),
    )
    D.build_dossier_prose(NOW)
    with news_session() as s:
        assert queries.latest_dossier(s, "ZZZZ") is None
    assert latest("META").story == "Meta is launching glasses."


# --------------------------------------------------------------------------- #
# batches, order, the budget
# --------------------------------------------------------------------------- #


def test_batches_respect_size_and_the_dossier_cap(news_db, monkeypatch) -> None:
    names = [f"S{i:02d}" for i in range(30)]
    monkeypatch.setattr(D, "dossier_symbols", lambda: names)
    monkeypatch.setattr(D, "latest_picture_text", lambda now: None)
    monkeypatch.setattr(D, "held_underlyings", lambda: set())
    for n in names:
        seed(n, prose_ago=None)
    cfg = get_config().news
    monkeypatch.setattr(cfg.llm, "backend", "cli")
    monkeypatch.setattr(cfg.llm, "max_calls_per_day", 44)
    monkeypatch.setattr(cfg.dossier, "max_calls_per_day", 4)
    monkeypatch.setattr(cfg.dossier, "batch_size", 6)
    prompts: list[str] = []

    def cli(prompt, prefix, c):
        prompts.append(prompt)
        return json.dumps({"names": []}), None

    monkeypatch.setattr(llm, "_cli", cli)
    assert D.build_dossier_prose(NOW) == 24
    assert len(prompts) == 4 and llm_calls(NOW.date(), "dossier") == 4
    waiting = [n for n in names if latest(n).prose_at is None]
    assert len(waiting) == 6  # they wait for the next day's budget
    assert all(len([n for n in names if f"=== {n} " in p]) == 6 for p in prompts)
    # a second pass the same day finds the cap spent and builds nothing
    assert D.build_dossier_prose(NOW + timedelta(minutes=10)) == 0
    assert len(prompts) == 4


def test_names_that_wait_for_the_budget_are_not_marked_stale(news_db, monkeypatch) -> None:
    """A spent daily budget is not a failed call: the prose is simply not rebuilt yet."""
    from src.news.store.state import incr_llm_calls

    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    monkeypatch.setattr(D, "latest_picture_text", lambda now: None)
    seed("META", prose_ago=timedelta(hours=10))
    add_cluster(101, tickers=["META"])
    cfg = get_config().news
    monkeypatch.setattr(cfg.llm, "backend", "cli")
    monkeypatch.setattr(cfg.dossier, "max_calls_per_day", 2)
    for _ in range(2):
        incr_llm_calls(NOW.date(), "dossier")
    monkeypatch.setattr(llm, "_cli", lambda *a: pytest.fail("no call may be made"))
    monkeypatch.setattr("src.news.explain.call_llm", llm.call_llm)
    assert D.build_dossier_prose(NOW) == 0
    assert latest("META").stale is False


def test_held_names_are_built_first(news_db, monkeypatch) -> None:
    names = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "YYY", "ZZZ"]
    monkeypatch.setattr(D, "dossier_symbols", lambda: names)
    monkeypatch.setattr(D, "held_underlyings", lambda: {"ZZZ", "YYY"})
    monkeypatch.setattr(D, "latest_picture_text", lambda now: None)
    for n in names:
        # DDD also needs a profile, so it has two reasons; the others only `new`
        seed(n, prose_ago=None, profile_ago=None if n == "DDD" else timedelta(days=1))
    cfg = get_config().news
    monkeypatch.setattr(cfg.dossier, "batch_size", 3)
    monkeypatch.setattr(cfg.dossier, "max_calls_per_day", 1)  # one batch only
    monkeypatch.setattr(cfg.llm, "max_calls_per_day", 44)
    monkeypatch.setattr(cfg.llm, "backend", "cli")
    monkeypatch.setattr(llm, "_cli", lambda p, prefix, c: (json.dumps({"names": []}), None))
    monkeypatch.setattr("src.news.explain.call_llm", llm.call_llm)  # the real budget, a fake CLI
    assert D.build_dossier_prose(NOW) == 3
    built = {n for n in names if latest(n).prose_at is not None}
    assert built == {"YYY", "ZZZ", "DDD"}  # the two held names, then the one with more reasons


def test_the_order_is_held_then_reasons_then_symbol(monkeypatch) -> None:
    monkeypatch.setattr(D, "held_underlyings", lambda: {"ZZZ"})
    items = [("AAA", ["new"]), ("BBB", ["new", "profile"]), ("ZZZ", ["new"]), ("CCC", ["new"])]
    assert [name for name, _ in D.order_due(items)] == ["ZZZ", "BBB", "AAA", "CCC"]


def test_a_name_with_no_dossier_row_waits_for_the_facts_refresh(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    assert D.build_dossier_prose(NOW) == 0
    assert fake.calls == []


def test_nothing_due_makes_no_call(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META")
    assert D.build_dossier_prose(NOW) == 0
    assert fake.calls == []


def test_a_disabled_dossier_builds_nothing(news_db, fake, monkeypatch) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META", prose_ago=None)
    monkeypatch.setattr(get_config().news.dossier, "enabled", False)
    assert D.build_dossier_prose(NOW) == 0 and fake.calls == []


def test_the_prose_overlays_the_newest_numbers(news_db, fake, monkeypatch) -> None:
    """The model call takes a while; an hourly numbers refresh that lands meanwhile must not be
    overwritten with the older numbers the build started from."""
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META", prose_ago=None, profile_ago=None)
    newer_facts = [DossierFact(id="META:F1", label="RSI14", display="RSI 61")]

    def answer(prompt: str) -> dict:
        refreshed = seed(
            "META",
            prose_ago=None,
            profile_ago=None,
            facts_ago=timedelta(minutes=1),
            facts=newer_facts,
            version="META@refresh",
        )
        assert refreshed.facts == newer_facts
        return names_answer(one_name("META", profile="A social media company."))

    fake.answer = answer
    D.build_dossier_prose(NOW)
    got = latest("META")
    assert got.profile == "A social media company."
    assert got.facts == newer_facts  # the refresh's numbers survived the prose write
    assert got.version not in ("META@refresh",) and got.version.startswith("META@")


def test_prose_rows_have_their_own_version(news_db, fake, monkeypatch) -> None:
    """A prose build and a numbers refresh at the same instant must not collide on the unique
    version column."""
    monkeypatch.setattr(D, "dossier_symbols", symbols("META"))
    seed("META", prose_ago=None, facts_ago=timedelta(0))  # version META@<NOW>
    D.build_dossier_prose(NOW)
    with news_session() as s:
        versions = [r.version for r in s.query(TickerDossierRow).all()]
    assert len(versions) == len(set(versions)) == 2


# --------------------------------------------------------------------------- #
# the loops and the window
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (
            datetime(2026, 10, 22, 11, 59, tzinfo=UTC),
            False,
        ),  # 07:59 ET: before the premarket digest
        (datetime(2026, 10, 22, 12, 0, tzinfo=UTC), True),  # 08:00 ET
        (datetime(2026, 10, 22, 20, 30, tzinfo=UTC), True),  # 16:30 ET
        (datetime(2026, 10, 22, 20, 31, tzinfo=UTC), False),  # after the close digest
        (datetime(2026, 10, 24, 15, 0, tzinfo=UTC), False),  # Saturday
    ],
)
def test_the_dossier_window_is_premarket_to_the_close_on_trading_days(when, expected) -> None:
    assert D.in_dossier_window(when) is expected


async def test_the_service_runs_the_two_dossier_loops(news_db, monkeypatch) -> None:
    import src.news.service as S

    svc = S.NewsService(get_config(), clock=lambda: NOW)
    loops = {n: (i, f) for n, i, f in svc.loops()}
    assert loops["dossier_facts"][0] == 300 and loops["dossier"][0] == 600
    seen: dict[str, object] = {}
    monkeypatch.setattr(S, "refresh_facts", lambda now, **kw: seen.setdefault("facts", (now, kw)))
    monkeypatch.setattr(S, "build_dossier_prose", lambda now: seen.setdefault("prose", now))
    await loops["dossier_facts"][1](NOW)
    await loops["dossier"][1](NOW)
    assert seen["prose"] == NOW and seen["facts"][0] == NOW
    assert seen["facts"][1]["an"] is svc.an  # the service's one analytics bundle


async def test_the_loops_do_nothing_outside_the_window_or_when_disabled(
    news_db, monkeypatch
) -> None:
    import src.news.service as S

    svc = S.NewsService(get_config(), clock=lambda: NOW)
    loops = {n: f for n, _i, f in svc.loops()}
    calls: list[str] = []
    monkeypatch.setattr(S, "refresh_facts", lambda now, **kw: calls.append("facts"))
    monkeypatch.setattr(S, "build_dossier_prose", lambda now: calls.append("prose"))
    night = datetime(2026, 10, 22, 3, 0, tzinfo=UTC)
    await loops["dossier_facts"](night)
    await loops["dossier"](night)
    monkeypatch.setattr(get_config().news.dossier, "enabled", False)
    await loops["dossier_facts"](NOW)
    await loops["dossier"](NOW)
    assert calls == []
