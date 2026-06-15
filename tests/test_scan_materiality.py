"""Tests for the S1 intraday materiality gate + S10 scan-state store.

The 15-min intraday loop must re-fetch the (expensive) option chain only for symbols that
can change a decision this cycle — held positions, materially-moved would_own names, and names
that cleared the score floor last cycle — and skip the rest. The morning cron / manual /scan
(intraday=False) always sweep the full universe. No TWS/Gateway required.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    MarketConditions,
    PositionSnapshot,
    TechnicalStats,
)
from src.storage.scan_state import ScanState


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _state(symbol: str, last_spot: float, *, cleared_floor: bool = False) -> ScanState:
    return ScanState(
        symbol=symbol,
        last_spot=last_spot,
        last_scanned_at=datetime.now(UTC),  # recent → no force-full sweep
        cleared_floor=cleared_floor,
    )


# ---------------------------------------------------------------------------
# _compute_material_symbols — the gate logic in isolation
# ---------------------------------------------------------------------------


class TestComputeMaterialSymbols:
    @pytest.mark.asyncio
    async def test_empty_state_makes_everything_material(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {})
        material = await scanmod._compute_material_symbols(
            ["AAPL", "MSFT"], set(), ["AAPL", "MSFT"]
        )
        assert material == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_held_symbol_always_material(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        # NVDA held, unmoved; still material because it's a holding.
        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"NVDA": _state("NVDA", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.0)
        material = await scanmod._compute_material_symbols(["NVDA"], {"NVDA"}, [])
        assert "NVDA" in material

    @pytest.mark.asyncio
    async def test_unmoved_would_own_is_skipped(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"AAPL": _state("AAPL", 200.0)})
        # Move 0.1% — below the 0.5% default threshold.
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.2)
        material = await scanmod._compute_material_symbols(["AAPL"], set(), ["AAPL"])
        assert "AAPL" not in material

    @pytest.mark.asyncio
    async def test_moved_would_own_is_material(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"AAPL": _state("AAPL", 200.0)})
        # Move 2% — well past 0.5%.
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 204.0)
        material = await scanmod._compute_material_symbols(["AAPL"], set(), ["AAPL"])
        assert "AAPL" in material

    @pytest.mark.asyncio
    async def test_cleared_floor_last_cycle_is_material(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(
            scanmod,
            "get_scan_state",
            lambda syms: {"AAPL": _state("AAPL", 200.0, cleared_floor=True)},
        )
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0)  # unmoved
        material = await scanmod._compute_material_symbols(["AAPL"], set(), ["AAPL"])
        assert "AAPL" in material

    @pytest.mark.asyncio
    async def test_force_full_scan_when_stalest_too_old(self, monkeypatch):
        import src.orchestrator.scan as scanmod
        from src.common.config import get_config

        monkeypatch.setattr(get_config().market_data, "force_full_scan_minutes", 30.0)
        stale = ScanState(
            symbol="AAPL",
            last_spot=200.0,
            last_scanned_at=datetime.now(UTC) - timedelta(minutes=45),
            cleared_floor=False,
        )
        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"AAPL": stale})
        # Even unmoved, the periodic sweep forces it.
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0)
        material = await scanmod._compute_material_symbols(["AAPL"], set(), ["AAPL"])
        assert material == {"AAPL"}

    @pytest.mark.asyncio
    async def test_missing_baseline_forces_fetch(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        # State exists for another symbol (so not "empty"), but TSLA has no baseline.
        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"AAPL": _state("AAPL", 200.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 250.0)
        material = await scanmod._compute_material_symbols(
            ["AAPL", "TSLA"], set(), ["AAPL", "TSLA"]
        )
        assert "TSLA" in material  # establishes a baseline this cycle


# ---------------------------------------------------------------------------
# scan-state round-trip
# ---------------------------------------------------------------------------


class TestScanStateStore:
    def test_upsert_then_get_roundtrip(self, tmp_path, monkeypatch):
        _db_setup(tmp_path, monkeypatch)
        from src.storage.scan_state import get_scan_state, upsert_scan_state

        ts = datetime.now(UTC)
        upsert_scan_state("AAPL", last_spot=187.5, last_scanned_at=ts, cleared_floor=True)
        got = get_scan_state(["AAPL", "MSFT"])
        assert "MSFT" not in got
        assert got["AAPL"].last_spot == pytest.approx(187.5)
        assert got["AAPL"].cleared_floor is True

    def test_upsert_updates_existing_row(self, tmp_path, monkeypatch):
        _db_setup(tmp_path, monkeypatch)
        from src.storage.scan_state import get_scan_state, upsert_scan_state

        ts = datetime.now(UTC)
        upsert_scan_state("AAPL", last_spot=100.0, last_scanned_at=ts, cleared_floor=False)
        upsert_scan_state("AAPL", last_spot=110.0, last_scanned_at=ts, cleared_floor=True)
        got = get_scan_state(["AAPL"])
        assert got["AAPL"].last_spot == pytest.approx(110.0)
        assert got["AAPL"].cleared_floor is True


# ---------------------------------------------------------------------------
# End-to-end gating through run_scan(intraday=True)
# ---------------------------------------------------------------------------


def _make_account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=200_000.0,
        total_cash=150_000.0,
        buying_power=120_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=110_000.0,
    )


def _stub_common(scanmod, monkeypatch, *, positions):
    monkeypatch.setattr(
        scanmod, "get_account_snapshot_async", AsyncMock(return_value=_make_account())
    )
    monkeypatch.setattr(scanmod, "get_positions", lambda ib: positions)
    monkeypatch.setattr(scanmod, "get_market_conditions", lambda: MarketConditions(vix=15.0))
    monkeypatch.setattr(scanmod, "get_iv_stats", lambda symbol, quotes=None: IVStats(symbol=symbol))
    monkeypatch.setattr(
        scanmod, "get_technical_stats", lambda symbol, **_: TechnicalStats(symbol=symbol, price=100.0)
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


@pytest.mark.asyncio
async def test_intraday_gate_fetches_moved_skips_unmoved(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {"would_own": ["AAPL", "MSFT"], "sectors": {"AAPL": "tech", "MSFT": "tech"}},
    )
    _stub_common(scanmod, monkeypatch, positions=[])

    fetched: list[str] = []

    async def _track_fetch(ib, symbol):
        fetched.append(symbol)
        return []

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _track_fetch)

    # Seed baselines: AAPL will "move", MSFT will not.
    monkeypatch.setattr(
        scanmod,
        "get_scan_state",
        lambda syms: {"AAPL": _state("AAPL", 200.0), "MSFT": _state("MSFT", 300.0)},
    )
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 210.0 if s == "AAPL" else 300.1)

    await asyncio.wait_for(
        scanmod.run_scan(MagicMock(), bot=object(), chat_id="1", intraday=True), timeout=5.0
    )

    assert "AAPL" in fetched  # moved 5%
    assert "MSFT" not in fetched  # moved 0.03% → skipped


@pytest.mark.asyncio
async def test_full_sweep_ignores_gate(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {"would_own": ["AAPL", "MSFT"], "sectors": {"AAPL": "tech", "MSFT": "tech"}},
    )
    _stub_common(scanmod, monkeypatch, positions=[])

    fetched: list[str] = []

    async def _track_fetch(ib, symbol):
        fetched.append(symbol)
        return []

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _track_fetch)

    # _compute_material_symbols must NOT be consulted in full-sweep mode.
    def _boom(_syms):
        raise AssertionError("materiality gate must not run on a full sweep")

    monkeypatch.setattr(scanmod, "get_scan_state", _boom)

    await asyncio.wait_for(scanmod.run_scan(MagicMock(), bot=object(), chat_id="1"), timeout=5.0)

    assert set(fetched) == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_held_position_always_fetched_even_when_unmoved(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg, "universe", {"would_own": ["AAPL"], "sectors": {"AAPL": "tech", "NVDA": "tech"}}
    )
    held = PositionSnapshot(
        symbol="NVDA",
        underlying="NVDA",
        sec_type="STK",
        position=100.0,
        avg_cost=90.0,
    )
    _stub_common(scanmod, monkeypatch, positions=[held])

    fetched: list[str] = []

    async def _track_fetch(ib, symbol):
        fetched.append(symbol)
        return []

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _track_fetch)
    monkeypatch.setattr(
        scanmod,
        "get_scan_state",
        lambda syms: {"AAPL": _state("AAPL", 200.0), "NVDA": _state("NVDA", 90.0)},
    )
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0)  # AAPL unmoved

    await asyncio.wait_for(
        scanmod.run_scan(MagicMock(), bot=object(), chat_id="1", intraday=True), timeout=5.0
    )

    assert "NVDA" in fetched  # held → always material
    assert "AAPL" not in fetched  # would_own, unmoved → skipped


# ---------------------------------------------------------------------------
# Quiet-cycle heartbeat (S6) — an intraday cycle that surfaces nothing still pings Telegram
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quiet_intraday_cycle_sends_heartbeat(tmp_path, monkeypatch):
    """No candidate clears the gate and the buy list is empty → one quiet-cycle heartbeat goes
    out (so silence ≠ dead daemon), explaining how many names were below the move threshold."""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {"would_own": ["AAPL", "MSFT"], "sectors": {"AAPL": "tech", "MSFT": "tech"}},
    )
    _stub_common(scanmod, monkeypatch, positions=[])
    # Nothing surfaced this cycle → both sends report "nothing went out".
    monkeypatch.setattr(scanmod, "send_candidates", AsyncMock(return_value=False))
    monkeypatch.setattr(scanmod, "send_buy_list", AsyncMock(return_value=False))

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", AsyncMock(return_value=[]))
    # Both would_own names unmoved → skipped → material_count 0, skipped 2.
    monkeypatch.setattr(
        scanmod,
        "get_scan_state",
        lambda syms: {"AAPL": _state("AAPL", 200.0), "MSFT": _state("MSFT", 300.0)},
    )
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0 if s == "AAPL" else 300.0)

    bot = MagicMock()
    bot.send_message = AsyncMock()

    result = await asyncio.wait_for(
        scanmod.run_scan(MagicMock(), bot=bot, chat_id="1", intraday=True), timeout=5.0
    )

    assert result.quiet_cycle is True
    bot.send_message.assert_awaited_once()
    text = bot.send_message.await_args.kwargs["text"]
    assert "Quiet cycle" in text
    assert "2/2" in text  # both names below the move threshold


@pytest.mark.asyncio
async def test_full_sweep_never_sends_heartbeat(tmp_path, monkeypatch):
    """Manual /scan and the morning cron (intraday=False) must never emit the heartbeat, even
    when the cycle surfaces nothing — they always send in full."""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg, "universe", {"would_own": ["AAPL"], "sectors": {"AAPL": "tech"}}
    )
    _stub_common(scanmod, monkeypatch, positions=[])
    monkeypatch.setattr(scanmod, "send_candidates", AsyncMock(return_value=False))
    monkeypatch.setattr(scanmod, "send_buy_list", AsyncMock(return_value=False))
    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", AsyncMock(return_value=[]))

    bot = MagicMock()
    bot.send_message = AsyncMock()

    result = await asyncio.wait_for(
        scanmod.run_scan(MagicMock(), bot=bot, chat_id="1"), timeout=5.0
    )

    assert result.quiet_cycle is False
    # The full sweep still sends the end-of-scan data-provenance summary, but never the
    # intraday quiet-cycle heartbeat.
    for call in bot.send_message.await_args_list:
        assert "Quiet cycle" not in call.kwargs["text"]
