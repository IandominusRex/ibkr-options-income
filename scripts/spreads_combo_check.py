"""Operator check: does a spreads BAG order show in TWS as a CREDIT spread? (plan Task 11 Step 9)

Default (display only): places ONE deliberately unfillable put credit spread on the configured
underlying (SPY) on the PAPER account — limit credit at 90% of the width, far above any real
price — prints what IBKR echoes back, waits so you can look at the order in TWS/Gateway, then
cancels it. Refuses to run with LIVE_TRADING=true.

    python -m scripts.spreads_combo_check --short 600 --long 595

Expected in TWS: a BAG on SPY, "SELL 600P / BUY 595P", shown as a CREDIT of 4.50. If TWS shows
a DEBIT, the sign convention in src/spreads/orders.py is wrong — do not enable paper mode.

``--fill``: opens a fillable one-lot at the natural credit, prints whether IBKR's
``avgFillPrice`` is NEGATIVE as the executor expects for a credit, then closes it at the
natural debit and checks that average is POSITIVE. It also prints every execution IBKR
reported (secType, conId, commission), which shows whether a combo fill arrives with a
BAG-level execution and a commission on each leg. Pick strikes near enough the money to have
a natural credit. If the close does not fill, it says so: close the SPY spread by hand.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from typing import Any

from ib_async import IB, Option

from src.common.config import get_config
from src.common.logging import setup_logging
from src.common.market_hours import today_et
from src.common.schemas import SpreadCandidate, SpreadPosition
from src.ibkr.connection import connect_with_retry
from src.ibkr.market_data import req_fresh_mkt_data
from src.spreads.chain import to_chain_option
from src.spreads.orders import build_close_order, build_open_order, round_tick


def fill_sign_verdict(kind: str, avg_fill_price: float) -> str:
    """What IBKR's average says about the sign convention the executor relies on."""
    expected_negative = kind == "open"
    ok = avg_fill_price < 0 if expected_negative else avg_fill_price > 0
    want = "negative (a credit)" if expected_negative else "positive (a debit)"
    if ok:
        return f"OK: {kind} avgFillPrice {avg_fill_price:+.2f} is {want}, as the executor expects"
    return (
        f"MISMATCH: {kind} avgFillPrice {avg_fill_price:+.2f} — the executor expects {want}. "
        "It records the magnitude and flags the fill, but report this before using paper mode."
    )


async def _quote(ib: IB, legs: list[Any]) -> tuple[Any, Any]:
    tickers = [req_fresh_mkt_data(ib, c, "", False, False) for c in legs]
    try:
        await asyncio.sleep(3)
        short_q, long_q = (to_chain_option(c, t) for c, t in zip(legs, tickers, strict=True))
        return short_q, long_q
    finally:
        for c in legs:
            ib.cancelMktData(c)


async def _wait_filled(trade: Any, seconds: float) -> bool:
    for _ in range(int(seconds * 4)):
        if trade.orderStatus.status == "Filled":
            return True
        await asyncio.sleep(0.25)
    return trade.orderStatus.status == "Filled"


def _print_fills(kind: str, trade: Any) -> None:
    """Each execution IBKR reported, so the operator check also shows whether a combo fill
    comes with a BAG-level execution and which fills carry a commission (review M5)."""
    for f in trade.fills:
        rep = getattr(f, "commissionReport", None)
        print(
            f"  {kind} fill: secType={f.contract.secType} conId={f.contract.conId} "
            f"side={f.execution.side} qty={f.execution.shares} price={f.execution.price} "
            f"commission={getattr(rep, 'commission', None)}"
        )


async def _fill_round_trip(ib: IB, sc: Any, legs: list[Any], cand: SpreadCandidate) -> None:
    short_q, long_q = await _quote(ib, legs)
    if short_q.bid is None or long_q.ask is None or short_q.ask is None:
        raise SystemExit("no usable quote on one leg — pick strikes with live bids and asks")
    credit = round_tick(short_q.bid - long_q.ask)
    if credit <= 0:
        raise SystemExit(f"natural credit {credit:.2f} — move the strikes nearer the money")
    ref = f"{sc.order_ref_prefix}combo-check"
    bag, order = build_open_order(sc.underlying, cand, 1, credit, ref)
    trade = ib.placeOrder(bag, order)
    if not await _wait_filled(trade, 30):
        ib.cancelOrder(order)
        await asyncio.sleep(2)
        if trade.orderStatus.filled:  # it filled between the check and the cancel
            raise SystemExit(
                f"!!! the opening one-lot filled ({trade.orderStatus.filled:g}) as it was "
                "cancelled — close the SPY spread by hand in TWS now (SPY settles in shares)"
            )
        raise SystemExit(f"the opening one-lot did not fill at {credit:.2f}; cancelled")
    print(fill_sign_verdict("open", float(trade.orderStatus.avgFillPrice)))
    await asyncio.sleep(3)  # commission reports arrive after the fill
    _print_fills("open", trade)
    pos = SpreadPosition(
        spread_id="combo-check",
        mode="paper",
        side="put",
        expiry=cand.expiry,
        short_strike=cand.short_strike,
        long_strike=cand.long_strike,
        width=cand.width,
        contracts=1,
        entry_credit=credit,
        opened_at=datetime.now(UTC),
        short_con_id=cand.short_con_id,
        long_con_id=cand.long_con_id,
    )
    short_q, long_q = await _quote(ib, legs)
    debit = round_tick((short_q.ask or cand.width) - (long_q.bid or 0.0) + 0.05)
    bag, order = build_close_order(sc.underlying, pos, 1, max(debit, 0.01), f"{ref}:X")
    trade = ib.placeOrder(bag, order)
    if not await _wait_filled(trade, 30):
        print(
            "!!! the closing one-lot did NOT fill — close the SPY spread by hand in TWS now "
            "(SPY settles in shares)"
        )
        return
    print(fill_sign_verdict("close", float(trade.orderStatus.avgFillPrice)))
    await asyncio.sleep(3)
    _print_fills("close", trade)


async def _main(short: float, long_: float, wait: float, fill: bool) -> None:
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
        if fill:
            await _fill_round_trip(ib, sc, legs, cand)
            return
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
            if str(getattr(t.order, "orderRef", "")).startswith(
                f"{sc.order_ref_prefix}combo-check"
            ):
                ib.cancelOrder(t.order)
        await asyncio.sleep(2)
        ib.disconnect()


def main() -> None:
    setup_logging()
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--short", type=float, required=True)
    p.add_argument("--long", type=float, required=True)
    p.add_argument("--wait", type=float, default=60.0)
    p.add_argument(
        "--fill",
        action="store_true",
        help="open AND close a fillable one-lot and check IBKR's fill-price signs",
    )
    a = p.parse_args()
    asyncio.run(_main(a.short, a.long, a.wait, a.fill))


if __name__ == "__main__":
    main()
