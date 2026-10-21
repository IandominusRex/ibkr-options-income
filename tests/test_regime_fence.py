"""The regime / size-cut fence (market-picture spec sections 9 and 12; CLAUDE.md).

Three promises, each checked by parsing imports and assignments rather than by grepping text:

* the deterministic regime, ladder and sizing modules never read the enrichment tier (a sentiment,
  macro or news term there would let news tone reject or resize a trade);
* the engine / strategies / execution path imports nothing from the reasoning layer or the news
  package; and
* the one narrow exception to "no LLM value reaches the broker" really is narrow: Claude's
  `max_contracts` reaches a contract count only through `engine.regime_limits.claude_cut`, the
  spreads book cannot reach the regime limits, and the news process only ever reads the regime
  record, never writes it.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.test_spreads_fence import imported_modules

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# The enrichment tier and the reasoning layer: none of it may feed the deterministic modules.
ENRICHMENT = (
    "src.claude",
    "src.news",
    "src.spreads_ai",
    "src.analytics.market_conditions",
    "src.analytics.sentiment",
    "src.analytics.sector_context",
)
# The deterministic regime, ladder and sizing modules (the plan's Global Constraints list).
# `breakout.py` arrives with the covered-call timing work; it is picked up when it exists.
DETERMINISTIC = sorted(
    {
        *(
            SRC / "analytics" / f"{n}.py"
            for n in (
                "regime",
                "support_levels",
                "scale_in",
                "bottoming",
                "seasonality",
                "breakout",
            )
        ),
        *(SRC / "regime").glob("*.py"),
        SRC / "storage" / "regime_state.py",
        SRC / "engine" / "regime_limits.py",
    }
)


def _reaches(modules: set[str], prefix: str) -> bool:
    return any(m == prefix or m.startswith(prefix + ".") for m in modules)


def test_the_deterministic_list_is_not_empty_and_exists() -> None:
    existing = [p for p in DETERMINISTIC if p.exists()]
    assert len(existing) >= 9, "the fence must cover the regime modules it names"
    for must in ("regime.py", "scale_in.py", "regime_limits.py", "regime_state.py", "context.py"):
        assert any(p.name == must for p in existing), must


def test_regime_modules_never_import_enrichment() -> None:
    offenders = [
        f"{p.relative_to(ROOT)} -> {m}"
        for p in DETERMINISTIC
        if p.exists()
        for m in ENRICHMENT
        if _reaches(imported_modules(p), m)
    ]
    assert offenders == []


def test_engine_still_imports_nothing_from_claude_or_news() -> None:
    offenders: list[str] = []
    for pkg in ("engine", "strategies"):
        for p in sorted((SRC / pkg).rglob("*.py")):
            mods = imported_modules(p)
            offenders += [
                f"{p.relative_to(ROOT)} -> {m}"
                for m in ("src.claude", "src.news", "src.spreads_ai")
                if _reaches(mods, m)
            ]
    # Execution has one documented, one-way exception: it records fill outcomes for later scans
    # through src.claude.memory (execution informs Claude; nothing flows back).
    for p in sorted((SRC / "execution").rglob("*.py")):
        mods = imported_modules(p)
        offenders += [
            f"{p.relative_to(ROOT)} -> {m}"
            for m in sorted(mods)
            if (_reaches({m}, "src.claude") and not _reaches({m}, "src.claude.memory"))
            or _reaches({m}, "src.news")
            or _reaches({m}, "src.spreads_ai")
        ]
    assert offenders == []


def _calls_claude_cut(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "claude_cut"
    )


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def test_claude_cut_is_the_only_llm_value_reaching_contracts() -> None:
    """In the auto branch (src/notify/sender.py) a review's ``max_contracts`` is read in exactly
    one way, as an argument to ``claude_cut``, and every write of a candidate's ``contracts`` takes
    its value from a name that ``claude_cut`` produced."""
    path = SRC / "notify" / "sender.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = _parents(tree)

    # 1. Every read of `.max_contracts` is an argument of a claude_cut(...) call.
    reads = [
        n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "max_contracts"
    ]
    assert reads, "the auto branch no longer reads the review's size suggestion"
    for node in reads:
        parent = parents[node]
        assert _calls_claude_cut(parent) and node in parent.args, ast.unparse(parent)

    # 2. Every write of `contracts` (a model_copy update key or an attribute assignment) comes
    #    from a plain name whose only assignment in its function is claude_cut(...).
    def assigned_from_claude_cut(name: str, scope: ast.AST) -> bool:
        values = [
            n.value
            for n in ast.walk(scope)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
        ]
        return bool(values) and all(_calls_claude_cut(v) for v in values)

    def enclosing_function(node: ast.AST) -> ast.AST:
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                return node
        return tree

    writes: list[tuple[ast.AST, ast.AST]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "contracts":
                    writes.append((node, value))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == "contracts":
                    writes.append((node, node.value))
    assert writes, "the auto branch no longer writes a cut size"
    for node, value in writes:
        assert isinstance(value, ast.Name), ast.unparse(node)
        assert assigned_from_claude_cut(value.id, enclosing_function(node)), ast.unparse(node)


def test_no_module_outside_the_sender_and_its_card_reads_a_reviews_size_suggestion() -> None:
    """The review's size fields reach exactly two places: the auto branch (the cut) and the card
    line that shows the suggestion (which asks ``claude_cut`` whether it would be honoured)."""
    allowed = {SRC / "notify" / "sender.py", SRC / "notify" / "formatters.py"}
    spreads = (SRC / "spreads", SRC / "spreads_ai")  # a separate system with its own sizing
    offenders = []
    for p in sorted(SRC.rglob("*.py")):
        if p in allowed or any(s in p.parents for s in spreads):
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("max_contracts", "size_reason"):
                # The engine's own capital function and the config key share the name; only an
                # attribute read of a review matters, and none exists outside the two files.
                offenders.append(f"{p.relative_to(ROOT)}:{node.lineno} .{node.attr}")
    assert offenders == []


def test_spreads_sizing_cannot_reach_regime_limits() -> None:
    offenders = []
    for pkg in ("spreads", "spreads_ai"):
        for p in sorted((SRC / pkg).rglob("*.py")):
            mods = imported_modules(p)
            offenders += [
                f"{p.relative_to(ROOT)} -> {m}"
                for m in ("src.engine.regime_limits", "src.regime", "src.storage.regime_state")
                if _reaches(mods, m)
            ]
    assert offenders == []


_REGIME_WRITERS = {
    "save_regime_state",
    "update_regime_state",
    "suspend_regime",
    "resume_regime",
    "mark_changes_sent",
}


def test_news_reads_only_regime_state_and_portfolio_snapshots_from_storage() -> None:
    offenders: list[str] = []
    for p in sorted((SRC / "news").rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for m in imported_modules(p):
            if m == "src.storage" or m.startswith("src.storage."):
                ok = m in (
                    "src.storage.regime_state",
                    "src.storage.portfolio_snapshots",
                ) or m.startswith(("src.storage.regime_state.", "src.storage.portfolio_snapshots."))
                if not ok:
                    offenders.append(f"{p.relative_to(ROOT)} imports {m}")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.Name):
                names = [node.id]
            elif isinstance(node, ast.Attribute):
                names = [node.attr]
            else:
                continue
            for name in names:
                if name in _REGIME_WRITERS:
                    offenders.append(f"{p.relative_to(ROOT)}:{node.lineno} uses {name}")
    assert offenders == []


def test_the_fence_catches_what_it_claims_to(tmp_path) -> None:
    """The checkers themselves: a planted violation is seen, a clean file is not."""
    bad = tmp_path / "bad.py"
    bad.write_text("from src.analytics.sentiment import SentimentScorer\nimport src.news.store\n")
    mods = imported_modules(bad, "tmp.bad")
    assert _reaches(mods, "src.analytics.sentiment") and _reaches(mods, "src.news")
    good = tmp_path / "good.py"
    good.write_text("from src.common.schemas import MarketRegime\n")
    assert not any(_reaches(imported_modules(good, "tmp.good"), m) for m in ENRICHMENT)
