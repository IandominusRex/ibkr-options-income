"""The value book's calibration dry run (spec §17): score every name once and print the funnel.

    python -m scripts.value_dry_run backfill [--env-file PATH] [--universe-file PATH]
    python -m scripts.value_dry_run run [--env-file PATH] [--universe-file PATH]
        [--as-of YYYY-MM-DD] [--names GOOGL,META,BAC,MU] [--limit N] [--no-persist]
        [--out CARDS.json] [--report REPORT.txt]

``backfill`` queues and drains the research worker's own jobs (companyfacts and daily bars for
both value universes) in this process, writing research.db exactly as the worker would.
``run`` reads research.db read-only, fetches each name's yfinance market cap and next earnings
date, scores every name, ranks both lists, writes the ticker files to value.db (unless
``--no-persist``) and prints the pass funnel, the named names with every number, storage and
run time. No IBKR connection, no Telegram, no order path. Run it against copies of the
databases, never the live ones (the plan's Section D says how).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.common.value_universe import ValueUniverse
    from src.value.rank import RankEntry
    from src.value.schemas import ValueScorecard

NAMED = ("GOOGL", "META", "BAC", "MU")


def _load_env(path: str | None) -> None:
    """Before anything reads the config: the worktree has no .env of its own."""
    if path:
        from dotenv import load_dotenv

        load_dotenv(path, override=False)


def _universe(path: str | None) -> dict[str, Any]:
    if path:
        import yaml

        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    from src.common.universe import effective_universe

    return effective_universe()


def backfill(args: argparse.Namespace) -> int:
    from src.common.config import get_config
    from src.common.value_universe import build_value_universe
    from src.research.ingest.materialize import drain_ingest_jobs
    from src.research.ingest.symbols import refresh_symbol_directory
    from src.research.ingest.value_universe import enqueue_value_universe
    from src.research.store.models import IngestJobRow, SymbolRow
    from src.research.store.session import init_research_db, research_session

    init_research_db()
    with research_session() as s:
        if s.query(SymbolRow).count() == 0:
            refresh_symbol_directory()
    names = build_value_universe(get_config().value, _universe(args.universe_file)).all_names()
    counts = enqueue_value_universe(names)
    print(f"queued {counts} for {len(names)} names", flush=True)
    started = time.monotonic()
    while True:
        with research_session() as s:
            pending = s.query(IngestJobRow).filter_by(status="pending").count()
        if pending == 0:
            break
        done = drain_ingest_jobs(max_jobs=25)
        print(
            f"{time.monotonic() - started:7.0f}s  drained {done:3d}  pending {pending}", flush=True
        )
    with research_session() as s:
        failed = [(j.symbol, j.kind) for j in s.query(IngestJobRow).filter_by(status="failed")]
    print(f"backfill finished in {time.monotonic() - started:.0f}s; {len(failed)} jobs failed")
    for symbol, kind in failed:
        print(f"  failed: {symbol} {kind}")
    return 0


def _earnings(as_of: date) -> dict[str, date]:
    """Next earnings dates from news.db (spec §6.6), the earliest on or after *as_of*."""
    import src.news.store.queries as queries
    from src.news.store.readonly import read_only_session

    out: dict[str, date] = {}
    with read_only_session() as s:
        if s is None:
            return out
        for e in queries.earnings_between(s, as_of, as_of + timedelta(days=180)):
            out.setdefault(e.symbol, e.report_date)
    return out


def run(args: argparse.Namespace) -> int:
    from src.common import value_inputs as vi
    from src.common import value_universe as vu
    from src.common.config import get_config
    from src.common.value_types import Classification, MarketFacts, ValueInputs
    from src.research.store.models import SymbolRow
    from src.value.funnel import build_funnel, render_funnel, render_name
    from src.value.rank import filed_lists, rank_list, rs_cutoff
    from src.value.scorecard import build_scorecard

    vcfg = get_config().value
    as_of = args.as_of or date.today()
    t0 = time.monotonic()
    universe = vu.build_value_universe(vcfg, _universe(args.universe_file))
    names = universe.all_names()
    if args.limit:
        keep = set(names[: args.limit]) | set(NAMED)
        names = [n for n in names if n in keep]
    regime = vi.load_regime()
    earnings = _earnings(as_of)
    to_fetch = [n for n in names if n not in universe.etfs]
    with ThreadPoolExecutor(max_workers=4) as pool:
        facts = dict(zip(to_fetch, pool.map(vi.fetch_market_facts, to_fetch), strict=True))
    t_fetch = time.monotonic()

    inputs: list[ValueInputs] = []
    with vi.research_read() as s:
        if s is None:
            print("research.db not found", file=sys.stderr)
            return 1
        spy = vi.read_bars(s, "SPY", as_of)
        for symbol in names:
            cik, payload = vi.read_payload(s, symbol)
            row = s.get(SymbolRow, symbol)
            mf = facts.get(symbol, MarketFacts())
            sector, industry = universe.classification.get(symbol, (None, None))
            classification = Classification(
                sector=sector or mf.sector,
                industry=industry or mf.industry,
                source="snapshot" if industry else ("yfinance" if mf.industry else "none"),
                is_etf=symbol in universe.etfs
                or mf.quote_type == "ETF"
                or bool(row is not None and row.is_etf),
            )
            fin = (
                None
                if payload is None
                else vi.build_value_financials(
                    payload, as_of=as_of, stale_item_days=vcfg.rules.data_quality.stale_item_days
                )
            )
            inputs.append(
                ValueInputs(
                    symbol=symbol,
                    cik=cik,
                    as_of=as_of,
                    financials=fin,
                    price=vi.build_price_series(vi.read_bars(s, symbol, as_of), spy),
                    classification=classification,
                    yf_market_cap=mf.market_cap,
                    next_earnings=earnings.get(symbol, mf.next_earnings),
                    regime=regime,
                )
            )
    cutoff = rs_cutoff([i.price for i in inputs], vcfg.rules.timing.rs_bottom_pct)
    inputs = [i.model_copy(update={"rs_cutoff_6m": cutoff}) for i in inputs]
    t_load = time.monotonic()

    cards = [build_scorecard(i, vcfg) for i in inputs]
    deep, growth = rank_list(cards, "deep_value"), rank_list(cards, "quality_growth")
    filed = filed_lists(cards, deep, growth)
    t_score = time.monotonic()
    if not args.no_persist:
        _persist(cards, universe, deep, growth, dict(filed), as_of, cutoff, t0)
    t_persist = time.monotonic()

    trading = set(universe.trading)
    lines = [
        render_funnel(build_funnel([c for c in cards if c.symbol in trading]), "Trading universe"),
        "",
        render_funnel(build_funnel(cards), "Evidence + trading universe"),
        "",
    ]
    for symbol in args.names.split(",") if args.names else NAMED:
        card = next((c for c in cards if c.symbol == symbol.strip().upper()), None)
        lines += [render_name(card) if card else f"## {symbol}: not scored", ""]
    no_cap = sum(1 for i in inputs if not i.classification.is_etf and i.yf_market_cap is None)
    lines.append(
        f"regime {regime}; relative-strength line {cutoff}; no yfinance market cap: {no_cap}"
    )
    lines += _storage_lines()
    lines.append(
        f"run time: market facts {t_fetch - t0:.0f}s, load {t_load - t_fetch:.0f}s, "
        f"score+rank {t_score - t_load:.1f}s, persist {t_persist - t_score:.1f}s, "
        f"total {t_persist - t0:.0f}s for {len(cards)} names"
    )
    text = "\n".join(lines)
    print(text)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    if args.out:
        Path(args.out).write_text(
            json.dumps([c.model_dump(mode="json") for c in cards]), encoding="utf-8"
        )
    return 0


def _persist(
    cards: list[ValueScorecard],
    universe: ValueUniverse,
    deep: dict[str, RankEntry],
    growth: dict[str, RankEntry],
    filed: dict[str, str],
    as_of: date,
    cutoff: float | None,
    t0: float,
) -> None:
    from src.common.config import get_config
    from src.value.funnel import build_funnel
    from src.value.ruleset import ruleset_id
    from src.value.store import init_value_db, record_run, value_session
    from src.value.ticker_file import persist

    vcfg = get_config().value
    version, digest = ruleset_id(vcfg)
    now = datetime.now(UTC).replace(tzinfo=None)
    init_value_db()
    with value_session() as s:
        for card in cards:
            d, g = deep.get(card.symbol), growth.get(card.symbol)
            persist(
                s,
                card,
                universe=universe.tag(card.symbol),
                ranks={
                    "deep_value": d.score if d else None,
                    "quality_growth": g.score if g else None,
                },
                filed=filed.get(card.symbol),
                cfg=vcfg.ticker_file,
                session_row=True,
            )
        record_run(
            s,
            kind="dry_run",
            started_at=now - timedelta(seconds=time.monotonic() - t0),
            finished_at=now,
            as_of=as_of,
            ruleset_version=version,
            ruleset_hash=digest,
            names=len(cards),
            rs_cutoff_6m=cutoff,
            summary_json=build_funnel(cards).model_dump_json(),
        )


def _storage_lines() -> list[str]:
    from sqlalchemy import func

    from src.common.config import get_config
    from src.common.value_inputs import research_read
    from src.research.store.models import CompanyFactsRawRow

    cfg = get_config()
    out: list[str] = []
    with research_read() as s:
        if s is not None:
            n, total = s.query(
                func.count(CompanyFactsRawRow.cik),
                func.sum(func.length(CompanyFactsRawRow.payload_json)),
            ).one()
            avg = (total or 0) / n if n else 0
            out.append(
                f"raw companyfacts: {n} payloads, {(total or 0) / 1e6:,.0f} MB, "
                f"{avg / 1e6:.1f} MB average"
            )
    for label, url in (
        ("research.db", cfg.research_db_url_abs()),
        ("value.db", cfg.value_db_url_abs()),
    ):
        path = url[len("sqlite:///") :]
        if os.path.exists(path):
            out.append(f"{label}: {os.path.getsize(path) / 1e6:,.0f} MB")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Value book calibration dry run (spec §17)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("backfill", "run"):
        p = sub.add_parser(name)
        p.add_argument("--env-file", default=None)
        p.add_argument("--universe-file", default=None)
    r = sub.choices["run"]
    r.add_argument("--as-of", type=date.fromisoformat, default=None)
    r.add_argument("--names", default=None)
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--no-persist", action="store_true")
    r.add_argument("--out", default=None)
    r.add_argument("--report", default=None)
    args = parser.parse_args(argv)
    _load_env(args.env_file)
    from src.common.logging import setup_logging

    setup_logging()
    return backfill(args) if args.command == "backfill" else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
