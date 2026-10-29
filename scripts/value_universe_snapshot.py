"""Rebuild the value book's committed universe snapshots (spec §6.1).

    python -m scripts.value_universe_snapshot [--as-of YYYY-MM-DD]

Writes ``config/value_evidence_universe.csv`` (S&P 500) and ``config/value_universe.csv``
(S&P 100, its sector and industry joined from the S&P 500 table), each headed by
``# as_of: <date> source: ...``. Source: the constituents tables of Wikipedia's "List of S&P 500
companies" and "S&P 100" pages, through the MediaWiki parse API (the plain page refuses
scripted clients). Network only; touches no database. Review the diff before committing.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = "https://en.wikipedia.org/w/api.php"
# Wikimedia refuses a client without a contact URL in its User-Agent.
USER_AGENT = "IBKR-Income-System/1.0 (https://github.com/IandominusRex)"
SP500_PAGE = "List of S&P 500 companies"
SP100_PAGE = "S&P 100"
COLUMNS = ("symbol", "name", "sector", "industry", "cik")


class ConstituentsTable(HTMLParser):
    """Collects the text of every cell of the ``<table id="constituents">``, row by row."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._inside = False
        self._depth = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            if self._inside:
                self._depth += 1
            elif dict(attrs).get("id") == "constituents":
                self._inside, self._depth = True, 0
        if not self._inside:
            return
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if not self._inside:
            return
        if tag == "table":
            if self._depth == 0:
                self._inside = False
            else:
                self._depth -= 1
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_constituents(html: str) -> list[dict[str, str]]:
    """The constituents table as dicts keyed by its header cells."""
    table = ConstituentsTable()
    table.feed(html)
    if not table.rows:
        raise ValueError("no constituents table in the page")
    header, *body = table.rows
    return [dict(zip(header, row, strict=False)) for row in body if len(row) >= len(header)]


def fetch_page(page: str) -> str:
    resp = httpx.get(
        API,
        params={
            "action": "parse",
            "page": page,
            "prop": "text",
            "format": "json",
            "formatversion": "2",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    return str(resp.json()["parse"]["text"])


def sp500_rows(html: str) -> list[dict[str, str]]:
    out = []
    for rec in parse_constituents(html):
        out.append(
            {
                "symbol": rec["Symbol"].replace(".", "-"),
                "name": rec["Security"],
                "sector": rec["GICS Sector"],
                "industry": rec["GICS Sub-Industry"],
                "cik": rec.get("CIK", "").zfill(10) if rec.get("CIK") else "",
            }
        )
    return out


def sp100_rows(html: str, sp500: list[dict[str, str]]) -> list[dict[str, str]]:
    by_symbol = {r["symbol"]: r for r in sp500}
    out = []
    for rec in parse_constituents(html):
        symbol = rec["Symbol"].replace(".", "-")
        joined = by_symbol.get(symbol)
        out.append(
            joined
            if joined is not None
            else {
                "symbol": symbol,
                "name": rec["Name"],
                "sector": rec["Sector"],
                "industry": "",
                "cik": "",
            }
        )
    return out


def write_snapshot(path: Path, rows: list[dict[str, str]], as_of: date, source: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(f"# as_of: {as_of.isoformat()} source: {source}\n")
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r["symbol"]):
            writer.writerow({k: row.get(k, "") for k in COLUMNS})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    sp500 = sp500_rows(fetch_page(SP500_PAGE))
    sp100 = sp100_rows(fetch_page(SP100_PAGE), sp500)
    write_snapshot(
        ROOT / "config" / "value_evidence_universe.csv",
        sp500,
        args.as_of,
        f"Wikipedia, {SP500_PAGE}",
    )
    write_snapshot(
        ROOT / "config" / "value_universe.csv", sp100, args.as_of, f"Wikipedia, {SP100_PAGE}"
    )
    print(f"S&P 500: {len(sp500)} rows; S&P 100: {len(sp100)} rows; as of {args.as_of}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
