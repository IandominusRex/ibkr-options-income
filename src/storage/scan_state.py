"""Per-symbol intraday-scan materiality state (S1/S10).

Records the spot price and timestamp at each symbol's *last option-chain fetch*, plus
whether it cleared the score floor that cycle. The 15-min intraday loop reads this through
:func:`get_scan_state` to decide which symbols need a fresh chain fetch and which can be
skipped, and writes it back through :func:`bulk_upsert_scan_state` for every symbol it
actually fetched (in both full-sweep and intraday modes, so a full sweep seeds the baselines).
A seed-only dip_watch baseline (yfinance probe price persisted without a chain fetch at
startup / manual /scan) is also written here with ``last_scanned_at=NULL`` — see
``_persist_seed_only_baselines`` in orchestrator/scan.py (2026-08-28).

All failures are swallowed and logged — the materiality store is an optimisation, never a
correctness dependency; a read miss degrades to "treat as material" at the call site.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from src.storage.db import session_scope
from src.storage.models import ScanStateRow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanState:
    """Snapshot of one symbol's last-fetch state (see :class:`ScanStateRow`)."""

    symbol: str
    last_spot: float | None
    last_scanned_at: datetime | None
    cleared_floor: bool


def get_scan_state(symbols: Iterable[str]) -> dict[str, ScanState]:
    """Return the stored scan state for *symbols* (missing symbols are simply absent)."""
    wanted = set(symbols)
    if not wanted:
        return {}
    try:
        with session_scope() as s:
            rows = s.query(ScanStateRow).filter(ScanStateRow.symbol.in_(wanted)).all()
            return {
                r.symbol: ScanState(
                    symbol=r.symbol,
                    last_spot=r.last_spot,
                    last_scanned_at=r.last_scanned_at,
                    cleared_floor=bool(r.cleared_floor),
                )
                for r in rows
            }
    except Exception:
        log.warning("get_scan_state failed — treating all symbols as material", exc_info=True)
        return {}


def upsert_scan_state(
    symbol: str,
    *,
    last_spot: float | None,
    last_scanned_at: datetime,
    cleared_floor: bool,
) -> None:
    """Insert or update the materiality state for one *symbol*."""
    try:
        with session_scope() as s:
            row = s.query(ScanStateRow).filter_by(symbol=symbol).first()
            if row is None:
                s.add(
                    ScanStateRow(
                        symbol=symbol,
                        last_spot=last_spot,
                        last_scanned_at=last_scanned_at,
                        cleared_floor=cleared_floor,
                    )
                )
            else:
                if last_spot is not None:
                    row.last_spot = last_spot
                row.last_scanned_at = last_scanned_at
                row.cleared_floor = cleared_floor
    except Exception:
        log.warning("upsert_scan_state(%s) failed", symbol, exc_info=True)


def bulk_upsert_scan_state(
    updates: dict[str, tuple[float | None, datetime | None, bool]],
) -> None:
    """Batch-upsert materiality state for multiple symbols in a single DB transaction.

    *updates* maps symbol → (last_spot, last_scanned_at, cleared_floor). ``last_scanned_at`` is
    nullable: a NULL stamp marks a seed-only dip_watch baseline (yfinance probe price persisted
    so the per-cycle gate has something to compare against, without an IBKR chain fetch having
    happened — see ``_persist_seed_only_baselines`` in orchestrator/scan.py).
    Replaces N separate :func:`upsert_scan_state` calls (one per fetched symbol) with a
    single begin/commit so the 15-min loop doesn't pay N round-trips per cycle.
    """
    if not updates:
        return
    try:
        with session_scope() as s:
            existing = {
                r.symbol: r
                for r in s.query(ScanStateRow).filter(ScanStateRow.symbol.in_(updates)).all()
            }
            for symbol, (spot, scanned_at, cleared_floor) in updates.items():
                row = existing.get(symbol)
                if row is None:
                    s.add(
                        ScanStateRow(
                            symbol=symbol,
                            last_spot=spot,
                            last_scanned_at=scanned_at,
                            cleared_floor=cleared_floor,
                        )
                    )
                else:
                    if spot is not None:
                        row.last_spot = spot
                    row.last_scanned_at = scanned_at
                    row.cleared_floor = cleared_floor
    except Exception:
        log.warning("bulk_upsert_scan_state failed", exc_info=True)
