from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

import src.spreads.notify as notify
from src.common.schemas import (
    GexLevels,
    SpreadBriefResult,
    SpreadDayPlan,
    SpreadEntryContext,
    SpreadLlmCall,
    SpreadMarketSnapshot,
    SpreadPosition,
)
from src.spreads.notify import (
    DayCard,
    SpreadsNotifier,
    fmt_alert,
    fmt_day_card,
    fmt_entry,
    fmt_eod,
    fmt_exit,
    status_nothing_to_sell,
)

NOW = datetime(2026, 10, 7, 13, 45, tzinfo=UTC)
LV = GexLevels(
    as_of=NOW,
    spot=690.12,
    net_gex=2.5e9,
    regime="positive",
    flip=676.0,
    call_wall=700.0,
    put_wall=680.0,
    expected_move=5.8,
)
POS = SpreadPosition(
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


def _brief(plan: SpreadDayPlan | None, error: str = "") -> SpreadBriefResult:
    call = SpreadLlmCall.model_construct(error=error)
    return SpreadBriefResult.model_construct(
        plan=plan, market=SpreadMarketSnapshot.model_construct(), call=call
    )


def test_the_day_card_shows_levels_plan_and_status_as_separate_lines() -> None:
    plan = SpreadDayPlan(
        bias="neutral",
        risk_flags=["Spot 0.2% above the flip", "CPI tomorrow <b>"],
        skip_conditions=["SPY < 775.88 (puts)"],
        preferred_distance=">= 1.2x EM",
        summary="Quiet tape; credits thin.",
    )
    card = DayCard(
        day=date(2026, 10, 7),
        mode="paper",
        levels=LV,
        plan=_brief(plan),
        status="put side armed, no trade — nearest 679/674 pays $0.08",
        status_at=NOW,
        checks=3,
    )
    text = fmt_day_card(card)
    assert text.startswith("🟦 <b>SPY 0DTE · Wed 07 Oct</b> · PAPER")
    assert "spot 690.12 · EM ±5.80" in text and "put wall 680.00" in text
    assert "<b>Plan</b> · bias neutral" in text
    # Every flag is its own bullet, and Claude's text is escaped.
    assert "• Spot 0.2% above the flip\n• CPI tomorrow &lt;b&gt;" in text
    assert "<b>Skip if</b>\n• SPY &lt; 775.88 (puts)" in text
    assert "<b>Status</b> 09:45 ET · put side armed, no trade" in text
    assert "(3 armed checks)" in text


def test_a_failed_plan_says_so_on_the_card() -> None:
    card = DayCard(day=date(2026, 10, 7), mode="paper", plan=_brief(None, "timeout"))
    assert "Plan</b> unavailable (timeout)" in fmt_day_card(card)


def test_status_keeps_the_deciding_clause() -> None:
    why = (
        "put: short ≤ 773.67 (spot 777.62, EM 1.81 × 1, put wall 774.45) — nearest 773/768 "
        "pays $0.07 mid (Δ n/a), under the $0.25 credit floor"
    )
    assert status_nothing_to_sell("put", why) == (
        "put side armed, no trade — nearest 773/768 pays $0.07 mid (Δ n/a), under the $0.25 "
        "credit floor"
    )


def test_event_formats_carry_the_numbers() -> None:
    e = fmt_entry(POS, "paper")
    assert e.startswith("🟢 <b>Opened put spread 679/674</b> ×1 @ 0.57")
    assert "max loss $443" in e and "<code>s1</code>" in e
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
    tagged = fmt_entry(POS, "paper", tags)
    assert "NEGATIVE GAMMA" in tagged and "0.63× expected-move drop" in tagged
    assert "gap -0.40%" in tagged
    calm = tags.model_copy(update={"regime": "positive", "gap_day": False})
    assert "gamma positive" in fmt_entry(POS, "paper", calm)
    assert "gap" not in fmt_entry(POS, "paper", calm)
    assert "(baseline, simulated)" in fmt_entry(POS, "baseline")

    x = fmt_exit("s1", "profit_take", 0.32, 22.4, "paper")
    assert x.startswith("✅") and "profit take" in x and "+$22.40" in x
    stop = fmt_exit("s1", "stop_loss", 1.2, -61.3, "paper")
    assert stop.startswith("🔴") and "stop loss" in stop and "-$61.30" in stop
    eod = fmt_eod(date(2026, 10, 7), "shadow", 2, -10.0, 0)
    assert "2 trades" in eod and "-$10.00" in eod and "still open" not in eod


def test_alerts_drop_the_bracket_tag_and_escape() -> None:
    assert fmt_alert("[SPREADS] halt file a<b present") == "⚠️ halt file a&lt;b present"
    assert fmt_alert("[SPREADS] URGENT: 1 spread open").startswith("🚨")


async def test_send_without_credentials_never_builds_a_bot(monkeypatch) -> None:
    def boom(*a, **k):
        raise AssertionError("Bot must not be constructed without credentials")

    monkeypatch.setattr(notify, "Bot", boom)
    assert await SpreadsNotifier("", "", "").send("hello") is None
    assert await SpreadsNotifier("", "", "").edit(1, "hello") is True


class _FakeBot:
    sent: list[dict] = []
    edited: list[dict] = []

    def __init__(self, token: str) -> None:
        self.token = token

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send_message(self, **kw):
        _FakeBot.sent.append(kw)
        return SimpleNamespace(message_id=9)

    async def edit_message_text(self, **kw):
        _FakeBot.edited.append(kw)


async def test_send_posts_html_to_the_spreads_thread_and_edit_targets_the_message(
    monkeypatch,
) -> None:
    _FakeBot.sent, _FakeBot.edited = [], []
    monkeypatch.setattr(notify, "Bot", _FakeBot)
    n = SpreadsNotifier("tok", "123", "77")
    assert await n.send("hello") == 9
    (kw,) = _FakeBot.sent
    assert kw["chat_id"] == "123" and kw["message_thread_id"] == 77 and kw["parse_mode"] == "HTML"
    assert await n.edit(9, "again") is True
    assert _FakeBot.edited[0]["message_id"] == 9 and _FakeBot.edited[0]["text"] == "again"
    assert SpreadsNotifier("tok", "123", "").thread_id is None


def test_the_day_card_says_whether_the_map_builds_and_trades_are_assessed() -> None:
    at = NOW
    card = DayCard(
        day=date(2026, 10, 7),
        mode="paper",
        updated_at=at,
        map_at=at,
        map_builds=3,
        assessments=12,
        assessed_at=at,
        watch_note="trigger not armed — move 0.3 EM",
    )
    text = fmt_day_card(card)
    assert "<i>updated 09:45 ET</i>" in text.splitlines()[0]
    assert "GEX map</b> ✅ built 09:45 ET · 3 builds today" in text
    assert "Trades</b> 12 assessed · last 09:45 ET · trigger not armed — move 0.3 EM" in text
    card.map_failed_since, card.map_error = at, "no chain or index price"
    assert "⚠️ failing since 09:45 ET · no chain or index price · retrying every 5 min" in (
        fmt_day_card(card)
    )
    assert "⏳ not built yet" in fmt_day_card(DayCard(day=date(2026, 10, 7), mode="paper"))
