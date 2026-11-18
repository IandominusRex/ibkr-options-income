"""Review fix 10: the capacity report shows the budget the system would actually allow, which is
the scaled one while the slow breaker is tripped."""

from __future__ import annotations

import scripts.capacity_report as cr
from src.common.schemas import AccountSnapshot


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=500_000.0,
        total_cash=300_000.0,
        buying_power=600_000.0,
        maintenance_margin=0.0,
        excess_liquidity=300_000.0,
    )


def test_the_report_resolves_caps_with_the_slow_breaker_fraction(monkeypatch) -> None:
    seen: dict[str, float] = {}
    real = cr.resolve_caps

    def spy(account, risk, **kw):
        seen["csp_fraction"] = kw.get("csp_fraction", 1.0)
        return real(account, risk, **kw)

    monkeypatch.setattr(cr, "resolve_caps", spy)
    monkeypatch.setattr(cr, "csp_budget_fraction", lambda: 0.5)
    cr.build_report(_account(), [], ["AAPL"], {"AAPL": 0.3}, {"AAPL": 200.0})
    assert seen["csp_fraction"] == 0.5
