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
