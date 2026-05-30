"""Portfolio & account readers built on a live ib_async.IB connection.

Converts raw ib_async objects into the typed schemas the rest of the system uses.
Phase 1 extends this (Greeks enrichment, margin detail); Phase 0 needs positions
and an account snapshot for the healthcheck.
"""

from __future__ import annotations

from datetime import date

from ib_async import IB

from src.common.logging import get_logger
from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot

log = get_logger(__name__)


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
        buying_power=f("BuyingPower"),
        maintenance_margin=f("MaintMarginReq"),
        excess_liquidity=f("ExcessLiquidity"),
    )
    log.info(
        "Account %s — NetLiq=%.2f BuyingPower=%.2f ExcessLiq=%.2f",
        account,
        snap.net_liquidation,
        snap.buying_power,
        snap.excess_liquidity,
    )
    return snap
