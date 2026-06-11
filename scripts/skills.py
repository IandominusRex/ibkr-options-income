"""Review and manage reasoning skills — the human gate of the skill loop.

Skills proposed by `python -m scripts.propose_skill` land in config/skills/proposed/. Nothing
reaches a prompt until you promote it here. Promotion is a git-visible file move.

Usage:
    source .venv/bin/activate
    python -m scripts.skills list                  # active + proposed
    python -m scripts.skills show <name>           # full body of a skill
    python -m scripts.skills promote <name>        # proposed/ → active/ (injected from now on)
    python -m scripts.skills reject <name>         # proposed/ → rejected/
    python -m scripts.skills retire <name>         # active/  → proposed/ (stop injecting)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.claude.skills import registry


def _cmd_list() -> None:
    active = registry.load_active_skills()
    proposed = registry.list_proposed()
    print(f"ACTIVE ({len(active)}) — injected into strategist/roll prompts:")
    for s in active or []:
        print(f"  ● {s.name}: {s.description}")
    if not active:
        print("  (none)")
    print(f"\nPROPOSED ({len(proposed)}) — awaiting your review:")
    for s in proposed or []:
        print(f"  ○ {s.name}: {s.description}")
    if not proposed:
        print("  (none)")


def _cmd_show(name: str) -> None:
    for s in registry.load_active_skills() + registry.list_proposed():
        if s.name == name:
            print(f"# {s.name}\n{s.description}\n")
            if s.rationale:
                print(f"Rationale: {s.rationale}\n")
            if s.supporting_stats:
                print(f"Supporting stats: {s.supporting_stats}\n")
            print(s.body)
            return
    print(f"Skill '{name}' not found.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage reasoning skills.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for verb in ("show", "promote", "reject", "retire"):
        p = sub.add_parser(verb)
        p.add_argument("name")
    args = parser.parse_args()

    if args.cmd == "list":
        _cmd_list()
    elif args.cmd == "show":
        _cmd_show(args.name)
    elif args.cmd == "promote":
        print("Promoted." if registry.promote(args.name) else "Promote failed (see logs).")
    elif args.cmd == "reject":
        print("Rejected." if registry.reject(args.name) else "Reject failed (see logs).")
    elif args.cmd == "retire":
        print("Retired." if registry.retire(args.name) else "Retire failed (see logs).")


if __name__ == "__main__":
    main()
