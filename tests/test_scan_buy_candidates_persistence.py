"""Task 6.1 — orchestrator wiring for buy-candidate persistence (2026-09-05).

`generate_buy_candidates` output is now persisted via `save_buy_candidates` at both
orchestrator call sites: the full scan (`run_scan`) and the single-ticker `/scan TICKER`
path (`run_ticker_scan`). The storage layer's own round-trip and isolation guarantees are
covered by `tests/test_storage_buy_candidates.py`; this file proves the orchestrator
actually calls through to it, end to end, with IBKR and network calls mocked out.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from src.common.schemas import (
    AccountSnapshot,
    BuyCandidate,
    FundamentalStats,
    IVStats,
    MarketConditions,
    TechnicalStats,
)


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=200_000.0,
        total_cash=150_000.0,
        buying_power=120_000.0,
        maintenance_margin=10_000.0,
        excess_liquidity=110_000.0,
    )


def _stub_scan_common(scanmod, monkeypatch) -> None:
    """Mock every network/IBKR touchpoint shared by run_scan and run_ticker_scan.

    Empty option chains everywhere collapse both pipelines to their simplest path — no
    CC/CSP candidates, no Claude review — which is all this file needs since it is only
    checking that generate_buy_candidates' output reaches save_buy_candidates.
    """
    monkeypatch.setattr(scanmod, "get_account_snapshot_async", AsyncMock(return_value=_account()))
    monkeypatch.setattr(scanmod, "get_positions", lambda ib: [])
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
    monkeypatch.setattr(scanmod, "get_option_chain_quotes_async", AsyncMock(return_value=[]))

    class _DummySentiment:
        def __init__(self, **kwargs):
            pass

        def score(self, symbol):
            return None

    monkeypatch.setattr(scanmod, "SentimentScorer", _DummySentiment)
    monkeypatch.setattr(scanmod, "send_candidates", AsyncMock())
    monkeypatch.setattr(scanmod, "send_buy_list", AsyncMock())
    monkeypatch.setattr(scanmod, "send_account_snapshot", AsyncMock())


async def test_full_scan_persists_buy_candidates(tmp_path, monkeypatch) -> None:
    """A full scan writes generate_buy_candidates' output under the scan's real run_id."""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config
    from src.storage.buy_candidates import latest_buy_candidates

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {"would_own": ["AAPL"], "actively_wheeling": ["AAPL"], "sectors": {"AAPL": "tech"}},
    )
    _stub_scan_common(scanmod, monkeypatch)
    candidates = [BuyCandidate(symbol="AAPL", score=80.0, sector="tech")]
    monkeypatch.setattr(scanmod, "generate_buy_candidates", lambda *a, **k: candidates)

    result = await scanmod.run_scan(MagicMock(), bot=AsyncMock(), chat_id="1")

    saved = latest_buy_candidates()
    assert [c.symbol for c in saved] == ["AAPL"]
    assert saved[0].score == 80.0
    assert result.run_id and not result.run_id.startswith("scan-")


async def test_single_ticker_scan_does_not_displace_the_full_scan(tmp_path, monkeypatch) -> None:
    """A /scan NVDA must never replace the whole recommendations list with one name."""
    _db_setup(tmp_path, monkeypatch)
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config
    from src.storage.buy_candidates import latest_buy_candidates

    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {
            "would_own": ["AAPL", "NVDA"],
            "actively_wheeling": ["AAPL", "NVDA"],
            "sectors": {"AAPL": "tech", "NVDA": "semis"},
        },
    )
    _stub_scan_common(scanmod, monkeypatch)
    monkeypatch.setattr(
        "src.ibkr.contracts.qualify_stock_async", AsyncMock(return_value=MagicMock())
    )
    monkeypatch.setattr(scanmod, "get_sector_context", lambda symbol: None)

    full_scan_candidates = [BuyCandidate(symbol="AAPL", score=80.0, sector="tech")]
    monkeypatch.setattr(scanmod, "generate_buy_candidates", lambda *a, **k: full_scan_candidates)
    await scanmod.run_scan(MagicMock(), bot=AsyncMock(), chat_id="1")
    assert [c.symbol for c in latest_buy_candidates()] == ["AAPL"]

    ticker_candidates = [BuyCandidate(symbol="NVDA", score=95.0, sector="semis")]
    monkeypatch.setattr(scanmod, "generate_buy_candidates", lambda *a, **k: ticker_candidates)
    await scanmod.run_ticker_scan(
        MagicMock(), "NVDA", bot=AsyncMock(), chat_id="1", progress_msg_id=1
    )

    # The full scan's list is untouched — NVDA's single-ticker run went to a scan- row.
    assert [c.symbol for c in latest_buy_candidates()] == ["AAPL"]

    import src.storage.db as dbmod
    from src.storage.models import BuyCandidateRow

    with dbmod.session_scope() as s:
        run_ids = {r.run_id for r in s.query(BuyCandidateRow).all()}
    assert any(rid.startswith("scan-NVDA-") for rid in run_ids)
