from __future__ import annotations

from datetime import UTC, date, datetime

import src.spreads.notify as notify
from src.common.schemas import GexLevels, SpreadEntryContext, SpreadPosition
from src.spreads.notify import SpreadsNotifier, fmt_entry, fmt_eod, fmt_exit, fmt_map

NOW = datetime(2026, 10, 7, 13, 45, tzinfo=UTC)


def test_formats_carry_mode_and_numbers() -> None:
    lv = GexLevels(
        as_of=NOW,
        spot=690.12,
        net_gex=2.5e9,
        regime="positive",
        flip=676.0,
        call_wall=700.0,
        put_wall=680.0,
        expected_move=5.8,
    )
    m = fmt_map(lv, "shadow")
    assert (
        m.startswith("[SHADOW]")
        and "690.12" in m
        and "positive" in m
        and "680" in m
        and "±5.80" in m
    )
    pos = SpreadPosition(
        spread_id="s1",
        mode="paper",
        side="put",
        expiry=date(2026, 10, 7),
        short_strike=679,
        long_strike=674,
        width=5,
        contracts=1,
        entry_credit=0.57,
        opened_at=NOW,
    )
    e = fmt_entry(pos, "paper")
    assert e.startswith("[PAPER]") and "679/674" in e and "0.57" in e and "443" in e
    tags = SpreadEntryContext(
        trigger="move",
        move_em=0.63,
        gap_pct=-0.004,
        gap_day=True,
        regime="negative",
        net_gex=-1e9,
        spot=690.12,
        minutes_after_open=14,
    )
    tagged = fmt_entry(pos, "paper", tags)
    assert tagged.startswith(e)
    assert (
        "NEGATIVE GAMMA" in tagged
        and "0.63× expected-move drop" in tagged
        and "gap -0.40%" in tagged
    )
    calm = tags.model_copy(update={"regime": "positive", "gap_day": False})
    assert "gamma positive" in fmt_entry(pos, "paper", calm) and "gap" not in fmt_entry(
        pos, "paper", calm
    )
    x = fmt_exit("s1", "profit_take", 0.32, 22.4, "paper")
    assert "profit_take" in x and "+$22.40" in x
    assert "-$61.30" in fmt_exit("s1", "stop_loss", 1.2, -61.3, "paper")
    assert "2 trade(s)" in fmt_eod(date(2026, 10, 7), "shadow", 2, -10.0, 0)


async def test_send_without_credentials_never_builds_a_bot(monkeypatch) -> None:
    def boom(*a, **k):
        raise AssertionError("Bot must not be constructed without credentials")

    monkeypatch.setattr(notify, "Bot", boom)
    await SpreadsNotifier("", "", "").send("hello")


async def test_send_posts_to_the_spreads_thread(monkeypatch) -> None:
    sent: list[dict] = []

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send_message(self, **kw):
            sent.append(kw)

    monkeypatch.setattr(notify, "Bot", FakeBot)
    await SpreadsNotifier("tok", "123", "77").send("hello")
    assert sent == [{"chat_id": "123", "text": "hello", "message_thread_id": 77}]
    assert SpreadsNotifier("tok", "123", "").thread_id is None
