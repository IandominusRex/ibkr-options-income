"""The operator's handle on the value book's money (spec §9; Part 5, paper only).

Usage:
    python -m scripts.value_book                       # holdings, proposals, funding, freezes
    python -m scripts.value_book --approve 12          # a tap: approve a pending proposal
    python -m scripts.value_book --reject 12
    python -m scripts.value_book --clear GOOGL         # clear a frozen share attribution
    python -m scripts.value_book --split GOOGL 2:1     # restate the book after a split
    python -m scripts.value_book --reset-drawdown      # the drawdown breaker (spec §9.6)

Writes value.db only through ``src/value/`` (the one writer). The value process acts on an
approved proposal at its next RTH cycle. Part 6 adds the same taps as Telegram and web buttons.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from src.value.book import apply_split, clear_attribution, decide, get_state, set_state, totals
from src.value.store import (
    ValueAttributionRow,
    ValueFundingRow,
    ValueProposalRow,
    init_value_db,
    value_session,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--approve", type=int, metavar="ID")
    ap.add_argument("--reject", type=int, metavar="ID")
    ap.add_argument("--clear", metavar="SYMBOL")
    ap.add_argument("--split", nargs=2, metavar=("SYMBOL", "N:M"))
    ap.add_argument("--reset-drawdown", action="store_true")
    args = ap.parse_args(argv)
    now = datetime.now(UTC).replace(tzinfo=None)
    init_value_db()
    with value_session() as vs:
        if args.approve is not None:
            print(
                f"proposal {args.approve}: {decide(vs, args.approve, approve=True, now=now, by='cli')}"
            )
        if args.reject is not None:
            print(
                f"proposal {args.reject}: {decide(vs, args.reject, approve=False, now=now, by='cli')}"
            )
        if args.clear:
            done = clear_attribution(vs, args.clear, now)
            print(f"{args.clear.upper()}: {'cleared' if done else 'nothing to clear'}")
        if args.split:
            new, old = (float(x) for x in args.split[1].split(":"))
            count = apply_split(vs, args.split[0], new / old, now)
            print(f"{args.split[0].upper()}: {count} order(s) restated x{new / old:g}; --clear it")
        if args.reset_drawdown:
            state = get_state(vs, "high_water") or {}
            set_state(
                vs, "high_water", {**state, "stop": False, "high": state.get("value", 0)}, now
            )
            print("drawdown breaker reset")
        t = totals(vs)
        print("holdings:")
        for s, n in sorted(t.names.items()):
            if n.filled or n.working_buy_cost:
                print(f"  {s:<6} {n.list_name:<15} {n.filled:>8g} sh  cost {n.cost:>12,.2f}")
        print("open proposals:")
        for p in vs.scalars(
            select(ValueProposalRow)
            .where(ValueProposalRow.status.in_(("pending", "approved", "funding")))
            .order_by(ValueProposalRow.id)
        ):
            tap = "TAP" if p.status == "pending" else p.status
            print(
                f"  #{p.id:<4} {p.kind:<4} {p.symbol:<6} {p.shares:g} ({p.reason}, {p.cause}) {tap}"
            )
        for r in vs.scalars(select(ValueFundingRow).where(ValueFundingRow.status == "open")):
            print(
                f"  funding #{r.id} {r.symbol} ${r.needed_usd:,.0f} until {r.expires_at:%m-%d %H:%M}"
            )
        for a in vs.scalars(select(ValueAttributionRow).where(ValueAttributionRow.state != "ok")):
            print(f"  attribution {a.symbol}: {a.state.upper()} ({a.detail})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
