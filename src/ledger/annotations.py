"""The only writer of ``trade_annotations`` and the corporate-action review flag.

Called from the exec process's drain handlers (src/notify/command_drain.py), never the API.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ledger.state import bump_generation
from src.storage.models import BrokerCorporateActionRow, TradeAnnotationRow


def annotate(session: Session, *, order_key: str, fields: dict[str, Any], updated_by: str) -> None:
    """Upsert a ``TradeAnnotationRow`` for ``order_key``, applying only the keys in ``fields``.

    ``fields`` is already narrowed to ``model_fields_set`` by the caller, so a key's mere
    presence (not its truthiness) decides whether it is applied — e.g. ``notes=""`` clears the
    note, but an omitted ``notes`` leaves the existing value untouched. ``outcome_override``'s
    empty string clears the override (back to ``None``), the sentinel the payload's
    ``_LEDGER_OUTCOMES`` type carries for exactly this purpose.
    """
    row = session.scalar(
        select(TradeAnnotationRow).where(TradeAnnotationRow.order_key == order_key)
    )
    if row is None:
        row = TradeAnnotationRow(order_key=order_key, notes="", tags=[], exclude_from_stats=False)
        session.add(row)
    if "notes" in fields:
        row.notes = fields["notes"] or ""
    if "tags" in fields:
        row.tags = sorted({t.strip() for t in (fields["tags"] or []) if t and t.strip()})
    if "outcome_override" in fields:
        row.outcome_override = fields["outcome_override"] or None
    if "exclude_from_stats" in fields:
        row.exclude_from_stats = bool(fields["exclude_from_stats"])
    row.updated_by = updated_by
    bump_generation(session)


def mark_corporate_action_reviewed(session: Session, ca_id: int) -> bool:
    """Flag a corporate action as human-reviewed. Returns False if ``ca_id`` does not exist."""
    row = session.get(BrokerCorporateActionRow, ca_id)
    if row is None:
        return False
    row.reviewed = True
    bump_generation(session)
    return True
