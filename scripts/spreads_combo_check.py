"""Operator check: does a spreads BAG order show in TWS as a CREDIT spread? (plan Task 11 Step 9)

Places ONE deliberately unfillable put credit spread on the configured underlying (SPY) on the PAPER account — limit credit
at 90% of the width, far above any real price — prints what IBKR echoes back, waits so you can
look at the order in TWS/Gateway, then cancels it. Refuses to run with LIVE_TRADING=true.

    python -m scripts.spreads_combo_check --short 600 --long 595

Expected in TWS: a BAG on SPY, "SELL 600P / BUY 595P", shown as a CREDIT of 4.50. If TWS shows
a DEBIT, the sign convention in src/spreads/orders.py is wrong — do not enable paper mode.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from ib_async import IB, Option

from src.common.config import get_config
from src.common.logging import setup_logging
from src.common.market_hours import today_et
from src.common.schemas import SpreadCandidate
from src.ibkr.connection import connect_with_retry
from src.spreads.orders import build_open_order


async def _main(short: float, long_: float, wait: float) -> None:
    cfg = get_config()
    if cfg.is_live:
        raise SystemExit("refusing: LIVE_TRADING=true — this check is paper-only")
    sc = cfg.spreads
    ib = IB()
    await connect_with_retry(
        ib,
        cfg.ibkr.host,
        cfg.ibkr_port,
        cfg.ibkr.client_ids["healthcheck"],
        timeout=cfg.ibkr.connect_timeout_seconds,
        label="spreads_combo_check",
    )
    try:
        expiry = today_et()
        legs = [
            Option(
                sc.underlying, f"{expiry:%Y%m%d}", k, "P", "SMART", tradingClass=sc.trading_class
            )
            for k in (short, long_)
        ]
        await ib.qualifyContractsAsync(*legs)
        if not all(leg.conId for leg in legs):
            raise SystemExit(f"could not qualify {sc.underlying} {short}/{long_} puts for {expiry}")
        width = abs(short - long_)
        cand = SpreadCandidate(
            spread_id="combo-check",
            side="put",
            expiry=expiry,
            short_strike=short,
            long_strike=long_,
            width=width,
            short_con_id=legs[0].conId,
            long_con_id=legs[1].conId,
            credit_mid=0.9 * width,
            credit_natural=0.9 * width,
            spot=0.0,
            quote_time=datetime.now(UTC),
        )
        bag, order = build_open_order(
            sc.underlying, cand, 1, 0.9 * width, f"{sc.order_ref_prefix}combo-check"
        )
        trade = ib.placeOrder(bag, order)
        await asyncio.sleep(2)
        print("orderStatus:", trade.orderStatus)
        print("order:", trade.order)
        print(f"Look at TWS now ({wait:.0f}s): it must show a CREDIT of {0.9 * width:.2f}.")
        await asyncio.sleep(wait)
    finally:
        for t in ib.openTrades():
            if getattr(t.order, "orderRef", "") == f"{sc.order_ref_prefix}combo-check":
                ib.cancelOrder(t.order)
        await asyncio.sleep(2)
        ib.disconnect()


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--short", type=float, required=True)
    p.add_argument("--long", type=float, required=True)
    p.add_argument("--wait", type=float, default=60.0)
    a = p.parse_args()
    asyncio.run(_main(a.short, a.long, a.wait))


if __name__ == "__main__":
    main()
