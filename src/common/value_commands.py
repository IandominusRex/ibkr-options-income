"""The value book's command kinds, proposal fingerprint and Telegram callback format (Part 6, spec §9.7).

Standard library only: the API, ``approval_service`` and the value process all import it, and none of them may
import another's code. The value process is the only drainer of these kinds; ``command_drain`` skips them.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
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
