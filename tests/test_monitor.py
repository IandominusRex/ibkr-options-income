"""Tests for Phase 8: Intraday monitor + roll triggers.

All IB and Telegram calls are mocked. DB tests use tmp_path + SQLite.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    pos = _make_short_call(expiry=date.today() + timedelta(days=7))
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
    assert "delta_drift" in sent_text


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
    from src.monitor.intraday import _build_alert_text

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
    text = _build_alert_text(pos, quote, [alert], review=None)
    assert "Roll Alert" in text
    assert "AAPL" in text
    assert "delta_drift" in text
    assert "manual evaluation" in text


def test_build_alert_text_with_review() -> None:
    from src.monitor.intraday import _build_alert_text

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
    text = _build_alert_text(pos, quote, [alert], review=review)
    assert "ROLL" in text
    assert "$190" in text


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
                candidate_id="cand-iv", run_id="r1", strategy="covered_call",
                underlying="AAPL", right="C", strike=185.0, expiry=expiry,
                blended_score=70.0, payload={},
            )
        )
        s.add(
            FillRow(
                order_id=1, candidate_id="cand-iv", filled_qty=1.0,
                avg_price=1.50, entry_iv=0.32,
            )
        )

    pos = PositionSnapshot(
        symbol="AAPL  260117C00185000", sec_type="OPT", position=-1.0, avg_cost=1.50,
        right=OptionRight.CALL, strike=185.0, expiry=expiry, underlying="AAPL",
    )
    assert _load_entry_iv(pos) == pytest.approx(0.32)


def test_load_entry_iv_none_when_no_fill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.monitor.intraday import _load_entry_iv

    _isolated_db(tmp_path, monkeypatch)
    pos = PositionSnapshot(
        symbol="AAPL  260117C00185000", sec_type="OPT", position=-1.0, avg_cost=1.50,
        right=OptionRight.CALL, strike=185.0, expiry=date.today() + timedelta(days=30),
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
