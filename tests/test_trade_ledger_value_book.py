"""Part 6 Task 12: value fills are their own book in the whole-account trade ledger.

A fill the value book made (``book="value"``, tagged at ingest from the broker's ``orderRef``)
keeps that word on its trade; the wheel's per-ticker share count and wheel-adjusted cost basis
ignore it (matching ``src/storage/wheel_shares``); the whole-account totals still count it,
because the ledger is the account's truth.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.reporting.trade_ledger import _merge_book, group_orders
from tests.conftest import OWNER
from tests.test_trade_ledger_book import WHEEL, _book
from tests.test_trade_ledger_trades import ex, trades_of

# A value-book position in the same name the wheel trades: 50 shares bought, 20 sold.
VALUE_BUY = ex("AMZN", "2025-10-06, 10:00:00", 50, 100.0, comm=-1.0, codes="O", book="value")
VALUE_SELL = ex("AMZN", "2025-10-08, 10:00:00", -20, 110.0, comm=-1.0, codes="C", book="value")


def test_a_value_execution_keeps_its_book_on_the_trade() -> None:
    (trade,), _ = trades_of(
        ex("MU 20NOV26 90 P", "2026-10-01, 10:00:00", -1, 2.0, codes="O", book="value")
    )
    assert trade.book == "value"
    (other,), _ = trades_of(
        ex("MU 20NOV26 90 P", "2026-10-01, 10:00:00", -1, 2.0, codes="O", book="system")
    )
    assert other.book == "system"


def test_a_mixed_order_merges_spreads_first_then_value_then_system() -> None:
    assert _merge_book(["system", "value"]) == "value"
    assert _merge_book(["manual", "value", "system"]) == "value"
    assert _merge_book(["value", "spreads"]) == "spreads"
    assert _merge_book(["system", "manual"]) == "system"
    assert _merge_book(["manual"]) == "manual"
    # through group_orders: two partial fills of one order, tagged differently
    a = ex("MU 20NOV26 90 P", "2026-10-01, 10:00:00", -1, 2.0, codes="O", perm=7, book="system")
    b = ex("MU 20NOV26 90 P", "2026-10-01, 10:00:01", -1, 2.0, codes="O", perm=7, book="value")
    (order,) = group_orders([a, b])
    assert order.book == "value"


def test_a_shared_names_wheel_basis_ignores_value_buys_and_sells() -> None:
    wheel = WHEEL[:4]  # CSP assigned at 215, a covered call open
    _, _, _, plain, _ = _book(wheel, date(2025, 10, 21))
    _, lots, _, shared, _ = _book([*wheel, VALUE_BUY, VALUE_SELL], date(2025, 10, 21))
    (p,), (s,) = plain, shared
    assert s.shares_held == p.shares_held == 100
    assert s.broker_avg_cost == pytest.approx(215.0)
    assert s.wheel_adjusted_basis == pytest.approx(p.wheel_adjusted_basis)
    # the value shares exist as their own lot (30 left), never merged into the wheel's lot
    assert sorted(lot.remaining for lot in lots) == [30.0, 100.0]
    assert {lot.book for lot in lots} == {"value", "manual"}


def test_the_accounts_realised_total_still_counts_the_value_sale() -> None:
    wheel = WHEEL[:4]
    *_, plain = _book(wheel, date(2025, 10, 21))
    _, _, disposals, _, shared = _book([*wheel, VALUE_BUY, VALUE_SELL], date(2025, 10, 21))
    (d,) = disposals
    # 20 shares: sold at 110 less 1.0 commission each way pro rata, cost 100 plus its commission
    gain = (110.0 - 100.0) * 20 - 1.0 - 0.4
    assert d.realized == pytest.approx(gain, abs=0.01)
    assert shared.total_realized_usd == pytest.approx(plain.total_realized_usd + gain, abs=0.01)


def test_the_trades_route_filters_by_the_value_book(client, api_db) -> None:
    from src.storage.models import BrokerExecutionRow

    def row(n: int, book: str, contract: str, underlying: str):
        return BrokerExecutionRow(
            dedupe_key=f"live-{n}",
            source_kind="exec",
            source="live",
            exec_id=f"0000{n}",
            perm_id=900 + n,
            ib_order_id=10 + n,
            account="DU1",
            trade_time=datetime(2026, 10, 20, 14, 31, 7),
            trade_date=date(2026, 10, 20),
            contract_ident=contract,
            underlying=underlying,
            sec_type="OPT",
            right="P",
            strike=165.0,
            expiry=date(2026, 11, 20),
            multiplier=100.0,
            currency="USD",
            quantity=-1.0,
            price=2.35,
            proceeds=235.0,
            commission=-1.3,
            codes="O",
            book=book,
        )

    with api_db() as s:
        s.add_all(
            [
                row(1, "system", "NVDA 20261120 165 P", "NVDA"),
                row(2, "value", "MU 20261120 165 P", "MU"),
            ]
        )
    body = client.get("/ledger/trades?book=value", headers=OWNER).json()
    assert body["n"] == 1 and body["trades"][0]["underlying"] == "MU"
    assert body["trades"][0]["book"] == "value" and body["filters"]["book"] == "value"
    assert client.get("/ledger/trades?book=bogus", headers=OWNER).status_code == 422
