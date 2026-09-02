# Milestone 7 — AI Summary

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A pluggable AI backend writes narrative over the numbers the deterministic layer
already computed, and influences nothing.

**Spec:** `Web plan/P0-P1-design.md` §7. **Depends on:** Milestone 6.

**The fence governs this entire milestone.** The summary is enrichment: it may read everything
and change nothing. Task 7.5 proves it structurally.

---

## Task 7.1 — Provider protocol and context builder `[SONNET]`

Sonnet: fence-critical, and the context builder is what makes "the model never computes a
number" true rather than aspirational.

**Files:** Create `src/research/summary/protocol.py`, `src/research/summary/context.py`,
`src/research/summary/factory.py`. Test `tests/test_summary_context.py`.

**Interfaces:**
- Produces:
  - `Summary` (Pydantic): `thesis: str`, `bull_points: list[str]`, `bear_points: list[str]`,
    `watch_items: list[str]`, `caveats: list[str]`, `model: str`, `data_as_of: datetime`
  - `SummaryProvider` Protocol: `generate(context: ResearchContext) -> Summary | None`
  - `ResearchContext` (Pydantic): the fully-computed inputs, nothing else
  - `build_context(symbol: str, analysis: AnalysisResponse) -> ResearchContext`
  - `get_summary_provider() -> SummaryProvider` reading `research.summary.backend`

- [ ] **Step 1: Write the failing test**

```python
"""The context carries computed values only, and never asks the model to calculate."""

from __future__ import annotations

from src.research.summary.context import build_context


def test_context_carries_check_results_with_their_actuals(sample_analysis) -> None:
    ctx = build_context("AAPL", sample_analysis)
    health = next(c for c in ctx.checks if c.id == "health.current_ratio")
    assert health.actual is not None
    assert health.threshold is not None
    assert health.statement


def test_context_carries_only_computed_numbers(sample_analysis) -> None:
    """Every numeric field must already be a number. Nothing is left for the model to derive."""
    ctx = build_context("AAPL", sample_analysis)
    for value in ctx.key_metrics.values():
        assert value is None or isinstance(value, int | float)


def test_context_marks_unknown_checks_explicitly(sample_analysis_with_gaps) -> None:
    """The model must be told what we do not know, or it will fill the gap itself."""
    ctx = build_context("AAPL", sample_analysis_with_gaps)
    assert any(c.state == "UNKNOWN" for c in ctx.checks)


def test_context_includes_the_quantitative_caveat(sample_analysis) -> None:
    ctx = build_context("AAPL", sample_analysis)
    joined = " ".join(ctx.caveats).lower()
    assert "one-time" in joined or "restatement" in joined


def test_context_excludes_anything_the_model_could_treat_as_an_instruction(
    sample_analysis_with_news,
) -> None:
    """News headlines are third-party text. They are data, never instructions."""
    ctx = build_context("AAPL", sample_analysis_with_news)
    assert ctx.headlines
    assert all(isinstance(h, str) for h in ctx.headlines)
```

- [ ] **Step 2: Implement.** `ResearchContext` fields: `symbol`, `name`, `is_etf`,
  `key_metrics: dict[str, float | None]`, `checks: list[CheckResult]`,
  `category_scores: list[CategoryScore]`, `technicals`, `sentiment`, `headlines: list[str]`,
  `warnings`, `caveats: list[str]`, `data_as_of`.

  `caveats` always includes the quantitative limit carried forward from the Simply Wall St
  finding: this analysis is entirely quantitative and cannot account for one-time charges,
  mergers, spinoffs, or accounting restatements.

- [ ] **Step 3: Run tests, commit.**

---

## Task 7.2 — The `claude_cli` backend `[SONNET]`

Sonnet: touches `src/claude/`, and the prompt contract is what keeps the model from inventing
numbers.

**Files:** Create `src/research/summary/claude_cli.py`, `src/research/summary/prompt.py`.
Test `tests/test_summary_claude_cli.py`.

**Interfaces:**
- Consumes: `src/claude/runner.py`'s CLI invocation pattern (`claude -p ... --output-format json`).
- Produces: `ClaudeCliSummaryProvider.generate(context) -> Summary | None`,
  `build_prompt(context: ResearchContext) -> str`,
  `parse_summary(raw: str, *, model: str, data_as_of: datetime) -> Summary | None`

**Prompt contract**, and every clause is load-bearing:
1. The model receives the context as JSON and writes narrative only.
2. **Every number it uses must appear in the context.** It never calculates, estimates, or
   recalls a figure from training.
3. It must not recommend a trade, a position size, or an entry price. That is the engine's job
   and the model has no path to it.
4. `UNKNOWN` checks are stated as unknown, never guessed.
5. Output is strict JSON matching `Summary`.

- [ ] **Step 1: Write the failing test**

```python
"""The CLI backend parses strictly and fails soft."""

from __future__ import annotations

from datetime import UTC, datetime

from src.research.summary.claude_cli import parse_summary
from src.research.summary.prompt import build_prompt

NOW = datetime.now(UTC)


def test_parses_a_well_formed_response() -> None:
    raw = """{"thesis": "Steady compounder with rich options premium.",
              "bull_points": ["ROE above 15%"], "bear_points": ["P/E above the market"],
              "watch_items": ["Earnings on 30 Oct"], "caveats": ["Quantitative only"]}"""
    s = parse_summary(raw, model="claude-sonnet-4-6", data_as_of=NOW)
    assert s is not None
    assert s.thesis.startswith("Steady")
    assert s.bull_points == ["ROE above 15%"]


def test_parses_json_wrapped_in_prose() -> None:
    raw = 'Here is the summary:\n```json\n{"thesis": "x", "bull_points": [], ' \
          '"bear_points": [], "watch_items": [], "caveats": []}\n```'
    assert parse_summary(raw, model="m", data_as_of=NOW) is not None


def test_unparseable_output_returns_none_rather_than_raising() -> None:
    """A bad parse renders the page without a summary. Enrichment, never a dependency."""
    assert parse_summary("I could not do that.", model="m", data_as_of=NOW) is None


def test_a_missing_required_field_returns_none() -> None:
    assert parse_summary('{"thesis": "x"}', model="m", data_as_of=NOW) is None


def test_prompt_forbids_calculation(sample_context) -> None:
    p = build_prompt(sample_context).lower()
    assert "must appear in the context" in p or "never calculate" in p


def test_prompt_forbids_trade_recommendations(sample_context) -> None:
    p = build_prompt(sample_context).lower()
    assert "not recommend" in p or "never recommend" in p


def test_prompt_states_unknowns_explicitly(sample_context_with_unknowns) -> None:
    assert "UNKNOWN" in build_prompt(sample_context_with_unknowns)
```

- [ ] **Step 2: Implement.** Reuse `src/claude/runner.py`'s subprocess and timeout handling
  rather than writing a second CLI invoker. Read that module first and match its error
  handling, its `--output-format json` parsing, and its cost logging.

- [ ] **Step 3: Run tests, commit.**

---

## Task 7.3 — The `anthropic`, `openai`, and `ollama` backends `[GLM]`

**Files:** Create `src/research/summary/anthropic.py`, `openai.py`, `ollama.py`. Test each.

The pattern is fixed by Task 7.2: build the same prompt, call the backend, parse with the same
`parse_summary`. Only transport differs.

Required behaviours, each with a test per backend:
- A missing API key returns `None` and logs once, rather than raising.
- A timeout returns `None`.
- A malformed response returns `None`.
- The parsed `Summary` is identical across backends for identical model output, proving the
  prompt and parser are genuinely shared.
- `ollama` reuses `src/claude/ollama_runner.py`'s host and timeout config rather than a second
  copy.

New secrets in `.env.example`: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`. Add both to `Secrets` in
`src/common/config.py`.

- [ ] Write the tests, implement, run, update `SETUP.md`, commit.

---

## Task 7.4 — Caching and the on-demand trigger `[GLM]`

**Files:** Create `src/research/summary/service.py`. Modify `src/api/routers/research.py`.
Test `tests/test_summary_service.py`.

**Interfaces:**
- Produces:
  - `summary_for(symbol: str, analysis, *, force: bool = False) -> Summary | None`
  - `GET /research/{symbol}/summary` → `{as_of, summary: Section[Summary]}`
  - `POST /research/{symbol}/summary` → generates on demand

**The on-demand rule from the spec:** a summary is generated on explicit request or for
watchlisted names, **never automatically for every cold-tier search**. A first-time search on an
obscure ticker must not silently trigger a model call.

Required behaviours, each with a test:
- `GET` on a symbol with no cached summary returns `Section` state `unavailable` with a reason,
  and **makes no model call**. A test asserts the provider was not invoked.
- `POST` generates and caches.
- The cache key is `(symbol, model, prompt_hash, data_as_of)`. A changed `data_as_of` misses.
- A cached summary older than `research.summary.cache_ttl_hours` is regenerated.
- A watchlisted symbol is eligible for background generation; a cold one is not.

- [ ] Write the tests, implement, run, update `docs/web/api.md`, commit.

---

## Task 7.5 — Extend the fence `[SONNET]`

Sonnet: enforces a `CLAUDE.md` invariant.

**Files:** Modify `tests/test_web_fence.py`.

- [ ] **Step 1: Add these tests**

```python
def test_the_checks_engine_never_imports_the_summary_layer() -> None:
    """Already covered in Milestone 1, but the summary package now has real content."""
    offenders = [
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "src" / "research" / "checks").glob("*.py"))
        if "summary" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"summary reachable from checks: {offenders}"


def test_the_summary_layer_never_writes_to_any_database_but_its_own() -> None:
    """The summary is enrichment. It records itself and touches nothing else."""
    forbidden = ("src.storage", "trading_db", "risk_limits", "scoring_weights")
    offenders = [
        str(p.relative_to(ROOT))
        for p in sorted((ROOT / "src" / "research" / "summary").rglob("*.py"))
        if any(token in p.read_text(encoding="utf-8") for token in forbidden)
    ]
    assert not offenders, f"summary layer reached beyond its bounds: {offenders}"


def test_no_summary_output_reaches_a_scoring_or_sizing_path() -> None:
    offenders = [
        rel
        for rel in _modules_under("engine", "execution", "strategies")
        if "summary" in (ROOT / rel).read_text(encoding="utf-8").lower()
    ]
    assert not offenders, f"summary reachable from the engine path: {offenders}"


def test_the_recommendations_route_does_not_rescore() -> None:
    """The site and Telegram must never disagree about what the system thinks."""
    text = (ROOT / "src" / "api" / "routers" / "research.py").read_text(encoding="utf-8")
    assert "generate_buy_candidates" not in text
    assert "blended_score" not in text or "=" not in text.split("blended_score")[1][:3]
```

- [ ] **Step 2: Run the whole suite.** If any fails, the violation is real; fix the code, never
  the test.

- [ ] **Step 3: Commit.**

---

## Task 7.6 — Summary panel `[GLM]`

**Files:** Create `web/components/stock/SummaryPanel.tsx`. Modify the ticker page.
Test `web/components/stock/SummaryPanel.test.tsx`.

Required behaviours, each with a test:
- With no cached summary, the panel shows one line of text and a **Generate summary** button.
  No decorative icon circle above a heading; that template is banned.
- While generating, the button is disabled and shows a loading state.
- A rendered summary shows thesis, bulls, bears, watch items, and caveats as distinct labelled
  regions, not one prose blob.
- The panel carries an attribution line naming the model and the data `as_of` it saw, so a
  stale summary is visibly stale.
- The caveats region is always rendered when present, never collapsed by default. The
  quantitative limit is the thing most likely to be papered over by fluent prose, so it stays
  visible.
- A failed generation shows the reason and leaves the rest of the page untouched.

- [ ] Write the tests, implement, run `npx vitest run && npm run build && npm run lint`, commit.

---

## Task 7.7 — Close out P1 `[GLM]`

- [ ] Update `STATUS.md`: P0 and P1 built, with the milestone list. P2 (options console),
      P3 (portfolio), P4 (profitability tracker) and P5 (mobile) deliberately not built, with
      `Web plan/OVERVIEW.md` named as the roadmap.
- [ ] Update `README.md`: the web layer in the layout table, and a short "Running the web app"
      section pointing at `SETUP.md`.
- [ ] Update `SETUP.md`: full walkthrough covering `pip install -e ".[web,dev]"`, the three
      new `.env` keys, `python -m scripts.run_api`, `python -m scripts.run_research_worker`,
      `cd web && npm install && npm run dev`, and a troubleshooting row for each of: SEC 403
      (missing `SEC_CONTACT_EMAIL`), 401 from the API (missing `WEB_API_TOKEN`), and an empty
      search (worker has not run).
- [ ] Regenerate `docs/web/openapi.json` and `web/lib/api-types.ts`.
- [ ] Run the complete gate one final time:
      `python -m pytest -q && ruff check . && mypy src && cd web && npx vitest run && npm run build && npm run lint`
- [ ] Commit.

---

## Milestone 7 exit criteria

- [ ] Full Python and web gates green
- [ ] All four summary backends selectable by config; each fails soft to a page with no summary
- [ ] A cold-tier search triggers no model call
- [ ] The fence tests pass with real content on both sides
- [ ] Every doc obligation in `IMPLEMENTATION-PLAN.md` discharged

---

## After P1

**The cutover.** Run the site alongside `format_buy_list` for two weeks. When the web
recommendations are trusted, removing the Telegram buy-list is a separate one-task change that
also updates the Telegram command tables in `README.md`, `SETUP.md` and `ARCHITECTURE.md`.

**Then P2.** The options console is the next phase and needs its own spec, because it touches
the execution path. Its foundation already exists in
`docs/superpowers/specs/2026-08-10-remediation-and-ios-app-design.md` §9.3: the `app_commands`
intent queue, drained by `approval_service`, performing exactly the `ApprovalRow` mutation
`_process_button` performs today. **The web layer creates intent. It never creates orders.**
