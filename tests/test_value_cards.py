"""Part 6, Task 4: the value book's Telegram cards (pure) and the outbox that posts each once."""

from __future__ import annotations

import ast
import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from src.common import value_commands as vc
from src.value import cards, outbox
from src.value.store import (
    ValueAttributionRow,
    ValueBookStateRow,
    ValueEffectiveRow,
    ValueProposalRow,
    ValueReevaluationRow,
    value_session,
)

NOW = datetime(2026, 11, 2, 15, 0)


def _proposal(
    *,
    pid: int = 12,
    kind: str = "buy",
    symbol: str = "GOOGL",
    shares: float = 10.0,
    cause: str = "python",
    needs_tap: bool = True,
    status: str = "pending",
    reason: str = "tranche 1",
    price: float | None = 180.0,
    tranche: int | None = 1,
) -> ValueProposalRow:
    return ValueProposalRow(
        id=pid,
        kind=kind,
        symbol=symbol,
        list_name="quality_growth",
        shares=shares,
        price=price,
        cost_usd=shares * (price or 0.0),
        tranche=tranche,
        reason=reason,
        cause=cause,
        needs_tap=needs_tap,
        status=status,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=30),
    )


def _fp(p: ValueProposalRow) -> str:
    return vc.proposal_fingerprint(p.id, p.kind, p.symbol, p.shares, p.created_at)


def test_a_buy_card_names_the_release_it_may_cause() -> None:
    card = cards.proposal_card(
        _proposal(), release_closes=3, fair_value=240.0, mos=0.25, verdict_by="python", tranches=3
    )
    assert card.key == "proposal:12"
    assert "Buy 10 GOOGL (quality growth, tranche 1 of 3)" in card.text
    assert "close up to 3 of the wheel's cash-secured puts at breakeven or better" in card.text
    assert len(card.text) <= 3500


def test_a_tap_card_has_approve_and_reject_with_the_fingerprint() -> None:
    p = _proposal()
    card = cards.proposal_card(p, release_closes=3, fair_value=240.0, mos=0.25, verdict_by="python")
    assert card.buttons == (
        ("Approve", vc.callback_data("approve", 12, _fp(p))),
        ("Reject", vc.callback_data("reject", 12, _fp(p))),
    )
    assert all(len(data.encode()) <= 64 for _, data in card.buttons)


def test_an_auto_proposal_card_has_no_buttons() -> None:
    p = _proposal(needs_tap=False, status="approved")
    card = cards.proposal_card(p, release_closes=3, fair_value=240.0, mos=0.25, verdict_by="python")
    assert card.buttons == ()
    assert "Approved by the system" in card.text


def test_a_claude_sale_says_it_waits_for_you() -> None:
    p = _proposal(kind="sell", cause="claude", reason="claude_broken", tranche=None)
    card = cards.proposal_card(p, release_closes=3, fair_value=None, mos=None, verdict_by="claude")
    assert "Only Claude's number makes this sale; it waits for you" in card.text
    assert "Sell 10 GOOGL" in card.text
    assert "cash-secured puts" not in card.text  # a sale funds nothing
    assert len(card.buttons) == 2
    assert all("Claude" not in label for label, _ in card.buttons)


def test_unknown_numbers_read_n_a() -> None:
    card = cards.proposal_card(
        _proposal(price=None), release_closes=3, fair_value=None, mos=None, verdict_by="python"
    )
    assert "n/a" in card.text
    assert "$0.00" not in card.text and "0%" not in card.text.replace("10%", "")


def test_every_risk_reason_has_words() -> None:
    tree = ast.parse(Path("src/value/risk.py").read_text())
    codes = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "append"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "reasons"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    assert len(codes) >= 20, codes  # the parse found the gate's reasons
    assert codes <= set(cards.VALUE_REASON_LABELS), codes - set(cards.VALUE_REASON_LABELS)
    assert cards.reason_words("sleeve_exhausted") == cards.VALUE_REASON_LABELS["sleeve_exhausted"]
    assert cards.reason_words("something_new") == "something new"


def test_the_trim_card_lists_what_it_would_sell() -> None:
    episode = vc.trim_episode(100_000.0, NOW)
    state = {"high": 100_000.0, "value": 74_000.0, "episode": episode}
    card = cards.trim_card(state, [("GOOGL", 5.0), ("META", 2.0)])
    assert card.key == f"trim:{episode}"
    assert "down 26% from its high ($100,000 to $74,000)" in card.text
    assert "GOOGL: sell 5" in card.text and "META: sell 2" in card.text
    assert "nothing sells until the next check" in card.text
    assert card.buttons == (("Trim to half", vc.callback_data("trim", 0, episode)),)


def _reeval(**over) -> ValueReevaluationRow:
    base = dict(
        id=7,
        shadow_id=0,
        position_id=3,
        symbol="GOOGL",
        list_name="quality_growth",
        session=date(2026, 11, 2),
        last_session=date(2026, 11, 2),
        severity="major",
        triggers_json=json.dumps(
            [{"day": "2026-11-02", "kind": "move", "detail": "raw move -9.0%"}]
        ),
        plan_before_json=json.dumps({"stop": 150.0, "trail_floor": None}),
        plan_after_json=json.dumps({"stop": 162.5, "trail_floor": None}),
        verdict_at_entry="READY",
        ruleset_version="v4",
        ruleset_hash="be30d1eaa915",
        created_at=NOW,
    )
    return ValueReevaluationRow(**{**base, **over})


def test_a_major_reevaluation_card_shows_plan_before_and_after() -> None:
    card = cards.reevaluation_card(_reeval())
    assert card.key == "reeval:7"
    assert "GOOGL" in card.text and "raw move -9.0%" in card.text
    assert "$150.00" in card.text and "$162.50" in card.text
    assert card.buttons == ()


def _put_proposal(**over) -> int:
    p = _proposal(**over)
    p.id = None  # type: ignore[assignment]
    with value_session() as vs:
        vs.add(p)
        vs.flush()
        return p.id


def _cfg():
    from src.common.config import get_config

    return get_config().value


def test_the_outbox_posts_each_card_once(value_book_db) -> None:
    pid = _put_proposal()
    with value_session() as vs:
        vs.add(
            ValueEffectiveRow(
                symbol="GOOGL",
                list_name="quality_growth",
                as_of=date(2026, 11, 2),
                verdict="READY",
                decided_by="python",
                python_verdict="READY",
                fair_value=240.0,
                margin_of_safety=0.25,
                updated_at=NOW,
            )
        )
        vs.add(
            ValueAttributionRow(
                symbol="ZZZ", broker=5, wheel=0, value_filled=0, state="frozen", updated_at=NOW
            )
        )
        vs.add(
            ValueBookStateRow(
                key="high_water",
                value=json.dumps({"high": 100.0, "value": 70.0, "episode": "0123456789"}),
                updated_at=NOW,
            )
        )
        vs.add(_reeval(position_id=3))
    with value_session() as vs:
        due = outbox.due(vs, NOW, _cfg())
    keys = [c.key for c in due]
    assert set(keys) == {f"proposal:{pid}", "reeval:7", "trim:0123456789", "freeze:ZZZ"}
    assert "Fair value $240.00" in next(c for c in due if c.key.startswith("proposal")).text
    with value_session() as vs:
        outbox.mark_posted(vs, keys, NOW)
    with value_session() as vs:
        assert outbox.due(vs, NOW, _cfg()) == []
        state = json.loads(vs.get(ValueBookStateRow, "high_water").value)  # type: ignore[union-attr]
    assert state["episode"] == "0123456789" and state["trim_posted"]


def test_minor_reevaluations_wait_for_the_digest(value_book_db) -> None:
    with value_session() as vs:
        vs.add(_reeval(id=8, severity="minor"))
        vs.add(_reeval(id=9, shadow_id=5, position_id=None))  # a shadow entry's row: hypothetical
    with value_session() as vs:
        assert outbox.due(vs, NOW, _cfg()) == []


def test_send_cards_never_raises(monkeypatch) -> None:
    import telegram

    import src.value.notify as notify

    secrets = SimpleNamespace(
        telegram_bot_token="t", telegram_chat_id="1", telegram_thread_value="58"
    )
    monkeypatch.setattr(notify, "get_config", lambda: SimpleNamespace(secrets=secrets))
    sent_to: list[dict] = []

    class Boom:
        def __init__(self, token: str) -> None:
            pass

        async def __aenter__(self):
            raise RuntimeError("network down")

        async def __aexit__(self, *a) -> None:
            return None

    class Fine(Boom):
        async def __aenter__(self):
            return self

        async def send_message(self, **kw) -> None:
            sent_to.append(kw)

    card = cards.Card(
        key="trim:abc", text="hello", buttons=(("Trim to half", "vbook:t:0:0123456789"),)
    )
    monkeypatch.setattr(telegram, "Bot", Boom)
    assert asyncio.run(notify.send_cards([card])) == []
    monkeypatch.setattr(telegram, "Bot", Fine)
    assert asyncio.run(notify.send_cards([card])) == ["trim:abc"]
    assert sent_to[0]["message_thread_id"] == 58 and sent_to[0]["reply_markup"] is not None
