"""Stock lots, wheel cost basis, tickers, FX, summary, build_book (spec §4.3-4.5; R4, R5)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.common.schemas import LedgerCashItem, PortfolioSnapshot, PositionSnapshot
from src.reporting.trade_ledger import (
    FxTable,
    attach_stock_gains,
    build_option_trades,
    build_stock_lots,
    build_summary,
    build_tickers,
    group_orders,
)
from tests.test_trade_ledger_trades import ex

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"

# The AMZN wheel from the operator's real statement: CSP 215P -> assigned -> CC 235C -> called away.
WHEEL = [
    ex("AMZN 10OCT25 215 P", "2025-10-03, 14:45:08", -1, 1.77, comm=-1.1430721, codes="O"),
    ex("AMZN 10OCT25 215 P", "2025-10-10, 16:20:00", 1, 0.0, comm=0.0, codes="A;C"),
    ex("AMZN", "2025-10-10, 16:20:00", 100, 215.0, comm=0.0, codes="A;O"),
    ex("AMZN 31OCT25 235 C", "2025-10-20, 10:30:00", -1, 4.01, comm=-1.0, codes="O"),
    ex("AMZN 31OCT25 235 C", "2025-10-31, 16:20:00", 1, 0.0, comm=0.0, codes="A;C"),
    ex("AMZN", "2025-10-31, 16:20:00", -100, 235.0, comm=-0.018094, codes="A;C"),
]


def _book(execs, today, cash=(), snapshot=None, fx=None):
    orders = group_orders(list(execs))
    trades, orphans = build_option_trades(orders, today=today)
    lots, disposals, stock_orphans = build_stock_lots(orders)
    attach_stock_gains(trades, disposals)
    tickers = build_tickers(trades, lots, disposals, list(cash), snapshot=snapshot)
    summary = build_summary(
        trades,
        tickers,
        lots,
        disposals,
        list(cash),
        fx or FxTable({}, 7),
        today=today,
        snapshot=snapshot,
        orphans=orphans + stock_orphans,
        unreviewed_corporate_actions=0,
        marks_as_of=None,
    )
    return trades, lots, disposals, tickers, summary


def test_wheel_lot_disposal_and_stock_gain() -> None:
    trades, lots, disposals, tickers, _ = _book(WHEEL, date(2025, 11, 5))
    (lot,) = lots
    assert (lot.source, lot.cost_per_share, lot.remaining) == ("assigned", 215.0, 0.0)
    (d,) = disposals
    assert d.realized == pytest.approx(1999.98, abs=0.01)
    call = next(t for t in trades if t.right == "C")
    assert call.outcome == "Called away" and call.stock_gain == pytest.approx(1999.98, abs=0.01)
    (amzn,) = tickers
    assert amzn.total_realized == pytest.approx(175.857 + 400.0 + 1999.982, abs=0.01)
    assert amzn.shares_held == 0 and amzn.wheel_adjusted_basis is None


def test_wheel_adjusted_basis_while_the_call_is_open() -> None:
    _, _, _, tickers, _ = _book(WHEEL[:4], date(2025, 10, 21))
    (amzn,) = tickers
    assert amzn.shares_held == 100
    assert amzn.broker_avg_cost == pytest.approx(215.0)
    assert amzn.wheel_adjusted_basis == pytest.approx((21500 - 175.857 - 400.0) / 100, abs=1e-3)


def test_stock_sold_before_history_is_an_orphan_with_ibkr_realized() -> None:
    _, lots, disposals, _, summary = _book(
        [ex("MSTY", "2026-03-30, 11:19:46", -20, 21.55, codes="C;IA", realized=-973.37)],
        date(2026, 4, 1),
    )
    assert lots == [] and disposals == []
    assert summary.orphan_closes == 1
    assert summary.total_realized_usd == pytest.approx(-973.37)


def test_fx_conversion_and_missing_rate_flag() -> None:
    sgd_lot = [ex("A17U", "2025-07-17, 01:31:33", 500, 2.77, comm=-2.725, currency="SGD")]
    _, _, _, _, missing = _book(sgd_lot, date(2025, 7, 20))
    assert missing.fx_incomplete is True
    fx = FxTable({"SGD": [(date(2025, 7, 16), 0.78)]}, 7)
    _, _, _, _, ok = _book(sgd_lot, date(2025, 7, 20), fx=fx)
    assert ok.fx_incomplete is False
    assert ok.capital_utilised_usd == pytest.approx((1385 + 2.725) * 0.78, abs=0.01)


def test_fx_table_respects_max_gap() -> None:
    fx = FxTable({"SGD": [(date(2025, 1, 1), 0.75)]}, 7)
    assert fx.to_usd(100, "SGD", date(2025, 1, 5)) == pytest.approx(75.0)
    assert fx.to_usd(100, "SGD", date(2025, 2, 1)) is None
    assert fx.to_usd(100, "USD", date(2025, 2, 1)) == 100


def test_contributed_unknown_without_deposits_and_available_formula() -> None:
    _, _, _, _, s = _book(WHEEL, date(2025, 11, 5))
    assert s.contributed_usd is None and s.available_usd is None
    cash = [
        LedgerCashItem(
            event_date=date(2025, 5, 26),
            event_type="deposit",
            currency="USD",
            amount=45000.0,
            description="EFT",
        )
    ]
    _, _, _, _, s2 = _book(WHEEL, date(2025, 11, 5), cash=cash)
    assert s2.contributed_usd == 45000.0
    assert s2.available_usd == pytest.approx(
        45000.0 + s2.total_realized_usd - s2.capital_utilised_usd
    )


def test_capital_utilised_counts_open_short_put_collateral() -> None:
    _, _, _, _, s = _book(
        [ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:00", -2, 1.9)], date(2025, 7, 20)
    )
    assert s.capital_utilised_usd == pytest.approx(170 * 100 * 2)


def test_excluded_trade_counts_in_money_not_in_win_rate() -> None:
    trades, lots, disposals, _, _ = _book(WHEEL, date(2025, 11, 5))
    for t in trades:
        t.exclude_from_stats = True
    tickers = build_tickers(trades, lots, disposals, [], snapshot=None)
    assert tickers[0].win_rate is None
    assert tickers[0].option_net_pnl == pytest.approx(575.857, abs=0.01)


def test_unrealized_is_none_without_a_snapshot_and_summed_with_one() -> None:
    open_put = [ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:00", -1, 1.9)]
    _, _, _, tickers, _ = _book(open_put, date(2025, 7, 20))
    assert tickers[0].unrealized is None
    snap = PortfolioSnapshot(
        captured_at=datetime(2025, 7, 20, 15, tzinfo=UTC),
        source="monitor",
        positions=[
            PositionSnapshot.model_validate(
                {
                    "symbol": "NVDA 250725P00170000",
                    "sec_type": "OPT",
                    "underlying": "NVDA",
                    "position": -1,
                    "avg_cost": 190.0,
                    "unrealized_pnl": 55.0,
                }
            )
        ],
    )
    _, _, _, tickers2, _ = _book(open_put, date(2025, 7, 20), snapshot=snap)
    assert tickers2[0].unrealized == 55.0


def test_build_book_end_to_end_from_the_fixture(db) -> None:
    from src.ledger.activity_csv import parse_activity_csv
    from src.ledger.ingest import ingest
    from src.reporting.trade_ledger import build_book, ticker_detail

    ingest(parse_activity_csv(FIXTURE.read_text()), source="csv")
    with db() as s:
        book = build_book(s, today=date(2026, 10, 5), snapshot=None)
    nvda = next(t for t in book.trades if t.underlying == "NVDA")
    assert round(nvda.pct_profit, 2) == 34.65
    assert {t.symbol for t in book.tickers} >= {"AMZN", "NVDA", "OPEN", "QDTE", "A17U"}
    amzn = ticker_detail(book, "AMZN")
    assert amzn is not None and len(amzn.trades) == 3 and len(amzn.disposals) == 1
    # A17U (SGD, Jul 2025) has no FX rate within 7 days; the SGD withdrawal (2026-01-02) converts
    # at the fixture's USD.SGD forex trade (2026-01-06, 4 days away).
    assert book.summary.fx_incomplete is True
    assert book.summary.contributed_usd == pytest.approx(45000 - 6371.24 / 1.2795, abs=0.01)
    assert book.summary.unreviewed_corporate_actions == 1


def test_build_book_ignores_a_snapshot_from_a_different_account(db) -> None:
    """F5: the live PortfolioSnapshot is captured from the paper account while the ledger
    tracks the real one. A snapshot whose account differs from the locked ledger account must
    be treated as no snapshot at all (unrealized None), never borrowed across accounts."""
    from src.common.schemas import AccountSnapshot, LedgerContract, ParsedExecution, ParsedStatement
    from src.ledger.ingest import ingest
    from src.ledger.state import ledger_account
    from src.reporting.trade_ledger import build_book

    stmt = ParsedStatement(
        account="U0000001",
        executions=[
            ParsedExecution(
                contract=LedgerContract(
                    underlying="NVDA",
                    sec_type="OPT",
                    right="P",
                    strike=170.0,
                    expiry=date(2025, 7, 25),
                    multiplier=100.0,
                ),
                trade_time=datetime(2025, 7, 18, 14, 0, tzinfo=UTC),
                quantity=-1,
                price=1.9,
                proceeds=190.0,
                commission=-1.0,
                codes="O",
                source_kind="order",
            )
        ],
    )
    ingest(stmt, source="csv", filename=None)
    snap = PortfolioSnapshot(
        captured_at=datetime(2025, 7, 20, 15, tzinfo=UTC),
        source="monitor",
        account=AccountSnapshot(
            account="DU999999",
            net_liquidation=0.0,
            total_cash=0.0,
            buying_power=0.0,
            maintenance_margin=0.0,
            excess_liquidity=0.0,
        ),
        positions=[
            PositionSnapshot.model_validate(
                {
                    "symbol": "NVDA 250725P00170000",
                    "sec_type": "OPT",
                    "underlying": "NVDA",
                    "position": -1,
                    "avg_cost": 190.0,
                    "unrealized_pnl": 55.0,
                }
            )
        ],
    )
    with db() as s:
        # Not vacuous: the ingest above really did lock the ledger account to the statement's
        # account, so the gate below is comparing against a real value, not None == None.
        assert ledger_account(s) == "U0000001"
        book = build_book(s, today=date(2025, 7, 20), snapshot=snap)
    nvda = next(t for t in book.tickers if t.symbol == "NVDA")
    assert nvda.unrealized is None
    assert book.summary.unrealized_usd is None


def test_build_book_uses_a_snapshot_from_the_matching_account(db) -> None:
    """F5 happy path: a snapshot whose account matches the locked ledger account must still
    reach unrealized/marks — the gate only drops a snapshot from a *different* account."""
    from src.common.schemas import AccountSnapshot, LedgerContract, ParsedExecution, ParsedStatement
    from src.ledger.ingest import ingest
    from src.ledger.state import ledger_account
    from src.reporting.trade_ledger import build_book

    stmt = ParsedStatement(
        account="U0000001",
        executions=[
            ParsedExecution(
                contract=LedgerContract(
                    underlying="NVDA",
                    sec_type="OPT",
                    right="P",
                    strike=170.0,
                    expiry=date(2025, 7, 25),
                    multiplier=100.0,
                ),
                trade_time=datetime(2025, 7, 18, 14, 0, tzinfo=UTC),
                quantity=-1,
                price=1.9,
                proceeds=190.0,
                commission=-1.0,
                codes="O",
                source_kind="order",
            )
        ],
    )
    ingest(stmt, source="csv", filename=None)
    snap = PortfolioSnapshot(
        captured_at=datetime(2025, 7, 20, 15, tzinfo=UTC),
        source="monitor",
        account=AccountSnapshot(
            account="U0000001",
            net_liquidation=0.0,
            total_cash=0.0,
            buying_power=0.0,
            maintenance_margin=0.0,
            excess_liquidity=0.0,
        ),
        positions=[
            PositionSnapshot.model_validate(
                {
                    "symbol": "NVDA 250725P00170000",
                    "sec_type": "OPT",
                    "underlying": "NVDA",
                    "position": -1,
                    "avg_cost": 190.0,
                    "unrealized_pnl": 55.0,
                }
            )
        ],
    )
    with db() as s:
        assert ledger_account(s) == "U0000001"
        book = build_book(s, today=date(2025, 7, 20), snapshot=snap)
    nvda = next(t for t in book.tickers if t.symbol == "NVDA")
    assert nvda.unrealized == 55.0
    assert book.summary.unrealized_usd == 55.0


def test_summary_unrealized_is_none_when_any_open_ticker_has_no_mark() -> None:
    """I2: a partial sum is never reported as the account's unrealized."""
    execs = [
        ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:00", -1, 1.9),
        ex("AMZN 25JUL25 200 P", "2025-07-18, 10:00:00", -1, 2.0),
    ]
    snap = PortfolioSnapshot(
        captured_at=datetime(2025, 7, 20, 15, tzinfo=UTC),
        source="monitor",
        positions=[
            PositionSnapshot.model_validate(
                {
                    "symbol": "NVDA 250725P00170000",
                    "sec_type": "OPT",
                    "underlying": "NVDA",
                    "position": -1,
                    "avg_cost": 190.0,
                    "unrealized_pnl": 55.0,
                }
            )
        ],
    )
    _, _, _, tickers, summary = _book(execs, date(2025, 7, 20), snapshot=snap)
    assert {t.symbol: t.unrealized for t in tickers} == {"NVDA": 55.0, "AMZN": None}
    assert summary.unrealized_usd is None
