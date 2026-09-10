"""The first portfolio route. Empty is reported as empty, never as zero.

`GET /portfolio/summary` renders what `read_portfolio` found and adds nothing to it:
account values as `Sourced` (IBKR provenance, age derived by `Sourced.of`), the
exposure the operator needs before deciding anything, and the degradation rung in
words. The `none` rung is a 200 with `account=None` — zeros here would be a claim
about the account.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.conftest import OWNER, long_put, short_call, short_put, stock


def test_a_fresh_snapshot_is_reported_fresh(client, seed_portfolio_snapshot) -> None:
    when = datetime.now(UTC) - timedelta(minutes=3)
    seed_portfolio_snapshot(captured_at=when, source="monitor", net_liq=250_000.0)

    body = client.get("/portfolio/summary", headers=OWNER).json()
    assert body["source"] == "monitor"
    assert body["degraded"] is False
    assert body["account"]["net_liquidation"]["value"] == 250_000.0
    assert body["account"]["net_liquidation"]["stale"] is False
    assert body["as_of"].startswith(when.isoformat()[:16])


def test_nothing_captured_yet_is_200_and_says_so(client) -> None:
    """Zeros here would be a claim about the account."""
    r = client.get("/portfolio/summary", headers=OWNER)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "none"
    assert body["account"] is None
    assert body["exposure"] is None
    assert body["note"]


def test_the_eod_rung_is_flagged_degraded(client, seed_position_snapshot, seed_journal) -> None:
    seed_position_snapshot(symbols=["NVDA"])
    seed_journal(net_liq=100_000.0)

    body = client.get("/portfolio/summary", headers=OWNER).json()
    assert body["source"] == "eod"
    assert body["degraded"] is True
    assert body["note"]


def test_an_old_snapshot_marks_every_value_stale(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(captured_at=datetime.now(UTC) - timedelta(hours=4))
    account = client.get("/portfolio/summary", headers=OWNER).json()["account"]
    assert all(
        account[k]["stale"] is True
        for k in (
            "net_liquidation",
            "total_cash",
            "buying_power",
            "maintenance_margin",
            "excess_liquidity",
        )
    )


def test_cash_secured_counts_short_puts_only(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(
        positions=[
            short_put(strike=100.0, contracts=2),  # 100 * 2 * 100 = 20_000
            short_call(strike=200.0, contracts=1),  # not cash-secured
            long_put(strike=90.0, contracts=1),  # not an obligation
            stock(symbol="NVDA", shares=100),  # not an option
        ]
    )
    exposure = client.get("/portfolio/summary", headers=OWNER).json()["exposure"]
    assert exposure["cash_secured_against_puts"] == 20_000.0


def test_utilisation_is_none_not_zero_when_buying_power_is_zero(
    client, seed_portfolio_snapshot
) -> None:
    seed_portfolio_snapshot(buying_power=0.0)
    exposure = client.get("/portfolio/summary", headers=OWNER).json()["exposure"]
    assert exposure["buying_power_utilisation_pct"] is None


def test_assignment_risk_count_uses_the_shared_predicate(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(positions=[short_call(delta=-0.75, dte=10)])
    exposure = client.get("/portfolio/summary", headers=OWNER).json()["exposure"]
    assert exposure["shorts_at_assignment_risk"] == 1


def test_a_non_owner_is_refused(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/portfolio/summary", headers=OWNER).status_code == 403


def test_net_delta_matches_the_eod_formula(client, seed_portfolio_snapshot) -> None:
    """Options contribute delta * position * 100; stock contributes its share count —
    the same Σ the EOD summary already computes (eod_report.py:236)."""
    seed_portfolio_snapshot(
        positions=[
            short_put(delta=-0.25, contracts=2),  # -0.25 * -2 * 100 = +50
            short_call(delta=0.30, contracts=1),  # 0.30 * -1 * 100 = -30
            stock(symbol="NVDA", shares=100),  # +100
        ]
    )
    exposure = client.get("/portfolio/summary", headers=OWNER).json()["exposure"]
    assert exposure["net_delta_exposure"] == 120.0
