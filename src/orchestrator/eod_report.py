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

from src.claude.eval.assignment import assigned_shorts
from src.claude.eval.reconcile import reconcile
from src.claude.runner import write_journal_narrative
from src.common.config import get_config
from src.common.market_hours import today_et
from src.common.schemas import AccountSnapshot, EODSummary, PositionSnapshot
from src.common.universe import effective_universe
from src.ibkr.connection import IBKRConnection
from src.ibkr.portfolio import (
    enrich_positions_with_greeks_async,
    get_account_snapshot_async,
    get_positions,
)
from src.notify.formatters import format_eod_summary
from src.storage.campaigns import mark_campaign_assigned
from src.storage.db import init_db, session_scope
from src.storage.models import FillRow, JournalRow
from src.storage.positions import save_position_snapshot

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def _today_et() -> date:
    """The current market-timezone (ET) calendar date.

    The journal is keyed on the ET trading day, so every date used to *write* a JournalRow must
    match the date used to *read* one back. The local wall-clock date can differ from ET (the EOD
    run typically fires next-morning local in UTC+8), so using `date.today()` to key the row while
    reading by ET silently breaks the yesterday→today baseline lookup — the unrealized Δ then
    collapses to the full unrealized value every day. Always anchor on ET.
    """
    return today_et()


# Per-request cap for the EOD IV backfill. ib_async's default reqHistoricalData timeout is ~60s;
# when IBKR's historical-data farm (HMDS) is down for a session, *every* symbol times out, turning
# a 2-minute EOD into a ~1-hour hang that blocks the (data-independent) P&L summary and Telegram
# send. We fail each request fast and trip a circuit breaker after a run of consecutive failures —
# a dead farm fails the same way for all symbols, so there is nothing to gain by grinding on.
_IV_REQUEST_TIMEOUT_S = 8.0
_IV_MAX_CONSECUTIVE_FAILURES = 5


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


def _universe_symbols() -> list[str]:
    """Indexes ∪ watchlist ∪ would_own — the symbols whose IV history we keep fresh."""
    u = effective_universe()
    return sorted(
        set(u.get("indexes", [])) | set(u.get("watchlist", [])) | set(u.get("would_own", []))
    )


async def _append_one_iv(ib, sym: str, timeout: float) -> bool:
    """Fetch and store one symbol's most recent daily IV bar. Returns True iff a new row was
    inserted. Exceptions propagate — the caller decides what a failure means (first-pass
    circuit-breaker bookkeeping, or a retry-pass outcome)."""
    from src.ibkr.contracts import qualify_stock_async
    from src.storage.iv_history import append_observation

    stock = await qualify_stock_async(ib, sym)
    bars = await asyncio.wait_for(
        ib.reqHistoricalDataAsync(
            stock,
            endDateTime="",
            durationStr="2 D",
            barSizeSetting="1 day",
            whatToShow="OPTION_IMPLIED_VOLATILITY",
            useRTH=True,
            keepUpToDate=False,
        ),
        timeout=timeout,
    )
    if not bars:
        return False
    last = bars[-1]
    bar_date = last.date if isinstance(last.date, date) else last.date.date()
    return append_observation(sym, bar_date, float(last.close))


def _iv_symbols(held: list[str]) -> list[str]:
    """Universe ∪ held symbols, never-observed first, then oldest observation first.

    Ordering by staleness (not alphabet) means a mid-run abort starves whichever names were
    freshest, not the same alphabetical tail every night (2026-09 TQQQ/UPRO/MAGS incident).
    """
    from src.storage.iv_history import latest_obs_dates

    symbols = sorted(set(_universe_symbols()) | {s.upper() for s in held})
    last = latest_obs_dates(symbols)
    return sorted(symbols, key=lambda s: (s in last, last.get(s, date.min), s))


async def _append_daily_iv(ib, symbols: list[str]) -> None:
    """Append today's ATM IV observation per symbol so the IV-rank window stays current (N4).

    Without this the only writer to `iv_history` is the one-shot bootstrap backfill, so the
    trailing-year window ages silently — and IV rank is both the largest score weight and a hard
    gate. Reuses the backfill's `OPTION_IMPLIED_VOLATILITY` daily bar; `append_observation` skips
    a date already present, so a re-run (or a second EOD) is idempotent. Best-effort per symbol.

    A run of consecutive failures no longer aborts the rest of *symbols* unconditionally — it
    used to, and a chronic single-symbol failure (a delisted ticker, a contract IBKR can't
    qualify) silently froze `iv_history` for every symbol alphabetically after it for a month
    (2026-09-11 incident: only AAPL/AMZN, first in sort order, kept updating past 2026-08-12).
    The failure run now triggers ``probe_market_data_health`` — a cheap, already-used check —
    to tell a genuinely dead farm (bail, as before) from a handful of bad symbols on an
    otherwise-healthy connection (log it, reset the counter, keep going).

    After the main pass, every symbol that failed (but did not trip the dead-farm abort) gets
    exactly one more attempt at double the per-request timeout — a single slow response
    (network blip, a momentarily busy farm) shouldn't leave a symbol stale for a whole day.
    A confirmed dead-farm abort skips the retry pass entirely: retrying symbols the health
    probe already told us can't succeed is exactly the grinding the breaker exists to avoid.
    """
    from src.ibkr.market_data import probe_market_data_health

    inserted = 0
    consecutive_failures = 0
    failed_symbols: list[str] = []
    aborted = False
    for sym in symbols:
        try:
            if await _append_one_iv(ib, sym, _IV_REQUEST_TIMEOUT_S):
                inserted += 1
            consecutive_failures = 0
        except Exception:
            logger.warning("EOD IV append failed for %s", sym, exc_info=True)
            consecutive_failures += 1
            failed_symbols.append(sym)
            if consecutive_failures >= _IV_MAX_CONSECUTIVE_FAILURES:
                probe = await probe_market_data_health(ib)
                if not probe.healthy:
                    # The farm itself is down (confirmed, not assumed) — every remaining
                    # symbol would burn the full per-request timeout for nothing. Bail so the
                    # (IV-independent) P&L summary and Telegram send are not delayed.
                    logger.warning(
                        "EOD: aborting IV append after %d consecutive failures — health probe "
                        "confirms the data farm is down (%s); iv_history will age until the "
                        "next run",
                        consecutive_failures,
                        probe.diagnosis or "unhealthy",
                    )
                    aborted = True
                    break
                # Connection is fine — this is a cluster of bad symbols, not a dead farm.
                # Skip them (already counted as failed) and keep going with the rest.
                logger.warning(
                    "EOD: %d consecutive IV-append failures (%s) but the health probe says "
                    "the connection is fine — treating as isolated bad symbols and continuing",
                    consecutive_failures,
                    ", ".join(failed_symbols[-consecutive_failures:]),
                )
                consecutive_failures = 0
        await asyncio.sleep(0.2)  # pace reqHistoricalData calls

    if not aborted and failed_symbols:
        retry_targets = list(dict.fromkeys(failed_symbols))  # de-dup, preserve order
        recovered = 0
        still_failed: list[str] = []
        for sym in retry_targets:
            try:
                if await _append_one_iv(ib, sym, _IV_REQUEST_TIMEOUT_S * 2):
                    inserted += 1
                recovered += 1
            except Exception:
                logger.warning("EOD IV retry failed for %s", sym, exc_info=True)
                still_failed.append(sym)
            await asyncio.sleep(0.2)
        logger.info("EOD: IV retry pass recovered %d/%d", recovered, len(retry_targets))
        failed_symbols = still_failed

    logger.info(
        "EOD: appended %d new IV observation(s) across %d symbols (%d failed: %s)",
        inserted,
        len(symbols),
        len(failed_symbols),
        ", ".join(failed_symbols) or "none",
    )


async def _append_daily_prices(symbols: list[str]) -> None:
    """Append today's settled daily OHLCV bar per symbol so the store stays current.

    The scan loader only persists bars strictly before *today* (the current session is still
    forming intraday); after the close those bars are final, so the EOD run captures today's
    settled bar here. yfinance is blocking, so each fetch runs in the default executor.
    `append_bars` skips dates already stored, so this is idempotent. Best-effort per symbol.
    """
    from src.analytics.price_data import _fetch_yf_bars
    from src.storage.price_history import append_bars

    loop = asyncio.get_running_loop()
    today = date.today()
    inserted = 0
    for sym in symbols:
        try:
            bars = await loop.run_in_executor(None, _fetch_yf_bars, sym, "5d")
            # Include today now that the session has settled; drop any future-dated rows.
            settled = [b for b in bars if b.obs_date <= today]
            inserted += await loop.run_in_executor(None, append_bars, sym, settled)
        except Exception:
            logger.debug("EOD price append failed for %s", sym, exc_info=True)
        await asyncio.sleep(0.05)
    logger.info("EOD: appended %d new daily price bar(s) across %d symbols", inserted, len(symbols))


def _load_yesterday_unrealized(today: date) -> float:
    """Return the unrealized_pnl from yesterday's JournalRow, or 0.0 if none."""
    yesterday = today - timedelta(days=1)
    with session_scope() as session:
        row = session.query(JournalRow).filter(JournalRow.entry_date == yesterday).first()
        return float(row.unrealized_pnl or 0.0) if row else 0.0


def _load_yesterday_watchlist(today: date) -> list[str] | None:
    """Return yesterday's `tomorrow_watchlist` from its JournalRow, or None if unavailable.

    Used to decide whether to reprint the (usually static) watchlist in full or collapse it to a
    count. None means "no prior entry" → treat as changed so the full list is shown.
    """
    yesterday = today - timedelta(days=1)
    with session_scope() as session:
        row = session.query(JournalRow).filter(JournalRow.entry_date == yesterday).first()
        if not row or not row.payload:
            return None
        wl = row.payload.get("eod_summary", {}).get("tomorrow_watchlist")
        return list(wl) if wl is not None else None


def _build_eod_summary(
    positions: list[PositionSnapshot],
    account: AccountSnapshot,
    realized_pnl: float,
    fill_count: int,
    yesterday_unrealized: float,
    watchlist: list[str],
    watchlist_changed: bool = True,
) -> EODSummary:
    """Compute EODSummary from live positions and DB history."""
    today = _today_et()

    unrealized_pnl = sum(p.unrealized_pnl or 0.0 for p in positions)
    unrealized_delta = unrealized_pnl - yesterday_unrealized

    # Net delta exposure across the full portfolio:
    #   Options: delta * contracts * 100 (position is contract count; negative = short)
    #   Stocks:  1.0 * shares (each share = 1 delta; negative = short stock)
    net_delta = sum((p.delta or 0.0) * p.position * 100 for p in positions if p.sec_type == "OPT")
    net_delta += sum(p.position for p in positions if p.sec_type == "STK")

    # Top movers / drivers: aggregate unrealized P&L by underlying across *all* sec_types (a stock
    # leg can be the day's largest swing — e.g. an assigned/wheeled position — so options-only would
    # leave the report's drivers line empty). Rank by absolute swing and keep the top 3.
    agg_pnl: dict[str, float] = {}
    for p in positions:
        if p.unrealized_pnl is None:
            continue
        sym = p.underlying or p.symbol
        agg_pnl[sym] = agg_pnl.get(sym, 0.0) + p.unrealized_pnl
    ranked = sorted(agg_pnl.items(), key=lambda kv: abs(kv[1]), reverse=True)[:3]
    top_movers_dedup = [sym for sym, _ in ranked]
    mover_pnl = {sym: pnl for sym, pnl in ranked}

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
        mover_pnl=mover_pnl,
        tomorrow_watchlist=watchlist,
        watchlist_changed=watchlist_changed,
    )


def _write_journal(summary: EODSummary, narrative: str | None, fill_ids: list[int]) -> None:
    """Upsert the journal row for summary.date (idempotent if the EOD run repeats).

    Deliberately mirrors src/storage/positions.py::save_position_snapshot, which is already
    idempotent for exactly this reason: an EOD run that repeats must not lose the steps that
    follow it (the reconciler, assignment auto-detection, tomorrow's position baseline).
    """
    payload = {
        "eod_summary": summary.model_dump(mode="json"),
        "fills": fill_ids,
    }
    with session_scope() as session:
        row = session.query(JournalRow).filter_by(entry_date=summary.date).first()
        if row is None:
            session.add(
                JournalRow(
                    entry_date=summary.date,
                    realized_pnl=summary.realized_pnl,
                    unrealized_pnl=summary.unrealized_pnl,
                    narrative=narrative,
                    payload=payload,
                )
            )
        else:
            # Every field is replaced except `created_at` (identity: when the day's row was
            # first written is real history, not something a re-run should overwrite).
            row.realized_pnl = summary.realized_pnl
            row.unrealized_pnl = summary.unrealized_pnl
            row.narrative = narrative
            row.payload = payload
    logger.info("JournalRow upserted for %s", summary.date)


async def _send_eod_telegram(summary: EODSummary, narrative: str | None) -> None:
    cfg = get_config()
    token = cfg.secrets.telegram_bot_token
    chat_id = cfg.secrets.telegram_chat_id

    if not token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping EOD send")
        return

    from src.notify.sender import thread_id

    thread_id_val = thread_id(cfg.secrets.telegram_thread_account)
    text = format_eod_summary(summary, narrative)
    try:
        async with Bot(token=token) as bot:
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id_val,
                text=text,
                parse_mode="MarkdownV2",
            )
        logger.info("EOD summary sent to Telegram (thread=%s)", thread_id_val)
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
        # Keep the IV-rank window current (N4) while the connection is open. Union in
        # currently-held stock symbols (not just the universe) so a position acquired
        # outside the watchlist/would-own lists still gets its IV tracked, and order by
        # staleness so a mid-run abort starves the freshest names, not the same
        # alphabetical tail every night.
        try:
            held = [p.symbol for p in positions if p.sec_type == "STK"]
            await _append_daily_iv(ib, _iv_symbols(held=held))
        except Exception:
            logger.exception("EOD: daily IV append failed — iv_history may age")
    logger.info("Disconnected from IBKR")

    # Capture today's settled daily close into price_history so tomorrow's first scan needs no
    # OHLCV fetch. Uses yfinance (the technical layer's source), not IBKR — runs after the
    # disconnect. Best-effort: a failure just means the next scan fetches the tail itself.
    try:
        await _append_daily_prices(_universe_symbols())
    except Exception:
        logger.exception("EOD: daily price append failed — price_history may age")

    # 2. Compute realized P&L from DB fills (anchored to the ET trading day).
    today = datetime.now(_ET).date()
    realized_pnl, fill_count, fill_ids = _compute_realized_pnl(today)

    # 3. Load yesterday's baseline for unrealized delta.
    yesterday_unrealized = _load_yesterday_unrealized(today)

    # 4. Build the summary.
    watchlist = list(effective_universe().get("watchlist", []))
    prev_watchlist = _load_yesterday_watchlist(today)
    watchlist_changed = prev_watchlist is None or prev_watchlist != watchlist
    summary = _build_eod_summary(
        positions,
        account,
        realized_pnl,
        fill_count,
        yesterday_unrealized,
        watchlist,
        watchlist_changed,
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
        assigned = assigned_shorts(positions, today)
        reconcile(assigned_candidate_ids={sh.candidate_id for sh in assigned})
        # C6: roll the assignment through to the wheel campaign so adjusted cost basis is
        # maintained (put assignment) / the campaign is flagged assigned (call assignment).
        for sh in assigned:
            mark_campaign_assigned(sh.underlying, assignment_price=sh.strike, right=sh.right)
        save_position_snapshot(today, positions)
    except Exception:
        logger.exception("EOD: ledger reconciliation failed — continuing")

    # 7. Send Telegram.
    await _send_eod_telegram(summary, narrative)

    # 8. Prune the write-only audit table so SQLite stays bounded. Forensics-only — no
    # production code reads it back, so a bounded window costs nothing operationally.
    # Also prune the intraday portfolio snapshots to the configured retention (P3-P4 M1)
    # — the web portfolio needs days of history, not years (a year needs a rollup).
    from src.storage.maintenance import backup_database
    from src.storage.portfolio_snapshots import prune_portfolio_snapshots
    from src.storage.risk_verdicts import purge_old_risk_verdicts

    purge_old_risk_verdicts()
    prune_portfolio_snapshots(get_config().storage.portfolio_snapshot_retention_days)

    # 9. Nightly backup of the system of record (orders, fills, learning history).
    backup_database()

    logger.info("EOD report complete")


def main() -> None:
    from src.common.logging import setup_logging

    setup_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
