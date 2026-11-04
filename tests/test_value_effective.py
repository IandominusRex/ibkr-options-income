"""The effective verdict: Python's baseline, then Claude's call (value book spec §6.7)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.common.config import get_config
from src.value.effective import ClaudeOpinion, effective
from src.value.scorecard import build_scorecard
from tests.value_fixtures import AS_OF, financials, inputs

CFG = get_config().value
REVIEW = CFG.rules.margin_of_safety.review_above_pct
# Deep value: Python's fair value 46.85, required 25%, so Python's ceiling is 35.14.
CHEAP = build_scorecard(inputs(close=30.0), CFG)  # Python READY
DEAR = build_scorecard(inputs(close=40.0), CFG)  # Python WAIT (40 > 35.14)
SICK = build_scorecard(inputs(fin=financials(shares_diluted=[110, 104, 98, 92, 86])), CFG)
SOON = build_scorecard(inputs(close=30.0, next_earnings=AS_OF + timedelta(days=3)), CFG)


def _eff(card, verdict, fv, list_name="deep_value"):
    return effective(card, list_name, ClaudeOpinion(verdict, fv, 7), review_above_pct=REVIEW)


@pytest.mark.parametrize(
    ("card", "claude", "fv", "verdict", "by"),
    [
        (CHEAP, None, None, "READY", "python"),  # not read: Python only
        (CHEAP, "NO", 60.0, "NO", "claude"),  # Claude decides on a healthy name
        (DEAR, "READY", 60.0, "READY", "claude"),  # 40 <= 60 x 0.75 = 45: Claude lifts a WAIT
        (DEAR, "READY", 50.0, "WAIT", "claude"),  # 40 > 37.5: the margin applies to Claude's FV
        (CHEAP, "WAIT", 60.0, "WAIT", "claude"),  # Claude's WAIT stands though the price is in
        (CHEAP, "WATCH", 60.0, "WATCH", "claude"),
        (SOON, "READY", 60.0, "WATCH", "claude"),  # Python's timing gate applies on top
        (SICK, "READY", 60.0, "NO", "python"),  # a failed health gate is final
        (CHEAP, "READY", None, "READY", "python"),  # Claude's fair value unusable: baseline
    ],
)
def test_the_effective_verdict(card, claude, fv, verdict, by) -> None:
    opinion = None if claude is None else ClaudeOpinion(claude, fv, 7)
    out = effective(card, "deep_value", opinion, review_above_pct=REVIEW)
    assert (out.verdict, out.decided_by) == (verdict, by)


def test_claudes_fair_value_replaces_pythons_in_the_ceiling_and_the_margin() -> None:
    out = _eff(DEAR, "READY", 60.0)
    assert out.fair_value == 60.0 and out.entry_ceiling == pytest.approx(45.0)
    assert out.margin_of_safety == pytest.approx(1 / 3)
    assert out.python_verdict == "WAIT" and out.claude_verdict == "READY" and out.verdict_id == 7
    assert out.mos_review is False
    assert _eff(CHEAP, "READY", 90.0).mos_review is True  # a 67% margin goes to a human


def test_unknown_and_not_applicable_are_final() -> None:
    unknown = build_scorecard(inputs(yf_market_cap=6000.0), CFG)
    assert _eff(unknown, "READY", 60.0).verdict == "UNKNOWN"
    etf = build_scorecard(inputs(is_etf=True), CFG)
    assert _eff(etf, "READY", 60.0).verdict == "NOT_APPLICABLE"
