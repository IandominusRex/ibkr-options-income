"""Tests for Phase 4 (Competitive Research Plan) — C6: Campaign chaining + auto cost-basis."""

from __future__ import annotations

from datetime import date

import pytest

# ---------------------------------------------------------------------------
# DB helpers (same pattern as test_execution.py)
# ---------------------------------------------------------------------------


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _seed_fill(session, candidate_id: str, action: str, avg_price: float, qty: float) -> None:
    from src.storage.models import FillRow

    session.add(
        FillRow(
            order_id=1,
            candidate_id=candidate_id,
            action=action,
            filled_qty=qty,
            avg_price=avg_price,
            is_live=False,
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# C6 — attach_fill_to_campaign: open / add leg / rollup / auto-close
# ---------------------------------------------------------------------------


def test_attach_sell_opens_new_campaign(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import attach_fill_to_campaign, load_campaigns
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "cand-001", "SELL", 1.50, 1.0)

    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "SELL", 1.50, 1.0)

    campaigns = load_campaigns()
    assert len(campaigns) == 1
    c = campaigns[0]
    assert c["symbol"] == "AAPL"
    assert c["status"] == "open"
    assert c["leg_count"] == 1
    assert c["total_premium_collected"] == pytest.approx(150.0)
    assert c["net_premium"] == pytest.approx(150.0)


def test_attach_second_sell_adds_leg(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import attach_fill_to_campaign, load_campaigns
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "cand-001", "SELL", 1.50, 1.0)
        _seed_fill(s, "cand-002", "SELL", 2.00, 1.0)

    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "SELL", 1.50, 1.0)
    attach_fill_to_campaign("AAPL", "cand-002", "covered_call", "SELL", 2.00, 1.0)

    campaigns = load_campaigns()
    assert len(campaigns) == 1  # same symbol → same campaign
    c = campaigns[0]
    assert c["leg_count"] == 2
    assert c["total_premium_collected"] == pytest.approx(350.0)  # (1.50 + 2.00) × 100


def test_attach_buy_fill_adds_debit(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import attach_fill_to_campaign, load_campaigns
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "cand-001", "SELL", 2.00, 1.0)
        _seed_fill(s, "cand-001", "BUY", 0.75, 1.0)

    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "SELL", 2.00, 1.0)
    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "BUY", 0.75, 1.0)

    campaigns = load_campaigns()
    c = campaigns[0]
    assert c["total_premium_collected"] == pytest.approx(200.0)
    assert c["total_debit_paid"] == pytest.approx(75.0)
    assert c["net_premium"] == pytest.approx(125.0)


def test_attach_buy_orphan_is_noop(tmp_path, monkeypatch):
    """BUY fill with no open campaign should not create a campaign."""
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import attach_fill_to_campaign, load_campaigns
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "cand-001", "BUY", 0.50, 1.0)

    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "BUY", 0.50, 1.0)
    assert load_campaigns() == []


def test_auto_close_when_net_flat(tmp_path, monkeypatch):
    """Campaign closes automatically when buy qty equals sell qty and not assigned."""
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import attach_fill_to_campaign, load_campaigns
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "cand-001", "SELL", 2.00, 1.0)
        _seed_fill(s, "cand-001", "BUY", 0.50, 1.0)

    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "SELL", 2.00, 1.0)
    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "BUY", 0.50, 1.0)

    campaigns = load_campaigns()
    assert campaigns[0]["status"] == "closed"
    assert campaigns[0]["closed_date"] is not None


def test_auto_close_does_not_fire_when_assigned(tmp_path, monkeypatch):
    """An assigned campaign stays open so the CC follow-on can attach."""
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import (
        attach_fill_to_campaign,
        load_campaigns,
        mark_campaign_assigned,
    )
    from src.storage.db import session_scope

    # Seed and attach fills in order (SELL first, then assignment, then BUY closure).
    with session_scope() as s:
        _seed_fill(s, "cand-001", "SELL", 2.00, 1.0)
    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "SELL", 2.00, 1.0)

    # Assignment detected before the closing BUY arrives (e.g. from position diff at EOD).
    mark_campaign_assigned("AAPL", assignment_price=38.0)

    # Closing BUY (assignment exercised, option bought back at intrinsic or expires assigned).
    with session_scope() as s:
        _seed_fill(s, "cand-001", "BUY", 2.00, 1.0)
    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "BUY", 2.00, 1.0)

    campaigns = load_campaigns()
    # Assigned flag prevents auto-close even though buy_qty == sell_qty.
    assert campaigns[0]["status"] == "open"
    assert campaigns[0]["assigned"] is True


def test_mark_campaign_assigned_computes_acb(tmp_path, monkeypatch):
    """adjusted_cost_basis = assignment_price − net_premium / 100."""
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import (
        attach_fill_to_campaign,
        load_campaigns,
        mark_campaign_assigned,
    )
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "cand-001", "SELL", 3.00, 1.0)  # $300 net premium

    attach_fill_to_campaign("AAPL", "cand-001", "cash_secured_put", "SELL", 3.00, 1.0)
    mark_campaign_assigned("AAPL", assignment_price=150.0)

    campaigns = load_campaigns()
    c = campaigns[0]
    assert c["assigned"] is True
    # net_premium = 300, /100 = 3.00 per share → ACB = 150 − 3 = 147
    assert c["adjusted_cost_basis"] == pytest.approx(147.0)


def test_mark_campaign_assigned_no_open_campaign_is_noop(tmp_path, monkeypatch):
    """mark_campaign_assigned on a symbol with no open campaign must not raise."""
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import mark_campaign_assigned

    mark_campaign_assigned("AAPL", assignment_price=100.0)  # should not raise


def test_load_campaigns_open_only_filter(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import attach_fill_to_campaign, load_campaigns
    from src.storage.db import session_scope

    # AAPL — open (one SELL, no BUY)
    with session_scope() as s:
        _seed_fill(s, "cand-aapl", "SELL", 1.50, 1.0)
    attach_fill_to_campaign("AAPL", "cand-aapl", "cash_secured_put", "SELL", 1.50, 1.0)

    # MARA — closed (SELL + matching BUY)
    with session_scope() as s:
        _seed_fill(s, "cand-mara", "SELL", 2.00, 1.0)
        _seed_fill(s, "cand-mara", "BUY", 0.50, 1.0)
    attach_fill_to_campaign("MARA", "cand-mara", "cash_secured_put", "SELL", 2.00, 1.0)
    attach_fill_to_campaign("MARA", "cand-mara", "cash_secured_put", "BUY", 0.50, 1.0)

    all_campaigns = load_campaigns()
    open_campaigns = load_campaigns(open_only=True)

    assert len(all_campaigns) == 2
    assert len(open_campaigns) == 1
    assert open_campaigns[0]["symbol"] == "AAPL"


def test_different_symbols_get_separate_campaigns(tmp_path, monkeypatch):
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import attach_fill_to_campaign, load_campaigns
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "cand-aapl", "SELL", 1.50, 1.0)
        _seed_fill(s, "cand-mara", "SELL", 2.00, 1.0)

    attach_fill_to_campaign("AAPL", "cand-aapl", "cash_secured_put", "SELL", 1.50, 1.0)
    attach_fill_to_campaign("MARA", "cand-mara", "cash_secured_put", "SELL", 2.00, 1.0)

    campaigns = load_campaigns()
    assert len(campaigns) == 2
    symbols = {c["symbol"] for c in campaigns}
    assert symbols == {"AAPL", "MARA"}


# ---------------------------------------------------------------------------
# C6 — format_campaigns formatter
# ---------------------------------------------------------------------------


def test_format_campaigns_empty():
    from src.notify.formatters import format_campaigns

    text = format_campaigns([])
    assert "No campaigns" in text


def test_format_campaigns_open_campaign():
    from src.notify.formatters import format_campaigns

    campaigns = [
        {
            "symbol": "AAPL",
            "status": "open",
            "opened_date": date(2026, 1, 15),
            "closed_date": None,
            "leg_count": 2,
            "total_premium_collected": 342.0,
            "total_debit_paid": 0.0,
            "net_premium": 342.0,
            "assigned": False,
            "adjusted_cost_basis": None,
            "realized_stock_pnl": None,
        }
    ]
    text = format_campaigns(campaigns)
    assert "AAPL" in text
    assert "342" in text
    assert "2 legs" in text


def test_format_campaigns_assigned_shows_acb():
    from src.notify.formatters import format_campaigns

    campaigns = [
        {
            "symbol": "MARA",
            "status": "open",
            "opened_date": date(2026, 2, 1),
            "closed_date": None,
            "leg_count": 1,
            "total_premium_collected": 300.0,
            "total_debit_paid": 0.0,
            "net_premium": 300.0,
            "assigned": True,
            "adjusted_cost_basis": 17.50,
            "realized_stock_pnl": None,
        }
    ]
    text = format_campaigns(campaigns)
    assert "MARA" in text
    assert "assigned" in text
    assert "cost basis" in text
    assert "17" in text  # ACB value present (dot is MarkdownV2-escaped in the raw string)


def test_format_campaigns_closed_campaign():
    from src.notify.formatters import format_campaigns

    campaigns = [
        {
            "symbol": "TSLA",
            "status": "closed",
            "opened_date": date(2026, 1, 1),
            "closed_date": date(2026, 1, 30),
            "leg_count": 1,
            "total_premium_collected": 125.0,
            "total_debit_paid": 37.5,
            "net_premium": 87.5,
            "assigned": False,
            "adjusted_cost_basis": None,
            "realized_stock_pnl": None,
        }
    ]
    text = format_campaigns(campaigns)
    assert "TSLA" in text
    assert "88" in text  # net_premium 87.5 rounded to 0 dp → 88
