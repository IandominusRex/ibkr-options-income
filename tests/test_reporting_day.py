"""The day's executed trades and the month's realised calendar (web Home follow-ups)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.schemas import CloseReason
from src.reporting.day import SpreadDayInput, build_day_trades, build_month_calendar
from src.reporting.pnl import build_legs
from src.storage.models import (
    ApprovalRow,
    CampaignRow,
    CandidateRow,
    ClaudeReviewRow,
    FillRow,
    RollAlertRow,
)

DAY = date(2026, 10, 9)  # a Friday in the past, so nothing here depends on today's date
FAR = date(2099, 1, 15)  # an expiry that is never in the past: the leg stays open


def at(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    """Naive UTC, the way fills are stored. 14:00 UTC is 10:00 in New York."""
    return datetime(day.year, day.month, day.day, hour, minute)


@pytest.fixture()
def db(api_db):
    return api_db


def put_leg(
    db,
    cid: str,
    *,
    symbol: str = "AAPL",
    right: str = "P",
    strike: float = 180.0,
    expiry: date = FAR,
    strategy: str = "cash_secured_put",
    qty: float = 1,
    sold: tuple[float, datetime, float] | None = (2.35, at(14), 1.3),
    bought: tuple[float, datetime, float, str | None] | None = None,
    order_id: int = 1,
    buy_order_id: int | None = None,
) -> None:
    """Seed a candidate and its fills. `sold` = (price, when, commission); `bought` adds the
    close reason stamped on the buy-back fill."""
    with db() as s:
        s.add(
            CandidateRow(
                candidate_id=cid,
                run_id="run-1",
                strategy=strategy,
                underlying=symbol,
                right=right,
                strike=strike,
                expiry=expiry,
                payload={},
            )
        )
        if sold is not None:
            price, when, comm = sold
            s.add(
                FillRow(
                    order_id=order_id,
                    candidate_id=cid,
                    action="SELL",
                    filled_qty=qty,
                    avg_price=price,
                    commission=comm,
                    filled_at=when,
                )
            )
        if bought is not None:
            price, when, comm, reason = bought
            s.add(
                FillRow(
                    order_id=buy_order_id if buy_order_id is not None else order_id + 100,
                    candidate_id=cid,
                    action="BUY",
                    filled_qty=qty,
                    avg_price=price,
                    commission=comm,
                    close_reason=reason,
                    filled_at=when,
                )
            )


def day_trades(db, strategy="all", spreads=(), day=DAY):
    legs = build_legs(db)
    return build_day_trades(db, legs, list(spreads), day=day, strategy=strategy)


def by_key(trades, suffix: str):
    return {t.key: t for t in trades}[suffix]


# --- opened --------------------------------------------------------------------------------


def test_an_opened_put_carries_its_premium_commission_and_return(db) -> None:
    put_leg(db, "c1", expiry=date(2099, 1, 15))
    with db() as s:
        s.add(ApprovalRow(candidate_id="c1", status="approved"))
        s.add(
            ClaudeReviewRow(
                candidate_id="c1",
                recommendation="sell",
                payload={
                    "why_attractive": "IV rank 62.",
                    "risks": "Earnings inside.",
                    "summary": "Fine.",
                },
            )
        )
    [t] = day_trades(db)
    assert (t.action, t.kind, t.source) == ("opened", "csp", "wheel")
    assert (t.underlying, t.right, t.strike, t.contracts) == ("AAPL", "P", 180.0, 1)
    assert t.premium == pytest.approx(235.0)
    assert t.commissions == pytest.approx(1.3)
    assert t.capital == pytest.approx(18_000.0)
    assert t.roc_pct == pytest.approx(235 / 18_000 * 100)
    assert t.dte_at_open == (date(2099, 1, 15) - DAY).days
    assert t.annualized_pct == pytest.approx(t.roc_pct * 365 / t.dte_at_open)
    assert t.net_pnl is None and t.bought_back is None  # open: no result yet, never 0
    assert t.review is not None and t.review.why_attractive == "IV rank 62."
    assert t.approval_id is not None
    assert t.at == at(14).replace(tzinfo=UTC)


def test_a_trade_opened_on_another_day_is_not_listed(db) -> None:
    put_leg(db, "c1")
    assert day_trades(db, day=DAY + timedelta(days=1)) == []
    assert day_trades(db, day=DAY - timedelta(days=1)) == []


def test_the_new_york_day_decides_not_utc(db) -> None:
    # 02:00 UTC on the 10th is 22:00 on the 9th in New York.
    put_leg(db, "late", sold=(1.0, at(2, 0, DAY + timedelta(days=1)), 1.0))
    assert [t.key for t in day_trades(db, day=DAY)] == ["late:opened"]
    assert day_trades(db, day=DAY + timedelta(days=1)) == []


# --- closed --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason, headline, rule",
    [
        ("profit_take", "Closed for a profit", "enough of its premium is kept"),
        ("loss_exit", "Closed at the loss limit", "loss limit"),
        ("defensive", "Closed defensively", "you chose it"),
        ("manual", "Closed outside the system", "reconciled"),
        ("capital_release", "Closed to fund a value-book buy", "breakeven or better"),
        (None, "reason was not recorded", "predates"),
    ],
)
def test_a_buy_back_says_why_in_the_words_of_its_close_reason(db, reason, headline, rule) -> None:
    put_leg(
        db,
        "c1",
        sold=(2.35, at(14, 0, DAY - timedelta(days=20)), 1.3),
        bought=(0.62, at(15), 1.3, reason),
    )
    [t] = day_trades(db)
    assert (t.action, t.how) == ("closed", "bought_back")
    assert headline in (t.reason or "")
    rule_fact = next(f for f in t.facts if f.label == "Rule")
    assert rule in rule_fact.text and rule_fact.source == "system"


def test_every_close_reason_but_a_roll_has_words_of_its_own() -> None:
    """A roll is its own card; every other stamped reason must say why in words. A reason added to
    CloseReason without words here would read "the reason was not recorded", which is false."""
    from src.reporting.day import _CLOSE_RULE

    assert set(CloseReason) - set(_CLOSE_RULE) == {CloseReason.ROLL}


def test_a_closed_card_shows_the_whole_trade_so_its_stub_can_sum(db) -> None:
    put_leg(
        db,
        "c1",
        sold=(2.35, at(14, 0, DAY - timedelta(days=20)), 1.3),
        bought=(0.62, at(15), 1.3, "profit_take"),
    )
    [t] = day_trades(db)
    assert t.premium == pytest.approx(235.0)
    assert t.bought_back == pytest.approx(62.0)
    assert t.commissions == pytest.approx(2.6)
    assert t.net_pnl == pytest.approx(235 - 62 - 2.6)
    assert t.pct_kept == pytest.approx((235 - 62) / 235 * 100)
    result = next(f for f in t.facts if f.label == "Result").text
    assert "Sold at $2.35 a share" in result and "bought back at $0.62" in result
    assert "74% of the premium kept" in result


def test_a_loss_says_the_buy_back_cost_more_not_a_negative_percent(db) -> None:
    put_leg(
        db,
        "c1",
        sold=(1.41, at(14, 0, DAY - timedelta(days=20)), 1.0),
        bought=(2.95, at(15), 1.0, "loss_exit"),
    )
    [t] = day_trades(db)
    result = next(f for f in t.facts if f.label == "Result").text
    assert "the buy-back cost 109% more than the premium collected" in result
    assert "-" not in result.replace("buy-back", "")
    assert t.net_pnl is not None and t.net_pnl < 0 and t.pct_kept == pytest.approx(-109.2, abs=0.1)


def test_an_expiry_on_the_day_is_listed_as_closed_expired(db) -> None:
    put_leg(db, "c1", expiry=DAY, sold=(1.0, at(14, 0, DAY - timedelta(days=7)), 1.0))
    [t] = day_trades(db)
    assert (t.action, t.how) == ("closed", "expired")
    assert t.net_pnl == pytest.approx(100 - 1.0)
    assert "kept the whole premium" in (t.reason or "")
    assert t.at == datetime(2026, 10, 9, 20, 0, tzinfo=UTC)  # 16:00 New York


def test_an_assignment_names_the_shares_and_the_adjusted_cost(db) -> None:
    put_leg(db, "c1", expiry=DAY, sold=(2.0, at(14, 0, DAY - timedelta(days=7)), 1.0))
    with db() as s:
        s.add(
            CampaignRow(
                campaign_id="AAPL-1",
                symbol="AAPL",
                status="open",
                opened_date=DAY - timedelta(days=7),
                leg_candidate_ids=["c1"],
                assigned=True,
                payload={},
            )
        )
    [t] = day_trades(db)
    assert t.how == "assigned"
    assert "you bought 100 shares at $180" in (t.reason or "")
    assert "adjusted cost on those shares is $178" in t.facts[0].text


def test_a_call_that_is_assigned_is_called_away(db) -> None:
    put_leg(
        db, "c1", right="C", strike=72.0, strategy="covered_call", expiry=DAY,
        sold=(0.64, at(14, 0, DAY - timedelta(days=7)), 1.0),
    )  # fmt: skip
    with db() as s:
        s.add(
            CampaignRow(
                campaign_id="KO-1", symbol="AAPL", status="open",
                opened_date=DAY - timedelta(days=7), leg_candidate_ids=["c1"],
                assigned=True, payload={},
            )
        )  # fmt: skip
    [t] = day_trades(db)
    assert t.how == "called_away" and "100 shares were sold at $72" in (t.reason or "")


def test_an_open_trade_closed_on_a_later_day_is_still_listed_as_opened_on_its_day(db) -> None:
    put_leg(
        db,
        "c1",
        sold=(2.0, at(14), 1.0),
        bought=(0.5, at(15, 0, DAY + timedelta(days=3)), 1.0, "profit_take"),
    )
    assert [t.action for t in day_trades(db)] == ["opened"]
    assert [t.action for t in day_trades(db, day=DAY + timedelta(days=3))] == ["closed"]


def test_opened_and_closed_the_same_day_gives_two_cards_newest_first(db) -> None:
    put_leg(db, "c1", sold=(2.0, at(14), 1.0), bought=(0.5, at(17), 1.0, "profit_take"))
    assert [t.action for t in day_trades(db)] == ["closed", "opened"]


# --- rolled --------------------------------------------------------------------------------


def seed_roll(db, *, with_new_leg: bool = True, decision: bool = True, claude: bool = True):
    """NVDA $160 call (sold 3 weeks ago) rolled today to the $165 call: one combo order (id 77)
    carries the new SELL and the old BUY, which is how the cards pair them."""
    old_expiry, new_expiry = date(2026, 10, 16), date(2026, 11, 20)
    put_leg(
        db, "old", symbol="NVDA", right="C", strike=160.0, strategy="covered_call",
        expiry=old_expiry, sold=(2.50, at(14, 0, DAY - timedelta(days=21)), 1.0),
        bought=(3.10, at(15), 1.0, CloseReason.ROLL.value), buy_order_id=77,
    )  # fmt: skip
    if with_new_leg:
        put_leg(
            db, "new", symbol="NVDA", right="C", strike=165.0, strategy="roll",
            expiry=new_expiry, sold=(2.80, at(15), 1.0), order_id=77,
        )  # fmt: skip
        with db() as s:
            s.add(ApprovalRow(candidate_id="new", status="approved"))
    with db() as s:
        approval_id = s.query(ApprovalRow.id).filter_by(candidate_id="new").scalar()
        if decision:
            s.add(
                RollAlertRow(
                    position_symbol="NVDA  261016C00160000",
                    underlying="NVDA",
                    trigger="roll_decision",
                    detail="roll:credit_roll",
                    created_at=at(14, 30),
                    payload={
                        "trigger": "strike_breach",
                        "approval_id": approval_id,
                        "decision": {
                            "action": "roll",
                            "reason": "credit_roll",
                            "detail": "Roll up and out for a $0.30/sh net credit.",
                        },
                    },
                )
            )
        if claude:
            s.add(
                RollAlertRow(
                    position_symbol="NVDA  261016C00160000",
                    underlying="NVDA",
                    trigger="strike_breach",
                    detail="breached",
                    claude_recommendation="roll",
                    created_at=at(14, 10),
                    payload={},
                )
            )


def test_a_roll_is_one_card_with_the_old_leg_the_new_leg_and_the_reason(db) -> None:
    seed_roll(db)
    trades = day_trades(db)
    assert sorted(t.action for t in trades) == ["rolled"]  # the new leg is not repeated as opened
    [t] = trades
    assert (t.how, t.kind, t.underlying, t.strike) == ("rolled", "cc", "NVDA", 160.0)
    assert t.rolled_to is not None
    assert (t.rolled_to.strike, t.rolled_to.expiry) == (165.0, date(2026, 11, 20))
    assert t.rolled_to.premium == pytest.approx(280.0)
    assert "Rolled to the $165 call expiring Nov 20" in (t.reason or "")
    # the closed leg's whole result, before the new leg: 250 collected, 310 bought back, 2 fees
    assert (t.premium, t.bought_back, t.commissions) == (
        pytest.approx(250.0),
        pytest.approx(310.0),
        pytest.approx(2.0),
    )
    assert t.net_pnl == pytest.approx(250 - 310 - 2)
    assert t.approval_id is not None


def test_a_rolled_card_explains_the_trigger_the_terms_and_claudes_view(db) -> None:
    seed_roll(db)
    [t] = day_trades(db)
    facts = {f.label: f for f in t.facts}
    why = facts["Why it was rolled"]
    assert "Trigger: strike breached." in why.text
    assert "Roll up and out for a $0.30/sh net credit." in why.text
    assert why.source == "system"
    terms = facts["Roll terms"].text
    assert "Bought back the $160 call at $3.10 a share" in terms
    assert "sold the $165 call expiring Nov 20 at $2.80" in terms
    assert "net debit of $0.30 a share" in terms
    view = facts["Claude's view"]
    assert view.source == "claude" and "roll" in view.text


def test_a_roll_without_a_logged_decision_says_so_instead_of_inventing_one(db) -> None:
    seed_roll(db, decision=False, claude=False)
    [t] = day_trades(db)
    labels = [f.label for f in t.facts]
    assert "Claude's view" not in labels
    why = next(f for f in t.facts if f.label == "Why it was rolled")
    assert "was not found" in why.text


def test_a_roll_whose_new_leg_is_missing_still_shows_the_buy_back(db) -> None:
    seed_roll(db, with_new_leg=False)
    [t] = day_trades(db)
    assert t.action == "rolled" and t.rolled_to is None
    assert "new leg is not on record" in (t.reason or "")


def test_a_roll_counts_under_the_side_it_rolls(db) -> None:
    seed_roll(db)
    assert len(day_trades(db, strategy="cc")) == 1
    assert day_trades(db, strategy="csp") == []
    assert day_trades(db, strategy="spread") == []


# --- spreads -------------------------------------------------------------------------------


def spread(**over) -> SpreadDayInput:
    base = dict(
        spread_id="s1", underlying="SPY", side="put", expiry=DAY, short_strike=580.0,
        long_strike=575.0, width=5.0, contracts_opened=2, contracts_open=2, entry_credit=0.84,
        entry_commission=2.6, opened_at=at(14), closed_at=None, exit_debit=None,
        exit_commission=0.0, exit_reason=None, status="open", realized_pnl_usd=None,
    )  # fmt: skip
    base.update(over)
    return SpreadDayInput(**base)


def test_a_spread_opened_today_is_a_card_with_its_risk_and_return(db) -> None:
    [t] = day_trades(db, spreads=[spread()])
    assert (t.action, t.kind, t.source, t.right) == ("opened", "spread", "spreads", "P")
    assert (t.strike, t.long_strike) == (580.0, 575.0)
    assert t.premium == pytest.approx(168.0)
    assert t.capital == pytest.approx((5 - 0.84) * 100 * 2)
    assert t.roc_pct == pytest.approx(168 / 832 * 100)
    assert t.commissions == pytest.approx(2.6)


def test_a_closed_spread_names_its_exit_rule_and_its_result(db) -> None:
    closed = spread(
        status="closed", contracts_open=0, closed_at=at(18), exit_debit=0.20,
        exit_commission=2.6, exit_reason="profit_take", realized_pnl_usd=123.6,
    )  # fmt: skip
    trades = day_trades(db, spreads=[closed])
    assert sorted(t.action for t in trades) == ["closed", "opened"]
    t = by_key(trades, "spread:s1:closed")
    assert t.how == "bought_back" and "profit" in (t.reason or "")
    assert t.net_pnl == pytest.approx(123.6)
    assert t.bought_back == pytest.approx(40.0)
    assert t.pct_kept == pytest.approx((168 - 40) / 168 * 100)
    assert t.commissions == pytest.approx(5.2)


def test_a_spread_that_expired_is_closed_as_expired(db) -> None:
    done = spread(
        status="closed", contracts_open=0, closed_at=at(20), exit_debit=0.0,
        exit_reason="expire_worthless", realized_pnl_usd=165.4,
    )  # fmt: skip
    t = by_key(day_trades(db, spreads=[done]), "spread:s1:closed")
    assert t.how == "expired" and "whole credit" in (t.reason or "")


def test_spreads_follow_the_strategy_scope(db) -> None:
    assert len(day_trades(db, strategy="spread", spreads=[spread()])) == 1
    assert day_trades(db, strategy="csp", spreads=[spread()]) == []


# --- the calendar --------------------------------------------------------------------------


def test_each_day_is_the_net_of_what_closed_after_commissions(db) -> None:
    put_leg(
        db,
        "a",
        sold=(2.0, at(14, 0, DAY - timedelta(days=9)), 1.0),
        bought=(0.5, at(15), 1.0, "profit_take"),
    )
    put_leg(
        db,
        "b",
        sold=(1.0, at(14, 0, DAY - timedelta(days=9)), 1.0),
        bought=(2.0, at(16), 1.0, "loss_exit"),
    )
    put_leg(
        db,
        "c",
        sold=(1.0, at(14, 0, DAY - timedelta(days=3)), 1.0),
        bought=(0.2, at(15, 0, DAY + timedelta(days=1)), 1.0, "profit_take"),
    )
    cal = build_month_calendar(build_legs(db), [], month=DAY, strategy="all")
    assert [d.date for d in cal.days] == [DAY, DAY + timedelta(days=1)]
    first, second = cal.days
    assert first.realized == pytest.approx((200 - 50 - 2) + (100 - 200 - 2))
    assert first.n_closed == 2
    assert second.realized == pytest.approx(100 - 20 - 2)
    assert cal.total == pytest.approx(first.realized + second.realized)
    assert cal.n_closed == 3 and cal.complete is True


def test_an_open_leg_contributes_nothing_to_the_calendar(db) -> None:
    put_leg(db, "open")
    cal = build_month_calendar(build_legs(db), [], month=DAY, strategy="all")
    assert cal.days == [] and cal.total == 0.0 and cal.n_closed == 0


def test_only_the_asked_month_is_counted(db) -> None:
    put_leg(
        db,
        "a",
        sold=(2.0, at(14, 0, DAY - timedelta(days=20)), 1.0),
        bought=(0.5, at(15), 1.0, "profit_take"),
    )
    nov = build_month_calendar(build_legs(db), [], month=date(2026, 11, 1), strategy="all")
    assert nov.days == []
    sep_edge = build_month_calendar(build_legs(db), [], month=date(2026, 9, 1), strategy="all")
    assert sep_edge.days == []


def test_a_missing_commission_marks_the_day_incomplete(db) -> None:
    put_leg(
        db,
        "a",
        sold=(2.0, at(14, 0, DAY - timedelta(days=9)), 1.0),
        bought=(0.5, at(15), 1.0, "profit_take"),
    )
    with db() as s:
        s.query(FillRow).filter_by(candidate_id="a", action="BUY").update({"commission": None})
    cal = build_month_calendar(build_legs(db), [], month=DAY, strategy="all")
    assert cal.days[0].complete is False and cal.complete is False


def test_the_calendar_includes_closed_spreads_and_follows_scope(db) -> None:
    closed = spread(
        status="closed", contracts_open=0, closed_at=at(18), exit_debit=0.2,
        exit_commission=2.6, exit_reason="profit_take", realized_pnl_usd=123.6,
    )  # fmt: skip
    put_leg(
        db,
        "a",
        sold=(2.0, at(14, 0, DAY - timedelta(days=9)), 1.0),
        bought=(0.5, at(15), 1.0, "profit_take"),
    )
    allc = build_month_calendar(build_legs(db), [closed], month=DAY, strategy="all")
    assert allc.days[0].realized == pytest.approx(148 + 123.6)
    assert build_month_calendar(
        build_legs(db), [closed], month=DAY, strategy="spread"
    ).total == pytest.approx(123.6)
    assert build_month_calendar(
        build_legs(db), [closed], month=DAY, strategy="csp"
    ).total == pytest.approx(148)


def test_an_expiry_counts_on_its_expiry_date(db) -> None:
    put_leg(db, "a", expiry=DAY, sold=(1.0, at(14, 0, DAY - timedelta(days=7)), 1.0))
    cal = build_month_calendar(build_legs(db), [], month=DAY, strategy="all")
    assert [d.date for d in cal.days] == [DAY] and cal.days[0].realized == pytest.approx(99.0)


# --- who approved it (web overhaul Part 2, Task 2) ------------------------------------------


def test_an_opened_card_says_who_approved_it(db) -> None:
    put_leg(db, "c1")
    with db() as s:
        s.add(ApprovalRow(candidate_id="c1", status="approved", decided_by="system"))
    [t] = day_trades(db)
    assert t.decided_by == "system"


def test_an_unrecorded_decider_stays_unknown(db) -> None:
    put_leg(db, "c1")
    with db() as s:
        s.add(ApprovalRow(candidate_id="c1", status="approved"))
    [t] = day_trades(db)
    assert t.decided_by is None


def test_a_closed_card_never_borrows_the_opening_decision(db) -> None:
    put_leg(db, "c1", sold=(2.35, at(14), 1.3), bought=(0.5, at(17), 1.3, "profit_take"))
    with db() as s:
        s.add(ApprovalRow(candidate_id="c1", status="approved", decided_by="web"))
    trades = day_trades(db)
    assert by_key(trades, "c1:opened").decided_by == "web"
    assert by_key(trades, "c1:closed").decided_by is None


def test_a_rolled_card_says_who_approved_the_roll(db) -> None:
    seed_roll(db)
    with db() as s:
        s.query(ApprovalRow).filter_by(candidate_id="new").update({"decided_by": "system"})
    [t] = day_trades(db)
    assert t.decided_by == "system"
