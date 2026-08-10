"""What can this system actually trade today, and what binds first?

The test suite verifies that gates reject what they claim to reject; it never asked whether
the account can reach the universe at all. That blind spot is why a 1-lot CSP silently
required ``NLV >= 2000 x strike`` (D1) and why the income floor silently excluded every
low-vol name (D2) — both passed every test.

Run:
    python -m scripts.capacity_report              # live account via IBKR
    python -m scripts.capacity_report --net-liq 300000 --cash 100000   # hypothetical
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from src.common.config import get_config
from src.common.schemas import AccountSnapshot, PositionSnapshot
from src.engine.capital import max_contracts, resolve_caps, seed_budgets


@dataclass(frozen=True)
class CapacityRow:
    symbol: str
    spot: float
    contracts: int
    binding: str
    collateral: float
    nlv_needed_for_one: float


def build_report(
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    universe_symbols: list[str],
    iv_by_symbol: dict[str, float],
    price_by_symbol: dict[str, float],
) -> list[CapacityRow]:
    """One row per symbol: how many contracts fit, and which constraint stops the next one.

    Strike is approximated as 0.90 x spot, a stand-in for the ~0.25-delta put the screens
    target. This is a capacity estimate, not a quote.

    ``seed_budgets`` is called fresh *inside* the per-symbol loop (deliberate): a capacity
    report answers "what could this symbol do on its own" — the headroom it would see if it
    were the only candidate — not "what fits after the others already took their share." The
    real scan consumes one shared ``Budgets`` greedily across candidates (see
    ``engine.capital.charge``); this report intentionally does not, so every row is an
    independent, single-symbol capacity check.
    """
    cfg = get_config()
    risk = cfg.risk
    caps = resolve_caps(account, risk)
    sector_of = cfg.universe.get("sectors", {}).get
    hard_max = int(risk.get("cash_secured_put", {}).get("max_contracts", 10))
    dte = 30

    rows: list[CapacityRow] = []
    for symbol in universe_symbols:
        spot = price_by_symbol.get(symbol, 0.0)
        if spot <= 0:
            continue
        strike = round(spot * 0.90, 2)
        unit = strike * 100
        budgets = seed_budgets(positions, sector_of)
        n, binding = max_contracts(
            unit_collateral=unit,
            current_iv=iv_by_symbol.get(symbol),
            dte=dte,
            symbol=symbol,
            sector=sector_of(symbol),
            caps=caps,
            budgets=budgets,
            hard_max=hard_max,
        )
        ticker_pct = float(risk.get("portfolio", {}).get("max_collateral_per_ticker_pct", 10.0))
        rows.append(
            CapacityRow(
                symbol=symbol,
                spot=spot,
                contracts=n,
                binding=binding,
                collateral=unit * n,
                nlv_needed_for_one=unit / (ticker_pct / 100.0) if ticker_pct > 0 else 0.0,
            )
        )
    return rows


def format_report(rows: list[CapacityRow]) -> str:
    """Render the table. Handles an empty *rows* without a ZeroDivisionError."""
    header = f"{'SYMBOL':<8}{'SPOT':>10}{'LOTS':>6}{'COLLATERAL':>13}  {'BINDING'}"
    lines = [header, "-" * len(header)]
    for r in sorted(rows, key=lambda x: (-x.contracts, x.symbol)):
        lines.append(
            f"{r.symbol:<8}{r.spot:>10.2f}{r.contracts:>6}{r.collateral:>13,.0f}  "
            f"{r.binding or 'none (hit hard_max)'}"
        )
    tradeable = sum(1 for r in rows if r.contracts >= 1)
    lines.append("")
    if not rows:
        lines.append("0 symbols had price/IV data — no report to show.")
    else:
        lines.append(f"{tradeable}/{len(rows)} symbols tradeable at this account size.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Report tradeable capacity per symbol.")
    parser.add_argument("--net-liq", type=float, default=None)
    parser.add_argument("--cash", type=float, default=None)
    args = parser.parse_args()

    cfg = get_config()
    symbols = sorted(set(cfg.universe.get("would_own", [])))

    if args.net_liq is not None and args.cash is not None:
        account = AccountSnapshot(
            account="hypothetical",
            net_liquidation=args.net_liq,
            total_cash=args.cash,
            buying_power=args.cash,
            maintenance_margin=0.0,
            excess_liquidity=args.cash,
        )
        positions: list[PositionSnapshot] = []
    else:
        # Reuse the existing "healthcheck" clientId/role (settings.yaml -> ibkr.client_ids) —
        # this is a read-only report, so it rides the same connection pattern
        # scripts/healthcheck.py uses rather than opening a new one.
        from src.ibkr.connection import IBKRConnection
        from src.ibkr.portfolio import get_account_snapshot, get_positions

        conn = IBKRConnection("healthcheck")
        with conn as ib:
            account_id = conn.resolve_account()
            account = get_account_snapshot(ib, account_id)
            positions = get_positions(ib)

    from src.analytics.iv import get_iv_stats
    from src.analytics.technicals import get_technical_stats

    iv_by_symbol: dict[str, float] = {}
    price_by_symbol: dict[str, float] = {}
    for sym in symbols:
        stats = get_iv_stats(sym)
        if stats.current_iv:
            iv_by_symbol[sym] = stats.current_iv
        tech = get_technical_stats(sym)
        if tech.price:
            price_by_symbol[sym] = tech.price

    print(format_report(build_report(account, positions, symbols, iv_by_symbol, price_by_symbol)))


if __name__ == "__main__":
    main()
