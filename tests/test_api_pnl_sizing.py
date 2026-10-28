"""GET /pnl/sizing - the sizing record's totals (web overhaul Part 3, Task 1).

A thin renderer over src/claude/eval/sizing_counterfactual.py::summarize, read behind the eval
fence exactly as GET /pnl/system reads the score report: nothing is recomputed here, and the
route offers nothing that could change a limit, a size or a weight.
"""

from __future__ import annotations

from datetime import date, datetime

from src.claude.eval.sizing_counterfactual import summarize
from src.storage.models import OrderRow, SizingActionRow
from tests.conftest import OWNER

DAY = date(2026, 10, 20)


def _row(
    sym: str,
    kind: str,
    *,
    sent: int,
    wanted: int = 2,
    day: date = DAY,
    resolved: bool = False,
    expiry_pnl: float = 0.0,
    rules_pnl: float | None = 0.0,
    exact: float | None = None,
    reason: str = "stopped",
) -> SizingActionRow:
    return SizingActionRow(
        created_at=datetime(2026, 10, 20, 15, 0),
        candidate_id=f"c-{sym}-{kind}",
        record_key=f"csp:{sym}:{kind}:{day}",
        underlying=sym,
        strategy="cash_secured_put",
        right="P",
        strike=35.0,
        expiry=date(2026, 11, 13),
        premium=2.0,
        kind=kind,
        regime="stressed",
        deterministic_contracts=wanted,
        sent_contracts=sent,
        reason=reason,
        action_day=day,
        resolved_at=datetime(2026, 11, 14) if resolved else None,
        shadow_pnl_expiry=expiry_pnl if resolved else None,
        shadow_pnl_rules=rules_pnl if resolved else None,
        realized_pnl_per_contract=exact,
    )


def test_requires_owner(client) -> None:
    assert client.get("/pnl/sizing").status_code == 401


def test_an_empty_record_is_an_empty_list_not_an_error(client, api_db) -> None:
    r = client.get("/pnl/sizing", headers=OWNER)
    assert r.status_code == 200
    assert r.json()["groups"] == [] and r.json()["since"] is None


def test_a_group_counts_every_row_and_values_only_the_resolved(client, api_db) -> None:
    with api_db() as s:
        s.add_all(
            [
                _row(
                    "ASTS", "scale_in_zone", sent=0, resolved=True, expiry_pnl=120.0, rules_pnl=80.0
                ),
                _row("NVDA", "scale_in_zone", sent=0),
            ]
        )
    (g,) = client.get("/pnl/sizing", headers=OWNER).json()["groups"]
    assert (g["key"], g["kind"], g["split"]) == (
        "scale_in_zone:never_sent",
        "scale_in_zone",
        "never_sent",
    )
    assert (g["count"], g["contracts_withheld"], g["resolved"], g["exact"]) == (2, 4, 1, 0)
    assert (g["pnl_expiry"], g["pnl_rules"], g["rules_missing"]) == (120.0, 80.0, 0)
    assert g["applied"] is None and g["unapplied"] is None


def test_a_row_that_traded_smaller_is_its_own_group_and_may_lack_a_rules_mark(
    client, api_db
) -> None:
    with api_db() as s:
        s.add(
            _row(
                "AMD",
                "loss_exit_cooldown",
                sent=1,
                resolved=True,
                expiry_pnl=-30.0,
                rules_pnl=None,
                exact=-15.0,
            )
        )
    (g,) = client.get("/pnl/sizing", headers=OWNER).json()["groups"]
    assert g["key"] == "loss_exit_cooldown:sent_smaller"
    assert (g["contracts_withheld"], g["exact"], g["rules_missing"]) == (1, 1, 1)
    assert (g["pnl_expiry"], g["pnl_rules"]) == (-30.0, 0.0)


def test_claudes_cuts_are_one_overrides_line_with_applied_and_unapplied_counts(
    client, api_db
) -> None:
    with api_db() as s:
        s.add_all(
            [
                _row("NVDA", "claude_cut", sent=1, wanted=3),
                _row("TSLA", "claude_cut_unapplied", sent=3, wanted=3, reason="Claude suggested 1"),
            ]
        )
    (g,) = client.get("/pnl/sizing", headers=OWNER).json()["groups"]
    assert (g["key"], g["kind"], g["split"]) == ("claude_overrides", "claude_cut", "overrides")
    assert (g["count"], g["applied"], g["unapplied"], g["contracts_withheld"]) == (2, 1, 1, 4)


def test_a_breakout_row_a_covered_call_replaced_is_counted_and_never_valued(client, api_db) -> None:
    with api_db() as s:
        s.add(
            OrderRow(
                candidate_id="cc1",
                state="filled",
                filled_qty=1.0,
                created_at=datetime(2026, 10, 20, 15, 0),
                snapshot={"underlying": "NVDA", "strategy": "covered_call"},
            )
        )
        s.add(_row("NVDA", "cc_breakout_floor", sent=0))
    (g,) = client.get("/pnl/sizing", headers=OWNER).json()["groups"]
    assert (g["key"], g["split"], g["count"]) == ("cc_breakout_floor:pushed_out", "pushed_out", 1)
    for field in (
        "contracts_withheld",
        "resolved",
        "exact",
        "pnl_expiry",
        "pnl_rules",
        "rules_missing",
    ):
        assert g[field] is None, field


def test_since_leaves_out_older_actions_and_is_echoed_back(client, api_db) -> None:
    with api_db() as s:
        s.add_all(
            [
                _row("OLD", "scale_in_zone", sent=0, day=date(2026, 10, 1)),
                _row("NEW", "scale_in_zone", sent=0),
            ]
        )
    body = client.get("/pnl/sizing?since=2026-10-15", headers=OWNER).json()
    assert body["since"] == "2026-10-15"
    assert [g["count"] for g in body["groups"]] == [1]
    assert client.get("/pnl/sizing?since=not-a-date", headers=OWNER).status_code == 422


def test_groups_come_back_in_a_stable_order(client, api_db) -> None:
    with api_db() as s:
        s.add_all(
            [
                _row("A", "scale_in_zone", sent=0),
                _row("B", "loss_exit_cooldown", sent=0),
            ]
        )
    keys = [g["key"] for g in client.get("/pnl/sizing", headers=OWNER).json()["groups"]]
    assert keys == ["loss_exit_cooldown:never_sent", "scale_in_zone:never_sent"]


def test_the_route_does_not_recompute_the_summary(client, api_db, monkeypatch) -> None:
    """If the record is wrong, it is fixed in sizing_counterfactual.py, not in a router."""
    calls: list[date] = []

    def spy(since: date):
        calls.append(since)
        return summarize(since)

    monkeypatch.setattr("src.api.routers.pnl.summarize_sizing", spy)
    client.get("/pnl/sizing", headers=OWNER)
    assert calls == [date.min]


def test_a_non_owner_is_refused(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/pnl/sizing", headers=OWNER).status_code == 403
