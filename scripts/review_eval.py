"""Replay stored `candidates` rows through the local Ollama reviewer and report review quality.

Built for Task 10 (scan-loop remediation): validates a model swap
(`config/settings.yaml → claude.ollama_model`) and the new schema-constrained FACTS/rubric prompt
before committing to it in production, against the pre-fix baseline (2026-09-29): 6/6 "wait" on
single-candidate prompts, 1/3 candidates reviewed on the multi-candidate prompt.

Read-only: no DB writes. Bypasses `ollama_runner`'s module-level circuit breaker and the
`claude.enabled` switch entirely — it calls the prompt builder + `_generate` + parser directly
instead of `ollama_runner.review_candidates`, so a tripped production circuit (or `enabled:
false`) never blocks an eval run.

Usage:
    source .venv/bin/activate
    python -m scripts.review_eval --model qwen3:8b --runs 2
    python -m scripts.review_eval --model qwen3.5:4b --runs 2 --limit 5
    python -m scripts.review_eval --model qwen3.5:9b --ids c-001 c-002
    python -m scripts.review_eval --model qwen3:8b --since 2026-09-01
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.claude import ollama_runner
from src.claude.parser import parse_ollama_review_output
from src.claude.prompts.strategist import build_prompt
from src.common.config import get_config
from src.common.schemas import AccountSnapshot, ClaudeReview, TradeCandidate
from src.storage.db import init_db, session_scope
from src.storage.models import CandidateRow
from src.storage.price_history import load_bars

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


def _spot_prices(candidates: list[TradeCandidate]) -> dict[str, float]:
    """Best-effort scan-time spot per underlying, from the latest stored daily bar.

    Historical rows carry no spot of their own (`TradeCandidate` doesn't store it); the FACTS
    block's moneyness/cushion lines (F1/F2) just degrade to absent when a symbol has no stored
    bar, matching production's fail-soft behaviour for a missing price.
    """
    spots: dict[str, float] = {}
    for underlying in {c.underlying for c in candidates}:
        bars = load_bars(underlying, limit=1)
        if bars:
            spots[underlying] = bars[-1].close
    return spots


def _run_once(
    candidates: list[TradeCandidate], model: str
) -> tuple[list[ClaudeReview], float | None]:
    """One review call against `model`. Returns (reviews, seconds) — seconds is None on failure.

    Bypasses `ollama_runner.review_candidates`'s circuit breaker/`enabled` check by calling the
    prompt builder + `_generate` + parser directly.
    """
    cfg = get_config().claude.model_copy(update={"ollama_model": model})
    prompt = build_prompt(candidates, _STUB_ACCOUNT, spot_prices=_spot_prices(candidates))
    t0 = time.monotonic()
    raw = ollama_runner._generate(prompt, cfg)
    elapsed = time.monotonic() - t0
    if raw is None:
        return [], None
    reviews = parse_ollama_review_output(raw, [c.candidate_id for c in candidates])
    return reviews, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay stored candidates through the local Ollama reviewer."
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
    args = parser.parse_args()

    init_db()
    candidates, note = _load_candidates(args.ids, args.since, args.limit)
    print(f"Candidates: {note}")
    if not candidates:
        print("Nothing to evaluate — the candidates table is empty.")
        return
    print(f"Reviewing {len(candidates)} candidate(s): {[c.candidate_id for c in candidates]}")
    print(f"Model: {args.model}   Runs: {args.runs}")
    print("=" * 72)

    verdicts: Counter[str] = Counter()
    empty_evidence = 0
    total_reviewed = 0
    for run in range(1, args.runs + 1):
        reviews, elapsed = _run_once(candidates, args.model)
        header = (
            f"--- Run {run}/{args.runs} ---"
            if elapsed is None
            else (f"--- Run {run}/{args.runs} ({elapsed:.1f}s) ---")
        )
        print(f"\n{header}")
        print(f"Reviewed {len(reviews)}/{len(candidates)} requested candidates")
        for r in reviews:
            verdicts[r.recommendation] += 1
            total_reviewed += 1
            if not r.evidence:
                empty_evidence += 1
            print(
                f"  {r.candidate_id:<24} {r.recommendation:<5} "
                f"evidence={r.evidence or '[]'} confidence={r.confidence}"
            )

    print("\n" + "=" * 72)
    print(f"Verdict distribution: {dict(verdicts)}")
    if total_reviewed:
        pct = empty_evidence / total_reviewed
        print(f"Empty evidence: {empty_evidence}/{total_reviewed} ({pct:.0%})")
    else:
        print("Empty evidence: n/a — nothing was reviewed")


if __name__ == "__main__":
    main()
