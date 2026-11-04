"""Shared helpers for the value book's Stage 3 tests (Part 5): value orders, proposals and funding
requests written the way src/value writes them. The ``value_book_db`` fixture (a value.db in tmp,
with value_view pointed at it) is in tests/conftest.py."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from src.value.store import (
    ValueEffectiveRow,
    ValueFundingRow,
    ValueOrderRow,
    ValueProposalRow,
    ValueTickerFileRow,
    value_session,
)

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


def funding(
    symbol: str,
    needed: float,
    *,
    proposal_id: int = 1,
    status: str = "open",
    hours=30,
    as_of: datetime | None = NOW,
):
    with value_session() as s:
        row = ValueFundingRow(
            proposal_id=proposal_id,
            symbol=symbol,
            needed_usd=needed,
            status=status,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=hours),
            as_of=as_of,
        )
        s.add(row)
        s.flush()
        return row.id


def ticker_file(
    symbol: str,
    *,
    as_of: date = date(2026, 11, 2),
    computed_at: datetime = NOW,
    universe: str = "trading",
    verdict_deep: str = "READY",
    verdict_growth: str = "NO",
    rank_deep: float | None = 80.0,
    rank_growth: float | None = None,
    fair_value_deep: float | None = 140.0,
    mos_deep: float | None = 0.3,
    price: float | None = 98.0,
    effective: dict[str, tuple[str, str]] | None = None,
) -> None:
    """A ``value_ticker_files`` row (summary columns only) and, per list, its ``value_effective`` row."""
    with value_session() as s:
        s.add(
            ValueTickerFileRow(
                symbol=symbol,
                computed_at=computed_at,
                as_of=as_of,
                universe=universe,
                fingerprint_key="k" * 16,
                fingerprint_json="{}",
                ruleset_version="v4",
                ruleset_hash="be30d1eaa915",
                company_class="operating",
                data_quality="pass",
                health="pass",
                verdict_deep=verdict_deep,
                verdict_growth=verdict_growth,
                fair_value_deep=fair_value_deep,
                mos_deep=mos_deep,
                rank_deep=rank_deep,
                rank_growth=rank_growth,
                price=price,
                summary_json="{}",
                scorecard_json="{}",
            )
        )
        for list_name, (verdict, by) in (effective or {}).items():
            s.add(
                ValueEffectiveRow(
                    symbol=symbol,
                    list_name=list_name,
                    as_of=as_of,
                    verdict=verdict,
                    decided_by=by,
                    python_verdict=verdict,
                    updated_at=computed_at,
                )
            )
