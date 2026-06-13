"""ONE-SHOT EOD orchestrator: P&L + what changed + watchlist + Claude journal.

Steps:
  1. Connect to IBKR (clientId 11)
  2. Fetch positions + account snapshot
  3. Read today's fills for realized P&L
  4. Read yesterday's JournalRow for unrealized delta baseline
  5. Build EODSummary
  6. Call Claude for a narrative (best-effort; falls back gracefully)
  7. Write JournalRow to DB
  8. Send Telegram summary
  9. Disconnect

Usage:
    python -m scripts.run_eod
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Bot

from src.claude.runner import write_journal_narrative
from src.common.config import get_config
from src.common.schemas import AccountSnapshot, EODSummary, PositionSnapshot
from src.ibkr.connection import IBKRConnection
from src.ibkr.portfolio import (
    enrich_positions_with_greeks_async,
    get_account_snapshot_async,
    get_positions,
)
from src.notify.formatters import format_eod_summary
from src.storage.db import init_db, session_scope
from src.storage.models import FillRow, JournalRow

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def _compute_realized_pnl(today: date) -> tuple[float, int, list[int]]:
    """Return (premium_cashflow, fill_count, fill_ids) for the option fills on the *ET* trading day.

    This is the net option premium **cashflow** for the day — credits from sells minus
    debits from buys (e.g. a buy-to-close) — NOT a full realized-P&L that pairs opens with
    closes. For an income desk that only opens short premium it equals premium collected;
    signing by `action` keeps it correct the moment a closing buy is recorded so a roll's
    debit no longer reads as a gain.

    `today` is interpreted as a market-timezone (ET) calendar date. The day window is built
    at ET midnight and converted to UTC so it lines up with how fills are stored (UTC).
    This avoids the local-vs-UTC midnight gap that previously zeroed out P&L when the report
    ran between local midnight and the UTC-date rollover (e.g. early morning in UTC+8).
    """
    next_day = today + timedelta(days=1)
    today_start = datetime(today.year, today.month, today.day, tzinfo=_ET).astimezone(UTC)
    tomorrow_start = datetime(next_day.year, next_day.month, next_day.day, tzinfo=_ET).astimezone(
        UTC
    )
    with session_scope() as session:
        fills = (
            session.query(FillRow)
            .filter(FillRow.filled_at >= today_start, FillRow.filled_at < tomorrow_start)
            .all()
        )
        # SELL = credit (+), BUY = debit (−). Legacy/unset rows default to SELL.
        realized = sum(
            (-1.0 if (f.action or "SELL").upper() == "BUY" else 1.0)
            * f.avg_price
            * f.filled_qty
            * 100
            for f in fills
        )
        fill_ids = [f.id for f in fills]
    return realized, len(fill_ids), fill_ids


def _universe_symbols(cfg) -> list[str]:
    """Indexes ∪ watchlist ∪ would_own — the symbols whose IV history we keep fresh."""
    u = cfg.universe
    return sorted(
        set(u.get("indexes", [])) | set(u.get("watchlist", [])) | set(u.get("would_own", []))
    )


async def _append_daily_iv(ib, symbols: list[str]) -> None:
    """Append today's ATM IV observation per symbol so the IV-rank window stays current (N4).

    Without this the only writer to `iv_history` is the one-shot bootstrap backfill, so the
    trailing-year window ages silently — and IV rank is both the largest score weight and a hard
    gate. Reuses the backfill's `OPTION_IMPLIED_VOLATILITY` daily bar; `append_observation` skips
    a date already present, so a re-run (or a second EOD) is idempotent. Best-effort per symbol.
    """
    from src.ibkr.contracts import qualify_stock_async
    from src.storage.iv_history import append_observation

    inserted = 0
    for sym in symbols:
        try:
            stock = await qualify_stock_async(ib, sym)
            bars = await ib.reqHistoricalDataAsync(
                stock,
                endDateTime="",
                durationStr="2 D",
                barSizeSetting="1 day",
                whatToShow="OPTION_IMPLIED_VOLATILITY",
                useRTH=True,
                keepUpToDate=False,
            )
            if not bars:
                continue
            last = bars[-1]
            bar_date = last.date if isinstance(last.date, date) else last.date.date()
            if append_observation(sym, bar_date, float(last.close)):
                inserted += 1
        except Exception:
            logger.debug("EOD IV append failed for %s", sym, exc_info=True)
        await asyncio.sleep(0.2)  # pace reqHistoricalData calls
    logger.info("EOD: appended %d new IV observation(s) across %d symbols", inserted, len(symbols))


def _load_yesterday_unrealized(today: date) -> float:
    """Return the unrealized_pnl from yesterday's JournalRow, or 0.0 if none."""
    yesterday = today - timedelta(days=1)
    with session_scope() as session:
        row = session.query(JournalRow).filter(JournalRow.entry_date == yesterday).first()
        return float(row.unrealized_pnl or 0.0) if row else 0.0


def _build_eod_summary(
    positions: list[PositionSnapshot],
    account: AccountSnapshot,
    realized_pnl: float,
    fill_count: int,
    yesterday_unrealized: float,
    watchlist: list[str],
) -> EODSummary:
    """Compute EODSummary from live positions and DB history."""
    today = date.today()

    unrealized_pnl = sum(p.unrealized_pnl or 0.0 for p in positions)
    unrealized_delta = unrealized_pnl - yesterday_unrealized

    # Net delta exposure across the full portfolio:
    #   Options: delta * contracts * 100 (position is contract count; negative = short)
    #   Stocks:  1.0 * shares (each share = 1 delta; negative = short stock)
    net_delta = sum((p.delta or 0.0) * p.position * 100 for p in positions if p.sec_type == "OPT")
    net_delta += sum(p.position for p in positions if p.sec_type == "STK")

    # Top movers: option positions sorted by abs(unrealized_pnl), take top 3.
    opt_positions = [p for p in positions if p.sec_type == "OPT" and p.unrealized_pnl is not None]
    opt_positions.sort(key=lambda p: abs(p.unrealized_pnl or 0.0), reverse=True)
    top_movers = [p.underlying or p.symbol for p in opt_positions[:3]]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    top_movers_dedup: list[str] = []
    for sym in top_movers:
        if sym not in seen:
            seen.add(sym)
            top_movers_dedup.append(sym)

    return EODSummary(
        date=today,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        unrealized_pnl_delta=unrealized_delta,
        fills_today=fill_count,
        open_positions=len(positions),
        net_delta_exposure=net_delta,
        account=account,
        top_movers=top_movers_dedup,
        tomorrow_watchlist=watchlist,
    )


def _write_journal(summary: EODSummary, narrative: str | None, fill_ids: list[int]) -> None:
    payload = {
        "eod_summary": summary.model_dump(mode="json"),
        "fills": fill_ids,
    }
    with session_scope() as session:
        row = JournalRow(
            entry_date=summary.date,
            realized_pnl=summary.realized_pnl,
            unrealized_pnl=summary.unrealized_pnl,
            narrative=narrative,
            payload=payload,
        )
        session.add(row)
    logger.info("JournalRow written for %s", summary.date)


async def _send_eod_telegram(summary: EODSummary, narrative: str | None) -> None:
    cfg = get_config()
    token = cfg.secrets.telegram_bot_token
    chat_id = cfg.secrets.telegram_chat_id

    if not token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping EOD send")
        return

    text = format_eod_summary(summary, narrative)
    try:
        async with Bot(token=token) as bot:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
        logger.info("EOD summary sent to Telegram")
    except Exception:
        logger.exception("Failed to send EOD Telegram message")


async def run() -> None:
    init_db()
    cfg = get_config()
    mode = "*** LIVE TRADING ***" if cfg.is_live else "paper"
    logger.warning("=" * 60)
    logger.warning("  MODE: %s", mode)
    logger.warning(
        "  Account: %s  Port: %d", cfg.secrets.ibkr_account or "(not set)", cfg.ibkr_port
    )
    logger.warning("=" * 60)
    logger.info(
        "EOD report starting — account=%s live=%s",
        cfg.secrets.ibkr_account or "(not set)",
        cfg.is_live,
    )

    # 1. Connect to IBKR (async — we're already inside asyncio.run) and fetch portfolio data.
    #    Enrich option positions with live greeks so net-delta exposure is real, not 0.
    async with IBKRConnection("engine") as ib:
        positions = get_positions(ib)
        account = await get_account_snapshot_async(ib, cfg.secrets.ibkr_account)
        try:
            await enrich_positions_with_greeks_async(ib, positions)
        except Exception:
            logger.exception("EOD: greeks enrichment failed — net delta may read 0")
        # Keep the IV-rank window current (N4) while the connection is open.
        try:
            await _append_daily_iv(ib, _universe_symbols(cfg))
        except Exception:
            logger.exception("EOD: daily IV append failed — iv_history may age")
    logger.info("Disconnected from IBKR")

    # 2. Compute realized P&L from DB fills (anchored to the ET trading day).
    today = datetime.now(_ET).date()
    realized_pnl, fill_count, fill_ids = _compute_realized_pnl(today)

    # 3. Load yesterday's baseline for unrealized delta.
    yesterday_unrealized = _load_yesterday_unrealized(today)

    # 4. Build the summary.
    watchlist = list(cfg.universe.get("watchlist", []))
    summary = _build_eod_summary(
        positions, account, realized_pnl, fill_count, yesterday_unrealized, watchlist
    )
    logger.info(
        "EODSummary: realized=%.2f unrealized=%.2f delta=%.2f fills=%d",
        summary.realized_pnl,
        summary.unrealized_pnl,
        summary.unrealized_pnl_delta,
        summary.fills_today,
    )

    # 5. Call Claude for a narrative (non-blocking on failure).
    narrative = write_journal_narrative(summary)

    # 6. Persist to DB.
    _write_journal(summary, narrative, fill_ids)

    # 6b. Reconcile the verdict outcome ledger (deterministic, DB-only). Attaches realized
    #     outcomes to closed trades so the enrichment layer accumulates labeled history.
    #     Assignment is auto-detected by diffing the prior position snapshot against today's
    #     positions (Phase 4) — a vanished short whose underlying stock moved ~100×contracts is
    #     assigned, not expired-worthless. Today's snapshot is then saved as tomorrow's baseline.
    try:
        from src.claude.eval.assignment import assigned_candidate_ids
        from src.claude.eval.reconcile import reconcile
        from src.storage.positions import save_position_snapshot

        assigned = assigned_candidate_ids(positions, today)
        reconcile(assigned_candidate_ids=assigned)
        save_position_snapshot(today, positions)
    except Exception:
        logger.exception("EOD: ledger reconciliation failed — continuing")

    # 7. Send Telegram.
    await _send_eod_telegram(summary, narrative)

    # 8. Prune the write-only option_quotes audit table so SQLite stays bounded.
    from src.storage.maintenance import backup_database, purge_old_option_quotes

    purge_old_option_quotes()

    # 9. Nightly backup of the system of record (orders, fills, learning history).
    backup_database()

    logger.info("EOD report complete")


def main() -> None:
    from src.common.logging import setup_logging

    setup_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
