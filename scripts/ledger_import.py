"""Import an IBKR Activity Statement CSV into the trade ledger.

    python -m scripts.ledger_import path/to/statement.csv            # import
    python -m scripts.ledger_import path/to/statement.csv --dry-run  # parse + count only

Same code path as the dashboard upload (the ``ledger_import`` drain handler).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from src.ledger.activity_csv import NotAnActivityStatement, parse_activity_csv
from src.ledger.ingest import ingest
from src.storage.db import init_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--dry-run", action="store_true", help="parse and print counts; write nothing"
    )
    args = parser.parse_args(argv)

    init_db()
    try:
        statement = parse_activity_csv(args.path.read_text(encoding="utf-8-sig"))
    except NotAnActivityStatement as exc:
        print(f"Not an IBKR Activity Statement CSV: {exc}")
        return 2

    if args.dry_run:
        by_kind = Counter(e.contract.sec_type for e in statement.executions)
        print(
            json.dumps(
                {
                    "account": statement.account,
                    "period": [str(statement.period_start), str(statement.period_end)],
                    "executions": dict(by_kind),
                    "cash_events": len(statement.cash_events),
                    "corporate_actions": len(statement.corporate_actions),
                    "errors": [e.model_dump() for e in statement.errors[:20]],
                    "fatal": statement.fatal,
                },
                indent=2,
            )
        )
        return 1 if statement.fatal else 0

    result = ingest(statement, source="csv", filename=args.path.name)
    print(json.dumps(result.model_dump(), indent=2, default=str))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
