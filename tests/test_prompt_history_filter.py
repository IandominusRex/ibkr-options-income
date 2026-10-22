"""The strategist prompt no longer carries "YOUR PRIOR RECOMMENDATIONS" at all (spec decision 1:
memory is the state of the market, not a record of what the model said before).

This file used to hold the filter that kept that block to the reviewed candidates' own tickers
(in the AVGO review of 2026-10-15 the block was 47 rows over 18 other tickers, 48% of the prompt).
The block is gone, so the same intent - a prompt that is not padded with the model's own old
prose - is now asserted directly: there is no history parameter, and passing one is an error."""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from src.claude.prompts.strategist import build_prompt
from src.storage.models import ClaudeMemoryRow
from tests.test_claude import _make_account, _make_candidate


def _row(underlying: str, rationale: str = "x") -> ClaudeMemoryRow:
    return ClaudeMemoryRow(
        scan_date=date(2026, 10, 14),
        underlying=underlying,
        strategy_type="cash_secured_put",
        recommendation="sell",
        confidence=0.8,
        rationale=f"{rationale} {underlying}-only-text",
        outcome=None,
    )


def test_the_prompt_builder_takes_no_history() -> None:
    assert "history" not in inspect.signature(build_prompt).parameters


def test_passing_history_is_an_error_not_a_silent_no_op() -> None:
    """A caller that still passes the old memory rows must fail loudly, not be ignored."""
    with pytest.raises(TypeError):
        build_prompt(  # type: ignore[call-arg]
            [_make_candidate(underlying="AVGO")], _make_account(), history=[_row("AVGO")]
        )


def test_no_prior_recommendations_block_in_a_built_prompt() -> None:
    prompt = build_prompt([_make_candidate(underlying="AVGO")], _make_account())
    assert "PRIOR RECOMMENDATIONS" not in prompt and "outcome:" not in prompt


def test_the_candidate_block_is_the_only_per_name_text() -> None:
    prompt = build_prompt(
        [_make_candidate("a", underlying="AVGO"), _make_candidate("b", underlying="AMD")],
        _make_account(),
    )
    assert "--- Candidate 1 ---" in prompt and "--- Candidate 2 ---" in prompt
    assert "PRIOR RECOMMENDATIONS" not in prompt
