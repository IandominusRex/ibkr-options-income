"""Draft a reasoning skill from the labeled verdict ledger via `claude -p`.

Writes the draft to config/skills/proposed/ for human review. It is NOT promoted — run
`python -m scripts.skills promote <name>` after reading it. Requires the claude CLI and at
least some closed (settled) trades in the ledger.

Usage:
    source .venv/bin/activate
    python -m scripts.propose_skill
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.claude.skills.proposer import propose_skill
from src.common.logging import setup_logging
from src.storage.db import init_db


def main() -> None:
    setup_logging()
    init_db()
    proposal = propose_skill()
    if proposal is None:
        print(
            "No proposal generated. Need closed trades in the ledger and the claude CLI "
            "available — see logs."
        )
        return
    print(f"Drafted skill '{proposal.name}' → config/skills/proposed/{proposal.name}.md")
    print(f"  {proposal.description}")
    if proposal.rationale:
        print(f"  Rationale: {proposal.rationale}")
    print(f"\nReview it, then: python -m scripts.skills promote {proposal.name}")


if __name__ == "__main__":
    main()
