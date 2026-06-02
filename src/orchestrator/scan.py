"""Full-pipeline scan orchestrator — shared by the Telegram /scan command and the morning cron.

Runs:
  1. IBKR: fetch positions + account
  2. Market data: option chains for universe ∪ holdings
  3. Analytics: IV, technicals, fundamentals per symbol
  4. Strategies: CC candidates (from holdings), CSP candidates (from would_own)
  5. Buy-to-own: score symbols not held from the would_own universe
  6. Risk engine: gate CC + CSP candidates
  7. Scoring: blended_score
  8. Claude: review with prior recommendation history injected
  9. Persist: CandidateRow, ClaudeReviewRow, ClaudeMemoryRow
 10. Notify: send CC/CSP as Approve/Reject messages; buy list as informational message
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date

from ib_async import IB

from src.analytics.fundamentals import get_fundamental_stats
from src.analytics.iv import get_iv_stats
from src.analytics.sentiment import SentimentScorer
from src.analytics.technicals import get_technical_stats
from src.claude.runner import review_candidates
from src.common.config import get_config
from src.common.schemas import (
    AccountSnapshot,
    BuyCandidate,
    ClaudeReview,
    FundamentalStats,
    IVStats,
    OptionQuote,
    PositionSnapshot,
    TechnicalStats,
    TradeCandidate,
)
from src.engine.decision_engine import select_top_candidates
from src.engine.risk_engine import validate_candidates
from src.engine.scoring import score_candidates
from src.ibkr.market_data import get_option_chain_quotes_async
from src.ibkr.portfolio import get_account_snapshot_async, get_positions
from src.notify.sender import send_buy_list, send_candidates
from src.storage.db import session_scope
from src.storage.models import CandidateRow, ClaudeMemoryRow, ClaudeReviewRow
from src.strategies.buy_candidates import generate_buy_candidates
from src.strategies.cash_secured_put import generate_csp_candidates
from src.strategies.covered_call import generate_cc_candidates

log = logging.getLogger(__name__)

_MEMORY_LOOKBACK_DAYS = 30

# ---------------------------------------------------------------------------
# Telegram progress tracker
# ---------------------------------------------------------------------------

_ProgressCB = Callable[[str], Awaitable[None]]

_STAGE_ORDER = ["account", "market_data", "scoring", "claude", "notify"]
_STAGE_LABELS = {
    "account": "Account & positions",
    "market_data": "Market data",
    "scoring": "Scoring & risk gate",
    "claude": "Claude review",
    "notify": "Sending results",
}


def _md2(s: str) -> str:
    """Escape a string for Telegram MarkdownV2."""
    for c in r"\_*[]()~`>#+-=|{}.!":
        s = s.replace(c, f"\\{c}")
    return s


class _Tracker:
    """Maintains stage state and fires an async callback with an updated progress message."""

    def __init__(self, cb: _ProgressCB | None) -> None:
        self._cb = cb
        # (icon, detail) — detail is already md2-escaped
        self._states: dict[str, tuple[str, str]] = {k: ("⬜", "") for k in _STAGE_ORDER}

    def _render(self, header: str = "🔍 *Scan in progress\\.\\.\\.*") -> str:
        lines = [header, ""]
        for key in _STAGE_ORDER:
            icon, detail = self._states[key]
            label = _md2(_STAGE_LABELS[key])
            lines.append(f"{icon} {label}" + (f" — {detail}" if detail else ""))
        return "\n".join(lines)

    async def tick(self, stage: str, icon: str, detail: str = "") -> None:
        self._states[stage] = (icon, _md2(detail) if detail else "")
        if self._cb is not None:
            try:
                await self._cb(self._render())
            except Exception:
                log.debug("Progress callback failed", exc_info=True)

    async def complete(self, cc: int, csp: int, buy: int) -> None:
        header = "🔍 *Scan complete*"
        self._states["notify"] = (
            "✅",
            _md2(f"{cc} CC · {csp} CSP · {buy} buy"),
        )
        if self._cb is not None:
            try:
                await self._cb(self._render(header))
            except Exception:
                log.debug("Progress complete callback failed", exc_info=True)


@dataclass
class ScanResult:
    cc_candidates: list[TradeCandidate] = field(default_factory=list)
    csp_candidates: list[TradeCandidate] = field(default_factory=list)
    buy_candidates: list[BuyCandidate] = field(default_factory=list)
    reviews: list[ClaudeReview] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------


def _load_memory(symbols: list[str]) -> list[ClaudeMemoryRow]:
    """Load recent ClaudeMemoryRow records for the given symbols."""
    from datetime import timedelta

    from sqlalchemy import select

    cutoff = date.today() - timedelta(days=_MEMORY_LOOKBACK_DAYS)
    try:
        with session_scope() as sess:
            rows = (
                sess.execute(
                    select(ClaudeMemoryRow)
                    .where(ClaudeMemoryRow.underlying.in_(symbols))
                    .where(ClaudeMemoryRow.scan_date >= cutoff)
                    .order_by(ClaudeMemoryRow.scan_date.desc())
                )
                .scalars()
                .all()
            )
            return list(rows)
    except Exception as exc:
        log.warning("Failed to load Claude memory: %s", exc)
        return []


def _persist_memory(
    candidates: list[TradeCandidate],
    buy_cands: list[BuyCandidate],
    reviews: list[ClaudeReview],
) -> None:
    """Write ClaudeMemoryRow entries for this scan. Outcomes start as None."""
    review_map = {r.candidate_id: r for r in reviews}
    today = date.today()
    rows: list[ClaudeMemoryRow] = []

    for cand in candidates:
        review = review_map.get(cand.candidate_id)
        rationale = ""
        recommendation = "skip"
        priority = 99
        confidence = None
        if review:
            rationale = f"{review.why_attractive} | Risks: {review.risks}"
            recommendation = review.recommendation
            priority = review.priority
            confidence = review.confidence
        rows.append(
            ClaudeMemoryRow(
                scan_date=today,
                underlying=cand.underlying,
                strategy_type=cand.strategy.value,
                recommendation=recommendation,
                priority=priority,
                confidence=confidence,
                rationale=rationale,
                candidate_id=cand.candidate_id,
            )
        )

    for buy in buy_cands:
        rows.append(
            ClaudeMemoryRow(
                scan_date=today,
                underlying=buy.symbol,
                strategy_type="buy_to_own",
                recommendation="buy",
                priority=99,
                confidence=None,
                rationale=buy.rationale or f"Score {buy.score:.0f}; IV rank {buy.iv_rank}",
                candidate_id=None,
            )
        )

    if rows:
        with session_scope() as sess:
            sess.add_all(rows)
        log.info("Persisted %d ClaudeMemoryRow entries", len(rows))


def _persist_candidates(
    candidates: list[TradeCandidate],
    reviews: list[ClaudeReview],
    run_id: str,
) -> None:
    """Persist CandidateRow + ClaudeReviewRow to DB.

    Uses upsert semantics for CandidateRow: if a row with the same candidate_id
    already exists (e.g. from a re-scan), the fresh data overwrites the stale one
    so _load_candidate() always returns the most recent scan's payload.
    """
    review_map = {r.candidate_id: r for r in reviews}
    with session_scope() as sess:
        for cand in candidates:
            # Delete any stale row with the same candidate_id before inserting fresh data.
            existing = (
                sess.query(CandidateRow)
                .filter(CandidateRow.candidate_id == cand.candidate_id)
                .first()
            )
            if existing is not None:
                sess.delete(existing)
                sess.flush()

            sess.add(
                CandidateRow(
                    candidate_id=cand.candidate_id,
                    run_id=run_id,
                    strategy=cand.strategy.value,
                    underlying=cand.underlying,
                    right=cand.right.value,
                    strike=cand.strike,
                    expiry=cand.expiry,
                    blended_score=cand.blended_score,
                    payload=cand.model_dump(mode="json"),
                )
            )
            review = review_map.get(cand.candidate_id)
            if review:
                sess.add(
                    ClaudeReviewRow(
                        candidate_id=review.candidate_id,
                        priority=review.priority,
                        recommendation=review.recommendation,
                        payload=review.model_dump(mode="json"),
                    )
                )


# ---------------------------------------------------------------------------
# Analytics helpers
# ---------------------------------------------------------------------------


def _fetch_analytics(
    symbol: str,
    quotes: list[OptionQuote] | None = None,
) -> tuple[IVStats, TechnicalStats, FundamentalStats]:
    # Pass the live chain so IV term-structure slope + put/call skew actually compute
    # (they are None without quotes).
    iv_stats = get_iv_stats(symbol, quotes)
    tech_stats = get_technical_stats(symbol)
    fund_stats = get_fundamental_stats(symbol)
    return iv_stats, tech_stats, fund_stats


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_scan(
    ib: IB,
    bot: object,
    chat_id: str,
    progress_callback: _ProgressCB | None = None,
) -> ScanResult:
    """Run the full pipeline. Returns ScanResult even on partial failures.

    Args:
        ib: A live, connected IB instance dedicated to market data for this scan.
        bot: telegram.Bot instance for sending results.
        chat_id: Telegram chat id to send results to.
        progress_callback: Optional async callable that receives a MarkdownV2 string and
            edits the in-chat progress message. Called at each stage transition.
    """
    cfg = get_config()
    result = ScanResult()
    tracker = _Tracker(progress_callback)

    # --- 1. Account + positions ---
    await tracker.tick("account", "⏳")
    try:
        managed = ib.managedAccounts()
        acct = cfg.secrets.ibkr_account or (managed[0] if managed else "")
        account: AccountSnapshot = await get_account_snapshot_async(ib, acct)
        positions: list[PositionSnapshot] = get_positions(ib)
    except Exception:
        log.exception("scan: failed to fetch account/positions — aborting")
        await tracker.tick("account", "❌", "failed")
        return result
    await tracker.tick("account", "✅")

    # --- 2. Symbol universe ---
    would_own: list[str] = cfg.universe.get("would_own", [])
    holdings_symbols: set[str] = {
        p.underlying or p.symbol for p in positions if p.sec_type == "STK" and p.position > 0
    }
    all_symbols: list[str] = sorted(set(would_own) | holdings_symbols)
    n = len(all_symbols)
    log.info(
        "scan: %d symbols to scan (%d holdings, %d universe)",
        n,
        len(holdings_symbols),
        len(would_own),
    )

    # --- 3. Sentiment scorer ---
    sentiment = SentimentScorer(
        client_id=cfg.secrets.reddit_client_id,
        client_secret=cfg.secrets.reddit_client_secret,
        user_agent=cfg.secrets.reddit_user_agent,
    )

    # --- 4. Per-symbol: market data + analytics + strategy candidates ---
    cc_candidates: list[TradeCandidate] = []
    csp_candidates: list[TradeCandidate] = []
    analytics_map: dict[str, tuple[IVStats, TechnicalStats, FundamentalStats]] = {}

    await tracker.tick("market_data", "⏳", f"0/{n} symbols")
    for i, symbol in enumerate(all_symbols):
        log.info("scan: processing %s", symbol)
        await tracker.tick("market_data", "⏳", f"{i + 1}/{n} — {symbol}")

        loop = asyncio.get_running_loop()

        # Option chain — IB calls run on the loop thread (async), NOT in a worker thread.
        # Chain fetches stay sequential per symbol to respect the ~100 market-data line cap.
        try:
            quotes: list[OptionQuote] = await get_option_chain_quotes_async(ib, symbol)
        except Exception:
            log.exception("scan: option chain failed for %s", symbol)
            quotes = []

        # Analytics (yfinance) and sentiment (Reddit) are independent external I/O — run them
        # concurrently in the default executor to cut per-symbol latency.
        analytics_res, sentiment_res = await asyncio.gather(
            loop.run_in_executor(None, _fetch_analytics, symbol, quotes),
            loop.run_in_executor(None, sentiment.score, symbol),
            return_exceptions=True,
        )
        if isinstance(analytics_res, BaseException):
            log.exception("scan: analytics failed for %s", symbol, exc_info=analytics_res)
            continue
        iv_stats, tech_stats, fund_stats = analytics_res
        sentiment_score = None if isinstance(sentiment_res, BaseException) else sentiment_res

        analytics_map[symbol] = (iv_stats, tech_stats, fund_stats)

        # CC candidates for held stock positions
        stock_pos = next(
            (
                p
                for p in positions
                if (p.underlying or p.symbol) == symbol and p.sec_type == "STK" and p.position > 0
            ),
            None,
        )
        if stock_pos and quotes:
            new_cc = generate_cc_candidates(
                symbol, quotes, stock_pos, iv_stats, tech_stats, fund_stats
            )
            # Inject sentiment score into ScoreCard
            for c in new_cc:
                c.scores.sentiment_score = sentiment_score
            cc_candidates.extend(new_cc)

        # CSP candidates for would_own symbols
        if symbol in would_own and quotes:
            new_csp = generate_csp_candidates(
                symbol, quotes, account, iv_stats, tech_stats, fund_stats
            )
            for c in new_csp:
                c.scores.sentiment_score = sentiment_score
            csp_candidates.extend(new_csp)

    await tracker.tick("market_data", "✅", f"{n}/{n} symbols")

    # --- 5. Buy-to-own recommendations ---
    result.buy_candidates = generate_buy_candidates(would_own, holdings_symbols, analytics_map)

    # --- 6. Scoring THEN risk gate ---
    # Score first so the risk engine consumes its cumulative budgets (per-ticker /
    # per-sector / total-CSP / buying-power) greedily in priority order.
    await tracker.tick("scoring", "⏳")
    all_option_candidates = cc_candidates + csp_candidates
    if all_option_candidates:
        scored = score_candidates(all_option_candidates)  # sorted DESC by blended_score
        verdicts = validate_candidates(scored, account, positions)
        verdict_map = {v.candidate_id: v for v in verdicts}
        passed = [
            c
            for c in scored
            if verdict_map.get(c.candidate_id)
            and verdict_map[c.candidate_id].verdict.value == "pass"
        ]
        log.info("scan: %d/%d candidates passed risk gate", len(passed), len(all_option_candidates))
        # Score floor: only surface candidates above the configured quality bar.
        min_score = cfg.weights.get("min_candidate_score", 0)
        passed = [c for c in passed if c.blended_score >= min_score]
        top = select_top_candidates(passed)
    else:
        top = []
        passed = []

    result.cc_candidates = [c for c in top if c.strategy.value == "covered_call"]
    result.csp_candidates = [c for c in top if c.strategy.value == "cash_secured_put"]
    await tracker.tick("scoring", "✅", f"{len(top)}/{len(all_option_candidates)} passed")

    # --- 7. Load prior Claude memory for history injection ---
    memory = _load_memory(all_symbols)

    # --- 8. Claude review ---
    await tracker.tick("claude", "⏳")
    if top:
        result.reviews = review_candidates(top, account, history=memory)
    log.info("scan: %d Claude reviews", len(result.reviews))
    await tracker.tick("claude", "✅", f"{len(result.reviews)} reviews")

    # --- 9. Persist ---
    _persist_candidates(top, result.reviews, result.run_id)
    _persist_memory(top, result.buy_candidates, result.reviews)

    # --- 10. Send to Telegram ---
    # send_candidates manages its own short DB transactions (no session held across the
    # Telegram network sends — that would block other processes writing the same SQLite DB).
    await tracker.tick("notify", "⏳")
    try:
        await send_candidates(result.cc_candidates + result.csp_candidates, result.reviews)
        await send_buy_list(result.buy_candidates, bot, chat_id)
    except Exception:
        log.exception("scan: failed to send Telegram messages")

    await tracker.complete(
        len(result.cc_candidates),
        len(result.csp_candidates),
        len(result.buy_candidates),
    )

    log.info(
        "scan complete — run_id=%s CC=%d CSP=%d buy=%d reviews=%d",
        result.run_id,
        len(result.cc_candidates),
        len(result.csp_candidates),
        len(result.buy_candidates),
        len(result.reviews),
    )
    return result
