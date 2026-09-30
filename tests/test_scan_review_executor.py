"""Task 11 fix round 1 — the full-scan path's Claude/Ollama review call must not block the
event loop.

`review_candidates` (dispatched to the local Ollama backend, `src/claude/ollama_runner.py`) does
blocking I/O (`httpx.post` to Ollama, and — Task 11 — a keyless news fetch plus a bounded
tool-calling research turn). The single-ticker `/scan TICKER` path (`run_ticker_scan`) already
wraps its call in `loop.run_in_executor`; the full-scan path (`run_scan`) called it directly,
freezing ib_async/Telegram/progress for however long the local model took — worse once the
research path can chain multiple HTTP calls (review, worst case, ~500s). This file proves the
full-scan call is now off the event loop, with IBKR mocked out and one real `TradeCandidate`
engineered to reach the Claude-review step via a mocked `scan_symbol` (bypassing the real
option-chain fetch entirely — that plumbing is exercised elsewhere).
"""

from __future__ import annotations

import asyncio
import time
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    MarketConditions,
    OptionRight,
    RiskVerdict,
    ScoreCard,
    Strategy,
    TechnicalStats,
    TradeCandidate,
    Verdict,
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


def _candidate() -> TradeCandidate:
    return TradeCandidate(
        candidate_id="exec-001",
        strategy=Strategy.COVERED_CALL,
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=200.0,
        expiry=date(2026, 12, 18),
        contracts=1,
        premium=2.0,
        collateral=20_000.0,
        roc_pct=1.0,
        annualized_yield_pct=12.0,
        breakeven=198.0,
        dte=60,
        scores=ScoreCard(symbol="AAPL"),
        blended_score=95.0,
    )


def _stub_scan(scanmod, monkeypatch, *, review_side_effect) -> None:
    """Mock IBKR/network plumbing and inject one candidate straight past the option-chain
    fetch via `scan_symbol`, so the run reaches the Claude-review step without needing a real
    quote pipeline (calibrating real delta/liquidity/risk-gate thresholds is out of scope here
    — `score_candidates`/`validate_candidates` are stubbed to pass the one candidate through)."""
    from src.orchestrator.scan_pipeline import ChainStatus, SymbolOutcome

    monkeypatch.setattr(scanmod, "get_account_snapshot_async", AsyncMock(return_value=_account()))
    monkeypatch.setattr(scanmod, "get_positions", lambda ib: [])
    monkeypatch.setattr(scanmod, "get_market_conditions", lambda: MarketConditions(vix=15.0))
    monkeypatch.setattr(scanmod, "send_candidates", AsyncMock())
    monkeypatch.setattr(scanmod, "send_buy_list", AsyncMock())
    monkeypatch.setattr(scanmod, "send_account_snapshot", AsyncMock())
    monkeypatch.setattr(scanmod, "generate_buy_candidates", lambda *a, **k: [])

    outcome = SymbolOutcome(
        symbol="AAPL",
        chain_status=ChainStatus.FETCHED,
        analytics=(
            IVStats(symbol="AAPL"),
            TechnicalStats(symbol="AAPL", price=200.0),
            FundamentalStats(symbol="AAPL"),
        ),
        cc_passed=[_candidate()],
    )
    monkeypatch.setattr(scanmod, "scan_symbol", AsyncMock(return_value=outcome))

    monkeypatch.setattr(scanmod, "score_candidates", lambda cands: cands)
    monkeypatch.setattr(
        scanmod,
        "validate_candidates",
        lambda scored, *a, **k: [
            RiskVerdict(candidate_id=c.candidate_id, verdict=Verdict.PASS) for c in scored
        ],
    )
    monkeypatch.setattr(scanmod, "review_candidates", review_side_effect)


async def test_full_scan_review_call_runs_off_the_event_loop(tmp_path, monkeypatch) -> None:
    """A slow, synchronous `review_candidates` must not freeze a concurrently-scheduled
    coroutine — proving the full-scan call site is wrapped in `run_in_executor`, matching the
    single-ticker path. Regression for the pre-fix-round-1 direct call at scan.py's Claude
    review step, which blocked ib_async/Telegram/progress for the model's full response time.
    """
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    _db_setup(tmp_path, monkeypatch)
    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {"would_own": ["AAPL"], "actively_wheeling": ["AAPL"], "sectors": {"AAPL": "tech"}},
    )

    window: dict[str, float] = {}

    def _blocking_review(*args, **kwargs):
        window["start"] = time.monotonic()
        time.sleep(0.5)
        window["end"] = time.monotonic()
        return []

    _stub_scan(scanmod, monkeypatch, review_side_effect=_blocking_review)

    ticks: list[float] = []
    stop = asyncio.Event()

    async def _heartbeat() -> None:
        while not stop.is_set():
            await asyncio.sleep(0.02)
            ticks.append(time.monotonic())

    heartbeat_task = asyncio.create_task(_heartbeat())
    await scanmod.run_scan(MagicMock(), bot=AsyncMock(), chat_id="1")
    stop.set()
    await heartbeat_task

    # Event-based, not a wall-clock race (final review minor — the old `elapsed < 0.5` margin
    # could flake on a loaded machine): if the synchronous review ran ON the event loop, the
    # heartbeat could not tick at all while it slept, so zero ticks would fall inside the
    # review's own [start, end] window. Off the loop (run_in_executor) it keeps ticking every
    # ~20ms through the 0.5s review — requiring just 3 is a wide margin either way.
    during = [t for t in ticks if window["start"] < t < window["end"]]
    assert len(during) >= 3, (
        f"review_candidates appears to have blocked the event loop: {len(during)} heartbeat "
        "tick(s) during the review"
    )


async def test_scan_lease_is_renewed_immediately_before_the_review(tmp_path, monkeypatch) -> None:
    """Final review I2(b): the 600s scan lease was renewed only inside the per-symbol loop, but
    the review alone may now take up to its full deadline + floor (300s) after the last symbol —
    so it is renewed right before the review starts, too."""
    import src.orchestrator.scan as scanmod
    from src.common.config import get_config

    _db_setup(tmp_path, monkeypatch)
    cfg = get_config()
    monkeypatch.setattr(
        cfg,
        "universe",
        {"would_own": ["AAPL"], "actively_wheeling": ["AAPL"], "sectors": {"AAPL": "tech"}},
    )
    events: list[str] = []

    def _review(*args, **kwargs):
        events.append("review")
        return []

    _stub_scan(scanmod, monkeypatch, review_side_effect=_review)

    def _score(cands):
        events.append("score")  # after the per-symbol loop, before the review
        return cands

    monkeypatch.setattr(scanmod, "score_candidates", _score)
    monkeypatch.setattr(scanmod, "renew_scan_lease", lambda *a, **k: events.append("renew") or True)

    await scanmod.run_scan(MagicMock(), bot=AsyncMock(), chat_id="1")

    assert "review" in events
    after_scoring = events[events.index("score") :]
    assert after_scoring[after_scoring.index("review") - 1] == "renew"
