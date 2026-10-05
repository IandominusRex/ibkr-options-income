"""Pull the IBKR Flex statement into the trade ledger now.

python -m scripts.ledger_flex_pull                    # the nightly query (IBKR_FLEX_QUERY_ID)
python -m scripts.ledger_flex_pull --query-id 123456  # e.g. a one-off 365-day backfill query
python -m scripts.ledger_flex_pull --dry-run          # fetch + parse, print counts, write nothing
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

from src.common.schemas import ParsedStatement
from src.ledger.flex import run_flex_pull
from src.storage.db import init_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--query-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    init_db()
    result = run_flex_pull(query_id=args.query_id, dry_run=args.dry_run)
    if result is None:
        print("Flex is not configured: set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in .env")
        return 0
    if isinstance(result, ParsedStatement):
        codes = Counter(e.codes for e in result.executions)
        print(
            json.dumps(
                {
                    "account": result.account,
                    "executions": len(result.executions),
                    "with_exec_id": sum(1 for e in result.executions if e.exec_id),
                    "codes": dict(codes),
                    "cash_events": len(result.cash_events),
                    "fx_rates": len(result.fx_rates),
                    "errors": [e.model_dump() for e in result.errors[:20]],
                },
                indent=2,
            )
        )
        return 0
    print(json.dumps(result.model_dump(), indent=2, default=str))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
