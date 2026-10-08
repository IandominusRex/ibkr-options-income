from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from src.common.schemas import GexLevels, SpreadCandidate, SpreadEntryContext, SpreadVerdict

NOW = datetime(2026, 10, 7, 14, 30, tzinfo=UTC)
LATER = datetime(2026, 10, 7, 16, 0, tzinfo=UTC)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    import src.spreads.store as st

    monkeypatch.setattr(st, "_engine", None)
    monkeypatch.setattr(st, "_SessionLocal", None)
    monkeypatch.setattr(st, "_resolve_url", lambda: f"sqlite:///{tmp_path / 'spreads.db'}")
    st.init_spreads_db()
    return st


def cand(spread_id: str = "s1") -> SpreadCandidate:
    return SpreadCandidate(
        spread_id=spread_id,
        side="put",
        expiry=date(2026, 10, 7),
        short_strike=679.0,
        long_strike=674.0,
        width=5.0,
        short_con_id=111,
        long_con_id=222,
        credit_mid=0.61,
        credit_natural=0.56,
        short_delta=-0.12,
        spot=690.0,
        quote_time=NOW,
    )


def test_open_position_round_trips_and_counts_risk(store) -> None:
    pos = store.open_position(
        cand(), mode="shadow", contracts=1, credit=0.57, commission=1.30, now=NOW, perm_id=None
    )
    assert pos.entry_credit == 0.57 and pos.contracts == 1 and pos.short_con_id == 111
    assert [p.spread_id for p in store.open_positions("shadow")] == ["s1"]
    assert store.open_positions("paper") == []
    assert store.open_risk_usd("shadow") == pytest.approx((5.0 - 0.57) * 100)


# Review Focus 3 — partial closes pro-rate the entry commission and keep the rest open.
def test_partial_close_then_final_close(store) -> None:
    store.open_position(
        cand(), mode="paper", contracts=2, credit=0.60, commission=2.60, now=NOW, perm_id=9
    )
    first = store.close_position(
        "s1", contracts=1, debit=0.30, commission=1.30, reason="profit_take", now=LATER
    )
    assert first == pytest.approx(30.0 - 1.30 - 1.30)
    (still,) = store.open_positions("paper")
    assert still.contracts == 1
    second = store.close_position(
        "s1", contracts=1, debit=0.50, commission=1.30, reason="profit_take", now=LATER
    )
    assert second == pytest.approx(10.0 - 1.30 - 1.30)
    assert store.open_positions("paper") == []
    ((regime, reason, pnl),) = store.closed_results("paper")
    assert reason == "profit_take" and pnl == pytest.approx(34.8)
    with store.spreads_session() as s:
        row = s.query(store.SpreadPositionRow).one()
        assert row.exit_debit == pytest.approx(0.40) and row.status == "closed"


def test_day_stats_counts_trades_opened_that_et_day(store) -> None:
    store.open_position(
        cand("a"), mode="shadow", contracts=1, credit=0.6, commission=1.3, now=NOW, perm_id=None
    )
    store.open_position(
        cand("b"), mode="shadow", contracts=1, credit=0.6, commission=1.3, now=NOW, perm_id=None
    )
    store.close_position("a", contracts=1, debit=1.2, commission=1.3, reason="stop_loss", now=LATER)
    trades, realized = store.day_stats(date(2026, 10, 7), "shadow")
    assert trades == 2
    assert realized == pytest.approx(-60.0 - 1.3 - 1.3)
    assert store.day_stats(date(2026, 10, 8), "shadow") == (0, 0.0)
    assert store.sides_opened(date(2026, 10, 7), "shadow") == ["put", "put"]
    assert store.sides_opened(date(2026, 10, 8), "shadow") == []
    # The book's capital grows and shrinks with everything it has realized, per mode.
    assert store.realized_pnl_total("shadow") == pytest.approx(-60.0 - 1.3 - 1.3)
    assert store.realized_pnl_total("paper") == 0.0


def test_every_trade_is_logged_with_its_tags_hold_time_and_mae(store) -> None:
    tags = SpreadEntryContext(
        trigger="move",
        move_em=0.7,
        gap_pct=-0.004,
        gap_day=True,
        regime="negative",
        net_gex=-2e9,
        flip=700.0,
        expected_move=5.8,
        day_em=6.0,
        spot=690.0,
        minutes_after_open=12,
    )
    store.open_position(
        cand(),
        mode="shadow",
        contracts=2,
        credit=0.60,
        commission=2.6,
        now=NOW,
        perm_id=None,
        context=tags,
    )
    store.note_mark("s1", 0.90)
    store.note_mark("s1", 0.70)  # a better mark never lowers the worst one
    store.close_position(
        "s1", contracts=2, debit=0.30, commission=2.6, reason="profit_take", now=LATER
    )
    (t,) = store.trade_log("shadow")
    assert (t.side, t.status, t.regime, t.trigger, t.gap_day, t.minutes_after_open) == (
        "put",
        "closed",
        "negative",
        "move",
        True,
        12,
    )
    assert t.move_em == pytest.approx(0.7) and t.gap_pct == pytest.approx(-0.004)
    assert t.hold_minutes == pytest.approx(90.0)
    assert t.mae_usd == pytest.approx((0.90 - 0.60) * 100 * 2)
    assert t.pnl_usd == pytest.approx((0.60 - 0.30) * 100 * 2 - 2.6 - 2.6)
    assert store.closed_results("shadow") == [("negative", "profit_take", pytest.approx(t.pnl_usd))]
    with store.spreads_session() as s:
        assert s.query(store.SpreadPositionRow).one().entry_context["net_gex"] == -2e9


def test_an_open_untagged_trade_is_logged_too(store) -> None:
    store.open_position(
        cand(), mode="paper", contracts=1, credit=0.6, commission=1.3, now=NOW, perm_id=7
    )
    (t,) = store.trade_log("paper")
    assert (t.status, t.regime, t.trigger) == ("open", "unknown", "always")
    assert t.hold_minutes is None and t.mae_usd is None and t.closed_at is None
    assert store.trade_log("shadow") == []


def test_first_map_em_is_the_days_yardstick(store) -> None:
    def lv(at: datetime, em: float | None) -> GexLevels:
        return GexLevels(as_of=at, spot=690.0, net_gex=1e9, regime="positive", expected_move=em)

    store.record_map(lv(NOW, None))
    store.record_map(lv(LATER, 5.8))
    store.record_map(lv(LATER + timedelta(hours=1), 4.0))
    assert store.first_map_em(date(2026, 10, 7)) == pytest.approx(5.8)
    assert store.first_map_em(date(2026, 10, 8)) is None


def test_expiring_positions_are_tracked_separately(store) -> None:
    store.open_position(
        cand(), mode="shadow", contracts=1, credit=0.6, commission=1.3, now=NOW, perm_id=None
    )
    store.mark_expiring("s1")
    assert store.open_positions("shadow") == []
    assert [p.spread_id for p in store.expiring_positions("shadow")] == ["s1"]
    assert store.open_risk_usd("shadow") == pytest.approx(440.0)


def test_maps_candidates_and_orders_are_recorded(store) -> None:
    store.record_map(
        GexLevels(
            as_of=NOW, spot=690.0, net_gex=1e9, regime="positive", flip=675.0, expected_move=5.8
        )
    )
    store.record_candidate(
        cand(),
        SpreadVerdict(spread_id="s1", approved=False, reasons=["negative_gamma"]),
        "negative",
        NOW,
    )
    store.record_order(
        spread_id="s1",
        kind="open",
        order_ref="CS:s1",
        ib_order_id=7,
        perm_id=9001,
        filled_qty=0,
        price=None,
        commission=0.0,
        reason="not_filled",
        now=NOW,
    )
    with store.spreads_session() as s:
        assert s.query(store.GexMapRow).count() == 1
        assert s.query(store.SpreadCandidateRow).one().reasons == ["negative_gamma"]
        assert s.query(store.SpreadOrderRow).one().perm_id == 9001


def test_spreads_tables_never_share_the_trading_base() -> None:
    from src.spreads.store import SpreadsBase
    from src.storage.models import Base

    assert not set(SpreadsBase.metadata.tables) & set(Base.metadata.tables)


# Review minor — a spread the service can no longer close is settled by hand, not by editing SQL.
def test_spreads_resolve_settles_an_open_spread(store, monkeypatch, capsys) -> None:
    import scripts.spreads_resolve as resolve

    store.open_position(
        cand("gone"), mode="paper", contracts=2, credit=0.60, commission=2.6, now=NOW, perm_id=1
    )
    assert store.held_contracts("gone") == 2 and store.held_contracts("nope") is None
    monkeypatch.setattr(
        "sys.argv",
        ["spreads_resolve", "--spread-id", "gone", "--debit", "0.10", "--commission", "2.6"],
    )
    resolve.main()
    assert store.open_positions("paper") == []
    ((_, reason, pnl),) = store.closed_results("paper")
    assert reason == "resolved_by_hand" and pnl == pytest.approx((0.60 - 0.10) * 200 - 2.6 - 2.6)
    assert "settled 2 contract(s)" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["spreads_resolve", "--spread-id", "gone", "--debit", "0"])
    with pytest.raises(SystemExit):
        resolve.main()
