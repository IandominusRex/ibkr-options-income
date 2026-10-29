"""The value book's shadow record, printed for a human (spec §6.8, §7, §11, §12).

    python -m scripts.value_report [--track baseline] [--universe all|trading|evidence]
        [--ruleset VERSION] [--postmortems]

Reads data/value.db (select only; on a new install it first creates the empty tables) and
prints: the survivorship caveat, the
go-live line of spec §12, fixed-horizon returns against SPY with errors clustered by entry date,
the three exit policies side by side, the ranked monthly record and, with ``--postmortems``, one
postmortem per closed position. No IBKR connection, no network.
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from src.common.config import get_config
from src.value.report import HORIZONS, EntryView, EventView, LegView, RankedView, render
from src.value.store import (
    ValueRankedRow,
    ValueShadowEventRow,
    ValueShadowLegRow,
    ValueShadowRow,
    ValueTickerFileRow,
    init_value_db,
    value_session,
)


def load(args: argparse.Namespace) -> str:
    vcfg = get_config().value
    init_value_db()
    with value_session() as s:
        q = select(ValueShadowRow).where(ValueShadowRow.track == args.track)
        if args.universe != "all":
            q = q.where(ValueShadowRow.universe == args.universe)
        if args.ruleset:
            q = q.where(ValueShadowRow.ruleset_version == args.ruleset)
        entries = [
            EntryView(
                id=r.id,
                track=r.track,
                kind=r.kind,
                list_name=r.list_name,
                symbol=r.symbol,
                universe=r.universe,
                status=r.status,
                signal_date=r.signal_date,
                entry_date=r.entry_date,
                entry_price=r.entry_price,
                fair_value=r.fair_value,
                margin_of_safety=r.margin_of_safety,
                ruleset_version=r.ruleset_version,
                returns={h: getattr(r, f"ret_{h}") for h in HORIZONS},
                spy={h: getattr(r, f"spy_{h}") for h in HORIZONS},
                scorecard_json=r.scorecard_json if r.kind == "ready" else "",
            )
            for r in s.scalars(q.order_by(ValueShadowRow.id))
        ]
        ids = {e.id for e in entries}
        legs = [
            LegView(
                shadow_id=g.shadow_id,
                policy=g.policy,
                closed=g.closed,
                exit_date=g.exit_date,
                ret=g.ret_exit,
                spy_ret=g.spy_ret_exit,
                max_drawdown=g.max_drawdown,
                sessions=g.sessions,
                sells=g.sells,
            )
            for g in s.scalars(select(ValueShadowLegRow))
            if g.shadow_id in ids
        ]
        events = [
            EventView(
                shadow_id=v.shadow_id,
                policy=v.policy,
                day=v.day,
                kind=v.kind,
                price=v.price,
                fraction=v.fraction,
                detail=v.detail,
            )
            for v in s.scalars(select(ValueShadowEventRow).order_by(ValueShadowEventRow.id))
            if args.postmortems and v.shadow_id in ids
        ]
        ranked = [
            RankedView(
                formed_on=r.formed_on,
                list_name=r.list_name,
                bucket=r.bucket,
                n=r.n,
                closed_on=r.closed_on,
                ret=r.ret,
                spy_ret=r.spy_ret,
                missing=r.missing,
            )
            for r in s.scalars(select(ValueRankedRow).order_by(ValueRankedRow.formed_on))
            if not args.ruleset or r.ruleset_version == args.ruleset
        ]
        now: dict[tuple[str, str], float | None] = {}
        for f in s.scalars(select(ValueTickerFileRow)):
            now[(f.symbol, "deep_value")] = f.fair_value_deep
            now[(f.symbol, "quality_growth")] = f.fair_value_growth
    return render(
        entries,
        legs,
        events,
        ranked,
        fair_values_now=now,
        live_policy=vcfg.rules.exits.live_policy,
        track=args.track,
        postmortems=args.postmortems,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The value book's shadow record (spec §6.8)")
    parser.add_argument("--track", default="baseline", choices=("baseline", "claude"))
    parser.add_argument("--universe", default="all", choices=("all", "trading", "evidence"))
    parser.add_argument("--ruleset", default=None, help="only this ruleset version")
    parser.add_argument("--postmortems", action="store_true")
    args = parser.parse_args(argv)
    print(load(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
