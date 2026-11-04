"""The VALUE NOTE (Part 6 Task 10, ruling 9): what the value book thinks of the names the wheel is
reviewing, as prompt text for the trade review, the roll review and ``/scan NAME``.

The renderer is pure; the reader is the wheel's read-only window onto value.db; the block reaches
a prompt and nothing else (the fence test lives in ``tests/test_value_fence.py``).
"""

from __future__ import annotations

import subprocess
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src.claude.ollama_runner as ollama_mod
from src.claude import runner, value_context
from src.claude.prompts.roll import build_roll_prompt
from src.claude.prompts.strategist import build_prompt
from src.common import value_text as vt
from src.common import value_view as vv
from src.common.config import get_config
from src.common.schemas import OptionRight, Strategy
from src.value.store import (
    ValueEffectiveRow,
    ValuePositionRow,
    ValueReevaluationRow,
    ValueTickerFileRow,
    value_session,
)
from tests.test_claude import _make_account, _make_candidate
from tests.test_dossier_readers import _alert, _pos, _quote
from tests.value_book_fixtures import NOW, order, ticker_file

NOW_AWARE = datetime(2026, 11, 5, 15, tzinfo=UTC)

BOTH = vt.ValueNoteView(
    symbol="GOOGL",
    lists=(
        vt.ListNote("deep_value", "WAIT", "python", 140.0, 140.0, 0.05, 130.0),
        vt.ListNote("quality_growth", "READY", "claude", 151.0, 180.0, 0.22, 148.0),
    ),
    held_shares=10.0,
    next_exit=("sell half at", 180.0),
    reevaluation=("major", "2026-11-03"),
)


def csp(cid: str, underlying: str):
    return _make_candidate(
        cid,
        strategy=Strategy.CASH_SECURED_PUT,
        underlying=underlying,
        strike=60.0,
        right=OptionRight.PUT,
    )


# --------------------------------------------------------------------------- #
# the renderer
# --------------------------------------------------------------------------- #


def test_the_note_names_both_lists_and_who_decided_each() -> None:
    text = vt.render_value_notes(["googl"], {"GOOGL": BOTH})
    lines = text.splitlines()
    assert lines[0] == "=== VALUE NOTE ==="
    assert lines[1] == "GOOGL  quality growth: READY (Claude) · deep value: WAIT (Python)"
    assert (
        "  quality growth: fair value $151.00 (Python) / $180.00 (effective, Claude's clamped)"
        " · margin 22% · value put ceiling $148.00"
    ) in lines
    assert (
        "  deep value: fair value $140.00 (Python) · margin 5% · value put ceiling $130.00" in lines
    )
    assert (
        "  value book holds 10 sh · next exit: sell half at $180.00 · "
        "re-evaluation open (major, 2026-11-03)"
    ) in lines


def test_unknown_numbers_print_n_a_never_zero() -> None:
    one = vt.ValueNoteView("MU", (vt.ListNote("deep_value", "WATCH", "python"),), held_shares=3.0)
    text = vt.render_value_notes(["MU"], {"MU": one})
    assert "  fair value n/a (Python) · margin n/a · value put ceiling n/a" in text
    assert "value book holds 3 sh" in text and "next exit" not in text
    assert "$0.00" not in text and " 0%" not in text


def test_the_rule_line_is_always_last() -> None:
    text = vt.render_value_notes(["GOOGL"], {"GOOGL": BOTH})
    assert text.splitlines()[-1] == vt.RULE_LINE
    assert "Context only. It never moves the Rules Engine" in vt.RULE_LINE
    many = {f"S{i}": vt.ValueNoteView(f"S{i}", BOTH.lists, 1.0) for i in range(40)}
    cut = vt.render_value_notes(list(many), many)
    assert cut.splitlines()[-1] == vt.RULE_LINE


def test_the_note_is_cut_at_2000_characters_on_a_name_boundary() -> None:
    many = {f"S{i}": vt.ValueNoteView(f"S{i}", BOTH.lists, 1.0, BOTH.next_exit) for i in range(40)}
    names = list(many)
    text = vt.render_value_notes(names, many)
    assert len(text) <= vt.MAX_CHARS
    shown = [ln for ln in text.splitlines() if ln.startswith("S") and "  " in ln[:6]]
    assert 0 < len(shown) < 40
    # every shown name is whole (header, two value lines, holding line) and the cut says how many
    assert text.count("value book holds") == len(shown)
    assert f"({40 - len(shown)} more names with value notes are not shown)" in text
    assert text.index(f"S{len(shown) - 1}  ") < text.index("more names")


def test_a_name_the_book_does_not_know_prints_nothing() -> None:
    assert vt.render_value_notes(["AAPL"], {"GOOGL": BOTH}) == ""
    assert vt.render_value_notes([], {"GOOGL": BOTH}) == ""
    assert vt.render_name(vt.ValueNoteView("AAPL")) == ""
    text = vt.render_value_notes(["AAPL", "GOOGL"], {"GOOGL": BOTH})
    assert "AAPL" not in text and "GOOGL" in text


# --------------------------------------------------------------------------- #
# the reader
# --------------------------------------------------------------------------- #


def _seed() -> None:
    order("GOOGL", filled=10)
    ticker_file("GOOGL", effective={"deep_value": ("WAIT", "python")})
    with value_session() as s:
        s.add(
            ValueEffectiveRow(
                symbol="GOOGL",
                list_name="quality_growth",
                as_of=date(2026, 11, 2),
                verdict="READY",
                decided_by="claude",
                python_verdict="WATCH",
                fair_value=180.0,
                entry_ceiling=148.0,
                margin_of_safety=0.22,
                updated_at=NOW,
            )
        )
        row = s.get(ValueTickerFileRow, "GOOGL")
        row.fair_value_growth = 151.0
        s.add(
            ValuePositionRow(
                symbol="GOOGL",
                list_name="quality_growth",
                status="open",
                opened_on=date(2026, 10, 1),
                plan_json='{"half_sold": false, "fair_value": 151.0, "effective_fair_value": 180.0}',
            )
        )
        s.flush()
        pid = s.query(ValuePositionRow).one().id
        s.add(
            ValueReevaluationRow(
                shadow_id=0,
                symbol="GOOGL",
                list_name="quality_growth",
                session=date(2026, 11, 3),
                last_session=date(2026, 11, 3),
                severity="major",
                triggers_json="[]",
                plan_before_json="{}",
                plan_after_json="{}",
                verdict_at_entry="READY",
                review_state="WEAKENED",
                ruleset_version="v4",
                ruleset_hash="be30d1eaa915",
                created_at=NOW,
                position_id=pid,
            )
        )


def test_read_notes_reads_the_effective_verdicts_holding_exit_and_reevaluation(
    value_book_db,
) -> None:
    _seed()
    notes = vv.read_notes(["googl", "AAPL"])
    assert notes is not None and set(notes) == {"GOOGL"}
    n = notes["GOOGL"]
    by = {x.list_name: x for x in n.lists}
    assert by["quality_growth"].verdict == "READY" and by["quality_growth"].decided_by == "claude"
    assert (by["quality_growth"].python_fair_value, by["quality_growth"].effective_fair_value) == (
        151.0,
        180.0,
    )
    assert by["quality_growth"].margin == 0.22 and by["quality_growth"].put_ceiling == 148.0
    assert by["deep_value"].verdict == "WAIT" and by["deep_value"].python_fair_value == 140.0
    assert n.held_shares == 10.0
    assert n.next_exit == ("sell half at", 180.0)
    assert n.reevaluation == ("major", "2026-11-03")
    text = vt.render_value_notes(["GOOGL"], notes)
    assert "quality growth: READY (Claude)" in text and "sell half at $180.00" in text


def test_read_notes_on_a_missing_file_is_none_and_the_block_is_absent(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(vv, "_path", lambda: tmp_path / "absent.db")
    assert vv.read_notes(["GOOGL"]) is None
    assert value_context.load_value_block(["GOOGL"], NOW_AWARE) is None


# --------------------------------------------------------------------------- #
# the prompts and the runners
# --------------------------------------------------------------------------- #

BLOCK = vt.render_value_notes(["GOOGL"], {"GOOGL": BOTH})


DOSSIER = "=== NAME NOTES ===\n--- QQQ ---"


def test_the_trade_prompt_carries_the_note_after_the_name_notes_and_before_the_candidates() -> None:
    prompt = build_prompt(
        [csp("c-1", "QQQ")], _make_account(), dossier_block=DOSSIER, value_block=BLOCK
    )
    assert BLOCK in prompt
    assert prompt.index("=== NAME NOTES ===") < prompt.index("=== VALUE NOTE ===")
    assert prompt.index("=== VALUE NOTE ===") < prompt.index("=== TRADE CANDIDATES ===")
    assert "VALUE NOTE" not in build_prompt([csp("c-1", "QQQ")], _make_account())


def test_the_roll_prompt_carries_the_note_before_the_system_proposal() -> None:
    roll = build_roll_prompt(
        _alert(), _pos(), _quote(), proposal="HOLD", dossier_block=DOSSIER, value_block=BLOCK
    )
    assert BLOCK in roll
    assert roll.index("=== NAME NOTES ===") < roll.index("=== VALUE NOTE ===")
    assert roll.index("=== VALUE NOTE ===") < roll.index("=== SYSTEM PROPOSAL ===")
    assert "VALUE NOTE" not in build_roll_prompt(_alert(), _pos(), _quote())


def _cli_cfg(backend: str):
    return SimpleNamespace(
        backend=backend,
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


def test_review_candidates_reads_the_note_and_passes_it_to_both_backends(value_book_db) -> None:
    _seed()
    seen_cli: list[str] = []
    seen_local: list[str] = []

    def cli_run(cmd, input=None, **kw):  # noqa: A002 - subprocess.run's own name
        seen_cli.append(input)
        return subprocess.CompletedProcess([], 1, stdout="", stderr="")

    with (
        patch.object(runner, "get_config") as get_cfg,
        patch.object(runner.subprocess, "run", side_effect=cli_run),
    ):
        get_cfg.return_value.claude = _cli_cfg("cli")
        runner.review_candidates([csp("c-1", "GOOGL")], _make_account())
    assert "=== VALUE NOTE ===" in seen_cli[0]
    assert "GOOGL  quality growth: READY (Claude) · deep value: WAIT (Python)" in seen_cli[0]
    assert seen_cli[0].index("=== VALUE NOTE ===") < seen_cli[0].index("=== TRADE CANDIDATES ===")

    with (
        patch.object(runner, "get_config") as get_cfg,
        patch.object(ollama_mod, "get_config") as ogc,
        patch.object(ollama_mod, "_generate", side_effect=lambda p, *a, **k: seen_local.append(p)),
    ):
        get_cfg.return_value.claude = _cli_cfg("ollama")
        ogc.return_value.claude = MagicMock(
            enabled=True,
            tool_research_enabled=False,
            ollama_timeout_seconds=60.0,
            tool_research_timeout_seconds=60.0,
            review_min_call_seconds=10.0,
        )
        runner.review_candidates([csp("c-1", "GOOGL")], _make_account())
    assert seen_local and "=== VALUE NOTE ===" in seen_local[0]
    assert "GOOGL  quality growth: READY (Claude)" in seen_local[0]


def test_the_note_is_off_when_the_config_says_so(value_book_db, monkeypatch) -> None:
    _seed()
    assert value_context.load_value_block(["GOOGL"], NOW_AWARE) is not None
    cfg = get_config()
    monkeypatch.setattr(cfg.value.prompt_note, "enabled", False)
    assert value_context.load_value_block(["GOOGL"], NOW_AWARE) is None
    seen: list[str] = []

    def cli_run(cmd, input=None, **kw):  # noqa: A002
        seen.append(input)
        return subprocess.CompletedProcess([], 1, stdout="", stderr="")

    with (
        patch.object(runner, "get_config") as get_cfg,
        patch.object(runner.subprocess, "run", side_effect=cli_run),
    ):
        get_cfg.return_value.claude = _cli_cfg("cli")
        runner.review_candidates([csp("c-1", "GOOGL")], _make_account())
    assert seen and "VALUE NOTE" not in seen[0]
