"""One definition. Before this file, /options/shorts and the monitor disagreed by 14 days.

``src/monitor/triggers.py::check_assignment_risk`` (the monitor, a trading process) and
``src/api/routers/options.py`` (the API, a web-layer process) each computed assignment risk
themselves, with different DTE thresholds (21 vs. a hardcoded 7). Task 0.3 moves the decision
into ``src/common/assignment_risk.py`` — the one module both may import — and rewires both
callers to it. The monitor's real threshold (0.70 delta, 21 DTE) wins; the API's 7 was a copy
of a copy that drifted.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.common.assignment_risk import assignment_risk_thresholds, is_assignment_risk

DELTA_T, DTE_T = 0.70, 21


def _risk(position: float, delta: float | None, dte: int | None) -> bool:
    return is_assignment_risk(
        position=position,
        delta=delta,
        dte=dte,
        delta_threshold=DELTA_T,
        dte_threshold=DTE_T,
    )


def test_the_case_the_two_surfaces_disagreed_on() -> None:
    """delta 0.75, 10 DTE: the monitor alerted, /options/shorts said false."""
    assert _risk(-1.0, -0.75, 10) is True


def test_far_from_expiry_is_not_at_risk() -> None:
    assert _risk(-1.0, -0.75, 25) is False


def test_low_delta_near_expiry_is_not_at_risk() -> None:
    assert _risk(-1.0, -0.50, 3) is False


def test_a_long_position_is_never_at_risk() -> None:
    assert _risk(1.0, -0.75, 3) is False


@pytest.mark.parametrize("delta,dte", [(None, 3), (-0.9, None), (None, None)])
def test_missing_data_is_never_a_signal(delta, dte) -> None:
    assert _risk(-1.0, delta, dte) is False


def test_fires_exactly_at_both_thresholds() -> None:
    """abs(delta) >= threshold and dte <= threshold are both inclusive boundaries."""
    assert _risk(-1.0, -0.70, 21) is True


def test_zero_position_is_not_a_short() -> None:
    assert _risk(0.0, -0.90, 1) is False


# ---------------------------------------------------------------------------
# assignment_risk_thresholds(cfg) — no caller hardcodes either number.
# ---------------------------------------------------------------------------


def test_thresholds_come_from_config_not_a_hardcoded_pair() -> None:
    from src.common.config import get_config

    cfg = get_config()
    delta_threshold, dte_threshold = assignment_risk_thresholds(cfg)
    assert delta_threshold == cfg.monitor.assignment_alert_delta
    assert dte_threshold == cfg.monitor.assignment_alert_dte
    # Pinned to the real config/settings.yaml values this task is about (0.70 / 21, not 7).
    assert (delta_threshold, dte_threshold) == (0.70, 21)


# ---------------------------------------------------------------------------
# check_assignment_risk delegates the decision but keeps its own signature and
# RollAlert construction.
# ---------------------------------------------------------------------------


def test_check_assignment_risk_still_returns_a_roll_alert_for_a_qualifying_position() -> None:
    from src.common.market_hours import today_et
    from src.common.schemas import OptionQuote, OptionRight, PositionSnapshot
    from src.monitor.triggers import check_assignment_risk

    expiry = today_et() + timedelta(days=10)
    pos = PositionSnapshot(
        symbol="AAPL  260117C00185000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=200.0,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=expiry,
        underlying="AAPL",
        delta=0.75,
    )
    quote = OptionQuote(
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=185.0,
        expiry=expiry,
        delta=0.75,
    )
    alert = check_assignment_risk(pos, quote, delta_threshold=0.70, dte_threshold=21)
    assert alert is not None
    assert alert.trigger == "assignment_risk"
    assert alert.position_symbol == "AAPL  260117C00185000"
    assert alert.underlying == "AAPL"
    assert alert.current_delta == 0.75
    assert alert.dte == 10


def test_check_assignment_risk_returns_none_when_not_qualifying() -> None:
    from src.common.market_hours import today_et
    from src.common.schemas import OptionQuote, OptionRight, PositionSnapshot
    from src.monitor.triggers import check_assignment_risk

    expiry = today_et() + timedelta(days=25)
    pos = PositionSnapshot(
        symbol="AAPL  260117C00185000",
        sec_type="OPT",
        position=-1.0,
        avg_cost=200.0,
        right=OptionRight.CALL,
        strike=185.0,
        expiry=expiry,
        underlying="AAPL",
        delta=0.75,
    )
    quote = OptionQuote(
        underlying="AAPL",
        right=OptionRight.CALL,
        strike=185.0,
        expiry=expiry,
        delta=0.75,
    )
    assert check_assignment_risk(pos, quote, delta_threshold=0.70, dte_threshold=21) is None


# ---------------------------------------------------------------------------
# The API and the monitor agree — the regression this task exists to prevent.
# ---------------------------------------------------------------------------

TOKEN = "correct-horse-battery"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("src.api.auth._configured_token", lambda: TOKEN)
    trading_db = tmp_path / "income_system.db"
    monkeypatch.setattr("src.api.trading_db._engine", None)
    monkeypatch.setattr("src.api.trading_db._SessionLocal", None)
    monkeypatch.setattr("src.api.trading_db._resolve_path", lambda: trading_db.as_posix())
    monkeypatch.setattr("src.api.trading_db._cmd_engine", None)
    monkeypatch.setattr("src.api.trading_db._cmd_session_factory", None)
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{trading_db}")
    dbmod.init_db()

    from src.api.main import create_app

    return TestClient(create_app())


@pytest.fixture
def seed_short_position(client):
    """Replace the latest snapshot with a single short position at the given delta/dte."""

    def _seed(*, delta: float, dte: int) -> None:
        from src.storage.db import session_scope
        from src.storage.models import PositionSnapshotRow

        expiry = (date.today() + timedelta(days=dte)).isoformat()
        with session_scope() as s:
            s.query(PositionSnapshotRow).delete()
            s.add(
                PositionSnapshotRow(
                    snapshot_date=date.today(),
                    payload=[
                        {
                            "symbol": "NVDA  260117 00190000 P",
                            "sec_type": "OPT",
                            "position": -1.0,
                            "avg_cost": 3.25,
                            "right": "P",
                            "strike": 190.0,
                            "expiry": expiry,
                            "delta": delta,
                            "underlying": "NVDA",
                        }
                    ],
                    created_at=datetime.now(UTC),
                )
            )

    return _seed


def test_the_api_and_the_monitor_agree(client, seed_short_position) -> None:
    """The regression this task exists to prevent from recurring."""
    for delta, dte, expected in [(-0.75, 10, True), (-0.75, 25, False), (-0.50, 3, False)]:
        seed_short_position(delta=delta, dte=dte)
        body = client.get("/options/shorts", headers=AUTH).json()
        assert body["shorts"][0]["assignment_risk"] is expected
        assert expected == _risk(-1.0, delta, dte)
