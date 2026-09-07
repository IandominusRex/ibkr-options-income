"""Instrument-level warnings surfaced alongside the check catalogue.

Warnings are *not* checks: they never appear in the check ribbon and never dilute a
category score. A leveraged ETF's daily-reset decay is a structural property of the
instrument, not a pass/fail question about its fundamentals.

The leveraged set is read from ``config/universe.yaml → leveraged_etfs`` so the two
sets never drift:

* ``CC-only`` (never assignment-eligible) = ``leveraged_etfs − would_own``
* ``Deliberate would_own exception``      = ``leveraged_etfs ∩ would_own``
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from src.common.config import get_config
from src.common.universe import effective_universe


class Warning(BaseModel):
    """One surfaced caveat. ``level`` drives the icon/tint; never colour-only."""

    level: str  # "info" | "caution"
    title: str
    detail: str


def _leveraged_set() -> set[str]:
    cfg = get_config()
    raw = cfg.universe.get("leveraged_etfs") or []
    return {str(s).upper() for s in raw}


def _would_own_set() -> set[str]:
    raw = effective_universe().get("would_own") or []
    return {str(s).upper() for s in raw}


def warnings_for(
    symbol: str, *, is_etf: bool, info: Mapping[str, Any] | None = None
) -> list[Warning]:
    """Structural caveats for one symbol. Empty for an ordinary stock or plain ETF."""
    sym = symbol.upper()
    out: list[Warning] = []

    leveraged = _leveraged_set()
    if sym not in leveraged:
        return out

    would_own = _would_own_set()
    if sym in would_own:
        # Deliberate would_own exception — the UI must read as a considered choice,
        # not an oversight.
        out.append(
            Warning(
                level="caution",
                title="Daily-reset decay risk",
                detail=(
                    f"{sym} is a leveraged ETF. Daily compounding means its long-run "
                    "return can diverge sharply from the index it tracks. It is in "
                    "would_own as a DELIBERATE exception (confirmed 2026-08-27): the "
                    "decay risk on assignment is accepted for covered-call and "
                    "cash-secured-put income specifically."
                ),
            )
        )
    else:
        # CC-only — never assignment-eligible.
        out.append(
            Warning(
                level="caution",
                title="Daily-reset decay risk",
                detail=(
                    f"{sym} is a leveraged ETF. Daily compounding means its long-run "
                    "return can diverge sharply from the index it tracks. Assignment "
                    f"is a structural risk event, so {sym} is deliberately excluded "
                    "from would_own and used for covered call premium only — never "
                    "as a cash-secured-put candidate."
                ),
            )
        )

    return out
