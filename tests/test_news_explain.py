# tests/test_news_explain.py
from __future__ import annotations

import json
from datetime import UTC, datetime

from src.news import explain as X
from src.news.llm import LlmResult
from src.news.schemas import ClusterView, FactSheet, ItemView

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)
GOOD = {
    "headline": "NVDA slides on curbs",
    "what_happened": "NVDA fell 6.2% on export curbs.",
    "read": "Move is 2x implied.",
    "bull": "AI demand intact",
    "bear": "China revenue at risk",
    "verdict": "overreaction_likely",
    "confidence": "medium",
    "book_impact": "",
    "setup_impact": "",
    "evidence": ["F1", "N1"],
}


def _facts():
    s = FactSheet()
    s.add("Move today", -6.2, "-6.2%")
    s.add("Move ÷ implied", 2.0, "2.0× implied")
    return s


def test_explain_happy_path(news_db, monkeypatch) -> None:
    monkeypatch.setattr(X, "call_llm", lambda prompt, **kw: LlmResult(json.dumps(GOOD), "cli"))
    out = X.explain_card(
        "ticker_move",
        headlines=[ItemView(title="Nvidia hit by curbs")],
        facts=_facts(),
        prior=None,
        reaction=None,
        now=NOW,
    )
    assert (
        out.stage == "explained"
        and out.backend == "cli"
        and out.explanation.verdict == "overreaction_likely"
    )


def test_invalid_then_valid_retries_once(news_db, monkeypatch) -> None:
    replies = iter([LlmResult('{"headline": "x"}', "cli"), LlmResult(json.dumps(GOOD), "cli")])
    prompts = []
    monkeypatch.setattr(X, "call_llm", lambda prompt, **kw: prompts.append(prompt) or next(replies))
    out = X.explain_card(
        "ticker_move", headlines=[], facts=_facts(), prior=None, reaction=None, now=NOW
    )
    assert out.stage == "explained" and "validation error" in prompts[1].lower()


def test_unavailable_is_fallback(news_db, monkeypatch) -> None:
    monkeypatch.setattr(X, "call_llm", lambda prompt, **kw: None)
    monkeypatch.setattr(X, "cap_reached", lambda now: True)
    out = X.explain_card(
        "ticker_move", headlines=[], facts=_facts(), prior=None, reaction=None, now=NOW
    )
    assert out.stage == "fallback" and out.explanation is None and out.note == "🧠 off (daily cap)"


def test_digest_reads_batch_one_call(news_db, monkeypatch) -> None:
    calls = []
    body = {
        "items": [
            {
                "cluster_id": 1,
                "headline": "Fed split",
                "read": "Fewer cuts.",
                "verdict": "priced_in",
                "evidence": ["N1"],
            }
        ]
    }
    monkeypatch.setattr(
        X, "call_llm", lambda prompt, **kw: calls.append(1) or LlmResult(json.dumps(body), "cli")
    )
    cl = ClusterView(
        id=1,
        headline="Fed minutes show split",
        category="macro",
        first_seen=NOW,
        last_seen=NOW,
        source_count=2,
        items=[ItemView(title="Fed minutes show split")],
    )
    reads = X.digest_reads([cl], FactSheet(), now=NOW)
    assert calls == [1] and reads[1].read == "Fewer cuts."


def test_invalid_twice_is_fallback_unavailable(news_db, monkeypatch) -> None:
    monkeypatch.setattr(
        X, "call_llm", lambda prompt, **kw: LlmResult('{"headline": "x"}', "ollama")
    )
    monkeypatch.setattr(X, "cap_reached", lambda now: False)
    out = X.explain_card(
        "ticker_move", headlines=[], facts=_facts(), prior=None, reaction=None, now=NOW
    )
    assert out.stage == "fallback" and out.backend == "ollama" and out.note == "🧠 unavailable"


def test_ungrounded_number_is_trimmed_and_what_falls_back(news_db, monkeypatch) -> None:
    bad = {**GOOD, "what_happened": "NVDA fell 9.9% on export curbs."}
    monkeypatch.setattr(X, "call_llm", lambda prompt, **kw: LlmResult(json.dumps(bad), "cli"))
    out = X.explain_card(
        "ticker_move",
        headlines=[ItemView(title="Nvidia hit by curbs")],
        facts=_facts(),
        prior=None,
        reaction=None,
        now=NOW,
        fallback_what="Move today: -6.2%",
    )
    assert out.trimmed and out.explanation.what_happened == "Move today: -6.2%"


def test_editor_drops_unknown_cluster_ids(news_db, monkeypatch) -> None:
    body = {
        "regime": "risk_off",
        "threads": [
            {"cluster_ids": [1, 99], "title": "Fed"},
            {"cluster_ids": [98], "title": "Ghost"},
        ],
        "dropped": [],
    }
    monkeypatch.setattr(X, "call_llm", lambda prompt, **kw: LlmResult(json.dumps(body), "cli"))
    cl = ClusterView(
        id=1,
        headline="Fed minutes",
        category="macro",
        first_seen=NOW,
        last_seen=NOW,
        source_count=2,
    )
    out = X.edit_digest([cl], FactSheet(), now=NOW)
    assert out is not None and out.regime == "risk_off"
    assert [t.cluster_ids for t in out.threads] == [[1]]
    assert X.edit_digest([], FactSheet(), now=NOW) is None


def test_writer_prompt_carries_facts_prior_and_reaction_gap() -> None:
    from src.news.playbook import PlaybookPrior
    from src.news.prompts import number_headlines, writer_prompt

    block, index = number_headlines(
        [ItemView(title="CPI hot", source="Reuters", summary="Core up")]
    )
    prior = PlaybookPrior(key="cpi", direction="hot", arrows={"stocks": "🔴"}, rationale="rates up")
    p = writer_prompt("macro_print", headlines=block, facts=_facts(), prior=prior, reaction=None)
    assert "F1 Move today: -6.2%" in p and "N1 [Reuters] CPI hot" in p
    assert "stocks: textbook 🔴 | actual pending" in p and "textbook rationale: rates up" in p
    assert set(index) == {"N1"}
