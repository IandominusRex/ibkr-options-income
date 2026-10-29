"""The value book's two universes (spec §6.1). Neutral: the research worker's nightly sweep
and the value process read the same lists through it.

- **Trading universe**: ``universe.yaml``'s ``would_own`` + ``watchlist`` plus the trading
  snapshot (S&P 100). The names the strip shows and Stage 3 may act on.
- **Evidence universe**: the wider snapshot (S&P 500), scored by the same code for the shadow
  ledger only.

Snapshots are committed CSVs (``symbol,name,sector,industry,cik``) whose first line is
``# as_of: YYYY-MM-DD source: ...``; ``scripts/value_universe_snapshot.py`` rebuilds them.
A second share class of one filer is scored once, under its primary ticker.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.common.config import ROOT, ValueCfg

SNAPSHOT_COLUMNS = ("symbol", "name", "sector", "industry", "cik")


@dataclass(frozen=True, slots=True)
class SnapshotName:
    symbol: str
    name: str
    sector: str
    industry: str
    cik: str


@dataclass(slots=True)
class ValueUniverse:
    trading: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    etfs: set[str] = field(default_factory=set)
    classification: dict[str, tuple[str, str]] = field(default_factory=dict)  # sector, industry
    trading_as_of: date | None = None
    evidence_as_of: date | None = None

    def all_names(self) -> list[str]:
        return sorted(set(self.trading) | set(self.evidence))

    def tag(self, symbol: str) -> str:
        return "trading" if symbol in set(self.trading) else "evidence"


def normalise_symbol(raw: str) -> str:
    """EDGAR and yfinance spell a class share with a dash (BRK-B), Wikipedia with a dot."""
    return raw.strip().upper().replace(".", "-")


def read_snapshot(path: Path) -> tuple[date | None, list[SnapshotName]]:
    """``(as_of, rows)``; a missing file is ``(None, [])``."""
    if not path.exists():
        return None, []
    as_of: date | None = None
    rows: list[SnapshotName] = []
    with path.open(encoding="utf-8", newline="") as fh:
        lines = fh.read().splitlines()
    data = []
    for line in lines:
        if line.startswith("#"):
            if "as_of:" in line:
                token = line.split("as_of:", 1)[1].split()[0]
                as_of = date.fromisoformat(token)
            continue
        data.append(line)
    for rec in csv.DictReader(data):
        rows.append(
            SnapshotName(
                symbol=normalise_symbol(rec["symbol"]),
                name=rec.get("name", ""),
                sector=rec.get("sector", ""),
                industry=rec.get("industry", ""),
                cik=(rec.get("cik") or "").zfill(10) if rec.get("cik") else "",
            )
        )
    return as_of, rows


def _primary(symbol: str, share_class_primary: dict[str, str]) -> str:
    return share_class_primary.get(symbol, symbol)


def build_value_universe(cfg: ValueCfg, universe: dict[str, Any]) -> ValueUniverse:
    """Both universes from the config, *universe* (``effective_universe()`` or a YAML the
    caller read) and the two snapshots."""
    primary = {k.upper(): v.upper() for k, v in cfg.universe.share_class_primary.items()}
    trading_as_of, trading_rows = read_snapshot(ROOT / cfg.universe.trading_snapshot)
    evidence_as_of, evidence_rows = read_snapshot(ROOT / cfg.universe.evidence_snapshot)
    out = ValueUniverse(trading_as_of=trading_as_of, evidence_as_of=evidence_as_of)
    for row in [*evidence_rows, *trading_rows]:
        out.classification[_primary(row.symbol, primary)] = (row.sector, row.industry)
    out.etfs = {
        normalise_symbol(str(s))
        for key in ("indexes", "leveraged_etfs")
        for s in universe.get(key) or []
    }
    lists = {
        normalise_symbol(str(s))
        for key in ("would_own", "watchlist")
        for s in universe.get(key) or []
    }
    out.trading = sorted({_primary(s, primary) for s in lists | {r.symbol for r in trading_rows}})
    out.evidence = sorted({_primary(r.symbol, primary) for r in evidence_rows})
    return out
