"""The spreads fence: src/spreads/ is a second system beside the wheel, not a wheel module.

Same globbing rule as tests/test_web_fence.py — a hand-kept list goes stale the moment a module
is added, and a fence that silently stops covering new code is worse than none.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from src.common.config import get_config

ROOT = Path(__file__).resolve().parents[1]
SPREADS = sorted((ROOT / "src" / "spreads").rglob("*.py"))

FORBIDDEN_FOR_SPREADS = (
    "src.claude",
    "src.engine",
    "src.execution",
    "src.strategies",
    "src.orchestrator",
    "src.monitor",
    "src.notify",
    "src.reporting",
    "src.api",
    "src.research",
    "src.spreads_ai",
    "src.news",
)
# Everything outside the spreads package: no wheel layer, no shared one, no script but the
# spreads entrypoints may import it (wheel code learns of the book only via src.common.books).
NOT_SPREADS = sorted(
    p for p in (ROOT / "src").rglob("*.py") if (ROOT / "src" / "spreads") not in p.parents
)
WHEEL_SCRIPTS = sorted(p for p in (ROOT / "scripts").glob("*.py") if "spreads" not in p.stem)


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imported_modules(path: Path, module: str | None = None) -> set[str]:
    """Every module *path* (importable as *module*) imports, resolved: ``from src import
    engine`` is ``src.engine``, relative imports are made absolute, and
    ``importlib.import_module("…")`` / ``__import__`` with a literal count too — a string
    search misses all three."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = (module or _module_name(path)).split(".")
    if path.name != "__init__.py":
        package = package[:-1]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                module = ".".join([*base, node.module] if node.module else base)
            else:
                module = node.module or ""
            out.add(module)
            out.update(f"{module}.{a.name}" for a in node.names)
        elif (
            isinstance(node, ast.Call)
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
            )
        ):
            out.add(node.args[0].value)
    return out


def _reaches(modules: set[str], prefix: str) -> bool:
    return any(m == prefix or m.startswith(prefix + ".") for m in modules)


def _imports(path: Path, module: str) -> bool:
    return _reaches(imported_modules(path), module)


def test_the_import_parser_sees_every_spelling(tmp_path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(
        "from src import engine\n"
        "from ..execution import order_builder\n"
        "import importlib\n"
        "importlib.import_module('src.claude.runner')\n"
        "__import__('src.notify')\n",
        encoding="utf-8",
    )
    mods = imported_modules(probe, "src.spreads.probe")
    for m in ("src.engine", "src.execution.order_builder", "src.claude.runner", "src.notify"):
        assert _reaches(mods, m), m


def test_spreads_package_exists() -> None:
    assert len(SPREADS) >= 10, "fence must cover the spreads package"


def test_spreads_imports_none_of_the_wheel_layers() -> None:
    offenders = [
        f"{p.relative_to(ROOT)} → {m}"
        for p in SPREADS
        for m in FORBIDDEN_FOR_SPREADS
        if _imports(p, m)
    ]
    assert offenders == []


def test_only_the_service_reaches_the_ledger_or_the_trading_db() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in SPREADS
        if p.name != "service.py" and any(_imports(p, m) for m in ("src.ledger", "src.storage"))
    ]
    assert offenders == []


def test_nothing_outside_the_spreads_package_imports_it() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in [*NOT_SPREADS, *WHEEL_SCRIPTS]
        if _imports(p, "src.spreads")
    ]
    assert offenders == []


def test_the_spreads_process_loads_no_wheel_layer_even_transitively() -> None:
    """Imports every spreads module plus the ledger/storage modules the service reaches for in
    paper mode, in a clean interpreter, and checks ``sys.modules`` — a direct-import check
    can't see a forbidden layer pulled in two hops away."""
    code = (
        "import importlib, json, pkgutil, sys\n"
        "import src.spreads as sp\n"
        "for m in pkgutil.walk_packages(sp.__path__, 'src.spreads.'):\n"
        "    importlib.import_module(m.name)\n"
        "import src.ledger.live, src.ledger.state, src.storage.db\n"
        "import src.storage.envelope_switches\n"  # the service's lazy slow-breaker switch read
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    env = {**os.environ, "IBKR_CONFIG_USE_EXAMPLES": "1"}
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    )
    loaded = set(json.loads(out.stdout.strip().splitlines()[-1]))
    assert [m for m in FORBIDDEN_FOR_SPREADS if _reaches(loaded, m)] == []


def test_spreads_never_calls_reqmktdata_directly_or_sends_market_orders() -> None:
    for p in SPREADS:
        text = p.read_text(encoding="utf-8")
        assert ".reqMktData(" not in text, f"{p.relative_to(ROOT)}: use req_fresh_mkt_data"
        assert "MarketOrder" not in text, f"{p.relative_to(ROOT)}: LimitOrder only"


def test_spreads_runtime_files_are_gitignored() -> None:
    """The ThetaData cache is licensed market data and the CSV exports are the account's trade
    log; the halt file is a runtime switch. None of them may ever be picked up by ``git add``."""
    spreads = get_config().spreads
    paths = [
        f"{spreads.backtest.cache_dir}/0123456789abcdef.csv",
        spreads.halt_file,
        "data/spreads_trades.csv",  # the paths SETUP.md §16 and the report script's docstring use
        "data/spreads_paper_trades.csv",
        "data/spreads_bt/june.csv",
    ]
    for rel in paths:
        ignored = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT, check=False)
        assert ignored.returncode == 0, f"{rel} must be git-ignored"


def test_spreads_store_has_its_own_declarative_base() -> None:
    assert "src.storage.models" not in (ROOT / "src" / "spreads" / "store.py").read_text(
        encoding="utf-8"
    )


SPREADS_AI = sorted((ROOT / "src" / "spreads_ai").rglob("*.py"))
FORBIDDEN_FOR_SPREADS_AI = (
    "src.spreads",
    "src.engine",
    "src.execution",
    "src.strategies",
    "src.orchestrator",
    "src.monitor",
    "src.notify",
    "src.ledger",
    "src.storage",
    "src.reporting",
    "src.api",
    "src.research",
    "src.news.store.session",
)


def test_spreads_ai_package_exists() -> None:
    assert len(SPREADS_AI) >= 5, "fence must cover the spreads_ai package"


def test_spreads_ai_never_reaches_orders_or_the_wheel() -> None:
    offenders = [
        f"{p.relative_to(ROOT)} → {m}"
        for p in SPREADS_AI
        for m in FORBIDDEN_FOR_SPREADS_AI
        if _imports(p, m)
    ]
    assert offenders == []


def test_spreads_ai_reaches_claude_only_through_the_light_cli() -> None:
    offenders = [
        f"{p.relative_to(ROOT)} → {m}"
        for p in SPREADS_AI
        for m in imported_modules(p)
        if (m == "src.claude" or m.startswith("src.claude."))
        and not (m == "src.claude.cli" or m.startswith("src.claude.cli."))
    ]
    assert offenders == []


def test_only_the_spreads_entrypoint_imports_spreads_ai() -> None:
    outside = [
        p for p in (ROOT / "src").rglob("*.py") if (ROOT / "src" / "spreads_ai") not in p.parents
    ]
    scripts = [p for p in (ROOT / "scripts").glob("*.py") if p.stem != "run_spreads"]
    offenders = [
        str(p.relative_to(ROOT)) for p in [*outside, *scripts] if _imports(p, "src.spreads_ai")
    ]
    assert offenders == []


def test_the_full_spreads_process_loads_claude_only_through_the_light_cli() -> None:
    """The spreads process with the picker wired in: spreads + spreads_ai + the entrypoint. It
    may load src.claude.cli and the news read-only store, never the wheel's prompt stack, the
    Ollama runner, the trading path or the news process's read-write engine."""
    code = (
        "import importlib, json, pkgutil, sys\n"
        "import src.spreads as sp, src.spreads_ai as sa\n"
        "for pkg, prefix in ((sp, 'src.spreads.'), (sa, 'src.spreads_ai.')):\n"
        "    for m in pkgutil.walk_packages(pkg.__path__, prefix):\n"
        "        importlib.import_module(m.name)\n"
        "import scripts.run_spreads\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    env = {**os.environ, "IBKR_CONFIG_USE_EXAMPLES": "1"}
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    )
    loaded = set(json.loads(out.stdout.strip().splitlines()[-1]))
    claude = sorted(m for m in loaded if m.startswith("src.claude."))
    assert claude == ["src.claude.cli"]
    forbidden = [
        f for f in FORBIDDEN_FOR_SPREADS if f not in ("src.claude", "src.news", "src.spreads_ai")
    ]
    assert [m for m in forbidden if _reaches(loaded, m)] == []
    assert not _reaches(loaded, "src.news.store.session")
