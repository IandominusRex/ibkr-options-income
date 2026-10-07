"""The operator's config/*.yaml stays private; the repo ships config/*.example.yaml.

``src.common.config.config_path`` reads the private copy when it exists, falls back to the
committed example when it doesn't, and always uses the example under
``IBKR_CONFIG_USE_EXAMPLES=1`` (which tests/conftest.py sets for the whole suite).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

import src.common.config as config_mod

_ROOT = Path(__file__).resolve().parents[1]


def test_every_private_config_ships_an_example() -> None:
    for name in config_mod.PRIVATE_CONFIG_FILES:
        example = config_mod.example_path(name)
        assert example.exists(), f"missing {example.name}"
        assert isinstance(yaml.safe_load(example.read_text(encoding="utf-8")), dict)


def test_private_config_files_are_gitignored() -> None:
    for name in config_mod.PRIVATE_CONFIG_FILES:
        rel = f"config/{name}"
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", rel], cwd=_ROOT, check=False
        ).returncode
        assert ignored == 0, f"{rel} must be git-ignored"
        example_rel = f"config/{config_mod.example_path(name).name}"
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", example_rel],
            cwd=_ROOT,
            check=False,
            capture_output=True,
        ).returncode
        assert tracked == 0, f"{example_rel} must be committed"


def test_the_suite_reads_the_examples() -> None:
    assert config_mod.config_path("settings.yaml") == config_mod.example_path("settings.yaml")
    assert config_mod.get_config().ledger.account == ""


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.delenv(config_mod.USE_EXAMPLES_ENV, raising=False)
    (tmp_path / "settings.example.yaml").write_text("ledger: {account: ''}\n")
    return tmp_path


def test_private_copy_wins_when_present(config_dir) -> None:
    (config_dir / "settings.yaml").write_text("ledger: {account: DU0000001}\n")
    assert config_mod.config_path("settings.yaml") == config_dir / "settings.yaml"


def test_missing_private_copy_falls_back_to_the_example(config_dir, caplog) -> None:
    with caplog.at_level("WARNING"):
        path = config_mod.config_path("settings.yaml")
    assert path == config_dir / "settings.example.yaml"
    assert "settings.yaml not found" in caplog.text


def test_non_private_files_are_read_as_is(config_dir) -> None:
    assert config_mod.config_path("research.yaml") == config_dir / "research.yaml"
