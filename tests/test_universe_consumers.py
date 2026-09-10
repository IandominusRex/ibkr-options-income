"""An override changes what the system does. Except where it must not.

M7 Task 7.3: six trading-code call sites were migrated to read `would_own`/`watchlist`
through `effective_universe()` (`src/common/universe.py`, Task 7.2) instead of straight off
`get_config().universe`. This file proves the migration actually took at the *consumer*
level — an override written to `universe_overrides` must change what
`generate_csp_candidates` returns, not just what the composer computes in isolation — and
proves the two call sites this milestone explicitly forbids migrating (`sectors` in
`risk_engine.py`, `strike_bands`/`actively_wheeling` in `market_data.py`/`scan.py`) were left
alone.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.common.config import get_config
from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    OptionQuote,
    OptionRight,
    Regime,
    TechnicalStats,
)
from src.common.universe import effective_universe, invalidate_universe_cache
from src.storage.universe_overrides import set_override
from src.strategies.cash_secured_put import generate_csp_candidates

ROOT = Path(__file__).resolve().parents[1]

# Expiry within the [7, 28] DTE window, computed relative to today (mirrors
# tests/test_strategies.py) so this stays green regardless of when it runs.
_TODAY = date.today()
_EXPIRY = _TODAY + timedelta(days=24)


# --------------------------------------------------------------------------- #
# Fixtures — same recipe as tests/test_strategies.py's TestCashSecuredPut, which already
# proves this exact combination clears every gate (delta/dte/liquidity/ROC/yield/fair-value).
# --------------------------------------------------------------------------- #


def _put_quote(
    strike: float = 170.0,
    delta: float = -0.25,
    bid: float = 2.10,
    ask: float = 2.30,
    volume: int = 500,
    oi: int = 2000,
    expiry: date = _EXPIRY,
) -> OptionQuote:
    return OptionQuote(
        underlying="AAPL",
        right=OptionRight.PUT,
        strike=strike,
        expiry=expiry,
        bid=bid,
        ask=ask,
        volume=volume,
        open_interest=oi,
        iv=0.28,
        delta=delta,
    )


def _account(
    *,
    net_liq: float = 100_000.0,
    cash: float = 70_000.0,
    total_cash: float = 50_000.0,
    buying_power: float = 80_000.0,
) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=net_liq,
        total_cash=total_cash,
        buying_power=buying_power,
        maintenance_margin=10_000.0,
        excess_liquidity=cash,
    )


def _iv(symbol: str = "AAPL", rank: float = 65.0) -> IVStats:
    return IVStats(symbol=symbol, current_iv=28.0, iv_rank=rank)


def _tech(
    symbol: str = "AAPL", price: float = 185.0, regime: Regime | None = None
) -> TechnicalStats:
    return TechnicalStats(symbol=symbol, price=price, rsi_14=55.0, regime=regime)


def _fund(quality: bool | None = True, dividend_safe: bool | None = None) -> FundamentalStats:
    return FundamentalStats(symbol="AAPL", quality_flag=quality, dividend_safe=dividend_safe)


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    """A fresh trading DB session, matching tests/test_effective_universe.py's pattern.

    ``effective_universe()`` reads overrides through ``src.storage.db.session_scope()``
    internally, not through this fixture's session directly — but since both are bound to the
    same monkeypatched ``dbmod._engine``/``_SessionLocal``, a write committed via this session
    is visible to ``effective_universe()``'s own session without any extra patching.
    """
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    session = dbmod._SessionLocal()
    try:
        yield session
    finally:
        session.close()


# --------------------------------------------------------------------------- #
# The consequential edit: an override must actually change strategy-generator output
# --------------------------------------------------------------------------- #


def test_a_would_own_add_makes_a_symbol_csp_eligible(db_session) -> None:
    """The single most consequential edit in the system. It must actually work end to end —
    not just at the composer layer (already proven by test_effective_universe.py), but at
    the consumer that decides whether a trade is even considered."""
    # LABU is a leveraged ETF, CC-only in the YAML — confirmed absent from would_own.
    yaml_universe = get_config().universe
    assert "LABU" not in yaml_universe["would_own"]

    result = generate_csp_candidates("LABU", [_put_quote()], _account(), _iv(), _tech(), _fund())
    assert result == []

    set_override(db_session, symbol="LABU", list_name="would_own", action="add", created_by="owner")
    db_session.commit()
    invalidate_universe_cache()
    assert "LABU" in effective_universe()["would_own"]

    result = generate_csp_candidates("LABU", [_put_quote()], _account(), _iv(), _tech(), _fund())
    assert len(result) == 1


def test_a_would_own_remove_makes_a_symbol_csp_ineligible(db_session) -> None:
    # AAPL is in the YAML would_own (dip-watch tier) — confirmed present.
    yaml_universe = get_config().universe
    assert "AAPL" in yaml_universe["would_own"]

    result = generate_csp_candidates("AAPL", [_put_quote()], _account(), _iv(), _tech(), _fund())
    assert len(result) == 1

    set_override(
        db_session, symbol="AAPL", list_name="would_own", action="remove", created_by="owner"
    )
    db_session.commit()
    invalidate_universe_cache()
    assert "AAPL" not in effective_universe()["would_own"]

    result = generate_csp_candidates("AAPL", [_put_quote()], _account(), _iv(), _tech(), _fund())
    assert result == []


# --------------------------------------------------------------------------- #
# What must NOT move — sectors, strike_bands, actively_wheeling stay YAML-only
# --------------------------------------------------------------------------- #


def test_the_risk_engine_still_reads_the_file() -> None:
    """sectors is not overridable, so risk_engine must not go through the accessor."""
    text = (ROOT / "src" / "engine" / "risk_engine.py").read_text(encoding="utf-8")
    assert "effective_universe" not in text


def test_strike_bands_and_actively_wheeling_still_read_the_file() -> None:
    """Neither strike_bands nor actively_wheeling is overridable — a regression test that
    fails loudly if a future edit accidentally migrates either read."""
    market_data_text = (ROOT / "src" / "ibkr" / "market_data.py").read_text(encoding="utf-8")
    assert "effective_universe" not in market_data_text

    scan_text = (ROOT / "src" / "orchestrator" / "scan.py").read_text(encoding="utf-8")
    assert 'cfg.universe.get("actively_wheeling"' in scan_text


# --------------------------------------------------------------------------- #
# A fifth, optional verification — eod_report's watchlist reporting picks up an override
# --------------------------------------------------------------------------- #


def test_eod_report_watchlist_reflects_an_override(db_session) -> None:
    """`_universe_symbols` (indexes ∪ watchlist ∪ would_own, used to keep IV history fresh)
    must also see a watchlist override — the second migrated site in eod_report.py."""
    from src.orchestrator.eod_report import _universe_symbols

    cfg = get_config()
    assert "ZZZZ" not in cfg.universe["watchlist"]
    assert "ZZZZ" not in _universe_symbols()

    set_override(db_session, symbol="ZZZZ", list_name="watchlist", action="add", created_by="owner")
    db_session.commit()
    invalidate_universe_cache()

    assert "ZZZZ" in _universe_symbols()
