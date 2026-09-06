"""Full-pipeline scan orchestrator — shared by the 15-min daemon loop and the Telegram /scan command.

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
from collections.abc import Container
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ib_async import IB

from src.analytics.fair_value import compute_ideal_zone
from src.analytics.fundamentals import get_fundamental_stats
from src.analytics.iv import get_iv_stats, infer_spot_from_quotes
from src.analytics.market_conditions import get_market_conditions
from src.analytics.sector_context import get_sector_context, render_sector_context
from src.analytics.sentiment import SentimentScorer
from src.analytics.technicals import _fetch_last_price, get_technical_stats
from src.claude.runner import review_candidates
from src.common.config import Config, get_config
from src.common.market_hours import today_et
from src.common.schemas import (
    AccountSnapshot,
    AssessedContract,
    AssessmentStage,
    BuyCandidate,
    ClaudeReview,
    FundamentalStats,
    IdealZone,
    IVStats,
    MarketConditions,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    RiskVerdict,
    SectorContext,
    TechnicalStats,
    TradeCandidate,
)
from src.engine.decision_engine import select_top_candidates_detailed
from src.engine.risk_engine import validate_candidates
from src.engine.scoring import score_candidates
from src.ibkr.market_data import drain_market_data_lines, get_option_chain_quotes_async
from src.ibkr.portfolio import get_account_snapshot_async, get_positions

# The only names this module still takes from src.notify. They are held here — rather than in
# scan_progress, which owns every other Telegram call — because tests/test_scan_timeout.py,
# tests/test_scan_materiality.py and tests/test_scan_review_reuse.py monkeypatch them as
# attributes of this module. They are injected into send_scan_results via SendDeps.
from src.notify.sender import send_account_snapshot, send_buy_list, send_candidates
from src.orchestrator.scan_pipeline import ChainStatus, SymbolDeps, scan_symbol
from src.orchestrator.scan_progress import (
    SendDeps,
    _ProgressCB,
    _Tracker,
    send_scan_results,
)
from src.storage.buy_candidates import save_buy_candidates
from src.storage.db import session_scope
from src.storage.models import CandidateRow, ClaudeMemoryRow, ClaudeReviewRow
from src.storage.risk_verdicts import record_assessments
from src.storage.scan_state import ScanState, bulk_upsert_scan_state, get_scan_state
from src.storage.system_settings import (
    acquire_scan_lease,
    get_setting,
    release_scan_lease,
    renew_scan_lease,
    set_setting,
)
from src.strategies.buy_candidates import generate_buy_candidates
from src.strategies.cash_secured_put import screen_csp_candidates
from src.strategies.covered_call import screen_cc_candidates

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

# Max near-miss contracts to name on an empty CC/CSP screen; further rejects collapse into a
# trailing "…and N more" line. One "closest" per strategy keeps each quiet-cycle line compact.
_NEAR_MISS_LIMIT = 1


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
    # Every contract this scan priced and what became of it — approved, or rejected with the
    # reasons why, at whichever stage it stopped. Ranked best-first. This is what lets a scan
    # that approves nothing still show the operator what it looked at.
    assessed: list[AssessedContract] = field(default_factory=list)
    reviews: list[ClaudeReview] = field(default_factory=list)
    market_conditions: MarketConditions = field(default_factory=MarketConditions)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    # True when this scan was skipped because another process held the scan lease (F5).
    lease_skipped: bool = False
    # True when the run was aborted mid-sweep by the half-dead-socket circuit breaker:
    # max_consecutive_chain_timeouts symbols timed out back-to-back, so rather than grind the
    # rest of the universe at symbol_timeout_seconds each the scan bails. The caller (intraday
    # loop) reads this to notify the operator and force a reconnect.
    aborted_unhealthy: bool = False
    # Symbols never reached this run because of an ``aborted_unhealthy`` abort — the symbol that
    # tipped the circuit breaker plus everything after it in iteration order. Empty on a clean
    # run. The caller (intraday loop) carries this forward as next cycle's forced-include set so
    # a partial abort doesn't silently strand symbols outside the materiality gate's normal
    # triggers (2026-08-28).
    unreached_symbols: list[str] = field(default_factory=list)
    # Intraday telemetry (S1/S5): how many symbols were fetched this cycle vs the universe
    # size, and whether the Claude review was reused. `material_count` also feeds the
    # "N/M names moved <X%" clause appended to a quiet cycle's empty-screen diagnostic.
    total_symbols: int = 0
    material_count: int = 0
    reused_reviews: bool = False
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

    cutoff = today_et() - timedelta(days=_MEMORY_LOOKBACK_DAYS)
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
    today = today_et()
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
        # Full sentiment breakdown (sources, counts, 1-day velocity) for later EV/calibration
        # analysis in the verdict learning loop — enrichment only, never gates or sizes.
        "sentiment_detail": (
            c.scores.sentiment_detail.model_dump() if c.scores.sentiment_detail else None
        ),
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
    today = today_et()
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


# Priority bands for `_fetch_priority`. Real move ratios are ~1.0-20.0, so the sentinels sit
# clear of them at both ends.
_RETRY_PRIORITY = 1e9
_FLOOR_PRIORITY = 1e6
_STALE_PRIORITY = 0.5


def _move_ratio(
    symbol: str,
    price: float,
    last_spot: float,
    *,
    holdings: Container[str],
    aw_set: Container[str],
    dip_set: Container[str],
    cfg: Config,
) -> float:
    """How far *symbol* moved past its own bar, as a multiple of that bar.

    ``>= 1.0`` means material; ``2.0`` means it moved twice as far as its threshold requires.
    Buckets are **unioned** — a symbol in more than one bucket takes the max across all of them,
    so holding shares can never lower a name's ratio (2026-08-28).

    This is the single source of truth for the move gate. ``_compute_material_symbols`` uses it
    as a boolean (``>= 1.0``); the intraday fetch budget re-uses the same number to *rank* which
    material symbols are worth spending the cycle on first. Expressing both in "multiples of its
    own bar" is what makes the ranking comparable across buckets: a dip-watch name down 6% (2.0x
    its 3% bar) outranks an actively_wheeling name down 0.6% (1.2x its 0.5% bar), which is the
    right economics — in a sell-off the deepest drops are the best CSP entries. Keeping one
    implementation means the gate and the ranker cannot disagree about what "moved" means.
    """
    if last_spot <= 0:
        return 0.0
    up = (price - last_spot) / last_spot
    ratios: list[float] = []
    if symbol in holdings:  # (a) up only — a new CC strike needs a rally's room
        ratios.append(up / cfg.market_data.held_position_move_pct)
    if symbol in aw_set:  # (b) either way — core rotation
        ratios.append(abs(up) / cfg.market_data.intraday_rescan_move_pct)
    if symbol in dip_set:  # (c) drop only — opportunistic CSP entry
        ratios.append(-up / cfg.market_data.dip_pull_in_pct)
    return max(ratios, default=0.0)


def _fetch_priority(
    material: set[str],
    probed_spots: dict[str, float],
    states: dict[str, ScanState],
    *,
    holdings: Container[str],
    aw_set: Container[str],
    dip_set: Container[str],
    must_include: set[str] | None,
    cfg: Config,
) -> dict[str, float]:
    """Rank the material symbols so a capped cycle spends its budget on the best fetches first.

    Only meaningful alongside ``market_data.chain_fetch_budget_seconds``: when every material
    symbol fits in the cycle the order is irrelevant, and when it doesn't, *which* ones get
    dropped is the whole question. Highest first:

    ``_RETRY_PRIORITY``   symbols a previous cycle ran out of budget (or socket) before reaching.
                          Unconditionally first, otherwise a name at the back of a big queue can
                          starve indefinitely while fresher movers keep jumping ahead of it.
    ``_FLOOR_PRIORITY``   cleared the risk gate *and* score floor on its last fetch — a live,
                          tradeable candidate whose price is going stale. Repricing an actionable
                          contract beats discovering a new one.
    move ratio            how many multiples of its own bar the symbol moved (see
                          ``_move_ratio``). Comparable across buckets, so in a sell-off the
                          deepest drops are bought first.
    ``_STALE_PRIORITY``   material only because its 120-min staleness timer expired. Below every
                          real mover by construction: it is quiet, which is exactly why nothing
                          else fired for it.

    Immaterial symbols are absent from the result; the caller treats a missing key as lowest.
    """
    priority: dict[str, float] = {}
    for sym in material:
        if must_include and sym in must_include:
            priority[sym] = _RETRY_PRIORITY
            continue
        st = states.get(sym)
        if st is not None and st.cleared_floor:
            priority[sym] = _FLOOR_PRIORITY
            continue
        price = probed_spots.get(sym)
        ratio = (
            _move_ratio(
                sym,
                price,
                st.last_spot,
                holdings=holdings,
                aw_set=aw_set,
                dip_set=dip_set,
                cfg=cfg,
            )
            if price is not None and st is not None and st.last_spot
            else 0.0
        )
        # A material symbol that didn't move is here on the staleness timer (or has no baseline).
        priority[sym] = ratio if ratio >= 1.0 else _STALE_PRIORITY
    return priority


async def _compute_material_symbols(
    all_symbols: list[str],
    holdings_symbols: set[str],
    actively_wheeling: list[str],
    dip_watch: list[str],
    *,
    force_full_sweep: bool = False,
    must_include: set[str] | None = None,
) -> tuple[set[str], dict[str, float]]:
    """Decide which symbols need a fresh option-chain fetch this intraday cycle (S1).

    Returns ``(material, probed_spots)``:
      - ``material`` is the subset of *all_symbols* that are *material*. Rules (a)-(c) are the
        per-bucket move gates, and they are **UNIONed, not selected between** (2026-08-28): a
        symbol that sits in two buckets is tested against both, and any one of them firing is
        enough. Holding shares must never *reduce* a name's coverage, which is exactly what the
        old ``if held / elif dip_watch / else`` chain did — an ``actively_wheeling`` name you
        owned silently dropped from (b) to (a)-only, shrinking the core rotation to just the
        names you *don't* hold. The buckets answer different questions about the same fetch —
        (a) "is there room for a new covered call?", (b)/(c) "is this a CSP entry?" — and the
        CSP screen runs for every ``would_own`` symbol whether or not it is held, so a held
        wheel name genuinely has both reasons:
          (a) every held stock position whose live spot has *risen* ≥
              ``market_data.held_position_move_pct`` from the spot at its last fetch —
              directional (2026-08-27): a new CC candidate needs room to sell an OTM strike,
              which only opens up on a rally; a drop doesn't create that opportunity, and
              existing-position risk (delta drift, assignment, rolls) is handled continuously by
              the separate event-driven monitor (`src/monitor/intraday.py`), not this gate. For a
              held name that is *only* held (not in ``would_own``) this is the whole story, and a
              drop is still caught within `force_full_scan_minutes` by (f) below;
          (b) every ``actively_wheeling`` name — held or not — whose live spot has drifted ≥
              ``market_data.intraday_rescan_move_pct`` from the spot at its last fetch;
          (c) every ``dip_watch`` name — held or not — whose live spot has *dropped* ≥
              ``market_data.dip_pull_in_pct`` from the spot at its last fetch — directional,
              since a rally is never a CSP entry signal for a name outside the core rotation;
          (d) every name that cleared the score floor last cycle;
          (e) any symbol with no usable baseline yet (new position, or first time seen) — always
              fetched once to establish one;
          (f) every ``actively_wheeling``/held name individually stale beyond
              ``force_full_scan_minutes`` since ITS OWN last fetch (never ``dip_watch`` — that
              would defeat the point of keeping dip-watch off the per-cycle rotation). This is
              deliberately **per symbol**, not "sweep the whole core the moment the single
              stalest one goes over the line" — under that old rule, one quiet name (e.g. GLD on
              a slow week) would drag all 19 into a synchronized burst together every time its
              own clock expired. Per-symbol staleness means each name's clock starts ticking
              from *its own* last fetch, so cheap/frequent fetches (a volatile name tripping (a)
              or (b) often) and rare ones (a quiet name relying on this fallback) desynchronize
              naturally — the periodic refreshes spread out over time instead of bunching, with
              no explicit batch/rotation schedule needed to get that effect. Since 2026-08-28 the
              stamps this reads are also written per symbol (see ``_persist_scan_state``), so a
              sweep's cohort no longer shares one identical clock and expires spread across the
              same span the sweep took, rather than all inside one later cycle.
        The very first intraday cycle (no `scan_state` at all yet) sweeps everything to seed it,
        as does *force_full_sweep* — with one exception: dip_watch names get seed-only (see the
        ``force_full_sweep`` branch below).
      - ``probed_spots`` is the live yfinance price fetched while checking (a)-(c), keyed by
        symbol. Immaterial symbols skip the option chain and therefore have no chain-derived
        spot — the caller reuses this probe price as ``spot_override`` so
        ``get_technical_stats`` doesn't pay for a second identical ``fast_info`` fetch (S1
        follow-up).

    *must_include* forces exactly the named symbols into ``material`` regardless of the rules
    above — the intraday loop's own retry queue for symbols an aborted sweep never reached last
    cycle (2026-08-28). Unlike *force_full_sweep* this doesn't widen anything else: an unrelated
    unmoved symbol is still gated normally, so a retry costs only what it needs to.

    Only ever *narrows* the set — callers in full-sweep mode (manual ``/scan``)
    must not call this and instead fetch every symbol. Pure read; never raises.
    """
    cfg = get_config()

    aw_set = set(actively_wheeling)
    dip_set = set(dip_watch)

    # Full-sweep mode (the first cycle since process start, or a manual /scan) overrides the
    # materiality gate — with one exception (2026-08-28): dip_watch names don't get an
    # unconditional IBKR chain fetch. A dip_watch name has only one CSP-entry reason to be
    # fetched — a real drop — and at startup there's no *intraday* drift to measure yet, only an
    # overnight gap from yesterday's persisted baseline. That gap is checked bidirectionally
    # against ``dip_pull_in_pct`` (a rally is a legitimate CSP setup at the open via an IV
    # expansion / gap-up, even though a small intraday rally is never a CSP entry later); names
    # with no material overnight gap (or no baseline to compare against — the first-ever run)
    # get seed-only: the caller persists the yfinance probe price as ``last_spot`` and skips the
    # chain fetch. This keeps the per-cycle rule (c) drop-only gate working from cycle 1 onward,
    # sourced end-to-end from yfinance (no IBKR/yfinance mismatch), at the cost of forgoing the
    # first-cycle IV/Greeks set for quiet dip_watch names — acceptable, since a dip_watch name
    # that hasn't gapped overnight isn't a candidate anyway.
    if force_full_sweep:
        # Everything except pure-dip_watch names is material unconditionally.
        material: set[str] = {s for s in all_symbols if s not in dip_set or s in holdings_symbols}
        # Probe only the dip_watch names (those not already in material) to either fetch them
        # (overnight gap ≥ dip_pull_in_pct) or seed-only (quiet overnight / no baseline).
        to_probe_dip = [s for s in dip_watch if s not in material and s in set(all_symbols)]
        states = get_scan_state(to_probe_dip) if to_probe_dip else {}
        dip_pct = cfg.market_data.dip_pull_in_pct
        loop = asyncio.get_running_loop()
        prices = await asyncio.gather(
            *(loop.run_in_executor(None, _fetch_last_price, s) for s in to_probe_dip),
            return_exceptions=True,
        )
        probed_spots: dict[str, float] = {}
        for sym, price in zip(to_probe_dip, prices, strict=True):
            if not isinstance(price, BaseException) and price is not None:
                probed_spots[sym] = price
            st = states.get(sym)
            # No baseline → seed-only (per design: accept no overnight detection on the first
            # day for a brand-new ticker; rule (c) drop-only works from cycle 1 onward).
            if (
                isinstance(price, BaseException)
                or price is None
                or st is None
                or not st.last_spot
                or st.last_spot <= 0
            ):
                continue  # seed-only: stays out of material, probe price in probed_spots
            # Bidirectional overnight-move check — a gap in either direction is a legitimate
            # CSP setup at the open (gap-up = IV expansion / news; gap-down = the dip rule).
            if abs(price - st.last_spot) / st.last_spot >= dip_pct:
                material.add(sym)
        if must_include:
            material |= must_include & set(all_symbols)
        return material, probed_spots

    states = get_scan_state(all_symbols)

    # No baseline yet (first intraday cycle after a cold start) → sweep everything to seed it.
    if not states:
        return set(all_symbols), {}

    material = {sym for sym, st in states.items() if st.cleared_floor}  # (d)

    # (f) Per-symbol safety-net staleness — scoped to actively_wheeling ∪ held only. dip_watch
    # names are event-triggered by a genuine drop, never swept on a timer.
    force_minutes = cfg.market_data.force_full_scan_minutes
    if force_minutes > 0:
        now = datetime.now(UTC)
        for sym in set(actively_wheeling) | holdings_symbols:
            stamp = states[sym].last_scanned_at if sym in states else None
            # SQLite drops tzinfo on round-trip; last_scanned_at was stored as datetime.now(UTC),
            # so a naive value here is UTC — reattach tzinfo before comparing.
            if stamp is not None and stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            if stamp is None or (now - stamp).total_seconds() > force_minutes * 60:
                material.add(sym)

    # A symbol can belong to more than one bucket (a name you hold *and* actively wheel). The
    # rules below are UNIONed, not selected between — see the loop. ``aw_set``/``dip_set`` are
    # defined above the force_full_sweep branch so it can reuse them.
    # fast_info is a cheap single quote (no option chain); fan out so the materiality probe
    # stays sub-second. The three lists below only control probe *ordering* and de-duplication
    # (each symbol is probed exactly once, held names first) — they do not pick which threshold
    # applies. That is decided per rule in the loop.
    to_probe_held = [s for s in holdings_symbols if s not in material]
    to_probe_core = [
        s for s in actively_wheeling if s not in material and s not in holdings_symbols
    ]
    to_probe_dip = [s for s in dip_watch if s not in material and s not in holdings_symbols]
    to_probe = to_probe_held + to_probe_core + to_probe_dip

    loop = asyncio.get_running_loop()
    prices = await asyncio.gather(
        *(loop.run_in_executor(None, _fetch_last_price, s) for s in to_probe),
        return_exceptions=True,
    )
    probed_spots = {}
    for sym, price in zip(to_probe, prices, strict=True):
        if not isinstance(price, BaseException) and price is not None:
            probed_spots[sym] = price
        st = states.get(sym)
        # No baseline, no price, or a non-positive last_spot → fetch to (re)establish one. (e)
        if (
            isinstance(price, BaseException)
            or price is None
            or st is None
            or not st.last_spot
            or st.last_spot <= 0
        ):
            material.add(sym)
            continue
        # Union, not if/elif (2026-08-28). A symbol in two buckets is tested against BOTH: these
        # used to be mutually exclusive with `holdings_symbols` winning, which meant holding
        # shares of a name *reduced* its coverage — an actively_wheeling name you owned dropped
        # from +-intraday_rescan_move_pct either way to held_position_move_pct up only, silently
        # shrinking the core rotation to just the names you don't hold. Since the CSP screen runs
        # for every would_own symbol regardless of whether it is held (see
        # `strategies/cash_secured_put.py`), a held wheel name has a live CSP reason to be
        # refetched on a dip that the held (CC) rule alone can never see. `_move_ratio` owns the
        # union so the fetch-budget ranker uses the identical definition of "moved".
        if (
            _move_ratio(
                sym,
                price,
                st.last_spot,
                holdings=holdings_symbols,
                aw_set=aw_set,
                dip_set=dip_set,
                cfg=cfg,
            )
            >= 1.0
        ):
            material.add(sym)

    if must_include:
        material |= must_include & set(all_symbols)

    return material, probed_spots


def _persist_scan_state(
    fetched: dict[str, tuple[float, datetime]],
    cleared_floor_symbols: set[str],
) -> None:
    """Write the per-symbol materiality baseline for every fetched symbol (S1/S10). Off-thread.

    *fetched* maps symbol → (spot at fetch, the moment **that symbol's** chain was fetched).
    The timestamp is per symbol, not one shared run-level stamp (2026-08-28): a run-level stamp
    recorded every symbol in a sweep as having been fetched when the *whole run* finished, which
    (i) overstated the freshness of everything fetched early by up to the sweep's duration, and
    (ii) gave the entire cohort one identical staleness clock, so they all expired together in a
    single later cycle. Per-symbol stamps spread a sweep's expiry across the same span the sweep
    itself took — which matters because a burst longer than ``intraday_loop_minutes`` overruns
    the cycle and costs the next one entirely (``scan_running``). This is what makes the
    per-symbol staleness check in ``_compute_material_symbols`` (f) actually per symbol: that
    check already read each symbol's own stamp, but every stamp in a sweep used to be identical.
    """
    bulk_upsert_scan_state(
        {
            symbol: (spot, stamp, symbol in cleared_floor_symbols)
            for symbol, (spot, stamp) in fetched.items()
        }
    )


def _persist_seed_only_baselines(
    probed_spots: dict[str, float],
    material: set[str],
) -> None:
    """Persist yfinance probe prices as ``last_spot`` baselines for symbols that were *not*
    fetched this cycle (2026-08-28).

    In a full-sweep cycle (startup, manual /scan), dip_watch names that didn't gap overnight
    are skipped — no IBKR chain fetch — but their yfinance probe price is the baseline the
    per-cycle rule (c) gate will compare against from cycle 1 onward. Without persisting it
    here, rule (e) (no baseline → fetch to establish one) would fire on the very next cycle for
    every seed-only name, defeating the optimization. ``last_scanned_at`` is left NULL (no chain
    was fetched — distinguishes these from real fetches in the staleness log) and
    ``cleared_floor`` is False (a name never chain-fetched can't have cleared the score floor).

    Only symbols in *probed_spots* but not in *material* are seeded: a name that *was* fetched
    gets its baseline written by ``_persist_scan_state`` at end-of-run with the chain's spot and
    a real timestamp, which is the authoritative value. Pure write; never raises.
    """
    seed_only = {sym: spot for sym, spot in probed_spots.items() if sym not in material}
    if not seed_only:
        return
    bulk_upsert_scan_state({sym: (spot, None, False) for sym, spot in seed_only.items()})


def _rank_assessed(assessed: list[AssessedContract]) -> list[AssessedContract]:
    """Order assessed contracts best-first: approved, then closest-to-approved.

    Within the rejected set, a contract that stumbled at the last hurdle (score floor, top-N)
    ranks above one that never cleared the delta band, and higher blended score breaks ties.
    ``AssessmentStage`` is declared in pipeline order, so its position in the enum *is* the
    "how far did it get" rank.
    """
    order = {stage: i for i, stage in enumerate(AssessmentStage)}

    def key(a: AssessedContract) -> tuple[int, int, float]:
        # PASSED sorts first; among rejects, later stages (got further) sort first.
        return (0 if a.passed else 1, -order[a.stage], -a.candidate.blended_score)

    return sorted(assessed, key=key)


def _near_misses(
    assessed: list[AssessedContract], strategy_value: str
) -> tuple[list[tuple[TradeCandidate, list[str]]], int]:
    """The closest rejected contracts for one strategy, plus how many more were truncated.

    Feeds the compact one-line digest appended on a quiet cycle. Expects *assessed* already
    ranked by :func:`_rank_assessed`.
    """
    rejected = [
        a for a in assessed if not a.passed and a.candidate.strategy.value == strategy_value
    ]
    shown = [(a.candidate, a.reasons) for a in rejected[:_NEAR_MISS_LIMIT]]
    return shown, max(0, len(rejected) - len(shown))


def _no_candidates_reason(
    result: ScanResult,
    all_count: int,
    *,
    strategy: str = "",
    positions: list[PositionSnapshot] | None = None,
    rejection_tally: dict[str, int] | None = None,
    symbol_count: int = 0,
    intraday: bool = False,
) -> str:
    """Human-readable explanation for why a per-strategy screen is empty this cycle.

    On an intraday cycle the answer is often "we didn't look" rather than "we looked and
    found nothing" — the materiality gate (S1) skips the chain fetch for names that barely
    moved. That distinction is appended so a deliberately quiet market never reads as a dead
    daemon; it used to live in a separate heartbeat message that could not actually fire.
    """
    return _empty_screen_base(
        result,
        all_count,
        strategy=strategy,
        positions=positions,
        rejection_tally=rejection_tally,
        symbol_count=symbol_count,
    ) + _materiality_clause(result, intraday)


def _empty_screen_base(
    result: ScanResult,
    all_count: int,
    *,
    strategy: str,
    positions: list[PositionSnapshot] | None,
    rejection_tally: dict[str, int] | None,
    symbol_count: int,
) -> str:
    prov = result.provenance
    if result.total_symbols == 0:
        return "no symbols in universe"

    # All chains came back empty (no quotes at all — market closed or data subscription issue).
    if prov.chain_ibkr == 0 and prov.chain_failed > 0:
        return (
            f"{prov.chain_failed}/{result.total_symbols} option chains returned no data"
            " — market may be closed or check data subscription"
        )

    if all_count == 0:
        # CC-specific: no long stock positions means no shares to write calls against.
        if strategy == "covered_call" and positions is not None:
            held = [p for p in positions if p.sec_type == "STK" and p.position > 0]
            if not held:
                return "no long stock positions held — covered calls require owned shares"

        # Chain data was fetched but every quote was filtered out by delta/DTE/ROC/yield/liquidity.
        if prov.chain_ibkr > 0:
            return (
                f"option data returned for {prov.chain_ibkr}/{result.total_symbols} symbols"
                " but no quotes met delta/DTE/ROC/yield criteria"
                " (check market hours and filter thresholds)"
            )

        # Fallback: chains returned nothing and nothing failed either (shouldn't happen in full scan).
        return "no option chain data returned this cycle — market may be closed"

    # Build a compact rejection breakdown so the operator can see which gate dominated.
    sym_clause = f" across {symbol_count} symbols" if symbol_count > 0 else ""
    gate_summary = ""
    if rejection_tally:
        top = sorted(rejection_tally.items(), key=lambda kv: kv[1], reverse=True)[:3]
        gate_summary = " (" + ", ".join(f"{r} ×{n}" for r, n in top) + ")"

    return f"0/{all_count} candidates{sym_clause} passed the risk gate{gate_summary}"


def _materiality_clause(result: ScanResult, intraday: bool) -> str:
    """ " · N/M names moved too little (chain re-fetch skipped)" for a gated intraday cycle.

    No single percentage applies any more — held names, actively_wheeling, and dip-watch names
    each use a different threshold (held_position_move_pct / intraday_rescan_move_pct /
    dip_pull_in_pct) — so the clause names the count, not a specific figure.
    """
    if not intraday or result.total_symbols <= 0:
        return ""
    skipped = max(0, result.total_symbols - result.material_count)
    if skipped <= 0:
        return ""
    return f" · {skipped}/{result.total_symbols} names moved too little (chain re-fetch skipped)"


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
    force_full_sweep: bool = False,
    must_include_symbols: set[str] | None = None,
    include_buy_list: bool = True,
) -> ScanResult:
    """Run the full pipeline under a cross-process scan lease (SYSTEM_REVIEW F5).

    ``intraday=True`` (the 15-min loop) enables the S1 materiality gate: only held positions that
    moved ≥2%, ``actively_wheeling`` names that moved ≥0.5%, ``would_own``-but-not-
    ``actively_wheeling`` ("dip-watch") names that *dropped* ≥3%, and names that cleared the
    score floor last cycle get a fresh option-chain fetch; everything else is skipped this
    cycle. Manual ``/scan`` (``intraday=False``) runs the full-sweep path: actively_wheeling ∪
    held names are fetched unconditionally, and dip_watch names are seed-only unless they gapped
    ≥3% overnight (see ``_compute_material_symbols``'s force_full_sweep branch, 2026-08-28).

    ``force_full_sweep=True`` overrides the materiality gate for the 15-min loop's first eligible
    cycle after every process start (see ``_intraday_scan_loop``) — actively_wheeling ∪ held names
    are fetched unconditionally, and dip_watch names get the same seed-only / overnight-gap
    treatment as a manual ``/scan``. No effect when ``intraday=False`` (already a full sweep).

    ``must_include_symbols`` forces just the named symbols through the gate regardless of
    movement — the intraday loop's retry queue for symbols a previous ``aborted_unhealthy`` run
    never reached (see ``ScanResult.unreached_symbols``, 2026-08-28). Unlike
    ``force_full_sweep`` this doesn't widen the fetch to everything else, so a retry costs only
    what it needs to; already-cached symbols stay gated normally. No effect when
    ``intraday=False``.

    ``include_buy_list=False`` skips only the Telegram send of the buy-to-own screen —
    ``result.buy_candidates`` is still scored (it's cheap: reuses analytics already fetched for
    CC/CSP). The 15-min intraday loop sets this ``False`` on every cycle after the first one
    that completes each day, so the buy list fires once daily rather than every 15 minutes.
    Manual ``/scan`` leaves it ``True``.

    A full chain scan consumes most of the account-level ~100 market-data line cap, so two
    concurrent full scans (e.g. two simultaneous ``/scan`` commands, in separate processes)
    would poison each other. The lease serialises them; a scan that can't acquire
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
            force_full_sweep=force_full_sweep,
            must_include_symbols=must_include_symbols,
            include_buy_list=include_buy_list,
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
    force_full_sweep: bool = False,
    must_include_symbols: set[str] | None = None,
    include_buy_list: bool = True,
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
    actively_wheeling: list[str] = cfg.universe.get("actively_wheeling", [])
    dip_watch: list[str] = sorted(set(would_own) - set(actively_wheeling))
    holdings_symbols: set[str] = {
        p.underlying or p.symbol for p in positions if p.sec_type == "STK" and p.position > 0
    }
    all_symbols: list[str] = sorted(set(would_own) | holdings_symbols)
    n = len(all_symbols)
    result.total_symbols = n
    log.info(
        "scan: %d symbols to scan (%d holdings, %d would_own [%d actively_wheeling, %d dip-watch])",
        n,
        len(holdings_symbols),
        len(would_own),
        len(actively_wheeling),
        len(dip_watch),
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
    # Full-sweep mode (manual /scan, or the first cycle since process start) now skips the
    # IBKR chain fetch for dip_watch names that didn't gap overnight — see
    # ``_compute_material_symbols``'s force_full_sweep branch (2026-08-28). The 15-min loop
    # fetches only material ones and skips the rest, sparing the dominant option-chain cost.
    if intraday:
        material_symbols, probed_spots = await _compute_material_symbols(
            all_symbols,
            holdings_symbols,
            actively_wheeling,
            dip_watch,
            force_full_sweep=force_full_sweep,
            must_include=must_include_symbols,
        )
        log.info(
            "scan: intraday materiality gate — %d/%d symbols material%s: %s",
            len(material_symbols),
            n,
            " (forced full sweep — first cycle since process start)" if force_full_sweep else "",
            sorted(material_symbols),
        )
    else:
        # Manual /scan: reuse the full-sweep branch so dip_watch names get seed-only too
        # (quiet overnight → yfinance baseline, no chain fetch; gapped → fetched). Holding
        # this gate against manual /scan is fine because /scan TICKER still force-fetches a
        # single named ticker on demand, and the operator can always inspect one name that way.
        material_symbols, probed_spots = await _compute_material_symbols(
            all_symbols,
            holdings_symbols,
            actively_wheeling,
            dip_watch,
            force_full_sweep=True,
        )
        log.info(
            "scan: full sweep — %d/%d symbols material (dip_watch seed-only): %s",
            len(material_symbols),
            n,
            sorted(material_symbols),
        )
    result.material_count = len(material_symbols)

    # --- 3c. Intraday fetch budget (2026-08-28) ---
    # Order the sweep so the cycle's chain-fetch budget is spent on the highest-value symbols
    # first, and cut it off before the run overruns the interval. Without this the gate is the
    # only throttle, and it stops throttling exactly when it matters: in a broad sell-off every
    # would_own name crosses its bar at once (measured: 5 of 66 real runs already exceeded the
    # 15-min cycle, up to 30.1 min), and an overrun sets `scan_running`, costing the NEXT
    # cycle's scan outright. Symbols cut are carried to `unreached_symbols` -> next cycle's
    # `must_include`, where they rank first — so a big cluster drains over consecutive cycles
    # that each finish on time instead of one burst that eats the following cycle.
    budget_seconds = cfg.market_data.chain_fetch_budget_seconds if intraday else 0.0
    if budget_seconds > 0 and material_symbols:
        priority = _fetch_priority(
            material_symbols,
            probed_spots,
            get_scan_state(sorted(material_symbols)),
            holdings=holdings_symbols,
            aw_set=set(actively_wheeling),
            dip_set=set(dip_watch),
            must_include=must_include_symbols,
            cfg=cfg,
        )
        # Material first (best-ranked first), then everything else. Immaterial symbols still run
        # analytics + sentiment — they feed the buy-to-own screen and the Claude prompt — but
        # they cost no chain time, so their order is irrelevant.
        scan_order = sorted(all_symbols, key=lambda sym: (-priority.get(sym, -1.0), sym))
    else:
        priority = {}
        scan_order = all_symbols

    # Persist the seed-only dip_watch baselines (probe prices for names that didn't gap
    # overnight) so the per-cycle rule (c) gate has a yfinance-sourced baseline to compare
    # against from cycle 1 onward. Full-sweep chains fetched below are persisted by
    # ``_persist_scan_state`` at the end of the run; this only seeds the names that were *not*
    # fetched this cycle. ``last_scanned_at`` is left NULL (no chain was fetched) and
    # ``cleared_floor`` is False (a name never chain-fetched can't have cleared the floor).
    #
    # Scoped to an actual full sweep ONLY (2026-08-28 fix) — a normal intraday-gated cycle's
    # ``probed_spots`` holds every probed symbol regardless of bucket (held/actively_wheeling/
    # dip_watch), most of which are probed-but-immaterial on any quiet cycle. Calling this
    # unconditionally used to null out a real ``last_scanned_at`` on every such symbol every
    # quiet cycle, which (a) defeated the sticky-``last_spot`` drift-accumulation invariant
    # (each cycle rebased to itself instead of comparing against the last real fetch) and (b)
    # made the very next cycle's per-symbol ``force_full_scan_minutes`` staleness check (f) see
    # ``stamp is None`` and force an immediate real refetch — an actively_wheeling/held name
    # ended up force-refetched roughly every other cycle (~30 min) instead of every 120 min,
    # the opposite of what the gate exists to do.
    if probed_spots and (force_full_sweep or not intraday):
        _persist_seed_only_baselines(probed_spots, material_symbols)

    # --- 4. Per-symbol: market data + analytics + strategy candidates ---
    cc_candidates: list[TradeCandidate] = []
    csp_candidates: list[TradeCandidate] = []
    # Contracts the strategy generators priced but rejected (delta band, DTE, liquidity,
    # ROC/yield). Previously these were dropped with a `continue` and survived only as an
    # aggregate log counter — so a symbol whose whole chain failed produced nothing to show.
    generator_rejects: list[tuple[TradeCandidate, list[str]]] = []
    analytics_map: dict[str, tuple[IVStats, TechnicalStats, FundamentalStats]] = {}
    # symbol → (spot at fetch, when THIS symbol was fetched); the scan_state baseline.
    fetched: dict[str, tuple[float, datetime]] = {}
    # Half-dead-socket circuit breaker (N-fix 2026-06-24): count consecutive chain-fetch
    # timeouts. A live socket that hangs on one symbol (pacing, a non-existent weekly chain)
    # recovers on the next; a socket that has lost its IBKR data farm times out on *every*
    # symbol. After max_consecutive_chain_timeouts in a row we conclude the socket is dead and
    # abort, rather than burning symbol_timeout_seconds × the rest of the universe (~115 min)
    # and starving every later intraday cycle.
    consecutive_chain_timeouts = 0
    max_consecutive_timeouts = cfg.market_data.max_consecutive_chain_timeouts

    # The collaborators the per-symbol pipeline calls out to. Bound here, from this module's
    # namespace, so the orchestrator stays in charge of which implementation runs.
    deps = SymbolDeps(
        fetch_chain=get_option_chain_quotes_async,
        fetch_analytics=_fetch_analytics,
        score_sentiment=sentiment.score,
        screen_cc=screen_cc_candidates,
        screen_csp=screen_csp_candidates,
    )

    await tracker.tick("market_data", "⏳", f"0/{n} symbols")
    chain_deadline = (
        asyncio.get_running_loop().time() + budget_seconds if budget_seconds > 0 else None
    )
    over_budget: list[str] = []
    for i, symbol in enumerate(scan_order):
        log.info("scan: processing %s", symbol)
        await tracker.mark_symbol(i + 1, n, symbol)

        # Budget check. Only ever *demotes* a symbol to immaterial (analytics still run, chain
        # skipped) — never aborts the run, so the cycle still produces a complete picture from
        # everything already fetched. Checked between symbols because a fetch in flight can't be
        # preempted; `chain_fetch_budget_seconds` is sized to leave one `symbol_timeout_seconds`
        # of headroom for the overshoot that allows.
        fetch_this = symbol in material_symbols
        if (
            fetch_this
            and chain_deadline is not None
            and asyncio.get_running_loop().time() >= chain_deadline
        ):
            fetch_this = False
            over_budget.append(symbol)

        # Heartbeat: extend the scan lease each iteration so a full ~60-symbol scan can't
        # outlive the TTL and let a second scan start mid-run (N7). CAS — if we've lost the
        # lease there's nothing to renew (we keep going; release will no-op safely).
        renew_scan_lease(lease_token)

        # All the per-symbol I/O and screening lives in scan_pipeline: it returns data, never
        # touching the tracker or the run-level accumulators below.
        outcome = await scan_symbol(
            ib,
            symbol,
            material=fetch_this,
            account=account,
            positions=positions,
            would_own=would_own,
            # For symbols that skipped the chain (S1), reuse the materiality probe's fast_info
            # price instead of letting get_technical_stats fetch it again from scratch.
            probed_spot=probed_spots.get(symbol),
            symbol_timeout_seconds=cfg.market_data.symbol_timeout_seconds,
            deps=deps,
        )

        # Chain + Greeks provenance for this symbol.
        if outcome.chain_status is ChainStatus.SKIPPED:
            result.provenance.chain_skipped += 1
        elif outcome.chain_status is ChainStatus.FETCHED:
            result.provenance.chain_ibkr += 1
            result.provenance.greeks_ibkr += outcome.greeks_ibkr
            result.provenance.greeks_yfinance += outcome.greeks_yfinance
        else:  # EMPTY / TIMEOUT / ERROR — nothing usable came back
            result.provenance.chain_failed += 1

        for message in outcome.errors:
            await tracker.add_error(message)

        # Circuit breaker: a run of back-to-back timeouts means the socket is dead, not that
        # this one symbol is slow. A SKIPPED symbol asked nothing of the socket, so it neither
        # advances nor clears the count; any other outcome proves the socket answered.
        if outcome.chain_status is ChainStatus.TIMEOUT:
            consecutive_chain_timeouts += 1
        elif outcome.chain_status is not ChainStatus.SKIPPED:
            consecutive_chain_timeouts = 0
        if max_consecutive_timeouts > 0 and consecutive_chain_timeouts >= max_consecutive_timeouts:
            # Bail before grinding the rest of the universe; this symbol's results are dropped.
            log.error(
                "scan: %d consecutive chain timeouts — aborting run, socket appears "
                "half-dead (processed %d/%d symbols)",
                consecutive_chain_timeouts,
                i + 1,
                n,
            )
            result.aborted_unhealthy = True
            # Every symbol in the triggering consecutive-timeout run failed for the same root
            # cause (dead socket), not its own issue — back up to where that run started, then
            # everything from there to the end of the universe was either dropped or never
            # attempted. The caller carries this forward as next cycle's forced-include set.
            run_start = i - consecutive_chain_timeouts + 1
            result.unreached_symbols = scan_order[run_start:]
            await tracker.add_error(
                f"socket half-dead — aborted after {consecutive_chain_timeouts} "
                f"consecutive timeouts"
            )
            break

        if outcome.analytics is None:
            continue  # analytics failed — nothing to accumulate for this symbol
        _iv_stats, tech_stats, _fund_stats = outcome.analytics
        analytics_map[symbol] = outcome.analytics

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
        # The timestamp is taken here, per symbol, rather than once for the whole run — see
        # `_persist_scan_state`.
        if outcome.did_fetch and tech_stats.price:
            fetched[symbol] = (tech_stats.price, datetime.now(UTC))

        cc_candidates.extend(outcome.cc_passed)
        csp_candidates.extend(outcome.csp_passed)
        generator_rejects.extend(outcome.rejected)

    await tracker.tick("market_data", "✅", f"{n}/{n} symbols")

    # Symbols the budget cut join anything an aborted socket never reached: both are "material
    # this cycle but not fetched", and both are carried forward as next cycle's must_include,
    # where `_fetch_priority` ranks them first so a long queue can't starve its tail.
    if over_budget:
        result.unreached_symbols = sorted(set(result.unreached_symbols) | set(over_budget))
        log.warning(
            "scan: chain-fetch budget (%.0fs) exhausted — %d of %d material symbols deferred "
            "to next cycle: %s",
            budget_seconds,
            len(over_budget),
            result.material_count,
            sorted(over_budget),
        )
        await tracker.add_error(
            f"fetch budget reached — {len(over_budget)} symbol(s) deferred to the next cycle"
        )

    # --- 5. Buy-to-own recommendations ---
    result.buy_candidates = generate_buy_candidates(would_own, holdings_symbols, analytics_map)
    # Persisted so the web layer can read them without recomputing (which would mean a
    # full scan per page load). Display-only data; nothing reads this back into a gate.
    save_buy_candidates(result.run_id, result.buy_candidates)

    # --- 6. Scoring THEN risk gate ---
    # Score first so the risk engine consumes its cumulative budgets (per-ticker /
    # per-sector / total-CSP / buying-power) greedily in priority order.
    await tracker.tick("scoring", "⏳")
    all_option_candidates = cc_candidates + csp_candidates
    cc_rejection_tally: dict[str, int] = {}
    csp_rejection_tally: dict[str, int] = {}
    # Top contracts that *failed* the gate per strategy (the "near misses"), surfaced on an empty
    # screen so a quiet cycle still names the closest trades and why they were rejected. Capped at
    # _NEAR_MISS_LIMIT; any beyond that are counted in the `_more` tally for a "…and N more" line.
    cc_near_misses: list[tuple[TradeCandidate, list[str]]] = []
    csp_near_misses: list[tuple[TradeCandidate, list[str]]] = []
    cc_near_miss_more = 0
    csp_near_miss_more = 0
    # Every contract this scan priced, and what became of it. Generator-stage rejects are
    # scored separately from the gated slate so they can be ranked and displayed, but they are
    # deliberately NOT fed to validate_candidates — the risk engine's cumulative budgets are
    # consumed greedily, and charging them against contracts that never qualified would
    # wrongly starve the ones that did.
    assessed: list[AssessedContract] = []
    if generator_rejects:
        try:
            scored_rejects = {
                c.candidate_id: c for c in score_candidates([cand for cand, _ in generator_rejects])
            }
            assessed.extend(
                AssessedContract(
                    candidate=scored_rejects.get(cand.candidate_id, cand),
                    stage=AssessmentStage.GENERATOR,
                    reasons=reasons,
                )
                for cand, reasons in generator_rejects
            )
        except Exception:
            log.exception("scan: scoring generator rejects failed — continuing without them")
    try:
        if all_option_candidates:
            scored = score_candidates(all_option_candidates)  # sorted DESC by blended_score
            # Hand the gate this sweep's per-symbol IV so existing option positions can charge
            # the RISK-UNIT concentration budgets, not just the raw-collateral one. The data is
            # already in `analytics_map` — no extra fetch. (The single-ticker deep-dive in
            # `run_ticker_scan` deliberately does NOT do this: it would have to fetch IV for
            # every other held position just to answer a one-symbol question.)
            verdicts = validate_candidates(
                scored,
                account,
                positions,
                iv_by_symbol={
                    sym: iv.current_iv
                    for sym, (iv, _tech, _fund) in analytics_map.items()
                    if iv.current_iv is not None
                },
            )
            verdict_map = {v.candidate_id: v for v in verdicts}
            gate_passed = [
                c
                for c in scored
                if verdict_map.get(c.candidate_id)
                and verdict_map[c.candidate_id].verdict.value == "pass"
            ]
            log.info(
                "scan: %d/%d candidates passed risk gate",
                len(gate_passed),
                len(all_option_candidates),
            )
            # Tally rejection reasons per strategy and per symbol (C7).
            # The per-symbol map drives the skip-reasons card sent at the end of each scan.
            per_symbol_skip: dict[str, list[str]] = {}
            for c in cc_candidates:
                v = verdict_map.get(c.candidate_id)
                if v and v.verdict.value != "pass":
                    for r in v.reasons:
                        cc_rejection_tally[r] = cc_rejection_tally.get(r, 0) + 1
                    bucket = per_symbol_skip.setdefault(c.underlying, [])
                    for r in v.reasons:
                        if r not in bucket:
                            bucket.append(r)
            for c in csp_candidates:
                v = verdict_map.get(c.candidate_id)
                if v and v.verdict.value != "pass":
                    for r in v.reasons:
                        csp_rejection_tally[r] = csp_rejection_tally.get(r, 0) + 1
                    bucket = per_symbol_skip.setdefault(c.underlying, [])
                    for r in v.reasons:
                        if r not in bucket:
                            bucket.append(r)
            # Score floor: only surface candidates above the configured quality bar.
            min_score = get_config().weights.get("min_candidate_score", 0)
            passed = [c for c in gate_passed if c.blended_score >= min_score]
            # Remove any symbol that has at least one passing candidate from the skip map —
            # we only surface symbols where *every* candidate was rejected (C7).
            for c in passed:
                per_symbol_skip.pop(c.underlying, None)
            top, dropped = select_top_candidates_detailed(passed)

            # Record the fate of every gated contract. `gate_passed` is pre-score-floor, so the
            # difference between it and `passed` is exactly the score-floor casualties.
            gate_passed_ids = {c.candidate_id for c in gate_passed}
            floor_ids = gate_passed_ids - {c.candidate_id for c in passed}
            top_ids = {c.candidate_id for c in top}
            dropped_reasons = {c.candidate_id: why for c, why in dropped}
            for cand in scored:
                if cand.candidate_id in top_ids:
                    assessed.append(AssessedContract(candidate=cand, stage=AssessmentStage.PASSED))
                elif cand.candidate_id in dropped_reasons:
                    why = dropped_reasons[cand.candidate_id]
                    assessed.append(
                        AssessedContract(
                            candidate=cand,
                            stage=(
                                AssessmentStage.DEDUPE if why == "dedupe" else AssessmentStage.TOP_N
                            ),
                            reasons=[f"{why}_not_surfaced"],
                        )
                    )
                elif cand.candidate_id in floor_ids:
                    assessed.append(
                        AssessedContract(
                            candidate=cand,
                            stage=AssessmentStage.SCORE_FLOOR,
                            reasons=["score_below_minimum"],
                        )
                    )
                else:
                    v = verdict_map.get(cand.candidate_id)
                    assessed.append(
                        AssessedContract(
                            candidate=cand,
                            stage=AssessmentStage.RISK_GATE,
                            reasons=list(v.reasons) if v is not None else [],
                        )
                    )

        else:
            top = []
            passed = []
            per_symbol_skip = {}
    except Exception:
        log.exception("scan: scoring/risk-gate failed — aborting")
        await tracker.error("scoring", "failed — aborting")
        return result

    # Rank the assessed-but-not-approved contracts best-first, per strategy. This now covers
    # generator-stage rejects too, so a symbol whose entire chain failed the delta band still
    # produces a named closest contract instead of silence.
    result.assessed = _rank_assessed(assessed)
    cc_near_misses, cc_near_miss_more = _near_misses(result.assessed, "covered_call")
    csp_near_misses, csp_near_miss_more = _near_misses(result.assessed, "cash_secured_put")

    result.cc_candidates = [c for c in top if c.strategy.value == "covered_call"]
    result.csp_candidates = [c for c in top if c.strategy.value == "cash_secured_put"]
    await tracker.tick("scoring", "✅", f"{len(top)}/{len(all_option_candidates)} passed")

    # --- 6b. Persist per-symbol materiality state for the next intraday cycle (S1/S10) ---
    # Only symbols we actually fetched this run get a fresh baseline; `cleared_floor` marks the
    # names that cleared the score floor so the next cycle always re-checks them. Runs in both
    # modes so the first intraday cycle (full sweep, no prior baselines) seeds the gate.
    cleared_floor_symbols = {c.underlying for c in passed}
    if fetched:
        await loop.run_in_executor(
            None,
            _persist_scan_state,
            fetched,
            cleared_floor_symbols,
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
            # (intraday loop only — manual /scan always reviews fresh).
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
                    analytics=analytics_map,
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
    # Assessment audit trail: every contract priced this run and why it was or wasn't
    # surfaced. Write-only forensics (pruned to 14d at EOD) — nothing reads it back, so it
    # can never influence a trading decision, and a write failure never aborts the scan.
    record_assessments(result.run_id, result.assessed)

    # --- 10. Send to Telegram ---
    # Presentation lives in scan_progress; this module only supplies the finished result plus the
    # three sender coroutines (held here because the scan tests monkeypatch them on this module).
    await send_scan_results(
        tracker,
        result,
        bot=bot,
        chat_id=chat_id,
        intraday=intraday,
        account=account,
        positions=positions,
        cc_empty_reason=_no_candidates_reason(
            result,
            len(cc_candidates),
            strategy="covered_call",
            positions=positions,
            rejection_tally=cc_rejection_tally,
            symbol_count=len({c.underlying for c in cc_candidates}),
            intraday=intraday,
        ),
        csp_empty_reason=_no_candidates_reason(
            result,
            len(csp_candidates),
            strategy="cash_secured_put",
            rejection_tally=csp_rejection_tally,
            symbol_count=len({c.underlying for c in csp_candidates}),
            intraday=intraday,
        ),
        cc_near_misses=cc_near_misses,
        cc_near_miss_more=cc_near_miss_more,
        csp_near_misses=csp_near_misses,
        csp_near_miss_more=csp_near_miss_more,
        per_symbol_skip=per_symbol_skip,
        sends=SendDeps(
            send_candidates=send_candidates,
            send_buy_list=send_buy_list,
            send_account_snapshot=send_account_snapshot,
        ),
        include_buy_list=include_buy_list,
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


# ---------------------------------------------------------------------------
# Single-ticker scan (Telegram /scan TICKER)
# ---------------------------------------------------------------------------


class TickerNotFoundError(Exception):
    """Raised when a ticker cannot be qualified on IBKR."""


class TickerPricingAborted(Exception):
    """Raised by `_price_and_gate_ticker` when analytics or the portfolio fetch fails outright.

    Carries the stage name (``"analytics"`` or ``"account"``) so `run_ticker_scan` can
    reproduce its original per-stage Telegram error message. A caller with no Telegram
    message to send (the promote drain handler, M4 Task 4.2) has no reason to catch this
    specially — it propagates as an ordinary handler failure instead.
    """

    def __init__(self, stage: str) -> None:
        super().__init__(stage)
        self.stage = stage


@dataclass
class TickerPricingResult:
    """Everything `_price_and_gate_ticker` produced for one symbol.

    This is `run_ticker_scan`'s steps 2-7 (chain fetch, analytics, positions/account fetch,
    CC/CSP screens, scoring, the `validate_candidates` gate) plus the pre-existing
    `record_assessments` call, returned as data instead of formatted straight to Telegram.
    `run_ticker_scan` uses a subset of these fields to carry on with its own steps 7b+
    (near-miss detection, hypothetical zones, the buy candidate, the Claude/Ollama review,
    and the Telegram card). The promote drain handler (M4 Task 4.2) instead uses `scored` +
    `verdict_map` + `min_score` + `chain_error` to find and classify one specific contract,
    without paying for the review or the formatting.
    """

    quotes: list[OptionQuote]
    # None on success. On a chain-fetch failure this is `str(exc)` (or "timed out" for a
    # `TimeoutError`) — genuinely new: `run_ticker_scan` itself still only sees an empty
    # `quotes` list and a log line, same as before this refactor.
    chain_error: str | None
    iv_stats: IVStats
    tech_stats: TechnicalStats
    fund_stats: FundamentalStats
    positions: list[PositionSnapshot]
    account: AccountSnapshot
    stock_pos: PositionSnapshot | None
    is_held: bool
    csp_skip_reason: str | None
    scored: list[TradeCandidate]
    verdict_map: dict[str, RiskVerdict]
    min_score: float
    cc_passed: list[TradeCandidate]
    csp_passed: list[TradeCandidate]
    ticker_assessed: list[AssessedContract]


async def _price_and_gate_ticker(ib: IB, ticker: str) -> TickerPricingResult:
    """Fetch a fresh chain for *ticker*, screen + score + gate CC/CSP candidates, and record
    the assessment audit trail.

    Extracted out of `run_ticker_scan` (M4 Task 4.2) so a promote can re-price and re-gate a
    single contract exactly as a `/scan TICKER` would — same generators, same scoring, same
    Rules Engine, same audit trail — without needing a live `bot`/`progress_msg_id` or paying
    for the Claude review and Telegram formatting that follow in `run_ticker_scan`. Ticker
    qualification (`run_ticker_scan`'s step 1) stays with the caller:
    `get_option_chain_quotes_async` already qualifies the stock itself, so an unknown ticker
    surfaces here as an empty chain, not a separate error path.

    Never raises for a chain-fetch failure — that mirrors the pre-existing swallow-and-log
    behavior: `quotes` comes back empty and the failure text lands in `chain_error`. Raises
    `TickerPricingAborted` when analytics or the portfolio fetch fails outright, since nothing
    downstream (screens, scoring, the gate) can run without them.
    """
    cfg = get_config()
    loop = asyncio.get_running_loop()

    # 2. Fetch option chain.
    quotes: list[OptionQuote] = []
    chain_error: str | None = None
    try:
        quotes = await asyncio.wait_for(
            get_option_chain_quotes_async(ib, ticker),
            timeout=cfg.market_data.symbol_timeout_seconds,
        )
    except TimeoutError:
        log.error("ticker_scan: option chain for %s timed out", ticker)
        chain_error = "timed out"
        drain_market_data_lines(ib)
    except Exception as exc:
        log.exception("ticker_scan: option chain failed for %s", ticker)
        chain_error = str(exc)
        drain_market_data_lines(ib)

    # 3. Analytics (yfinance) — blocking, run off-thread.
    # require_parity — see `infer_spot_from_quotes`; a strike-quantized spot must never reach
    # TechnicalStats.price, which is persisted as the materiality baseline.
    spot_override = infer_spot_from_quotes(quotes, require_parity=True) if quotes else None
    try:
        iv_stats, tech_stats, fund_stats = await loop.run_in_executor(
            None, _fetch_analytics, ticker, quotes, spot_override, None
        )
    except Exception as exc:
        log.exception("ticker_scan: analytics failed for %s", ticker)
        raise TickerPricingAborted("analytics") from exc

    # 4. Portfolio: fetch positions and account (needed for CC sizing / CSP collateral).
    try:
        positions: list[PositionSnapshot] = get_positions(ib)
        managed = ib.managedAccounts()
        acct = cfg.secrets.ibkr_account or (managed[0] if managed else "")
        account: AccountSnapshot = await get_account_snapshot_async(ib, acct)
    except Exception as exc:
        log.exception("ticker_scan: failed to fetch positions/account for %s", ticker)
        raise TickerPricingAborted("account") from exc

    # 5. CC candidates — only if we hold the stock.
    cc_candidates: list[TradeCandidate] = []
    ticker_rejects: list[tuple[TradeCandidate, list[str]]] = []
    stock_pos = next(
        (
            p
            for p in positions
            if (p.underlying or p.symbol) == ticker and p.sec_type == "STK" and p.position > 0
        ),
        None,
    )
    is_held = stock_pos is not None
    if stock_pos and quotes:
        existing_short_calls = sum(
            int(abs(p.position))
            for p in positions
            if (p.underlying or p.symbol) == ticker
            and p.sec_type == "OPT"
            and p.right == OptionRight.CALL
            and p.position < 0
        )
        cc_screen = screen_cc_candidates(
            ticker,
            quotes,
            stock_pos,
            iv_stats,
            tech_stats,
            fund_stats,
            existing_short_calls=existing_short_calls,
        )
        cc_candidates = cc_screen.passed
        ticker_rejects.extend(cc_screen.rejected)

    # 6. CSP candidates — always attempt (the screen filters by would_own).
    csp_candidates: list[TradeCandidate] = []
    csp_skip_reason: str | None = None
    if quotes:
        csp_screen = screen_csp_candidates(
            ticker, quotes, account, iv_stats, tech_stats, fund_stats, positions=positions
        )
        csp_candidates = csp_screen.passed
        ticker_rejects.extend(csp_screen.rejected)
        csp_skip_reason = csp_screen.skipped

    # 7. Scoring + risk gate on CC+CSP.
    all_option_candidates = cc_candidates + csp_candidates
    scored: list[TradeCandidate] = []
    verdict_map: dict[str, RiskVerdict] = {}
    min_score: float = 0
    if all_option_candidates:
        try:
            scored = score_candidates(all_option_candidates)  # sorted DESC by blended_score
            verdicts = validate_candidates(scored, account, positions)
            verdict_map = {v.candidate_id: v for v in verdicts}
            min_score = get_config().weights.get("min_candidate_score", 0)
            passed = [
                c
                for c in scored
                if verdict_map.get(c.candidate_id)
                and verdict_map[c.candidate_id].verdict.value == "pass"
                and c.blended_score >= min_score
            ]
        except Exception:
            log.exception("ticker_scan: scoring/risk-gate failed for %s", ticker)
            passed = []
        cc_passed = [c for c in passed if c.strategy.value == "covered_call"]
        csp_passed = [c for c in passed if c.strategy.value == "cash_secured_put"]
    else:
        cc_passed = []
        csp_passed = []

    # Assemble every contract this deep-dive priced, gate-stage and generator-stage alike, so
    # the card can name the closest miss and list the alternatives it considered. Before this,
    # a ticker whose whole chain failed the delta band produced no candidate at all and the
    # near-miss block silently vanished.
    passed_ids = {c.candidate_id for c in cc_passed + csp_passed}
    ticker_assessed: list[AssessedContract] = [
        AssessedContract(candidate=c, stage=AssessmentStage.PASSED) for c in cc_passed + csp_passed
    ]
    for cand in scored:
        if cand.candidate_id in passed_ids:
            continue
        v = verdict_map.get(cand.candidate_id)
        if v is not None and v.verdict.value == "pass":
            # Cleared the gate but fell below the score floor (else it'd be in `passed`).
            ticker_assessed.append(
                AssessedContract(
                    candidate=cand,
                    stage=AssessmentStage.SCORE_FLOOR,
                    reasons=["score_below_minimum"],
                )
            )
        else:
            ticker_assessed.append(
                AssessedContract(
                    candidate=cand,
                    stage=AssessmentStage.RISK_GATE,
                    reasons=list(v.reasons) if v is not None else [],
                )
            )
    if ticker_rejects:
        try:
            scored_rejects = {
                c.candidate_id: c for c in score_candidates([c for c, _ in ticker_rejects])
            }
        except Exception:
            log.warning("ticker_scan: scoring rejects failed for %s", ticker, exc_info=True)
            scored_rejects = {}
        ticker_assessed.extend(
            AssessedContract(
                candidate=scored_rejects.get(cand.candidate_id, cand),
                stage=AssessmentStage.GENERATOR,
                reasons=reasons,
            )
            for cand, reasons in ticker_rejects
        )
    ticker_assessed = _rank_assessed(ticker_assessed)
    # Same write-only audit trail as the full scan, keyed by a per-deep-dive run id.
    record_assessments(f"ticker-{uuid.uuid4().hex[:8]}", ticker_assessed)

    return TickerPricingResult(
        quotes=quotes,
        chain_error=chain_error,
        iv_stats=iv_stats,
        tech_stats=tech_stats,
        fund_stats=fund_stats,
        positions=positions,
        account=account,
        stock_pos=stock_pos,
        is_held=is_held,
        csp_skip_reason=csp_skip_reason,
        scored=scored,
        verdict_map=verdict_map,
        min_score=min_score,
        cc_passed=cc_passed,
        csp_passed=csp_passed,
        ticker_assessed=ticker_assessed,
    )


async def run_ticker_scan(
    ib: IB,
    ticker: str,
    *,
    bot: object,
    chat_id: str,
    progress_msg_id: int,
) -> None:
    """Run a single-ticker on-demand scan and edit *progress_msg_id* with the result.

    Fetches the option chain for *ticker*, runs analytics + CC/CSP/buy-candidate
    generation, applies scoring and the risk gate, and formats a compact Telegram
    MarkdownV2 summary.  The progress message is always edited — either with the
    result or an error.  Never raises (errors edit the message and return).

    Raises:
        TickerNotFoundError: if *ticker* cannot be qualified as an IBKR Stock.
    """
    from src.ibkr.contracts import qualify_stock_async
    from src.notify.formatters import format_ticker_scan_result

    loop = asyncio.get_running_loop()

    # 1. Validate the ticker exists on IBKR.
    try:
        await qualify_stock_async(ib, ticker)
    except ValueError as exc:
        raise TickerNotFoundError(ticker) from exc

    # 2-7. Fetch a fresh chain, run analytics, screen + score + gate CC/CSP candidates, and
    # record the assessment audit trail — shared with the promote drain handler (M4 Task 4.2).
    try:
        priced = await _price_and_gate_ticker(ib, ticker)
    except TickerPricingAborted as exc:
        message = {
            "analytics": "❌ *Scan failed* — analytics error\\.",
            "account": "❌ *Scan failed* — account fetch error\\.",
        }[exc.stage]
        await _ticker_edit_msg(bot, chat_id, progress_msg_id, message)
        return

    quotes = priced.quotes
    iv_stats, tech_stats, fund_stats = priced.iv_stats, priced.tech_stats, priced.fund_stats
    positions, account = priced.positions, priced.account
    stock_pos, is_held = priced.stock_pos, priced.is_held
    csp_skip_reason = priced.csp_skip_reason
    cc_passed, csp_passed = priced.cc_passed, priced.csp_passed
    ticker_assessed = priced.ticker_assessed

    cc_reject_reasons: list[str] = []
    csp_reject_reasons: list[str] = []
    cc_near_miss: TradeCandidate | None = None
    csp_near_miss: TradeCandidate | None = None

    # Why was a strategy empty? Name the closest contract that failed plus exactly what it
    # failed on, so the card explains "No qualifying X options" with a real strike rather than
    # going silent (the single-ticker analogue of C7's skip-reasons card).
    def _closest(strategy_value: str) -> tuple[TradeCandidate | None, list[str]]:
        for a in ticker_assessed:
            if not a.passed and a.candidate.strategy.value == strategy_value:
                return a.candidate, a.reasons
        return None, []

    if not cc_passed:
        cc_near_miss, cc_reject_reasons = _closest("covered_call")
    if not csp_passed:
        csp_near_miss, csp_reject_reasons = _closest("cash_secured_put")

    # 7b. Hypothetical fair value — informational only, never scored or gated. Runs only when
    # nothing above already carries a real `.ideal` zone to show: no qualifying contract *and*
    # no near-miss either, which happens when the symbol never reached a single quote (off the
    # would_own allowlist for a CSP, or shares not held for a CC) or the chain had no contracts
    # of that right at all. Priced at the strategy's own configured mid-DTE since there is no
    # actual contract's DTE to anchor to.
    def _mid_dte(cfg_key: str) -> int:
        strat_cfg = get_config().risk.get(cfg_key, {})
        return int(((strat_cfg.get("dte_min") or 21) + (strat_cfg.get("dte_max") or 45)) / 2)

    csp_hypothetical: IdealZone | None = None
    if not csp_passed and csp_near_miss is None and tech_stats.price:
        csp_hypothetical = compute_ideal_zone(
            symbol=ticker,
            right=OptionRight.PUT,
            dte=_mid_dte("cash_secured_put"),
            spot=tech_stats.price,
            tech=tech_stats,
            iv=iv_stats,
            fund=fund_stats,
        )

    cc_hypothetical: IdealZone | None = None
    if not cc_passed and cc_near_miss is None and tech_stats.price:
        cc_hypothetical = compute_ideal_zone(
            symbol=ticker,
            right=OptionRight.CALL,
            dte=_mid_dte("covered_call"),
            spot=tech_stats.price,
            tech=tech_stats,
            iv=iv_stats,
            fund=fund_stats,
            cost_basis=stock_pos.avg_cost if stock_pos else None,
        )

    # 8. Buy candidate for this single ticker.
    analytics_map: dict[str, tuple[IVStats, TechnicalStats, FundamentalStats]] = {
        ticker: (iv_stats, tech_stats, fund_stats)
    }
    holdings_symbols: set[str] = {
        p.underlying or p.symbol for p in positions if p.sec_type == "STK" and p.position > 0
    }
    buy_candidates = generate_buy_candidates([ticker], holdings_symbols, analytics_map)
    buy_candidate = buy_candidates[0] if buy_candidates else None
    # Persisted under a scan-prefixed run id so a single-ticker /scan can never displace
    # the full scan's recommendations list (latest_buy_candidates filters this prefix out).
    save_buy_candidates(f"scan-{ticker}-{int(time.time())}", buy_candidates)

    # 8b. Deep-dive enrichment (enrichment only — never gates; the /scan TICKER path only formats
    # text, so nothing here can reach execution).
    #
    # The macro + sector backdrop (VIX regime + how the name's industry / the broad market are
    # trading) is deterministic and ALWAYS fetched — it doesn't depend on a tradeable contract
    # existing, and feeds both the "Market & Sector" card line and the LLM Read. Fetched off-thread
    # (yfinance/OHLCV block), fail-soft.
    #
    # The LLM "Read" reviews the best CC + best CSP. When neither cleared the gate we fall back to
    # reviewing the closest *near-miss* per strategy so the deep-dive still produces a synthesis
    # instead of going silent — these near-misses surface only as the overall summary, never as a
    # per-candidate verdict (the card shows verdicts only beside a qualifying contract). Prior-
    # recommendation memory for this ticker is injected so the read can learn from how past calls
    # on the same name played out. Per-symbol analytics are passed so the model sees the raw
    # technical/fundamental/IV signals, not just the composite scores.
    sector_ctx: SectorContext | None = None
    market_conditions: MarketConditions | None = None
    reviews: list[ClaudeReview] = []
    memory: list = []
    try:
        memory, market_conditions, sector_ctx = await asyncio.gather(
            loop.run_in_executor(None, _load_memory, [ticker]),
            loop.run_in_executor(None, get_market_conditions),
            loop.run_in_executor(None, get_sector_context, ticker),
        )
    except Exception:
        log.warning("ticker_scan: backdrop fetch failed for %s", ticker, exc_info=True)

    to_review = cc_passed[:1] + csp_passed[:1]
    if not to_review:
        to_review = [c for c in (cc_near_miss, csp_near_miss) if c is not None]
    if to_review:
        spot_prices = {ticker: tech_stats.price} if tech_stats.price else None
        sector_block = render_sector_context(sector_ctx)
        try:
            reviews = await loop.run_in_executor(
                None,
                lambda: review_candidates(
                    to_review,
                    account,
                    history=memory,
                    market_conditions=market_conditions,
                    spot_prices=spot_prices,
                    sector_context=sector_block,
                    single_ticker=True,
                    analytics=analytics_map,
                ),
            )
        except Exception:
            log.warning("ticker_scan: Claude/Ollama review failed for %s", ticker, exc_info=True)

    # 9. Format and edit the progress message.
    # Greeks provenance for the footer: did any contract's Greeks fall back to yfinance BS?
    greeks_fallback = any(q.greeks_source == "black_scholes" for q in quotes)
    text = format_ticker_scan_result(
        ticker=ticker,
        iv_stats=iv_stats,
        tech_stats=tech_stats,
        fund_stats=fund_stats,
        cc_candidates=cc_passed,
        csp_candidates=csp_passed,
        buy_candidate=buy_candidate,
        is_held=is_held,
        quotes_available=bool(quotes),
        reviews=reviews,
        cc_reject_reasons=cc_reject_reasons,
        csp_reject_reasons=csp_reject_reasons,
        cc_near_miss=cc_near_miss,
        csp_near_miss=csp_near_miss,
        csp_skip_reason=csp_skip_reason,
        cc_hypothetical=cc_hypothetical,
        csp_hypothetical=csp_hypothetical,
        greeks_fallback=greeks_fallback,
        market_conditions=market_conditions,
        sector_context=sector_ctx,
        assessed=ticker_assessed,
    )
    await _ticker_edit_msg(bot, chat_id, progress_msg_id, text)
    log.info(
        "ticker_scan complete — %s CC=%d CSP=%d buy=%s",
        ticker,
        len(cc_passed),
        len(csp_passed),
        buy_candidate is not None,
    )


async def _ticker_edit_msg(bot: object, chat_id: str, message_id: int, text: str) -> None:
    """Best-effort edit of a Telegram message (silently swallows errors)."""
    try:
        await bot.edit_message_text(  # type: ignore[attr-defined]
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="MarkdownV2",
        )
    except Exception:
        log.warning("ticker_scan: failed to edit message %s", message_id, exc_info=True)
