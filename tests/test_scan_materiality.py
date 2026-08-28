"""Tests for the S1 intraday materiality gate + S10 scan-state store.

The 15-min intraday loop must re-fetch the (expensive) option chain only for symbols that
can change a decision this cycle: held positions that *rose* >= held_position_move_pct,
actively_wheeling names that moved >= intraday_rescan_move_pct in either direction, would_own-
but-not-actively_wheeling ("dip-watch") names that *dropped* >= dip_pull_in_pct, and names that
cleared the score floor last cycle — and skip the rest. Manual /scan (intraday=False) and the
first-cycle forced full sweep fetch actively_wheeling ∪ held names unconditionally; dip_watch
names get seed-only (yfinance baseline persisted, no chain fetch) unless they gapped ≥3%
overnight (2026-08-28). No TWS/Gateway required.

Bucket membership is a UNION, not a selection (2026-08-28): a symbol in two buckets is tested
against both thresholds and any one firing is enough, so holding shares can never *reduce* a
name's scan coverage.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
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


def await_sync(coro):
    """Run *coro* to completion on a throwaway loop (for sync DB-backed tests)."""
    return asyncio.run(coro)


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
        material, _probed = await scanmod._compute_material_symbols(
            ["AAPL", "MSFT"], set(), ["AAPL", "MSFT"], []
        )
        assert material == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_held_symbol_no_baseline_is_material(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        # NVDA held, no baseline yet → fetched once to establish one.
        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"AAPL": _state("AAPL", 1.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.0)
        material, _probed = await scanmod._compute_material_symbols(
            ["AAPL", "NVDA"], {"NVDA"}, [], []
        )
        assert "NVDA" in material

    @pytest.mark.asyncio
    async def test_held_symbol_unmoved_is_skipped(self, monkeypatch):
        """2026-08-27: held positions are no longer unconditionally material — a CC-candidate
        refresh is only worth an option-chain fetch if the stock actually moved."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"NVDA": _state("NVDA", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.1)  # 0.1% < 2% default
        material, _probed = await scanmod._compute_material_symbols(["NVDA"], {"NVDA"}, [], [])
        assert "NVDA" not in material

    @pytest.mark.asyncio
    async def test_held_symbol_risen_enough_is_material(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"NVDA": _state("NVDA", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 102.0)  # +2%
        material, _probed = await scanmod._compute_material_symbols(["NVDA"], {"NVDA"}, [], [])
        assert "NVDA" in material

    @pytest.mark.asyncio
    async def test_held_symbol_dropped_is_not_material(self, monkeypatch):
        """2026-08-27: held-position gating is upside-only — a new CC candidate needs room to
        sell an OTM strike, which only opens up on a rally. A drop no longer triggers a refetch
        from this gate (it's still caught by the per-symbol force_full_scan_minutes safety net).

        This is the held-*only* case: NVDA is in no other bucket here. A held name that is also
        actively_wheeling or dip-watch picks up that bucket's rule too — see the union tests."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"NVDA": _state("NVDA", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 90.0)  # -10%, well past 2%
        material, _probed = await scanmod._compute_material_symbols(["NVDA"], {"NVDA"}, [], [])
        assert "NVDA" not in material

    @pytest.mark.asyncio
    async def test_unmoved_actively_wheeling_is_skipped(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"AAPL": _state("AAPL", 200.0)})
        # Move 0.1% — below the 0.5% default threshold.
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.2)
        material, _probed = await scanmod._compute_material_symbols(["AAPL"], set(), ["AAPL"], [])
        assert "AAPL" not in material

    @pytest.mark.asyncio
    async def test_moved_actively_wheeling_is_material(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"AAPL": _state("AAPL", 200.0)})
        # Move 2% — well past 0.5%.
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 204.0)
        material, _probed = await scanmod._compute_material_symbols(["AAPL"], set(), ["AAPL"], [])
        assert "AAPL" in material

    @pytest.mark.asyncio
    async def test_dip_watch_drop_is_material(self, monkeypatch):
        """A would_own-but-not-actively_wheeling name is pulled in on a >=3% drop."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"XLV": _state("XLV", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 96.0)  # -4%
        material, _probed = await scanmod._compute_material_symbols(["XLV"], set(), [], ["XLV"])
        assert "XLV" in material

    @pytest.mark.asyncio
    async def test_dip_watch_rally_is_not_material(self, monkeypatch):
        """A rally is never a CSP entry signal for a dip-watch name — only a drop counts."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"XLV": _state("XLV", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 105.0)  # +5%, well past 3%
        material, _probed = await scanmod._compute_material_symbols(["XLV"], set(), [], ["XLV"])
        assert "XLV" not in material

    @pytest.mark.asyncio
    async def test_dip_watch_small_drop_is_not_material(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"XLV": _state("XLV", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 99.0)  # -1% < 3%
        material, _probed = await scanmod._compute_material_symbols(["XLV"], set(), [], ["XLV"])
        assert "XLV" not in material

    @pytest.mark.asyncio
    async def test_held_dip_watch_symbol_gets_the_held_rally_rule(self, monkeypatch):
        """A name that's both held and dip-watch also gets the held (2%, up-only) rule: a +3%
        rally fires it even though the dip-watch rule alone (3%, drop-only) never would."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"XLV": _state("XLV", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 103.0)  # +3%: <3%-down rule
        # would be skipped as dip-watch (no drop at all), but held → 2% either-direction applies.
        material, _probed = await scanmod._compute_material_symbols(["XLV"], {"XLV"}, [], ["XLV"])
        assert "XLV" in material

    @pytest.mark.asyncio
    async def test_held_actively_wheeling_still_gets_the_half_percent_rule(self, monkeypatch):
        """2026-08-28 union: holding shares must not *reduce* coverage.

        A held actively_wheeling name that drops 0.6% is material via rule (b), even though the
        held rule (a) is up-only and would never fire on a drop. Under the old if/elif chain
        `held` won outright and this returned empty — silently shrinking the core rotation to
        just the names the operator doesn't hold.
        """
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"SOXL": _state("SOXL", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 99.4)  # -0.6%
        material, _probed = await scanmod._compute_material_symbols(
            ["SOXL"], {"SOXL"}, ["SOXL"], []
        )
        assert "SOXL" in material

    @pytest.mark.asyncio
    async def test_held_dip_watch_still_gets_the_dip_rule(self, monkeypatch):
        """A held dip-watch name that drops 3%+ is material via rule (c) — the held rule is
        up-only and cannot see a dip, but the CSP screen runs for it regardless of holding."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"PLTR": _state("PLTR", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 96.5)  # -3.5%
        material, _probed = await scanmod._compute_material_symbols(
            ["PLTR"], {"PLTR"}, [], ["PLTR"]
        )
        assert "PLTR" in material

    @pytest.mark.asyncio
    async def test_held_actively_wheeling_unmoved_is_still_skipped(self, monkeypatch):
        """The union widens which rules apply, not the thresholds themselves — a name below
        every one of its buckets' bars stays immaterial."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"META": _state("META", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.2)  # +0.2%
        material, _probed = await scanmod._compute_material_symbols(
            ["META"], {"META"}, ["META"], []
        )
        assert "META" not in material

    @pytest.mark.asyncio
    async def test_cleared_floor_last_cycle_is_material(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(
            scanmod,
            "get_scan_state",
            lambda syms: {"AAPL": _state("AAPL", 200.0, cleared_floor=True)},
        )
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0)  # unmoved
        material, _probed = await scanmod._compute_material_symbols(["AAPL"], set(), ["AAPL"], [])
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
        # Even unmoved, the periodic sweep forces it — AAPL is actively_wheeling here.
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0)
        material, _probed = await scanmod._compute_material_symbols(["AAPL"], set(), ["AAPL"], [])
        assert material == {"AAPL"}

    @pytest.mark.asyncio
    async def test_force_full_scan_is_per_symbol_not_whole_core(self, monkeypatch):
        """2026-08-27: staleness is checked per symbol, not "sweep the whole core the moment the
        single stalest one goes over the line" — a quiet, stale name must not drag a recently-
        fetched, unmoved sibling along with it. This is what lets the periodic refresh spread out
        naturally over time instead of bursting all 19 actively_wheeling names at once."""
        import src.orchestrator.scan as scanmod
        from src.common.config import get_config

        monkeypatch.setattr(get_config().market_data, "force_full_scan_minutes", 30.0)
        stale = ScanState(
            symbol="AAPL",
            last_spot=200.0,
            last_scanned_at=datetime.now(UTC) - timedelta(minutes=45),
            cleared_floor=False,
        )
        fresh = ScanState(
            symbol="MSFT",
            last_spot=300.0,
            last_scanned_at=datetime.now(UTC) - timedelta(minutes=5),
            cleared_floor=False,
        )
        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"AAPL": stale, "MSFT": fresh})
        # Both unmoved.
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0 if s == "AAPL" else 300.0)
        material, _probed = await scanmod._compute_material_symbols(
            ["AAPL", "MSFT"], set(), ["AAPL", "MSFT"], []
        )
        assert material == {"AAPL"}  # only the actually-stale one, not its fresh sibling

    @pytest.mark.asyncio
    async def test_dip_watch_excluded_from_force_full_sweep(self, monkeypatch):
        """A stale, unmoved dip-watch baseline must NOT be swept by force_full_scan_minutes —
        only actively_wheeling/held staleness triggers that safety net."""
        import src.orchestrator.scan as scanmod
        from src.common.config import get_config

        monkeypatch.setattr(get_config().market_data, "force_full_scan_minutes", 30.0)
        stale = ScanState(
            symbol="XLV",
            last_spot=100.0,
            last_scanned_at=datetime.now(UTC) - timedelta(minutes=200),
            cleared_floor=False,
        )
        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"XLV": stale})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.0)  # unmoved
        material, _probed = await scanmod._compute_material_symbols(["XLV"], set(), [], ["XLV"])
        assert "XLV" not in material

    @pytest.mark.asyncio
    async def test_missing_baseline_forces_fetch(self, monkeypatch):
        import src.orchestrator.scan as scanmod

        # State exists for another symbol (so not "empty"), but TSLA has no baseline.
        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"AAPL": _state("AAPL", 200.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 250.0)
        material, _probed = await scanmod._compute_material_symbols(
            ["AAPL", "TSLA"], set(), ["AAPL", "TSLA"], []
        )
        assert "TSLA" in material  # establishes a baseline this cycle

    @pytest.mark.asyncio
    async def test_must_include_forces_a_symbol_regardless_of_movement(self, monkeypatch):
        """A symbol queued for retry (an aborted sweep never reached it last cycle) must be
        fetched this cycle even though it hasn't moved enough to clear the normal gate."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"XLV": _state("XLV", 100.0)})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.0)  # unmoved
        material, _probed = await scanmod._compute_material_symbols(
            ["XLV"], set(), [], ["XLV"], must_include={"XLV"}
        )
        assert "XLV" in material

    @pytest.mark.asyncio
    async def test_must_include_does_not_widen_beyond_named_symbols(self, monkeypatch):
        """must_include is scoped to exactly the symbols named — an unrelated unmoved name
        must still be gated normally."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(
            scanmod,
            "get_scan_state",
            lambda syms: {"XLV": _state("XLV", 100.0), "XLU": _state("XLU", 50.0)},
        )
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.0 if s == "XLV" else 50.0)
        material, _probed = await scanmod._compute_material_symbols(
            ["XLV", "XLU"], set(), [], ["XLV", "XLU"], must_include={"XLV"}
        )
        assert material == {"XLV"}

    @pytest.mark.asyncio
    async def test_force_full_sweep_bypasses_gate_entirely(self, monkeypatch):
        """2026-08-21: the intraday loop's "first cycle since process start" rule passes
        force_full_sweep=True — must return every non-dip_watch symbol without even consulting
        scan_state (a fresh, recently-scanned baseline must not suppress the forced sweep).
        2026-08-28: dip_watch names are seed-only under force_full_sweep — see
        ``test_dip_watch_seed_only_on_full_sweep_quiet`` and the dedicated seed-only suite
        below."""
        import src.orchestrator.scan as scanmod

        def _boom(_syms):
            raise AssertionError("get_scan_state must not be consulted for non-dip_watch names")

        monkeypatch.setattr(scanmod, "get_scan_state", _boom)
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0)
        material, probed = await scanmod._compute_material_symbols(
            ["AAPL", "MSFT"], set(), ["AAPL", "MSFT"], [], force_full_sweep=True
        )
        assert material == {"AAPL", "MSFT"}
        assert probed == {}  # no dip_watch names to probe


# ---------------------------------------------------------------------------
# force_full_sweep — dip_watch seed-only (2026-08-28)
#
# At startup / manual /scan, dip_watch names no longer get an unconditional IBKR
# chain fetch. Instead they get a yfinance probe; names that gapped ≥3% overnight
# (bidirectional) are fetched, and quiet ones get seed-only — the probe price is
# persisted as `last_spot` so rule (c) works from cycle 1, without a chain fetch.
# ---------------------------------------------------------------------------


class TestForceFullSweepDipWatchSeedOnly:
    @pytest.mark.asyncio
    async def test_dip_watch_seed_only_on_full_sweep_quiet(self, monkeypatch):
        """A dip_watch name with a persisted baseline that didn't gap overnight is NOT
        material under force_full_sweep — it's seed-only (probe price returned so the
        caller can persist it, but no chain fetch)."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(
            scanmod,
            "get_scan_state",
            lambda syms: {"XLV": _state("XLV", 100.0)},
        )
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.5)  # +0.5% < 3%
        material, probed = await scanmod._compute_material_symbols(
            ["XLV"], set(), [], ["XLV"], force_full_sweep=True
        )
        assert "XLV" not in material
        assert probed == {"XLV": 100.5}  # seed-only baseline for the caller to persist

    @pytest.mark.asyncio
    async def test_dip_watch_fetched_on_overnight_gap_up(self, monkeypatch):
        """A dip_watch name that gapped UP ≥3% overnight IS material — a gap-up at the
        open is a legitimate CSP setup (IV expansion / news), even though a small
        intraday rally is never a CSP entry later in the day."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(
            scanmod,
            "get_scan_state",
            lambda syms: {"PLTR": _state("PLTR", 170.0)},
        )
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 185.0)  # +8.8%
        material, _probed = await scanmod._compute_material_symbols(
            ["PLTR"], set(), [], ["PLTR"], force_full_sweep=True
        )
        assert "PLTR" in material

    @pytest.mark.asyncio
    async def test_dip_watch_fetched_on_overnight_gap_down(self, monkeypatch):
        """A dip_watch name that gapped DOWN ≥3% overnight IS material — the dip rule,
        applied bidirectionally at startup (a gap-down is the obvious CSP entry)."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(
            scanmod,
            "get_scan_state",
            lambda syms: {"PLTR": _state("PLTR", 185.0)},
        )
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 170.0)  # -8.1%
        material, _probed = await scanmod._compute_material_symbols(
            ["PLTR"], set(), [], ["PLTR"], force_full_sweep=True
        )
        assert "PLTR" in material

    @pytest.mark.asyncio
    async def test_dip_watch_seed_only_no_baseline(self, monkeypatch):
        """A dip_watch name with NO persisted baseline (first-ever run, or DB wiped) is
        seed-only — accept no overnight detection for the first day; rule (c) drop-only
        works from cycle 1 onward against the yfinance-seeded baseline."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.0)
        material, probed = await scanmod._compute_material_symbols(
            ["XLV"], set(), [], ["XLV"], force_full_sweep=True
        )
        assert "XLV" not in material
        assert probed == {"XLV": 100.0}

    @pytest.mark.asyncio
    async def test_dip_watch_seed_only_then_rule_c_fires_next_cycle(self, monkeypatch):
        """End-to-end across two cycles: cycle 1 (force_full_sweep) seeds a dip_watch
        baseline from yfinance without a chain fetch; cycle 2 (normal intraday gate)
        sees a ≥3% drop from that seeded baseline and fires rule (c) — without the name
        ever having been chain-fetched on cycle 1."""
        import src.orchestrator.scan as scanmod

        # Cycle 1: force_full_sweep, no baseline → seed-only.
        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.0)
        material1, probed1 = await scanmod._compute_material_symbols(
            ["XLV"], set(), [], ["XLV"], force_full_sweep=True
        )
        assert "XLV" not in material1
        assert probed1 == {"XLV": 100.0}

        # Cycle 2: normal intraday gate. The seeded baseline (100.0) is now in scan_state;
        # a -3.1% probe fires rule (c) drop-only.
        monkeypatch.setattr(
            scanmod,
            "get_scan_state",
            lambda syms: {"XLV": _state("XLV", 100.0)},
        )
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 96.9)  # -3.1%
        material2, _probed2 = await scanmod._compute_material_symbols(["XLV"], set(), [], ["XLV"])
        assert "XLV" in material2

    @pytest.mark.asyncio
    async def test_held_dip_watch_is_material_under_force_full_sweep(self, monkeypatch):
        """A name that's both held AND dip_watch is material under force_full_sweep
        regardless of the overnight move — held names get an unconditional chain fetch
        in a full sweep (a new CC strike might open up), and the dip_watch seed-only
        path is scoped to dip_watch-only names."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(
            scanmod,
            "get_scan_state",
            lambda syms: {"XLV": _state("XLV", 100.0)},
        )
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.1)  # unmoved
        material, probed = await scanmod._compute_material_symbols(
            ["XLV"], {"XLV"}, [], ["XLV"], force_full_sweep=True
        )
        assert "XLV" in material
        assert "XLV" not in probed  # fetched, not seed-only

    @pytest.mark.asyncio
    async def test_actively_wheeling_is_material_under_force_full_sweep(self, monkeypatch):
        """An actively_wheeling name is material under force_full_sweep regardless of
        movement — the core rotation always gets an unconditional chain fetch at startup."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {})
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0)
        material, probed = await scanmod._compute_material_symbols(
            ["AAPL"], set(), ["AAPL"], [], force_full_sweep=True
        )
        assert "AAPL" in material
        assert probed == {}  # not probed — actively_wheeling is unconditionally material

    @pytest.mark.asyncio
    async def test_must_include_forces_a_dip_watch_name_under_force_full_sweep(self, monkeypatch):
        """must_include overrides even the seed-only path — a dip_watch name named in
        must_include is fetched regardless of the overnight move."""
        import src.orchestrator.scan as scanmod

        monkeypatch.setattr(
            scanmod,
            "get_scan_state",
            lambda syms: {"XLV": _state("XLV", 100.0)},
        )
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.1)  # unmoved
        material, _probed = await scanmod._compute_material_symbols(
            ["XLV"],
            set(),
            [],
            ["XLV"],
            force_full_sweep=True,
            must_include={"XLV"},
        )
        assert "XLV" in material


class TestPersistSeedOnlyBaselines:
    def test_persists_probe_price_for_non_material_symbols(self, tmp_path, monkeypatch):
        """A probe price for a seed-only symbol is persisted as last_spot with NULL
        last_scanned_at and cleared_floor=False — so rule (c) can compare against it
        next cycle without rule (e) (no-baseline) forcing a fetch."""
        _db_setup(tmp_path, monkeypatch)
        from src.orchestrator.scan import _persist_seed_only_baselines
        from src.storage.scan_state import get_scan_state

        _persist_seed_only_baselines({"XLV": 100.5, "AAPL": 200.0}, material={"AAPL"})

        got = get_scan_state(["XLV", "AAPL"])
        # XLV is seed-only: baseline persisted, no scan timestamp, floor not cleared.
        assert got["XLV"].last_spot == pytest.approx(100.5)
        assert got["XLV"].last_scanned_at is None
        assert got["XLV"].cleared_floor is False
        # AAPL was material — NOT seeded here (it'll be persisted by _persist_scan_state
        # with the chain's spot at end of run). It should be absent from the store.
        assert "AAPL" not in got

    def test_empty_probed_spots_is_noop(self, tmp_path, monkeypatch):
        _db_setup(tmp_path, monkeypatch)
        from src.orchestrator.scan import _persist_seed_only_baselines
        from src.storage.scan_state import get_scan_state

        _persist_seed_only_baselines({}, material=set())
        assert get_scan_state(["XLV"]) == {}

    def test_all_material_is_noop(self, tmp_path, monkeypatch):
        _db_setup(tmp_path, monkeypatch)
        from src.orchestrator.scan import _persist_seed_only_baselines
        from src.storage.scan_state import get_scan_state

        _persist_seed_only_baselines({"XLV": 100.0}, material={"XLV"})
        assert get_scan_state(["XLV"]) == {}  # nothing seeded


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


class TestPersistScanState:
    """2026-08-28: each fetched symbol carries its OWN fetch timestamp.

    A single run-level stamp recorded everything in a sweep as fetched when the whole run
    finished, so (i) symbols fetched early were logged fresher than they were, and (ii) the
    entire cohort shared one staleness clock and expired together in a single later cycle —
    defeating the per-symbol staleness check that reads these stamps.
    """

    def test_each_symbol_keeps_its_own_fetch_timestamp(self, tmp_path, monkeypatch):
        _db_setup(tmp_path, monkeypatch)
        from src.orchestrator.scan import _persist_scan_state
        from src.storage.scan_state import get_scan_state

        early = datetime.now(UTC) - timedelta(minutes=20)
        late = datetime.now(UTC)
        _persist_scan_state({"SPY": (600.0, early), "NVDA": (180.0, late)}, {"NVDA"})

        got = get_scan_state(["SPY", "NVDA"])
        spy = got["SPY"].last_scanned_at
        nvda = got["NVDA"].last_scanned_at
        assert spy is not None and nvda is not None
        if spy.tzinfo is None:  # SQLite drops tzinfo on round-trip
            spy, nvda = spy.replace(tzinfo=UTC), nvda.replace(tzinfo=UTC)
        # The two stamps must differ by roughly the gap between the fetches, not collapse.
        assert (nvda - spy).total_seconds() == pytest.approx(20 * 60, abs=5)
        assert got["NVDA"].cleared_floor is True
        assert got["SPY"].cleared_floor is False

    def test_stale_and_fresh_members_of_one_sweep_expire_separately(self, tmp_path, monkeypatch):
        """The payoff: a symbol fetched early in a long sweep goes stale a cycle before one
        fetched at the end, instead of the whole cohort tripping rule (f) together."""
        _db_setup(tmp_path, monkeypatch)
        import src.orchestrator.scan as scanmod
        from src.orchestrator.scan import _persist_scan_state
        from src.storage.scan_state import get_scan_state

        now = datetime.now(UTC)
        # A 20-min sweep, 121 minutes ago: SPY was first out, NVDA last.
        _persist_scan_state(
            {
                "SPY": (600.0, now - timedelta(minutes=141)),
                "NVDA": (180.0, now - timedelta(minutes=121)),
            },
            set(),
        )
        monkeypatch.setattr(scanmod, "get_scan_state", get_scan_state)
        monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 600.0 if s == "SPY" else 180.0)

        material, _probed = await_sync(
            scanmod._compute_material_symbols(["SPY", "NVDA"], set(), ["SPY", "NVDA"], [])
        )
        # Both are over 120 min here, so both fire — but their clocks are 20 min apart, which is
        # what lets them separate once one of them is refetched on its own.
        assert material == {"SPY", "NVDA"}

        # Refetch only SPY now; NVDA keeps its old stamp.
        _persist_scan_state({"SPY": (600.0, now)}, set())
        material, _probed = await_sync(
            scanmod._compute_material_symbols(["SPY", "NVDA"], set(), ["SPY", "NVDA"], [])
        )
        assert material == {"NVDA"}  # SPY is fresh, NVDA is still stale — no drag-along


class TestBulkUpsertScanState:
    def test_inserts_multiple_symbols_in_one_transaction(self, tmp_path, monkeypatch):
        _db_setup(tmp_path, monkeypatch)
        from src.storage.scan_state import bulk_upsert_scan_state, get_scan_state

        ts = datetime.now(UTC)
        bulk_upsert_scan_state({"AAPL": (190.0, ts, True), "MSFT": (350.0, ts, False)})
        got = get_scan_state(["AAPL", "MSFT", "TSLA"])
        assert got["AAPL"].last_spot == pytest.approx(190.0)
        assert got["AAPL"].cleared_floor is True
        assert got["MSFT"].last_spot == pytest.approx(350.0)
        assert got["MSFT"].cleared_floor is False
        assert "TSLA" not in got

    def test_updates_existing_rows(self, tmp_path, monkeypatch):
        _db_setup(tmp_path, monkeypatch)
        from src.storage.scan_state import bulk_upsert_scan_state, get_scan_state, upsert_scan_state

        ts = datetime.now(UTC)
        upsert_scan_state("AAPL", last_spot=100.0, last_scanned_at=ts, cleared_floor=False)
        bulk_upsert_scan_state({"AAPL": (110.0, ts, True), "TSLA": (250.0, ts, False)})
        got = get_scan_state(["AAPL", "TSLA"])
        assert got["AAPL"].last_spot == pytest.approx(110.0)
        assert got["AAPL"].cleared_floor is True
        assert got["TSLA"].last_spot == pytest.approx(250.0)

    def test_empty_dict_is_noop(self, tmp_path, monkeypatch):
        _db_setup(tmp_path, monkeypatch)
        from src.storage.scan_state import bulk_upsert_scan_state, get_scan_state

        bulk_upsert_scan_state({})
        assert get_scan_state(["AAPL"]) == {}


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
    monkeypatch.setattr(scanmod, "send_account_snapshot", AsyncMock())


@pytest.mark.asyncio
async def test_intraday_gate_fetches_moved_skips_unmoved(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": ["AAPL", "MSFT"],
            "actively_wheeling": ["AAPL", "MSFT"],
            "sectors": {"AAPL": "tech", "MSFT": "tech"},
        },
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
async def test_must_include_symbols_forces_a_fetch_through_run_scan(tmp_path, monkeypatch):
    """End-to-end: a symbol named in must_include_symbols gets its chain fetched this cycle
    even though it hasn't moved — this is how a retry queued from an aborted sweep gets
    honoured on the next cycle."""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": ["AAPL", "MSFT"],
            "actively_wheeling": ["AAPL", "MSFT"],
            "sectors": {"AAPL": "tech", "MSFT": "tech"},
        },
    )
    _stub_common(scanmod, monkeypatch, positions=[])

    fetched: list[str] = []

    async def _track_fetch(ib, symbol):
        fetched.append(symbol)
        return []

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _track_fetch)
    # Both unmoved — neither would normally clear the gate.
    monkeypatch.setattr(
        scanmod,
        "get_scan_state",
        lambda syms: {"AAPL": _state("AAPL", 200.0), "MSFT": _state("MSFT", 300.0)},
    )
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0 if s == "AAPL" else 300.0)

    await asyncio.wait_for(
        scanmod.run_scan(
            MagicMock(),
            bot=object(),
            chat_id="1",
            intraday=True,
            must_include_symbols={"MSFT"},
        ),
        timeout=5.0,
    )

    assert "MSFT" in fetched  # forced via must_include_symbols
    assert "AAPL" not in fetched  # unmoved, not in must_include_symbols → still gated


@pytest.mark.asyncio
async def test_full_sweep_ignores_gate(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": ["AAPL", "MSFT"],
            "actively_wheeling": ["AAPL", "MSFT"],
            "sectors": {"AAPL": "tech", "MSFT": "tech"},
        },
    )
    _stub_common(scanmod, monkeypatch, positions=[])

    fetched: list[str] = []

    async def _track_fetch(ib, symbol):
        fetched.append(symbol)
        return []

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _track_fetch)

    # No dip_watch names here (both are actively_wheeling), so scan_state is not consulted
    # even under the new seed-only dip_watch branch — it only probes dip_watch names.
    def _boom(_syms):
        raise AssertionError("scan_state must not be consulted when no symbols are dip_watch")

    monkeypatch.setattr(scanmod, "get_scan_state", _boom)

    await asyncio.wait_for(scanmod.run_scan(MagicMock(), bot=object(), chat_id="1"), timeout=5.0)

    assert set(fetched) == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_held_position_fetched_when_moved_enough(tmp_path, monkeypatch):
    """2026-08-27: held positions are no longer unconditionally fetched — a CC-candidate
    refresh is gated at held_position_move_pct (2%) like everything else, since it was
    previously the single largest fixed IBKR chain-fetch cost in the loop."""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": ["AAPL"],
            "actively_wheeling": [],
            "sectors": {"AAPL": "tech", "NVDA": "tech"},
        },
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
    # AAPL is dip-watch here (would_own, not actively_wheeling) and unmoved; NVDA held, +5.5%.
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0 if s == "AAPL" else 95.0)

    await asyncio.wait_for(
        scanmod.run_scan(MagicMock(), bot=object(), chat_id="1", intraday=True), timeout=5.0
    )

    assert "NVDA" in fetched  # held, moved 5.5% ≥ 2% → material
    assert "AAPL" not in fetched  # dip-watch, unmoved (no drop) → skipped


@pytest.mark.asyncio
async def test_held_position_skipped_when_moved_too_little(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {"would_own": [], "actively_wheeling": [], "sectors": {"NVDA": "tech"}},
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
    monkeypatch.setattr(scanmod, "get_scan_state", lambda syms: {"NVDA": _state("NVDA", 90.0)})
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 90.05)  # 0.06% < 2%

    await asyncio.wait_for(
        scanmod.run_scan(MagicMock(), bot=object(), chat_id="1", intraday=True), timeout=5.0
    )

    assert "NVDA" not in fetched  # held but moved too little → skipped


@pytest.mark.asyncio
async def test_quiet_gated_cycle_does_not_null_a_real_fetch_timestamp(tmp_path, monkeypatch):
    """Regression (2026-08-28 fix): a quiet, non-full-sweep intraday cycle must never call
    ``_persist_seed_only_baselines`` on its own ``probed_spots`` — that helper is for the
    full-sweep dip_watch path only. Before the fix, a probed-but-immaterial actively_wheeling
    symbol had its real ``last_scanned_at`` overwritten to NULL every quiet cycle, which (a)
    defeated the sticky-``last_spot`` drift-accumulation invariant and (b) made the *next*
    cycle's per-symbol ``force_full_scan_minutes`` staleness check see ``stamp is None`` and
    force an immediate real refetch — roughly every other cycle instead of every 120 minutes.
    """
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config
    from src.storage.scan_state import bulk_upsert_scan_state, get_scan_state

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": ["TQQQ"],
            "actively_wheeling": ["TQQQ"],
            "sectors": {"TQQQ": "tech"},
        },
    )
    _stub_common(scanmod, monkeypatch, positions=[])

    fetched: list[str] = []

    async def _track_fetch(ib, symbol):
        fetched.append(symbol)
        return []

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _track_fetch)
    # A real chain fetch 15 minutes ago — well under force_full_scan_minutes (120).
    real_fetch_time = datetime.now(UTC) - timedelta(minutes=15)
    bulk_upsert_scan_state({"TQQQ": (50.0, real_fetch_time, False)})
    # get_scan_state is deliberately NOT mocked — the test reads real persisted state.
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 50.05)  # +0.1% < 0.5%

    await asyncio.wait_for(
        scanmod.run_scan(MagicMock(), bot=object(), chat_id="1", intraday=True), timeout=5.0
    )

    assert "TQQQ" not in fetched  # moved too little → correctly gated out this cycle
    after = get_scan_state(["TQQQ"])["TQQQ"]
    assert after.last_scanned_at is not None  # must stay the real 15-min-old stamp
    assert after.last_spot == 50.0  # sticky — unchanged by this cycle's probe


# ---------------------------------------------------------------------------
# Quiet intraday cycle — silence is explained, not empty (S6)
#
# A quiet cycle used to be routed to a separate `format_quiet_cycle` heartbeat message, but
# that path was unreachable: both `send_candidates` and `send_buy_list` return True on their
# empty path, so `if not cand_sent and not buy_sent` never fired in production (only the
# mocked tests, which stubbed the return to False, ever exercised it). The materiality detail
# it carried now rides on the empty-screen diagnostic that actually gets appended.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quiet_intraday_cycle_explains_why_chains_were_skipped(tmp_path, monkeypatch):
    """No candidate clears the gate → the empty-screen reason names how many symbols were
    below the move threshold, so silence is distinguishable from a dead daemon."""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": ["AAPL", "MSFT"],
            "actively_wheeling": ["AAPL", "MSFT"],
            "sectors": {"AAPL": "tech", "MSFT": "tech"},
        },
    )
    _stub_common(scanmod, monkeypatch, positions=[])
    send_candidates = AsyncMock(return_value=True)
    monkeypatch.setattr(scanmod, "send_candidates", send_candidates)
    monkeypatch.setattr(scanmod, "send_buy_list", AsyncMock(return_value=True))
    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", AsyncMock(return_value=[]))
    # Both actively_wheeling names unmoved → skipped → material_count 0, skipped 2.
    monkeypatch.setattr(
        scanmod,
        "get_scan_state",
        lambda syms: {"AAPL": _state("AAPL", 200.0), "MSFT": _state("MSFT", 300.0)},
    )
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 200.0 if s == "AAPL" else 300.0)

    bot = MagicMock()
    bot.send_message = AsyncMock()

    await asyncio.wait_for(
        scanmod.run_scan(MagicMock(), bot=bot, chat_id="1", intraday=True), timeout=5.0
    )

    reasons = [c.kwargs.get("empty_reason", "") for c in send_candidates.await_args_list]
    assert any("2/2 names moved" in (r or "") for r in reasons), reasons


@pytest.mark.asyncio
async def test_full_sweep_omits_the_materiality_clause(tmp_path, monkeypatch):
    """A manual /scan re-fetches everything, so "names moved <X%" would be a lie there."""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {"would_own": ["AAPL"], "actively_wheeling": ["AAPL"], "sectors": {"AAPL": "tech"}},
    )
    _stub_common(scanmod, monkeypatch, positions=[])
    send_candidates = AsyncMock(return_value=True)
    monkeypatch.setattr(scanmod, "send_candidates", send_candidates)
    monkeypatch.setattr(scanmod, "send_buy_list", AsyncMock(return_value=True))
    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", AsyncMock(return_value=[]))

    bot = MagicMock()
    bot.send_message = AsyncMock()

    await asyncio.wait_for(scanmod.run_scan(MagicMock(), bot=bot, chat_id="1"), timeout=5.0)

    for call in send_candidates.await_args_list:
        assert "names moved" not in (call.kwargs.get("empty_reason") or "")


def test_materiality_clause_is_empty_when_everything_was_fetched() -> None:
    import src.orchestrator.scan as scanmod

    result = scanmod.ScanResult(total_symbols=5, material_count=5)
    assert scanmod._materiality_clause(result, intraday=True) == ""


@pytest.mark.asyncio
async def test_manual_scan_seeds_dip_watch_quiet_name(tmp_path, monkeypatch):
    """Manual /scan (intraday=False) now skips the IBKR chain fetch for dip_watch names
    that didn't gap overnight — they get a yfinance-seeded baseline instead. The
    actively_wheeling name is still fetched unconditionally; the dip_watch name is not.
    (2026-08-28)"""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": ["AAPL", "XLV"],
            "actively_wheeling": ["AAPL"],  # XLV is dip_watch
            "sectors": {"AAPL": "tech", "XLV": "health"},
        },
    )
    _stub_common(scanmod, monkeypatch, positions=[])

    fetched: list[str] = []

    async def _track_fetch(ib, symbol):
        fetched.append(symbol)
        return []

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _track_fetch)
    # XLV has a persisted baseline and is unmoved → seed-only. AAPL is actively_wheeling.
    monkeypatch.setattr(
        scanmod,
        "get_scan_state",
        lambda syms: {"XLV": _state("XLV", 100.0)},
    )
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 100.1)  # XLV +0.1% < 3%

    await asyncio.wait_for(scanmod.run_scan(MagicMock(), bot=object(), chat_id="1"), timeout=5.0)

    assert "AAPL" in fetched  # actively_wheeling → fetched
    assert "XLV" not in fetched  # dip_watch, quiet overnight → seed-only

    # The seed-only baseline should have been persisted so rule (c) works next cycle.
    from src.storage.scan_state import get_scan_state

    got = get_scan_state(["XLV"])
    assert got["XLV"].last_spot == pytest.approx(100.1)
    assert got["XLV"].last_scanned_at is None


@pytest.mark.asyncio
async def test_manual_scan_fetches_dip_watch_overnight_gap(tmp_path, monkeypatch):
    """Manual /scan (intraday=False) DOES fetch a dip_watch name that gapped ≥3%
    overnight — a gap is a legitimate CSP setup at the open. (2026-08-28)"""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": ["XLV"],
            "actively_wheeling": [],  # XLV is dip_watch
            "sectors": {"XLV": "health"},
        },
    )
    _stub_common(scanmod, monkeypatch, positions=[])

    fetched: list[str] = []

    async def _track_fetch(ib, symbol):
        fetched.append(symbol)
        return []

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _track_fetch)
    monkeypatch.setattr(
        scanmod,
        "get_scan_state",
        lambda syms: {"XLV": _state("XLV", 170.0)},
    )
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 185.0)  # +8.8% overnight

    await asyncio.wait_for(scanmod.run_scan(MagicMock(), bot=object(), chat_id="1"), timeout=5.0)

    assert "XLV" in fetched  # gapped up → fetched


# ---------------------------------------------------------------------------
# Intraday chain-fetch budget (2026-08-28)
# ---------------------------------------------------------------------------


class TestFetchPriority:
    """Ranking decides *which* material symbols a capped cycle spends its budget on."""

    def _rank(self, material, probed, states, **kw):
        import src.orchestrator.scan as scanmod
        from src.common.config import get_config

        kw.setdefault("holdings", set())
        kw.setdefault("aw_set", set())
        kw.setdefault("dip_set", set())
        kw.setdefault("must_include", None)
        return scanmod._fetch_priority(material, probed, states, cfg=get_config(), **kw)

    def test_retry_outranks_everything(self):
        p = self._rank(
            {"AAA", "BBB"},
            {"AAA": 100.0, "BBB": 50.0},
            {"AAA": _state("AAA", 100.0), "BBB": _state("BBB", 100.0)},  # BBB -50%
            aw_set={"AAA", "BBB"},
            must_include={"AAA"},
        )
        # BBB moved 100x its bar; AAA didn't move at all — but AAA is a retry, so it wins.
        assert p["AAA"] > p["BBB"]

    def test_cleared_floor_outranks_a_mover(self):
        p = self._rank(
            {"AAA", "BBB"},
            {"AAA": 100.0, "BBB": 90.0},
            {
                "AAA": _state("AAA", 100.0, cleared_floor=True),
                "BBB": _state("BBB", 100.0),  # -10% = 20x the 0.5% bar
            },
            aw_set={"AAA", "BBB"},
        )
        assert p["AAA"] > p["BBB"]

    def test_deepest_drop_wins_across_buckets(self):
        """The point of ranking in multiples of each symbol's own bar: a dip-watch name down 6%
        (2x its 3% bar) must outrank an actively_wheeling name down 0.6% (1.2x its 0.5% bar)."""
        p = self._rank(
            {"DIP", "AW"},
            {"DIP": 94.0, "AW": 99.4},
            {"DIP": _state("DIP", 100.0), "AW": _state("AW", 100.0)},
            aw_set={"AW"},
            dip_set={"DIP"},
        )
        assert p["DIP"] > p["AW"] >= 1.0

    def test_staleness_only_ranks_below_every_real_mover(self):
        p = self._rank(
            {"QUIET", "MOVER"},
            {"QUIET": 100.0, "MOVER": 99.4},
            {"QUIET": _state("QUIET", 100.0), "MOVER": _state("MOVER", 100.0)},
            aw_set={"QUIET", "MOVER"},
        )
        assert p["MOVER"] > p["QUIET"]
        assert p["QUIET"] == pytest.approx(0.5)


class TestMoveRatio:
    """`_move_ratio` is the single definition of "moved" shared by the gate and the ranker."""

    def _r(self, sym, price, last, **kw):
        import src.orchestrator.scan as scanmod
        from src.common.config import get_config

        kw.setdefault("holdings", set())
        kw.setdefault("aw_set", set())
        kw.setdefault("dip_set", set())
        return scanmod._move_ratio(sym, price, last, cfg=get_config(), **kw)

    def test_unions_across_buckets_taking_the_max(self):
        # Held + actively_wheeling, down 0.6%: the held (up-only) rule sees nothing, the aw rule
        # sees 1.2x. The union must return the aw ratio, not the held one.
        assert self._r("X", 99.4, 100.0, holdings={"X"}, aw_set={"X"}) == pytest.approx(1.2)

    def test_held_only_drop_is_zero(self):
        assert self._r("X", 90.0, 100.0, holdings={"X"}) <= 0

    def test_no_baseline_is_zero(self):
        assert self._r("X", 100.0, 0.0, aw_set={"X"}) == 0.0


@pytest.mark.asyncio
async def test_budget_defers_lowest_priority_symbols(tmp_path, monkeypatch):
    """A cycle whose material set can't fit the budget fetches the best-ranked ones and defers
    the rest to `unreached_symbols` — it never aborts, and never overruns unboundedly."""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    syms = ["AAA", "BBB", "CCC", "DDD"]
    monkeypatch.setattr(
        cfg,
        "universe",
        {"would_own": syms, "actively_wheeling": syms, "sectors": {s: "tech" for s in syms}},
    )
    # Budget fits ~2 fetches at 0.3s each; symbol_timeout must stay below it (config invariant).
    monkeypatch.setattr(cfg.market_data, "chain_fetch_budget_seconds", 0.65)
    monkeypatch.setattr(cfg.market_data, "symbol_timeout_seconds", 0.5)
    _stub_common(scanmod, monkeypatch, positions=[])

    fetched: list[str] = []

    async def _slow(ib, symbol):
        await asyncio.sleep(0.3)
        fetched.append(symbol)
        return []

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _slow)
    # All four material; DDD moved furthest, then CCC, then BBB, then AAA.
    monkeypatch.setattr(
        scanmod,
        "get_scan_state",
        lambda s: {x: _state(x, 100.0) for x in syms},
    )
    moves = {"AAA": 99.4, "BBB": 99.0, "CCC": 95.0, "DDD": 80.0}
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: moves[s])

    result = await asyncio.wait_for(
        scanmod.run_scan(MagicMock(), bot=object(), chat_id="1", intraday=True), timeout=30.0
    )

    assert result.material_count == 4
    assert len(fetched) < 4, "budget should have cut at least one fetch"
    # Deepest movers bought first.
    assert "DDD" in fetched and "CCC" in fetched
    # Everything not fetched is carried forward, and nothing is lost.
    assert set(result.unreached_symbols) == set(syms) - set(fetched)


@pytest.mark.asyncio
async def test_budget_disabled_fetches_everything(tmp_path, monkeypatch):
    """budget=0 restores the old unbounded behaviour."""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    syms = ["AAA", "BBB", "CCC"]
    monkeypatch.setattr(
        cfg,
        "universe",
        {"would_own": syms, "actively_wheeling": syms, "sectors": {s: "tech" for s in syms}},
    )
    monkeypatch.setattr(cfg.market_data, "chain_fetch_budget_seconds", 0.0)
    _stub_common(scanmod, monkeypatch, positions=[])

    fetched: list[str] = []

    async def _slow(ib, symbol):
        await asyncio.sleep(0.05)
        fetched.append(symbol)
        return []

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _slow)
    monkeypatch.setattr(scanmod, "get_scan_state", lambda s: {x: _state(x, 100.0) for x in syms})
    monkeypatch.setattr(scanmod, "_fetch_last_price", lambda s: 80.0)

    result = await asyncio.wait_for(
        scanmod.run_scan(MagicMock(), bot=object(), chat_id="1", intraday=True), timeout=30.0
    )
    assert set(fetched) == set(syms)
    assert result.unreached_symbols == []


@pytest.mark.asyncio
async def test_manual_scan_is_never_budgeted(tmp_path, monkeypatch):
    """A manual /scan is operator-initiated and must sweep in full regardless of the budget."""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    cfg = get_config()
    syms = ["AAA", "BBB", "CCC"]
    monkeypatch.setattr(
        cfg,
        "universe",
        {"would_own": syms, "actively_wheeling": syms, "sectors": {s: "tech" for s in syms}},
    )
    monkeypatch.setattr(cfg.market_data, "chain_fetch_budget_seconds", 0.01)
    _stub_common(scanmod, monkeypatch, positions=[])

    fetched: list[str] = []

    async def _slow(ib, symbol):
        await asyncio.sleep(0.05)
        fetched.append(symbol)
        return []

    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", _slow)
    monkeypatch.setattr(scanmod, "get_scan_state", lambda s: {})

    await asyncio.wait_for(
        scanmod.run_scan(MagicMock(), bot=object(), chat_id="1", intraday=False), timeout=30.0
    )
    assert set(fetched) == set(syms)


# ---------------------------------------------------------------------------
# Put-call-parity spot vs the OTM-only chain (2026-08-28)
# ---------------------------------------------------------------------------


class TestParitySpotGuard:
    """`_build_chain_contracts` going OTM-only removed every both-rights strike, so parity is
    structurally impossible. The strike-quantized fallback must not reach the materiality
    baseline, where its ~0.8% error would swamp the 0.5% move gate."""

    @staticmethod
    def _q(strike, right, mid, expiry=date(2026, 9, 18)):
        from src.common.schemas import OptionQuote, OptionRight

        return OptionQuote(
            underlying="AAA",
            expiry=expiry,
            strike=strike,
            right=OptionRight.CALL if right == "C" else OptionRight.PUT,
            bid=mid - 0.05,
            ask=mid + 0.05,
        )

    def test_parity_used_when_both_rights_present(self):
        from src.analytics.iv import infer_spot_from_quotes

        quotes = [self._q(150.0, "C", 5.0), self._q(150.0, "P", 3.0)]
        # spot = strike + call_mid - put_mid = 150 + 5 - 3
        assert infer_spot_from_quotes(quotes, require_parity=True) == pytest.approx(152.0)

    def test_strict_returns_none_on_an_otm_only_chain(self):
        from src.analytics.iv import infer_spot_from_quotes

        # OTM-only: calls above spot, puts below — no strike carries both.
        quotes = [self._q(152.5, "C", 4.0), self._q(147.5, "P", 4.0)]
        assert infer_spot_from_quotes(quotes, require_parity=True) is None

    def test_loose_still_returns_the_rough_strike(self):
        """Term-structure/skew callers only rank strikes by distance to spot — half a strike
        increment is harmless there, so the default must keep working."""
        from src.analytics.iv import infer_spot_from_quotes

        quotes = [self._q(152.5, "C", 4.0), self._q(147.5, "P", 4.0)]
        assert infer_spot_from_quotes(quotes) is not None

    def test_otm_chain_leaves_no_parity_pairs(self):
        """Guards the premise: the real contract builder produces no both-rights strike."""
        from collections import defaultdict

        from src.ibkr.market_data import _build_chain_contracts, _cap_strikes, _filter_strikes

        spot = 149.97
        strikes = _cap_strikes(
            _filter_strikes([round(100 + 2.5 * i, 2) for i in range(41)], spot, 0.45), spot, 80
        )
        rights = defaultdict(set)
        for c in _build_chain_contracts("X", ["20260918"], strikes, spot):
            rights[c.strike].add(c.right)
        assert not [k for k, v in rights.items() if len(v) == 2]

    @pytest.mark.asyncio
    async def test_scan_symbol_passes_no_spot_override_for_an_otm_chain(self):
        """The precise contract: with an OTM-only chain, `scan_symbol` must hand analytics
        `spot_override=None` so `get_technical_stats` falls through to the yfinance probe price
        — not a strike, which would land in TechnicalStats.price and become the baseline."""
        from src.orchestrator.scan_pipeline import SymbolDeps, scan_symbol

        seen: dict = {}

        def _analytics(symbol, quotes, spot_override, cached_yf_price):
            seen["spot_override"] = spot_override
            seen["cached_yf_price"] = cached_yf_price
            raise RuntimeError("stop here — we only care about the arguments")

        otm_only = [self._q(152.5, "C", 4.0), self._q(147.5, "P", 4.0)]

        async def _chain(ib, symbol):
            return otm_only

        await scan_symbol(
            MagicMock(),
            "AAA",
            material=True,
            account=MagicMock(),
            positions=[],
            would_own=["AAA"],
            probed_spot=149.97,
            symbol_timeout_seconds=5.0,
            deps=SymbolDeps(
                fetch_chain=_chain,
                fetch_analytics=_analytics,
                score_sentiment=lambda s: None,
                screen_cc=MagicMock(),
                screen_csp=MagicMock(),
            ),
        )
        assert seen["spot_override"] is None, (
            f"got {seen['spot_override']} — a strike-quantized spot must not reach analytics"
        )
        assert seen["cached_yf_price"] == pytest.approx(149.97)
