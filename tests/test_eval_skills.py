"""Tests for the skill loop + the fence.

The fence test is the load-bearing one: it proves promoted skills can reach the reasoning
prompts but NOT the risk engine, scoring, or sizing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.common.schemas import SkillProposal


@pytest.fixture
def skills_dirs(tmp_path, monkeypatch):
    """Point the registry at throwaway skill directories."""
    import src.claude.skills.registry as reg

    root = tmp_path / "skills"
    monkeypatch.setattr(reg, "SKILLS_DIR", root)
    monkeypatch.setattr(reg, "ACTIVE_DIR", root / "active")
    monkeypatch.setattr(reg, "PROPOSED_DIR", root / "proposed")
    monkeypatch.setattr(reg, "REJECTED_DIR", root / "rejected")
    return reg


def _proposal(name: str = "prefer-high-ivr") -> SkillProposal:
    return SkillProposal(
        name=name,
        description="Lean to wait on thin-IVR CSPs.",
        body="When IVR < 30, bias the recommendation toward wait and lower priority.",
        rationale="Thin-IVR sells underperformed in the ledger.",
        supporting_stats={"n": 12},
    )


def test_propose_review_promote_render(skills_dirs) -> None:
    reg = skills_dirs
    reg.save_proposal(_proposal())

    assert [s.name for s in reg.list_proposed()] == ["prefer-high-ivr"]
    assert reg.load_active_skills() == []
    assert reg.render_active_skills() == ""  # nothing active yet

    assert reg.promote("prefer-high-ivr") is True
    active = reg.load_active_skills()
    assert [s.name for s in active] == ["prefer-high-ivr"]
    assert reg.list_proposed() == []

    rendered = reg.render_active_skills()
    assert "prefer-high-ivr" in rendered
    assert "bias the recommendation toward wait" in rendered
    assert "verdict + ranking only" in rendered  # the fence is stated in the injected block


def test_reject_and_retire(skills_dirs) -> None:
    reg = skills_dirs
    reg.save_proposal(_proposal("draft-one"))
    assert reg.reject("draft-one") is True
    assert reg.list_proposed() == []
    assert (reg.REJECTED_DIR / "draft-one.md").exists()

    reg.save_proposal(_proposal("draft-two"))
    reg.promote("draft-two")
    assert reg.retire("draft-two") is True
    assert reg.load_active_skills() == []
    assert [s.name for s in reg.list_proposed()] == ["draft-two"]


def test_skill_injected_into_strategist_prompt(skills_dirs, monkeypatch) -> None:
    from datetime import date, timedelta

    from src.claude.prompts.strategist import build_prompt
    from src.common.schemas import (
        AccountSnapshot,
        OptionRight,
        ScoreCard,
        Strategy,
        TradeCandidate,
    )

    skills_dirs.save_proposal(_proposal())
    skills_dirs.promote("prefer-high-ivr")

    cand = TradeCandidate(
        candidate_id="x",
        strategy=Strategy.COVERED_CALL,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date.today() + timedelta(days=30),
        premium=1.5,
        collateral=18500.0,
        roc_pct=0.8,
        annualized_yield_pct=10.0,
        breakeven=183.5,
        dte=30,
        scores=ScoreCard(symbol="AAPL"),
        blended_score=80.0,
    )
    account = AccountSnapshot(
        account="DU1",
        net_liquidation=100_000.0,
        total_cash=50_000.0,
        buying_power=80_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=70_000.0,
    )

    prompt = build_prompt([cand], account)
    assert "ACTIVE REASONING SKILLS" in prompt
    assert "bias the recommendation toward wait" in prompt


def test_skills_disabled_config_suppresses_injection(skills_dirs, monkeypatch) -> None:
    from src.claude.prompts.strategist import _active_skills_block
    from src.common.config import get_config

    skills_dirs.save_proposal(_proposal())
    skills_dirs.promote("prefer-high-ivr")

    monkeypatch.setattr(get_config().claude, "skills_enabled", False)
    assert _active_skills_block() == ""


# --------------------------------------------------------------------------- #
# The fence — skills influence verdict + ranking ONLY
# --------------------------------------------------------------------------- #
_ENGINE_PATH_MODULES = [
    "src/engine/risk_engine.py",
    "src/engine/scoring.py",
    "src/engine/decision_engine.py",
    "src/execution/order_builder.py",
    "src/execution/executor.py",
    "src/execution/approval.py",
]


def test_skills_never_reach_the_engine() -> None:
    """The risk engine, scoring, sizing, and execution must not import or render skills.

    This is the structural guarantee behind CLAUDE.md's fence: a skill can change what Claude
    recommends, never what the deterministic layer gates, sizes, or sends.
    """
    root = Path(__file__).resolve().parents[1]
    # All strategy files participate in sizing (contracts/collateral) too.
    targets = list(_ENGINE_PATH_MODULES) + [
        str(p.relative_to(root)) for p in (root / "src" / "strategies").glob("*.py")
    ]
    offenders = []
    for rel in targets:
        text = (root / rel).read_text(encoding="utf-8")
        if "claude.skills" in text or "render_active_skills" in text:
            offenders.append(rel)
    assert not offenders, f"fence violated — skills reachable from: {offenders}"


def test_render_active_skills_only_imported_by_prompt_builders() -> None:
    """`render_active_skills` (the injection function) is referenced only by the prompt
    builders — the single, auditable path skills take to Claude."""
    root = Path(__file__).resolve().parents[1] / "src"
    importers = {
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if "render_active_skills" in p.read_text(encoding="utf-8")
        and p.name != "registry.py"  # the definition lives here
    }
    assert importers <= {"claude/prompts/strategist.py", "claude/prompts/roll.py"}, importers
