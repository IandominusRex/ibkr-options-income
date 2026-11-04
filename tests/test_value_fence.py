"""The value fence (value book spec §16): src/value/ is deterministic and its own system.

Imports are parsed with ``ast`` (tests/test_spreads_fence.py's parser), so ``from src import x``,
relative imports and ``importlib`` count.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.test_spreads_fence import _reaches, imported_modules

ROOT = Path(__file__).resolve().parents[1]
VALUE = sorted((ROOT / "src" / "value").rglob("*.py"))
# The pure modules: no I/O, so the API may compute a ticker file during a request (spec §6.9).
PURE = (
    "schemas",
    "metrics",
    "scores",
    "gates",
    "valuation",
    "timing",
    "scorecard",
    "rank",
    "funnel",
    "ruleset",
    "exits",
    "ranked",
    "report",
    "residuals",
    "reevaluate",
    "claude_valuation",
    "effective",
    "kill_triggers",
    "grounding",
    "risk",
    "sizing",
)

FORBIDDEN_FOR_VALUE = (
    "src.claude",
    "src.news",
    "src.value_ai",
    "src.spreads",
    "src.spreads_ai",
    "src.notify",
    "src.api",
    "src.engine",
    "src.execution",
    "src.strategies",
    "src.orchestrator",
    "src.monitor",
    "src.ledger",
    "src.reporting",
    "src.analytics.sentiment",
    "src.analytics.sector_context",
    "src.analytics.market_conditions",
)
RESEARCH_ALLOWED = ("src.research.ingest.concepts", "src.research.schemas")
ENRICHMENT = (
    "src.claude",
    "src.news",
    "src.value_ai",
    "src.spreads_ai",
    "src.analytics.sentiment",
    "src.analytics.sector_context",
    "src.analytics.market_conditions",
)


def test_the_value_package_exists() -> None:
    assert len(VALUE) >= 12, "the fence must cover the value package"


def test_value_imports_no_enrichment_and_no_other_system() -> None:
    offenders = [
        f"{p.relative_to(ROOT)} -> {m}"
        for p in VALUE
        for m in FORBIDDEN_FOR_VALUE
        if _reaches(imported_modules(p), m)
    ]
    assert offenders == []


def test_value_reads_research_only_through_concepts_and_schemas() -> None:
    offenders = []
    for p in VALUE:
        for m in imported_modules(p):
            if (m == "src.research" or m.startswith("src.research.")) and not any(
                m == ok or m.startswith(ok + ".") for ok in RESEARCH_ALLOWED
            ):
                offenders.append(f"{p.relative_to(ROOT)} -> {m}")
    assert offenders == []


def test_the_pure_modules_do_no_io() -> None:
    io_modules = (
        "sqlalchemy",
        "httpx",
        "requests",
        "yfinance",
        "src.data",
        "src.storage",
        "src.common.value_inputs",
        "src.value.store",
        "src.value.ticker_file",
    )
    offenders = []
    for name in PURE:
        p = ROOT / "src" / "value" / f"{name}.py"
        mods = imported_modules(p)
        offenders += [f"{name} -> {m}" for m in io_modules if _reaches(mods, m)]
        tree = ast.parse(p.read_text(encoding="utf-8"))
        offenders += [
            f"{name}:{n.lineno} open()"
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"
        ]
    assert offenders == []


def test_the_input_loader_imports_no_enrichment_and_no_value_code() -> None:
    for rel in (
        "src/common/value_inputs.py",
        "src/common/value_types.py",
        "src/common/value_universe.py",
        "src/common/value_ai_types.py",
    ):
        mods = imported_modules(ROOT / rel)
        bad = [m for m in (*ENRICHMENT, "src.value") if _reaches(mods, m)]
        assert bad == [], rel


def test_value_types_is_plain_pydantic() -> None:
    for name in ("value_types.py", "value_ai_types.py"):
        mods = imported_modules(ROOT / "src" / "common" / name)
        assert {m.split(".")[0] for m in mods} <= {"__future__", "datetime", "typing", "pydantic"}


def test_value_opens_no_sec_client() -> None:
    """The research worker owns every SEC fetch (spec §6.9): src/value reaches no data provider
    and no HTTP client."""
    offenders = [
        f"{p.relative_to(ROOT)} -> {m}"
        for p in VALUE
        for m in ("src.data", "httpx", "requests")
        if _reaches(imported_modules(p), m)
    ]
    assert offenders == []


def test_the_trading_path_never_imports_the_value_book() -> None:
    offenders = [
        f"{p.relative_to(ROOT)}"
        for pkg in (
            "engine",
            "execution",
            "strategies",
            "orchestrator",
            "monitor",
            "notify",
            "spreads",
            "news",
            "claude",
        )
        for p in sorted((ROOT / "src" / pkg).rglob("*.py"))
        if _reaches(imported_modules(p), "src.value")
    ]
    assert offenders == []


def test_value_commands_is_stdlib_only() -> None:
    mods = imported_modules(ROOT / "src" / "common" / "value_commands.py")
    assert {m.split(".")[0] for m in mods} <= {"__future__", "hashlib", "re", "datetime", "typing"}


def test_research_reaches_the_value_book_only_through_the_keep_fresh_file() -> None:
    """Review I4: the research sweep keeps held names fresh from a plain file. It imports no
    ``src.value`` and no ``value.db`` code, and ``src/value/`` opens no research store."""
    offenders = [
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "src" / "research").rglob("*.py"))
        if _reaches(imported_modules(p), "src.value")
    ]
    assert offenders == []
    keep = imported_modules(ROOT / "src" / "common" / "value_keep_fresh.py")
    stdlib = {"__future__", "json", "logging", "os", "collections", "pathlib"}
    assert {m.split(".")[0] for m in keep} <= stdlib | {"src"}
    assert not [m for m in keep if m.startswith("src.") and not m.startswith("src.common.config")]
    writes_research = [
        str(p.relative_to(ROOT))
        for p in VALUE
        if _reaches(imported_modules(p), "src.research.store")
    ]
    assert writes_research == []


def test_only_src_value_constructs_value_rows() -> None:
    rows = (
        "ValueTickerFileRow(",
        "ValueTickerHistoryRow(",
        "ValueRunRow(",
        "ValueShadowRow(",
        "ValueShadowLegRow(",
        "ValueShadowEventRow(",
        "ValueRankedRow(",
        "ValueReevaluationRow(",
        "ValueClaudeReadRow(",
        "ValueClaudeVerdictRow(",
        "ValueClaudeNoteRow(",
        "ValueKillTriggerRow(",
        "ValueClaudeFactRow(",
        "ValueEffectiveRow(",
        "ValueClaudeStateRow(",
        "ValueOrderRow(",
        "ValuePositionRow(",
        "ValueProposalRow(",
        "ValueFundingRow(",
        "ValueAttributionRow(",
        "ValueBookStateRow(",
    )
    offenders = []
    for p in [*(ROOT / "src").rglob("*.py"), *(ROOT / "scripts").rglob("*.py")]:
        if (ROOT / "src" / "value") in p.parents:
            continue
        text = p.read_text(encoding="utf-8")
        offenders += [f"{p.relative_to(ROOT)}: {r[:-1]}" for r in rows if r in text]
    assert offenders == []


def test_the_value_scorecard_loads_no_wheel_layer_even_transitively() -> None:
    probe = (
        "import json, sys\n"
        "import src.value.scorecard, src.value.store, src.value.ticker_file, src.value.funnel\n"
        "import src.value.exits, src.value.shadow, src.value.service, src.value.report\n"
        "import src.value.residuals, src.value.reevaluate\n"
        "import src.value.claude_valuation, src.value.effective, src.value.claude_verdicts\n"
        "import src.value.claude_reads\n"
        "import src.common.value_inputs, src.common.value_universe\n"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('src.'))))\n"
    )
    env = {**os.environ, "IBKR_CONFIG_USE_EXAMPLES": "1"}
    out = subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    )
    loaded = json.loads(out.stdout)
    bad = [
        m
        for m in loaded
        for f in (
            *FORBIDDEN_FOR_VALUE,
            "src.research.store.session",
            "src.research.ingest.fundamentals",
        )
        if m == f or m.startswith(f + ".")
    ]
    assert bad == []


def test_only_the_value_entrypoint_may_import_value_ai() -> None:
    """Spec §5/§16: scripts/run_value.py is the only importer of src.value_ai (Part 4)."""
    outside = [
        p for p in (ROOT / "src").rglob("*.py") if (ROOT / "src" / "value_ai") not in p.parents
    ]
    scripts = [p for p in (ROOT / "scripts").glob("*.py") if p.stem != "run_value"]
    offenders = [
        str(p.relative_to(ROOT))
        for p in [*outside, *scripts]
        if _reaches(imported_modules(p), "src.value_ai")
    ]
    assert offenders == []


def test_the_value_entrypoint_imports_only_its_feed_and_the_service() -> None:
    """scripts/run_value.py is never imported (it starts a service), so its own imports are
    checked by name; everything it reaches is in the sys.modules probe below."""
    allowed = (
        "asyncio",
        "datetime",
        "logging",
        "signal",
        "threading",
        "scripts.value_feed",
        "src.common.config",
        "src.common.logging",
        "src.common.value_ai_types",
        "src.common.value_inputs",
        "src.common.value_types",
        "src.value.claude_reads",
        "src.value.service",
        "src.value_ai.analyst",
        # Part 5 (Stage 3): the trading side's switches, read for the night; the RTH cycle
        "zoneinfo",
        "src.common.market_hours",
        "src.storage.system_settings",
        "src.value.notify",
        "src.value.stage3",
        # Part 6: the value process drains its own command kinds (spec §9.7)
        "time",
        "src.common.value_commands",
        "src.value.commands",
        "src.storage.app_commands",
        "src.storage.db",
        "src.value.store",
        # Part 6 Task 4: the card outbox
        "src.value.outbox",
    )
    mods = imported_modules(ROOT / "scripts" / "run_value.py")
    extra = sorted(m for m in mods if not any(m == a or m.startswith(a + ".") for a in allowed))
    assert extra == []


def test_the_value_entrypoint_drains_lazily() -> None:
    """Part 6: scripts/run_value.py reaches the trading DB's command queue only inside a function
    body, so importing the value process loads no wheel layer (the sys.modules probe below)."""
    tree = ast.parse((ROOT / "scripts" / "run_value.py").read_text(encoding="utf-8"))
    lazy = ("src.storage.app_commands", "src.storage.db")

    def names(node: ast.AST) -> set[str]:
        if isinstance(node, ast.Import):
            return {a.name for a in node.names}
        if isinstance(node, ast.ImportFrom) and node.module:
            return {node.module}
        return set()

    top: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            for sub in ast.walk(node):
                top |= names(sub)
    inside = {
        m
        for fn in ast.walk(tree)
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
        for sub in ast.walk(fn)
        for m in names(sub)
    }
    assert not [m for m in top if m in lazy]
    assert set(lazy) <= inside


def test_the_value_process_loads_no_wheel_layer_and_no_ibkr() -> None:
    """Everything the value process imports, including the news.db readers its feed uses for
    earnings dates: no wheel layer, no Claude, no IBKR client, and never news.db's read-write
    engine."""
    probe = (
        "import importlib, json, pkgutil, sys\n"
        "import src.value as v\n"
        "for m in pkgutil.walk_packages(v.__path__, 'src.value.'):\n"
        "    importlib.import_module(m.name)\n"
        "import scripts.value_feed\n"
        "import src.news.store.readonly, src.news.store.queries, src.data.factory\n"
        # what the service imports lazily, inside functions (review M11)
        "import src.common.universe, src.storage.regime_state\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    env = {**os.environ, "IBKR_CONFIG_USE_EXAMPLES": "1"}
    out = subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    )
    loaded = set(json.loads(out.stdout.strip().splitlines()[-1]))
    forbidden = [f for f in FORBIDDEN_FOR_VALUE if f != "src.news"]
    assert [m for m in forbidden if _reaches(loaded, m)] == []
    assert not _reaches(loaded, "src.news.store.session")
    assert not _reaches(loaded, "ib_async")


def test_the_research_worker_owns_the_filings_feed() -> None:
    """Spec §6.9: the submissions and going-concern jobs live in src/research and fetch through
    src/data; the value side reads their table only through the neutral loader."""
    for name in ("submissions", "going_concern", "filing_sections"):
        mods = imported_modules(ROOT / "src" / "research" / "ingest" / f"{name}.py")
        assert _reaches(mods, "src.data.factory") and not _reaches(mods, "src.value")
    readers = [
        str(p.relative_to(ROOT))
        for p in [*VALUE, *(ROOT / "scripts").glob("value_*.py")]
        if "FilingIndexRow" in p.read_text(encoding="utf-8")
        or "FilingSectionRow" in p.read_text(encoding="utf-8")
    ]
    assert readers == []  # only src/common/value_inputs.py names the tables


VALUE_AI = sorted((ROOT / "src" / "value_ai").rglob("*.py"))
FORBIDDEN_FOR_VALUE_AI = (
    "src.value",
    "src.engine",
    "src.execution",
    "src.strategies",
    "src.orchestrator",
    "src.monitor",
    "src.notify",
    "src.ledger",
    "src.storage",
    "src.spreads",
    "src.spreads_ai",
    "src.api",
    "src.reporting",
    "src.research",
)


def test_value_ai_reaches_claude_only_through_the_cli_and_never_the_value_book() -> None:
    """Spec §8, §16: src/value_ai/ imports nothing from src.value, the trading path, notify,
    the ledger or the storage layer; from src.claude only the slim ``src.claude.cli``; it reads
    news.db only through the read-only engine and the Session-parameterised queries."""
    assert len(VALUE_AI) >= 5
    offenders = []
    for p in VALUE_AI:
        mods = imported_modules(p)
        offenders += [f"{p.name} -> {m}" for m in FORBIDDEN_FOR_VALUE_AI if _reaches(mods, m)]
        offenders += [
            f"{p.name} -> {m}"
            for m in mods
            if _reaches({m}, "src.claude") and not _reaches({m}, "src.claude.cli")
        ]
        offenders += [
            f"{p.name} -> {m}"
            for m in mods
            if _reaches({m}, "src.news")
            and not _reaches({m}, "src.news.store.readonly")
            and not _reaches({m}, "src.news.store.queries")
        ]
    assert offenders == []


def test_the_analyst_loads_no_wheel_layer_and_no_value_code() -> None:
    """Importing the analyst (what scripts/run_value.py does) loads src.claude.cli alone from the
    reasoning layer: no runner, prompt stack or memory, no src.value, no IBKR client, and never
    news.db's read-write engine."""
    probe = (
        "import json, sys\nimport src.value_ai.analyst\nprint(json.dumps(sorted(sys.modules)))\n"
    )
    env = {**os.environ, "IBKR_CONFIG_USE_EXAMPLES": "1"}
    out = subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    )
    loaded = set(json.loads(out.stdout.strip().splitlines()[-1]))
    claude = sorted(m for m in loaded if m.startswith("src.claude."))
    assert claude == ["src.claude.cli"]
    bad = [m for m in FORBIDDEN_FOR_VALUE_AI if _reaches(loaded, m)]
    assert bad == [] and not _reaches(loaded, "ib_async")
    assert not _reaches(loaded, "src.news.store.session")


def test_the_wheel_reads_the_value_book_only_through_the_read_only_view() -> None:
    """Spec §9.1-§9.2, §16 (Part 5): src/common/value_view.py opens value.db read-only with plain
    SQL and imports nothing of the value book, and it (with src.common.books) is the only way the
    engine, execution, strategies and the IBKR readers learn of the book."""
    mods = imported_modules(ROOT / "src" / "common" / "value_view.py")
    assert {m.split(".")[0] for m in mods} <= {
        "__future__",
        "logging",
        "sqlite3",
        "dataclasses",
        "datetime",
        "pathlib",
        "src",
    }
    # Part 6 (Task 5): the one widening of this fence, src.common.value_commands (standard library
    # only; the proposal fingerprint a /value card's buttons must carry)
    assert all(
        _reaches({m}, "src.common.config") or _reaches({m}, "src.common.value_commands")
        for m in mods
        if m.startswith("src.")
    )
    text = (ROOT / "src" / "common" / "value_view.py").read_text(encoding="utf-8")
    assert "mode=ro" in text and "INSERT" not in text.upper().replace("INSERTED", "")
    offenders = [
        str(p.relative_to(ROOT))
        for pkg in ("engine", "execution", "strategies", "ibkr", "notify", "orchestrator")
        for p in sorted((ROOT / "src" / pkg).rglob("*.py"))
        if "value_db_url" in p.read_text(encoding="utf-8")
        or _reaches(imported_modules(p), "src.value")
    ]
    assert offenders == []  # no other way to the value database's path or code


def test_the_money_modules_read_no_claude_prose_or_facts() -> None:
    """Spec §9.4, §16: the gate and the book read what an LLM produced only as the effective
    verdict and fair value Python computed and clamped; never notes, kill triggers or facts."""
    prose = ("ValueClaudeNoteRow", "ValueKillTriggerRow", "ValueClaudeFactRow", "src.value_ai")
    offenders = [
        f"{name}: {word}"
        for name in ("risk", "sizing", "book", "live", "executor", "stage3")
        for word in prose
        if word in (ROOT / "src" / "value" / f"{name}.py").read_text(encoding="utf-8")
    ]
    assert offenders == []
    risk_mods = imported_modules(ROOT / "src" / "value" / "risk.py")
    assert not _reaches(risk_mods, "src.value.store")  # the gate reads nothing itself


def test_approval_service_reaches_the_value_book_only_through_the_view() -> None:
    """Part 6 ruling 6: a tap on a value card is forwarded as an intent. approval_service imports
    the stdlib-only command module and the read-only view, and nothing under src.value."""
    mods = imported_modules(ROOT / "src" / "notify" / "approval_service.py")
    assert _reaches(mods, "src.common.value_view") and _reaches(mods, "src.common.value_commands")
    assert not _reaches(mods, "src.value")
    assert not _reaches(mods, "src.value_ai")
