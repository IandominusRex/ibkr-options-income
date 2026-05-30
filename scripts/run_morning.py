"""Entry point for the morning scan (one-shot).

Usage:
    python -m scripts.run_morning [--dry-run]
    # or add to crontab: 45 9 * * 1-5 /path/to/.venv/bin/python -m scripts.run_morning

--dry-run  Run the full pipeline (analytics, scoring, Claude) but skip Telegram send
           and order submission. Useful for verifying live-mode config without placing orders.
           Candidates and scores are NOT written to DB in dry-run mode.
"""

import argparse

from src.orchestrator.morning_scan import main

parser = argparse.ArgumentParser(description="Morning scan (one-shot)")
parser.add_argument(
    "--dry-run",
    action="store_true",
    help="Run pipeline but skip execution and Telegram send",
)
args = parser.parse_args()
main(dry_run=args.dry_run)
