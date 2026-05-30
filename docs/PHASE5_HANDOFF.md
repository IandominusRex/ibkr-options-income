# Phase 5 Handoff — Claude Integration

> Read this first, then `PLAN.md` (Phase 5 entry) and `CLAUDE.md`.

## Where things stand (end of Phase 4)

**Phases 0–4 are complete and verified** (139/139 tests pass, `ruff` clean, `mypy` clean).

What now exists and should be **reused, not rebuilt**:

| File | What it gives you |
|---|---|
| `src/engine/scoring.py` | `score_candidates(candidates) -> list[TradeCandidate]` — fills `blended_score`, sorted DESC |
| `src/engine/decision_engine.py` | `select_top_candidates(candidates, n) -> list[TradeCandidate]` — top-N with `rationale_tags` |
| `src/engine/risk_engine.py` | `validate_candidates(candidates, account, positions) -> list[RiskVerdict]` — PASS/REJECT with reasons |
| `src/common/schemas.py` | `TradeCandidate`, `RiskVerdict`, `ClaudeReview` — Phase 5 **produces** `ClaudeReview` objects |
| `src/common/config.py` | `get_config().claude` — CLI command, timeout, retries, output_format, enabled flag |

The typical Phase 4→5 call sequence in the orchestrator will be:

```python
raw = generate_cc_candidates(...) + generate_csp_candidates(...)
scored = score_candidates(raw)
top = select_top_candidates(scored, n=10)
verdicts = validate_candidates(top, account, positions)
approved = [c for c, v in zip(top, verdicts) if v.verdict == Verdict.PASS]
# Phase 5: reviews = await_claude_review(approved, account)
```

## Phase 5 goal (acceptance criterion)

> Given a `list[TradeCandidate]` (PASS verdicts from Phase 4) and an `AccountSnapshot`,
> Phase 5 produces a `list[ClaudeReview]` — one per candidate — by shelling out to
> `claude -p --output-format json`.
>
> If Claude is unavailable or output is unparseable, the function returns `[]` (deterministic
> fallback: the caller uses the Rules-Engine-approved ranked list as-is).
>
> `pytest` green, `mypy` clean. No live TWS or real Claude CLI needed for tests (mock subprocess).

## Files to create

```
src/claude/runner.py         # subprocess wrapper: build prompt, call claude -p, return raw output
src/claude/parser.py         # parse double-envelope → list[ClaudeReview]; handle all failure modes
src/claude/prompts/          # directory for role templates
src/claude/prompts/strategist.py   # main prompt builder: candidates + portfolio summary → str
tests/test_claude.py         # unit tests; mock subprocess.run
```

`src/claude/__init__.py` already exists (empty).

## Implementation notes (the parts that bite)

### 1. `runner.py` — subprocess wrapper

```python
def review_candidates(
    candidates: list[TradeCandidate],
    account: AccountSnapshot,
) -> list[ClaudeReview]:
    """Shell out to `claude -p`, parse output → list[ClaudeReview]. Returns [] on any failure."""
```

Key steps:
1. Build the prompt string via `strategist.build_prompt(candidates, account)`.
2. Call `subprocess.run(["claude", "-p", prompt, "--output-format", "json"], capture_output=True, text=True, timeout=cfg.claude.timeout_seconds)`.
3. On `subprocess.TimeoutExpired` or non-zero return code → log + return `[]`.
4. Pass `result.stdout` to `parser.parse_claude_output(raw)` → return the result (may be `[]`).
5. If `cfg.claude.enabled` is False, skip the subprocess and return `[]` immediately.
6. Respect `cfg.claude.max_retries` — retry once on transient failure (non-zero returncode with empty stdout, or timeout).

**Important:** `claude -p` can take 30–120 s for a multi-candidate review. Set timeout to `cfg.claude.timeout_seconds` (default 180 s). Do NOT use `asyncio.create_subprocess_exec` here — the orchestrator is a one-shot process and the subprocess blocks the single thread intentionally.

### 2. `parser.py` — double-envelope parse

`--output-format json` from `claude -p` returns an **envelope** like:

```json
{
  "type": "result",
  "subtype": "success",
  "result": "<assistant text here, possibly JSON>",
  "total_cost_usd": 0.003,
  ...
}
```

The assistant's own JSON lives inside `result` as a **string**. Parse steps:

1. Parse the outer envelope with `json.loads(raw)`.
2. Extract `envelope["result"]` (a string).
3. Strip markdown code fences if present: e.g. `` ```json\n...\n``` `` → strip to inner content.
4. Parse the inner string as JSON.
5. Validate against `ClaudeReview` schema (or a list of them).
6. Return `[]` if **any** step fails — never propagate exceptions to the orchestrator.

```python
def parse_claude_output(raw: str) -> list[ClaudeReview]:
    """Parse raw claude -p JSON output → list[ClaudeReview]. Returns [] on any parse failure."""
```

**Expected inner JSON shape** (one object per candidate, or a list):

```json
[
  {
    "candidate_id": "...",
    "priority": 1,
    "recommendation": "sell",
    "why_attractive": "...",
    "risks": "...",
    "tradeoffs": "...",
    "assignment_considerations": "..."
  }
]
```

The `ClaudeReview` schema is in `src/common/schemas.py` — match it exactly. `rolling_considerations` and `confidence` are optional (have defaults).

### 3. `prompts/strategist.py` — prompt builder

```python
def build_prompt(candidates: list[TradeCandidate], account: AccountSnapshot) -> str:
    """Build the full prompt string sent to claude -p."""
```

The prompt should:
- Open with a **role**: "You are a disciplined options income strategist reviewing proposed covered call and cash-secured put trades for an IBKR account."
- Include a **portfolio summary** from `account`: net liquidation, buying power, maintenance margin.
- For each candidate, include: symbol, strategy, strike, expiry, DTE, premium, ROC%, annualized yield, delta, IV rank, blended_score, rationale_tags, and top ScoreCard components.
- Instruct Claude to return **only a JSON array** matching the `ClaudeReview` schema, one object per candidate, ordered by your recommended priority (1 = best).
- Tell Claude to be **concise** (2–3 sentences per field) — this is Telegram-destined output.
- Remind Claude it is **enrichment only** — the Rules Engine already approved these; Claude re-ranks and explains risks/tradeoffs.

Keep prompts in `src/claude/prompts/` as Python string builders (not Jinja templates — avoid another dep).

### 4. `.mcp.json` — trading_skills MCP (optional for Phase 5, wire up now)

Phase 5 is the right time to create `.mcp.json` so the headless `claude -p` subprocess can use `trading_skills` for ad-hoc lookups during reasoning:

```json
{
  "mcpServers": {
    "trading_skills": {
      "command": "uvx",
      "args": ["trading-skills"],
      "env": {
        "IB_HOST": "127.0.0.1",
        "IB_PORT": "7497",
        "IB_CLIENT_ID": "20"
      }
    }
  }
}
```

- Use `clientId` 20 (reserved for trading_skills MCP in `config/settings.yaml`).
- `.mcp.json` is not gitignored — it's safe (no secrets). Provide `.mcp.json.example` too.
- This is optional for Phase 5 acceptance; the tests don't require it.

### 5. Timeout + retry details

```python
cfg = get_config().claude
for attempt in range(cfg.max_retries + 1):
    try:
        result = subprocess.run(
            [cfg.cli_command, "-p", prompt, "--output-format", cfg.output_format],
            capture_output=True, text=True, timeout=cfg.timeout_seconds,
        )
        if result.returncode == 0:
            return parse_claude_output(result.stdout)
        # transient failure: retry
    except subprocess.TimeoutExpired:
        log.warning("claude -p timed out (attempt %d)", attempt + 1)
return []
```

## Testing without live Claude

Mock `subprocess.run` in tests — do NOT call the real CLI:

```python
from unittest.mock import patch, MagicMock

def test_parse_valid_output():
    raw = json.dumps({
        "type": "result",
        "result": json.dumps([{
            "candidate_id": "test-001",
            "priority": 1,
            "recommendation": "sell",
            "why_attractive": "high IV rank",
            "risks": "assignment if drops",
            "tradeoffs": "caps upside",
            "assignment_considerations": "low probability"
        }])
    })
    reviews = parse_claude_output(raw)
    assert len(reviews) == 1
    assert reviews[0].recommendation == "sell"
```

Minimum coverage:
- `parse_claude_output` with valid envelope → `list[ClaudeReview]`
- `parse_claude_output` with markdown-fenced inner JSON → parses correctly
- `parse_claude_output` with malformed outer JSON → returns `[]`
- `parse_claude_output` with valid envelope but invalid inner schema → returns `[]`
- `review_candidates` with mocked subprocess returning valid output → `list[ClaudeReview]`
- `review_candidates` with subprocess timeout → returns `[]`
- `review_candidates` with non-zero returncode → returns `[]`
- `review_candidates` when `cfg.claude.enabled = False` → returns `[]` without calling subprocess
- `build_prompt` includes candidate IDs, symbols, and key economics in the output string
- Empty candidate list → `[]` without subprocess call

## Quick verification when ready

```bash
source .venv/bin/activate
python -c "
from src.claude.parser import parse_claude_output
import json
raw = json.dumps({'type': 'result', 'result': json.dumps([{
    'candidate_id': 'x', 'priority': 1, 'recommendation': 'sell',
    'why_attractive': 'a', 'risks': 'b', 'tradeoffs': 'c',
    'assignment_considerations': 'd'
}])})
reviews = parse_claude_output(raw)
print(reviews)
"
python -m pytest -q && ruff check . && mypy src
```

## Open decisions

- **Prompt in one call vs. per-candidate**: send all approved candidates in one Claude call (cheaper, single context) vs. one call per candidate (more focused, easier to attribute cost). Recommend **single call** for Phase 5 — simpler, cheaper.
- **Streaming vs. blocking**: `claude -p` can stream (`--output-format stream-json`). Blocking is simpler for v1; streaming adds complexity for marginal UX gain in a cron job.
- **`.mcp.json` now or Phase 8**: creating it now lets the headless Claude use `trading_skills` for richer roll reasoning; skipping it now is fine if you want the minimal Phase 5.
- **Prompt templates as `.txt` files vs. Python strings**: Python strings avoid a file-load dependency and are easier to test. Stick with Python.
- **Cost logging**: `total_cost_usd` is in the Claude envelope — consider persisting it to a `claude_calls` SQLite table for monitoring. Optional for Phase 5.
