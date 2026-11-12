"""The ITM put roll-down rule and the roll noise fixes (operator ruling 2026-11-12).

A deep in-the-money roll is worth sending only for a positive credit AND a lower strike that cuts
the assignment cost (new strike minus the net credit) by ``roll.csp.itm_min_basis_drop_pct``.
The roll constructor and the Rules Engine read the same rule.
"""

from __future__ import annotations

from src.common.config import RollCfg, RollCspCfg
from src.common.schemas import RollAlert
from tests.test_roll_evaluate import _evaluate, _pos, wired  # noqa: F401 — fixture reuse
from tests.test_rolling_construct import _W1, _build, _ctx, q

RULE = RollCfg(csp=RollCspCfg(itm_min_basis_drop_pct=1.0))  # old 335 -> cost cap 331.65


def test_an_itm_put_never_rolls_at_the_same_strike() -> None:
    cand, rej = _build(_ctx(), [q(335.0, _W1, 6.40, -0.58)], RULE)  # spot 325: ITM
    assert cand is None and rej.get("not_rolled_down") == 1


def test_an_itm_put_rolls_down_when_the_cost_falls_enough() -> None:
    quotes = [q(335.0, _W1, 6.40, -0.58), q(332.5, _W1, 6.10, -0.55), q(330.0, _W1, 6.20, -0.50)]
    cand, _ = _build(_ctx(), quotes, RULE)
    assert cand is not None and cand.strike == 330.0  # cost 329.80, under the 331.65 cap
    assert cand.roll_from is not None and cand.roll_from.itm_at_proposal


def test_a_small_roll_down_that_barely_moves_the_cost_is_refused() -> None:
    cand, rej = _build(_ctx(), [q(332.5, _W1, 6.10, -0.55)], RULE)  # cost 332.40 > 331.65
    assert cand is None and rej.get("not_rolled_down") == 1


def test_an_otm_breach_keeps_the_old_rule() -> None:
    cand, _ = _build(_ctx(spot=336.0), [q(335.0, _W1, 6.40, -0.58)], RULE)
    assert cand is not None and cand.strike == 335.0
    assert cand.roll_from is not None and not cand.roll_from.itm_at_proposal


def test_the_rules_engine_refuses_an_itm_roll_that_does_not_roll_down() -> None:
    from tests.test_risk_engine_roll import _reasons, _roll, roll_from

    itm = roll_from().model_copy(update={"itm_at_proposal": True})  # old strike 150
    assert "roll_not_rolled_down" in _reasons(_roll(strike=150.0, premium=0.40, roll_from=itm))
    assert "roll_not_rolled_down" not in _reasons(_roll(strike=145.0, premium=0.20, roll_from=itm))
    assert "roll_not_rolled_down" not in _reasons(_roll(strike=150.0, premium=0.40))


async def test_three_unfilled_rolls_today_fall_back_to_the_no_roll_answer(
    wired,  # noqa: F811
    db,
    monkeypatch,
) -> None:
    import src.execution.roll_pipeline as rp
    from src.common.config import get_config
    from src.storage.models import ApprovalRow, OrderRow

    # the fixture's roll is same-strike on an ITM put: switch the roll-down rule off here
    monkeypatch.setattr(rp.get_config().roll.csp, "itm_min_basis_drop_pct", None)
    monkeypatch.setattr(get_config().roll.csp, "itm_min_basis_drop_pct", None)
    if True:
        _, approval_id = await _evaluate()
        assert approval_id is not None
        with db() as s:
            row = s.get(ApprovalRow, approval_id)
            row.status = "approved"
            for order in s.query(OrderRow).filter_by(approval_id=approval_id):
                s.delete(order)
            s.flush()
            for i in range(3):
                appr = (
                    row
                    if i == 0
                    else ApprovalRow(
                        candidate_id=row.candidate_id,
                        status="approved",
                        snapshot=row.snapshot,
                        chat_id=row.chat_id,
                        expires_at=row.expires_at,
                    )
                )
                s.add(appr)
                s.flush()
                s.add(
                    OrderRow(
                        candidate_id="x",
                        approval_id=appr.id,
                        state="cancelled",
                        snapshot=row.snapshot,
                    )
                )
            s.commit()
        decision, again = await _evaluate()
        assert decision.action == "assign" and again is None
        assert "roll_unfilled_x3_today" in decision.reason


async def test_info_alerts_a_decision_card_covers_are_not_sent(db) -> None:
    from unittest.mock import AsyncMock, patch

    from src.common.config import get_config
    from src.monitor import intraday
    from tests.test_monitor_roll_eval import _pos as mpos
    from tests.test_monitor_roll_eval import _quote

    pos, quote = mpos(), _quote(95.0)  # strike 100, spot 95, 5 days: the roll policy acts
    alerts = [
        RollAlert(position_symbol=pos.symbol, underlying="AAPL", trigger=t, detail=t)
        for t in ("strike_breach", "delta_drift", "iv_spike")
    ]
    bot = AsyncMock()
    with (
        patch.object(intraday, "_alert_window_open", return_value=True),
        patch.object(intraday, "_review_send_persist", new=AsyncMock()) as send,
    ):
        await intraday.fire_alerts(alerts, pos, quote, bot, "1", get_config(), None)
    (fresh,) = send.await_args.args[:1]
    assert [a.trigger for a in fresh] == ["iv_spike"]
