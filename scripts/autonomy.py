"""Show or change the autonomy rung from the command line (backs ``./ibkr autonomy``).

Goes through the exact same ``system_settings.promotion_blockers`` / ``set_autonomy_level``
gate as Telegram's ``/autonomy`` command (``src/notify/approval_service.py``) and the web
``set_autonomy`` drain handler (``src/notify/command_drain.py``) — there is exactly one
autonomy rung and one promotion gate; this script is not a new back door around either.
Promotion (moving up a rung) is refused, with the unmet criteria printed, unless the evidence
gate is satisfied or ``automation.paper_skip_promotion_gate`` bypasses it (paper mode only —
see ``config/settings.yaml`` and ``src/storage/system_settings.py::promotion_blockers``).
Demotion (moving down, including a same-rung no-op) always succeeds.

Usage:
    python -m scripts.autonomy                 # show current rung + promotion blockers
    python -m scripts.autonomy full             # attempt to move to FULL
    python -m scripts.autonomy WHITELIST         # level names are case-insensitive
"""

from __future__ import annotations

import sys

from src.common.logging import setup_logging
from src.common.schemas import AutonomyLevel
from src.storage.db import init_db
from src.storage.system_settings import (
    autonomy_progress,
    get_autonomy_level,
    promotion_blockers,
    set_autonomy_level,
)

_ORDER = [
    AutonomyLevel.OBSERVE,
    AutonomyLevel.MANUAL,
    AutonomyLevel.WHITELIST,
    AutonomyLevel.FULL,
]


def _print_status(level: AutonomyLevel) -> None:
    fills, fill_rate, closed_once = autonomy_progress()
    print(f"autonomy = {level.value}")
    print(f"evidence: {fills} fills, {fill_rate:.0%} fill rate, closed_once={closed_once}")

    idx = _ORDER.index(level)
    if idx == len(_ORDER) - 1:
        print("Already at the top rung (FULL).")
        return

    next_level = _ORDER[idx + 1]
    blockers = promotion_blockers(next_level)
    if blockers:
        print(f"blocked from {next_level.value}:")
        for b in blockers:
            print(f"  - {b}")
    else:
        print(f"eligible to promote to {next_level.value}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    init_db()

    if not argv:
        _print_status(get_autonomy_level())
        return 0

    requested = argv[0].strip().lower()
    try:
        target = AutonomyLevel(requested)
    except ValueError:
        valid = ", ".join(level.value for level in _ORDER)
        print(f"error: unknown autonomy level {requested!r}. Valid: {valid}.", file=sys.stderr)
        return 1

    blockers = promotion_blockers(target)
    if blockers:
        print(f"refused: promotion to {target.value} blocked:", file=sys.stderr)
        for b in blockers:
            print(f"  - {b}", file=sys.stderr)
        return 1

    set_autonomy_level(target)
    print(f"autonomy = {target.value}")
    return 0


if __name__ == "__main__":
    setup_logging()
    raise SystemExit(main())
