"""Tests for the per-symbol option-chain timeout in run_scan (scan hang fix).

A symbol whose option-chain fetch never returns (IBKR pacing violation, competing-session
lockout, etc.) must not hang the whole scan: it should be skipped after
`market_data.symbol_timeout_seconds` and the scan should still reach completion (Telegram
send + lease release). No TWS/Gateway required — everything IBKR-shaped is mocked.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    MarketConditions,
    TechnicalStats,
)


def _make_account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=200_000.0,
        total_cash=150_000.0,
        buying_power=120_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=110_000.0,
    )


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


@pytest.mark.asyncio
async def test_hung_symbol_does_not_hang_the_scan(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)

    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(cfg.market_data, "symbol_timeout_seconds", 0.05)
    monkeypatch.setattr(cfg, "universe", {"would_own": ["AAPL"], "sectors": {"AAPL": "tech"}})

    # --- IB + account/positions ---
    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    monkeypatch.setattr(
        scanmod, "get_account_snapshot_async", AsyncMock(return_value=_make_account())
    )
    monkeypatch.setattr(scanmod, "get_positions", lambda ib: [])
    monkeypatch.setattr(scanmod, "get_market_conditions", lambda: MarketConditions(vix=15.0))

    # --- Option chain that never returns ---
    async def _hangs_forever(ib, symbol):
        await asyncio.sleep(3600)

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _hangs_forever)

    # --- Analytics / sentiment stubs ---
    monkeypatch.setattr(scanmod, "get_iv_stats", lambda symbol, quotes=None: IVStats(symbol=symbol))
    monkeypatch.setattr(
        scanmod,
        "get_technical_stats",
        lambda symbol, **_: TechnicalStats(symbol=symbol, price=100.0),
    )
    monkeypatch.setattr(
        scanmod, "get_fundamental_stats", lambda symbol: FundamentalStats(symbol=symbol)
    )

    class _DummySentiment:
        def __init__(self, **kwargs):
            pass

        def score(self, symbol):
            return None

    monkeypatch.setattr(scanmod, "SentimentScorer", _DummySentiment)
    monkeypatch.setattr(scanmod, "generate_buy_candidates", lambda *a, **k: [])

    # --- Telegram send ---
    monkeypatch.setattr(scanmod, "send_candidates", AsyncMock())
    monkeypatch.setattr(scanmod, "send_buy_list", AsyncMock())

    result = await asyncio.wait_for(
        scanmod.run_scan(mock_ib, bot=object(), chat_id="123"), timeout=5.0
    )

    assert result.lease_skipped is False
    assert result.cc_candidates == []
    assert result.csp_candidates == []


@pytest.mark.asyncio
async def test_timeout_logs_error_and_continues(tmp_path, monkeypatch, caplog):
    _db_setup(tmp_path, monkeypatch)

    import logging

    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(cfg.market_data, "symbol_timeout_seconds", 0.05)
    monkeypatch.setattr(cfg, "universe", {"would_own": ["AAPL"], "sectors": {"AAPL": "tech"}})

    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    monkeypatch.setattr(
        scanmod, "get_account_snapshot_async", AsyncMock(return_value=_make_account())
    )
    monkeypatch.setattr(scanmod, "get_positions", lambda ib: [])
    monkeypatch.setattr(scanmod, "get_market_conditions", lambda: MarketConditions(vix=15.0))

    async def _hangs_forever(ib, symbol):
        await asyncio.sleep(3600)

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _hangs_forever)
    monkeypatch.setattr(scanmod, "get_iv_stats", lambda symbol, quotes=None: IVStats(symbol=symbol))
    monkeypatch.setattr(
        scanmod,
        "get_technical_stats",
        lambda symbol, **_: TechnicalStats(symbol=symbol, price=100.0),
    )
    monkeypatch.setattr(
        scanmod, "get_fundamental_stats", lambda symbol: FundamentalStats(symbol=symbol)
    )

    class _DummySentiment:
        def __init__(self, **kwargs):
            pass

        def score(self, symbol):
            return None

    monkeypatch.setattr(scanmod, "SentimentScorer", _DummySentiment)
    monkeypatch.setattr(scanmod, "generate_buy_candidates", lambda *a, **k: [])
    monkeypatch.setattr(scanmod, "send_candidates", AsyncMock())
    monkeypatch.setattr(scanmod, "send_buy_list", AsyncMock())

    with caplog.at_level(logging.ERROR, logger="src.orchestrator.scan"):
        await asyncio.wait_for(scanmod.run_scan(mock_ib, bot=object(), chat_id="123"), timeout=5.0)

    assert any("exceeded symbol_timeout_seconds" in r.message for r in caplog.records)
    assert any("AAPL" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_consecutive_timeouts_abort_the_scan(tmp_path, monkeypatch):
    """A half-dead socket times out on EVERY symbol — the circuit breaker must abort the run
    after max_consecutive_chain_timeouts rather than grinding through the whole universe."""
    _db_setup(tmp_path, monkeypatch)

    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(cfg.market_data, "symbol_timeout_seconds", 0.05)
    monkeypatch.setattr(cfg.market_data, "max_consecutive_chain_timeouts", 2)
    universe = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META"]
    monkeypatch.setattr(
        cfg, "universe", {"would_own": universe, "sectors": {s: "tech" for s in universe}}
    )

    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    monkeypatch.setattr(
        scanmod, "get_account_snapshot_async", AsyncMock(return_value=_make_account())
    )
    monkeypatch.setattr(scanmod, "get_positions", lambda ib: [])
    monkeypatch.setattr(scanmod, "get_market_conditions", lambda: MarketConditions(vix=15.0))

    calls: list[str] = []

    async def _hangs_forever(ib, symbol):
        calls.append(symbol)
        await asyncio.sleep(3600)

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _hangs_forever)
    monkeypatch.setattr(scanmod, "get_iv_stats", lambda symbol, quotes=None: IVStats(symbol=symbol))
    monkeypatch.setattr(
        scanmod,
        "get_technical_stats",
        lambda symbol, **_: TechnicalStats(symbol=symbol, price=100.0),
    )
    monkeypatch.setattr(
        scanmod, "get_fundamental_stats", lambda symbol: FundamentalStats(symbol=symbol)
    )

    class _DummySentiment:
        def __init__(self, **kwargs):
            pass

        def score(self, symbol):
            return None

    monkeypatch.setattr(scanmod, "SentimentScorer", _DummySentiment)
    monkeypatch.setattr(scanmod, "generate_buy_candidates", lambda *a, **k: [])
    monkeypatch.setattr(scanmod, "send_candidates", AsyncMock())
    monkeypatch.setattr(scanmod, "send_buy_list", AsyncMock())

    result = await asyncio.wait_for(
        scanmod.run_scan(mock_ib, bot=object(), chat_id="123"), timeout=5.0
    )

    assert result.aborted_unhealthy is True
    # Breaker tripped after exactly the threshold — the remaining universe was NOT fetched.
    assert len(calls) == 2
    assert len(calls) < len(universe)
