"""Task 19: the trade, roll and ``/scan`` reviews read each name's dossier.

The news process writes the dossiers; the Claude-side prompts only read them (news.db,
read-only). The full-scan review gets a compact note for each reviewed name (capped, in candidate
priority order); a ``/scan TICKER`` deep-dive and a roll review get the full note for their one
name. The notes are enrichment: they reach prompt text and the review-reuse fingerprint, nothing
else. A review is reused only while the prose and events it read are unchanged; the hourly
numbers refresh does not count.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import src.claude.ollama_runner as ollama_mod
from src.claude import runner
from src.claude.dossier_context import dossier_block, load_dossiers, prose_key
from src.claude.prompts.roll import build_roll_prompt
from src.claude.prompts.strategist import build_prompt
from src.common.config import get_config
from src.common.schemas import (
    DossierEvent,
    DossierFact,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RollAlert,
    Strategy,
)
from tests.test_claude import _make_account, _make_candidate
from tests.test_dossier_store import dossier, save

NOW = datetime(2026, 10, 22, 15, tzinfo=UTC)
STALENESS = 26.0


def csp(cid: str, underlying: str):
    return _make_candidate(
        cid,
        strategy=Strategy.CASH_SECURED_PUT,
        underlying=underlying,
        strike=60.0,
        right=OptionRight.PUT,
    )


# --------------------------------------------------------------------------- #
# the reader
# --------------------------------------------------------------------------- #


def test_load_dossiers_reads_the_latest_per_name(news_db) -> None:
    save(dossier("META", NOW - timedelta(hours=3), story="old"))
    save(dossier("META", NOW, story="new"))
    save(dossier("AMD", NOW))
    got = load_dossiers(["META", "AMD", "NVDA"])
    assert set(got) == {"META", "AMD"} and got["META"].story == "new"
    assert load_dossiers([]) == {}


def test_missing_news_db_gives_no_block_and_no_error() -> None:
    # no news_db fixture: there is no news.db file to open
    assert load_dossiers(["META"]) == {}
    assert dossier_block(["META"], {}, now=NOW, compact=True, max_names=8) == ""


def test_a_reader_that_blows_up_never_raises(monkeypatch) -> None:
    import src.claude.dossier_context as dc

    def boom():
        raise RuntimeError("db on fire")

    monkeypatch.setattr(dc, "read_only_session", boom)
    assert dc.load_dossiers(["META"]) == {}


def test_dossier_block_caps_and_says_how_many_were_cut() -> None:
    names = [f"N{i}" for i in range(10)]
    notes = {n: dossier(n, NOW) for n in names}
    block = dossier_block(names, notes, now=NOW, compact=True, max_names=3)
    assert block.startswith("=== NAME NOTES ===")
    for n in names[:3]:
        assert f"--- {n} (stock" in block
    for n in names[3:]:
        assert f"--- {n} " not in block
    assert block.splitlines()[-1] == "(7 more names without notes in this prompt)"
    assert "more name" not in dossier_block(names[:3], notes, now=NOW, compact=True, max_names=3)


def test_dossier_block_lists_each_name_once_and_marks_those_without_notes() -> None:
    notes = {"META": dossier("META", NOW)}
    block = dossier_block(["meta", "META", "AMD"], notes, now=NOW, compact=True, max_names=8)
    assert block.count("--- META (stock") == 1
    assert "--- meta" not in block  # names are upper-cased before they are matched and listed
    assert "--- AMD --- (no notes yet)" in block
    assert dossier_block([], notes, now=NOW, compact=True, max_names=8) == ""
    assert dossier_block(["AMD"], {}, now=NOW, compact=True, max_names=8) == ""  # nothing at all


def test_old_prose_is_labelled_stale_by_the_configured_age(monkeypatch) -> None:
    notes = {"META": dossier("META", NOW, prose_at=NOW - timedelta(hours=30))}
    block = dossier_block(["META"], notes, now=NOW, compact=True, max_names=8)
    assert "PROSE IS STALE (built Oct 21 05:00 ET)" in block
    monkeypatch.setattr(get_config().news.dossier, "staleness_hours", 48.0)
    assert "PROSE IS STALE" not in dossier_block(
        ["META"], notes, now=NOW, compact=True, max_names=8
    )


def test_compact_and_full_blocks_differ_as_the_renderer_says() -> None:
    notes = {"META": dossier("META", NOW)}
    compact = dossier_block(["META"], notes, now=NOW, compact=True, max_names=8)
    full = dossier_block(["META"], notes, now=NOW, compact=False, max_names=8)
    assert "Profile (Claude's summary, general knowledge)" not in compact
    assert "Profile (Claude's summary, general knowledge)" in full


# --------------------------------------------------------------------------- #
# the key a reused review depends on
# --------------------------------------------------------------------------- #


def test_prose_key_tracks_prose_and_events_not_the_hourly_numbers() -> None:
    base = dossier("META", NOW)
    refreshed = base.model_copy(
        update={
            "version": "META@later",
            "facts_at": NOW + timedelta(hours=1),
            "facts": [DossierFact(id="META:F1", label="RSI14", display="RSI 70")],
            "sentiment_7d": -0.4,
            "health": "weak",
        }
    )
    assert prose_key(base) == prose_key(refreshed)
    assert prose_key(None) is None
    # new prose, a new event, a moved event date: each changes the key
    assert prose_key(base) != prose_key(base.model_copy(update={"prose_at": NOW}))
    new_event = DossierEvent(
        id="META:E2", title="x", on=date(2026, 11, 2), evidence="C1", quote="Nov 2"
    )
    assert prose_key(base) != prose_key(
        base.model_copy(update={"events": [*base.events, new_event]})
    )
    moved = base.events[0].model_copy(update={"on": date(2026, 10, 30)})
    assert prose_key(base) != prose_key(base.model_copy(update={"events": [moved]}))
    # a failed rebuild flips the stale label the model reads
    assert prose_key(base) != prose_key(base.model_copy(update={"stale": True}))
    # the order of the events does not matter
    two = [*base.events, new_event]
    assert prose_key(base.model_copy(update={"events": two})) == prose_key(
        base.model_copy(update={"events": list(reversed(two))})
    )
    assert prose_key(dossier("META", NOW, prose_at=None)) != prose_key(base)


def test_fingerprint_changes_with_new_prose_or_events() -> None:
    from src.orchestrator.scan import _candidates_review_hash, _review_fingerprint

    c = csp("c-1", "META")
    base = dossier("META", NOW)
    key = prose_key(base)
    a = _review_fingerprint(c, 15.0, dossier_key=key)
    assert a == _review_fingerprint(c, 15.0, dossier_key=key)
    assert a["dossier"] == key
    assert a != _review_fingerprint(
        c, 15.0, dossier_key=prose_key(base.model_copy(update={"prose_at": NOW}))
    )
    assert a != _review_fingerprint(c, 15.0, dossier_key=None)
    # the existing callers that pass no key are unchanged: no dossier is the same as None
    assert _review_fingerprint(c, 15.0) == _review_fingerprint(c, 15.0, dossier_key=None)
    h1 = _candidates_review_hash([c], 15.0, dossier_keys={"META": key})
    h2 = _candidates_review_hash(
        [c], 15.0, dossier_keys={"META": prose_key(base.model_copy(update={"prose_at": NOW}))}
    )
    assert h1 != h2 and h1 == _candidates_review_hash([c], 15.0, dossier_keys={"META": key})
    assert _candidates_review_hash([c], 15.0) == _candidates_review_hash([c], 15.0, dossier_keys={})


def test_fingerprint_ignores_the_hourly_fact_refresh() -> None:
    from src.orchestrator.scan import _candidates_review_hash

    c = csp("c-1", "META")
    base = dossier("META", NOW)
    refreshed = base.model_copy(
        update={
            "version": "META@later",
            "facts_at": NOW + timedelta(hours=1),
            "facts": [DossierFact(id="META:F1", label="RSI14", display="RSI 70")],
        }
    )
    assert _candidates_review_hash(
        [c], 15.0, dossier_keys={"META": prose_key(base)}
    ) == _candidates_review_hash([c], 15.0, dossier_keys={"META": prose_key(refreshed)})


# --------------------------------------------------------------------------- #
# the prompts
# --------------------------------------------------------------------------- #

BLOCK = "=== NAME NOTES ===\n--- QQQ (ETF · health n/a) ---\nStory: x"


def test_the_trade_prompt_places_the_notes_before_the_candidates_and_states_the_rule() -> None:
    prompt = build_prompt(
        [csp("c-1", "QQQ")],
        _make_account(),
        picture_block="=== MARKET PICTURE ===\nSPY: normal",
        book_block="=== YOUR BOOK ===\nnothing open",
        dossier_block=BLOCK,
    )
    assert BLOCK in prompt
    assert prompt.index("=== MARKET PICTURE ===") < prompt.index("=== NAME NOTES ===")
    assert prompt.index("=== NAME NOTES ===") < prompt.index("=== TRADE CANDIDATES ===")
    assert "NAME NOTES give each name's situation." in prompt
    assert "Cite their ids (META:F3, META:E1, C#) like other facts." in prompt
    assert "A profile is general knowledge, never the only reason for a verdict." in prompt


def test_a_trade_prompt_without_notes_has_no_trace_of_them() -> None:
    prompt = build_prompt([csp("c-1", "QQQ")], _make_account())
    assert "NAME NOTES" not in prompt
    assert prompt == build_prompt([csp("c-1", "QQQ")], _make_account(), dossier_block=None)
    assert prompt == build_prompt([csp("c-1", "QQQ")], _make_account(), dossier_block="")


def test_the_deep_dive_prompt_gets_the_notes_too() -> None:
    prompt = build_prompt(
        [csp("c-1", "QQQ")], _make_account(), single_ticker=True, dossier_block=BLOCK
    )
    assert BLOCK in prompt and prompt.index("=== NAME NOTES ===") < prompt.index(
        "=== TRADE CANDIDATES ==="
    )


def _alert() -> RollAlert:
    return RollAlert(
        position_symbol="TQQQ 78P", underlying="TQQQ", trigger="delta_drift", detail="delta 0.62"
    )


def _pos() -> PositionSnapshot:
    return PositionSnapshot(
        symbol="TQQQ 78P",
        sec_type="OPT",
        position=-10,
        avg_cost=1.2,
        right=OptionRight.PUT,
        strike=78.0,
        expiry=date(2026, 10, 30),
        underlying="TQQQ",
        delta=-0.3,
    )


def _quote() -> OptionQuote:
    return OptionQuote(
        underlying="TQQQ",
        right=OptionRight.PUT,
        strike=78.0,
        expiry=date(2026, 10, 30),
        bid=2.0,
        ask=2.2,
        delta=-0.6,
        iv=0.8,
    )


def test_the_roll_prompt_has_the_notes_before_the_proposal_and_still_only_agrees() -> None:
    prompt = build_roll_prompt(
        _alert(), _pos(), _quote(), proposal="ROLL 78P -> 72P", dossier_block=BLOCK
    )
    assert BLOCK in prompt
    assert prompt.index("=== NAME NOTES ===") < prompt.index("=== SYSTEM PROPOSAL ===")
    assert "You may not change it" in prompt
    assert "NAME NOTES" not in build_roll_prompt(_alert(), _pos(), _quote())


def test_ticker_scan_and_roll_prompts_have_full_notes(news_db) -> None:
    """The roll runners read the rolled name's dossier themselves and show it in full (an
    explicit block wins; an explicit empty one means none)."""
    save(dossier("TQQQ", datetime.now(UTC), kind="leveraged_etf", health="n/a", health_why=[]))
    cfg = SimpleNamespace(enabled=True, backend="cli", model_for=lambda kind: "")
    seen: list[str] = []

    def capture(prompt, *a, **k):
        seen.append(prompt)
        return None, "cli_error"

    with (
        patch.object(runner, "get_config") as get_cfg,
        patch.object(runner, "_run_cli_outcome", side_effect=capture),
        patch.object(runner, "_build_cmd", return_value=["claude"]),
    ):
        get_cfg.return_value.claude = cfg
        runner.review_roll(_alert(), _pos(), _quote(), proposal="HOLD")
        runner.review_roll(_alert(), _pos(), _quote(), dossier_block="EXPLICIT NOTES")
        runner.review_roll(_alert(), _pos(), _quote(), dossier_block="")
    assert "--- TQQQ (leveraged ETF · health n/a) ---" in seen[0]
    assert "Profile (Claude's summary, general knowledge)" in seen[0]  # the full rendering
    assert "EXPLICIT NOTES" in seen[1] and "--- TQQQ" not in seen[1]
    assert "NAME NOTES" not in seen[2] and "--- TQQQ" not in seen[2]

    ollama_seen: list[str] = []

    def answer(prompt, cfg, schema=None):
        ollama_seen.append(prompt)
        return json.dumps(
            {
                "position_symbol": "TQQQ 78P",
                "recommendation": "hold",
                "roll_target": "",
                "rationale": "r",
                "risks": "k",
            }
        )

    with (
        patch.object(ollama_mod, "get_config") as ogc,
        patch.object(ollama_mod, "_generate", side_effect=answer),
    ):
        ogc.return_value.claude = MagicMock(enabled=True)
        ollama_mod.review_roll(_alert(), _pos(), _quote(), dossier_block=BLOCK)
    assert BLOCK in ollama_seen[0]


def test_the_roll_fallback_to_ollama_carries_the_same_notes(news_db) -> None:
    save(dossier("TQQQ", datetime.now(UTC)))
    cfg = SimpleNamespace(enabled=True, backend="cli_then_ollama", model_for=lambda kind: "")
    with (
        patch.object(runner, "get_config") as get_cfg,
        patch.object(runner, "_review_roll_cli", return_value=(None, "usage_limit")) as cli,
        patch.object(runner, "should_fall_back", return_value=True),
        patch.object(ollama_mod, "review_roll", return_value=None) as local,
    ):
        get_cfg.return_value.claude = cfg
        runner.review_roll(_alert(), _pos(), _quote())
    assert "--- TQQQ" in cli.call_args.kwargs["dossier_block"]
    assert local.call_args.kwargs["dossier_block"] == cli.call_args.kwargs["dossier_block"]


def test_a_roll_review_with_no_news_db_has_no_notes() -> None:
    cfg = SimpleNamespace(enabled=True, backend="cli", model_for=lambda kind: "")
    seen: list[str] = []

    def capture(prompt, *a, **k):
        seen.append(prompt)
        return None, "cli_error"

    with (
        patch.object(runner, "get_config") as get_cfg,
        patch.object(runner, "_run_cli_outcome", side_effect=capture),
        patch.object(runner, "_build_cmd", return_value=["claude"]),
    ):
        get_cfg.return_value.claude = cfg
        runner.review_roll(_alert(), _pos(), _quote())
    assert "NAME NOTES" not in seen[0]


def test_the_local_model_review_gets_the_notes_too() -> None:
    seen: dict = {}

    def fake_build(*args, **kwargs):
        seen.update(kwargs)
        return "p"

    with (
        patch.object(ollama_mod, "get_config") as ocfg,
        patch.object(ollama_mod, "build_prompt", side_effect=fake_build),
        patch.object(ollama_mod, "_generate", return_value=None),
    ):
        ocfg.return_value.claude = MagicMock(
            enabled=True,
            tool_research_enabled=False,
            ollama_timeout_seconds=60.0,
            tool_research_timeout_seconds=60.0,
            review_min_call_seconds=10.0,
        )
        ollama_mod.review_candidates(
            [_make_candidate("test-001")], _make_account(), dossier_block="NOTES"
        )
    assert seen["dossier_block"] == "NOTES"


def test_the_runners_pass_the_notes_into_the_prompt() -> None:
    seen: dict = {}

    def fake_build(*args, **kwargs):
        seen.update(kwargs)
        return "p"

    cfg = SimpleNamespace(
        backend="cli",
        enabled=True,
        max_retries=0,
        timeout_seconds=5.0,
        cli_command="claude",
        output_format="json",
        max_turns=1,
        model="",
        effort="",
        disallowed_tools="",
        slim_context=False,
        workdir="",
        model_for=lambda kind: "",
        review_reuse_minutes=0,
    )
    import subprocess

    with (
        patch.object(runner, "get_config") as get_cfg,
        patch.object(runner, "build_prompt", side_effect=fake_build),
        patch.object(
            runner.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, stdout="", stderr=""),
        ),
    ):
        get_cfg.return_value.claude = cfg
        runner.review_candidates(
            [_make_candidate("test-001")], _make_account(), dossier_block="NOTES"
        )
    assert seen["dossier_block"] == "NOTES"


# --------------------------------------------------------------------------- #
# the scans
# --------------------------------------------------------------------------- #


def test_trade_review_prompt_has_compact_notes_for_reviewed_names_only(news_db) -> None:
    import src.orchestrator.scan as scanmod

    now = datetime.now(UTC)
    for name in ("META", "NVDA", "AMD"):
        save(dossier(name, now))
    top = [csp("c1", "NVDA"), csp("c2", "META"), csp("c3", "NVDA")]
    ctx = scanmod._build_review_context(top, [], None)
    block = ctx.dossier_block
    assert block.startswith("=== NAME NOTES ===")
    assert "--- NVDA (stock" in block and "--- META (stock" in block
    assert "AMD" not in block  # a dossier exists, but no AMD trade is being reviewed
    assert block.index("--- NVDA") < block.index("--- META")  # candidate priority order, once each
    assert block.count("--- NVDA") == 1
    assert "Profile (Claude's summary" not in block  # compact
    assert ctx.dossier_keys == {
        "NVDA": prose_key(dossier("NVDA", now)),
        "META": prose_key(dossier("META", now)),
    }


def test_notes_capped_at_max_names_in_priority_order(news_db, monkeypatch) -> None:
    import src.orchestrator.scan as scanmod

    monkeypatch.setattr(get_config().news.dossier, "max_names_in_review", 3)
    now = datetime.now(UTC)
    names = [f"N{i}" for i in range(10)]
    for n in names:
        save(dossier(n, now))
    top = [csp(f"c{i}", n) for i, n in enumerate(names)]
    ctx = scanmod._build_review_context(top, [], None)
    assert [n for n in names if f"--- {n} (" in ctx.dossier_block] == ["N0", "N1", "N2"]
    assert ctx.dossier_block.splitlines()[-1] == "(7 more names without notes in this prompt)"
    assert set(ctx.dossier_keys) == {"N0", "N1", "N2"}  # only what the model read keys the reuse


def test_a_review_context_without_a_news_db_has_no_notes() -> None:
    import src.orchestrator.scan as scanmod

    ctx = scanmod._build_review_context([csp("c1", "NVDA")], [], None)
    assert ctx.dossier_block == "" and ctx.dossier_keys == {}


async def test_full_scan_passes_the_compact_notes(tmp_path, monkeypatch, news_db) -> None:
    import src.orchestrator.scan as scanmod
    from tests.test_scan_review_executor import _db_setup, _stub_scan

    _db_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        get_config(),
        "universe",
        {"would_own": ["AAPL"], "actively_wheeling": ["AAPL"], "sectors": {"AAPL": "tech"}},
    )
    save(dossier("AAPL", datetime.now(UTC)))
    seen: dict = {}

    def capture(*args, **kwargs):
        seen.update(kwargs)
        return []

    _stub_scan(scanmod, monkeypatch, review_side_effect=capture)
    await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1")
    assert (
        "=== NAME NOTES ===" in seen["dossier_block"] and "--- AAPL (stock" in seen["dossier_block"]
    )
    assert "Profile (Claude's summary" not in seen["dossier_block"]


async def test_ticker_scan_passes_the_full_notes_for_its_one_name(
    tmp_path, monkeypatch, news_db
) -> None:
    import src.orchestrator.scan as scanmod
    from src.common.schemas import FundamentalStats, IVStats, TechnicalStats
    from tests.test_scan_review_executor import _account, _db_setup

    _db_setup(tmp_path, monkeypatch)
    save(dossier("AAPL", datetime.now(UTC)))
    save(dossier("MSFT", datetime.now(UTC)))
    cand = csp("t-1", "AAPL").model_copy(update={"contracts": 1})
    priced = SimpleNamespace(
        quotes=[],
        iv_stats=IVStats(symbol="AAPL"),
        tech_stats=TechnicalStats(symbol="AAPL", price=200.0),
        fund_stats=FundamentalStats(symbol="AAPL"),
        positions=[],
        account=_account(),
        stock_pos=None,
        is_held=False,
        csp_skip_reason=None,
        cc_passed=[],
        csp_passed=[cand],
        ticker_assessed=[],
    )
    monkeypatch.setattr(scanmod, "_price_and_gate_ticker", AsyncMock(return_value=priced))
    monkeypatch.setattr(
        "src.ibkr.contracts.qualify_stock_async", AsyncMock(return_value=MagicMock())
    )
    monkeypatch.setattr(scanmod, "generate_buy_candidates", lambda *a, **k: [])
    monkeypatch.setattr(scanmod, "get_sector_context", lambda symbol: None)
    monkeypatch.setattr(scanmod, "get_market_conditions", lambda: None)
    seen: dict = {}

    def capture(*args, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(scanmod, "review_candidates", capture)
    await scanmod.run_ticker_scan(
        MagicMock(), "AAPL", bot=AsyncMock(), chat_id="1", progress_msg_id=1
    )
    block = seen["dossier_block"]
    assert "--- AAPL (stock" in block and "MSFT" not in block
    assert "Profile (Claude's summary, general knowledge)" in block  # the full rendering
    assert seen["single_ticker"] is True


async def test_new_prose_makes_the_scan_review_fresh_but_the_hourly_refresh_does_not(
    tmp_path, monkeypatch, news_db
) -> None:
    from tests.test_scan_review_reuse import _db_setup, _stub_pipeline

    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod

    monkeypatch.setattr(get_config(), "universe", {"would_own": ["AAPL"], "sectors": {"AAPL": "t"}})
    counter = {"n": 0}
    _stub_pipeline(scanmod, monkeypatch, counter)
    now = datetime.now(UTC)
    first = dossier("AAPL", now - timedelta(hours=3), prose_at=now - timedelta(hours=4))
    save(first)

    async def scan() -> None:
        await scanmod.run_scan(MagicMock(), bot=object(), chat_id="1", intraday=True)

    await scan()
    await scan()
    assert counter["n"] == 1  # the second cycle reused the review

    # the hourly numbers refresh: same prose, new facts and version
    save(
        first.model_copy(
            update={
                "version": f"AAPL@{now.isoformat()}",
                "facts_at": now,
                "facts": [DossierFact(id="AAPL:F1", label="RSI14", display="RSI 33")],
            }
        ),
        built_at=now - timedelta(hours=1),
    )
    await scan()
    assert counter["n"] == 1  # still reused

    # new prose lands: the review is redone
    save(
        first.model_copy(
            update={
                "version": f"AAPL@{now.isoformat()}:prose",
                "facts_at": now,
                "prose_at": now,
                "story": "A different story.",
            }
        ),
        built_at=now,
    )
    await scan()
    assert counter["n"] == 2
