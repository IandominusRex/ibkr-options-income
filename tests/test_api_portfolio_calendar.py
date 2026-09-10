"""GET /portfolio/calendar — option expiries grouped by date, with consequences.

The consequence table (Task 2.4's exact spec): an ITM short put is `assigned`; an
ITM short call is `called_away` only when the stock is held to deliver, else
`assigned`; any short OTM/ATM is `expires_worthless`; unknown moneyness is
`unknown` — a real value, never a default to `expires_worthless`.
"""

from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import OWNER, long_put, short_call, short_put, stock


def _day(offset: int) -> date:
    return date.today() + timedelta(days=offset)


def test_an_itm_short_put_maps_to_assigned(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(
        positions=[
            stock(symbol="NVDA", market_price=176.0),
            short_put(strike=190.0, underlying="NVDA"),
        ]
    )
    day = client.get("/portfolio/calendar", headers=OWNER).json()["days"][0]
    assert day["entries"][0]["consequence"] == "assigned"


def test_an_itm_short_call_with_stock_held_maps_to_called_away(
    client, seed_portfolio_snapshot
) -> None:
    seed_portfolio_snapshot(
        positions=[
            stock(symbol="NVDA", market_price=210.0),
            short_call(strike=200.0, underlying="NVDA"),
        ]
    )
    day = client.get("/portfolio/calendar", headers=OWNER).json()["days"][0]
    assert day["entries"][0]["consequence"] == "called_away"


def test_an_itm_short_call_without_stock_held_maps_to_assigned(
    client, seed_portfolio_snapshot
) -> None:
    """A naked short call assignment is a short stock position, not a call-away."""
    from src.storage.db import session_scope
    from src.storage.models import PriceHistoryRow

    with session_scope() as s:
        s.add(
            PriceHistoryRow(
                symbol="NVDA",
                obs_date=date.today(),
                open=210.0,
                high=211.0,
                low=209.0,
                close=210.0,
                volume=1.0,
            )
        )
    seed_portfolio_snapshot(positions=[short_call(strike=200.0, underlying="NVDA")])
    day = client.get("/portfolio/calendar", headers=OWNER).json()["days"][0]
    assert day["entries"][0]["consequence"] == "assigned"


def test_an_otm_short_maps_to_expires_worthless(client, seed_portfolio_snapshot) -> None:
    # spot ABOVE the put's strike: the put is OTM, so expiry means nothing happens.
    seed_portfolio_snapshot(
        positions=[
            stock(symbol="NVDA", market_price=200.0),
            short_put(strike=190.0, underlying="NVDA"),
        ]
    )
    day = client.get("/portfolio/calendar", headers=OWNER).json()["days"][0]
    assert day["entries"][0]["consequence"] == "expires_worthless"


def test_an_otm_long_option_maps_to_expires_worthless(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(
        positions=[stock(symbol="AAPL", market_price=150.0), long_put(strike=90.0)]
    )
    day = client.get("/portfolio/calendar", headers=OWNER).json()["days"][0]
    assert day["entries"][0]["consequence"] == "expires_worthless"
    assert day["entries"][0]["short"] is False


def test_unknown_moneyness_maps_to_unknown_not_expires_worthless(
    client, seed_portfolio_snapshot
) -> None:
    seed_portfolio_snapshot(positions=[short_put(underlying="ZZZZ")])  # no price source
    day = client.get("/portfolio/calendar", headers=OWNER).json()["days"][0]
    assert day["entries"][0]["consequence"] == "unknown"


def test_entries_group_by_expiry_and_days_order_nearest_first(
    client, seed_portfolio_snapshot
) -> None:
    seed_portfolio_snapshot(
        positions=[
            stock(symbol="NVDA", market_price=176.0),
            short_put(strike=190.0, underlying="NVDA", expiry=_day(30)),
            short_call(strike=200.0, underlying="NVDA", expiry=_day(7)),
        ]
    )
    body = client.get("/portfolio/calendar", headers=OWNER).json()
    assert [d["dte"] for d in body["days"]] == sorted(d["dte"] for d in body["days"])
    assert body["days"][0]["dte"] == 7
    assert len(body["days"][0]["entries"]) == 1
    assert len(body["days"][1]["entries"]) == 1


def test_horizon_days_excludes_far_expiries(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(
        positions=[
            stock(symbol="NVDA", market_price=176.0),
            short_put(strike=190.0, underlying="NVDA", expiry=_day(30)),
        ]
    )
    body = client.get("/portfolio/calendar?horizon_days=7", headers=OWNER).json()
    assert body["days"] == []
    assert body["horizon_days"] == 7


def test_horizon_days_caps_at_365(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(positions=[])
    r = client.get("/portfolio/calendar?horizon_days=9999", headers=OWNER)
    assert r.status_code == 422


def test_the_empty_rung_is_an_empty_list_source_none(client) -> None:
    body = client.get("/portfolio/calendar", headers=OWNER).json()
    assert body["source"] == "none"
    assert body["days"] == []
    assert body["degraded"] is True


def test_a_non_owner_is_refused(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/portfolio/calendar", headers=OWNER).status_code == 403


def test_assignment_risk_flags_ride_on_calendar_entries(client, seed_portfolio_snapshot) -> None:
    seed_portfolio_snapshot(
        positions=[
            stock(symbol="NVDA", market_price=176.0),
            short_put(strike=190.0, delta=-0.75, dte=10, underlying="NVDA"),
        ]
    )
    day = client.get("/portfolio/calendar", headers=OWNER).json()["days"][0]
    assert day["entries"][0]["assignment_risk"] is True
    assert day["entries"][0]["moneyness"] == "itm"
