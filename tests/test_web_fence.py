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
        for p in sorted((ROOT / "src" / d).rglob("*.py"))
        if p.name != "__init__.py"
    ]


def test_checks_engine_never_imports_the_summary_layer() -> None:
    """The AI summary is enrichment. It must not reach the deterministic checks engine."""
    checks_dir = ROOT / "src" / "research" / "checks"
    assert checks_dir.is_dir(), "checks package must exist for this fence to be meaningful"
    offenders = [
        str(p.relative_to(ROOT))
        for p in sorted(checks_dir.rglob("*.py"))
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


# ---------------------------------------------------------------------------
# P2 — the API writes exactly one table. See Web plan/P2-design.md §4.2.
# ---------------------------------------------------------------------------


def test_only_the_command_module_holds_a_write_handle() -> None:
    """get_command_engine and command_session are the API's only read-write handle.

    One module (``src/api/commands.py``) may import them, alongside ``trading_db.py``
    where they are defined. The router must not reach for ``command_session`` to clear
    a confirm token — that write goes through ``src/api/commands.py`` instead.
    """
    allowed = {"src/api/commands.py", "src/api/trading_db.py"}
    offenders = [
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "src" / "api").rglob("*.py"))
        if any(
            token in p.read_text(encoding="utf-8")
            for token in ("get_command_engine", "command_session")
        )
        and str(p.relative_to(ROOT)) not in allowed
    ]
    assert not offenders, f"write handle leaked to: {offenders}"


def test_the_command_writer_names_no_other_table() -> None:
    """A grep-level guard on top of the runtime listener from Task 1.2."""
    text = (ROOT / "src" / "api" / "commands.py").read_text(encoding="utf-8")
    forbidden = ("OrderRow", "ApprovalRow", "CandidateRow", "PositionSnapshotRow", "FillRow")
    named = [t for t in forbidden if t in text]
    assert not named, f"the command writer must touch app_commands only, names: {named}"


def test_the_trading_path_still_never_imports_the_web_layer() -> None:
    """P2 adds a drain in src/notify/, which MAY import src.api's schemas. The engine,
    execution and strategies packages still may not."""
    offenders = [
        rel
        for rel in _modules_under("engine", "execution", "strategies")
        if any(
            token in (ROOT / rel).read_text(encoding="utf-8")
            for token in ("src.api", "src.research")
        )
    ]
    assert not offenders, f"fence violated — web layer reachable from: {offenders}"


# ---------------------------------------------------------------------------
# P2 M7 — universe overrides are human-edited config, and only a human writes them.
# See Web plan/P2-design.md §7.4.
# ---------------------------------------------------------------------------


def test_no_enrichment_layer_can_write_a_universe_override() -> None:
    """An override changes CSP eligibility. Only an authenticated human may create one."""
    offenders = [
        str(p.relative_to(ROOT))
        for d in ("claude/eval", "research")
        for p in sorted((ROOT / "src" / d).rglob("*.py"))
        if "universe_overrides" in p.read_text(encoding="utf-8")
        or "set_override" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"an enrichment layer can write the universe: {offenders}"


def test_the_risk_engine_never_reads_an_override() -> None:
    """sectors feeds concentration limits and is deliberately not overridable."""
    text = (ROOT / "src" / "engine" / "risk_engine.py").read_text(encoding="utf-8")
    assert "effective_universe" not in text
    assert "universe_overrides" not in text


def test_the_overridable_set_matches_the_spec_exactly() -> None:
    """A future edit that widens this must fail here first.

    The overridable set `{"would_own", "watchlist"}` is independently declared four times
    (M7 final-review Fix 6): `src.common.universe.OVERRIDABLE_LISTS`,
    `src.api.routers.universe._OVERRIDABLE`, `UniversePayload.list_name`'s `Literal` type,
    and the two route functions' `list_name: Literal[...]` parameters. This test pins all
    four so a future edit that widens any one of them without the others fails here first,
    not silently at runtime.
    """
    import typing

    from src.api.models.commands import UniversePayload
    from src.api.routers.universe import (
        _OVERRIDABLE,
        add_to_universe,
        remove_from_universe,
    )
    from src.common.universe import OVERRIDABLE_LISTS

    expected = frozenset({"would_own", "watchlist"})

    assert OVERRIDABLE_LISTS == expected
    assert _OVERRIDABLE == expected

    payload_annotation = UniversePayload.model_fields["list_name"].annotation
    assert frozenset(typing.get_args(payload_annotation)) == expected

    for route_fn in (add_to_universe, remove_from_universe):
        hints = typing.get_type_hints(route_fn)
        assert frozenset(typing.get_args(hints["list_name"])) == expected, (
            f"{route_fn.__name__}'s list_name parameter has drifted from the spec's overridable set"
        )


def test_reporting_never_imports_the_enrichment_loop() -> None:
    """src/reporting/ is downstream of everything and upstream of nothing."""
    reporting = ROOT / "src" / "reporting"
    assert reporting.is_dir(), "src/reporting/ does not exist (M4 Task 4.1 not run)"
    for path in reporting.rglob("*.py"):
        text = path.read_text()
        assert "src.claude" not in text, f"{path} imports the enrichment layer"


def test_the_trading_path_never_imports_reporting() -> None:
    """A report reads the whole book, including enrichment tables. It stays on the read side."""
    for pkg in ("engine", "execution", "strategies"):
        pkg_dir = ROOT / "src" / pkg
        assert pkg_dir.is_dir(), f"src/{pkg}/ does not exist"
        for path in pkg_dir.rglob("*.py"):
            text = path.read_text()
            assert "src.reporting" not in text, f"{path} imports the reporting layer"


# ---------------------------------------------------------------------------
# P3-P4 M6 — GET /pnl/system reads behind the src/claude/eval/ fence (Task 6.1).
# These lock down the read-only guarantee that makes that route not a breach.
# See Web plan/P3-P4-design.md §7.5.
# ---------------------------------------------------------------------------


def test_no_web_module_can_write_the_verdict_ledger() -> None:
    """P4 reads the outcome ledger. Nothing in the web layer may write it."""
    writers = ("record_verdicts", "update_outcome", "mark_filled", "VerdictLedgerRow(")
    for path in Path("src/api").rglob("*.py"):
        text = path.read_text()
        for writer in writers:
            assert writer not in text, f"{path} can write the verdict ledger via {writer}"


def test_no_web_module_can_write_a_scoring_weight() -> None:
    """The fence's whole point: the loop does not close automatically."""
    for path in Path("src/api").rglob("*.py"):
        text = path.read_text()
        assert "scoring_weights" not in text, f"{path} references scoring weights"


def test_the_api_still_writes_exactly_one_table() -> None:
    """P3 and P4 add no write. The P2 guarantee is unchanged, re-asserted here because
    this is the phase that had the most reason to relax it.

    ``trading_db.py`` is skipped alongside ``commands.py`` because it DEFINES
    ``get_command_engine``/``command_session`` (see
    ``test_only_the_command_module_holds_a_write_handle`` above, which already carries the
    same exception) — this mirrors that existing P2 test's allowed set, not a relaxation of
    the invariant.
    """
    skip = {"commands.py", "trading_db.py"}
    for path in Path("src/api").rglob("*.py"):
        if path.name in skip:
            continue
        text = path.read_text()
        assert "get_command_engine" not in text
        assert "command_session" not in text


def test_reporting_never_writes_anything() -> None:
    """src/reporting/ computes. It does not persist, and a cache is not an exception."""
    for path in Path("src/reporting").rglob("*.py"):
        text = path.read_text()
        for writer in ("session.add", "session.merge", "session.delete", "session.commit"):
            assert writer not in text, f"{path} writes to the database"


def test_the_portfolio_snapshot_writers_are_the_two_we_intended() -> None:
    """A third writer means a third cadence nobody reasoned about."""
    callers = [
        path
        for path in Path("src").rglob("*.py")
        if "save_portfolio_snapshot" in path.read_text() and path.name != "portfolio_snapshots.py"
    ]
    assert {p.as_posix() for p in callers} == {
        "src/monitor/intraday.py",
        "src/notify/command_drain.py",
    }


# ---------------------------------------------------------------------------
# Trade ledger (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §9).
# ---------------------------------------------------------------------------

_LEDGER_WRITERS = (
    "BrokerExecutionRow(",
    "BrokerCashEventRow(",
    "BrokerCorporateActionRow(",
    "FxRateRow(",
    "LedgerImportRunRow(",
    "TradeAnnotationRow(",
)


def test_the_trading_path_never_imports_the_ledger() -> None:
    """The ledger is reporting. It must never reach a gate, a size, or a screen."""
    for pkg in ("engine", "execution", "strategies"):
        for path in (ROOT / "src" / pkg).rglob("*.py"):
            text = path.read_text()
            assert "src.ledger" not in text, f"{path} imports the trade ledger"
            assert "trade_ledger" not in text, f"{path} imports the trade-ledger builder"


def test_the_ledger_never_imports_the_enrichment_layer() -> None:
    ledger = ROOT / "src" / "ledger"
    assert ledger.is_dir()
    for path in ledger.rglob("*.py"):
        assert "src.claude" not in path.read_text(), f"{path} imports the enrichment layer"


def test_only_the_ledger_package_writes_the_ledger_tables() -> None:
    for path in (ROOT / "src").rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[:2] == ("src", "ledger") or path.name == "models.py":
            continue
        text = path.read_text()
        for writer in _LEDGER_WRITERS:
            assert writer not in text, (
                f"{rel} constructs {writer[:-1]} — only src/ledger/ may write it"
            )
