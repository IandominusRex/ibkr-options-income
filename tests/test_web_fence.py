"""The one-way import fence between the trading system and the web layer.

The web layer knows about the trading system. The trading system does not know the web layer
exists. See Web plan/P0-P1-design.md §4.7.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _modules_under(*dirs: str) -> list[str]:
    """Every non-init module under the given src/ subdirectories, globbed not listed.

    Globbed for the same reason tests/test_eval_skills.py globs: a hand-maintained list goes
    stale the moment the path grows a module, and a fence test that silently stops covering
    new code is worse than no fence test.
    """
    return [
        str(p.relative_to(ROOT))
        for d in dirs
        for p in sorted((ROOT / "src" / d).glob("*.py"))
        if p.name != "__init__.py"
    ]


def test_trading_path_never_imports_the_web_layer() -> None:
    offenders = [
        rel
        for rel in _modules_under("engine", "execution", "strategies")
        if any(
            token in (ROOT / rel).read_text(encoding="utf-8")
            for token in ("src.api", "src.research")
        )
    ]
    assert not offenders, f"fence violated — web layer reachable from: {offenders}"


def test_checks_engine_never_imports_the_summary_layer() -> None:
    """The AI summary is enrichment. It must not reach the deterministic checks engine."""
    checks_dir = ROOT / "src" / "research" / "checks"
    assert checks_dir.is_dir(), "checks package must exist for this fence to be meaningful"
    offenders = [
        str(p.relative_to(ROOT))
        for p in sorted(checks_dir.glob("*.py"))
        if "src.research.summary" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"fence violated — summary reachable from checks: {offenders}"


def test_research_schema_does_not_share_the_trading_base() -> None:
    """A shared Base would let create_all() build either schema against either engine."""
    text = (ROOT / "src" / "research" / "store" / "models.py").read_text(encoding="utf-8")
    assert "src.storage.models" not in text


def test_the_api_never_constructs_a_broker_connection() -> None:
    """No ib_async anywhere under src/api/ or src/research/: no clientId, no placeOrder path."""
    offenders = [
        str(p.relative_to(ROOT))
        for d in ("api", "research")
        for p in sorted((ROOT / "src" / d).rglob("*.py"))
        if "ib_async" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"web layer must hold no broker connection: {offenders}"


# ---------------------------------------------------------------------------
# M7 — the AI summary layer. It records itself and touches nothing else
# (Web plan/milestones/P0-P1/M7-ai-summary.md Task 7.5).
#
# These check for the import path ``src.research.summary`` rather than the plan's
# original bare "summary" substring: "summary" is already an ordinary word elsewhere in
# this codebase (``EODSummary``, ``execution/roll_executor.py``'s ``_leg_fill_summary``,
# and this very file's own fence-documentation comments), so a bare substring check
# false-positives on code that never touches the AI summary layer. The import path is
# the actual enforceable invariant and is what test_checks_engine_never_imports_the_
# summary_layer above already uses.
# ---------------------------------------------------------------------------


def test_the_checks_engine_never_imports_the_summary_layer() -> None:
    """Already covered above, but the summary package now has real content (M7)."""
    offenders = [
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "src" / "research" / "checks").glob("*.py"))
        if "src.research.summary" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"summary reachable from checks: {offenders}"


def test_the_summary_layer_never_writes_to_any_database_but_its_own() -> None:
    """The summary is enrichment. It records itself and touches nothing else."""
    forbidden = ("src.storage", "trading_db", "risk_limits", "scoring_weights")
    offenders = [
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "src" / "research" / "summary").rglob("*.py"))
        if any(token in p.read_text(encoding="utf-8") for token in forbidden)
    ]
    assert not offenders, f"summary layer reached beyond its bounds: {offenders}"


def test_no_summary_output_reaches_a_scoring_or_sizing_path() -> None:
    offenders = [
        rel
        for rel in _modules_under("engine", "execution", "strategies")
        if "src.research.summary" in (ROOT / rel).read_text(encoding="utf-8")
    ]
    assert not offenders, f"summary reachable from the engine path: {offenders}"


def test_the_recommendations_route_does_not_rescore() -> None:
    """The site and Telegram must never disagree about what the system thinks."""
    text = (ROOT / "src" / "api" / "routers" / "research.py").read_text(encoding="utf-8")
    assert "generate_buy_candidates" not in text
    assert "blended_score" not in text or "=" not in text.split("blended_score")[1][:3]
