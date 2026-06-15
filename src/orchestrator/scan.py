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
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from ib_async import IB

from src.analytics.fundamentals import get_fundamental_stats
from src.analytics.iv import get_iv_stats, infer_spot_from_quotes
from src.analytics.market_conditions import get_market_conditions
from src.analytics.sentiment import SentimentScorer
from src.analytics.technicals import _fetch_last_price, get_technical_stats
from src.claude.runner import review_candidates
from src.common.config import get_config
from src.common.market_hours import now_et_hhmm
from src.common.schemas import (
    AccountSnapshot,
    BuyCandidate,
    ClaudeReview,
    FundamentalStats,
    IVStats,
    MarketConditions,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    TechnicalStats,
    TradeCandidate,
)
from src.engine.decision_engine import select_top_candidates
from src.engine.risk_engine import validate_candidates
from src.engine.scoring import score_candidates
from src.ibkr.market_data import get_option_chain_quotes_async, persist_chain_quotes
from src.ibkr.portfolio import get_account_snapshot_async, get_positions
from src.notify.formatters import format_data_provenance
from src.notify.sender import send_buy_list, send_candidates
from src.storage.db import session_scope
from src.storage.models import CandidateRow, ClaudeMemoryRow, ClaudeReviewRow
from src.storage.scan_state import get_scan_state, upsert_scan_state
from src.storage.system_settings import (
    acquire_scan_lease,
    get_setting,
    release_scan_lease,
    renew_scan_lease,
    set_setting,
)
from src.strategies.buy_candidates import generate_buy_candidates
from src.strategies.cash_secured_put import generate_csp_candidates
from src.strategies.covered_call import generate_cc_candidates

log = logging.getLogger(__name__)

_MEMORY_LOOKBACK_DAYS = 30
# N9 — bound the memory injected into each prompt. Without a cap, 30 days × every 15-min
# scan's surfaced candidates balloons into thousands of history lines per prompt (cost,
# latency, and an echo chamber of Claude's own prior prose). Keep only the most useful few
# rows per symbol, outcomes first.
_MEMORY_ROWS_PER_SYMBOL = 3

# S5 — system_settings key holding a content hash of the prior cycle's top-candidate signal
# vectors. When this cycle's hash matches, the intraday loop skips the `claude -p` subprocess
# and reuses the persisted ClaudeReviews — enrichment-only, never touches gating (the fence).
_REVIEW_HASH_KEY = "last_review_hash"

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

# Fraction of total wall-clock each stage occupies — used to drive the dashboard progress
# bar + ETA. Market data (per-symbol option chains) dominates a scan, hence the wide span.
_STAGE_SPAN: dict[str, tuple[float, float]] = {
    "account": (0.00, 0.05),
    "market_data": (0.05, 0.85),
    "scoring": (0.85, 0.89),
    "claude": (0.89, 0.98),
    "notify": (0.98, 1.00),
}

# Minimum seconds between throttled dashboard pushes (per-symbol updates). Stage changes,
# errors, and completion always flush immediately regardless of this guard.
_DASHBOARD_MIN_INTERVAL = 2.0
_BAR_CELLS = 10


def _md2(s: str) -> str:
    """Escape a string for Telegram MarkdownV2."""
    for c in r"\_*[]()~`>#+-=|{}.!":
        s = s.replace(c, f"\\{c}")
    return s


def _fmt_eta(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"~{s}s left"
    return f"~{s // 60}m {s % 60}s left"


class _Tracker:
    """Drives two Telegram messages for a scan:

    1. the *checklist* (one line per pipeline stage with a status icon), and
    2. the *dashboard* (a progress bar + ETA, a current-activity line, and a running log of
       errors flagged in red).

    Each is edited in place through its own async callback. Either callback may be ``None``
    (e.g. the 15-min daemon loop runs the scan silently).
    """

    def __init__(
        self,
        checklist_cb: _ProgressCB | None,
        dashboard_cb: _ProgressCB | None = None,
    ) -> None:
        self._checklist_cb = checklist_cb
        self._dashboard_cb = dashboard_cb
        self._failed = False
        self._done = False
        # (icon, detail) — detail is already md2-escaped
        self._states: dict[str, tuple[str, str]] = {k: ("⬜", "") for k in _STAGE_ORDER}
        # Dashboard state
        self._pct = 0.0
        self._status = "Starting scan…"
        self._errors: list[str] = []
        self._t0 = time.monotonic()
        self._last_push = 0.0

    # -- checklist (message 1) -------------------------------------------------
    def _render_checklist(self, header: str | None = None) -> str:
        if header is None:
            header = "🔍 *Scan failed*" if self._failed else "🔍 *Scan in progress\\.\\.\\.*"
        lines = [header, ""]
        for key in _STAGE_ORDER:
            icon, detail = self._states[key]
            label = _md2(_STAGE_LABELS[key])
            lines.append(f"{icon} {label}" + (f" — {detail}" if detail else ""))
        return "\n".join(lines)

    # -- dashboard (message 2) -------------------------------------------------
    def _render_dashboard(self) -> str:
        pct = max(0.0, min(1.0, self._pct))
        filled = round(pct * _BAR_CELLS)
        bar = "▰" * filled + "▱" * (_BAR_CELLS - filled)

        if self._done:
            title, pct_txt, eta = "Scan complete", "100%", ""
        elif self._failed:
            title, pct_txt = "Scan failed", f"{int(pct * 100)}%"
            eta = ""
        else:
            title, pct_txt = "Scanning…", f"{int(pct * 100)}%"
            elapsed = time.monotonic() - self._t0
            eta = _fmt_eta(elapsed * (1 - pct) / pct) if 0.02 < pct < 1.0 else ""

        lines = [f"🔍 *{title}* {pct_txt}", f"{bar}" + (f"  {_md2(eta)}" if eta else ""), ""]
        lines.append(f"⚙️ {_md2(self._status)}")
        if self._errors:
            lines.append("")
            lines.append(f"🔴 *Errors \\({len(self._errors)}\\)*")
            for e in self._errors:
                lines.append(f"🔴 {_md2(e)}")
        return "\n".join(lines)

    # -- push mechanics --------------------------------------------------------
    async def _push(self, *, force: bool = False, checklist: bool = True) -> None:
        now = time.monotonic()
        if not force and (now - self._last_push) < _DASHBOARD_MIN_INTERVAL:
            return
        self._last_push = now
        if checklist and self._checklist_cb is not None:
            try:
                header = "🔍 *Scan complete*" if self._done else None
                await self._checklist_cb(self._render_checklist(header))
            except Exception:
                log.debug("Checklist callback failed", exc_info=True)
        if self._dashboard_cb is not None:
            try:
                await self._dashboard_cb(self._render_dashboard())
            except Exception:
                log.debug("Dashboard callback failed", exc_info=True)

    def _stage_pct(self, stage: str, frac: float) -> float:
        lo, hi = _STAGE_SPAN[stage]
        return lo + (hi - lo) * max(0.0, min(1.0, frac))

    # -- public API ------------------------------------------------------------
    async def tick(self, stage: str, icon: str, detail: str = "") -> None:
        self._states[stage] = (icon, _md2(detail) if detail else "")
        # Position the bar: ⏳ → stage start, ✅ → stage end.
        self._pct = self._stage_pct(stage, 1.0 if icon == "✅" else 0.0)
        self._status = f"{_STAGE_LABELS[stage]}…"
        await self._push(force=True)

    async def mark_symbol(self, i: int, n: int, symbol: str) -> None:
        """Per-symbol market-data progress (throttled)."""
        frac = (i / n) if n else 0.0
        self._pct = self._stage_pct("market_data", frac)
        self._states["market_data"] = ("⏳", _md2(f"{i}/{n} — {symbol}"))
        self._status = f"Option chain — {symbol} ({i}/{n})"
        await self._push()

    async def add_error(self, message: str) -> None:
        self._errors.append(message)
        await self._push(force=True, checklist=False)

    async def error(self, stage: str, detail: str = "") -> None:
        """Mark a stage as failed and flip both messages to the failed state."""
        self._failed = True
        self._states[stage] = ("❌", _md2(detail) if detail else "")
        if detail:
            self._errors.append(f"{_STAGE_LABELS.get(stage, stage)}: {detail}")
        await self._push(force=True)

    async def complete(self, cc: int, csp: int, buy: int, vix: float | None = None) -> None:
        vix_str = f" · VIX {vix:.1f}" if vix is not None else ""
        self._states["notify"] = ("✅", _md2(f"{cc} CC · {csp} CSP · {buy} buy{vix_str}"))
        self._done = True
        self._pct = 1.0
        self._status = f"Done — {cc} CC · {csp} CSP · {buy} buy{vix_str}"
        await self._push(force=True)


@dataclass
class ProvenanceCounts:
    """Tallies of where this cycle's data actually came from — surfaced in the end-of-scan
    Telegram summary so an operator can see at a glance which sources were live vs. fell back.
    """

    chain_ibkr: int = 0  # option chain fetched successfully from IBKR
    chain_failed: int = 0  # chain fetch attempted but timed out / errored
    chain_skipped: int = 0  # not material this cycle — chain fetch skipped (intraday gate)
    spot_ibkr: int = 0  # spot price inferred from the live IBKR chain (put-call parity)
    spot_yfinance: int = 0  # spot price from yfinance fast_info (no chain / parity unavailable)
    spot_unavailable: int = 0  # neither source produced a usable price
    greeks_ibkr: int = 0  # option quotes whose Greeks came from IBKR model Greeks / BS-on-IBKR-IV
    greeks_yfinance: int = 0  # option quotes whose Greeks fell back to yfinance Black-Scholes
    vix_available: bool = False


@dataclass
class ScanResult:
    cc_candidates: list[TradeCandidate] = field(default_factory=list)
    csp_candidates: list[TradeCandidate] = field(default_factory=list)
    buy_candidates: list[BuyCandidate] = field(default_factory=list)
    reviews: list[ClaudeReview] = field(default_factory=list)
    market_conditions: MarketConditions = field(default_factory=MarketConditions)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    # True when this scan was skipped because another process held the scan lease (F5).
    lease_skipped: bool = False
    # Intraday telemetry (S1/S5/S6): how many symbols were fetched this cycle vs the universe
    # size, whether the Claude review was reused, and whether the cycle ended silently and so
    # emitted a quiet-cycle heartbeat instead of any card/buy-list message.
    total_symbols: int = 0
    material_count: int = 0
    reused_reviews: bool = False
    quiet_cycle: bool = False
    # Data-provenance counters for the end-of-scan summary: where each piece of data this
    # cycle actually came from, and how many symbols/quotes fell back to a secondary source.
    provenance: ProvenanceCounts = field(default_factory=lambda: ProvenanceCounts())


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
    except Exception as exc:
        log.warning("Failed to load Claude memory: %s", exc)
        return []

    # Cap per symbol (N9): rows arrive most-recent-first; a stable sort that floats rows with
    # a recorded outcome to the top means we keep the few most informative ("what actually
    # happened") observations rather than a wall of repeated open recommendations.
    by_symbol: dict[str, list[ClaudeMemoryRow]] = {}
    for r in rows:
        by_symbol.setdefault(r.underlying, []).append(r)
    capped: list[ClaudeMemoryRow] = []
    for sym_rows in by_symbol.values():
        sym_rows.sort(key=lambda r: r.outcome is None)  # outcomes (not None) first; stable
        capped.extend(sym_rows[:_MEMORY_ROWS_PER_SYMBOL])
    return capped


def _persist_memory(
    candidates: list[TradeCandidate],
    buy_cands: list[BuyCandidate],
    reviews: list[ClaudeReview],
) -> None:
    """Upsert one ClaudeMemoryRow per (symbol, strategy, day). Outcomes start as None.

    Deduped per (underlying, strategy_type, scan_date) (N9): the 15-min loop re-surfaces the
    same names ~26×/day, so a naive insert wrote hundreds of near-identical rows daily. Keeping
    one row per symbol+strategy+day — refreshed with the best (highest-ranked) candidate's
    verdict — collapses that volume while preserving the day's view. A recorded `outcome` is
    never clobbered (it's back-filled by candidate_id in claude/memory.py).
    """
    review_map = {r.candidate_id: r for r in reviews}
    today = date.today()
    written = 0

    with session_scope() as sess:

        def _upsert(
            underlying: str,
            strategy_type: str,
            recommendation: str,
            priority: int,
            confidence: float | None,
            rationale: str,
            candidate_id: str | None,
        ) -> None:
            nonlocal written
            existing = (
                sess.query(ClaudeMemoryRow)
                .filter(
                    ClaudeMemoryRow.scan_date == today,
                    ClaudeMemoryRow.underlying == underlying,
                    ClaudeMemoryRow.strategy_type == strategy_type,
                )
                .first()
            )
            if existing is not None:
                existing.recommendation = recommendation
                existing.priority = priority
                existing.confidence = confidence
                existing.rationale = rationale
                existing.candidate_id = candidate_id  # link the latest scan's best candidate
                return
            sess.add(
                ClaudeMemoryRow(
                    scan_date=today,
                    underlying=underlying,
                    strategy_type=strategy_type,
                    recommendation=recommendation,
                    priority=priority,
                    confidence=confidence,
                    rationale=rationale,
                    candidate_id=candidate_id,
                )
            )
            written += 1

        # `candidates` is score-sorted desc; keep the first (best) per key this scan so a later,
        # lower-ranked strike for the same symbol+strategy doesn't overwrite it.
        seen: set[tuple[str, str]] = set()
        for cand in candidates:
            key = (cand.underlying, cand.strategy.value)
            if key in seen:
                continue
            seen.add(key)
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
            _upsert(
                cand.underlying,
                cand.strategy.value,
                recommendation,
                priority,
                confidence,
                rationale,
                cand.candidate_id,
            )

        for buy in buy_cands:
            key = (buy.symbol, "buy_to_own")
            if key in seen:
                continue
            seen.add(key)
            _upsert(
                buy.symbol,
                "buy_to_own",
                "buy",
                99,
                None,
                buy.rationale or f"Score {buy.score:.0f}; IV rank {buy.iv_rank}",
                None,
            )

    log.info("Persisted/updated ClaudeMemoryRow entries (%d new) for %s", written, today)


def _signal_vector(c: TradeCandidate, vix: float | None) -> dict:
    """The signal snapshot Claude saw for this candidate — frozen into the outcome ledger."""
    return {
        "blended_score": c.blended_score,
        "iv_rank": c.iv_rank,
        "delta": c.delta,
        "vrp": c.vrp,
        "prob_otm": c.prob_otm,
        "roc_pct": c.roc_pct,
        "annualized_yield_pct": c.annualized_yield_pct,
        "dte": c.dte,
        "premium": c.premium,
        "scores": {
            "iv": c.scores.iv_score,
            "technical": c.scores.technical_score,
            "fundamental": c.scores.fundamental_score,
            "liquidity": c.scores.liquidity_score,
            "assignment_safety": c.scores.assignment_safety_score,
            "sentiment": c.scores.sentiment_score,
        },
        "rationale_tags": list(c.rationale_tags),
        "vix": vix,
    }


def _candidates_review_hash(top: list[TradeCandidate], vix: float | None) -> str:
    """Stable content hash of the top candidates' signal vectors (S5).

    Keyed on each candidate's deterministic ``candidate_id`` + the exact signal snapshot Claude
    would see. If two consecutive cycles produce the same hash, the LLM review would be identical,
    so the intraday loop can reuse the prior ``ClaudeReview`` instead of re-invoking ``claude -p``.
    """
    payload = sorted(((c.candidate_id, _signal_vector(c, vix)) for c in top), key=lambda x: x[0])
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _load_prior_reviews(candidate_ids: list[str]) -> dict[str, ClaudeReview]:
    """Load the most recent persisted ClaudeReview per candidate_id (S5 reuse path).

    Returns only the ids that have a parseable prior review, so the caller can require a complete
    set before reusing (a partial set falls back to a fresh review).
    """
    out: dict[str, ClaudeReview] = {}
    try:
        with session_scope() as s:
            for cid in candidate_ids:
                row = (
                    s.query(ClaudeReviewRow)
                    .filter_by(candidate_id=cid)
                    .order_by(ClaudeReviewRow.id.desc())
                    .first()
                )
                if row and row.payload:
                    try:
                        out[cid] = ClaudeReview.model_validate(row.payload)
                    except Exception:
                        log.debug("S5: prior review for %s unparseable — will re-review", cid)
    except Exception:
        log.warning("S5: failed to load prior reviews — running a fresh review", exc_info=True)
    return out


def _persist_ledger(
    top: list[TradeCandidate],
    reviews: list[ClaudeReview],
    market_conditions: MarketConditions,
    run_id: str,
) -> None:
    """Write the outcome ledger for this scan: one VerdictRecord per surfaced candidate,
    capturing the signals Claude saw, its verdict, and the deterministic baseline. Outcomes
    are back-filled later by the reconciler. Enrichment-only — never gates anything.
    """
    if not top:
        return
    from src.claude.eval.baseline import baseline_decisions
    from src.claude.eval.ledger import record_verdicts
    from src.common.schemas import VerdictRecord

    review_map = {r.candidate_id: r for r in reviews}
    baselines = baseline_decisions(top)
    vix = market_conditions.vix if market_conditions else None
    today = date.today()
    records: list[VerdictRecord] = []
    for c in top:
        review = review_map.get(c.candidate_id)
        base = baselines.get(c.candidate_id)
        claude_rec = review.recommendation if review else "none"
        baseline_rec = base.recommendation if base else "skip"
        # Agreement: did Claude choose to trade where the baseline did (both "sell" or neither)?
        agreement: bool | None = None
        if review is not None and base is not None:
            agreement = (claude_rec == "sell") == (baseline_rec == "sell")
        records.append(
            VerdictRecord(
                candidate_id=c.candidate_id,
                run_id=run_id,
                scan_date=today,
                underlying=c.underlying,
                strategy=c.strategy,
                right=c.right,
                strike=c.strike,
                expiry=c.expiry,
                dte=c.dte,
                signals=_signal_vector(c, vix),
                claude_recommendation=claude_rec,
                claude_priority=review.priority if review else None,
                claude_confidence=review.confidence if review else None,
                claude_rationale=(
                    f"{review.why_attractive} | Risks: {review.risks}" if review else ""
                ),
                baseline_recommendation=baseline_rec,
                baseline_rank=base.rank if base else None,
                baseline_score=base.score if base else c.blended_score,
                agreement=agreement,
            )
        )
    record_verdicts(records)


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


async def _compute_material_symbols(
    all_symbols: list[str],
    holdings_symbols: set[str],
    would_own: list[str],
) -> tuple[set[str], dict[str, float]]:
    """Decide which symbols need a fresh option-chain fetch this intraday cycle (S1).

    Returns ``(material, probed_spots)``:
      - ``material`` is the subset of *all_symbols* that are *material*:
          (a) every held stock position — CC / profit-take / roll need fresh quotes;
          (b) every ``would_own`` name whose live spot has drifted ≥
              ``market_data.intraday_rescan_move_pct`` from the spot at its last fetch;
          (c) every name that cleared the score floor last cycle.
        Plus a periodic full sweep when the oldest fetched symbol is older than
        ``force_full_scan_minutes`` (or when no state exists yet, e.g. the first intraday cycle).
      - ``probed_spots`` is the live yfinance price fetched while checking (b), keyed by
        symbol. Immaterial symbols skip the option chain and therefore have no chain-derived
        spot — the caller reuses this probe price as ``spot_override`` so
        ``get_technical_stats`` doesn't pay for a second identical ``fast_info`` fetch (S1
        follow-up).

    Only ever *narrows* the set — callers in full-sweep mode (morning cron, manual ``/scan``)
    must not call this and instead fetch every symbol. Pure read; never raises.
    """
    cfg = get_config()
    states = get_scan_state(all_symbols)

    # No baseline yet (first intraday cycle after a cold start) → sweep everything to seed it.
    if not states:
        return set(all_symbols), {}

    # Periodic safety-net full sweep: if the stalest fetched symbol is too old, refresh all.
    force_minutes = cfg.market_data.force_full_scan_minutes
    if force_minutes > 0:
        stamps = [s.last_scanned_at for s in states.values() if s.last_scanned_at]
        oldest = min(stamps) if stamps else None
        # SQLite drops tzinfo on round-trip; last_scanned_at was stored as datetime.now(UTC),
        # so a naive value here is UTC — reattach tzinfo before comparing.
        if oldest is not None and oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=UTC)
        if oldest is None or (datetime.now(UTC) - oldest).total_seconds() > force_minutes * 60:
            return set(all_symbols), {}

    material: set[str] = set(holdings_symbols)  # (a)
    material |= {sym for sym, st in states.items() if st.cleared_floor}  # (c)

    # (b) would_own names whose live spot moved past the threshold. fast_info is a cheap
    # single quote (no option chain); fan out so the materiality probe stays sub-second.
    move_pct = cfg.market_data.intraday_rescan_move_pct
    to_probe = [s for s in would_own if s not in material]
    loop = asyncio.get_running_loop()
    prices = await asyncio.gather(
        *(loop.run_in_executor(None, _fetch_last_price, s) for s in to_probe),
        return_exceptions=True,
    )
    probed_spots: dict[str, float] = {}
    for sym, price in zip(to_probe, prices, strict=True):
        if not isinstance(price, BaseException) and price is not None:
            probed_spots[sym] = price
        st = states.get(sym)
        # No baseline, no price, or a non-positive last_spot → fetch to (re)establish one.
        if (
            isinstance(price, BaseException)
            or price is None
            or st is None
            or not st.last_spot
            or st.last_spot <= 0
        ):
            material.add(sym)
            continue
        if abs(price - st.last_spot) / st.last_spot >= move_pct:
            material.add(sym)

    return material, probed_spots


def _persist_scan_state(
    fetched_spots: dict[str, float],
    cleared_floor_symbols: set[str],
    scanned_at: datetime,
) -> None:
    """Write the per-symbol materiality baseline for every fetched symbol (S1/S10). Off-thread."""
    for symbol, spot in fetched_spots.items():
        upsert_scan_state(
            symbol,
            last_spot=spot,
            last_scanned_at=scanned_at,
            cleared_floor=symbol in cleared_floor_symbols,
        )


async def _send_quiet_heartbeat(bot: object, chat_id: str, result: ScanResult) -> None:
    """Send the intraday quiet-cycle heartbeat (S6). Best-effort; never raises.

    Called only when an ``intraday`` cycle surfaced nothing — no candidate cleared the gate and
    the buy list was unchanged, so neither ``send_candidates`` nor ``send_buy_list`` emitted a
    message. Without this the operator sees total silence and can't distinguish a deliberately
    quiet market from a dead daemon. Reuses the same ``bot``/``chat_id`` as the buy-list send.
    """
    if bot is None or not chat_id:
        return
    from src.notify.formatters import format_quiet_cycle

    skipped = max(0, result.total_symbols - result.material_count)
    vix = result.market_conditions.vix if result.market_conditions else None
    try:
        await bot.send_message(  # type: ignore[attr-defined]
            chat_id=chat_id,
            text=format_quiet_cycle(
                skipped=skipped,
                total=result.total_symbols,
                move_pct=get_config().market_data.intraday_rescan_move_pct,
                vix=vix,
                at=now_et_hhmm(),
            ),
            parse_mode="MarkdownV2",
        )
        result.quiet_cycle = True
        log.info(
            "scan: quiet intraday cycle — sent heartbeat (%d/%d names below the move threshold)",
            skipped,
            result.total_symbols,
        )
    except Exception:
        log.warning("scan: failed to send quiet-cycle heartbeat", exc_info=True)


def _fetch_analytics(
    symbol: str,
    quotes: list[OptionQuote] | None = None,
    spot_override: float | None = None,
    cached_yf_price: float | None = None,
) -> tuple[IVStats, TechnicalStats, FundamentalStats]:
    # Pass the live chain so IV term-structure slope + put/call skew actually compute
    # (they are None without quotes).
    iv_stats = get_iv_stats(symbol, quotes)
    tech_stats = get_technical_stats(
        symbol, spot_override=spot_override, cached_yf_price=cached_yf_price
    )
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
    dashboard_callback: _ProgressCB | None = None,
    *,
    intraday: bool = False,
) -> ScanResult:
    """Run the full pipeline under a cross-process scan lease (SYSTEM_REVIEW F5).

    ``intraday=True`` (the 15-min loop) enables the S1 materiality gate: only held positions,
    materially-moved ``would_own`` names, and names that cleared the score floor last cycle get
    a fresh option-chain fetch; everything else is skipped this cycle. The morning cron and
    manual ``/scan`` leave it ``False`` and always sweep the full universe.

    A full chain scan consumes most of the account-level ~100 market-data line cap, so two
    concurrent scans (e.g. the morning cron and the 15-min daemon loop, in separate
    processes) would poison each other. The lease serialises them; a scan that can't acquire
    it returns an empty result with ``lease_skipped=True`` rather than competing for lines.

    Args:
        progress_callback: edits the *checklist* message (one line per stage).
        dashboard_callback: edits the *dashboard* message (progress bar + ETA + status +
            running error log). Either may be ``None`` (the 15-min loop runs silently).
    """
    lease_token = acquire_scan_lease()
    if lease_token is None:
        log.warning("scan: another scan holds the lease — skipping this run (F5)")
        result = ScanResult()
        result.lease_skipped = True
        return result
    try:
        return await _run_scan_body(
            ib,
            bot,
            chat_id,
            progress_callback,
            dashboard_callback=dashboard_callback,
            lease_token=lease_token,
            intraday=intraday,
        )
    finally:
        # Compare-and-swap release: only clears the lease if we still hold it, so a scan that
        # overran its TTL (and was re-claimed) can't zero out the new holder's lease (N7).
        release_scan_lease(lease_token)


async def _run_scan_body(
    ib: IB,
    bot: object,
    chat_id: str,
    progress_callback: _ProgressCB | None = None,
    dashboard_callback: _ProgressCB | None = None,
    lease_token: str | None = None,
    intraday: bool = False,
) -> ScanResult:
    """Run the full pipeline. Returns ScanResult even on partial failures.

    Args:
        ib: A live, connected IB instance dedicated to market data for this scan.
        bot: telegram.Bot instance for sending results.
        chat_id: Telegram chat id to send results to.
        progress_callback: Optional async callable that edits the checklist message.
        dashboard_callback: Optional async callable that edits the progress-bar dashboard.
    """
    cfg = get_config()
    result = ScanResult()
    tracker = _Tracker(progress_callback, dashboard_callback)

    # --- 0. Market conditions (VIX) — fetched once, off-thread ---
    loop = asyncio.get_running_loop()
    try:
        result.market_conditions = await loop.run_in_executor(None, get_market_conditions)
        if result.market_conditions.vix is not None:
            log.info("scan: VIX=%.2f", result.market_conditions.vix)
            result.provenance.vix_available = True
    except Exception:
        log.warning("scan: failed to fetch market conditions")

    # --- 1. Account + positions ---
    await tracker.tick("account", "⏳")
    try:
        managed = ib.managedAccounts()
        acct = cfg.secrets.ibkr_account or (managed[0] if managed else "")
        account: AccountSnapshot = await get_account_snapshot_async(ib, acct)
        positions: list[PositionSnapshot] = get_positions(ib)
    except Exception:
        log.exception("scan: failed to fetch account/positions — aborting")
        await tracker.error("account", "fetch failed — aborting")
        return result
    await tracker.tick("account", "✅")

    # --- 2. Symbol universe ---
    would_own: list[str] = cfg.universe.get("would_own", [])
    holdings_symbols: set[str] = {
        p.underlying or p.symbol for p in positions if p.sec_type == "STK" and p.position > 0
    }
    all_symbols: list[str] = sorted(set(would_own) | holdings_symbols)
    n = len(all_symbols)
    result.total_symbols = n
    log.info(
        "scan: %d symbols to scan (%d holdings, %d universe)",
        n,
        len(holdings_symbols),
        len(would_own),
    )

    # N15: any symbol missing from universe.yaml `sectors:` silently escapes the per-sector
    # concentration cap (the risk engine can't bucket it). Warn loudly so the gap is visible.
    sectors_map = cfg.universe.get("sectors", {})
    unmapped = sorted(s for s in all_symbols if s not in sectors_map)
    if unmapped:
        log.warning(
            "scan: %d symbol(s) missing from universe.yaml `sectors:` — they bypass the "
            "per-sector concentration cap: %s",
            len(unmapped),
            unmapped,
        )

    # --- 3. Sentiment scorer ---
    sentiment = SentimentScorer(
        client_id=cfg.secrets.reddit_client_id,
        client_secret=cfg.secrets.reddit_client_secret,
        user_agent=cfg.secrets.reddit_user_agent,
    )

    # --- 3b. Intraday materiality gate (S1) ---
    # Full-sweep modes (morning cron, manual /scan) fetch every symbol; the 15-min loop fetches
    # only material ones and skips the rest, sparing the dominant option-chain cost.
    if intraday:
        material_symbols, probed_spots = await _compute_material_symbols(
            all_symbols, holdings_symbols, would_own
        )
        log.info(
            "scan: intraday materiality gate — %d/%d symbols material: %s",
            len(material_symbols),
            n,
            sorted(material_symbols),
        )
    else:
        material_symbols = set(all_symbols)
        probed_spots = {}
    result.material_count = len(material_symbols)

    # --- 4. Per-symbol: market data + analytics + strategy candidates ---
    cc_candidates: list[TradeCandidate] = []
    csp_candidates: list[TradeCandidate] = []
    analytics_map: dict[str, tuple[IVStats, TechnicalStats, FundamentalStats]] = {}
    fetched_spots: dict[str, float] = {}  # symbols whose chain we fetched → scan_state baseline

    await tracker.tick("market_data", "⏳", f"0/{n} symbols")
    for i, symbol in enumerate(all_symbols):
        log.info("scan: processing %s", symbol)
        await tracker.mark_symbol(i + 1, n, symbol)

        # Heartbeat: extend the scan lease each iteration so a full ~60-symbol scan can't
        # outlive the TTL and let a second scan start mid-run (N7). CAS — if we've lost the
        # lease there's nothing to renew (we keep going; release will no-op safely).
        renew_scan_lease(lease_token)

        # Option chain — IB calls run on the loop thread (async), NOT in a worker thread.
        # Chain fetches stay sequential per symbol to respect the ~100 market-data line cap.
        # Bounded by symbol_timeout_seconds: an IBKR call that never responds (pacing
        # violation, competing-session lockout) must not hang the whole scan — skip the
        # symbol (quotes=[]) and move on so the remaining symbols and the Telegram send
        # step still run.
        symbol_start = time.monotonic()
        quotes: list[OptionQuote]
        did_fetch = symbol in material_symbols
        if not did_fetch:
            # Intraday gate (S1): immaterial this cycle (not held, spot unmoved, didn't clear
            # the floor last cycle). Skip the dominant option-chain fetch; analytics below still
            # run (cheap/day-cached) so the buy-to-own list stays complete.
            quotes = []
            result.provenance.chain_skipped += 1
            log.debug("scan: skipping option chain for %s (immaterial this intraday cycle)", symbol)
        else:
            try:
                quotes = await asyncio.wait_for(
                    get_option_chain_quotes_async(ib, symbol),
                    timeout=cfg.market_data.symbol_timeout_seconds,
                )
            except TimeoutError:
                elapsed = time.monotonic() - symbol_start
                log.error(
                    "scan: option chain for %s exceeded symbol_timeout_seconds=%.0f "
                    "(ran %.1fs) — skipping this symbol",
                    symbol,
                    cfg.market_data.symbol_timeout_seconds,
                    elapsed,
                )
                quotes = []
                result.provenance.chain_failed += 1
                await tracker.add_error(f"{symbol} — option chain timed out, skipped")
            except Exception:
                log.exception("scan: option chain failed for %s", symbol)
                quotes = []
                result.provenance.chain_failed += 1
                await tracker.add_error(f"{symbol} — option chain failed, skipped")
            else:
                if quotes:
                    result.provenance.chain_ibkr += 1
                    for q in quotes:
                        if q.greeks_source == "black_scholes":
                            result.provenance.greeks_yfinance += 1
                        else:
                            result.provenance.greeks_ibkr += 1
                else:
                    result.provenance.chain_failed += 1
                elapsed = time.monotonic() - symbol_start
                if elapsed > cfg.market_data.symbol_timeout_seconds / 3:
                    log.warning(
                        "scan: option chain for %s took %.1fs (%d quotes)",
                        symbol,
                        elapsed,
                        len(quotes),
                    )
                else:
                    log.debug(
                        "scan: option chain for %s took %.1fs (%d quotes)",
                        symbol,
                        elapsed,
                        len(quotes),
                    )
                # Persist the snapshot so later cycles have a store to diff against (S10).
                if quotes:
                    try:
                        await loop.run_in_executor(
                            None, persist_chain_quotes, symbol, quotes, result.run_id
                        )
                    except Exception:
                        log.warning("scan: persist_chain_quotes failed for %s", symbol)

        # Spot price (N17 follow-up): prefer the IBKR chain's put-call-parity spot over
        # yfinance fast_info when we just paid for the chain fetch.
        spot_override = infer_spot_from_quotes(quotes) if quotes else None
        # For symbols that skipped the chain (S1), reuse the materiality probe's fast_info
        # price instead of letting get_technical_stats fetch it again from scratch.
        cached_yf_price = probed_spots.get(symbol)

        # Analytics (yfinance) and sentiment (Reddit) are independent external I/O — run them
        # concurrently in the default executor to cut per-symbol latency.
        analytics_res, sentiment_res = await asyncio.gather(
            loop.run_in_executor(
                None, _fetch_analytics, symbol, quotes, spot_override, cached_yf_price
            ),
            loop.run_in_executor(None, sentiment.score, symbol),
            return_exceptions=True,
        )
        if isinstance(analytics_res, BaseException):
            log.exception("scan: analytics failed for %s", symbol, exc_info=analytics_res)
            await tracker.add_error(f"{symbol} — analytics failed, skipped")
            continue
        iv_stats, tech_stats, fund_stats = analytics_res
        sentiment_score = None if isinstance(sentiment_res, BaseException) else sentiment_res

        analytics_map[symbol] = (iv_stats, tech_stats, fund_stats)

        # Spot-price provenance (S1 follow-up): track which source produced the price Claude
        # and the strategies see for this symbol this cycle.
        if tech_stats.price > 0:
            if tech_stats.price_source == "ibkr":
                result.provenance.spot_ibkr += 1
            else:
                result.provenance.spot_yfinance += 1
        else:
            result.provenance.spot_unavailable += 1

        # Record the live spot at this fetch as the next cycle's materiality baseline (S1/S10).
        # Only fetched symbols update their baseline so slow drift accrues from the last *fetch*.
        if did_fetch and tech_stats.price:
            fetched_spots[symbol] = tech_stats.price

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
            # Calls already written against this underlying — netted out of CC sizing so
            # a re-scan never proposes calls on top of already-covered shares.
            existing_short_calls = sum(
                int(abs(p.position))
                for p in positions
                if (p.underlying or p.symbol) == symbol
                and p.sec_type == "OPT"
                and p.right == OptionRight.CALL
                and p.position < 0
            )
            new_cc = generate_cc_candidates(
                symbol,
                quotes,
                stock_pos,
                iv_stats,
                tech_stats,
                fund_stats,
                existing_short_calls=existing_short_calls,
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
    try:
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
            log.info(
                "scan: %d/%d candidates passed risk gate", len(passed), len(all_option_candidates)
            )
            # Score floor: only surface candidates above the configured quality bar.
            min_score = cfg.weights.get("min_candidate_score", 0)
            passed = [c for c in passed if c.blended_score >= min_score]
            top = select_top_candidates(passed)
        else:
            top = []
            passed = []
    except Exception:
        log.exception("scan: scoring/risk-gate failed — aborting")
        await tracker.error("scoring", "failed — aborting")
        return result

    result.cc_candidates = [c for c in top if c.strategy.value == "covered_call"]
    result.csp_candidates = [c for c in top if c.strategy.value == "cash_secured_put"]
    await tracker.tick("scoring", "✅", f"{len(top)}/{len(all_option_candidates)} passed")

    # --- 6b. Persist per-symbol materiality state for the next intraday cycle (S1/S10) ---
    # Only symbols we actually fetched this run get a fresh baseline; `cleared_floor` marks the
    # names that cleared the score floor so the next cycle always re-checks them. Runs in both
    # modes so the morning full sweep seeds the gate the first intraday cycle reads.
    cleared_floor_symbols = {c.underlying for c in passed}
    if fetched_spots:
        scanned_at = datetime.now(UTC)
        await loop.run_in_executor(
            None,
            _persist_scan_state,
            fetched_spots,
            cleared_floor_symbols,
            scanned_at,
        )

    # --- 7. Load prior Claude memory for history injection ---
    memory = _load_memory(all_symbols)

    # --- 8. Claude review (enrichment only — failure does not abort) ---
    await tracker.tick("claude", "⏳")
    reused_reviews = False
    try:
        if top:
            # Scan-time spot per symbol (N17) so Claude reasons from current levels, not the
            # stale static universe anchors. Sourced from the technicals computed this scan.
            spot_prices = {
                sym: tech.price
                for sym, (_iv, tech, _fund) in analytics_map.items()
                if tech.price  # drop missing/zero spot
            }
            # S5: skip the LLM when the top set + signals are unchanged from the prior cycle
            # (intraday loop only — manual /scan and the morning cron always review fresh).
            vix = result.market_conditions.vix if result.market_conditions else None
            review_hash = _candidates_review_hash(top, vix)
            if intraday and get_setting(_REVIEW_HASH_KEY) == review_hash:
                cached = _load_prior_reviews([c.candidate_id for c in top])
                if len(cached) == len(top):
                    result.reviews = [cached[c.candidate_id] for c in top]
                    reused_reviews = True
                    log.info(
                        "scan: top candidates unchanged since last cycle — reused %d Claude "
                        "review(s), skipped the LLM (S5)",
                        len(result.reviews),
                    )
            if not reused_reviews:
                result.reviews = review_candidates(
                    top,
                    account,
                    history=memory,
                    market_conditions=result.market_conditions,
                    spot_prices=spot_prices,
                )
            set_setting(_REVIEW_HASH_KEY, review_hash)
        log.info("scan: %d Claude reviews", len(result.reviews))
    except Exception:
        log.exception("scan: Claude review failed — continuing without reviews")
        await tracker.error("claude", "failed")
    else:
        detail = f"{len(result.reviews)} reviews" + (" (reused)" if reused_reviews else "")
        await tracker.tick("claude", "✅", detail)
    result.reused_reviews = reused_reviews

    # --- 9. Persist ---
    _persist_candidates(top, result.reviews, result.run_id)
    _persist_memory(top, result.buy_candidates, result.reviews)
    # Outcome ledger: verdict + signals + deterministic baseline (outcomes back-filled later).
    _persist_ledger(top, result.reviews, result.market_conditions, result.run_id)

    # --- 10. Send to Telegram ---
    # send_candidates manages its own short DB transactions (no session held across the
    # Telegram network sends — that would block other processes writing the same SQLite DB).
    await tracker.tick("notify", "⏳")
    try:
        cand_sent = await send_candidates(
            result.cc_candidates + result.csp_candidates,
            result.reviews,
            suppress_unchanged=intraday,
        )
        buy_sent = await send_buy_list(
            result.buy_candidates, bot, chat_id, suppress_unchanged=intraday
        )
        # S6: an intraday cycle that surfaced nothing (no candidate cleared the gate, buy list
        # unchanged) would otherwise be silent — the operator can't tell a deliberately quiet
        # market from a dead daemon. Send one compact heartbeat that confirms the scan ran and
        # explains the silence (most names moved < the materiality threshold, so chains weren't
        # re-fetched and Claude wasn't invoked). Manual /scan and the cron never reach this
        # (intraday=False) and always send in full.
        if intraday and not cand_sent and not buy_sent:
            await _send_quiet_heartbeat(bot, chat_id, result)
    except Exception:
        log.exception("scan: failed to send Telegram messages")
        await tracker.error("notify", "send failed")
    else:
        await tracker.complete(
            len(result.cc_candidates),
            len(result.csp_candidates),
            len(result.buy_candidates),
            vix=result.market_conditions.vix,
        )

    # Full sweep (manual /scan, morning cron): close out with a provenance summary so the
    # operator can see at a glance which data sources were live vs. fell back this run.
    # Best-effort — a failure here must not affect the notify stage's success status above.
    if not intraday and bot is not None and chat_id:
        prov = result.provenance
        try:
            await bot.send_message(  # type: ignore[attr-defined]
                chat_id=chat_id,
                text=format_data_provenance(
                    total_symbols=result.total_symbols,
                    chain_ibkr=prov.chain_ibkr,
                    chain_failed=prov.chain_failed,
                    chain_skipped=prov.chain_skipped,
                    spot_ibkr=prov.spot_ibkr,
                    spot_yfinance=prov.spot_yfinance,
                    spot_unavailable=prov.spot_unavailable,
                    greeks_ibkr=prov.greeks_ibkr,
                    greeks_yfinance=prov.greeks_yfinance,
                    vix=result.market_conditions.vix if result.market_conditions else None,
                ),
                parse_mode="MarkdownV2",
            )
        except Exception:
            log.warning("scan: failed to send data-provenance summary", exc_info=True)

    log.info(
        "scan complete — run_id=%s CC=%d CSP=%d buy=%d reviews=%d",
        result.run_id,
        len(result.cc_candidates),
        len(result.csp_candidates),
        len(result.buy_candidates),
        len(result.reviews),
    )
    return result
