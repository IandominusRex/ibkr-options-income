"""The value book's command kinds, proposal fingerprint and Telegram callback format (Part 6, spec §9.7).

Standard library only: the API, ``approval_service`` and the value process all import it, and none of them may
import another's code. The value process is the only drainer of these kinds; ``command_drain`` skips them.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Literal

VALUE_KINDS: frozenset[str] = frozenset(
    {
        "value_approve",
        "value_reject",
        "value_trim",
        "value_snapshot",
        "value_analyse",
        "value_refresh",
    }
)
# Kinds that change order state; the value process refuses them under LIVE_TRADING=true.
VALUE_ORDER_KINDS: frozenset[str] = frozenset({"value_approve", "value_reject", "value_trim"})

Action = Literal["approve", "reject", "trim"]
_CODE: dict[str, str] = {"approve": "a", "reject": "r", "trim": "t"}
_ACTION: dict[str, Action] = {"a": "approve", "r": "reject", "t": "trim"}
_FP = re.compile(r"^[0-9a-f]{10}$")
_CALLBACK = re.compile(r"^vbook:([art]):(\d{1,9}):([0-9a-f]{10})$")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def proposal_fingerprint(
    pid: int, kind: str, symbol: str, shares: float, created_at: datetime
) -> str:
    """What a card shows and a tap must carry back: a re-sized or replaced proposal no longer matches."""
    return _hash(f"{pid}|{kind}|{symbol.upper()}|{shares:g}|{created_at:%Y-%m-%dT%H:%M:%S}")


def trim_episode(high: float, offered_at: datetime) -> str:
    """One drawdown episode's id: a trim tap after ``--reset-drawdown`` no longer matches."""
    return _hash(f"trim|{high:.2f}|{offered_at:%Y-%m-%dT%H:%M:%S}")


TRIM_TTL_HOURS = 30.0  # a trim's approved sells: the same horizon as a funding request


def trim_offer_stale(state: dict, trim_pct: float | None, now: datetime) -> bool:
    """Whether the stored trim offer can no longer be tapped (review I5, orchestrator ruling,
    conservative and reversible): the offer is more than ``TRIM_TTL_HOURS`` old, or (given
    *trim_pct*, ``book.drawdown_trim_pct``) the book is no longer down by that much from its high.
    An unknown (missing or unreadable) number never reads as stale. The book refuses the tap on
    this rule and the API reads the same rule for Home, so the two cannot disagree."""
    offered = state.get("trim_offered_at")
    if offered:
        try:
            if now - datetime.fromisoformat(str(offered)) > timedelta(hours=TRIM_TTL_HOURS):
                return True
        except (ValueError, TypeError):  # unreadable, or a naive/aware clock mismatch
            pass
    high, value = state.get("high"), state.get("value")
    if trim_pct is not None and isinstance(high, int | float) and isinstance(value, int | float):
        if high > 0 and (high - value) / high * 100.0 < trim_pct:
            return True
    return False


def is_fingerprint(text: str) -> bool:
    return bool(_FP.match(text))


def callback_data(action: Action, target: int, fingerprint: str) -> str:
    """``vbook:<a|r|t>:<id>:<fp>``; at most 32 bytes, under Telegram's 64."""
    return f"vbook:{_CODE[action]}:{target}:{fingerprint}"


def parse_callback(data: str) -> tuple[Action, int, str] | None:
    m = _CALLBACK.match(data or "")
    if m is None:
        return None
    return _ACTION[m.group(1)], int(m.group(2)), m.group(3)
