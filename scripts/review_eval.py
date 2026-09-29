"""Replay stored `candidates` rows through the local Ollama reviewer and report review quality.

Built for Task 10 (scan-loop remediation): validates a model swap
(`config/settings.yaml → claude.ollama_model`) and the new schema-constrained FACTS/rubric prompt
before committing to it in production, against the pre-fix baseline (2026-09-29): 6/6 "wait" on
single-candidate prompts, 1/3 candidates reviewed on the multi-candidate prompt.

**Not a pure read — one disclosed exception (Task 10 fix round 2).** This script never writes
`candidates`, approvals, orders, `claude_memory`, the verdict ledger, or any other table itself —
but because it calls `scan.py`'s own `_fetch_analytics` to build a production-shaped prompt (see
below), it can populate the same two shared, idempotent caches a live scan populates:
`price_history` (`analytics.iv.get_iv_stats` and `analytics.technicals.get_technical_stats` both
call `analytics.price_data.get_ohlcv`, which appends any missing daily bars via
`storage.price_history.append_bars` — insert-missing-only, never overwrites a settled bar) and
`fundamentals_cache` (`analytics.fundamentals.get_fundamental_stats` upserts a
`FundamentalCacheRow` when its entry is missing or past its earnings-aware TTL). Both are the same
rows/upserts a live scan would write for these symbols regardless of whether this script ever ran
— stubbing them out was considered and rejected: it would make the eval diverge from the real
prompt again, the exact gap fix round 1 closed. `_load_candidates`/`_build_history` only `SELECT`
(`candidates`/`claude_memory`); `_build_market_conditions` (`get_market_conditions`) uses only the
process-local, in-memory `@daily_cached` decorator (`src/common/cache.py`) and writes nothing to
any table — verified by reading every function this script's call graph reaches, not assumed.

Bypasses `ollama_runner`'s module-level circuit breaker and the `claude.enabled` switch entirely —
it builds the prompt and POSTs to `/api/generate` directly (mirroring `ollama_runner._generate`'s
request body byte-for-byte) instead of going through `ollama_runner.review_candidates`, so a
tripped production circuit (or `enabled: false`) never blocks an eval run.

**Production-shaped by default (Task 10 fix round 1).** A first cut of this script built the
prompt with no `analytics`, `market_conditions`, or `history` — understating the real prompt the
production scan sends (`scan.py`'s full-universe review call passes all three; a full scan can
also send up to `risk_limits.yaml → portfolio.max_new_positions_per_run` candidates, default 10).
This version reuses `scan.py`'s own `_fetch_analytics`/`_load_memory` and
`analytics.market_conditions.get_market_conditions` — the exact functions production calls, none
of which need an IBKR connection (yfinance/`price_history`/`iv_history`/`claude_memory` only) — so
the replayed prompt matches what a real scan would have sent for these candidates. Each piece
degrades independently and is reported: a symbol whose analytics fetch fails is just missing from
the FACTS/analytics block (matching production's per-symbol fail-soft behaviour), and a failed
`get_market_conditions()` call (it doesn't raise per its own docstring, but this script still
guards it) drops the VIX line rather than aborting the run.

Also reports real `/api/generate` metadata — `prompt_eval_count` (input tokens), `eval_count`
(output tokens), and `total_duration`/`load_duration` (wall time, split out the model-load
portion when Ollama reports it) — needed to check `ollama_num_ctx` headroom and
`ollama_timeout_seconds` margin against the *real* prompt shape, not an approximation.

Usage:
    source .venv/bin/activate
    python -m scripts.review_eval --model qwen3.5:4b --runs 2
    python -m scripts.review_eval --model qwen3.5:4b --runs 2 --limit 5
    python -m scripts.review_eval --model qwen3.5:9b --ids c-001 c-002
    python -m scripts.review_eval --model qwen3:8b --since 2026-06-01 --limit 10
    # Cold-load measurement (unload first, use a generous client timeout so a slow cold load
    # isn't cut off before you can see how long it really took):
    ollama stop qwen3.5:4b
    python -m scripts.review_eval --model qwen3.5:4b --runs 1 --limit 10 --timeout 400
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.claude.news_context import news_block_for_candidates
from src.claude.ollama_runner import REVIEW_SCHEMA
from src.claude.parser import parse_ollama_review_output
from src.claude.prompts.strategist import AnalyticsMap, build_prompt
from src.common.config import get_config
from src.common.schemas import AccountSnapshot, ClaudeReview, MarketConditions, TradeCandidate
from src.storage.db import init_db, session_scope
from src.storage.models import CandidateRow

# A generic account snapshot — the reviewer only reads these for the PORTFOLIO SUMMARY block;
# they don't affect verdict quality, so a fixed stand-in is fine for an eval run.
_STUB_ACCOUNT = AccountSnapshot(
    account="EVAL",
    net_liquidation=100_000.0,
    total_cash=50_000.0,
    buying_power=80_000.0,
    maintenance_margin=10_000.0,
    excess_liquidity=70_000.0,
)


def _load_candidates(
    ids: list[str] | None, since: date, limit: int
) -> tuple[list[TradeCandidate], str]:
    """Load up to `limit` distinct candidates (most recent first). Returns (candidates, note).

    `note` is a human-readable string describing where the rows came from — including the
    since-date fallback when nothing was found in the requested window (per the task brief: if
    the table has no rows since the default cutover, use the most recent rows available and say
    so instead of silently returning nothing).
    """
    note = ""
    with session_scope() as s:
        if ids:
            rows = (
                s.query(CandidateRow)
                .filter(CandidateRow.candidate_id.in_(ids))
                .order_by(CandidateRow.created_at.desc())
                .all()
            )
            note = f"{len(rows)} row(s) matching --ids {ids}"
        else:
            since_dt = datetime.combine(since, datetime.min.time())
            rows = (
                s.query(CandidateRow)
                .filter(CandidateRow.created_at >= since_dt)
                .order_by(CandidateRow.created_at.desc())
                .all()
            )
            if rows:
                note = f"{len(rows)} row(s) since {since}"
            else:
                rows = (
                    s.query(CandidateRow)
                    .order_by(CandidateRow.created_at.desc())
                    .limit(limit)
                    .all()
                )
                note = (
                    f"no candidates rows since {since} — falling back to the {len(rows)} "
                    "most recent row(s) in the table"
                )

        seen: set[str] = set()
        out: list[TradeCandidate] = []
        for row in rows:
            if row.candidate_id in seen:
                continue
            seen.add(row.candidate_id)
            try:
                out.append(TradeCandidate.model_validate(row.payload))
            except Exception as exc:  # noqa: BLE001 — one bad row must not abort the eval
                print(f"  (skipping {row.candidate_id}: {exc})")
            if len(out) >= limit:
                break
    return out, note


def _build_analytics(underlyings: set[str]) -> AnalyticsMap:
    """Real per-symbol IV/technicals/fundamentals, reusing scan.py's own `_fetch_analytics` —
    the exact function the production scan calls per symbol. No IBKR connection needed (it reads
    yfinance/`price_history`/`iv_history` only, never `ib`). Degrades gracefully: a symbol whose
    fetch raises is just omitted from the map, matching production's per-symbol
    continue-on-failure behaviour (scan.py:1391-1392, `if outcome.analytics is None: continue`).
    """
    from src.orchestrator.scan import _fetch_analytics

    analytics: AnalyticsMap = {}
    for symbol in sorted(underlyings):
        try:
            analytics[symbol] = _fetch_analytics(symbol)
        except Exception as exc:  # noqa: BLE001 — one symbol's failure must not sink the eval
            print(f"  (analytics unavailable for {symbol}: {exc})")
    return analytics


def _build_market_conditions() -> MarketConditions | None:
    """The real VIX/macro backdrop, via the same `get_market_conditions()` the scan calls.

    It never raises internally (each field degrades to None on its own), but this still guards
    the call — an eval script must never abort on an enrichment-only fetch.
    """
    from src.analytics.market_conditions import get_market_conditions

    try:
        return get_market_conditions()
    except Exception as exc:  # noqa: BLE001
        print(f"  (market conditions unavailable: {exc})")
        return None


def _build_history(underlyings: list[str]) -> list:
    """Real prior-recommendation memory, via scan.py's own `_load_memory` — the exact function
    the production scan calls. DB-only (reads `claude_memory`), no network."""
    from src.orchestrator.scan import _load_memory

    try:
        return _load_memory(underlyings)
    except Exception as exc:  # noqa: BLE001
        print(f"  (memory history unavailable: {exc})")
        return []


def _build_news_block(candidates: list[TradeCandidate]) -> str:
    """Real NEWS block (Task 11): Google News RSS search + yfinance headlines for these
    candidates' underlyings, via the same `news_block_for_candidates` production calls
    (`ollama_runner.review_candidates` when `claude.tool_research_enabled`). Never raises —
    degrades to an empty block like every other piece of this prompt.
    """
    cfg = get_config().claude
    block, _index = news_block_for_candidates(
        candidates,
        per_symbol=cfg.news_per_symbol,
        days=cfg.news_days,
        max_items=cfg.news_max_items,
    )
    return block


def _build_production_prompt(candidates: list[TradeCandidate]) -> str:
    """The prompt a real full-universe scan would send for these candidates: real analytics
    (IV/technicals/fundamentals) per underlying, real prior-recommendation history, real VIX/macro
    conditions, spot prices read off the same analytics (mirroring
    `scan.py`'s `spot_prices = {sym: tech.price for sym, (_iv, tech, _fund) in
    analytics_map.items() if tech.price}`) — not an approximation from a stored daily bar — and
    (Task 11) a real NEWS block. Does not replicate the bounded tool-calling research turn
    (`src.claude.ollama_tools.research_turn`) — this script mirrors `_generate`'s single-shot
    `/api/generate` request shape by design (see module docstring), not
    `review_candidates`'s `/api/chat` research path.
    """
    underlyings = {c.underlying for c in candidates}
    analytics = _build_analytics(underlyings)
    spot_prices = {sym: tech.price for sym, (_iv, tech, _fund) in analytics.items() if tech.price}
    history = _build_history(sorted(underlyings))
    market_conditions = _build_market_conditions()
    news_block = _build_news_block(candidates)
    return build_prompt(
        candidates,
        _STUB_ACCOUNT,
        history=history,
        market_conditions=market_conditions,
        spot_prices=spot_prices,
        analytics=analytics,
        news_block=news_block or None,
    )


def _generate_with_meta(
    prompt: str, model: str, timeout: float
) -> tuple[str | None, dict[str, object]]:
    """POST to Ollama's `/api/generate`, mirroring `ollama_runner._generate`'s request body
    exactly (same `format`/`think`/`keep_alive`/`options` keys, sourced from the same config),
    but returns the full response metadata alongside the text — `_generate` only returns the
    `response` string, discarding `prompt_eval_count`/`eval_count`/timing, which this script
    needs to measure real context-window headroom and cold-load latency (Task 10 fix round 1,
    finding 2). Kept as a standalone POST here rather than changing `_generate`'s return
    contract, which every other caller (`review_candidates`/`review_roll`/
    `write_journal_narrative`) depends on.
    """
    cfg = get_config().claude
    url = f"{cfg.ollama_host.rstrip('/')}/api/generate"
    body = {
        "model": model,
        "prompt": prompt,
        "format": REVIEW_SCHEMA,
        "stream": False,
        "think": False,
        "keep_alive": cfg.ollama_keep_alive,
        "options": {"temperature": cfg.ollama_temperature, "num_ctx": cfg.ollama_num_ctx},
    }
    try:
        resp = httpx.post(url, json=body, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return None, {"error": str(exc)}
    d = resp.json()
    meta: dict[str, object] = {
        "prompt_eval_count": d.get("prompt_eval_count"),
        "eval_count": d.get("eval_count"),
        "total_duration_s": round((d.get("total_duration") or 0) / 1e9, 1),
        "load_duration_s": round((d.get("load_duration") or 0) / 1e9, 1),
    }
    return d.get("response"), meta


def _run_once(
    candidates: list[TradeCandidate], model: str, timeout: float
) -> tuple[list[ClaudeReview], float, dict[str, object]]:
    """One production-shaped review call against `model`. Returns (reviews, wall_seconds, meta).

    Bypasses `ollama_runner.review_candidates`'s circuit breaker/`enabled` check entirely — see
    module docstring.
    """
    prompt = _build_production_prompt(candidates)
    t0 = time.monotonic()
    raw, meta = _generate_with_meta(prompt, model, timeout)
    elapsed = time.monotonic() - t0
    if raw is None:
        return [], elapsed, meta
    reviews = parse_ollama_review_output(raw, [c.candidate_id for c in candidates])
    return reviews, elapsed, meta


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay stored candidates through the local Ollama reviewer, "
        "production-shaped (real analytics/history/market conditions). Never writes candidates, "
        "approvals, orders, claude_memory, or the verdict ledger — but, via scan.py's own "
        "_fetch_analytics, may populate the shared price_history/fundamentals_cache caches, the "
        "same idempotent rows a live scan writes."
    )
    parser.add_argument("--model", required=True, help="Ollama model tag, e.g. qwen3:8b")
    parser.add_argument("--runs", type=int, default=1, help="review calls to make (default 1)")
    parser.add_argument("--ids", nargs="*", default=None, metavar="CANDIDATE_ID")
    parser.add_argument(
        "--since", type=date.fromisoformat, default=date(2026, 9, 14), metavar="YYYY-MM-DD"
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="max distinct candidates per call (default 10)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="client-side timeout in seconds (default: claude.ollama_timeout_seconds config "
        "value — pass a larger number to observe a cold load that would exceed it)",
    )
    args = parser.parse_args()

    timeout = (
        args.timeout if args.timeout is not None else get_config().claude.ollama_timeout_seconds
    )

    init_db()
    candidates, note = _load_candidates(args.ids, args.since, args.limit)
    print(f"Candidates: {note}")
    if not candidates:
        print("Nothing to evaluate — the candidates table is empty.")
        return
    print(f"Reviewing {len(candidates)} candidate(s): {[c.candidate_id for c in candidates]}")
    print(f"Model: {args.model}   Runs: {args.runs}   Client timeout: {timeout:.0f}s")
    print("Building production-shaped prompt (real analytics/history/market conditions)...")
    print("=" * 72)

    verdicts: Counter[str] = Counter()
    empty_evidence = 0
    total_reviewed = 0
    for run in range(1, args.runs + 1):
        reviews, elapsed, meta = _run_once(candidates, args.model, timeout)
        print(f"\n--- Run {run}/{args.runs} ({elapsed:.1f}s wall) ---")
        if "error" in meta:
            print(f"  FAILED: {meta['error']}")
        else:
            print(
                f"  prompt_eval_count={meta['prompt_eval_count']}  eval_count={meta['eval_count']}"
                f"  total_duration={meta['total_duration_s']}s"
                f"  load_duration={meta['load_duration_s']}s"
            )
        # Count DISTINCT candidates covered, not raw review objects — a model can return a
        # duplicate candidate_id (re-reviewing one candidate twice, often a near-empty/low-
        # confidence throwaway) while silently never covering a different requested id at all.
        # Counting objects instead of distinct ids would report that as "10/10 reviewed" when
        # only 9 of the 10 requested candidates actually got a review (found during fix round 1's
        # cold-load re-measurement: a 10-candidate production-shaped run returned two objects for
        # one candidate_id and zero for another, both requested).
        distinct_ids = {r.candidate_id for r in reviews}
        coverage_note = (
            f" ({len(reviews)} review object(s) returned — {len(reviews) - len(distinct_ids)} "
            "duplicate candidate_id(s))"
            if len(reviews) != len(distinct_ids)
            else ""
        )
        print(f"Reviewed {len(distinct_ids)}/{len(candidates)} requested candidates{coverage_note}")
        for r in reviews:
            verdicts[r.recommendation] += 1
            total_reviewed += 1
            if not r.evidence:
                empty_evidence += 1
            print(
                f"  {r.candidate_id:<24} {r.recommendation:<5} "
                f"evidence={r.evidence or '[]'} confidence={r.confidence}"
            )
        missing = {c.candidate_id for c in candidates} - distinct_ids
        if missing:
            print(f"  MISSING (requested, never reviewed): {sorted(missing)}")

    print("\n" + "=" * 72)
    print(f"Verdict distribution: {dict(verdicts)}")
    if total_reviewed:
        pct = empty_evidence / total_reviewed
        print(f"Empty evidence: {empty_evidence}/{total_reviewed} ({pct:.0%})")
    else:
        print("Empty evidence: n/a — nothing was reviewed")


if __name__ == "__main__":
    main()
