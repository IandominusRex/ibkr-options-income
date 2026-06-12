"""Phase 0 foundation tests — no TWS/Gateway required.

Covers: config loading, the live/paper port switch, schema computed properties,
and DB initialization + a round-trip insert.
"""

from __future__ import annotations

from datetime import date, datetime

from src.common.config import get_config
from src.common.schemas import (
    OptionQuote,
    OptionRight,
    ScoreCard,
    Strategy,
    TradeCandidate,
)


def test_config_loads_and_sections_present():
    cfg = get_config()
    assert cfg.ibkr.host == "127.0.0.1"
    assert "max_pct_per_ticker" in cfg.risk["portfolio"]
    assert "watchlist" in cfg.universe
    assert "covered_call" in cfg.weights


def test_port_switch_follows_live_flag():
    cfg = get_config()
    expected = cfg.ibkr.live_port if cfg.is_live else cfg.ibkr.paper_port
    assert cfg.ibkr_port == expected


def test_client_ids_are_unique():
    cfg = get_config()
    ids = list(cfg.ibkr.client_ids.values())
    assert len(ids) == len(set(ids)), "clientIds must be unique per process"


class TestSchedulerTimeValidation:
    """SYSTEM_REVIEW F3: malformed HH:MM must fail loud at config load."""

    def test_valid_entry_cutoff_accepted(self):
        from src.common.config import SchedulerCfg

        assert SchedulerCfg(entry_cutoff="15:00").entry_cutoff == "15:00"
        assert SchedulerCfg(entry_cutoff="09:30").entry_cutoff == "09:30"

    def test_malformed_entry_cutoff_rejected(self):
        import pytest
        from pydantic import ValidationError

        from src.common.config import SchedulerCfg

        for bad in ("3pm", "1500", "15:60", "24:00", "15:00:00", ""):
            with pytest.raises(ValidationError):
                SchedulerCfg(entry_cutoff=bad)

    def test_morning_scan_and_eod_validated_too(self):
        import pytest
        from pydantic import ValidationError

        from src.common.config import SchedulerCfg

        with pytest.raises(ValidationError):
            SchedulerCfg(morning_scan="quarter to ten")
        with pytest.raises(ValidationError):
            SchedulerCfg(eod_report="25:00")


def test_option_quote_mid_and_spread():
    q = OptionQuote(
        underlying="NVDA",
        right=OptionRight.PUT,
        strike=100.0,
        expiry=date.today(),
        bid=1.00,
        ask=1.20,
    )
    assert q.mid == 1.10
    assert q.spread_pct == round(0.20 / 1.10 * 100, 2)


def test_option_quote_mid_falls_back_to_last():
    q = OptionQuote(
        underlying="NVDA",
        right=OptionRight.CALL,
        strike=100.0,
        expiry=date.today(),
        last=2.5,
    )
    assert q.mid == 2.5


def test_trade_candidate_roundtrips_through_json():
    cand = TradeCandidate(
        candidate_id="abc123",
        strategy=Strategy.CASH_SECURED_PUT,
        underlying="NVDA",
        right=OptionRight.PUT,
        strike=100.0,
        expiry=date(2026, 6, 19),
        premium=1.40,
        collateral=10000.0,
        roc_pct=1.4,
        annualized_yield_pct=17.0,
        breakeven=98.6,
        dte=20,
        scores=ScoreCard(symbol="NVDA"),
    )
    dumped = cand.model_dump(mode="json")
    restored = TradeCandidate.model_validate(dumped)
    assert restored.candidate_id == "abc123"
    assert restored.strategy is Strategy.CASH_SECURED_PUT


def test_db_init_and_insert(tmp_path, monkeypatch):
    # Point the DB at a temp file so the test never touches real state.
    import src.storage.db as dbmod
    from src.common.config import Config
    from src.storage.models import IVHistoryRow

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    # Patch the method on the class (Pydantic blocks per-instance attr assignment).
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")

    dbmod.init_db()
    with dbmod.session_scope() as s:
        s.add(IVHistoryRow(symbol="NVDA", obs_date=date.today(), iv=0.45, source="test"))

    with dbmod.session_scope() as s:
        rows = s.query(IVHistoryRow).all()
        assert len(rows) == 1
        assert rows[0].symbol == "NVDA"
        assert isinstance(rows[0].iv, float)
        assert isinstance(rows[0].obs_date, date)
        _ = datetime  # silence unused import in some linters
