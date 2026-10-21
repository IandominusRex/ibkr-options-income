"""The /regime Telegram command and the regime-change notices (Task 2)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.common.config import RegimeCfg
from src.common.schemas import (
    IndexRegime,
    MarketRegime,
    RegimeChange,
    RegimeInputs,
    RegimeState,
)

N = MarketRegime.NORMAL
C = MarketRegime.CAUTIOUS
S = MarketRegime.STRESSED
X = MarketRegime.CRISIS

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)  # Wed 11:00 ET
TODAY = date(2026, 10, 21)


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    import src.storage.db as dbmod
    from src.common.config import Config
    from src.regime.refresh import clear_regime_cache

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 't.db'}")
    dbmod.init_db()
    clear_regime_cache()
    yield
    clear_regime_cache()


def _ir(index: str, effective: MarketRegime, why: list[str] | None = None) -> IndexRegime:
    return IndexRegime(
        index=index,  # type: ignore[arg-type]
        base=effective,
        base_date=TODAY,
        since=TODAY,
        base_since=TODAY,
        effective=effective,
        escalated_by=why or [],
        inputs=RegimeInputs(vol=24.0),
    )


def _seed(spy: MarketRegime = N, qqq: MarketRegime = N, changes=None) -> RegimeState:
    from src.storage.regime_state import save_regime_state

    st = RegimeState(as_of=NOW, spy=_ir("SPY", spy), qqq=_ir("QQQ", qqq), changes=changes or [])
    save_regime_state(st)
    return st


def _update(chat_id: int = 99999) -> MagicMock:
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.message = AsyncMock()
    return update


def _ctx(*args: str) -> MagicMock:
    ctx = MagicMock()
    ctx.args = list(args)
    return ctx


@pytest.fixture()
def authorised(monkeypatch):
    cfg = SimpleNamespace(secrets=SimpleNamespace(telegram_chat_id="99999"))
    monkeypatch.setattr("src.notify.approval_service.get_config", lambda: cfg)


# --------------------------------------------------------------------------- #
# /regime
# --------------------------------------------------------------------------- #


async def test_regime_shows_both_indices_and_limits(authorised):
    from src.notify.approval_service import handle_regime_command

    _seed(spy=N, qqq=C)
    update = _update()
    await handle_regime_command(update, _ctx())
    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args.args[0]
    assert "SPY" in text and "QQQ" in text
    assert "normal" in text and "cautious" in text
    assert "CSP budget 70%" in text  # QQQ cautious
    assert "CSP budget 100%" in text  # SPY normal
    assert "at most 6 new CSPs" in text
    assert "limits are active" in text.lower()


async def test_regime_with_no_market_data_says_so_instead_of_claiming_calm(authorised):
    from src.notify.approval_service import handle_regime_command

    update = _update()  # no state, and the test environment has no market data
    await handle_regime_command(update, _ctx())
    text = update.message.reply_text.call_args.args[0]
    assert "no market data yet" in text
    assert "stale inputs" in text


async def test_regime_with_nothing_known_at_all_says_so(authorised, monkeypatch):
    from src.notify import approval_service

    monkeypatch.setattr(approval_service, "refresh_regime_cached", lambda now: None)
    update = _update()
    await approval_service.handle_regime_command(update, _ctx())
    assert "no regime state yet" in update.message.reply_text.call_args.args[0].lower()


async def test_regime_off_suspends_today_and_says_until_when(authorised, monkeypatch):
    from src.notify import approval_service
    from src.storage.regime_state import regime_suspended

    monkeypatch.setattr(approval_service, "today_et", lambda: TODAY)
    _seed(spy=S, qqq=S)
    update = _update()
    await approval_service.handle_regime_command(update, _ctx("off"))
    assert regime_suspended(TODAY) is True
    text = update.message.reply_text.call_args.args[0]
    assert "suspended" in text.lower()
    assert "2026-10-22" in text  # the next trading day's base
    assert "leveraged-ETF size limit" in text and "stays on" in text  # not a regime limit


async def test_regime_on_resumes(authorised, monkeypatch):
    from src.notify import approval_service
    from src.storage.regime_state import regime_suspended, suspend_regime

    monkeypatch.setattr(approval_service, "today_et", lambda: TODAY)
    suspend_regime(TODAY)
    update = _update()
    await approval_service.handle_regime_command(update, _ctx("on"))
    assert regime_suspended(TODAY) is False
    assert "resumed" in update.message.reply_text.call_args.args[0].lower()


async def test_regime_shows_suspension_in_the_status(authorised, monkeypatch):
    from src.notify import approval_service
    from src.storage.regime_state import suspend_regime

    monkeypatch.setattr(approval_service, "today_et", lambda: TODAY)
    _seed(spy=S, qqq=S)
    suspend_regime(TODAY)
    update = _update()
    await approval_service.handle_regime_command(update, _ctx())
    assert "suspended" in update.message.reply_text.call_args.args[0].lower()


async def test_regime_rejects_an_unknown_argument(authorised):
    from src.notify.approval_service import handle_regime_command

    update = _update()
    await handle_regime_command(update, _ctx("maybe"))
    assert "usage" in update.message.reply_text.call_args.args[0].lower()


async def test_regime_ignores_unauthorized_users(authorised):
    from src.notify.approval_service import handle_regime_command
    from src.storage.regime_state import regime_suspended

    update = _update(chat_id=11111)
    await handle_regime_command(update, _ctx("off"))
    update.message.reply_text.assert_not_called()
    assert regime_suspended(TODAY) is False


def test_regime_is_registered_in_the_command_menu_and_help():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src/notify/approval_service.py").read_text()
    assert 'CommandHandler("regime", handle_regime_command)' in src
    assert 'BotCommand("regime"' in src
    from src.notify.formatters import format_help

    assert "/regime" in format_help()


# --------------------------------------------------------------------------- #
# the change notice
# --------------------------------------------------------------------------- #


def _change(index="QQQ", before=N, after=S, why=None, sent=False) -> RegimeChange:
    return RegimeChange(
        index=index,  # type: ignore[arg-type]
        before=before,
        after=after,
        why=why if why is not None else ["QQQ -2.9% today"],
        at=NOW,
        sent=sent,
    )


def test_format_regime_change_text():
    from src.notify.regime_notice import format_regime_change

    text = format_regime_change(_change(), RegimeCfg(), working_opens=0)
    assert text == (
        "QQQ regime -> stressed (QQQ -2.9% today): CSP budget 40%, per-trade 30%, "
        "at most 3 new CSPs today."
    )


def test_format_regime_change_back_to_normal_says_the_limits_lift():
    from src.notify.regime_notice import format_regime_change

    text = format_regime_change(
        _change(before=S, after=N, why=["intraday escalation ended"]), RegimeCfg(), working_opens=0
    )
    assert text.startswith("QQQ regime -> normal (intraday escalation ended)")
    assert "CSP budget 100%" in text
    assert "no daily limit" in text


def test_format_regime_change_names_working_opening_orders():
    from src.notify.regime_notice import format_regime_change

    two = format_regime_change(_change(), RegimeCfg(), working_opens=2)
    assert (
        "2 opening orders already working at the broker are unchanged; cancel them in IBKR "
        "if you want them smaller." in two
    )
    one = format_regime_change(_change(), RegimeCfg(), working_opens=1)
    assert "1 opening order already working at the broker is unchanged" in one
    # a regime that eases tells nobody to cancel anything
    easing = format_regime_change(_change(before=S, after=C), RegimeCfg(), working_opens=2)
    assert "cancel" not in easing


async def test_send_regime_changes_sends_unsent_ones_then_marks_them_sent(monkeypatch):
    from src.notify import regime_notice
    from src.storage.regime_state import unsent_changes

    _seed(changes=[_change(sent=True), _change("SPY", N, C, why=["VIX 23.0"])])
    sent: list[dict] = []

    class FakeBot:
        def __init__(self, token: str) -> None:
            assert token == "tok"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def send_message(self, **kw):
            sent.append(kw)
            return SimpleNamespace(message_id=1)

    cfg = SimpleNamespace(
        secrets=SimpleNamespace(
            telegram_bot_token="tok", telegram_chat_id="99999", telegram_thread_account="58"
        )
    )
    monkeypatch.setattr(regime_notice, "get_config", lambda: cfg)
    monkeypatch.setattr(regime_notice, "Bot", FakeBot)

    n = await regime_notice.send_regime_changes()
    assert n == 1
    assert len(sent) == 1
    assert sent[0]["chat_id"] == "99999"
    assert sent[0]["message_thread_id"] == 58  # the trades/orders thread, like order notices
    assert "SPY regime -> cautious (VIX 23.0)" in sent[0]["text"]
    assert unsent_changes() == []
    # nothing new: nothing sent
    assert await regime_notice.send_regime_changes() == 0
    assert len(sent) == 1


async def test_send_regime_changes_keeps_them_unsent_when_the_send_fails(monkeypatch):
    from src.notify import regime_notice
    from src.storage.regime_state import unsent_changes

    _seed(changes=[_change()])

    class BrokenBot:
        def __init__(self, token: str) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def send_message(self, **kw):
            raise RuntimeError("telegram down")

    cfg = SimpleNamespace(
        secrets=SimpleNamespace(
            telegram_bot_token="tok", telegram_chat_id="99999", telegram_thread_account="58"
        )
    )
    monkeypatch.setattr(regime_notice, "get_config", lambda: cfg)
    monkeypatch.setattr(regime_notice, "Bot", BrokenBot)
    assert await regime_notice.send_regime_changes() == 0
    assert len(unsent_changes()) == 1  # retried on the next scan


async def test_send_regime_changes_without_a_token_does_nothing(monkeypatch):
    from src.notify import regime_notice
    from src.storage.regime_state import unsent_changes

    _seed(changes=[_change()])
    cfg = SimpleNamespace(
        secrets=SimpleNamespace(
            telegram_bot_token="", telegram_chat_id="", telegram_thread_account=""
        )
    )
    monkeypatch.setattr(regime_notice, "get_config", lambda: cfg)
    assert await regime_notice.send_regime_changes() == 0
    assert len(unsent_changes()) == 1


async def test_working_opens_counts_only_working_csp_orders(monkeypatch):
    from src.notify import regime_notice
    from src.storage.db import session_scope
    from src.storage.models import OrderRow

    def snap(strategy: str | None):
        return None if strategy is None else {"strategy": strategy}

    with session_scope() as s:
        s.add_all(
            [
                OrderRow(candidate_id="a", state="submitted", snapshot=snap("cash_secured_put")),
                OrderRow(candidate_id="b", state="partial", snapshot=snap("cash_secured_put")),
                OrderRow(candidate_id="c", state="filled", snapshot=snap("cash_secured_put")),
                OrderRow(candidate_id="d", state="submitted", snapshot=snap("covered_call")),
                OrderRow(candidate_id="e", state="submitted", snapshot=snap("roll")),
                OrderRow(candidate_id="close:X:1", state="submitted", snapshot=snap(None)),
                OrderRow(candidate_id="f", state="queued", snapshot=snap("cash_secured_put")),
            ]
        )
    assert regime_notice.working_csp_opens() == 2


# --------------------------------------------------------------------------- #
# the scan wires the refresh and the notices in
# --------------------------------------------------------------------------- #


async def test_the_scan_refreshes_the_regime_and_sends_notices(monkeypatch):
    from src.orchestrator import scan as scanmod

    seen: dict[str, object] = {}
    state = RegimeState(as_of=NOW, spy=_ir("SPY", N), qqq=_ir("QQQ", S), changes=[])

    def fake_refresh(now):
        seen["refreshed"] = now
        return state

    async def fake_send():
        seen["sent"] = True
        return 1

    monkeypatch.setattr(scanmod, "refresh_regime", fake_refresh)
    monkeypatch.setattr(scanmod, "send_regime_changes", fake_send)

    result = scanmod.ScanResult()
    await scanmod._refresh_and_announce_regime(result)
    assert result.regime is state
    assert seen["sent"] is True


async def test_a_regime_failure_never_aborts_the_scan(monkeypatch):
    from src.orchestrator import scan as scanmod

    def boom(now):
        raise RuntimeError("yfinance exploded")

    async def boom_send():
        raise RuntimeError("telegram exploded")

    monkeypatch.setattr(scanmod, "refresh_regime", boom)
    monkeypatch.setattr(scanmod, "send_regime_changes", boom_send)
    result = scanmod.ScanResult()
    await scanmod._refresh_and_announce_regime(result)  # must not raise
    assert result.regime is None
