"""The operator's handle on Claude's side of the value book (spec §8.2, §8.3, §8.5).

Usage:
    python -m scripts.value_claude                 # the breaker, today's budget, the queue
    python -m scripts.value_claude --read NVDA     # queue a read (first in the queue)
    python -m scripts.value_claude --reset-breaker # Claude's verdict applies again

Writes value.db only through ``src/value/`` (the one writer). The read itself runs in the value
process (``scripts/run_value.py``) at its next poll, with ``value.claude.enabled`` on. Part 6 adds
the same request as a web button and ``/value NAME analyse``.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from src.common.config import get_config
from src.value.claude_reads import queue_read, reads_left
from src.value.claude_verdicts import breaker_state, reset_breaker
from src.value.store import ValueClaudeReadRow, init_value_db, value_session


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--read", metavar="SYMBOL", help="queue a standard read of SYMBOL")
    ap.add_argument("--reset-breaker", action="store_true", help="let Claude's verdict apply")
    args = ap.parse_args(argv)
    cfg = get_config().value
    now = datetime.now(UTC).replace(tzinfo=None)
    init_value_db()
    with value_session() as vs:
        if args.read:
            row = queue_read(vs, args.read.upper(), kind="standard", reason="request", now=now)
            print(f"queued {args.read.upper()}" if row else f"{args.read.upper()}: already queued")
        if args.reset_breaker:
            reset_breaker(vs, now)
            print("breaker reset: Claude's verdict applies again")
        state = breaker_state(vs)
        standard, deep = reads_left(vs, now, cfg)
        queued = vs.scalars(
            select(ValueClaudeReadRow)
            .where(ValueClaudeReadRow.status == "queued")
            .order_by(ValueClaudeReadRow.priority, ValueClaudeReadRow.id)
        ).all()
        print(f"claude reads {'on' if cfg.claude.enabled else 'OFF (value.claude.enabled)'}")
        print(f"breaker: {'TRIPPED: ' + state.get('reason', '') if state.get('tripped') else 'ok'}")
        print(f"left today: {standard} standard, {deep} filing")
        for r in queued:
            print(f"  queued {r.symbol:<6} {r.kind:<8} {r.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
