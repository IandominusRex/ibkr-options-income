"""Tests for Phase 8: Intraday monitor + roll triggers.

All IB and Telegram calls are mocked. DB tests use tmp_path + SQLite.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.market_hours import today_et
from src.common.schemas import (
    FundamentalStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RollAlert,
    RollReview,
)
from src.monitor.triggers import (
    check_all,
    check_assignment_risk,
    check_delta_drift,
    check_dte_threshold,
    check_ex_div,
    check_iv_spike,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXPIRY_FAR = date.today() + timedelta(days=30)
_EXPIRY_NEAR = date.today() + timedelta(days=5)


def _make_short_call(
    symbol: str = "AAPL  260117C00185000",
    underlying: str = "AAPL",
    strike: float = 185.0,
    expiry: date = _EXPIRY_FAR,
    position: float = -1.0,
    delta: float | None = 0.25,
) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        sec_type="OPT",
        position=position,
        avg_cost=200.0,
        right=OptionRight.CALL,
        strike=strike,
        expiry=expiry,
        underlying=underlying,
        delta=delta,
    )


def _make_quote(
    delta: float | None = 0.25,
    iv: float | None = 0.35,
    bid: float = 1.50,
    ask: float = 1.60,
    expiry: date = _EXPIRY_FAR,
) -> OptionQuote:
    return OptionQuote(
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=185.0,
        expiry=expiry,
        bid=bid,
        ask=ask,
        delta=delta,
        iv=iv,
    )


def _make_fund_stats(ex_div_date: date | None = None) -> FundamentalStats:
    return FundamentalStats(symbol="AAPL", ex_dividend_date=ex_div_date)


# ---------------------------------------------------------------------------
# check_delta_drift
# ---------------------------------------------------------------------------


def test_delta_drift_fires_when_above_ceiling() -> None:
    pos = _make_short_call()
    quote = _make_quote(delta=0.48)
    alert = check_delta_drift(pos, quote, delta_ceiling=0.45)
    assert alert is not None
    assert alert.trigger == "delta_drift"
    assert "0.48" in alert.detail


def test_delta_drift_no_fire_within_ceiling() -> None:
    pos = _make_short_call()
    quote = _make_quote(delta=0.40)
    assert check_delta_drift(pos, quote, delta_ceiling=0.45) is None


def test_delta_drift_skips_long_positions() -> None:
    pos = _make_short_call(position=1.0)  # long
    quote = _make_quote(delta=0.90)
    assert check_delta_drift(pos, quote, delta_ceiling=0.45) is None


def test_delta_drift_skips_missing_delta() -> None:
    pos = _make_short_call()
    quote = _make_quote(delta=None)
    assert check_delta_drift(pos, quote, delta_ceiling=0.45) is None


def test_delta_drift_uses_abs_delta() -> None:
    """A short put with delta=-0.48 should also trigger."""
    pos = PositionSnapshot(
        symbol="AAPL  260117P00180000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=150.0,
        right=OptionRight.PUT,
        strike=180.0,
        expiry=_EXPIRY_FAR,
        underlying="AAPL",
    )
    quote = OptionQuote(
        underlying="AAPL",
        right=OptionRight.PUT,
        strike=180.0,
        expiry=_EXPIRY_FAR,
        delta=-0.48,
    )
    alert = check_delta_drift(pos, quote, delta_ceiling=0.45)
    assert alert is not None
    assert alert.trigger == "delta_drift"


# ---------------------------------------------------------------------------
# check_dte_threshold
# ---------------------------------------------------------------------------


def test_dte_fires_at_threshold() -> None:
    # check_dte_threshold computes DTE against today_et() (exchange time), not the local
    # wall-clock date — anchor the fixture there so this holds regardless of local timezone.
    pos = _make_short_call(expiry=today_et() + timedelta(days=7))
    alert = check_dte_threshold(pos, dte_threshold=7)
    assert alert is not None
    assert alert.trigger == "dte"


def test_dte_fires_below_threshold() -> None:
    pos = _make_short_call(expiry=date.today() + timedelta(days=3))
    assert check_dte_threshold(pos, dte_threshold=7) is not None


def test_dte_no_fire_above_threshold() -> None:
    pos = _make_short_call(expiry=date.today() + timedelta(days=15))
    assert check_dte_threshold(pos, dte_threshold=7) is None


def test_dte_skips_long_positions() -> None:
    pos = _make_short_call(expiry=date.today() + timedelta(days=3), position=1.0)
    assert check_dte_threshold(pos, dte_threshold=7) is None


def test_dte_skips_missing_expiry() -> None:
    pos = PositionSnapshot(
        symbol="X",
        sec_type="OPT",
        position=-1.0,
        avg_cost=100.0,
        underlying="X",
    )
    assert check_dte_threshold(pos, dte_threshold=7) is None


# ---------------------------------------------------------------------------
# check_manage_at_dte
# ---------------------------------------------------------------------------


def test_manage_at_dte_fires_inside_the_window() -> None:
    from datetime import timedelta

    from src.common.market_hours import today_et
    from src.monitor.triggers import check_manage_at_dte

    pos = _make_short_call(expiry=today_et() + timedelta(days=20))
    alert = check_manage_at_dte(pos, 21)
    assert alert is not None
    assert alert.trigger == "manage_dte"


def test_manage_at_dte_silent_outside_the_window() -> None:
    from datetime import timedelta

    from src.common.market_hours import today_et
    from src.monitor.triggers import check_manage_at_dte

    pos = _make_short_call(expiry=today_et() + timedelta(days=30))
    assert check_manage_at_dte(pos, 21) is None


def test_check_all_uses_the_configured_manage_at_dte() -> None:
    """`manage_at_dte` must be load-bearing, not defaulted.

    A 25-DTE short is OUTSIDE the hardcoded 21-day fallback, so this only fires if the
    configured 30 actually reaches `check_manage_at_dte` through `check_all`'s limits dict.
    """
    from datetime import timedelta

    from src.common.market_hours import today_et
    from src.monitor.triggers import check_all

    pos = _make_short_call(expiry=today_et() + timedelta(days=25))
    quote = _make_quote(delta=0.20)

    fired = check_all(pos, quote, entry_iv=None, fund_stats=None, limits={"manage_at_dte": 30})
    assert any(a.trigger == "manage_dte" for a in fired)

    silent = check_all(pos, quote, entry_iv=None, fund_stats=None, limits={})
    assert not any(a.trigger == "manage_dte" for a in silent)


async def test_intraday_monitor_passes_manage_at_dte_from_config() -> None:
    """The regression this closes: `monitor.manage_at_dte` was in config and in the trigger,
    but `intraday.py`'s limits dict never carried it — so editing the key did nothing and
    every alert used the hardcoded 21-day fallback."""
    from src.common.schemas import OptionRight, PositionSnapshot

    monitor, _mock_ib = _make_monitor()
    monitor._cfg.monitor.manage_at_dte = 30
    monitor._cfg.monitor.assignment_alert_delta = 0.70
    monitor._cfg.monitor.assignment_alert_dte = 21

    pos = PositionSnapshot(
        symbol="AAPL  260117C00185000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=1.50,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=today_et() + timedelta(days=25),  # outside the 21-day fallback, inside 30
        underlying="AAPL",
    )
    monitor._subscriptions[pos.symbol] = (pos, MagicMock())

    ticker = MagicMock()
    ticker.contract.localSymbol = pos.symbol
    ticker.bid, ticker.ask, ticker.last, ticker.volume = 1.0, 1.2, 1.1, 10
    ticker.modelGreeks = None

    captured: dict = {}

    def _capture(pos_, quote_, entry_iv, fund_stats, limits):
        captured.update(limits)
        from src.monitor.triggers import check_all as real_check_all

        return real_check_all(pos_, quote_, entry_iv, fund_stats, limits)

    with (
        patch("src.monitor.intraday.check_all", side_effect=_capture),
        patch("src.monitor.intraday.fire_alerts", new=AsyncMock()) as fire,
    ):
        await monitor._on_pending_tickers([ticker])

    assert captured["manage_at_dte"] == 30
    fired = fire.await_args.args[0]
    assert any(a.trigger == "manage_dte" for a in fired)


def test_manage_at_dte_ignores_long_positions() -> None:
    from datetime import timedelta

    from src.common.market_hours import today_et
    from src.monitor.triggers import check_manage_at_dte

    pos = _make_short_call(expiry=today_et() + timedelta(days=10), position=1.0)
    assert check_manage_at_dte(pos, 21) is None


# ---------------------------------------------------------------------------
# check_iv_spike
# ---------------------------------------------------------------------------


def test_iv_spike_fires_when_above_threshold() -> None:
    pos = _make_short_call()
    quote = _make_quote(iv=0.55)  # current IV
    alert = check_iv_spike(pos, quote, entry_iv=0.35, spike_pct=40.0)
    assert alert is not None
    assert alert.trigger == "iv_spike"
    # (0.55-0.35)/0.35 * 100 ≈ 57.1% > 40%


def test_iv_spike_no_fire_within_threshold() -> None:
    pos = _make_short_call()
    quote = _make_quote(iv=0.40)
    # (0.40-0.35)/0.35 * 100 ≈ 14.3% < 40%
    assert check_iv_spike(pos, quote, entry_iv=0.35, spike_pct=40.0) is None


def test_iv_spike_skips_missing_iv() -> None:
    pos = _make_short_call()
    quote = _make_quote(iv=None)
    assert check_iv_spike(pos, quote, entry_iv=0.35, spike_pct=40.0) is None


def test_iv_spike_skips_long_positions() -> None:
    pos = _make_short_call(position=1.0)
    quote = _make_quote(iv=0.80)
    assert check_iv_spike(pos, quote, entry_iv=0.35, spike_pct=40.0) is None


# ---------------------------------------------------------------------------
# check_ex_div
# ---------------------------------------------------------------------------


def test_ex_div_fires_for_short_call_within_window() -> None:
    pos = _make_short_call()
    fund = _make_fund_stats(ex_div_date=date.today() + timedelta(days=3))
    alert = check_ex_div(pos, fund, days_ahead=5)
    assert alert is not None
    assert alert.trigger == "ex_div"


def test_ex_div_no_fire_outside_window() -> None:
    pos = _make_short_call()
    fund = _make_fund_stats(ex_div_date=date.today() + timedelta(days=10))
    assert check_ex_div(pos, fund, days_ahead=5) is None


def test_ex_div_no_fire_for_puts() -> None:
    pos = PositionSnapshot(
        symbol="AAPL  260117P00180000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=150.0,
        right=OptionRight.PUT,
        strike=180.0,
        expiry=_EXPIRY_FAR,
        underlying="AAPL",
    )
    fund = _make_fund_stats(ex_div_date=date.today() + timedelta(days=2))
    assert check_ex_div(pos, fund, days_ahead=5) is None


def test_ex_div_skips_no_ex_date() -> None:
    pos = _make_short_call()
    fund = _make_fund_stats(ex_div_date=None)
    assert check_ex_div(pos, fund, days_ahead=5) is None


def test_ex_div_no_fire_for_long_positions() -> None:
    pos = _make_short_call(position=1.0)
    fund = _make_fund_stats(ex_div_date=date.today() + timedelta(days=2))
    assert check_ex_div(pos, fund, days_ahead=5) is None


def test_ex_div_suppressed_for_otm_call() -> None:
    # With a live quote showing an OTM call (low delta), early-assignment risk is negligible
    # → suppress the ex-div alert (it was pure noise before).
    pos = _make_short_call()
    fund = _make_fund_stats(ex_div_date=date.today() + timedelta(days=3))
    otm = _make_quote(delta=0.20)
    assert check_ex_div(pos, fund, days_ahead=5, quote=otm) is None


def test_ex_div_fires_for_itm_call() -> None:
    # An ITM-ish call (high delta) near ex-div carries real assignment risk → fire.
    pos = _make_short_call()
    fund = _make_fund_stats(ex_div_date=date.today() + timedelta(days=3))
    itm = _make_quote(delta=0.70)
    alert = check_ex_div(pos, fund, days_ahead=5, quote=itm)
    assert alert is not None
    assert alert.trigger == "ex_div"


def test_ex_div_fires_without_quote_backward_compatible() -> None:
    # No live quote → keep the conservative original behaviour (fire on the date alone).
    pos = _make_short_call()
    fund = _make_fund_stats(ex_div_date=date.today() + timedelta(days=3))
    assert check_ex_div(pos, fund, days_ahead=5) is not None


# ---------------------------------------------------------------------------
# check_assignment_risk (C4)
# ---------------------------------------------------------------------------

# check_assignment_risk computes DTE against today_et(), so anchor there rather than the
# local wall-clock date (which can be a day ahead of ET, e.g. mornings in Asia/Singapore).
_EXPIRY_21D = today_et() + timedelta(days=21)


def test_assignment_risk_fires_deep_itm_near_expiry() -> None:
    pos = _make_short_call(expiry=_EXPIRY_21D)
    quote = _make_quote(delta=0.72, expiry=_EXPIRY_21D)
    alert = check_assignment_risk(pos, quote, delta_threshold=0.70, dte_threshold=21)
    assert alert is not None
    assert alert.trigger == "assignment_risk"
    # The detail is prose, not debug output — it used to read "|Δ|=0.72 ≥ 0.70 with DTE=21".
    # The roll / close / let-assign options live in the card (format_assignment_alert), which
    # is where they belong; repeating them inside every trigger detail duplicated the card.
    assert "0.72" in alert.detail
    assert "21 days left" in alert.detail
    assert "=" not in alert.detail


def test_assignment_risk_no_fire_delta_below_threshold() -> None:
    pos = _make_short_call(expiry=_EXPIRY_21D)
    quote = _make_quote(delta=0.65, expiry=_EXPIRY_21D)
    assert check_assignment_risk(pos, quote, delta_threshold=0.70, dte_threshold=21) is None


def test_assignment_risk_no_fire_dte_above_threshold() -> None:
    pos = _make_short_call(expiry=date.today() + timedelta(days=22))
    quote = _make_quote(delta=0.80, expiry=date.today() + timedelta(days=22))
    assert check_assignment_risk(pos, quote, delta_threshold=0.70, dte_threshold=21) is None


def test_assignment_risk_skips_long_positions() -> None:
    pos = _make_short_call(position=1.0)  # long
    quote = _make_quote(delta=0.90, expiry=_EXPIRY_21D)
    assert check_assignment_risk(pos, quote, delta_threshold=0.70, dte_threshold=21) is None


def test_assignment_risk_skips_missing_delta() -> None:
    pos = _make_short_call(expiry=_EXPIRY_21D)
    quote = _make_quote(delta=None, expiry=_EXPIRY_21D)
    assert check_assignment_risk(pos, quote, delta_threshold=0.70, dte_threshold=21) is None


def test_assignment_risk_fires_exactly_at_thresholds() -> None:
    # Anchored to today_et() — the code under test computes DTE against exchange time.
    pos = _make_short_call(expiry=today_et() + timedelta(days=21))
    quote = _make_quote(delta=0.70, expiry=today_et() + timedelta(days=21))
    alert = check_assignment_risk(pos, quote, delta_threshold=0.70, dte_threshold=21)
    assert alert is not None


def test_check_all_includes_assignment_risk() -> None:
    pos = _make_short_call(expiry=date.today() + timedelta(days=10))
    quote = _make_quote(delta=0.75, expiry=date.today() + timedelta(days=10))
    limits = {
        "delta_ceiling": 0.45,
        "dte_threshold": 7,
        "iv_spike_pct": 40,
        "ex_div_days_ahead": 5,
        "assignment_alert_delta": 0.70,
        "assignment_alert_dte": 21,
    }
    alerts = check_all(pos, quote, entry_iv=None, fund_stats=None, limits=limits)
    assert any(a.trigger == "assignment_risk" for a in alerts)


# ---------------------------------------------------------------------------
# check_all
# ---------------------------------------------------------------------------


def test_check_all_combines_multiple_triggers() -> None:
    # Both delta drift and DTE should fire simultaneously
    pos = _make_short_call(expiry=date.today() + timedelta(days=5))
    quote = _make_quote(delta=0.50)
    limits = {"delta_ceiling": 0.45, "dte_threshold": 7, "iv_spike_pct": 40, "ex_div_days_ahead": 5}
    alerts = check_all(pos, quote, entry_iv=None, fund_stats=None, limits=limits)
    triggers = {a.trigger for a in alerts}
    assert "delta_drift" in triggers
    assert "dte" in triggers


def test_check_all_skips_iv_when_entry_iv_none() -> None:
    pos = _make_short_call()
    quote = _make_quote(delta=0.20, iv=0.99)  # IV very high, but no entry_iv → skipped
    limits = {"delta_ceiling": 0.45, "dte_threshold": 7, "iv_spike_pct": 40, "ex_div_days_ahead": 5}
    alerts = check_all(pos, quote, entry_iv=None, fund_stats=None, limits=limits)
    assert all(a.trigger != "iv_spike" for a in alerts)


def test_check_all_empty_when_no_triggers() -> None:
    pos = _make_short_call(expiry=date.today() + timedelta(days=30))
    quote = _make_quote(delta=0.25, iv=0.35)
    limits = {"delta_ceiling": 0.45, "dte_threshold": 7, "iv_spike_pct": 40, "ex_div_days_ahead": 5}
    assert check_all(pos, quote, entry_iv=0.30, fund_stats=None, limits=limits) == []


# ---------------------------------------------------------------------------
# DB persistence and de-duplication
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setattr("src.storage.db._engine", None)
    with patch("src.common.config.get_config") as mock_cfg:
        cfg = MagicMock()
        cfg.db_url_abs.return_value = db_url
        mock_cfg.return_value = cfg
        from src.storage.db import init_db

        init_db()
    return db_url


def test_persist_and_dedup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RollAlertRow written; second call within cooldown is suppressed."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import src.storage.db as _db_mod
    from src.monitor.intraday import _is_recent_alert, _persist_alert
    from src.storage.models import Base

    # Build an isolated SQLite engine so this test never touches the real DB.
    db_url = f"sqlite:///{tmp_path / 'monitor_dedup.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    monkeypatch.setattr(_db_mod, "_engine", engine)
    monkeypatch.setattr(_db_mod, "_SessionLocal", Session)

    alert = RollAlert(
        position_symbol="AAPL  260117C00185000",
        underlying="AAPL",
        trigger="delta_drift",
        detail="delta=0.48 > ceiling=0.45",
        current_delta=0.48,
        dte=30,
    )
    assert not _is_recent_alert(alert, cooldown_minutes=30)
    _persist_alert(alert, review=None)
    assert _is_recent_alert(alert, cooldown_minutes=30)


# ---------------------------------------------------------------------------
# fire_alerts — Telegram + DB integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fire_alerts_sends_telegram(tmp_path: Path) -> None:
    """A fresh alert sends a Telegram message and persists to DB."""
    from src.monitor.intraday import fire_alerts

    pos = _make_short_call(expiry=date.today() + timedelta(days=30))
    quote = _make_quote(delta=0.48)
    alert = RollAlert(
        position_symbol=pos.symbol,
        underlying=pos.underlying,
        trigger="delta_drift",
        detail="delta=0.48 > ceiling=0.45",
        current_delta=0.48,
        dte=30,
    )

    mock_bot = AsyncMock()

    cfg = MagicMock()
    cfg.monitor.alert_cooldown_minutes = 30
    cfg.claude.enabled = False  # skip actual Claude subprocess

    with (
        patch("src.monitor.intraday._is_recent_alert", return_value=False),
        patch("src.monitor.intraday._persist_alert"),
    ):
        with ThreadPoolExecutor(max_workers=1) as ex:
            await fire_alerts([alert], pos, quote, mock_bot, "test_chat", cfg, ex)

    mock_bot.send_message.assert_called_once()
    sent_text = mock_bot.send_message.call_args.kwargs.get("text", "")
    # trigger name is MarkdownV2-escaped (_→\_) so check for the prefix
    assert "delta" in sent_text and "drift" in sent_text


@pytest.mark.asyncio
async def test_fire_alerts_suppressed_when_recent(tmp_path: Path) -> None:
    """No Telegram send when all alerts are within the cooldown window."""
    from src.monitor.intraday import fire_alerts

    pos = _make_short_call()
    quote = _make_quote(delta=0.48)
    alert = RollAlert(
        position_symbol=pos.symbol,
        underlying=pos.underlying,
        trigger="delta_drift",
        detail="delta=0.48 > ceiling=0.45",
    )

    mock_bot = AsyncMock()
    cfg = MagicMock()
    cfg.monitor.alert_cooldown_minutes = 30
    cfg.claude.enabled = False

    with patch("src.monitor.intraday._is_recent_alert", return_value=True):
        with ThreadPoolExecutor(max_workers=1) as ex:
            await fire_alerts([alert], pos, quote, mock_bot, "test_chat", cfg, ex)

    mock_bot.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# Alert text formatting
# ---------------------------------------------------------------------------


def test_build_alert_text_no_review() -> None:
    from src.notify.formatters import format_roll_alert

    pos = _make_short_call()
    quote = _make_quote(delta=0.48, iv=0.55)
    alert = RollAlert(
        position_symbol=pos.symbol,
        underlying="AAPL",
        trigger="delta_drift",
        detail="delta=0.48 > ceiling=0.45",
        current_delta=0.48,
        dte=30,
    )
    text = format_roll_alert(pos, quote, [alert], review=None)
    assert "Roll Alert" in text
    assert "AAPL" in text
    # trigger name is MarkdownV2-escaped (_→\_); check both parts individually
    assert "delta" in text and "drift" in text
    assert "manual evaluation" in text


def test_build_alert_text_with_review() -> None:
    from src.notify.formatters import format_roll_alert

    pos = _make_short_call()
    quote = _make_quote(delta=0.48)
    alert = RollAlert(
        position_symbol=pos.symbol,
        underlying="AAPL",
        trigger="delta_drift",
        detail="delta=0.48 > ceiling=0.45",
    )
    review = RollReview(
        position_symbol=pos.symbol,
        recommendation="roll",
        roll_target="roll to $190 Aug 15 CC at 0.30 delta",
        rationale="Delta has exceeded threshold; roll to maintain income.",
        risks="Stock in momentum; assignment risk remains.",
        confidence=0.82,
    )
    text = format_roll_alert(pos, quote, [alert], review=review)
    assert "ROLL" in text
    assert "$190" in text


def test_format_assignment_alert_no_review() -> None:
    from src.notify.formatters import format_assignment_alert

    pos = _make_short_call(expiry=_EXPIRY_21D)
    quote = _make_quote(delta=0.75, expiry=_EXPIRY_21D)
    alert = RollAlert(
        position_symbol=pos.symbol,
        underlying="AAPL",
        trigger="assignment_risk",
        detail="|Δ|=0.75 ≥ 0.70 with DTE=21 — consider: roll / close / let-assign",
        current_delta=0.75,
        dte=21,
    )
    text = format_assignment_alert(pos, quote, [alert], review=None)
    assert "Assignment Risk" in text
    assert "AAPL" in text
    assert "roll" in text.lower()
    assert "close" in text.lower()
    assert "manual evaluation" in text


def test_format_assignment_alert_with_review() -> None:
    from src.notify.formatters import format_assignment_alert

    pos = _make_short_call(expiry=_EXPIRY_21D)
    quote = _make_quote(delta=0.80, expiry=_EXPIRY_21D)
    alert = RollAlert(
        position_symbol=pos.symbol,
        underlying="AAPL",
        trigger="assignment_risk",
        detail="|Δ|=0.80 ≥ 0.70 with DTE=15 — consider: roll / close / let-assign",
        current_delta=0.80,
        dte=15,
    )
    review = RollReview(
        position_symbol=pos.symbol,
        recommendation="roll",
        roll_target="roll out to Sep CC $195",
        rationale="Deep ITM; rolling recovers premium.",
        risks="Further upside possible.",
        confidence=0.78,
    )
    text = format_assignment_alert(pos, quote, [alert], review=review)
    assert "ROLL" in text
    assert "Sep CC" in text


# ---------------------------------------------------------------------------
# Claude integration (parse_roll_output)
# ---------------------------------------------------------------------------


def test_parse_roll_output_valid() -> None:
    import json

    from src.claude.parser import parse_roll_output

    inner = {
        "position_symbol": "AAPL  260117C00185000",
        "recommendation": "roll",
        "roll_target": "roll to $190 Aug 15",
        "rationale": "Delta drift too high.",
        "risks": "Stock momentum.",
        "confidence": 0.80,
    }
    envelope = {"type": "result", "result": json.dumps(inner)}
    result = parse_roll_output(json.dumps(envelope))
    assert result is not None
    assert result.recommendation == "roll"
    assert result.confidence == pytest.approx(0.80)


def test_parse_roll_output_empty_returns_none() -> None:
    from src.claude.parser import parse_roll_output

    assert parse_roll_output("") is None
    assert parse_roll_output("{}") is None


def test_parse_roll_output_invalid_schema_returns_none() -> None:
    import json

    from src.claude.parser import parse_roll_output

    inner = {"some": "garbage", "data": 123}
    envelope = {"type": "result", "result": json.dumps(inner)}
    assert parse_roll_output(json.dumps(envelope)) is None


# ---------------------------------------------------------------------------
# Phase C: entry_iv wiring (IV-spike baseline) — was permanently dead before.
# ---------------------------------------------------------------------------


def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import src.storage.db as _db_mod
    from src.storage.models import Base

    db_url = f"sqlite:///{tmp_path / 'entry_iv.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(_db_mod, "_engine", engine)
    monkeypatch.setattr(_db_mod, "_SessionLocal", Session)


def test_load_entry_iv_matches_position(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A filled candidate's entry_iv is recovered by matching the position's contract."""
    from src.monitor.intraday import _load_entry_iv
    from src.storage.db import session_scope
    from src.storage.models import CandidateRow, FillRow

    _isolated_db(tmp_path, monkeypatch)
    expiry = date.today() + timedelta(days=30)

    with session_scope() as s:
        s.add(
            CandidateRow(
                candidate_id="cand-iv",
                run_id="r1",
                strategy="covered_call",
                underlying="AAPL",
                right="C",
                strike=185.0,
                expiry=expiry,
                blended_score=70.0,
                payload={},
            )
        )
        s.add(
            FillRow(
                order_id=1,
                candidate_id="cand-iv",
                filled_qty=1.0,
                avg_price=1.50,
                entry_iv=0.32,
            )
        )

    pos = PositionSnapshot(
        symbol="AAPL  260117C00185000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=1.50,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=expiry,
        underlying="AAPL",
    )
    assert _load_entry_iv(pos) == pytest.approx(0.32)


def test_load_entry_iv_none_when_no_fill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.monitor.intraday import _load_entry_iv

    _isolated_db(tmp_path, monkeypatch)
    pos = PositionSnapshot(
        symbol="AAPL  260117C00185000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=1.50,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date.today() + timedelta(days=30),
        underlying="AAPL",
    )
    assert _load_entry_iv(pos) is None


def test_iv_spike_fires_end_to_end_with_loaded_entry_iv() -> None:
    """With a real entry_iv (as the monitor now loads), a large IV move fires the trigger."""
    pos = _make_short_call(delta=0.20)
    quote = _make_quote(delta=0.20, iv=0.60)  # IV jumped from 0.32 → 0.60 (+87%)
    limits = {"delta_ceiling": 0.45, "dte_threshold": 7, "iv_spike_pct": 40.0}
    alerts = check_all(pos, quote, entry_iv=0.32, fund_stats=None, limits=limits)
    assert any(a.trigger == "iv_spike" for a in alerts)


# ---------------------------------------------------------------------------
# IntradayMonitor: double-subscribe prevention (P0-05 / P0-06)
# ---------------------------------------------------------------------------


def _make_monitor() -> tuple:
    """Return (monitor, mock_ib) with a minimal config."""
    mock_ib = MagicMock()
    mock_ib.tickers.return_value = []
    mock_ib.portfolio.return_value = []
    mock_ib.qualifyContractsAsync = AsyncMock(side_effect=lambda *contracts: list(contracts))
    mock_cfg = MagicMock()
    mock_cfg.monitor.delta_ceiling = 0.45
    mock_cfg.monitor.dte_threshold = 7
    mock_cfg.monitor.iv_spike_pct = 40.0
    mock_cfg.monitor.ex_div_days_ahead = 5
    mock_cfg.monitor.alert_cooldown_minutes = 60
    mock_cfg.scheduler.intraday_poll_seconds = 60
    mock_cfg.claude.enabled = False

    from src.monitor.intraday import IntradayMonitor

    executor = ThreadPoolExecutor(max_workers=1)
    monitor = IntradayMonitor(mock_ib, AsyncMock(), "99999", mock_cfg, executor)
    return monitor, mock_ib


async def test_on_reconnect_clears_subscriptions_before_refresh() -> None:
    """P0-05: _on_reconnect must clear _subscriptions so _refresh_subscriptions
    doesn't find symbols already present and skip resubscription.

    After _on_reconnect, _subscriptions must be empty (cleared) before any
    new positions are re-subscribed.
    """
    from src.common.schemas import OptionRight, PositionSnapshot

    monitor, mock_ib = _make_monitor()

    # Pre-populate subscriptions as if already subscribed.
    dummy_contract = MagicMock()
    old_pos = PositionSnapshot(
        symbol="AAPL  260117C00185000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=1.50,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date.today() + timedelta(days=30),
        underlying="AAPL",
    )
    monitor._subscriptions["AAPL  260117C00185000"] = (old_pos, dummy_contract)
    monitor._entry_iv["AAPL  260117C00185000"] = 0.32

    # After reconnect with no positions (empty portfolio), subscriptions should be cleared.
    mock_ib.portfolio.return_value = []
    with patch("src.monitor.intraday.get_positions", return_value=[]):
        await monitor._on_reconnect()

    assert monitor._subscriptions == {}
    assert monitor._entry_iv == {}


class _RealishIB:
    """Stands in for ``ib_async.IB`` using a genuine ``Wrapper`` for ticker bookkeeping.

    ``reqMktData``/``cancelMktData`` delegate to the real ``Wrapper.startTicker``/``endTicker``
    — the exact code path that raises ``ValueError`` for an unqualified contract (``conId=0``,
    which is what ``build_option`` returns) — without needing a live TWS/Gateway connection. A
    ``MagicMock`` standing in for ``ib`` (as every other test in this file uses) never raises
    here regardless of whether the contract passed to it was qualified, which is exactly why
    this bug went unnoticed.
    """

    def __init__(self) -> None:
        from ib_async.wrapper import Wrapper

        self.wrapper = Wrapper(None)
        self._next_req_id = 1

    def reqMktData(self, contract, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        req_id = self._next_req_id
        self._next_req_id += 1
        return self.wrapper.startTicker(req_id, contract, "mktData")

    def cancelMktData(self, contract) -> None:  # noqa: ANN001
        ticker = self.wrapper.tickers.get(hash(contract))
        if ticker is not None:
            self.wrapper.endTicker(ticker, "mktData")

    async def qualifyContractsAsync(self, *contracts):  # noqa: ANN002
        for i, c in enumerate(contracts):
            c.conId = 999_000 + i
        return list(contracts)


async def test_refresh_subscriptions_qualifies_before_reqmktdata() -> None:
    """Regression: before the fix, `build_option`'s unqualified contract went straight into
    `reqMktData`, which raised inside ib_async's own ticker bookkeeping — silently caught by
    the surrounding `except Exception`, so the monitor never actually subscribed to a single
    short option's live ticks, and every roll/assignment trigger depending on
    `pendingTickersEvent` never fired."""
    from src.monitor.intraday import IntradayMonitor

    ib = _RealishIB()
    mock_cfg = MagicMock()
    mock_cfg.monitor.delta_ceiling = 0.45
    mock_cfg.monitor.dte_threshold = 7
    mock_cfg.monitor.iv_spike_pct = 40.0
    mock_cfg.monitor.ex_div_days_ahead = 5
    mock_cfg.monitor.alert_cooldown_minutes = 60
    mock_cfg.scheduler.intraday_poll_seconds = 60
    mock_cfg.claude.enabled = False

    executor = ThreadPoolExecutor(max_workers=1)
    monitor = IntradayMonitor(ib, AsyncMock(), "99999", mock_cfg, executor)

    pos = PositionSnapshot(
        symbol="AAPL  260117C00185000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=1.50,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date.today() + timedelta(days=30),
        underlying="AAPL",
    )

    with (
        patch("src.monitor.intraday.get_positions", return_value=[pos]),
        patch("src.monitor.intraday._load_entry_iv", return_value=None),
        patch("src.monitor.intraday.get_fundamental_stats", return_value=MagicMock()),
    ):
        await monitor._refresh_subscriptions()

    assert "AAPL  260117C00185000" in monitor._subscriptions
    _, contract = monitor._subscriptions["AAPL  260117C00185000"]
    assert getattr(contract, "conId", 0) != 0


async def test_double_subscribe_prevention_on_repeated_refresh() -> None:
    """P0-06: calling _refresh_subscriptions twice for the same position must call
    reqMktData exactly once — the second call sees the position already subscribed and
    updates the snapshot without adding a new subscription.
    """
    from src.common.schemas import OptionRight, PositionSnapshot

    monitor, mock_ib = _make_monitor()

    pos = PositionSnapshot(
        symbol="AAPL  260117C00185000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=1.50,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date.today() + timedelta(days=30),
        underlying="AAPL",
    )

    with (
        patch("src.monitor.intraday.get_positions", return_value=[pos]),
        patch("src.monitor.intraday._load_entry_iv", return_value=None),
        patch("src.monitor.intraday.get_fundamental_stats", return_value=MagicMock()),
        patch("src.monitor.intraday.build_option", return_value=MagicMock()),
    ):
        await monitor._refresh_subscriptions()
        await monitor._refresh_subscriptions()  # second call — should not add new subscription

    # reqMktData called exactly once despite two refresh calls.
    assert mock_ib.reqMktData.call_count == 1


async def test_cancel_uses_stored_contract() -> None:
    """P0-06: when a position is closed, cancelMktData must be called with the same
    Contract object that was used in reqMktData, not a freshly-built unqualified one.
    """
    from src.common.schemas import OptionRight, PositionSnapshot

    monitor, mock_ib = _make_monitor()

    stored_contract = MagicMock()
    stored_contract.conId = 99999

    pos = PositionSnapshot(
        symbol="AAPL  260117C00185000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=1.50,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=date.today() + timedelta(days=30),
        underlying="AAPL",
    )
    # Pre-populate with the stored contract.
    monitor._subscriptions["AAPL  260117C00185000"] = (pos, stored_contract)

    # Refresh with empty positions — triggers cancellation of the closed position.
    with patch("src.monitor.intraday.get_positions", return_value=[]):
        await monitor._refresh_subscriptions()

    mock_ib.cancelMktData.assert_called_once_with(stored_contract)
