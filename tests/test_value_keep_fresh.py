"""Review I4: a name the shadow record holds but a universe no longer lists still gets nightly
bars, through a plain "keep fresh" file (neither side imports the other's code or database)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import src.common.value_keep_fresh as kf
from src.common.value_universe import ValueUniverse

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def keep_file(tmp_path, monkeypatch):
    path = tmp_path / "value_keep_fresh.json"
    monkeypatch.setattr(kf, "KEEP_FRESH_FILE", path)
    return path


def test_the_list_round_trips_sorted_and_deduplicated(keep_file) -> None:
    assert kf.read_keep_fresh() == []  # no file: the universes alone
    kf.write_keep_fresh(["zzz", "AAA", "aaa"])
    assert kf.read_keep_fresh() == ["AAA", "ZZZ"]
    kf.write_keep_fresh([])
    assert kf.read_keep_fresh() == []


@pytest.mark.parametrize("text", ["not json", '{"a": 1}', '[1, null, ""]'])
def test_an_unreadable_file_is_an_empty_list(keep_file, text) -> None:
    keep_file.write_text(text, encoding="utf-8")
    assert kf.read_keep_fresh() == []


def test_the_sweep_covers_the_universes_and_the_held_names(keep_file, monkeypatch) -> None:
    from src.research.ingest import value_universe as sweep

    monkeypatch.setattr("src.common.universe.effective_universe", lambda: {})
    monkeypatch.setattr(
        sweep,
        "build_value_universe",
        lambda cfg, u: ValueUniverse(trading=["AAA"], evidence=["BBB"]),
    )
    assert sweep.value_names() == ["AAA", "BBB"]
    kf.write_keep_fresh(["GONE", "BBB"])
    assert sweep.value_names() == ["AAA", "BBB", "GONE"]  # BBB is not listed twice


def test_neither_side_imports_the_other() -> None:
    """The channel is a file: research never reaches value code or value.db, value never writes
    research.db (it has no import of the research store at all)."""

    def mods(rel: str) -> set[str]:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        out: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                out |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                out.add(n.module)
        return out

    assert not [
        m for m in mods("src/research/ingest/value_universe.py") if m.startswith("src.value")
    ]
    assert {m for m in mods("src/common/value_keep_fresh.py") if m.startswith("src.")} == {
        "src.common.config"
    }  # ast.ImportFrom.module: the ROOT name is not part of it
    service = mods("src/value/service.py")
    assert "src.common.value_keep_fresh" in service
    assert not [m for m in service if m.startswith("src.research.store")]
