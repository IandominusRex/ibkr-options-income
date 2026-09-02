"""The auth boundary: bearer token in, User out, owner-only routes gated."""

from __future__ import annotations

import pytest

from src.api.auth import Role, authenticate


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr("src.api.auth._configured_token", lambda: "correct-horse-battery")


def test_no_token_is_rejected() -> None:
    assert authenticate(None) is None


def test_empty_token_is_rejected() -> None:
    assert authenticate("") is None


def test_wrong_token_is_rejected() -> None:
    assert authenticate("wrong") is None


def test_correct_token_yields_the_owner() -> None:
    user = authenticate("correct-horse-battery")
    assert user is not None
    assert user.id == "owner"
    assert user.role is Role.OWNER


def test_unconfigured_token_rejects_everything(monkeypatch) -> None:
    """An empty WEB_API_TOKEN must fail closed, never open."""
    monkeypatch.setattr("src.api.auth._configured_token", lambda: "")
    assert authenticate("") is None
    assert authenticate("anything") is None
