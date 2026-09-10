"""GET /portfolio/positions — every position, grouped by underlying.

Adjusted-basis semantics: both cost bases are reported, never one substituted for
the other. `avg_cost` is what IBKR says; `adjusted_cost_basis` is what the
collected premium makes it. `unrealized_pnl` is against the former,
`unrealized_pnl_adjusted` against the latter — a profitable assigned position
must not look like a loss.
"""

from __future__ import annotations

from datetime import date

from tests.conftest import OWNER, short_call, short_put, stock


def test_stock_and_options_group_under_one_underlying(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(
        positions=[
            stock(symbol="NVDA", shares=100),
            short_put(underlying="NVDA"),
            short_call(underlying="NVDA"),
        ]
    )
    body = client.get("/portfolio/positions", headers=OWNER).json()
    assert body["source"] == "monitor"
    assert len(body["groups"]) == 1
    group = body["groups"][0]
    assert group["underlying"] == "NVDA"
    assert group["stock"]["shares"] == 100.0
    assert len(group["options"]) == 2


def test_an_option_with_no_underlying_groups_under_its_own_symbol(
    client, seed_portfolio_snapshot
) -> None:
    pos = short_put(underlying="NVDA")
    pos["underlying"] = None
    pos["symbol"] = "ORPHAN  260918 00190000P"
    seed_portfolio_snapshot(positions=[pos])

    groups = client.get("/portfolio/positions", headers=OWNER).json()["groups"]
    assert [g["underlying"] for g in groups] == ["ORPHAN  260918 00190000P"]
    assert groups[0]["stock"] is None
    assert len(groups[0]["options"]) == 1


def test_assigned_shares_report_both_cost_bases(
    client, seed_portfolio_snapshot, seed_assigned_campaign
) -> None:
    """Premium collected is what makes an assigned position profitable. Show both numbers."""
    seed_assigned_campaign(symbol="NVDA", assignment_price=180.0, adjusted_basis=173.50)
    assigned_stock = stock(symbol="NVDA", shares=100, avg_cost=180.0, market_price=176.0)
    assigned_stock["unrealized_pnl"] = -400.0  # (176 - 180) * 100, against the raw fill
    seed_portfolio_snapshot(positions=[assigned_stock])

    group = client.get("/portfolio/positions", headers=OWNER).json()["groups"][0]
    assert group["stock"]["avg_cost"] == 180.0
    assert group["stock"]["adjusted_cost_basis"] == 173.50
    assert group["stock"]["unrealized_pnl"] < 0  # against the raw fill price
    assert group["stock"]["unrealized_pnl_adjusted"] > 0  # against the premium-adjusted basis


def test_ordinary_shares_report_no_adjusted_basis(client, seed_portfolio_snapshot) -> None:
    """None, not a copy of the raw figure, and not zero."""
    seed_portfolio_snapshot(positions=[stock(symbol="AAPL", shares=100, avg_cost=200.0)])
    stock_leg = client.get("/portfolio/positions", headers=OWNER).json()["groups"][0]["stock"]
    assert stock_leg["adjusted_cost_basis"] is None
    assert stock_leg["unrealized_pnl_adjusted"] is None


def test_unrealized_pnl_is_passed_through_not_recomputed(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(positions=[stock(symbol="AAPL", shares=100, avg_cost=200.0)])
    # the stock builder leaves unrealized_pnl None — it must surface as None, never 0
    stock_leg = client.get("/portfolio/positions", headers=OWNER).json()["groups"][0]["stock"]
    assert stock_leg["unrealized_pnl"] is None


def test_moneyness_is_none_when_underlying_price_unknown(client, seed_portfolio_snapshot) -> None:
    """No stock leg and no price_history row — the strike alone must not produce a guess."""
    seed_portfolio_snapshot(positions=[short_put(underlying="ZZZZ")])
    leg = client.get("/portfolio/positions", headers=OWNER).json()["groups"][0]["options"][0]
    assert leg["moneyness"] is None


def test_dte_is_none_never_zero_for_an_unknown_expiry(client, seed_portfolio_snapshot) -> None:
    pos = short_put()
    pos["expiry"] = None
    seed_portfolio_snapshot(positions=[pos])
    leg = client.get("/portfolio/positions", headers=OWNER).json()["groups"][0]["options"][0]
    assert leg["expiry"] is None
    assert leg["dte"] is None  # 0 would read as "expires today"


def test_moneyness_reads_the_stock_leg_price(client, seed_portfolio_snapshot) -> None:
    """Same group's stock price is the moneyness source — spot 176 vs put strike 190 is itm."""
    seed_portfolio_snapshot(
        positions=[stock(symbol="NVDA", market_price=176.0), short_put(strike=190.0)]
    )
    leg = client.get("/portfolio/positions", headers=OWNER).json()["groups"][0]["options"][0]
    assert leg["moneyness"] == "itm"


def test_moneyness_falls_back_to_price_history_without_a_stock_leg(
    client, seed_portfolio_snapshot
) -> None:
    from src.storage.db import session_scope
    from src.storage.models import PriceHistoryRow

    with session_scope() as s:
        s.add(
            PriceHistoryRow(
                symbol="MSFT",
                obs_date=date.today(),
                open=400.0,
                high=401.0,
                low=399.0,
                close=400.0,
                volume=1.0,
            )
        )
    seed_portfolio_snapshot(positions=[short_call(underlying="MSFT", strike=380.0)])
    leg = client.get("/portfolio/positions", headers=OWNER).json()["groups"][0]["options"][0]
    assert leg["moneyness"] == "itm"


def test_assignment_risk_uses_the_shared_predicate(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(
        positions=[
            short_call(delta=-0.75, dte=10),  # deep ITM, near expiry — at risk
            short_put(delta=-0.22, dte=45),  # not
        ]
    )
    options = client.get("/portfolio/positions", headers=OWNER).json()["groups"][0]["options"]
    by_risk = {o["assignment_risk"] for o in options}
    assert by_risk == {True, False}


def test_the_empty_rung_is_an_empty_list_source_none(client) -> None:
    """An empty list plus source="none" is honest; plus source="monitor" it would be a
    claim that the account holds nothing."""
    body = client.get("/portfolio/positions", headers=OWNER).json()
    assert body["source"] == "none"
    assert body["groups"] == []
    assert body["degraded"] is True


def test_a_non_owner_is_refused(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/portfolio/positions", headers=OWNER).status_code == 403


def test_delta_source_rides_alongside_delta(client, seed_portfolio_snapshot) -> None:
    pos = short_put()
    pos["delta"] = -0.22
    seed_portfolio_snapshot(positions=[pos])
    leg = client.get("/portfolio/positions", headers=OWNER).json()["groups"][0]["options"][0]
    assert leg["delta"] == -0.22
    assert leg["delta_source"] == "ibkr"
