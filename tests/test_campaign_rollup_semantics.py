"""campaigns.net_premium is GROSS of commissions. Pinned so it cannot drift silently.

`src/storage/campaigns.py::_rollup` sums `avg_price * filled_qty * 100` per fill into
`total_premium_collected` (SELL) and `total_debit_paid` (BUY), then sets
`net_premium = collected - paid`. There is no commission term anywhere in that arithmetic,
even though `FillRow.commission` is recorded on every fill (populated from IBKR's
commission report by `execution/executor.py`) and sits right there, unused, on every row
`_rollup` reads.

Meanwhile `src/claude/eval/reconcile.py::_classify` computes realized P&L as
`credit - debit - commissions` — net. So a campaign's `net_premium` and the sum of its
legs' realized P&L differ by exactly the commission total. That is a deliberate, currently
undocumented gap this task makes explicit; see the docstrings on `CampaignRow` and `_rollup`.

If a future change decides commissions belong in the rollup, this test fails first and the
change becomes deliberate — which is the point. It is not a test to quietly update.

NOTE ON TEST PLUMBING: this repo has no shared `db` pytest fixture (verified against
tests/conftest.py) and `attach_fill_to_campaign`'s real signature is
`(symbol, candidate_id, strategy, action, avg_price, filled_qty)` — it takes no `commission`
argument. Commission lives on the `FillRow` that is seeded *before* the attach call (exactly
as `execution/executor.py` does it: commission is stamped onto the FillRow at fill time, then
`attach_fill_to_campaign` re-aggregates from the FillRow table — see `_rollup`). This test
therefore follows the `_db_setup`/`_seed_fill` pattern already used by
`tests/test_phase4.py` and `tests/test_phase6.py`, extended to also stamp `commission` on
the seeded fill, rather than the illustrative (and not directly runnable against the current
API) `attach_fill_to_campaign(..., commission=...)` / `db`-fixture form sketched in the M0
planning doc. The pinned assertions and numbers are unchanged from that sketch.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# DB helpers (same pattern as tests/test_phase4.py / tests/test_phase6.py)
# ---------------------------------------------------------------------------


def _db_setup(tmp_path, monkeypatch) -> None:
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()


def _seed_fill(
    session,
    candidate_id: str,
    action: str,
    avg_price: float,
    qty: float,
    commission: float | None = None,
) -> None:
    from src.storage.models import FillRow

    session.add(
        FillRow(
            order_id=1,
            candidate_id=candidate_id,
            action=action,
            filled_qty=qty,
            avg_price=avg_price,
            commission=commission,
            is_live=False,
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# Pinning tests
# ---------------------------------------------------------------------------


def test_net_premium_is_gross_of_commissions(tmp_path, monkeypatch) -> None:
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import attach_fill_to_campaign, load_campaigns
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "c1", "SELL", 1.50, 2, commission=1.30)
    attach_fill_to_campaign(
        symbol="NVDA",
        candidate_id="c1",
        strategy="cash_secured_put",
        action="SELL",
        avg_price=1.50,
        filled_qty=2,
    )

    with session_scope() as s:
        _seed_fill(s, "c1", "BUY", 0.40, 2, commission=1.30)
    attach_fill_to_campaign(
        symbol="NVDA",
        candidate_id="c1",
        strategy="cash_secured_put",
        action="BUY",
        avg_price=0.40,
        filled_qty=2,
    )

    campaign = load_campaigns()[0]
    assert campaign["symbol"] == "NVDA"
    assert campaign["total_premium_collected"] == 300.0
    assert campaign["total_debit_paid"] == 80.0
    assert campaign["net_premium"] == 220.0  # NOT 217.40 — commissions are excluded


def test_the_gross_and_net_figures_differ_by_exactly_the_commissions(tmp_path, monkeypatch) -> None:
    """The relationship M4's cross-check relies on: net_premium - commissions == the net
    figure src/claude/eval/reconcile.py::_classify (and M4's src/reporting/legs.py) computes.
    """
    _db_setup(tmp_path, monkeypatch)
    from src.storage.campaigns import attach_fill_to_campaign, load_campaigns
    from src.storage.db import session_scope

    with session_scope() as s:
        _seed_fill(s, "c1", "SELL", 2.00, 1, commission=0.65)
    attach_fill_to_campaign(
        symbol="NVDA",
        candidate_id="c1",
        strategy="cash_secured_put",
        action="SELL",
        avg_price=2.00,
        filled_qty=1,
    )

    campaign = load_campaigns()[0]
    commissions = 0.65
    net_of_commissions = campaign["net_premium"] - commissions
    assert campaign["net_premium"] == 200.0
    assert net_of_commissions == pytest.approx(199.35)
