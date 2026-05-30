"""Phase 0 acceptance check.

Verifies the full foundation: config loads, the DB initializes, we can connect to
TWS/Gateway, and we can read the account + positions.

Run:
    python -m scripts.healthcheck

Requires TWS or IB Gateway running with the API enabled on the configured port
(paper 7497 by default). Uses the 'healthcheck' clientId so it won't clash with
other processes.
"""

from __future__ import annotations

import sys

from src.common.config import get_config
from src.common.logging import get_logger
from src.ibkr.connection import IBKRConnection
from src.ibkr.portfolio import get_account_snapshot, get_positions
from src.storage.db import init_db

log = get_logger("healthcheck")


def main() -> int:
    cfg = get_config()
    mode = "LIVE" if cfg.is_live else "PAPER"
    print(f"\n=== IBKR Income System — Healthcheck ({mode}) ===\n")

    # 1. Config sanity
    print(f"DB URL            : {cfg.db_url_abs()}")
    print(f"IBKR endpoint     : {cfg.ibkr.host}:{cfg.ibkr_port}")
    print(f"Universe watchlist: {cfg.universe.get('watchlist', [])}")
    print(f"CSP would-own     : {cfg.universe.get('would_own', [])}")
    tele = "set" if cfg.secrets.telegram_bot_token else "MISSING (.env)"
    print(f"Telegram token    : {tele}")

    # 2. DB init
    init_db()
    print("Database          : initialized OK")

    # 3. Connect + read
    conn = IBKRConnection("healthcheck")
    try:
        ib = conn.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"\n[FAIL] Could not connect to IBKR: {exc}")
        print("Is TWS/Gateway running with API enabled on the configured port?")
        return 1

    try:
        account = conn.resolve_account()
        print(f"\nAccount           : {account}")
        snap = get_account_snapshot(ib, account)
        print(f"  Net liquidation : {snap.net_liquidation:,.2f}")
        print(f"  Buying power    : {snap.buying_power:,.2f}")
        print(f"  Excess liquidity: {snap.excess_liquidity:,.2f}")

        positions = get_positions(ib)
        print(f"\nPositions ({len(positions)}):")
        if not positions:
            print("  (none)")
        for p in positions:
            extra = ""
            if p.sec_type == "OPT":
                extra = f" {p.right} {p.strike} exp {p.expiry}"
            print(f"  {p.symbol:<22} {p.position:>8.0f} @ {p.avg_cost:>10.2f}{extra}")
    finally:
        conn.disconnect()

    print("\n[OK] Healthcheck passed.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
