"""Shared helpers for the value book's Stage 3 tests (Part 5): value orders, proposals and funding
requests written the way src/value writes them. The ``value_book_db`` fixture (a value.db in tmp,
with value_view pointed at it) is in tests/conftest.py."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.value.store import ValueFundingRow, ValueOrderRow, ValueProposalRow, value_session

NOW = datetime(2026, 11, 2, 15, 0)  # naive UTC: 10:00 ET, a Monday


def order(
    symbol: str,
    *,
    side: str = "buy",
    shares: float = 10,
    filled: float = 10,
    avg: float | None = 100.0,
    status: str = "filled",
    list_name: str = "deep_value",
) -> int:
    with value_session() as s:
        row = ValueOrderRow(
            symbol=symbol,
            list_name=list_name,
            side=side,
            shares=shares,
            filled=filled,
            avg_price=avg,
            status=status,
            created_at=NOW,
        )
        s.add(row)
        s.flush()
        row.order_ref = f"value:{row.id}"
        return row.id


def proposal(symbol: str, *, status: str = "approved", cost: float = 1000.0, kind: str = "buy"):
    with value_session() as s:
        row = ValueProposalRow(
            kind=kind,
            symbol=symbol,
            list_name="deep_value",
            shares=10,
            price=cost / 10,
            cost_usd=cost,
            reason="tranche 1",
            status=status,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=30),
        )
        s.add(row)
        s.flush()
        return row.id


def funding(symbol: str, needed: float, *, proposal_id: int = 1, status: str = "open", hours=30):
    with value_session() as s:
        row = ValueFundingRow(
            proposal_id=proposal_id,
            symbol=symbol,
            needed_usd=needed,
            status=status,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=hours),
        )
        s.add(row)
        s.flush()
        return row.id
