"""Event-driven intraday position monitor.

Runs as a long-lived asyncio process (clientId 12). Subscribes to live market
data for every short option position, fires trigger conditions on each tick, and
delivers Telegram roll alerts with optional Claude recommendations.

Key design points:
- IB ticks arrive via pendingTickersEvent (ib_async event).
- Claude subprocess runs in a ThreadPoolExecutor to avoid blocking the loop.
- Alert de-duplication: the roll_alerts DB table gates re-alerts per
  (position_symbol, trigger) within alert_cooldown_minutes.
- Multiple triggers for the same position in one pass are combined into a
  single Telegram message.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import signal
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from ib_async import IB

from src.analytics.fundamentals import get_fundamental_stats
from src.claude.runner import review_roll
from src.common.config import Config, get_config
from src.common.schemas import (
    FundamentalStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RollAlert,
    RollReview,
)
from src.ibkr.connection import AutoReconnect
from src.ibkr.contracts import build_option
from src.ibkr.portfolio import get_positions
from src.monitor.triggers import check_all
from src.storage.db import init_db, session_scope
from src.storage.models import CandidateRow, FillRow, RollAlertRow

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _ticker_to_quote(ticker: Any, pos: PositionSnapshot) -> OptionQuote:
    """Convert an ib_async Ticker to an OptionQuote using the position for metadata."""
    g = ticker.modelGreeks
    return OptionQuote(
        underlying=pos.underlying or pos.symbol,
        right=pos.right or OptionRight.CALL,
        strike=pos.strike or 0.0,
        expiry=pos.expiry or datetime.now(UTC).date(),
        bid=_safe(ticker.bid),
        ask=_safe(ticker.ask),
        last=_safe(ticker.last),
        volume=int(ticker.volume)
        if ticker.volume and not math.isnan(float(ticker.volume))
        else None,
        iv=_safe(g.impliedVol) if g else None,
        delta=_safe(g.delta) if g else None,
        gamma=_safe(g.gamma) if g else None,
        theta=_safe(g.theta) if g else None,
        vega=_safe(g.vega) if g else None,
        greeks_source="ibkr",
    )


def _load_entry_iv(pos: PositionSnapshot) -> float | None:
    """Return the IV recorded at fill for this short option position, or None.

    Matches the position's contract (underlying/strike/expiry/right) back to the
    candidate that produced its most recent fill and reads FillRow.entry_iv.
    """
    if pos.strike is None or pos.expiry is None or pos.right is None:
        return None
    with session_scope() as session:
        row = (
            session.query(FillRow.entry_iv)
            .join(CandidateRow, CandidateRow.candidate_id == FillRow.candidate_id)
            .filter(
                CandidateRow.underlying == (pos.underlying or pos.symbol),
                CandidateRow.strike == pos.strike,
                CandidateRow.expiry == pos.expiry,
                CandidateRow.right == pos.right.value,
            )
            .order_by(FillRow.filled_at.desc())
            .first()
        )
    return row[0] if row and row[0] is not None else None


def _is_recent_alert(alert: RollAlert, cooldown_minutes: int) -> bool:
    """Return True if the same (position_symbol, trigger) was alerted within cooldown."""
    cutoff = datetime.now(UTC) - timedelta(minutes=cooldown_minutes)
    with session_scope() as session:
        existing = (
            session.query(RollAlertRow)
            .filter(
                RollAlertRow.position_symbol == alert.position_symbol,
                RollAlertRow.trigger == alert.trigger,
                RollAlertRow.created_at >= cutoff,
            )
            .first()
        )
        return existing is not None


def _persist_alert(alert: RollAlert, review: RollReview | None) -> None:
    """Write a RollAlertRow to the DB."""
    with session_scope() as session:
        row = RollAlertRow(
            position_symbol=alert.position_symbol,
            underlying=alert.underlying,
            trigger=alert.trigger,
            detail=alert.detail,
            claude_recommendation=review.recommendation if review else None,
            payload={
                "alert": alert.model_dump(mode="json"),
                "review": review.model_dump(mode="json") if review else None,
            },
        )
        session.add(row)


# ---------------------------------------------------------------------------
# Core alert-firing logic (async, testable)
# ---------------------------------------------------------------------------


async def _try_queue_roll(
    ib: IB,
    pos: PositionSnapshot,
    chat_id: str,
    cfg: Config,
) -> int | None:
    """Fetch the chain, generate the best roll candidate, and raise a PENDING approval (N20).

    Returns the approval id (so the caller can attach Approve/Reject buttons), or None when no
    roll qualifies or anything fails — in which case the caller falls back to an alert-only send.
    """
    underlying = pos.underlying or pos.symbol
    try:
        from src.analytics.iv import get_iv_stats
        from src.analytics.technicals import get_technical_stats
        from src.execution.roll_pipeline import queue_roll_for_approval
        from src.ibkr.market_data import get_option_chain_quotes_async

        quotes = await get_option_chain_quotes_async(ib, underlying)
        if not quotes:
            return None
        loop = asyncio.get_running_loop()
        iv_stats = await loop.run_in_executor(None, get_iv_stats, underlying, quotes)
        tech_stats = await loop.run_in_executor(None, get_technical_stats, underlying)
        queued = queue_roll_for_approval(
            pos, quotes, iv_stats, tech_stats, chat_id=chat_id, ttl_minutes=cfg.approval.ttl_minutes
        )
        return queued[0] if queued is not None else None
    except Exception:
        log.exception("roll: chain/candidate generation failed for %s", underlying)
        return None


async def fire_alerts(
    alerts: list[RollAlert],
    pos: PositionSnapshot,
    quote: OptionQuote,
    bot: Any,
    chat_id: str,
    cfg: Config,
    executor: ThreadPoolExecutor,
    ib: IB | None = None,
) -> None:
    """De-dup, call Claude, send Telegram, persist. No-op if all alerts are recent.

    This function is the testable heart of the monitor — the IB event subscription
    code in IntradayMonitor calls into here. When ``cfg.monitor.roll_execution_enabled`` is set
    and an ``ib`` is supplied, the alert is sent as an **approvable roll candidate** (N20):
    tapping Approve queues a ROLL order that ``execute_roll`` executes. Otherwise it is the
    historical alert-only message.
    """
    fresh = [a for a in alerts if not _is_recent_alert(a, cfg.monitor.alert_cooldown_minutes)]
    if not fresh:
        log.debug(
            "All %d alert(s) for %s are within cooldown — suppressed", len(alerts), pos.symbol
        )
        return

    # Claude review in thread (subprocess — blocks; run off the event loop)
    review: RollReview | None = None
    if cfg.claude.enabled:
        loop = asyncio.get_running_loop()
        try:
            review = await loop.run_in_executor(
                executor,
                lambda: review_roll(fresh[0], pos, quote),
            )
        except Exception:
            log.exception("Claude roll review failed for %s", pos.symbol)

    # Optionally turn the alert into an approvable roll candidate (gated; default OFF).
    reply_markup = None
    if getattr(cfg.monitor, "roll_execution_enabled", False) is True and ib is not None:
        approval_id = await _try_queue_roll(ib, pos, chat_id, cfg)
        if approval_id is not None:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            reply_markup = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Approve roll", callback_data=f"approve:{approval_id}"
                        ),
                        InlineKeyboardButton("❌ Reject", callback_data=f"reject:{approval_id}"),
                    ]
                ]
            )

    from src.notify.formatters import format_roll_alert

    text = format_roll_alert(pos, quote, fresh, review)
    try:
        await bot.send_message(
            chat_id=chat_id, text=text, parse_mode="MarkdownV2", reply_markup=reply_markup
        )
        log.info(
            "Roll alert sent: %s triggers=%s recommendation=%s approvable=%s",
            pos.symbol,
            [a.trigger for a in fresh],
            review.recommendation if review else "n/a",
            reply_markup is not None,
        )
    except Exception:
        log.exception("Telegram send failed for roll alert %s", pos.symbol)

    for alert in fresh:
        try:
            _persist_alert(alert, review)
        except Exception:
            log.exception("Failed to persist roll alert for %s", alert.position_symbol)


# ---------------------------------------------------------------------------
# Monitor class
# ---------------------------------------------------------------------------


class IntradayMonitor:
    """Subscribes to ib_async pendingTickersEvent for short option positions."""

    def __init__(
        self,
        ib: IB,
        bot: Any,
        chat_id: str,
        cfg: Config,
        executor: ThreadPoolExecutor,
    ) -> None:
        self._ib = ib
        self._bot = bot
        self._chat_id = chat_id
        self._cfg = cfg
        self._executor = executor
        # Maps OCC symbol (localSymbol) → (PositionSnapshot, subscribed Contract).
        # Storing the Contract object used in reqMktData is required for cancelMktData
        # to actually cancel the right subscription (ib_async matches by reqId, not
        # by contract equality — a freshly-built unqualified Contract silently no-ops).
        self._subscriptions: dict[str, tuple[PositionSnapshot, Any]] = {}
        # OCC symbol → IV at entry (IV-spike baseline); underlying → fundamentals (ex-div).
        self._entry_iv: dict[str, float | None] = {}
        self._fund_stats: dict[str, FundamentalStats] = {}

    # ------------------------------------------------------------------
    # Subscription management — async, runs on the ib_async loop thread.
    # IB calls (positions, reqMktData, cancelMktData) are non-blocking and stay on
    # the loop; only the blocking yfinance fundamentals fetch is offloaded to a thread.
    # ------------------------------------------------------------------

    async def _on_reconnect(self) -> None:
        """Clear all subscription state then re-subscribe after a TWS reconnect.

        Without this clear, _refresh_subscriptions would find all symbols already in
        self._subscriptions (in-memory) and skip reqMktData — but ib.tickers() is
        empty on a fresh connection, so the check `not any(...)` would see all tickers
        missing and call reqMktData again, doubling every subscription.
        Clearing first makes the refresh behave identically to a cold start.
        """
        self._subscriptions.clear()
        self._entry_iv.clear()
        await self._refresh_subscriptions()

    async def _refresh_subscriptions(self) -> None:
        """Load positions; subscribe to new short options, unsubscribe from closed ones."""
        loop = asyncio.get_running_loop()
        try:
            positions = get_positions(self._ib)
        except Exception:
            log.exception("Failed to load positions during subscription refresh")
            return

        active_symbols: set[str] = set()

        for pos in positions:
            if pos.sec_type != "OPT" or pos.position >= 0:
                continue
            if pos.expiry is None or pos.strike is None or pos.right is None:
                continue

            active_symbols.add(pos.symbol)

            already_subscribed = pos.symbol in self._subscriptions

            # Entry IV (IV-spike baseline) — load once per position; it doesn't change.
            if pos.symbol not in self._entry_iv:
                self._entry_iv[pos.symbol] = _load_entry_iv(pos)
            # Fundamentals (ex-div date) — cache once per underlying for the session.
            underlying = pos.underlying or pos.symbol
            if underlying not in self._fund_stats:
                try:
                    # yfinance is blocking — keep it off the event loop.
                    self._fund_stats[underlying] = await loop.run_in_executor(
                        self._executor, get_fundamental_stats, underlying
                    )
                except Exception:
                    log.exception("Failed to fetch fundamentals for %s", underlying)

            if already_subscribed:
                # Update the position snapshot in-place, keeping the stored Contract.
                old_pos, old_contract = self._subscriptions[pos.symbol]
                self._subscriptions[pos.symbol] = (pos, old_contract)
            else:
                # New position — subscribe and store the Contract object used so that
                # cancelMktData can use the same object (ib_async matches by reqId).
                try:
                    contract = build_option(
                        pos.underlying or pos.symbol, pos.expiry, pos.strike, pos.right.value
                    )
                    self._ib.reqMktData(contract, "101", False, False)
                    self._subscriptions[pos.symbol] = (pos, contract)
                    log.info("Subscribed market data: %s", pos.symbol)
                except Exception:
                    log.exception("reqMktData failed for %s", pos.symbol)

        # Unsubscribe from positions that are no longer held
        for sym in list(self._subscriptions):
            if sym not in active_symbols:
                old_pos, contract = self._subscriptions.pop(sym)
                self._entry_iv.pop(sym, None)
                if contract is not None:
                    try:
                        self._ib.cancelMktData(contract)
                        log.info("Unsubscribed market data: %s", sym)
                    except Exception:
                        log.exception("cancelMktData failed for %s", sym)

    # ------------------------------------------------------------------
    # Ticker event handler
    # ------------------------------------------------------------------

    async def _on_pending_tickers(self, tickers: Any) -> None:
        """Called by ib_async for every pendingTickersEvent batch."""
        for ticker in tickers:
            if ticker.contract is None:
                continue
            local_sym = (ticker.contract.localSymbol or "").strip()
            entry = self._subscriptions.get(local_sym)
            if entry is None:
                continue
            pos, _ = entry
            quote = _ticker_to_quote(ticker, pos)
            limits = {
                "delta_ceiling": self._cfg.monitor.delta_ceiling,
                "dte_threshold": self._cfg.monitor.dte_threshold,
                "iv_spike_pct": self._cfg.monitor.iv_spike_pct,
                "ex_div_days_ahead": self._cfg.monitor.ex_div_days_ahead,
            }
            entry_iv = self._entry_iv.get(local_sym)
            fund_stats = self._fund_stats.get(pos.underlying or pos.symbol)
            alerts = check_all(pos, quote, entry_iv=entry_iv, fund_stats=fund_stats, limits=limits)
            if alerts:
                await fire_alerts(
                    alerts,
                    pos,
                    quote,
                    self._bot,
                    self._chat_id,
                    self._cfg,
                    self._executor,
                    ib=self._ib,
                )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, stop_event: asyncio.Event) -> None:
        """Subscribe to IB events and run until stop_event is set."""
        # Initial position load — IB calls run on the loop; yfinance is offloaded inside.
        await self._refresh_subscriptions()

        self._ib.pendingTickersEvent += self._on_pending_tickers

        poll_seconds = self._cfg.scheduler.intraday_poll_seconds

        async def _refresh_loop() -> None:
            while not stop_event.is_set():
                await asyncio.sleep(poll_seconds)
                await self._refresh_subscriptions()

        refresh_task = asyncio.create_task(_refresh_loop())
        log.info("Intraday monitor running (refresh every %ds)", poll_seconds)

        try:
            await stop_event.wait()
        finally:
            refresh_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await refresh_task
            self._ib.pendingTickersEvent -= self._on_pending_tickers
            log.info("Intraday monitor stopped")


# ---------------------------------------------------------------------------
# Process entrypoint
# ---------------------------------------------------------------------------


async def run(stop_event: asyncio.Event | None = None) -> None:
    """Connect to IBKR, start the monitor, block until stopped."""
    cfg = get_config()
    init_db()

    mode = "LIVE" if cfg.is_live else "PAPER"
    log.warning(
        "=" * 60 + "\n  INTRADAY MONITOR  |  mode=%s  port=%s  clientId=%s\n" + "=" * 60,
        mode,
        cfg.ibkr_port,
        cfg.ibkr.client_ids.get("monitor", 12),
    )

    token = cfg.secrets.telegram_bot_token
    chat_id = cfg.secrets.telegram_chat_id
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")

    from telegram import Bot

    ib = IB()
    try:
        await ib.connectAsync(
            cfg.ibkr.host,
            cfg.ibkr_port,
            clientId=cfg.ibkr.client_ids.get("monitor", 12),
            timeout=cfg.ibkr.connect_timeout_seconds,
        )
    except Exception:
        log.exception("IBKR connection failed — monitor cannot start")
        raise

    if stop_event is None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop_event.set)

    async with Bot(token=token) as bot:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="monitor") as executor:
            monitor = IntradayMonitor(ib, bot, chat_id, cfg, executor)
            # Keep the long-lived connection alive across TWS drops; on reconnect, re-subscribe
            # market data so the monitor doesn't go silently blind.
            reconnect = AutoReconnect(
                ib,
                cfg.ibkr.host,
                cfg.ibkr_port,
                cfg.ibkr.client_ids.get("monitor", 12),
                market_data_type=cfg.ibkr.market_data_type,
                on_reconnect=monitor._on_reconnect,
                label="monitor",
            )
            try:
                await monitor.start(stop_event)
            finally:
                reconnect.stop()
                ib.disconnect()
                log.info("IBKR monitor connection closed")
