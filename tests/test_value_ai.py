"""The value analyst (src/value_ai/): prompts, strict parsing, the call (value book spec §8)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from src.claude.cli import CliResult, OllamaSettings
from src.common.value_ai_types import AnalystRequest, DriverBounds, FilingSection, Range
from src.value_ai.analyst import Analyst
from src.value_ai.context import AnalystContext, gather
from src.value_ai.parse import parse_reply
from src.value_ai.prompts import OUTPUT_SCHEMA, build_prompt

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
REQ = AnalystRequest(
    read_id=1,
    symbol="STDY",
    kind="standard",
    reason="top",
    lists=["deep_value", "quality_growth"],
    card_text="STDY · price 30.00",
    bounds=[
        DriverBounds(
            list_name="deep_value",
            method="dcf",
            growth=Range(lo=-0.1, hi=0.197),
            terminal=Range(lo=0.0, hi=0.025),
            discount=Range(lo=0.09, hi=0.12),
            margin=Range(lo=0.106, hi=0.1625),
        )
    ],
    kill_menu={"dilution_above": Range(lo=1.0, hi=10.0), "guidance_cut": None},
    model="claude-sonnet-4-6",
)
GOOD = {
    "lists": [
        {
            "list": "deep_value",
            "verdict": "READY",
            "why": "cheap\nand healthy",
            "drivers": {"growth": 0.08, "terminal": 0.02, "discount": 0.1, "margin": 0.15},
        },
        {"list": "quality_growth", "verdict": "MAYBE", "why": "", "drivers": {}},
        {"list": "made_up", "verdict": "READY", "why": "", "drivers": {}},
    ],
    "profile": "Makes software.",
    "thesis": "Margins hold.",
    "kill_triggers": [
        {"kind": "dilution_above", "threshold": 4},
        {"kind": "dilution_above", "threshold": 9},
        {"kind": "insider_selling_cluster", "threshold": 1},
        {"kind": "guidance_cut", "threshold": None},
    ],
    "facts": [{"kind": "one_off", "value": 5, "accn": "x", "quote": "q"}],
}


def test_a_good_reply_parses_name_by_name() -> None:
    reply = parse_reply("```json\n" + json.dumps(GOOD) + "\n```", REQ)
    assert reply is not None
    assert [(c.list_name, c.verdict) for c in reply.lists] == [("deep_value", "READY")]
    assert reply.lists[0].why == "cheap and healthy"  # one line
    assert reply.lists[0].drivers.margin == 0.15
    assert [(t.kind, t.threshold) for t in reply.kill_triggers] == [
        ("dilution_above", 4.0),
        ("guidance_cut", None),
    ]
    assert reply.facts == []  # facts come from a filing read only


def test_a_malformed_or_verdictless_reply_means_no_notes() -> None:
    assert parse_reply("not json", REQ) is None
    assert parse_reply(json.dumps({"lists": []}), REQ) is None
    bad = {"lists": [{"list": "deep_value", "verdict": "BUY", "drivers": {}}]}
    assert parse_reply(json.dumps(bad), REQ) is None


def test_text_and_bools_are_not_numbers() -> None:
    reply = parse_reply(
        json.dumps(
            {
                "lists": [
                    {
                        "list": "deep_value",
                        "verdict": "WAIT",
                        "why": "",
                        "drivers": {"growth": "8%", "terminal": True, "discount": 0.1},
                    }
                ]
            }
        ),
        REQ,
    )
    assert reply is not None
    d = reply.lists[0].drivers
    assert (d.growth, d.terminal, d.discount, d.margin) == (None, None, 0.1, None)


def test_a_review_needs_a_state_and_a_filing_read_keeps_only_facts() -> None:
    review = REQ.model_copy(update={"kind": "review"})
    assert parse_reply(json.dumps(GOOD), review) is None
    ok = parse_reply(json.dumps({**GOOD, "review_state": "BROKEN", "review_why": "x"}), review)
    assert ok is not None and ok.review_state == "BROKEN"
    filing = REQ.model_copy(update={"kind": "filing"})
    facts = parse_reply(json.dumps(GOOD), filing)
    assert facts is not None and facts.lists == [] and facts.kill_triggers == []
    assert [(f.kind, f.value) for f in facts.facts] == [("one_off", 5.0)]


def test_the_prompt_shows_the_bounds_and_the_menu_and_asks_for_no_price() -> None:
    text = build_prompt(REQ, AnalystContext(headlines=["2026-10-30 · a story · 3 source(s)"]))
    assert "growth -0.100..0.197" in text and "margin 0.106..0.163" in text
    assert "dilution_above: threshold in 1..10" in text and "guidance_cut (no threshold" in text
    assert "a story" in text and "(no dossier for this name)" in text
    fields = set(OUTPUT_SCHEMA["properties"]) | set(
        OUTPUT_SCHEMA["properties"]["lists"]["items"]["properties"]
    )
    assert not fields & {"fair_value", "price", "strike", "size", "limit"}
    filing = REQ.model_copy(
        update={
            "kind": "filing",
            "sections": [FilingSection(accn="a1", form="10-K", section="Item 7", text="MD&A")],
        }
    )
    assert "VERBATIM quote" in build_prompt(filing, AnalystContext())


def _analyst(run, *, ollama: bool = False, only: bool = False) -> tuple[Analyst, list[dict]]:
    calls: list[dict] = []

    async def fake_run(prompt: str, **kwargs) -> CliResult:
        calls.append({"prompt": prompt, **kwargs})
        return run()

    async def fake_ollama(prompt: str, **kwargs) -> CliResult:
        calls.append({"ollama": True, **kwargs})
        return CliResult(json.dumps(GOOD), None, 50)

    settings = OllamaSettings("http://localhost:11434", "qwen3.5:4b", "5m", 0.1, 8192)
    return (
        Analyst(
            cli_command="claude",
            disallowed_tools="Bash",
            workdir=Path("/tmp/value-ai-test"),
            ollama=settings if ollama or only else None,
            ollama_only=only,
            run=fake_run,
            ollama_run=fake_ollama,
            context=lambda symbol, now, n: AnalystContext(),
        ),
        calls,
    )


def test_a_cli_read_is_labelled_cli_and_runs_slim_from_the_workdir() -> None:
    analyst, calls = _analyst(lambda: CliResult(json.dumps(GOOD), None, 900, 0.01))
    out = asyncio.run(analyst.read(REQ, NOW))
    assert out.reply is not None and out.call.backend == "cli" and out.call.error is None
    assert out.call.prompt_version == "value-v1" and out.call.cost_usd == 0.01
    (call,) = calls
    assert call["cwd"] == Path("/tmp/value-ai-test") and call["slim"] is True
    assert call["usage_kind"] == "value_standard" and call["model"] == "claude-sonnet-4-6"


def test_a_failed_cli_falls_back_to_ollama_labelled_and_a_timeout_does_not() -> None:
    analyst, _ = _analyst(lambda: CliResult(None, "cli_error", 100), ollama=True)
    out = asyncio.run(analyst.read(REQ, NOW))
    assert out.reply is not None and out.call.backend == "ollama"
    assert out.call.model == "ollama:qwen3.5:4b"
    slow, calls = _analyst(lambda: CliResult(None, "timeout", 240000), ollama=True)
    out = asyncio.run(slow.read(REQ, NOW))
    assert out.reply is None and out.call.error == "timeout" and len(calls) == 1
    only, calls = _analyst(lambda: CliResult(None, "cli_error", 1), only=True)
    out = asyncio.run(only.read(REQ, NOW))
    assert out.call.backend == "ollama" and all(c.get("ollama") for c in calls)


def test_an_unreadable_reply_is_no_notes_with_the_error_named() -> None:
    analyst, _ = _analyst(lambda: CliResult("I think it is cheap.", None, 10))
    out = asyncio.run(analyst.read(REQ, NOW))
    assert out.reply is None and out.call.error == "unparseable"
    assert out.call.raw == "I think it is cheap."


def test_context_without_news_db_says_so(monkeypatch, tmp_path) -> None:
    import src.news.store.readonly as ro

    monkeypatch.setattr(ro, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    ro.reset_engine()
    assert gather("STDY", NOW, 5).unavailable == ["news"]
    ro.reset_engine()
