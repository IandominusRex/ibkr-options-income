"""OI-E12: each dossier name is validated on its own.

The model answers for up to six names in one call. One field over its limit (a story past 280
characters, a fourth event, a date that is not ISO, a profile past 400) used to fail the whole
reply, so the retry and the next 10-minute loops spent the day's four dossier calls and left every
name's prose unbuilt. Now a name that breaks its limits or its schema is rejected alone: the other
names in the reply are accepted, the rejected one keeps its previous prose (marked stale) and the
call is counted once. A name whose draft was rejected waits ``prose_min_interval_hours`` before its
next attempt, so a persistently bad answer costs one call per interval. A reply that is not usable
at all (no JSON object, or ``names`` not a list) is still retried once as a whole.

The model is faked below the call counter (``llm._cli``), so ``llm_calls`` is the real count.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from src.common.config import get_config
from src.news import dossier as D
from src.news import explain, llm
from src.news.schemas import DossierNameDraft
from src.news.store.session import news_session
from src.news.store.state import llm_calls
from tests.test_dossier_build import (
    NOW,
    add_cluster,
    latest,
    names_answer,
    one_name,
    seed,
    symbols,
)

SIX = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
OLD = timedelta(hours=10)


@dataclass
class Scripted:
    """The CLI below the call counter: answers with ``answer`` (a dict, or raw text)."""

    answer: object = None
    prompts: list[str] = field(default_factory=list)

    def __call__(self, prompt, prefix, cfg):
        self.prompts.append(prompt)
        body = self.answer(prompt) if callable(self.answer) else self.answer
        return (body if isinstance(body, str) else json.dumps(body)), None


@pytest.fixture()
def scripted(monkeypatch) -> Scripted:
    s = Scripted(answer={"names": []})
    cfg = get_config().news
    monkeypatch.setattr(cfg.llm, "backend", "cli")
    monkeypatch.setattr(cfg.llm, "max_calls_per_day", 44)
    monkeypatch.setattr(cfg.dossier, "max_calls_per_day", 4)
    monkeypatch.setattr(llm, "_cli", s)
    monkeypatch.setattr("src.news.explain.call_llm", llm.call_llm)
    monkeypatch.setattr(D, "latest_picture_text", lambda now: None)
    monkeypatch.setattr(D, "held_underlyings", lambda: set())
    return s


def setup(monkeypatch, names: list[str], *, prose_ago: timedelta | None = OLD) -> None:
    """Every name has prose from *prose_ago* and a pile 2 story judged since: all are due."""
    monkeypatch.setattr(D, "dossier_symbols", symbols(*names))
    for i, n in enumerate(names):
        seed(n, prose_ago=prose_ago)
        add_cluster(100 + i, tickers=[n], headline=f"{n} announces a product", pile=2)


def good(symbol: str, i: int) -> dict:
    return one_name(symbol, story=f"{symbol} announces a product.", story_evidence=[f"C{100 + i}"])


def six_answer(bad_index: int, **bad_fields) -> dict:
    names = [good(n, i) for i, n in enumerate(SIX)]
    names[bad_index] = {**names[bad_index], **bad_fields}
    return names_answer(*names)


def calls() -> int:
    return llm_calls(NOW.date(), "dossier")


# --------------------------------------------------------------------------- #
# one bad name among six
# --------------------------------------------------------------------------- #


def test_one_over_long_story_among_six_five_accepted_one_stale_one_call(
    news_db, scripted, monkeypatch
) -> None:
    setup(monkeypatch, SIX)
    scripted.answer = six_answer(3, story="x" * 300)  # DDD overshoots the 280-character limit
    assert D.build_dossier_prose(NOW) == 5
    for i, n in enumerate(SIX):
        got = latest(n)
        if n == "DDD":
            assert got.stale is True
            assert got.story.startswith("OLDSTORY") and got.prose_at == NOW - OLD
        else:
            assert got.stale is False and got.prose_at == NOW
            assert got.story == f"{n} announces a product." and got.story_evidence == [
                f"C{100 + i}"
            ]
    assert calls() == 1 and len(scripted.prompts) == 1  # counted once, never retried


@pytest.mark.parametrize(
    ("label", "fields"),
    [
        ("story over 280", {"story": "x" * 281}),
        (
            "four events",
            {
                "events": [
                    {"title": f"Event {n}", "on": f"2026-11-0{n}", "evidence": "C103"}
                    for n in (1, 2, 3, 4)
                ]
            },
        ),
        (
            "a date that is not ISO",
            {"events": [{"title": "Keynote", "on": "next Tuesday", "evidence": "C103"}]},
        ),
        ("profile over 400", {"profile": "p" * 401}),
        ("story_evidence not a list", {"story_evidence": "C103"}),
        ("an event with no date", {"events": [{"title": "Keynote", "evidence": "C103"}]}),
    ],
)
def test_each_limit_rejects_its_own_name_only(
    news_db, scripted, monkeypatch, label, fields
) -> None:
    setup(monkeypatch, SIX)
    scripted.answer = six_answer(3, **fields)
    assert D.build_dossier_prose(NOW) == 5, label
    assert latest("DDD").stale is True and latest("DDD").prose_at == NOW - OLD, label
    assert all(latest(n).prose_at == NOW for n in SIX if n != "DDD"), label
    assert calls() == 1, label


def test_two_bad_names_do_not_cost_the_four_good_ones(news_db, scripted, monkeypatch) -> None:
    setup(monkeypatch, SIX)
    names = [good(n, i) for i, n in enumerate(SIX)]
    names[1]["story"] = "x" * 300
    names[4]["profile"] = "p" * 500
    scripted.answer = names_answer(*names)
    assert D.build_dossier_prose(NOW) == 4
    assert {n for n in SIX if latest(n).stale} == {"BBB", "EEE"}
    assert calls() == 1


def test_a_rejected_name_with_no_prose_yet_is_not_marked_stale(
    news_db, scripted, monkeypatch
) -> None:
    setup(monkeypatch, ["AAA", "BBB"], prose_ago=None)
    scripted.answer = names_answer(good("AAA", 0), {**good("BBB", 1), "story": "x" * 300})
    assert D.build_dossier_prose(NOW) == 1
    bbb = latest("BBB")
    assert bbb.stale is False and bbb.prose_at is None  # nothing was written, nothing to mark
    assert latest("AAA").prose_at == NOW


def test_the_first_valid_draft_of_a_name_wins_whatever_the_order(
    news_db, scripted, monkeypatch
) -> None:
    setup(monkeypatch, ["AAA", "BBB"])
    bad = {**good("AAA", 0), "story": "x" * 300}
    scripted.answer = names_answer(bad, good("AAA", 0), good("BBB", 1), bad | {"symbol": "BBB"})
    assert D.build_dossier_prose(NOW) == 2
    assert latest("AAA").stale is False and latest("AAA").story == "AAA announces a product."
    assert latest("BBB").stale is False


def test_an_element_that_is_not_an_object_or_has_no_symbol_is_ignored(
    news_db, scripted, monkeypatch
) -> None:
    setup(monkeypatch, ["AAA", "BBB"])
    scripted.answer = {"names": ["oops", {"story": "no symbol"}, good("AAA", 0)]}
    assert D.build_dossier_prose(NOW) == 2
    assert latest("AAA").story == "AAA announces a product."
    assert latest("BBB").story == ""  # left out: the existing empty story, not stale
    assert latest("BBB").stale is False and latest("BBB").prose_at == NOW


# --------------------------------------------------------------------------- #
# a reply that is not usable at all is retried as a whole, once, as before
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("reply", [{"names": "oops"}, {"names": {"a": 1}}, "this is not json"])
def test_an_unusable_reply_is_retried_once_then_the_batch_is_stale(
    news_db, scripted, monkeypatch, reply
) -> None:
    setup(monkeypatch, ["AAA", "BBB"])
    scripted.answer = reply
    assert D.build_dossier_prose(NOW) == 0
    assert calls() == 2 and len(scripted.prompts) == 2
    assert "not usable" in scripted.prompts[1]
    assert latest("AAA").stale is True and latest("BBB").stale is True


def test_a_retry_that_answers_properly_saves_the_batch(news_db, scripted, monkeypatch) -> None:
    setup(monkeypatch, ["AAA"])
    replies = iter([{"names": "oops"}, names_answer(good("AAA", 0))])
    scripted.answer = lambda prompt: next(replies)
    assert D.build_dossier_prose(NOW) == 1
    assert calls() == 2 and latest("AAA").story == "AAA announces a product."


def test_a_reply_without_names_is_an_empty_list_and_leaves_every_name_out(
    news_db, scripted, monkeypatch
) -> None:
    setup(monkeypatch, ["AAA"])
    scripted.answer = {}
    assert D.build_dossier_prose(NOW) == 1
    assert calls() == 1 and latest("AAA").story == "" and latest("AAA").prose_at == NOW


# --------------------------------------------------------------------------- #
# the loop guard: a rejected name must not be rebuilt on every 10-minute loop
# --------------------------------------------------------------------------- #


def test_a_persistently_bad_name_costs_one_call_per_interval(
    news_db, scripted, monkeypatch
) -> None:
    setup(monkeypatch, ["AAA"])
    scripted.answer = names_answer({**good("AAA", 0), "story": "x" * 300})
    interval = timedelta(hours=get_config().news.dossier.prose_min_interval_hours)
    minutes = 0
    while timedelta(minutes=minutes) < interval:  # every 10-minute loop of the first interval
        D.build_dossier_prose(NOW + timedelta(minutes=minutes))
        minutes += 10
    assert len(scripted.prompts) == 1 and calls() == 1
    assert latest("AAA").stale is True
    # the interval is over: one more attempt, then the wait starts again
    D.build_dossier_prose(NOW + interval)
    assert len(scripted.prompts) == 2
    D.build_dossier_prose(NOW + interval + timedelta(minutes=10))
    D.build_dossier_prose(NOW + interval + timedelta(hours=5))
    assert len(scripted.prompts) == 2


def test_the_wait_holds_for_every_due_reason_not_just_news(news_db, scripted, monkeypatch) -> None:
    """An alert or a fresh earnings release never waited before; a rejected name waits anyway."""
    from tests.test_dossier_build import add_post

    setup(monkeypatch, ["AAA"])
    scripted.answer = names_answer({**good("AAA", 0), "story": "x" * 300})
    D.build_dossier_prose(NOW)
    assert len(scripted.prompts) == 1
    add_post(subject="AAA", kind="ticker_move")  # an alert since the last prose
    D.build_dossier_prose(NOW + timedelta(minutes=10))
    assert len(scripted.prompts) == 1


def test_a_name_with_no_prose_yet_also_waits_after_a_rejection(
    news_db, scripted, monkeypatch
) -> None:
    setup(monkeypatch, ["AAA"], prose_ago=None)
    scripted.answer = names_answer({**good("AAA", 0), "story": "x" * 300})
    D.build_dossier_prose(NOW)
    D.build_dossier_prose(NOW + timedelta(minutes=10))
    D.build_dossier_prose(NOW + timedelta(hours=3))
    assert len(scripted.prompts) == 1  # not 'new' on every loop
    D.build_dossier_prose(NOW + timedelta(hours=6))
    assert len(scripted.prompts) == 2


def test_a_good_answer_after_the_wait_builds_the_name_and_clears_the_wait(
    news_db, scripted, monkeypatch
) -> None:
    setup(monkeypatch, ["AAA"])
    scripted.answer = names_answer({**good("AAA", 0), "story": "x" * 300})
    D.build_dossier_prose(NOW)
    scripted.answer = names_answer(good("AAA", 0))
    later = NOW + timedelta(hours=6)
    assert D.build_dossier_prose(later) == 1
    got = latest("AAA")
    assert got.stale is False and got.prose_at == later
    with news_session() as s:
        assert D._rejected_at(s, "AAA") is None


def test_a_rejection_waits_only_for_the_name_that_was_rejected(
    news_db, scripted, monkeypatch
) -> None:
    setup(monkeypatch, ["AAA", "BBB"])
    scripted.answer = names_answer({**good("AAA", 0), "story": "x" * 300}, good("BBB", 1))
    D.build_dossier_prose(NOW)
    with news_session() as s:
        assert D.dossier_due("AAA", latest("AAA"), now=NOW + timedelta(minutes=10), s=s) == []
        assert D._rejected_at(s, "BBB") is None


# --------------------------------------------------------------------------- #
# the call itself
# --------------------------------------------------------------------------- #


def test_validated_items_call_returns_the_good_items_and_the_rejected_ones(
    news_db, scripted
) -> None:
    scripted.answer = {
        "names": [
            {"symbol": "AAA", "story": "fine"},
            {"symbol": "BBB", "story": "x" * 300},
            "oops",
        ]
    }
    got = explain.validated_items_call(
        DossierNameDraft, "prompt", key="names", schema={}, prefix="t", now=NOW, purpose="dossier"
    )
    assert got is not None
    accepted, rejected = got
    assert [a.symbol for a in accepted] == ["AAA"]
    assert [r[0] if not isinstance(r[0], dict) else r[0]["symbol"] for r in rejected] == [
        "BBB",
        "oops",
    ]
    assert all(isinstance(why, str) and why for _raw, why in rejected)
    assert calls() == 1


def test_validated_items_call_is_none_without_an_answer(news_db, monkeypatch) -> None:
    monkeypatch.setattr("src.news.explain.call_llm", lambda *a, **k: None)
    assert (
        explain.validated_items_call(
            DossierNameDraft, "prompt", key="names", schema={}, prefix="t", now=NOW
        )
        is None
    )
