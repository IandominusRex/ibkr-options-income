"""Reconcile the verdict outcome ledger — attach realized outcomes to closed trades.

Deterministic and DB-only (no IBKR connection). Safe to re-run; terminal outcomes are never
re-classified. The EOD orchestrator runs this automatically; use this script to reconcile
on demand or to flag specific assignments the automatic pass treats as expired-worthless.

Usage:
    source .venv/bin/activate
    python -m scripts.reconcile_outcomes
    python -m scripts.reconcile_outcomes --assigned CID1 CID2   # mark these as assigned
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.claude.eval.reconcile import reconcile
from src.common.logging import get_logger, setup_logging
from src.storage.db import init_db

log = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile the verdict outcome ledger.")
    parser.add_argument(
        "--assigned",
        nargs="*",
        default=[],
        metavar="CANDIDATE_ID",
        help="candidate_ids whose past-expiry short was actually assigned",
    )
    args = parser.parse_args()

    setup_logging()
    init_db()
    counts = reconcile(assigned_candidate_ids=args.assigned or None)
    if counts:
        log.info("Reconciled outcomes: %s", counts)
    else:
        log.info("No ledger rows reached a terminal outcome this pass.")


if __name__ == "__main__":
    main()
