"""Tests for the fence: the CLAUDE.md invariant that nothing under `src/claude/` (the
reasoning/enrichment layer) is importable from the deterministic engine, execution, or
strategies path.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# The fence — src/claude/ influences verdict + ranking ONLY
# --------------------------------------------------------------------------- #


def _engine_path_modules() -> list[str]:
    """Every module on the engine / execution / sizing path, by directory.

    Globbed rather than listed: the hand-maintained list this replaces went stale the moment
    the path grew a module (it never gained `engine/capital.py` — position sizing and the
    concentration caps — or `execution/circuit_breakers.py`, `profit_take.py`,
    `roll_pipeline.py`), and a fence test that silently stops covering new code is worse than
    no fence test. `src/strategies/` was already globbed here for exactly this reason.
    """
    root = Path(__file__).resolve().parents[1]
    dirs = ("engine", "execution", "strategies")
    return [
        str(p.relative_to(root))
        for d in dirs
        for p in sorted((root / "src" / d).rglob("*.py"))
        if p.name != "__init__.py"
    ]


def test_skills_never_reach_the_engine() -> None:
    """The risk engine, scoring, sizing, and execution must not import the learning-loop
    surface: `src/claude/eval/` (the outcome ledger's scoring/metrics) or `src/claude/skills/`
    (reasoning playbooks — deleted, but checked for regardless in case it returns).

    This is the structural guarantee behind CLAUDE.md's fence: "nothing in eval/ or skills/ is
    importable from, or reachable by, the engine/execution/sizing path." Checked broadly by
    prefix (`src.claude.eval`, `src.claude.skills`) rather than by specific function name, so
    this stays true regardless of what those packages grow to contain.

    Deliberately narrower than "nothing under src/claude/ at all": `src/claude/memory.py` is a
    documented, one-way exception — execution/approval code calls `record_outcome()` to log
    fill/rejection outcomes for *later scans* to read back into prompts (see its module
    docstring: "Neutral module ... so executor / approval / approval_service can all call it
    without import cycles"). That is execution informing Claude, never Claude influencing
    execution, so it is not a fence violation and must not make this test fail.
    """
    root = Path(__file__).resolve().parents[1]
    # All strategy files participate in sizing (contracts/collateral) too.
    targets = _engine_path_modules()
    forbidden_prefixes = ("src.claude.eval", "src.claude.skills")
    offenders = []
    for rel in targets:
        text = (root / rel).read_text(encoding="utf-8")
        if any(prefix in text for prefix in forbidden_prefixes):
            offenders.append(rel)
    assert not offenders, f"fence violated — eval/skills reachable from: {offenders}"


def test_fair_value_stays_in_the_deterministic_tier() -> None:
    """`analytics/fair_value.py` can influence ranking (the optional `zone_fit` weight feeds
    `technical_score`), so it sits on the deterministic side of the fence.

    That means it may read technicals, IV, fundamentals and Black-Scholes — and nothing else.
    Pulling in sentiment, macro, sector context, or anything under `src.claude` would route
    enrichment-tier signals (news tone, crowd sentiment, LLM output) into candidate scoring,
    which the fence forbids.
    """
    root = Path(__file__).resolve().parents[1]
    text = (root / "src" / "analytics" / "fair_value.py").read_text(encoding="utf-8")
    forbidden = ["sentiment", "sector_context", "market_conditions", "src.claude"]
    offenders = [
        token
        for token in forbidden
        # Only flag real imports, not the word appearing in prose/comments.
        if f"import {token}" in text or f"from src.analytics.{token}" in text
    ]
    assert not offenders, f"fence violated — fair_value imports enrichment-tier: {offenders}"


def test_scan_pipeline_does_not_import_the_notify_layer() -> None:
    """The Phase 5 API triggers scans; it must not drag Telegram in.

    `src/orchestrator/` is split three ways: `scan_progress.py` renders progress, `scan.py`
    orchestrates and sends, and `scan_pipeline.py` produces data only. Keeping the last of
    those free of `src.notify` is what lets a non-Telegram caller run a scan and read a
    `ScanResult` without pulling in the bot.
    """
    import ast

    root = Path(__file__).resolve().parents[1]
    source = (root / "src" / "orchestrator" / "scan_pipeline.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
    offenders = [m for m in imported if m.startswith("src.notify") or m == "telegram"]
    assert not offenders, f"scan_pipeline must not import the notify layer: {offenders}"


def test_macro_never_reaches_the_engine() -> None:
    """The macro backdrop (VIX term, rates, headline tone) is enrichment: it may reach the
    prompt and the Telegram card, never the gate, the weights, or sizing."""
    root = Path(__file__).resolve().parents[1]
    targets = _engine_path_modules()
    offenders = [
        rel for rel in targets if "market_conditions" in (root / rel).read_text(encoding="utf-8")
    ]
    assert not offenders, f"fence violated — macro reachable from: {offenders}"


_ENRICHMENT_ONLY = (
    "src.claude.news_context",
    "src.claude.ollama_tools",
    "src.data.google_news_backend",
    # Final review M2: the factory accessor and the Protocol are the other two ways in — a
    # `from src.data.factory import get_news_search_provider` names none of the modules above.
    "get_news_search_provider",
    "NewsSearchProvider",
)


def test_news_and_tool_research_never_reach_the_deterministic_layer() -> None:
    """Task 11's news-grounded review is enrichment only: the `=== NEWS ===` block
    (`src.claude.news_context`), the bounded tool-calling research turn
    (`src.claude.ollama_tools`), and their keyless data-layer backend
    (`src.data.google_news_backend`) may reach the strategist prompt and the local Ollama
    reviewer, never the risk engine, execution, or sizing (CLAUDE.md's fence)."""
    root = Path(__file__).resolve().parents[1]
    for pkg in ("src/engine", "src/execution", "src/strategies"):
        for rel in [
            str(p.relative_to(root))
            for p in sorted((root / pkg).rglob("*.py"))
            if p.name != "__init__.py"
        ]:
            text = (root / rel).read_text(encoding="utf-8")
            offenders = [mod for mod in _ENRICHMENT_ONLY if mod in text]
            assert not offenders, f"{rel} imports enrichment-only module(s): {offenders}"
