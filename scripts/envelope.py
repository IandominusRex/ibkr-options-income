"""Show and change the risk envelope's data-gated switches.

A switch is a behaviour the envelope plan builds now but turns on only when data says so (a
replay or capture report PASSes, or you set it here). A report never overwrites a value set by
this CLI, and a FAIL never turns anything off: only this CLI does.

Usage:
    python -m scripts.envelope show                  # every switch: value, source, when set
    python -m scripts.envelope switch NAME VALUE     # set one (source "cli"), with a Telegram notice
    python -m scripts.envelope apply-reports         # apply the PASSed files in data/envelope_reports/

In live every switch reads its default whatever is stored (``spxw_ready`` excepted), so a value
set here takes effect in paper only.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from src.common.logging import setup_logging
from src.notify.notices import send_notice
from src.storage.db import init_db
from src.storage.envelope_switches import (
    SWITCHES,
    apply_reports,
    get_switch,
    set_switch,
    switch_record,
)


def _show() -> int:
    width = max(len(n) for n in SWITCHES)
    print(f"{'switch'.ljust(width)}  {'value':<8} {'source':<24} set_at")
    for name, (default, _allowed) in SWITCHES.items():
        rec = switch_record(name)
        source = str(rec.get("source")) if rec else "(default)"
        set_at = str(rec.get("set_at")) if rec else ""
        print(
            f"{name.ljust(width)}  {get_switch(name):<8} {source:<24} {set_at}  [default {default}]"
        )
    return 0


def _switch(name: str, value: str) -> int:
    old = get_switch(name) if name in SWITCHES else None
    try:
        set_switch(name, value, source="cli")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{name}: {old} -> {get_switch(name)}")
    asyncio.run(send_notice(f"envelope switch {name}: {old} -> {value} (set by CLI)"))
    return 0


def _apply_reports() -> int:
    messages = apply_reports()
    if not messages:
        print("no report changes a switch")
    for message in messages:
        print(message)
        asyncio.run(send_notice(message))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Risk-envelope switches")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="every switch, its value, source and when it was set")
    s = sub.add_parser("switch", help="set a switch by hand")
    s.add_argument("name")
    s.add_argument("value")
    sub.add_parser("apply-reports", help="apply the PASSed result files now")
    a = p.parse_args(argv)

    init_db()
    if a.cmd == "show":
        return _show()
    if a.cmd == "switch":
        return _switch(a.name, a.value)
    return _apply_reports()


if __name__ == "__main__":
    setup_logging()
    raise SystemExit(main())
