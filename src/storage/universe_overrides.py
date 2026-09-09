"""Helpers for the ``universe_overrides`` table — operator edits to the ``would_own``/
``watchlist`` universe lists, layered on top of ``config/universe.yaml`` by a later task's
storage helper (``src/common/universe.py``, M7 Task 7.2). Mirrors the shape of
``src/storage/app_commands.py``: every helper takes an existing ``Session`` so the caller
controls the transaction.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import UniverseOverrideRow, _utcnow


def _find(session: Session, symbol: str, list_name: str) -> UniverseOverrideRow | None:
    return session.execute(
        select(UniverseOverrideRow).where(
            UniverseOverrideRow.symbol == symbol,
            UniverseOverrideRow.list_name == list_name,
        )
    ).scalar_one_or_none()


def set_override(
    session: Session, *, symbol: str, list_name: str, action: str, created_by: str
) -> None:
    """Upsert. A later override for the same (symbol, list_name) replaces the earlier one.

    ``symbol`` is upper-cased before the lookup/write, so ``nvda`` and ``NVDA`` collide into
    the same row. The replace is total — ``action``, ``created_by``, and ``created_at`` are all
    overwritten to reflect this call, so the row always describes the current override, not the
    first one ever made for this (symbol, list_name).
    """
    symbol = symbol.upper()
    existing = _find(session, symbol, list_name)
    if existing is not None:
        existing.action = action
        existing.created_by = created_by
        existing.created_at = _utcnow()
    else:
        session.add(
            UniverseOverrideRow(
                symbol=symbol,
                list_name=list_name,
                action=action,
                created_by=created_by,
            )
        )
    session.flush()


def clear_override(session: Session, *, symbol: str, list_name: str) -> bool:
    """Revert to the YAML base. Returns True if an override existed."""
    existing = _find(session, symbol.upper(), list_name)
    if existing is None:
        return False
    session.delete(existing)
    session.flush()
    return True


def all_overrides(session: Session) -> list[UniverseOverrideRow]:
    """Every override row, unordered — the caller composes these onto the YAML base lists."""
    return list(session.execute(select(UniverseOverrideRow)).scalars().all())
