"""Draft a reasoning skill from the labeled verdict ledger via the configured Claude backend.

Writes the draft to config/skills/proposed/ for human review. It is NOT promoted — run
`python -m scripts.skills promote <name>` after reading it. Requires at least some closed
(settled) trades in the ledger, and dispatches on `config/settings.yaml → claude.backend`
("cli" -> claude CLI, "ollama" -> local model, "cli_then_ollama" -> CLI with local fallback)
just like `review_candidates`/`review_roll`.

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
            "No proposal generated. Need closed trades in the ledger and the configured "
            "claude.backend (claude CLI or Ollama) to be available — see logs."
        )
        return
    print(f"Drafted skill '{proposal.name}' → config/skills/proposed/{proposal.name}.md")
    print(f"  {proposal.description}")
    if proposal.rationale:
        print(f"  Rationale: {proposal.rationale}")
    print(f"\nReview it, then: python -m scripts.skills promote {proposal.name}")


if __name__ == "__main__":
    main()
