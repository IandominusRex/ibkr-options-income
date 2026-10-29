"""The value book's universes, the snapshot builder, and the research worker's sweep (Part 1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

import src.common.value_universe as vu
from scripts.value_universe_snapshot import parse_constituents, sp100_rows, sp500_rows
from src.common.config import ValueCfg

SP500_HTML = """
<table class="wikitable" id="constituents"><tbody>
<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th>
<th>Headquarters Location</th><th>Date added</th><th>CIK</th><th>Founded</th></tr>
<tr><td><a href="x">BRK.B</a></td><td>Berkshire Hathaway</td><td>Financials</td>
<td>Multi-Sector Holdings</td><td>Omaha</td><td>2010-02-16</td><td>0001067983</td><td>1839</td></tr>
<tr><td>GOOG</td><td>Alphabet Inc. (Class C)</td><td>Communication Services</td>
<td>Interactive Media &amp; Services</td><td>Mountain View</td><td>2006-04-03</td><td>0001652044</td><td>1998</td></tr>
<tr><td>GOOGL</td><td>Alphabet Inc. (Class A)</td><td>Communication Services</td>
<td>Interactive Media &amp; Services</td><td>Mountain View</td><td>2014-04-03</td><td>0001652044</td><td>1998</td></tr>
<tr><td>BAC</td><td>Bank of America</td><td>Financials</td><td>Diversified Banks</td>
<td>Charlotte</td><td>1976-06-30</td><td>0000070858</td><td>1998</td></tr>
</tbody></table>
<table id="other"><tr><th>x</th></tr><tr><td>y</td></tr></table>
"""

SP100_HTML = """
<table class="wikitable sortable" id="constituents"><tbody>
<tr><th>Symbol</th><th>Name</th><th>Sector</th></tr>
<tr><td>BAC</td><td>Bank of America</td><td>Financials</td></tr>
<tr><td>NEWCO</td><td>New Co</td><td>Industrials</td></tr>
</tbody></table>
"""


def test_the_snapshot_parser_reads_the_constituents_table_only() -> None:
    rows = parse_constituents(SP500_HTML)
    assert [r["Symbol"] for r in rows] == ["BRK.B", "GOOG", "GOOGL", "BAC"]
    assert rows[1]["GICS Sub-Industry"] == "Interactive Media & Services"


def test_sp500_rows_use_dashed_class_tickers_and_ten_digit_ciks() -> None:
    rows = sp500_rows(SP500_HTML)
    assert rows[0] == {
        "symbol": "BRK-B",
        "name": "Berkshire Hathaway",
        "sector": "Financials",
        "industry": "Multi-Sector Holdings",
        "cik": "0001067983",
    }


def test_sp100_rows_take_the_sp500_industry_and_keep_names_it_lacks() -> None:
    rows = sp100_rows(SP100_HTML, sp500_rows(SP500_HTML))
    assert rows[0]["industry"] == "Diversified Banks"
    assert rows[1] == {
        "symbol": "NEWCO",
        "name": "New Co",
        "sector": "Industrials",
        "industry": "",
        "cik": "",
    }


def _write(path, rows: list[str], as_of: str = "2026-10-29") -> None:
    path.write_text(
        f"# as_of: {as_of} source: test\nsymbol,name,sector,industry,cik\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )


def test_read_snapshot_returns_its_date_and_rows(tmp_path) -> None:
    p = tmp_path / "snap.csv"
    _write(p, ["BRK.B,Berkshire,Financials,Multi-Sector Holdings,1067983"])
    as_of, rows = vu.read_snapshot(p)
    assert as_of == date(2026, 10, 29)
    assert rows[0].symbol == "BRK-B" and rows[0].cik == "0001067983"
    assert vu.read_snapshot(tmp_path / "absent.csv") == (None, [])


def test_the_universes_merge_lists_snapshots_and_share_classes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vu, "ROOT", tmp_path)
    _write(tmp_path / "trading.csv", ["BAC,Bank of America,Financials,Diversified Banks,70858"])
    _write(
        tmp_path / "evidence.csv",
        [
            "BAC,Bank of America,Financials,Diversified Banks,70858",
            "GOOG,Alphabet C,Communication Services,Interactive Media & Services,1652044",
            "GOOGL,Alphabet A,Communication Services,Interactive Media & Services,1652044",
        ],
    )
    cfg = ValueCfg(
        universe={"trading_snapshot": "trading.csv", "evidence_snapshot": "evidence.csv"}
    )
    universe = {
        "indexes": ["QQQ"],
        "leveraged_etfs": ["SOXL"],
        "would_own": ["GOOGL", "QQQ", "HIMS"],
        "watchlist": ["META"],
    }
    out = vu.build_value_universe(cfg, universe)
    assert out.trading == ["BAC", "GOOGL", "HIMS", "META", "QQQ"]
    assert out.evidence == ["BAC", "GOOGL"]  # GOOG scored once, as GOOGL
    assert out.etfs == {"QQQ", "SOXL"}
    assert out.classification["GOOGL"] == ("Communication Services", "Interactive Media & Services")
    assert out.all_names() == ["BAC", "GOOGL", "HIMS", "META", "QQQ"]
    assert (out.tag("HIMS"), out.tag("BAC")) == ("trading", "trading")
    assert out.trading_as_of == date(2026, 10, 29)


def test_the_committed_snapshots_exist_and_are_dated() -> None:
    from src.common.config import ROOT, get_config

    cfg = get_config().value
    for rel, low, high in (
        (cfg.universe.trading_snapshot, 95, 110),
        (cfg.universe.evidence_snapshot, 495, 510),
    ):
        as_of, rows = vu.read_snapshot(ROOT / rel)
        assert as_of is not None, rel
        assert low <= len(rows) <= high, (rel, len(rows))


# ── the research worker's side ──────────────────────────────────────────────────────────────


@pytest.fixture()
def research_db(tmp_path, monkeypatch):
    from src.research.store.session import init_research_db

    monkeypatch.setattr(
        "src.research.store.session._resolve_url",
        lambda: f"sqlite:///{(tmp_path / 'research.db').as_posix()}",
    )
    monkeypatch.setattr("src.research.store.session._engine", None)
    init_research_db()


def test_the_sweep_queues_only_what_each_name_lacks(research_db) -> None:
    from src.research.ingest.value_universe import enqueue_value_universe
    from src.research.store.models import CompanyFactsRawRow, DailyBarRow, IngestJobRow, SymbolRow
    from src.research.store.session import research_session

    today = date(2026, 10, 29)
    now = datetime.now(UTC).replace(tzinfo=None)
    with research_session() as s:
        s.add(SymbolRow(symbol="FRESH", cik="0000000001"))
        s.add(SymbolRow(symbol="STALE", cik="0000000002"))
        s.add(CompanyFactsRawRow(cik="0000000001", payload_json="{}", fetched_at=now))
        s.add(
            CompanyFactsRawRow(
                cik="0000000002", payload_json="{}", fetched_at=now - timedelta(days=3)
            )
        )
        for i in range(260):
            s.add(DailyBarRow(symbol="FRESH", date=today - timedelta(days=260 - i), close=1.0))
    counts = enqueue_value_universe(["FRESH", "STALE", "NOCIK"], today=today)
    assert counts == {"fundamentals": 1, "prices": 2, "no_cik": 1}
    with research_session() as s:
        jobs = sorted((j.symbol, j.kind) for j in s.query(IngestJobRow))
    assert jobs == [("NOCIK", "prices"), ("STALE", "fundamentals"), ("STALE", "prices")]


def test_the_drain_runs_a_prices_job(research_db, monkeypatch) -> None:
    from src.research.ingest import materialize
    from src.research.store.models import IngestJobRow
    from src.research.store.session import research_session

    calls: list[str] = []
    monkeypatch.setattr(
        materialize, "ingest_daily_bars", lambda symbol: calls.append(symbol) or 250
    )
    materialize.enqueue("MU", "prices")
    assert materialize.drain_ingest_jobs() == 1
    assert calls == ["MU"]
    with research_session() as s:
        assert s.query(IngestJobRow).one().status == "done"


def test_a_prices_job_with_no_bars_is_retried_then_failed(research_db, monkeypatch) -> None:
    from src.research.ingest import materialize
    from src.research.store.models import IngestJobRow
    from src.research.store.session import research_session

    monkeypatch.setattr(materialize, "ingest_daily_bars", lambda symbol: 0)
    materialize.enqueue("ZZZZ", "prices")
    for _ in range(3):
        materialize.drain_ingest_jobs()
    with research_session() as s:
        job = s.query(IngestJobRow).one()
    assert (job.status, job.attempts) == ("failed", 3)
    assert "No daily bars" in (job.last_error or "")


def test_the_scheduler_adds_the_sweep_only_when_enabled(monkeypatch) -> None:
    from src.common.config import get_config
    from src.research.ingest.jobs import build_scheduler

    assert "value_sweep" not in {j.id for j in build_scheduler().get_jobs()}
    monkeypatch.setattr(get_config().value.research_sweep, "enabled", True)
    assert "value_sweep" in {j.id for j in build_scheduler().get_jobs()}
