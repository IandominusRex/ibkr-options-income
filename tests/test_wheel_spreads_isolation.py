"""The wheel's view of the account never contains a spreads-book leg.

Every wheel consumer of broker positions — the intraday monitor, profit-take, rolls, the scan's
budget seeding (`capital.seed_budgets` would charge a SPY short put strike×100 ≈ $69k of CSP
collateral), the approval re-gate, the EOD report — goes through `get_positions`, so one
default-on filter there is the whole separation.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.ibkr.portfolio import get_positions

ROOT = Path(__file__).resolve().parents[1]


def _item(symbol: str, *, strike: float = 690.0, right: str = "P", position: float = -1.0):
    contract = SimpleNamespace(
        symbol=symbol,
        localSymbol=f"{symbol} 261007{right}{strike:g}",
        secType="OPT",
        right=right,
        strike=strike,
        lastTradeDateOrContractMonth="20261007",
    )
    return SimpleNamespace(
        contract=contract,
        position=position,
        averageCost=50.0,
        marketPrice=0.5,
        marketValue=-50.0,
        unrealizedPNL=10.0,
    )


def _ib(*items):
    ib = MagicMock()
    ib.portfolio.return_value = list(items)
    return ib


def test_wheel_view_drops_spreads_book_legs() -> None:
    ib = _ib(
        _item("SPY"),
        _item("SPY", strike=685.0, position=1.0),
        _item("XSP"),
        _item("AAPL", strike=200.0),
    )
    assert [p.underlying for p in get_positions(ib)] == ["AAPL"]


def test_spx_legs_are_spreads_book_too() -> None:
    assert get_positions(_ib(_item("SPX", strike=6900.0))) == []


def test_account_truth_view_keeps_them() -> None:
    ib = _ib(_item("SPY"), _item("AAPL", strike=200.0))
    got = sorted(p.underlying or "" for p in get_positions(ib, include_spreads=True))
    assert got == ["AAPL", "SPY"]


def test_upro_is_still_a_wheel_position() -> None:
    assert [p.underlying for p in get_positions(_ib(_item("UPRO", strike=600.0)))] == ["UPRO"]


def test_only_the_healthcheck_asks_for_spreads_positions() -> None:
    """A wheel call site passing include_spreads=True would re-open every coupling above."""
    allowed = {"scripts/healthcheck.py", "src/ibkr/portfolio.py"}
    offenders = [
        str(p.relative_to(ROOT))
        for d in ("src", "scripts")
        for p in sorted((ROOT / d).rglob("*.py"))
        if "include_spreads=True" in p.read_text(encoding="utf-8")
        and str(p.relative_to(ROOT)) not in allowed
    ]
    assert offenders == []
