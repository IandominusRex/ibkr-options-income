"""The envelope's Telegram lines (risk-envelope plan Task 14; spec §3.4, §3.4.7, §3.7.4, E13).

The EOD line names every measure and the limits and labels stored IV; the LES line shows trend,
pullback, breadth and tier; a manual stock buy posts S10 and U_ew before and after, once per
execution.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from src.common.envelope_types import EnvelopeSnapshot, ShockResult
from src.common.schemas import LesSignal
from src.notify import formatters as fmt


def _result(s10: float = 22.3, uew: float = 1.36, unmeasured=()) -> ShockResult:
    return ShockResult(
        s10=s10, s20=41.0, g10=21.0, p20=38.0, t20=23.7, s_smh=12.0, s10_vol10=24.1,
        s10_net=21.1, s20_net=39.0, g10_net=20.0, p20_net=36.5, t20_net=22.9, s_smh_net=11.5,
        s10_vol10_net=23.0, uew=uew, unmeasured=tuple(unmeasured),
    )  # fmt: skip


def _snap(source: str = "live", **kw) -> EnvelopeSnapshot:
    base = dict(
        captured_at=datetime(2026, 11, 14, 20, 30, tzinfo=UTC),
        source=source,
        result=_result(),
        s10_limit=23.0,
        uew_limit=1.37,
        t20_limit=None,
        enforce="record",
        measured=True,
        nlv=650_000.0,
        cash_after_itm=-12_345.0,
    )
    base.update(kw)
    return EnvelopeSnapshot(**base)  # type: ignore[arg-type]


def test_the_daily_line_names_every_measure_and_the_limits() -> None:
    text = fmt.format_envelope_line(_snap())
    for token in (
        "S10   22.3% gross · 21.1% net · L(t) 23.0%",
        "S20 41.0% / 39.0%",
        "G10 21.0% / 20.0%",
        "P20 38.0% / 36.5%",
        "T20 23.7% / 22.9%",
        "S-SMH 12.0% / 11.5%",
        "S10+10v 24.1%",
        "U_ew  1.36 · limit 1.37",
        "Cash after every ITM put is assigned: $-12,345",
        "record: not enforced yet",
    ):
        assert token in text, token
    assert "n/a" not in text
    # unknown is n/a, never 0; an unmeasured book says so
    blind = fmt.format_envelope_line(
        _snap(
            cash_after_itm=None, uew_limit=None, measured=False, result=_result(unmeasured=("AMD",))
        )
    )
    assert "assigned: n/a" in blind and "limit n/a" in blind
    assert "UNMEASURED" in blind and "Unmeasured: AMD" in blind
    assert fmt.format_envelope_line(None) == "Envelope: no measurement yet"


def test_the_line_labels_stored_iv() -> None:
    assert "stored IV" in fmt.format_envelope_line(_snap("stored"))
    assert "live IV" in fmt.format_envelope_line(_snap("live"))
    assert "stored IV" not in fmt.format_envelope_line(_snap("live"))


def test_the_les_line_shows_trend_pullback_breadth_and_tier() -> None:
    sig = LesSignal(
        asof=date(2026, 11, 13), index="QQQ", trend_up=True, pullback=True, washout=False,
        trend_break=False, tier_pct=3.0,
    )  # fmt: skip
    line = fmt.format_les_line(sig, index="QQQ", osc=-22.5)
    assert line == (
        "LES QQQ (13 Nov): trend up · pullback yes · washout no · breadth -22.5 · tier 3.0%"
    )
    broke = sig.model_copy(update={"trend_up": False, "trend_break": True, "tier_pct": 0.0})
    assert "TREND BREAK" in fmt.format_les_line(broke, index="QQQ")
    assert "breadth n/a" in fmt.format_les_line(broke, index="QQQ")
    assert fmt.format_les_line(None, index="SOXX") == "LES SOXX: no signal recorded"


def test_the_eod_section_is_one_markdown_code_block() -> None:
    section = fmt.format_envelope_section(_snap(), ["LES QQQ: no signal recorded"])
    head, open_, *body, close = section.split("\n")
    assert head == "*Risk envelope*" and open_ == close == "```"
    assert "LES QQQ: no signal recorded" in body


def test_the_eod_report_appends_the_envelope_section(db, monkeypatch) -> None:
    from src.orchestrator import eod_report
    from src.storage.envelope_state import save_snapshot

    assert "no measurement yet" in eod_report._envelope_section()
    save_snapshot(
        _result(19.0), source="stored", enforce="record", measured=True, s10_limit=19.0,
        uew_limit=1.4, t20_limit=None, captured_at=datetime(2026, 11, 14, 20, 0, tzinfo=UTC),
    )  # fmt: skip
    save_snapshot(
        _result(22.3), source="live", enforce="record", measured=True, s10_limit=23.0,
        uew_limit=1.37, t20_limit=None, captured_at=datetime(2026, 11, 14, 19, 45, tzinfo=UTC),
    )  # fmt: skip
    section = eod_report._envelope_section()
    assert "live IV" in section and "22.3% gross" in section  # same ET day: the live one
    assert "LES QQQ: no signal recorded" in section and "LES SOXX" in section


# --- the manual-buy line (E13) ----------------------------------------------------------------


def _seed_exec(exec_id: str, *, sym="NVDA", qty=100.0, sec="STK", book="manual", day=None) -> None:
    from src.common.market_hours import today_et
    from src.storage.db import session_scope
    from src.storage.models import BrokerExecutionRow

    d = day or today_et()
    with session_scope() as s:
        s.add(
            BrokerExecutionRow(
                dedupe_key=f"k:{exec_id}", source_kind="exec", source="live", exec_id=exec_id,
                trade_time=datetime(d.year, d.month, d.day, 15, 0), trade_date=d,
                contract_ident=sym, underlying=sym, sec_type=sec, currency="USD", quantity=qty,
                price=180.0, proceeds=-qty * 180.0, book=book,
            )
        )  # fmt: skip


def test_a_manual_buy_posts_before_and_after(db, monkeypatch) -> None:
    from src.common.schemas import AccountSnapshot, PositionSnapshot
    from src.notify import approval_service as svc

    for i, kw in enumerate(
        [
            {},  # the one to report
            {"qty": -50.0},  # a sale
            {"sec": "OPT"},  # an option
            {"book": "system"},  # the system's own fill
            {"day": date(2026, 1, 5)},  # an old one from an import
        ]
    ):
        _seed_exec(f"e{i}", **kw)  # type: ignore[arg-type]
    positions = [
        PositionSnapshot(
            symbol="NVDA", sec_type="STK", position=300, avg_cost=170.0, market_price=180.0
        )
    ]
    account = AccountSnapshot(
        account="DU1", net_liquidation=100_000.0, total_cash=10_000.0, buying_power=1.0,
        maintenance_margin=1.0, excess_liquidity=1.0,
    )  # fmt: skip

    async def snapshot(*_a, **_k):
        return account

    sent: list[str] = []

    async def notice(text: str, **_k) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr("src.ibkr.portfolio.get_positions", lambda ib: positions)
    monkeypatch.setattr("src.ibkr.portfolio.get_account_snapshot_async", snapshot)
    monkeypatch.setattr("src.notify.notices.send_notice", notice)
    monkeypatch.setattr(
        "src.analytics.shock_inputs.betas", lambda syms, vs="SPY": ({s: 1.5 for s in syms}, set())
    )

    assert asyncio.run(svc.envelope_manual_buy_check(object())) == 1
    (text,) = sent
    # before: 200 shares x $180 x 1.5 x 10% = 5.4%; after: 300 shares = 8.1%
    assert "Manual buy seen: NVDA +100 shares" in text
    assert "S10 5.4% -> 8.1%" in text and "U_ew 0.36 -> 0.54" in text
    assert "Headroom against the targets (no glide yet) (S10 15.0%, U_ew 1.25)" in text
    assert "S10 +6.9 pts, U_ew +0.71" in text
    # once per execution id
    assert asyncio.run(svc.envelope_manual_buy_check(object())) == 0 and len(sent) == 1


def test_the_manual_buy_loop_runs_in_rth_on_a_live_connection(monkeypatch) -> None:
    """The loop reads what the ledger ingested on the sweep's cadence; out of RTH or with the
    connection down it does nothing, and a failing check never stops it."""
    from src.notify import approval_service as svc

    class _IB:
        def __init__(self) -> None:
            self.up = iter([True, False, True, True])

        def isConnected(self) -> bool:  # noqa: N802 - ib_async's name
            return next(self.up)

    rth = iter([True, True, False, True, True, True])
    calls: list[str] = []
    ticks = iter(range(5))

    async def sleep(_s):
        try:
            next(ticks)
        except StopIteration:
            raise asyncio.CancelledError from None

    async def check(_ib) -> int:
        calls.append("check")
        if len(calls) == 2:
            raise RuntimeError("boom")
        return 0

    monkeypatch.setattr(svc, "is_rth", lambda: next(rth))
    monkeypatch.setattr(svc, "envelope_manual_buy_check", check)
    monkeypatch.setattr(svc.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(svc.envelope_manual_buy_loop(_IB(), interval_minutes=0.0))
    # cycle 1 runs, 2 the connection is down, 3 out of RTH, 4 raises (logged), 5 runs
    assert calls == ["check", "check", "check"]
