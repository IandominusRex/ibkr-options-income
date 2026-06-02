"""Portfolio & account readers built on a live ib_async.IB connection.

Converts raw ib_async objects into the typed schemas the rest of the system uses.
Phase 1 extends this (Greeks enrichment, margin detail); Phase 0 needs positions
and an account snapshot for the healthcheck.
"""

from __future__ import annotations

import asyncio
from datetime import date

from ib_async import IB

from src.common.config import get_config
from src.common.logging import get_logger
from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot

log = get_logger(__name__)


def _safe_num(val: object) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN check


async def enrich_positions_with_greeks_async(
    ib: IB, positions: list[PositionSnapshot]
) -> list[PositionSnapshot]:
    """Populate `.delta` on every option position in-place from live model greeks.

    `get_positions` returns positions without greeks (the portfolio feed carries none), so
    any consumer that needs net-delta exposure (the EOD report) must enrich first — otherwise
    delta is always None and net delta reads 0. Best-effort: positions whose greeks don't
    stream in time keep delta=None. Runs on the ib_async loop thread.
    """
    from typing import Any

    from src.ibkr.contracts import build_option

    opt_positions = [
        p
        for p in positions
        if p.sec_type == "OPT" and p.strike and p.expiry and p.right is not None
    ]
    if not opt_positions:
        return positions

    wait = get_config().market_data.quote_sleep_seconds
    subscribed: list[tuple[PositionSnapshot, Any, Any]] = []
    for p in opt_positions:
        # Re-checked for the type-narrower; the comprehension above already guarantees these.
        if p.strike is None or p.expiry is None or p.right is None:
            continue
        try:
            contract = build_option(p.underlying or p.symbol, p.expiry, p.strike, p.right.value)
            ticker = ib.reqMktData(contract, "", False, False)
            subscribed.append((p, ticker, contract))
        except Exception:
            log.exception("greeks enrich: reqMktData failed for %s", p.symbol)

    # Give model greeks a moment to populate, then read + cancel.
    await asyncio.sleep(max(wait, 2.0))
    for p, ticker, contract in subscribed:
        greeks = getattr(ticker, "modelGreeks", None)
        if greeks is not None:
            p.delta = _safe_num(getattr(greeks, "delta", None))
        try:
            ib.cancelMktData(contract)
        except Exception:
            pass
    log.info("greeks enrich: updated delta on %d option position(s)", len(subscribed))
    return positions


def _parse_expiry(yyyymmdd: str) -> date | None:
    if not yyyymmdd:
        return None
    try:
        return date(int(yyyymmdd[0:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8]))
    except (ValueError, IndexError):
        return None


def get_positions(ib: IB) -> list[PositionSnapshot]:
    """Snapshot current positions (stocks and options) as typed objects."""
    out: list[PositionSnapshot] = []
    for item in ib.portfolio():
        c = item.contract
        right = None
        strike = None
        expiry = None
        underlying = c.symbol
        if c.secType == "OPT":
            right = OptionRight.CALL if c.right.upper().startswith("C") else OptionRight.PUT
            strike = c.strike
            expiry = _parse_expiry(c.lastTradeDateOrContractMonth)
        out.append(
            PositionSnapshot(
                symbol=c.localSymbol or c.symbol,
                sec_type=c.secType,
                position=item.position,
                avg_cost=item.averageCost,
                market_price=item.marketPrice or None,
                market_value=item.marketValue or None,
                unrealized_pnl=item.unrealizedPNL or None,
                right=right,
                strike=strike,
                expiry=expiry,
                underlying=underlying,
            )
        )
    log.info("Fetched %d portfolio positions", len(out))
    return out


def get_account_snapshot(ib: IB, account: str) -> AccountSnapshot:
    """Pull key account values into a typed snapshot."""
    rows = {row.tag: row.value for row in ib.accountSummary(account)}

    def f(tag: str) -> float:
        try:
            return float(rows.get(tag, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    snap = AccountSnapshot(
        account=account,
        net_liquidation=f("NetLiquidation"),
        total_cash=f("TotalCashValue"),
        # AvailableFunds = equity minus initial margin requirements, not the 2–4× leveraged
        # BuyingPower tag which would overstate available capital for margin accounts.
        buying_power=f("AvailableFunds"),
        maintenance_margin=f("MaintMarginReq"),
        excess_liquidity=f("ExcessLiquidity"),
    )
    log.info(
        "Account %s — NetLiq=%.2f AvailFunds=%.2f ExcessLiq=%.2f",
        account,
        snap.net_liquidation,
        snap.buying_power,
        snap.excess_liquidity,
    )
    return snap
