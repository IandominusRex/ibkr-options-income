"""The Nasdaq-100 breadth data, by hand (risk-envelope Task 10a).

    python -m scripts.breadth backfill               # load the thetrading.tools history, recompute
    python -m scripts.breadth refresh-constituents   # rewrite config/breadth_constituents.yaml
    python -m scripts.breadth status                 # what is stored, and the latest LES signals

``backfill`` runs the same function the EOD run calls every night (`record_breadth_and_les`): the
history insert is idempotent, so it is safe to repeat. ``refresh-constituents`` is the quarterly
refresh of the committed constituent list (Operator to-do 9): it reads the components table of the
Wikipedia Nasdaq-100 article and **refuses to write** unless it finds 100 to 102 tickers; a page
without the table, or a changed layout, stops there with a message and changes nothing.
"""

from __future__ import annotations

import argparse
import html as htmllib
import re
import sys
from datetime import date

import yaml

from src.common.config import ROOT

CONSTITUENTS_PATH = ROOT / "config" / "breadth_constituents.yaml"
SOURCE_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
USER_AGENT = "ibkr-options-income/1.0 (personal research; constituent list refresh)"
_MIN_COUNT, _MAX_COUNT = 100, 102
_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,5}$")


def _text(cell: str) -> str:
    return htmllib.unescape(re.sub(r"<[^>]+>", "", cell)).strip()


def parse_components(page: str) -> list[str]:
    """The tickers of the components table: the table whose header has ``Ticker`` and ``Company``.

    Returns ``[]`` when no such table exists. Symbols are upper-cased; a cell that is not a ticker
    is skipped; the order of the page is kept.
    """
    for table in re.findall(r"<table.*?</table>", page, flags=re.S | re.I):
        rows = re.findall(r"<tr.*?</tr>", table, flags=re.S | re.I)
        if not rows:
            continue
        header = [_text(c) for c in re.findall(r"<t[hd].*?</t[hd]>", rows[0], flags=re.S | re.I)]
        lowered = [h.lower() for h in header]
        if "ticker" not in lowered or "company" not in lowered:
            continue
        col = lowered.index("ticker")
        out: list[str] = []
        for row in rows[1:]:
            cells = [_text(c) for c in re.findall(r"<t[hd].*?</t[hd]>", row, flags=re.S | re.I)]
            if len(cells) > col and _TICKER.match(cells[col].upper()):
                out.append(cells[col].upper())
        return list(dict.fromkeys(out))
    return []


def refresh_constituents(page: str | None = None, *, path=CONSTITUENTS_PATH) -> int:
    """Rewrite the committed constituent list from *page* (fetched when None). Returns the count.

    Raises ``RuntimeError`` (and writes nothing) unless the page yields 100 to 102 tickers.
    """
    if page is None:
        import httpx

        response = httpx.get(SOURCE_URL, timeout=30, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        page = response.text
    tickers = parse_components(page)
    if not (_MIN_COUNT <= len(tickers) <= _MAX_COUNT):
        raise RuntimeError(
            f"found {len(tickers)} tickers in the components table at {SOURCE_URL}; expected "
            f"{_MIN_COUNT}-{_MAX_COUNT}. The file was not changed: check the page, or write "
            "config/breadth_constituents.yaml by hand from the index provider's list."
        )
    path.write_text(
        "# The Nasdaq-100 constituents the nightly breadth count uses (risk-envelope Task 10a).\n"
        "# Refreshed quarterly by `python -m scripts.breadth refresh-constituents`.\n"
        + yaml.safe_dump(
            {"as_of": date.today().isoformat(), "source": SOURCE_URL, "ndx": tickers},
            sort_keys=False,
            default_flow_style=None,
            width=100,
        )
    )
    return len(tickers)


def _status() -> None:
    from src.storage import les_state
    from src.storage.db import init_db

    init_db()
    counts = les_state.load_counts()
    print(f"breadth counts stored: {len(counts)}")
    if counts:
        print(f"  first {counts[0].day}, last {counts[-1].day}")
    print(f"  flagged days (sources disagree): {len(les_state.flagged_days())}")
    print(f"  constituents in the file: {len(les_state.load_constituents())}")
    for index in ("QQQ", "SOXX"):
        sig = les_state.latest_signal(index)
        print(f"  LES {index}: {sig.model_dump() if sig else 'none yet'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.breadth", description=__doc__)
    parser.add_argument("command", choices=["backfill", "refresh-constituents", "status"])
    args = parser.parse_args(argv)
    if args.command == "refresh-constituents":
        try:
            n = refresh_constituents()
        except Exception as exc:  # noqa: BLE001
            print(f"refresh-constituents: {exc}", file=sys.stderr)
            return 2
        print(f"wrote {n} tickers to {CONSTITUENTS_PATH}")
        return 0
    if args.command == "status":
        _status()
        return 0
    from src.orchestrator.eod_report import record_breadth_and_les
    from src.storage.db import init_db

    init_db()
    print(record_breadth_and_les())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
