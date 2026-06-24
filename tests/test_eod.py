"""Tests for Phase 9: EOD reporting + journaling.

All IBKR and Telegram calls are mocked. DB tests use tmp_path + in-process SQLite.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.common.schemas import (
    AccountSnapshot,
    EODSummary,
    OptionRight,
    PositionSnapshot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(nlv: float = 100_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU123456",
        net_liquidation=nlv,
        total_cash=50_000.0,
        buying_power=80_000.0,
        maintenance_margin=5_000.0,
        excess_liquidity=75_000.0,
    )


def _make_option_pos(
    symbol: str = "AAPL  260117C00185000",
    underlying: str = "AAPL",
    position: float = -1.0,
    unrealized_pnl: float = -50.0,
    delta: float | None = 0.28,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        sec_type="OPT",
        position=position,
        avg_cost=150.0,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date.today() + timedelta(days=30),
        underlying=underlying,
        unrealized_pnl=unrealized_pnl,
        delta=delta,
    )


def _make_stock_pos(symbol: str = "AAPL", position: float = 100.0) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        sec_type="STK",
        position=position,
        avg_cost=180.0,
        market_price=182.0,
        market_value=18_200.0,
        unrealized_pnl=200.0,
        underlying=symbol,
    )


def _make_eod_summary(**kwargs: object) -> EODSummary:
    defaults: dict = dict(
        date=date.today(),
        realized_pnl=142.50,
        unrealized_pnl=-320.0,
        unrealized_pnl_delta=-85.0,
        fills_today=2,
        open_positions=3,
        net_delta_exposure=-0.28,
        account=_make_account(),
        top_movers=["AAPL", "SPY"],
        tomorrow_watchlist=["AAPL", "SPY", "NVDA"],
    )
    defaults.update(kwargs)
    return EODSummary(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# EODSummary schema
# ---------------------------------------------------------------------------


def test_eod_summary_constructs() -> None:
    s = _make_eod_summary()
    assert s.realized_pnl == pytest.approx(142.50)
    assert s.open_positions == 3
    assert "AAPL" in s.tomorrow_watchlist


def test_eod_summary_serializes() -> None:
    s = _make_eod_summary()
    d = s.model_dump(mode="json")
    assert d["realized_pnl"] == pytest.approx(142.50)
    assert isinstance(d["date"], str)
    assert d["account"]["net_liquidation"] == pytest.approx(100_000.0)


# ---------------------------------------------------------------------------
# _build_eod_summary
# ---------------------------------------------------------------------------


def test_build_eod_summary_realized_pnl() -> None:
    from src.orchestrator.eod_report import _build_eod_summary

    positions = [_make_option_pos()]
    account = _make_account()
    summary = _build_eod_summary(positions, account, 142.50, 2, -235.0, ["AAPL", "SPY"])
    assert summary.realized_pnl == pytest.approx(142.50)
    assert summary.fills_today == 2


def test_build_eod_summary_unrealized_delta() -> None:
    from src.orchestrator.eod_report import _build_eod_summary

    positions = [_make_option_pos(unrealized_pnl=-320.0)]
    account = _make_account()
    yesterday_unrealized = -235.0
    summary = _build_eod_summary(positions, account, 0.0, 0, yesterday_unrealized, [])
    assert summary.unrealized_pnl == pytest.approx(-320.0)
    assert summary.unrealized_pnl_delta == pytest.approx(-320.0 - (-235.0))


def test_build_eod_summary_net_delta() -> None:
    from src.orchestrator.eod_report import _build_eod_summary

    # Short call: position=-1, delta=0.28 → contribution = 0.28 * (-1) * 100 = -28
    # Short put: position=-1, delta=-0.20 → contribution = (-0.20) * (-1) * 100 = +20
    # Net = -28 + 20 = -8
    positions = [
        _make_option_pos(position=-1.0, delta=0.28),
        PositionSnapshot(
            symbol="SPY   260117P00500000",
            sec_type="OPT",
            position=-1.0,
            avg_cost=200.0,
            right=OptionRight.PUT,
            strike=500.0,
            expiry=date.today() + timedelta(days=30),
            underlying="SPY",
            unrealized_pnl=-10.0,
            delta=-0.20,
        ),
    ]
    account = _make_account()
    summary = _build_eod_summary(positions, account, 0.0, 0, 0.0, [])
    assert summary.net_delta_exposure == pytest.approx(-8.0)


def test_build_eod_summary_stock_included_in_delta() -> None:
    from src.orchestrator.eod_report import _build_eod_summary

    # Stock position (100 shares, delta=1.0 per share) + short option (delta=0.30).
    # Net delta = stock + option = 100 + (0.30 * -1 * 100) = 100 - 30 = 70
    positions = [_make_stock_pos(), _make_option_pos(position=-1.0, delta=0.30)]
    account = _make_account()
    summary = _build_eod_summary(positions, account, 0.0, 0, 0.0, [])
    assert summary.net_delta_exposure == pytest.approx(70.0)


def test_build_eod_summary_top_movers_deduped() -> None:
    from src.orchestrator.eod_report import _build_eod_summary

    # Two AAPL options — should deduplicate to one entry
    positions = [
        _make_option_pos(symbol="AAPL  260117C00185000", underlying="AAPL", unrealized_pnl=-100.0),
        _make_option_pos(symbol="AAPL  260117P00180000", underlying="AAPL", unrealized_pnl=-80.0),
        _make_option_pos(
            symbol="SPY   260117C00500000", underlying="SPY", unrealized_pnl=-50.0, delta=0.25
        ),
    ]
    account = _make_account()
    summary = _build_eod_summary(positions, account, 0.0, 0, 0.0, [])
    assert summary.top_movers.count("AAPL") == 1


def test_build_eod_summary_watchlist_passed_through() -> None:
    from src.orchestrator.eod_report import _build_eod_summary

    wl = ["NVDA", "AAPL", "SPY"]
    summary = _build_eod_summary([_make_option_pos()], _make_account(), 0.0, 0, 0.0, wl)
    assert summary.tomorrow_watchlist == wl


def test_build_eod_summary_dates_on_et_day() -> None:
    # The journal must be keyed on the ET trading day so write/read line up across UTC offsets.
    from src.orchestrator.eod_report import _build_eod_summary

    summary = _build_eod_summary([_make_option_pos()], _make_account(), 0.0, 0, 0.0, [])
    assert summary.date == datetime.now(ZoneInfo("America/New_York")).date()


def test_build_eod_summary_stock_can_be_a_driver() -> None:
    # A stock leg with the largest swing must appear as a driver (options-only would miss it).
    from src.orchestrator.eod_report import _build_eod_summary

    positions = [
        _make_stock_pos(symbol="NVDA", position=300.0),  # unrealized_pnl=200.0 default
        _make_option_pos(underlying="AAPL", unrealized_pnl=-5.0),
    ]
    summary = _build_eod_summary(positions, _make_account(), 0.0, 0, 0.0, [])
    assert "NVDA" in summary.top_movers
    assert summary.mover_pnl["NVDA"] == pytest.approx(200.0)


def test_build_eod_summary_mover_pnl_aggregates_legs() -> None:
    from src.orchestrator.eod_report import _build_eod_summary

    positions = [
        _make_option_pos(symbol="AAPL  C", underlying="AAPL", unrealized_pnl=-100.0),
        _make_option_pos(symbol="AAPL  P", underlying="AAPL", unrealized_pnl=-80.0),
    ]
    summary = _build_eod_summary(positions, _make_account(), 0.0, 0, 0.0, [])
    assert summary.mover_pnl["AAPL"] == pytest.approx(-180.0)


def test_build_eod_summary_watchlist_changed_flag_passed() -> None:
    from src.orchestrator.eod_report import _build_eod_summary

    summary = _build_eod_summary(
        [_make_option_pos()], _make_account(), 0.0, 0, 0.0, ["AAPL"], False
    )
    assert summary.watchlist_changed is False


# ---------------------------------------------------------------------------
# _compute_realized_pnl (DB test)
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated in-process SQLite DB wired into src.storage.db."""
    import src.storage.db as _db_mod
    from src.storage.models import Base

    db_url = f"sqlite:///{tmp_path / 'eod_test.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(_db_mod, "_engine", engine)
    monkeypatch.setattr(_db_mod, "_SessionLocal", Session)
    return Session


def test_compute_realized_pnl_sums_fills(isolated_db) -> None:
    from src.orchestrator.eod_report import _compute_realized_pnl
    from src.storage.models import FillRow

    # The EOD day window is anchored to the ET trading day; fills are timestamped "now"
    # (UTC), which always falls inside ET-today's window regardless of local wall clock.
    today = datetime.now(ZoneInfo("America/New_York")).date()
    Session = isolated_db
    with Session() as session:
        # Two fills today: 2 contracts @ $1.50 and 1 contract @ $0.80
        session.add(
            FillRow(
                order_id=1,
                candidate_id="c1",
                filled_qty=2.0,
                avg_price=1.50,
                filled_at=datetime.now(UTC),
            )
        )
        session.add(
            FillRow(
                order_id=2,
                candidate_id="c2",
                filled_qty=1.0,
                avg_price=0.80,
                filled_at=datetime.now(UTC),
            )
        )
        session.commit()

    realized, count, fill_ids = _compute_realized_pnl(today)
    # 2 * 1.50 * 100 + 1 * 0.80 * 100 = 300 + 80 = 380
    assert realized == pytest.approx(380.0)
    assert count == 2
    assert len(fill_ids) == 2


def test_compute_realized_pnl_signs_buy_as_debit(isolated_db) -> None:
    """A buy-to-close fill is a debit (−), not added as if it were premium collected."""
    from src.orchestrator.eod_report import _compute_realized_pnl
    from src.storage.models import FillRow

    today = datetime.now(ZoneInfo("America/New_York")).date()
    Session = isolated_db
    with Session() as session:
        # SELL 2 @ $1.50 (credit) and BUY 1 @ $0.80 (debit, e.g. a roll's close leg).
        session.add(
            FillRow(
                order_id=1,
                candidate_id="c1",
                action="SELL",
                filled_qty=2.0,
                avg_price=1.50,
                filled_at=datetime.now(UTC),
            )
        )
        session.add(
            FillRow(
                order_id=2,
                candidate_id="c2",
                action="BUY",
                filled_qty=1.0,
                avg_price=0.80,
                filled_at=datetime.now(UTC),
            )
        )
        session.commit()

    realized, count, _ = _compute_realized_pnl(today)
    # 2 * 1.50 * 100  −  1 * 0.80 * 100 = 300 − 80 = 220
    assert realized == pytest.approx(220.0)
    assert count == 2


def test_compute_realized_pnl_excludes_yesterday(isolated_db) -> None:
    from src.orchestrator.eod_report import _compute_realized_pnl
    from src.storage.models import FillRow

    yesterday = datetime.now(UTC) - timedelta(days=1)
    Session = isolated_db
    with Session() as session:
        session.add(
            FillRow(
                order_id=10,
                candidate_id="old",
                filled_qty=1.0,
                avg_price=2.0,
                filled_at=yesterday,
            )
        )
        session.commit()

    realized, count, _ = _compute_realized_pnl(datetime.now(ZoneInfo("America/New_York")).date())
    assert realized == pytest.approx(0.0)
    assert count == 0


def test_compute_realized_pnl_empty(isolated_db) -> None:
    from src.orchestrator.eod_report import _compute_realized_pnl

    realized, count, fill_ids = _compute_realized_pnl(date.today())
    assert realized == pytest.approx(0.0)
    assert count == 0
    assert fill_ids == []


# ---------------------------------------------------------------------------
# _load_yesterday_unrealized (DB test)
# ---------------------------------------------------------------------------


def test_load_yesterday_unrealized_from_journal(isolated_db) -> None:
    from src.orchestrator.eod_report import _load_yesterday_unrealized
    from src.storage.models import JournalRow

    yesterday = date.today() - timedelta(days=1)
    Session = isolated_db
    with Session() as session:
        session.add(
            JournalRow(
                entry_date=yesterday,
                unrealized_pnl=-235.0,
                payload={},
            )
        )
        session.commit()

    result = _load_yesterday_unrealized(date.today())
    assert result == pytest.approx(-235.0)


def test_load_yesterday_unrealized_no_row(isolated_db) -> None:
    from src.orchestrator.eod_report import _load_yesterday_unrealized

    assert _load_yesterday_unrealized(date.today()) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _write_journal (DB test)
# ---------------------------------------------------------------------------


def test_write_journal_creates_row(isolated_db) -> None:
    from src.orchestrator.eod_report import _write_journal
    from src.storage.models import JournalRow

    summary = _make_eod_summary()
    _write_journal(summary, "Great day overall.", [1, 2, 3])

    Session = isolated_db
    with Session() as session:
        row = session.query(JournalRow).filter_by(entry_date=summary.date).first()
    assert row is not None
    assert row.narrative == "Great day overall."
    assert row.realized_pnl == pytest.approx(142.50)
    assert row.payload["fills"] == [1, 2, 3]


def test_write_journal_narrative_none(isolated_db) -> None:
    from src.orchestrator.eod_report import _write_journal
    from src.storage.models import JournalRow

    summary = _make_eod_summary()
    _write_journal(summary, None, [])

    Session = isolated_db
    with Session() as session:
        row = session.query(JournalRow).filter_by(entry_date=summary.date).first()
    assert row is not None
    assert row.narrative is None


# ---------------------------------------------------------------------------
# Claude EOD prompt
# ---------------------------------------------------------------------------


def test_build_eod_prompt_contains_key_fields() -> None:
    from src.claude.prompts.eod import build_eod_prompt

    summary = _make_eod_summary()
    prompt = build_eod_prompt(summary)
    assert str(summary.date) in prompt
    assert "142.50" in prompt
    assert "-320.00" in prompt or "320.00" in prompt
    assert "narrative" in prompt
    assert "JSON" in prompt


def test_build_eod_prompt_includes_watchlist() -> None:
    from src.claude.prompts.eod import build_eod_prompt

    summary = _make_eod_summary(tomorrow_watchlist=["AAPL", "SPY"])
    prompt = build_eod_prompt(summary)
    assert "AAPL" in prompt
    assert "SPY" in prompt


def test_build_eod_prompt_includes_top_movers() -> None:
    from src.claude.prompts.eod import build_eod_prompt

    summary = _make_eod_summary(top_movers=["NVDA", "MSFT"])
    prompt = build_eod_prompt(summary)
    assert "NVDA" in prompt


# ---------------------------------------------------------------------------
# parse_journal_output
# ---------------------------------------------------------------------------


def test_parse_journal_valid() -> None:
    from src.claude.parser import parse_journal_output

    inner = {"narrative": "Today was a solid income day with two fills."}
    envelope = {"type": "result", "result": json.dumps(inner)}
    result = parse_journal_output(json.dumps(envelope))
    assert result == "Today was a solid income day with two fills."


def test_parse_journal_strips_whitespace() -> None:
    from src.claude.parser import parse_journal_output

    inner = {"narrative": "  Some narrative.  "}
    envelope = {"type": "result", "result": json.dumps(inner)}
    assert parse_journal_output(json.dumps(envelope)) == "Some narrative."


def test_parse_journal_empty_string_returns_none() -> None:
    from src.claude.parser import parse_journal_output

    assert parse_journal_output("") is None


def test_parse_journal_missing_narrative_returns_none() -> None:
    from src.claude.parser import parse_journal_output

    inner = {"other_key": "stuff"}
    envelope = {"type": "result", "result": json.dumps(inner)}
    assert parse_journal_output(json.dumps(envelope)) is None


def test_parse_journal_bad_json_returns_none() -> None:
    from src.claude.parser import parse_journal_output

    assert parse_journal_output("not valid json at all") is None


def test_parse_journal_with_markdown_fence() -> None:
    from src.claude.parser import parse_journal_output

    inner = {"narrative": "Two fills today, premium collected."}
    fenced = "```json\n" + json.dumps(inner) + "\n```"
    envelope = {"type": "result", "result": fenced}
    result = parse_journal_output(json.dumps(envelope))
    assert result == "Two fills today, premium collected."


# ---------------------------------------------------------------------------
# format_eod_summary
# ---------------------------------------------------------------------------


def test_format_eod_summary_contains_date() -> None:
    from src.notify.formatters import format_eod_summary

    summary = _make_eod_summary()
    text = format_eod_summary(summary, "Solid day.")
    # MarkdownV2 escapes hyphens, so "2026-05-30" → "2026\-05\-30"
    assert "2026" in text
    assert "EOD Report" in text


def test_format_eod_summary_contains_realized_pnl() -> None:
    from src.notify.formatters import format_eod_summary

    summary = _make_eod_summary(realized_pnl=142.50)
    text = format_eod_summary(summary, None)
    assert "142" in text


def test_format_eod_summary_labels_figure_as_premium_cashflow() -> None:
    # N13: the figure is option premium cashflow, not a paired realized P&L.
    from src.notify.formatters import format_eod_summary

    text = format_eod_summary(_make_eod_summary(realized_pnl=142.50), None)
    assert "Premium cashflow" in text
    assert "excludes assignment" in text.lower()


def test_format_eod_summary_contains_narrative() -> None:
    from src.notify.formatters import format_eod_summary

    summary = _make_eod_summary()
    text = format_eod_summary(summary, "Two trades filled cleanly.")
    assert "Two trades filled cleanly" in text


def test_format_eod_summary_no_narrative() -> None:
    from src.notify.formatters import format_eod_summary

    summary = _make_eod_summary()
    text = format_eod_summary(summary, None)
    assert "Journal" not in text


def test_format_eod_summary_contains_watchlist() -> None:
    from src.notify.formatters import format_eod_summary

    summary = _make_eod_summary(tomorrow_watchlist=["AAPL", "SPY", "NVDA"])
    text = format_eod_summary(summary, None)
    assert "NVDA" in text


def test_format_eod_summary_truncated_gracefully() -> None:
    from src.notify.formatters import format_eod_summary

    long_narrative = "A" * 5000
    summary = _make_eod_summary()
    text = format_eod_summary(summary, long_narrative)
    # Body is truncated to _MAX_MESSAGE_LEN; source footer appended after, so allow overage.
    assert "\\.\\.\\." in text
    assert "Sources:" in text


def test_format_eod_summary_negative_realized_uses_minus() -> None:
    from src.notify.formatters import format_eod_summary

    summary = _make_eod_summary(realized_pnl=-50.0)
    text = format_eod_summary(summary, None)
    assert "50" in text


def test_format_eod_summary_disclaimer_suppressed_on_flat_day() -> None:
    # No cashflow and no fills → the premium-cashflow disclaimer is noise; suppress it.
    from src.notify.formatters import format_eod_summary

    summary = _make_eod_summary(realized_pnl=0.0, fills_today=0)
    text = format_eod_summary(summary, None)
    assert "excludes assignment" not in text.lower()


def test_format_eod_summary_disclaimer_shown_when_cashflow() -> None:
    from src.notify.formatters import format_eod_summary

    summary = _make_eod_summary(realized_pnl=142.50, fills_today=0)
    text = format_eod_summary(summary, None)
    assert "excludes assignment" in text.lower()


def test_format_eod_summary_shows_nlv_and_buying_power() -> None:
    from src.notify.formatters import format_eod_summary

    summary = _make_eod_summary(account=_make_account(nlv=1_000_000.0))
    text = format_eod_summary(summary, None)
    assert "NLV" in text and "BP" in text
    assert "1,000,000" in text


def test_format_eod_summary_drivers_carry_pnl() -> None:
    from src.notify.formatters import format_eod_summary

    summary = _make_eod_summary(top_movers=["NVDA"], mover_pnl={"NVDA": -7672.0})
    text = format_eod_summary(summary, None)
    assert "Drivers:" in text
    assert "NVDA" in text
    assert "7,672" in text  # P&L appears alongside the symbol


def test_format_eod_summary_collapses_unchanged_watchlist() -> None:
    from src.notify.formatters import format_eod_summary

    wl = [f"SYM{i}" for i in range(37)]
    summary = _make_eod_summary(tomorrow_watchlist=wl, watchlist_changed=False)
    text = format_eod_summary(summary, None)
    assert "37 names" in text
    assert "unchanged" in text
    assert "SYM0" not in text  # full list is NOT reprinted


def test_format_eod_summary_full_watchlist_when_changed() -> None:
    from src.notify.formatters import format_eod_summary

    summary = _make_eod_summary(tomorrow_watchlist=["AAPL", "NVDA"], watchlist_changed=True)
    text = format_eod_summary(summary, None)
    assert "AAPL" in text and "NVDA" in text


# ---------------------------------------------------------------------------
# Telegram send (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_eod_telegram_sends_message() -> None:
    from src.orchestrator.eod_report import _send_eod_telegram

    summary = _make_eod_summary()
    mock_bot = AsyncMock()

    cfg = MagicMock()
    cfg.secrets.telegram_bot_token = "test-token"
    cfg.secrets.telegram_chat_id = "123456"

    with (
        patch("src.orchestrator.eod_report.get_config", return_value=cfg),
        patch("src.orchestrator.eod_report.Bot") as MockBot,
    ):
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_bot)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        MockBot.return_value = mock_ctx

        await _send_eod_telegram(summary, "Good day.")

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == "123456"
    assert call_kwargs["parse_mode"] == "MarkdownV2"
    assert "EOD Report" in call_kwargs["text"] or str(summary.date) in call_kwargs["text"]


@pytest.mark.asyncio
async def test_send_eod_telegram_skips_when_no_credentials() -> None:
    from src.orchestrator.eod_report import _send_eod_telegram

    summary = _make_eod_summary()
    cfg = MagicMock()
    cfg.secrets.telegram_bot_token = ""
    cfg.secrets.telegram_chat_id = ""

    with patch("src.orchestrator.eod_report.get_config", return_value=cfg):
        await _send_eod_telegram(summary, None)  # should not raise


# ---------------------------------------------------------------------------
# _append_daily_iv — fail-fast when the historical-data farm is unavailable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_daily_iv_circuit_breaker_trips_on_dead_farm() -> None:
    """A down HMDS farm fails every symbol; the loop must bail after the breaker threshold
    instead of grinding through all symbols (the ~1-hour EOD hang we are fixing)."""
    from src.orchestrator import eod_report

    symbols = [f"SYM{i}" for i in range(30)]
    ib = MagicMock()
    ib.reqHistoricalDataAsync = AsyncMock(side_effect=RuntimeError("hmds down"))

    with (
        patch("src.ibkr.contracts.qualify_stock_async", new=AsyncMock(return_value=MagicMock())),
        patch("src.storage.iv_history.append_observation", return_value=False),
        patch("src.orchestrator.eod_report.asyncio.sleep", new=AsyncMock()),
    ):
        await eod_report._append_daily_iv(ib, symbols)

    # Stops at the breaker threshold, not after all 30 symbols.
    assert ib.reqHistoricalDataAsync.call_count == eod_report._IV_MAX_CONSECUTIVE_FAILURES


@pytest.mark.asyncio
async def test_append_daily_iv_caps_slow_request_with_timeout() -> None:
    """Each request is bounded by _IV_REQUEST_TIMEOUT_S so a hanging farm can't block for 60s."""
    from src.orchestrator import eod_report

    async def _never_returns(*args, **kwargs):
        await asyncio.sleep(60)

    ib = MagicMock()
    ib.reqHistoricalDataAsync = AsyncMock(side_effect=_never_returns)

    # NB: do not patch asyncio.sleep here — eod_report.asyncio is the global module, so patching
    # it would also neutralise the sleep inside _never_returns and defeat the timeout being tested.
    with (
        patch("src.ibkr.contracts.qualify_stock_async", new=AsyncMock(return_value=MagicMock())),
        patch("src.storage.iv_history.append_observation", return_value=False),
        patch.object(eod_report, "_IV_REQUEST_TIMEOUT_S", 0.05),
    ):
        # Would take 60s+ per symbol without the wait_for cap; the breaker then bails fast.
        await asyncio.wait_for(
            eod_report._append_daily_iv(ib, [f"SYM{i}" for i in range(30)]),
            timeout=10.0,
        )

    assert ib.reqHistoricalDataAsync.call_count == eod_report._IV_MAX_CONSECUTIVE_FAILURES
