"""OI-E10: figures quoted from the news live in a separate `reported` list, never in the story.

The story keeps using only Python's numbers (the name's own facts). A figure the model quotes from
the cited news goes in `reported`: a short text and the id of a cluster the model was shown for
that name. Python checks each item on its own: every number in its text must be written in the
cited cluster's shown text (headline and the first two items, summaries cut at 200 characters),
within the grounding tolerance; the cluster must be one shown for that name; the story's advice
and meta stripping applies; an item that fails is dropped alone and never costs the story. Every
reader prints the figures on their own line, "Reported in news (not computed by the system)".
No test makes a real model call: ``call_llm`` is faked.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.common.dossier_text import render_dossier, render_dossiers
from src.common.schemas import DossierReported, TickerDossier
from src.news import dossier as D
from src.news.store import queries
from src.news.store.models import TickerDossierRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from tests.test_dossier_build import (
    NOW,
    FakeLlm,
    add_cluster,
    facts_for,
    latest,
    names_answer,
    one_name,
    seed,
    symbols,
)


@pytest.fixture()
def fake(monkeypatch) -> FakeLlm:
    f = FakeLlm()
    monkeypatch.setattr("src.news.explain.call_llm", f)
    monkeypatch.setattr(D, "latest_picture_text", lambda now: None)
    monkeypatch.setattr(D, "held_underlyings", lambda: set())
    return f


LAUNCH = ("Meta to unveil MUSE glasses at Connect", "Analysts see $5.2 billion in glasses sales.")


def reported_setup(monkeypatch, *, items=None, names=("META",)) -> None:
    monkeypatch.setattr(D, "dossier_symbols", symbols(*names))
    seed("META", prose_ago=timedelta(hours=10))
    add_cluster(
        101, tickers=["META"], headline="Meta plans a glasses launch", items=items or [LAUNCH]
    )


def item(text: str, evidence: str = "C101") -> dict:
    return {"text": text, "evidence": evidence}


def build(fake, *reported: dict, story: str = "", evidence: list[str] | None = None, **kw):
    fake.answer = names_answer(
        one_name("META", story=story, story_evidence=evidence or [], reported=list(reported), **kw)
    )
    D.build_dossier_prose(NOW)
    return latest("META")


# --------------------------------------------------------------------------- #
# what survives
# --------------------------------------------------------------------------- #


def test_a_reported_figure_in_the_cited_clusters_shown_text_survives(
    news_db, fake, monkeypatch
) -> None:
    reported_setup(monkeypatch)
    got = build(fake, item("Analysts see glasses sales of $5.2 billion"))
    assert got.reported == [
        DossierReported(text="Analysts see glasses sales of $5.2 billion", cluster_id="C101")
    ]


def test_a_figure_absent_from_the_cited_clusters_shown_text_is_dropped(
    news_db, fake, monkeypatch
) -> None:
    reported_setup(monkeypatch)
    got = build(
        fake,
        item("Analysts see glasses sales of $7.9 billion"),  # not in the news
        item("Analysts see glasses sales of $5.2 billion"),
    )
    assert [r.text for r in got.reported] == ["Analysts see glasses sales of $5.2 billion"]


def test_every_number_in_an_item_must_be_in_the_news_not_just_one(
    news_db, fake, monkeypatch
) -> None:
    reported_setup(monkeypatch)
    got = build(fake, item("Sales of $5.2 billion in 2031 across 85 markets"))
    assert got.reported == []


def test_a_small_number_that_is_not_in_the_news_is_dropped_too(news_db, fake, monkeypatch) -> None:
    """The story's grounding lets a bare small number through; a quoted figure may not."""
    reported_setup(monkeypatch)
    got = build(fake, item("Launch in 7 markets"), item("Analysts see sales of $5.2 billion"))
    assert [r.text for r in got.reported] == ["Analysts see sales of $5.2 billion"]


def test_a_number_only_an_unshown_item_states_is_dropped(news_db, fake, monkeypatch) -> None:
    """The check runs against what the prompt showed: headline and the first two items."""
    reported_setup(
        monkeypatch,
        items=[("First item", None), ("Second item", None), ("Third item says $9.9 billion", None)],
    )
    got = build(fake, item("Sales of $9.9 billion"))
    assert got.reported == []
    assert "$9.9 billion" not in fake.calls[0]["prompt"]


def test_a_summary_is_checked_only_up_to_the_200_characters_the_model_saw(
    news_db, fake, monkeypatch
) -> None:
    reported_setup(monkeypatch, items=[("Item", "x" * 200 + " then $4.4 billion")])
    got = build(fake, item("Sales of $4.4 billion"))
    assert got.reported == []


def test_a_figure_within_the_grounding_tolerance_is_kept_and_a_far_one_is_not(
    news_db, fake, monkeypatch
) -> None:
    reported_setup(monkeypatch, items=[("Item", "Revenue of $250.0 million.")])
    got = build(fake, item("Revenue of $251 million"), item("Revenue of $300 million"))
    assert [r.text for r in got.reported] == ["Revenue of $251 million"]


def test_an_item_citing_a_cluster_the_model_was_not_shown_is_dropped(
    news_db, fake, monkeypatch
) -> None:
    reported_setup(monkeypatch)
    add_cluster(
        202, tickers=["AMD"], headline="AMD ships a chip", items=[("AMD chip", "$5.2 billion")]
    )
    got = build(
        fake,
        item("Analysts see sales of $5.2 billion", "C555"),  # no such cluster
        item("Analysts see sales of $5.2 billion", "C202"),  # shown for another name only
        item("Analysts see sales of $5.2 billion", "101"),  # malformed id
        item("Analysts see sales of $5.2 billion", "C101"),
    )
    assert [r.cluster_id for r in got.reported] == ["C101"]


def test_advice_meta_and_ids_in_a_reported_item_drop_it(news_db, fake, monkeypatch) -> None:
    reported_setup(monkeypatch)
    got = build(
        fake,
        item("Buy the dip as sales reach $5.2 billion"),
        item("The headlines supplied say sales reach $5.2 billion"),
        item("Sales reach $5.2 billion (C101)"),
        item("Sales reach $5.2 billion, per C101"),
        item("Sales of $5.2 billion are expected"),
    )
    assert [r.text for r in got.reported] == ["Sales of $5.2 billion are expected"]


def test_an_item_over_120_characters_is_dropped_alone(news_db, fake, monkeypatch) -> None:
    reported_setup(monkeypatch)
    long = "Analysts see sales of $5.2 billion " + "x" * 90
    assert len(long) > 120
    got = build(
        fake,
        item(long),
        item("Analysts see sales of $5.2 billion"),
        story="Meta is preparing a glasses launch.",
        evidence=["C101"],
    )
    assert [r.text for r in got.reported] == ["Analysts see sales of $5.2 billion"]
    assert got.story == "Meta is preparing a glasses launch."  # the story is not lost


def test_at_most_three_items_are_kept_the_first_three_that_pass(news_db, fake, monkeypatch) -> None:
    reported_setup(
        monkeypatch,
        items=[("Item", "Figures: $1.1 billion, $2.2 billion, $3.3 billion, $4.4 billion.")],
    )
    got = build(
        fake,
        item("Figure $1.1 billion"),
        item("Figure $9.9 billion"),  # fails: not in the news
        item("Figure $2.2 billion"),
        item("Figure $3.3 billion"),
        item("Figure $4.4 billion"),
    )
    assert [r.text for r in got.reported] == [
        "Figure $1.1 billion",
        "Figure $2.2 billion",
        "Figure $3.3 billion",
    ]


def test_duplicate_items_collapse(news_db, fake, monkeypatch) -> None:
    reported_setup(monkeypatch)
    got = build(fake, item("Sales of $5.2 billion"), item("Sales of  $5.2 billion"))
    assert len(got.reported) == 1


# --------------------------------------------------------------------------- #
# one bad item never costs the story, and the story keeps only Python's numbers
# --------------------------------------------------------------------------- #


def test_a_malformed_item_does_not_reject_the_name_or_lose_the_story(
    news_db, fake, monkeypatch
) -> None:
    reported_setup(monkeypatch)
    fake.answer = names_answer(
        one_name(
            "META",
            story="Meta is preparing a glasses launch.",
            story_evidence=["C101"],
            reported=["just a string", {"text": "no evidence"}, 7, item("Sales of $5.2 billion")],
        )
    )
    D.build_dossier_prose(NOW)
    got = latest("META")
    assert got.story == "Meta is preparing a glasses launch."
    assert [r.text for r in got.reported] == ["Sales of $5.2 billion"]
    assert got.stale is False and got.prose_at == NOW


def test_the_story_with_a_news_only_number_is_still_dropped_while_the_reported_figure_stays(
    news_db, fake, monkeypatch
) -> None:
    reported_setup(monkeypatch)
    got = build(
        fake,
        item("Analysts see glasses sales of $5.2 billion"),
        story="Meta is preparing a glasses launch with $5.2 billion of sales expected.",
        evidence=["C101"],
    )
    assert got.story == ""  # the figure is in the news, not in the name's facts: unchanged rule
    assert [r.text for r in got.reported] == ["Analysts see glasses sales of $5.2 billion"]


def test_the_story_may_still_use_a_fact_number_and_never_gets_a_reported_one_mixed_in(
    news_db, fake, monkeypatch
) -> None:
    reported_setup(monkeypatch)
    got = build(
        fake,
        item("Analysts see glasses sales of $5.2 billion"),
        story="The shares sit with RSI 52 while the launch nears.",
        evidence=["C101"],
    )
    assert got.story == "The shares sit with RSI 52 while the launch nears."
    assert "5.2" not in got.story


def test_a_rebuild_replaces_the_reported_list_and_a_failed_one_keeps_it(
    news_db, fake, monkeypatch
) -> None:
    reported_setup(monkeypatch)
    first = build(fake, item("Sales of $5.2 billion"))
    assert len(first.reported) == 1
    # the old list is never fed back to the model
    assert "Sales of $5.2 billion" not in fake.calls[0]["prompt"].split("=== META")[0]
    # a later build with no valid figure replaces it with an empty list
    add_cluster(102, tickers=["META"], headline="Another story", judged_ago=-timedelta(hours=1))
    fake.answer = names_answer(one_name("META", story="", reported=[]))
    D.build_dossier_prose(NOW + timedelta(hours=7))
    assert latest("META").reported == []
    add_cluster(103, tickers=["META"], headline="A third story", judged_ago=-timedelta(hours=8))
    fake.answer = names_answer(one_name("META", reported=[item("Sales of $5.2 billion")]))
    D.build_dossier_prose(NOW + timedelta(hours=14))
    again = latest("META")
    assert len(again.reported) == 1
    # a failed call keeps what was there, marked stale
    add_cluster(104, tickers=["META"], headline="A fourth story", judged_ago=-timedelta(hours=15))
    fake.fail = True
    D.build_dossier_prose(NOW + timedelta(hours=21))
    kept = latest("META")
    assert kept.reported == again.reported and kept.stale is True


def test_the_hourly_numbers_refresh_carries_the_reported_list_forward(news_db) -> None:
    prev = seed(
        "META",
        prose_ago=timedelta(hours=2),
        reported=[DossierReported(text="Sales of $5.2 billion", cluster_id="C101")],
    )
    fresh = D._fresh_row(
        "META",
        prev,
        now=NOW,
        today=NOW.date(),
        facts=facts_for("META"),
        sentiment=None,
        items=0,
        kind="stock",
        health="strong",
        why=[],
    )
    assert fresh.reported == prev.reported


# --------------------------------------------------------------------------- #
# the prompt
# --------------------------------------------------------------------------- #


def test_the_prompt_asks_for_reported_figures_and_limits_the_story_to_the_facts(
    news_db, fake, monkeypatch
) -> None:
    reported_setup(monkeypatch)
    D.build_dossier_prose(NOW)
    prompt = fake.calls[0]["prompt"]
    # the story may use only the facts' numbers: any figure quoted from the news goes in `reported`
    assert 'goes ONLY in "reported"' in prompt
    assert "Never put such a figure in the story" in prompt
    assert "using only numbers from the name's facts" in prompt
    assert "REPORTED:" in prompt and "at most 120 characters" in prompt
    assert "with the C# of the cluster that states it" in prompt
    assert '"reported"' in prompt  # in the JSON schema the model is shown


# --------------------------------------------------------------------------- #
# storage and old rows
# --------------------------------------------------------------------------- #


def test_the_list_round_trips_through_the_store(news_db) -> None:
    seed("META", reported=[DossierReported(text="Sales of $5.2 billion", cluster_id="C101")])
    with news_session() as s:
        got = queries.latest_dossier(s, "META")
    assert got is not None
    assert got.reported == [DossierReported(text="Sales of $5.2 billion", cluster_id="C101")]


def test_an_older_stored_dossier_without_the_key_reads_as_an_empty_list(news_db) -> None:
    d = seed("META")
    payload = d.model_dump(mode="json")
    payload.pop("reported", None)  # a row written before this field existed
    with news_session() as s:
        s.add(
            TickerDossierRow(
                symbol="AMD",
                version="AMD@old",
                built_at=naive_utc(NOW),
                payload={**payload, "symbol": "AMD", "version": "AMD@old"},
            )
        )
    with news_session() as s:
        old = queries.latest_dossier(s, "AMD")
    assert old is not None and old.reported == []


# --------------------------------------------------------------------------- #
# the readers: a separate, labelled line
# --------------------------------------------------------------------------- #

LABEL = "Reported in news (not computed by the system): "


def dossier_with(**kw) -> TickerDossier:
    base = dict(
        symbol="META",
        version="META@v1",
        facts_at=NOW - timedelta(hours=1),
        prose_at=NOW - timedelta(hours=2),
        profile_at=NOW - timedelta(days=1),
        kind="stock",
        health="strong",
        facts=facts_for("META"),
        story="Meta is preparing a glasses launch.",
        story_evidence=["C101"],
        reported=[
            DossierReported(text="Analysts see glasses sales of $5.2 billion", cluster_id="C101"),
            DossierReported(text="Launch set for 3 markets", cluster_id="C102"),
        ],
    )
    base.update(kw)
    return TickerDossier(**base)


@pytest.mark.parametrize("compact", [True, False])
def test_the_notes_print_the_reported_figures_on_their_own_labelled_line(compact) -> None:
    text = render_dossier(
        dossier_with(), symbol="META", now=NOW, staleness_hours=48, compact=compact
    )
    lines = text.splitlines()
    (reported_line,) = [ln for ln in lines if ln.startswith(LABEL)]
    assert "$5.2 billion" in reported_line and "(C101)" in reported_line
    story_line = next(ln for ln in lines if ln.startswith("Story:"))
    assert "5.2" not in story_line  # never mixed into the story line
    assert "Reported" not in story_line


def test_the_full_note_shows_every_item_and_the_compact_one_at_most_two() -> None:
    d = dossier_with(
        reported=[DossierReported(text=f"Figure {n} billion", cluster_id="C101") for n in (1, 2, 3)]
    )
    full = render_dossier(d, symbol="META", now=NOW, staleness_hours=48, compact=False)
    assert all(f"Figure {n} billion" in full for n in (1, 2, 3))
    compact = render_dossier(d, symbol="META", now=NOW, staleness_hours=48, compact=True)
    assert "Figure 3 billion" not in compact and "Figure 1 billion" in compact


def test_an_empty_list_prints_nothing() -> None:
    text = render_dossier(
        dossier_with(reported=[]), symbol="META", now=NOW, staleness_hours=48, compact=False
    )
    assert "Reported" not in text and "not computed" not in text


@pytest.mark.parametrize("compact", [True, False])
def test_the_word_budget_still_holds_with_reported_figures(compact) -> None:
    budget = 80 if compact else 220
    for story_words in (5, 40, 55):
        for n_reported in (0, 1, 2, 3):
            d = dossier_with(
                story=" ".join(["word"] * story_words) + ".",
                health_why=["passes the quality screen", "free cash flow positive"],
                reported=[
                    DossierReported(text="Figure " + " ".join(["x"] * 17), cluster_id="C101")
                    for _ in range(n_reported)
                ],
            )
            text = render_dossier(d, symbol="META", now=NOW, staleness_hours=48, compact=compact)
            assert len(text.split()) <= budget, (compact, story_words, n_reported)


def test_the_block_every_reader_shares_carries_the_labelled_line() -> None:
    block = render_dossiers(
        [("META", dossier_with()), ("AMD", None)], now=NOW, staleness_hours=48, compact=True
    )
    assert LABEL in block and block.startswith("=== NAME NOTES ===")


def test_a_stale_dossier_keeps_the_reported_line_under_the_stale_label() -> None:
    text = render_dossier(
        dossier_with(stale=True), symbol="META", now=NOW, staleness_hours=48, compact=False
    )
    assert "PROSE IS STALE" in text and LABEL in text


def test_the_review_prompts_carry_the_labelled_line_through_the_shared_block() -> None:
    """The trade review, the deep-dive and the roll review all print the block this builds."""
    from src.claude.dossier_context import dossier_block
    from src.claude.prompts.strategist import build_prompt
    from tests.test_claude import _make_account, _make_candidate

    d = dossier_with()
    for compact in (True, False):
        block = dossier_block(["META"], {"META": d}, now=NOW, compact=compact, max_names=8)
        assert LABEL in block
        prompt = build_prompt([_make_candidate("c-1")], _make_account(), dossier_block=block)
        assert LABEL + "Analysts see glasses sales of $5.2 billion (C101)" in prompt
        story = next(ln for ln in prompt.splitlines() if ln.startswith("Story:"))
        assert "5.2" not in story
