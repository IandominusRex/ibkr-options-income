"""Shared pytest fixtures."""

from __future__ import annotations

import os

# Tests read the committed config/*.example.yaml, never the operator's private config/*.yaml
# (set before anything imports src.common.config and caches a Config).
os.environ["IBKR_CONFIG_USE_EXAMPLES"] = "1"

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.common import cache
from src.common.universe import invalidate_universe_cache


@pytest.fixture(autouse=True)
def _clear_daily_caches():
    """Reset the process-local daily caches around every test.

    Analytics helpers (get_fundamental_stats, _compute_hv30) are @daily_cached, and tests
    reuse the same symbol with different yfinance mocks. Without this, a cached result from
    one test would leak into the next and mask the mock.
    """
    cache.clear_all()
    yield
    cache.clear_all()


@pytest.fixture(autouse=True)
def _clear_effective_universe_cache():
    """Reset ``src.common.universe``'s process-local TTL cache around every test (M7 Task 7.3).

    ``effective_universe()`` (read by scan.py, eod_report.py, and others as of Task 7.3) caches
    its composed result for ``_TTL_SECONDS`` of *wall*-monotonic time — far longer than a test
    file takes to run. Several pre-existing scan tests monkeypatch ``get_config().universe``
    directly and expect the change to take effect immediately; without this reset, a value
    cached by an earlier test in the same pytest process would leak into a later one that
    monkeypatches a different universe, independent of any DB override.
    """
    invalidate_universe_cache()
    yield
    invalidate_universe_cache()


@pytest.fixture(autouse=True)
def _mock_telegram_sender(monkeypatch):
    """Prevent tests from hitting the live Telegram API via sender.py helpers.

    send_order_notification creates its own Bot(token=...) internally using the real
    system config — not the mock bot passed to execute_candidate — so without this patch
    executor tests make real HTTP round-trips (~1–2 s each) to Telegram.
    """
    monkeypatch.setattr("src.notify.sender.send_order_notification", AsyncMock())


# ---------------------------------------------------------------------------
# Web API fixtures (P3-P4 M2 Task 2.1). Shared by the portfolio route tests
# (2.1, 2.2, 2.4) and reused by M4's tests — one copy, per the milestone's own
# instruction, so a second copy in each test file cannot drift from this one.
# ---------------------------------------------------------------------------

OWNER_TOKEN = "owner-horse-battery"
OWNER = {"Authorization": f"Bearer {OWNER_TOKEN}"}


def _trading_db_client(monkeypatch, tmp_path: Path):
    """A TestClient over an isolated trading DB (the test_api_shorts.py pattern).

    Patches the token, the API's read-only engine, and the storage engine to a
    tmp-file SQLite so seeds lands in the DB the routes read, then returns the
    client. Callers seed through `src.storage.db.session_scope()`.
    """
    from fastapi.testclient import TestClient

    from src.api.main import create_app
    from src.common.config import Config

    monkeypatch.setattr("src.api.auth._configured_token", lambda: OWNER_TOKEN)
    trading_db = tmp_path / "income_system.db"
    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: trading_db.as_posix())
    monkeypatch.setattr("src.api.trading_db._cmd_engine", None)
    monkeypatch.setattr("src.api.trading_db._cmd_session_factory", None)
    import src.storage.db as dbmod

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{trading_db}")
    dbmod.init_db()
    return TestClient(create_app())


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """Owner-token TestClient over an empty, isolated trading DB."""
    return _trading_db_client(monkeypatch, tmp_path)


def _account_dict(net_liq: float, buying_power: float) -> dict[str, Any]:
    from src.common.schemas import AccountSnapshot

    return AccountSnapshot(
        account="DU123",
        net_liquidation=net_liq,
        total_cash=50_000.0,
        buying_power=buying_power,
        maintenance_margin=5_000.0,
        excess_liquidity=75_000.0,
    ).model_dump(mode="json")


@pytest.fixture()
def seed_portfolio_snapshot():
    """Insert one `portfolio_snapshots` row — rung 1 of read_portfolio's chain.

    Everything defaults to a fresh, monitor-captured snapshot 3 minutes old; tests pass
    captured_at/source/net_liq/buying_power/positions to vary it. `positions` takes the
    dicts the short_put/short_call/long_put/stock builders below return.
    """
    from src.storage.db import session_scope
    from src.storage.models import PortfolioSnapshotRow

    def _seed(
        *,
        captured_at: datetime | None = None,
        source: str = "monitor",
        net_liq: float = 250_000.0,
        buying_power: float = 80_000.0,
        positions: list[dict[str, Any]] | None = None,
    ) -> None:
        when = captured_at or datetime.now(UTC) - timedelta(minutes=3)
        with session_scope() as s:
            s.add(
                PortfolioSnapshotRow(
                    captured_at=when,
                    source=source,
                    account=_account_dict(net_liq, buying_power),
                    positions=positions or [],
                )
            )

    return _seed


@pytest.fixture()
def seed_position_snapshot():
    """Insert one `position_snapshots` row — the positions half of rung 2."""

    def _seed(*, symbols: list[str]) -> None:
        from src.storage.db import session_scope
        from src.storage.models import PositionSnapshotRow

        with session_scope() as s:
            s.add(
                PositionSnapshotRow(
                    snapshot_date=date.today(),
                    payload=[
                        {
                            "symbol": sym,
                            "sec_type": "STK",
                            "position": 100.0,
                            "avg_cost": 170.0,
                        }
                        for sym in symbols
                    ],
                )
            )

    return _seed


@pytest.fixture()
def seed_journal():
    """Insert one journal row whose payload carries the eod_summary account block."""

    def _seed(*, net_liq: float = 100_000.0) -> None:
        from src.storage.db import session_scope
        from src.storage.models import JournalRow

        with session_scope() as s:
            s.add(
                JournalRow(
                    entry_date=date.today(),
                    realized_pnl=0.0,
                    unrealized_pnl=0.0,
                    narrative=None,
                    payload={
                        "fills": [],
                        "eod_summary": {"account": _account_dict(net_liq, 80_000.0)},
                    },
                )
            )

    return _seed


@pytest.fixture()
def seed_campaign():
    """Insert one campaign row (Task 2.3's shape) with optional CandidateRows.

    `leg_candidate_ids` populates the leg list; `seed_candidates` names which of those
    ids actually have a CandidateRow — the rest are the "pruned" legs that must still
    render with `known: false`.
    """

    def _seed(
        *,
        symbol: str = "NVDA",
        leg_candidate_ids: list[str] | None = None,
        seed_candidates: list[str] | None = None,
        status: str = "open",
        strategy: str = "cash_secured_put",
        right: str = "P",
        strike: float = 190.0,
        dte: int = 30,
        assigned: bool = False,
        adjusted_cost_basis: float | None = None,
        realized_stock_pnl: float | None = None,
        total_premium_collected: float = 0.0,
        total_debit_paid: float = 0.0,
        net_premium: float = 0.0,
        opened: date | None = None,
        closed_date: date | None = None,
    ) -> None:
        import uuid

        from src.storage.db import session_scope
        from src.storage.models import CampaignRow, CandidateRow

        with session_scope() as s:
            for cid in seed_candidates or []:
                s.add(
                    CandidateRow(
                        candidate_id=cid,
                        run_id="run-1",
                        strategy=strategy,
                        underlying=symbol,
                        right=right,
                        strike=strike,
                        expiry=date.today() + timedelta(days=dte),
                        payload={},
                    )
                )
            s.add(
                CampaignRow(
                    campaign_id=f"{symbol}-{uuid.uuid4().hex[:8]}",
                    symbol=symbol,
                    status=status,
                    opened_date=opened or (date.today() - timedelta(days=10)),
                    closed_date=closed_date if status == "closed" else None,
                    leg_candidate_ids=leg_candidate_ids or [],
                    total_premium_collected=total_premium_collected,
                    total_debit_paid=total_debit_paid,
                    net_premium=net_premium,
                    assigned=assigned,
                    adjusted_cost_basis=adjusted_cost_basis,
                    realized_stock_pnl=realized_stock_pnl,
                    payload={"first_strategy": strategy},
                )
            )

    return _seed


@pytest.fixture()
def seed_assigned_campaign():
    """Insert one open, assigned campaign with an adjusted cost basis — Task 2.2's
    adjusted-basis join and Task 2.3's leg rendering both read this shape."""

    def _seed(
        *,
        symbol: str = "NVDA",
        assignment_price: float = 180.0,
        adjusted_basis: float = 173.50,
        leg_candidate_ids: list[str] | None = None,
        seed_candidates: list[str] | None = None,
        status: str = "open",
        strategy: str = "cash_secured_put",
    ) -> None:
        from src.storage.db import session_scope
        from src.storage.models import CampaignRow, CandidateRow

        ids = leg_candidate_ids or []
        with session_scope() as s:
            for cid in seed_candidates or []:
                s.add(
                    CandidateRow(
                        candidate_id=cid,
                        run_id="run-1",
                        strategy=strategy,
                        underlying=symbol,
                        right="P",
                        strike=190.0,
                        expiry=date.today() + timedelta(days=30),
                        payload={},
                    )
                )
            s.add(
                CampaignRow(
                    campaign_id=f"{symbol}-test01",
                    symbol=symbol,
                    status=status,
                    opened_date=date.today() - timedelta(days=10),
                    closed_date=date.today() if status == "closed" else None,
                    leg_candidate_ids=ids,
                    total_premium_collected=650.0,
                    total_debit_paid=0.0,
                    net_premium=650.0,
                    assigned=True,
                    adjusted_cost_basis=adjusted_basis,
                    realized_stock_pnl=None,
                    payload={"first_strategy": strategy},
                )
            )

    return _seed


# Position builders: minimal PositionSnapshot-shaped dicts with every field the
# portfolio routes read. Defaults exercise the interesting rules (a short put
# worth counting, a non-trivial delta) so tests only override what they assert.


def _et_today() -> date:
    """The exchange-calendar today — the one clock the portfolio routes measure
    dte and horizon gates in (`routers/portfolio.py::_today_et`). A builder
    default seeded from the local clock disagrees with the route's ET clock by
    one day whenever the two calendars straddle midnight, silently dropping the
    position past a horizon gate the test did not intend to exercise."""
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("America/New_York")).date()


def short_put(
    *,
    symbol: str = "NVDA  260918 00190000P",
    strike: float = 100.0,
    contracts: int = 1,
    delta: float | None = -0.22,
    dte: int | None = 45,
    underlying: str = "NVDA",
    market_price: float | None = 2.10,
    expiry: date | None = None,
) -> dict[str, Any]:
    exp = expiry or (_et_today() + timedelta(days=dte if dte is not None else 45))
    return {
        "symbol": symbol,
        "sec_type": "OPT",
        "position": -float(contracts),
        "avg_cost": 3.25,
        "market_price": market_price,
        "market_value": None,
        "unrealized_pnl": 115.0,
        "right": "P",
        "strike": strike,
        "expiry": exp.isoformat(),
        "delta": delta,
        "underlying": underlying,
    }


def short_call(
    *,
    symbol: str = "NVDA  260918 00200000C",
    strike: float = 200.0,
    contracts: int = 1,
    delta: float | None = 0.30,
    dte: int | None = 45,
    underlying: str = "NVDA",
    market_price: float | None = 1.50,
    expiry: date | None = None,
) -> dict[str, Any]:
    exp = expiry or (_et_today() + timedelta(days=dte if dte is not None else 45))
    return {
        "symbol": symbol,
        "sec_type": "OPT",
        "position": -float(contracts),
        "avg_cost": 2.50,
        "market_price": market_price,
        "market_value": None,
        "unrealized_pnl": None,
        "right": "C",
        "strike": strike,
        "expiry": exp.isoformat(),
        "delta": delta,
        "underlying": underlying,
    }


def long_put(
    *,
    symbol: str = "AAPL  260918 0015000P",
    strike: float = 90.0,
    contracts: int = 1,
    underlying: str = "AAPL",
) -> dict[str, Any]:
    exp = (_et_today() + timedelta(days=45)).isoformat()
    return {
        "symbol": symbol,
        "sec_type": "OPT",
        "position": float(contracts),
        "avg_cost": 1.10,
        "market_price": 0.90,
        "market_value": None,
        "unrealized_pnl": None,
        "right": "P",
        "strike": strike,
        "expiry": exp,
        "delta": -0.15,
        "underlying": underlying,
    }


def stock(
    *,
    symbol: str = "NVDA",
    shares: float = 100.0,
    avg_cost: float = 180.0,
    market_price: float | None = 176.0,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "sec_type": "STK",
        "position": shares,
        "avg_cost": avg_cost,
        "market_price": market_price,
        "market_value": None,
        "unrealized_pnl": None,
    }


# ---------------------------------------------------------------------------
# P&L engine fixtures (P3-P4 M4 Tasks 4.3/4.4/4.7). Shared by the reporting
# builder tests and the wheel-scenario suite — one copy, beside the M2 Task 2.1
# fixtures, so a second copy in each test file cannot drift from this one.
# Same DB-isolation pattern as the M2 fixtures above: patch the storage engine
# to a tmp-file SQLite so seeds land in the DB build_legs reads.
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """An isolated trading DB; yields a session-maker scoped to it.

    Yields `session_scope` itself — tests call `with db() as s:` to seed, and pass
    `db` (the session-maker) to the reporting builders, whose `session` parameter
    is exactly that: a callable yielding a session.
    """
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    return dbmod.session_scope


@pytest.fixture()
def seed_leg(db):
    """Seed one option leg: CandidateRow + SELL/BUY FillRows, optionally a campaign.

    `sold`/`bought` are `(qty, price)` or `(qty, price, commission)` tuples — one FillRow
    each. `expiry_in_days` is relative to today (negative = already expired).
    `prune_candidate=True` skips the CandidateRow, simulating a pruned candidate whose
    fills survive. `days_held` overrides the natural opened→closed span (0 = same-day).
    `strike=None` seeds a candidate with no strike — collateral is unknown.
    """

    def _seed(
        *,
        candidate_id: str,
        sold: tuple[float, float] | tuple[float, float, float] | None = None,
        bought: tuple[float, float] | tuple[float, float, float] | None = None,
        expiry_in_days: int = 30,
        campaign_id: str | None = None,
        prune_candidate: bool = False,
        strike: float | None = 170.0,
        strategy: str = "cash_secured_put",
        right: str = "P",
        symbol: str = "NVDA",
        is_live: bool = False,
        days_held: int | None = None,
    ) -> None:
        from datetime import datetime, timedelta

        from sqlalchemy import select

        from src.storage.models import CampaignRow, CandidateRow, FillRow

        expiry = date.today() + timedelta(days=expiry_in_days)
        opened = datetime.now() - timedelta(days=(days_held if days_held is not None else 5))

        def _fills(spec, action):
            if spec is None:
                return []
            qty, price = spec[0], spec[1]
            commission = spec[2] if len(spec) > 2 else 1.0
            close_offset = days_held if days_held is not None else 1
            return [
                FillRow(
                    order_id=1,
                    candidate_id=candidate_id,
                    action=action,
                    filled_qty=qty,
                    avg_price=price,
                    commission=commission,
                    is_live=is_live,
                    filled_at=opened if action == "SELL" else opened + timedelta(days=close_offset),
                )
            ]

        with db() as s:
            if not prune_candidate:
                s.add(
                    CandidateRow(
                        candidate_id=candidate_id,
                        run_id="run-1",
                        strategy=strategy,
                        underlying=symbol,
                        right=right,
                        strike=strike if strike is not None else 0.0,
                        expiry=expiry,
                        payload={},
                    )
                )
            for f in _fills(sold, "SELL") + _fills(bought, "BUY"):
                s.add(f)
            if campaign_id is not None:
                existing = s.execute(
                    select(CampaignRow).where(CampaignRow.campaign_id == campaign_id)
                ).scalar_one_or_none()
                if existing is not None:
                    # Append to the existing campaign's leg list — one campaign, many legs.
                    leg_ids = list(existing.leg_candidate_ids or [])
                    if candidate_id not in leg_ids:
                        leg_ids.append(candidate_id)
                        existing.leg_candidate_ids = leg_ids
                else:
                    s.add(
                        CampaignRow(
                            campaign_id=campaign_id,
                            symbol=symbol,
                            status="open",
                            opened_date=opened.date(),
                            leg_candidate_ids=[candidate_id],
                            payload={"first_strategy": strategy},
                        )
                    )

    return _seed


@pytest.fixture()
def set_campaign(db):
    """Flip a seeded campaign's `assigned` flag — proves build_legs reads it, not a recompute."""

    def _set(campaign_id: str, *, assigned: bool) -> None:
        from sqlalchemy import select

        from src.storage.models import CampaignRow

        with db() as s:
            row = s.execute(
                select(CampaignRow).where(CampaignRow.campaign_id == campaign_id)
            ).scalar_one()
            row.assigned = assigned

    return _set


@pytest.fixture()
def seed_candidate_only(db):
    """Seed a CandidateRow with no fills — never a position, so never a leg."""

    def _seed(candidate_id: str, *, symbol: str = "NVDA") -> None:
        from datetime import timedelta

        from src.storage.models import CandidateRow

        with db() as s:
            s.add(
                CandidateRow(
                    candidate_id=candidate_id,
                    run_id="run-1",
                    strategy="cash_secured_put",
                    underlying=symbol,
                    right="P",
                    strike=170.0,
                    expiry=date.today() + timedelta(days=30),
                    payload={},
                )
            )

    return _seed


@pytest.fixture()
def snapshot_mark():
    """Build a PortfolioSnapshot carrying one OPT position (and optional STK position).

    The mark source `build_campaigns` reads — the same snapshot the portfolio page
    renders, so the two surfaces agree by construction.
    """

    def _make(
        *,
        underlying: str,
        strike: float,
        right: str,
        unrealized_pnl: float,
        stock_unrealized: float | None = None,
        expiry_in_days: int = 30,
    ):
        from datetime import timedelta

        from src.common.schemas import PortfolioSnapshot, PositionSnapshot

        positions = [
            PositionSnapshot(
                symbol=f"{underlying} OPT",
                sec_type="OPT",
                position=-1.0,
                avg_cost=1.50,
                market_price=1.05,
                unrealized_pnl=unrealized_pnl,
                right=right,  # type: ignore[arg-type]
                strike=strike,
                expiry=date.today() + timedelta(days=expiry_in_days),
                underlying=underlying,
            )
        ]
        if stock_unrealized is not None:
            positions.append(
                PositionSnapshot(
                    symbol=underlying,
                    sec_type="STK",
                    position=100.0,
                    avg_cost=170.0,
                    market_price=175.0,
                    unrealized_pnl=stock_unrealized,
                )
            )
        return PortfolioSnapshot(
            captured_at=datetime.now(UTC),
            source="monitor",
            positions=positions,
        )

    return _make


@pytest.fixture()
def seed_journal_day(db):
    """Insert one JournalRow for an arbitrary date with a configurable payload.

    The default payload carries a valid eod_summary account block (the same shape
    `seed_journal` writes); `payload=` overrides it entirely (e.g. a corrupt account
    for the unreadable-payload test), `realized_pnl=` sets the premium-cashflow column.
    """

    def _seed(
        entry_date: date,
        *,
        realized_pnl: float | None = 0.0,
        net_liq: float = 100_000.0,
        unrealized_pnl: float | None = 0.0,
        payload: dict | None = None,
    ) -> None:
        from src.storage.models import JournalRow

        if payload is None:
            payload = {
                "fills": [],
                "eod_summary": {"account": _account_dict(net_liq, 80_000.0)},
            }
        with db() as s:
            s.add(
                JournalRow(
                    entry_date=entry_date,
                    realized_pnl=realized_pnl,
                    unrealized_pnl=unrealized_pnl,
                    narrative=None,
                    payload=payload,
                )
            )

    return _seed


@pytest.fixture()
def seed_wheel_ledger(seed_leg):
    """Seed a closed-trade book AND a verdict-ledger row per leg, for the M4 cross-check.

    Two closed legs (one expired worthless, one bought back) so `reconcile()` has
    rows to settle and the ledger-vs-reporting-layer cross-check has both branches.
    """

    def _seed() -> None:
        from datetime import timedelta

        from src.claude.eval.ledger import record_verdicts
        from src.common.schemas import OptionRight, Strategy, VerdictRecord

        seed_leg(candidate_id="led1", sold=(1, 2.40, 1.30), expiry_in_days=-3, strike=170.0)
        seed_leg(
            candidate_id="led2",
            sold=(1, 1.50, 1.10),
            bought=(1, 0.90, 0.90),
            expiry_in_days=-10,
            strike=175.0,
        )

        records = [
            VerdictRecord(
                candidate_id="led1",
                run_id="run1",
                scan_date=date.today() - timedelta(days=40),
                underlying="NVDA",
                strategy=Strategy.CASH_SECURED_PUT,
                right=OptionRight.PUT,
                strike=170.0,
                expiry=date.today() - timedelta(days=3),
                dte=30,
                signals={"blended_score": 80, "iv_rank": 55, "delta": 0.28, "vrp": 4},
                claude_recommendation="sell",
                claude_priority=1,
                claude_confidence=0.7,
                claude_rationale="because",
                baseline_recommendation="sell",
                baseline_rank=1,
                baseline_score=80.0,
            ),
            VerdictRecord(
                candidate_id="led2",
                run_id="run1",
                scan_date=date.today() - timedelta(days=40),
                underlying="NVDA",
                strategy=Strategy.CASH_SECURED_PUT,
                right=OptionRight.PUT,
                strike=175.0,
                expiry=date.today() - timedelta(days=10),
                dte=30,
                signals={"blended_score": 75, "iv_rank": 50, "delta": 0.30, "vrp": 3},
                claude_recommendation="sell",
                claude_priority=2,
                claude_confidence=0.6,
                claude_rationale="because",
                baseline_recommendation="sell",
                baseline_rank=2,
                baseline_score=75.0,
            ),
        ]
        record_verdicts(records)

    return _seed


@pytest.fixture()
def seed_closed_ledger_rows(client):  # noqa: ARG001 - binds storage engine to the client's DB
    """Write `n` closed verdict-ledger rows spanning the blended-score bands (P3-P4 M6 Task 6.1).

    Alternates win/loss and sell/skip so the report's buckets, correlations, and the route's
    agreement figure all have real spread. `offset_days` sets how many days ago `outcome_date`
    falls, and namespaces candidate_id, so a test can call this twice to build two date cohorts
    for a since/until window test without the second call's upsert clobbering the first.
    """

    def _seed(*, n: int = 10, offset_days: int = 1) -> None:
        from src.claude.eval.ledger import record_verdicts
        from src.common.schemas import OptionRight, Strategy, VerdictOutcome, VerdictRecord

        records = []
        for i in range(n):
            win = i % 2 == 0
            score = 55.0 + (i % 5) * 10.0
            records.append(
                VerdictRecord(
                    candidate_id=f"score-{offset_days}-{i}",
                    run_id="run-score",
                    scan_date=date.today() - timedelta(days=offset_days + 30),
                    underlying="NVDA",
                    strategy=Strategy.CASH_SECURED_PUT,
                    right=OptionRight.PUT,
                    strike=170.0,
                    expiry=date.today() - timedelta(days=offset_days),
                    dte=30,
                    signals={
                        "blended_score": score,
                        "iv_rank": 50.0 + i,
                        "delta": 0.25,
                        "vrp": 3.0,
                        "prob_otm": 0.7,
                        "roc_pct": 2.0,
                        "scores": {
                            "iv": score,
                            "technical": score - 5,
                            "fundamental": score - 10,
                            "liquidity": score + 5,
                            "assignment_safety": score,
                            "sentiment": score - 2,
                        },
                    },
                    claude_recommendation="sell" if win else "skip",
                    claude_priority=1,
                    claude_confidence=0.7,
                    claude_rationale="because",
                    baseline_recommendation="sell",
                    baseline_rank=1,
                    baseline_score=score,
                    agreement=win,
                    outcome=(VerdictOutcome.EXPIRED_WORTHLESS if win else VerdictOutcome.ASSIGNED),
                    outcome_date=date.today() - timedelta(days=offset_days),
                    realized_pnl=150.0 if win else -50.0,
                    filled=True,
                )
            )
        record_verdicts(records)

    return _seed


# ---------------------------------------------------------------------------
# API + storage on one file (P3-P4 M5). The M4 `db` fixture points the storage
# engine at `tmp_path/t.db` while the `client` fixture's API reads
# `tmp_path/income_system.db` — two different files, invisible as long as the
# reporting builders are called with `db` directly (M4's tests never cross the
# boundary). The M5 route tests DO cross it: `seed_leg` writes through the
# storage engine and `/pnl/ledger` reads through the API's read-only engine.
# These fixtures put both engines on one file, then reuse `seed_leg` unchanged —
# no second copy of any seed can drift.
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_db(monkeypatch, tmp_path, client):
    """The storage session-maker, bound to the same DB the API client reads.

    The M4 `db` fixture above points the storage engine at a private `t.db`
    while the `client` fixture's API reads `income_system.db` — two different
    files, invisible while the reporting builders were called with `db`
    directly (M4's tests never cross the boundary) but wrong the moment an M5
    route test does: `seed_leg` writes through the storage engine and
    `/pnl/*` reads through the API's read-only engine. This fixture rebinds
    the storage engine to the client's `income_system.db` (already
    initialised by the `client` fixture) and yields `session_scope` exactly
    like the M4 fixture, so `seed_leg` and friends work unchanged beside a
    live TestClient. Tests that need both sides request `api_db` explicitly
    in place of `db`.
    """
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(
        Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'income_system.db'}"
    )
    dbmod.init_db()
    return dbmod.session_scope


@pytest.fixture()
def seed_wheel(seed_leg):
    """A three-leg wheel across two symbols: one campaigned, one campaign-less
    (synthetic thread), one on another symbol. The M5 route tests' shared shape."""

    def _seed() -> None:
        seed_leg(
            candidate_id="w1",
            sold=(1, 1.5, 1.0),
            bought=(1, 0.5, 1.0),
            campaign_id="NVDA-wheel",
            expiry_in_days=-3,
        )
        seed_leg(candidate_id="w2", sold=(1, 2.0, 1.0), expiry_in_days=-2)
        seed_leg(candidate_id="w3", sold=(1, 1.0, 1.0), symbol="AAPL", expiry_in_days=-1)

    return _seed


@pytest.fixture(autouse=True)
def _forbid_real_gateway_restart(monkeypatch):
    """Never let a test run launchctl or signal a real process group.

    ``src/ops/gateway_control.py`` restarts the operator's actual IB Gateway. On 2026-10-02 an
    intraday-loop test that fed an Error 10197 probe through the loop — without mocking the
    restarter — restarted the live Gateway twice mid-session. Tests that exercise the
    restarter inject their own fakes (``run=``/``killpg=``); anything that reaches the real
    OS boundary fails loudly instead.
    """
    import src.ops.gateway_control as gc

    def _refuse(*args, **kwargs):
        raise AssertionError(f"test tried to touch the real Gateway: {args!r}")

    monkeypatch.setattr(gc, "_run_cmd", _refuse)
    monkeypatch.setattr(gc, "_killpg", _refuse)


@pytest.fixture(autouse=True)
def _blank_flex_secrets(monkeypatch):
    """Keep the test session network-isolated from the IBKR Flex Web Service (Task 10, F9b).

    A developer's real .env may carry a live IBKR_FLEX_TOKEN/IBKR_FLEX_QUERY_ID. get_config()
    is a process-wide @lru_cache(maxsize=1), so without this, any test that reaches
    run_flex_pull — directly, via the EOD orchestrator's step 7b, or via
    scripts.ledger_flex_pull — could make a real HTTP request against IBKR using those
    credentials. Blank both env vars and drop the cached Config so every test sees Flex as
    unconfigured unless it explicitly monkeypatches its own token/query id back in.
    """
    from src.common.config import get_config

    monkeypatch.setenv("IBKR_FLEX_TOKEN", "")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "")
    get_config.cache_clear()
    yield
    get_config.cache_clear()
