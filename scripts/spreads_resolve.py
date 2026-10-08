"""Settle a spread by hand in data/spreads.db — the one write the operator makes to it.

For a spread the service can no longer close itself: it expired while still open, or the
broker shows it already gone (a close that filled while the Gateway was down). Look up what
actually happened in TWS or the trade ledger, then record it:

python -m scripts.spreads_resolve --spread-id 20261007-P679-674-100500 --debit 0.04
python -m scripts.spreads_resolve --spread-id ... --debit 0.30 --contracts 1 --commission 1.30
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from src.spreads import store


def main() -> None:
    p = argparse.ArgumentParser(description="Settle an open spread by hand")
    p.add_argument("--spread-id", required=True)
    p.add_argument(
        "--debit", type=float, required=True, help="per share paid to close (0 = expired worthless)"
    )
    p.add_argument("--contracts", type=int, default=None, help="default: every contract still open")
    p.add_argument(
        "--commission", type=float, default=0.0, help="closing commission, USD (positive)"
    )
    a = p.parse_args()
    store.init_spreads_db()
    held = store.held_contracts(a.spread_id)
    if held is None:
        raise SystemExit(f"no open or expiring spread {a.spread_id!r} in spreads.db")
    qty = held if a.contracts is None else a.contracts
    if not 1 <= qty <= held:
        raise SystemExit(f"{a.spread_id} has {held} contract(s) open; cannot settle {qty}")
    if a.debit < 0 or a.commission < 0:
        raise SystemExit(
            "--debit and --commission are per-share / USD costs and cannot be negative"
        )
    realized = store.close_position(
        a.spread_id,
        contracts=qty,
        debit=a.debit,
        commission=a.commission,
        reason="resolved_by_hand",
        now=datetime.now(UTC),
    )
    print(
        f"{a.spread_id}: settled {qty} contract(s) at {a.debit:.2f}, realized {realized:+.2f} USD"
    )


if __name__ == "__main__":
    main()
