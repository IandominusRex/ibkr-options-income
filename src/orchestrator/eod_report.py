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

from telegram import Bot

from src.claude.runner import write_journal_narrative
from src.common.config import get_config
from src.common.schemas import AccountSnapshot, EODSummary, PositionSnapshot
from src.ibkr.connection import IBKRConnection
from src.ibkr.portfolio import get_account_snapshot, get_positions
from src.notify.formatters import format_eod_summary
from src.storage.db import init_db, session_scope
from src.storage.models import FillRow, JournalRow

logger = logging.getLogger(__name__)


def _compute_realized_pnl(today: date) -> tuple[float, int, list[int]]:
    """Return (realized_pnl, fill_count, fill_ids) for today's option fills."""
    today_start = datetime(today.year, today.month, today.day, tzinfo=UTC)
    tomorrow_start = today_start + timedelta(days=1)
    with session_scope() as session:
        fills = (
            session.query(FillRow)
            .filter(FillRow.filled_at >= today_start, FillRow.filled_at < tomorrow_start)
            .all()
        )
        realized = sum(f.avg_price * f.filled_qty * 100 for f in fills)
        fill_ids = [f.id for f in fills]
    return realized, len(fill_ids), fill_ids


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

    # Net delta exposure: sum of delta * position * 100 for option positions.
    # delta is stored as the model-Greek value (e.g. 0.25 for long call).
    # Short positions have negative `position`, so the sign is automatic.
    net_delta = sum((p.delta or 0.0) * p.position * 100 for p in positions if p.sec_type == "OPT")

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

    # 1. Connect to IBKR and fetch portfolio data.
    with IBKRConnection("engine") as ib:
        positions = get_positions(ib)
        account = get_account_snapshot(ib, cfg.secrets.ibkr_account)
    logger.info("Disconnected from IBKR")

    # 2. Compute realized P&L from DB fills.
    today = date.today()
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

    # 7. Send Telegram.
    await _send_eod_telegram(summary, narrative)

    logger.info("EOD report complete")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
