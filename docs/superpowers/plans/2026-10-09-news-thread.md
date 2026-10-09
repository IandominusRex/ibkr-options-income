# News Thread Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A news service that posts succinct, number-grounded macro / market / ticker news with implications (playbook prior, measured reaction, LLM read, book impact) to Telegram thread 4409, answers `/news TICKER`, and backs a web `/news` page — without any LLM output reaching ranking, gating, or sizing.

**Architecture:** A new supervised process (`scripts/run_news.py`) owns `src/news/` and its own SQLite file `data/news.db` (own `NewsBase`, written only by `src/news/`). Sources live behind `src/data/` protocols (RSS, Google News, yfinance, Finnhub, ForexFactory schedule, Nasdaq actuals/earnings, yfinance intraday). Deterministic code builds a numbered fact sheet, a playbook prior and a measured reaction; the LLM (`claude -p` → Ollama → deterministic floor) only writes the explanation, which is grounding-checked before posting. `approval_service` and the web reach the news process only by inserting a `news_requests` row (`/news` command, `news_brief` drain kind); the API reads `news.db` read-only.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Pydantic 2, httpx, python-telegram-bot 22.7, yfinance, matplotlib (new), vaderSentiment (existing extra), optional transformers/torch (FinBERT extra), FastAPI, Next.js App Router + TypeScript + Tailwind v4 + react-query + vitest.

**Spec:** `docs/superpowers/specs/2026-10-09-news-thread-design.md` (read it first — every section number below refers to it).

## Progress log

| Task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| 1 Config + secrets | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | Added `config/news.yaml` to `.gitignore` (plan omitted it; `test_private_config_files_are_gitignored` requires it). Docs (ARCHITECTURE/SETUP) deferred to Task 34 per plan. |
| 2 News store | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | Dropped an unused `# type: ignore[no-untyped-def]` in `session.py` (mypy `unused-ignore`). |
| 3 Text utils + tagging | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | none |
| 4 Ingest + clustering | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | Test fixture headline reworded: the plan's pair ("shares fall after new" / "stock falls on fresh") scores Jaccard 0.44 < the spec's 0.5 default, so it never clustered. Spec default and `text.py` untouched. |
| 5 Data protocols + RSS | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | Renamed RSS-branch local `link`→`href` (mypy reused-variable type clash with the Atom branch). `NewsItem` summary/image_url already existed. |
| 6 Finnhub backend | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | `_get(**params: Any)` instead of `object` (mypy vs httpx `QueryParamTypes`). |
| 7 Econ schedule + actuals + probe script | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | none (`news_probe.main()` imports `src.news.playbook`, which lands in Task 10; only `infer_offset` is tested here, as the brief states). |
| 8 Earnings sources + merge | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | none (`EarningsEventRow` constructed with explicit defaults, per the brief's note). |
| 9 Intraday provider + tape | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | none |
| 10 Playbook | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | `parse_value` multiplies via `Decimal` instead of float: the plan's `float(t) * 1e9` gives 8279999999.999999 for `8.28B`, failing its own pinned test. |
| 11 Aliases + views + collectors | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | Test fixture forecast `200K`→`210K`: the plan's 197K vs 200K is a 3K beat, inside the committed playbook's 8K `jobless_claims` tolerance, so it is correctly `inline`, never `hot`. Playbook untouched. |
| 12 Service skeleton + entrypoint + fence | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | (a) `test_only_src_news_constructs_news_rows` only scans files importing `src.news`: `src/research/store/models.py` has its own unrelated `NewsItemRow` (research.db), which the plan's plain-string check flagged. (b) Spreads enumerations found: `scripts/start.py` `--no-spreads` (added `--no-news` + docstring line + `test_news_service_is_supervised_and_can_be_skipped`) and `ibkr logs` usage (added `news`); `scripts/launchd.py` enumerates none. (c) Step 5 networked smoke run not done: deferred to Task 34 live verification (it writes the operator's real `data/news.db`). |
| 13 Fact sheet + flags | done | (see git log) | pytest/ruff/mypy green | 2026-10-09 | (a) `post_earnings_moves` measures a **1-day** move (spec §6.1): the larger of pre-report→report-day and report-day→next close, since report dates carry no BMO/AMC timing. The plan's two-session window gave −9.0% against its own pinned −9.9%. Added `test_post_earnings_moves_before_open_report`. (b) `Analytics.live().daily` no longer does `_safe(...) or pd.DataFrame()`, which raises on any non-empty frame. Added `test_live_daily_returns_a_non_empty_frame`. (c) `_safe` made generic (`_safe[T]`) and the `type: ignore`s dropped, earnings ratio local renamed `r`→`ratio_f` (mypy: clashed with the float `r`), `import re` merged into the schemas import block. |
| 14 Reaction | done | (see git log) | pytest/ruff/mypy green (3057 passed) | 2026-10-09 | none |
| 15 Card schemas + render | done | (see git log) | pytest/ruff/mypy green (3064 passed) | 2026-10-09 | `fmt_when` treats a naive datetime as UTC: the plan's bare `astimezone()` reads naive as host-local, and the store keeps naive-UTC, so a card built from a DB row would show a wrong SGT/ET time. Added `test_naive_when_is_read_as_utc_not_local`. Local `l`→`lk` (ruff E741). |
| 16 Charts | done | (see git log) | pytest/ruff/mypy green (3066 passed) | 2026-10-09 | none (probed a tz-aware daily index and a NaN close: both render) |
| 17 Publisher + quiet hours | done | (see git log) | pytest/ruff/mypy green (3077 passed) | 2026-10-09 | `send` builds its retry op with `functools.partial` instead of the plan's default-arg lambda (mypy: cannot infer lambda type; same loop-variable binding). Added tests the brief did not name: `from_config` (unset secrets, and that the conftest guard really swaps `Bot`) and `send_photo`; both mutation-checked. |
| 18 Triggers + alert gate | done | (see git log) | pytest/ruff/mypy green (3086 passed) | 2026-10-09 | none to the plan code. Added two gate tests the brief did not name, both mutation-checked: `mark` is idempotent on the unique key, and a candidate dropped by the hourly cap is not recorded as fired (so it can retry once the window empties). |
| 19 Alert assembly | pending | | | | |
| 20 Digests | done | (see git log) | pytest/ruff/mypy green (3094 passed) | 2026-10-09 | (a) Task 19 was skipped by request, but `digests.py` imports `src.news.links.links_for`: pulled forward ONLY `src/news/links.py` (`pick_primary`, `links_for`, verbatim from Task 19) + `tests/test_news_links.py`; `alerts.py`/`AlertContext`/`plan_alert` remain Task 19's, which must not recreate `links.py` (it re-exports from it). (b) `due_digests` typed with a `tuple[tuple[DigestName, str], ...]` and `_KIND`/`_TITLE` typed `dict[DigestName, ...]` instead of the plan's `type: ignore`s; `gather_inputs(an: Analytics)` per the Interfaces block (plan code said `object`). (c) Added `test_gather_inputs_reads_store_and_picks_tape_by_digest` (brief named no gather_inputs test), mutation-checked: swapped rth/ext tape sets, dropped the lone-ticker filter, and 72 h→16 h each fail it. |
| 21 Service: deterministic posting loops | pending | | | | |
| 22 LLM transport | done | (see git log) | pytest/ruff/mypy green (3103 passed) | 2026-10-09 | none to the plan code (only `ruff format`). Added 6 tests the brief did not name, each mutation-checked: a raising backend is swallowed, counted and falls through; `ollama` backend never runs the CLI; all backends failing returns `None` yet still counts both attempts; the cap stops the second backend inside one call; the cap key is the ET date (22:00 ET on the 14th is 02:00 UTC on the 15th); and the real `_ollama` passes the model override, schema and timeout through to `_generate` (falling back to `claude.ollama_model`). Docs (ARCHITECTURE/SETUP) stay deferred to Task 34 per the plan. |
| 23 Prompts + explain + grounding | pending | | | | |
| 24 Two-stage edit + digest editor wiring | pending | | | | |
| 25 sentiment.py reads the store | pending | | | | |
| 26 news_context.py reads the store | pending | | | | |
| 27 FinBERT option | pending | | | | |
| 28 Brief queue + builder | pending | | | | |
| 29 `/news` Telegram command | pending | | | | |
| 30 `news_brief` command kind | pending | | | | |
| 31 Read-only `/news/*` API | pending | | | | |
| 32 Web `/news` pages | pending | | | | |
| 33 Watchdog check | pending | | | | |
| 34 Docs + final gate + live verification | pending | | | | |

Update this table after every task (status, commit SHAs, gate result, date, every deviation from the task text and why) and commit it with the task (CLAUDE.md "Change workflow" rule 4).

## Global Constraints

- Python ≥ 3.12; type-hint everything; `ruff check .`, `mypy src`, `python -m pytest -q` all green after every task.
- Tests are offline: no network, no TWS, no Telegram, no LLM. Every source is exercised through saved fixtures or fakes.
- `config/news.yaml` is a **private, git-ignored** operator file; the repo commits `config/news.example.yaml`. `config/news_playbook.yaml` is committed reference data (not private). Never `git add` `config/news.yaml` or `.env`.
- Secrets only in `.env`: `TELEGRAM_THREAD_NEWS=4409`, `FINNHUB_API_KEY` (already set on the operator's machine 2026-10-09). Never log or echo the Finnhub key; the backend passes it as the `token` query parameter and redacts it from every log line.
- `data/news.db` is written **only** by modules under `src/news/` (spec §10.3).
- `src/engine/`, `src/execution/`, `src/strategies/`, `src/spreads/` never import `src.news` (spec §10.1). `src/news/` never imports `src.engine`, `src.execution`, `src.strategies`, `src.spreads`, `src.orchestrator`, `src.notify.approval_service` (spec §10.2).
- The only `src.news` module `src/notify/` may import is `src.news.briefs` (spec §10.7). `src/api/` never imports `src.news.store.session` (spec §10.6).
- No LLM output reaches `ScoreCard.sentiment_score`, the risk engine, or sizing (spec D3). `sentiment.py` reads only `news_items.det_sentiment/published_at/fetched_at/tickers/cluster_id/title`.
- LLM backend config: `news.llm.backend` ∈ `cli | ollama | cli_then_ollama`, ships `cli_then_ollama`; `news.llm.model` ships `"claude-sonnet-5-5"`; `news.llm.max_calls_per_day` ships `40`.
- Telegram: thread from `TELEGRAM_THREAD_NEWS`; HTML parse mode; every dynamic string HTML-escaped; messages ≤ 4096 chars (split at section boundaries); quiet hours `00:00–07:00 Asia/Singapore` post with `disable_notification=True`, critical alerts notify.
- Time zones via `zoneinfo` only (`America/New_York`, `Asia/Singapore`); never a fixed UTC offset. Store naive-UTC datetimes in SQLite (the `src/spreads/store.py` convention) and convert at the edges.
- Web (`web/CLAUDE.md`): dark semantic tokens only, IBM Plex Mono + `.tabular` for numbers, state never colour-only, **no em dashes in UI copy**, banned words "seamless", "robust", "unlock", "elevate".
- New dependency: `matplotlib>=3.8` (core). Optional extra `finbert = ["transformers>=4.40", "torch>=2.2"]`. `vaderSentiment` stays in the existing `sentiment` extra.

## Review Focus

1. **Daylight-saving transitions** (US DST ends 2026-11-01): digest times are ET wall-clock and quiet hours are SGT wall-clock; the ET↔SGT gap changes from 12 h to 13 h. Expected: an 08:00 ET digest fires at 08:00 ET on both 2026-10-30 and 2026-11-02, and quiet hours stay 00:00–07:00 SGT. Pinned in Task 17 (`test_quiet_hours_across_us_dst_end`) and Task 20 (`test_premarket_due_across_dst_end`).
2. **Untrusted text in HTML**: headlines, sources, and LLM fields containing `<`, `>`, `&`, or a stray `<b>` must never break Telegram's HTML parser or inject markup. Expected: escaped verbatim. Pinned in Task 15 (`test_every_dynamic_field_is_escaped`).
3. **Nasdaq rows that are not data**: `actual` of `"&nbsp;"`, `" "`, `""`, times like `"All Day"`/`"Tentative"`, and the D+1 date key. Expected: such rows parse to `actual=None` / are skipped, never crash or alert. Pinned in Task 7 (`test_nasdaq_non_values_and_untimed_rows`).
4. **One story, two triggers**: a geopolitical cluster that also drives an index-level crossing must not post twice. Expected: the second trigger edits the first card's tail (`🔄 Update`), not a new post. Pinned in Task 19 (`test_cluster_already_posted_becomes_update`).
5. **`news.db` absent or locked** (fresh install, news service not yet started) when the API, `sentiment.py`, `news_context.py` or the watchdog read it. Expected: empty/`available: false` results and fallback behaviour, never a 500 or a scan failure. Pinned in Task 25 (`test_store_missing_falls_back_to_yfinance`), Task 31 (`test_news_routes_when_db_missing`), Task 33 (`test_news_check_when_db_missing`).

## File Map

| Path | Responsibility | Task |
|---|---|---|
| `src/common/config.py` | `NewsCfg` tree, `Config.news`, `news_db_url_abs()`, 4 new `DataCfg` keys, 2 new `Secrets` | 1 |
| `config/news.example.yaml` | committed defaults for every `news.*` key | 1 |
| `config/news_playbook.yaml` | committed 📘 playbook | 10 |
| `src/news/__init__.py` | package docstring (fence statement) | 2 |
| `src/news/store/models.py` | `NewsBase` + 10 row classes | 2 |
| `src/news/store/session.py` | read-write engine/session/init (news process only) | 2 |
| `src/news/store/readonly.py` | read-only engine for `sentiment.py`, `news_context.py`, watchdog | 2 |
| `src/news/store/state.py` | key/value state: heartbeat, LLM counter, per-source last-ok | 2 |
| `src/news/store/queries.py` | Session-parameterised read helpers (shared with the API) | 2, 11, 25, 26, 31 |
| `src/news/store/prune.py` | retention pruning | 21 |
| `src/news/text.py` | URL canonicalisation, hashes, title normalisation, tokens, Jaccard | 3 |
| `src/news/tagging.py` | ticker / event / topic tags, deterministic sentiment | 3, 27 |
| `src/news/ingest.py` | dedupe + cluster + persist | 4 |
| `src/data/protocols.py` | `NewsItem` (+summary, image_url) and new schemas/protocols | 5 |
| `src/data/rss_backend.py` | conditional-GET RSS/Atom fetch | 5 |
| `src/data/finnhub_backend.py` | Finnhub client (company/general news, earnings) | 6 |
| `src/data/forexfactory_backend.py` | weekly econ schedule | 7 |
| `src/data/nasdaq_backend.py` | econ actuals (D+1 rule) + earnings timing | 7, 8 |
| `src/data/yfinance_backend.py` | `YFinanceIntradayProvider`, `YFinanceEarningsHistory` | 8, 9 |
| `src/data/factory.py` | 5 new accessors | 5–9 |
| `scripts/news_probe.py` | live probe of every news source | 7 |
| `src/news/tape.py` | quotes, day change, prev close | 9 |
| `src/news/aliases.py` | ticker → company-name aliases (cached) | 11 |
| `src/news/collectors.py` | poll each source into the store | 11 |
| `src/news/earnings.py` | merge earnings sources, detect releases | 8 |
| `src/news/service.py` | asyncio loops | 12, 21, 24, 28 |
| `scripts/run_news.py` | entrypoint | 12 |
| `scripts/start.py` | `news` service entry | 12 |
| `src/news/facts.py` | fact sheet + flags | 13 |
| `src/news/playbook.py` | playbook loader, value parser, surprise, prior | 10 |
| `src/news/reaction.py` | measured post-release reaction | 14 |
| `src/news/schemas.py` | views, `Fact`, `FactSheet`, `Explanation`, `CardPayload`, … | 11, 13, 15, 23 |
| `src/news/render.py` | Telegram HTML for cards and digests | 15 |
| `src/news/charts.py` | matplotlib PNG | 16 |
| `src/news/publish.py` | Telegram Bot wrapper | 17 |
| `src/news/quiet.py` | quiet-hours rule | 17 |
| `src/news/triggers.py` | pure alert detectors + `AlertGate` | 18 |
| `src/news/links.py` | primary source + inline links (dependency-free; API-safe) | 19 |
| `src/news/alerts.py` | candidate → `CardPayload` (+ update-vs-new) | 19, 28 |
| `src/news/posting.py` | persist + publish + chart a card; edit a post | 21 |
| `src/news/followup.py` | stage 2: reaction + 🧠 edit | 24 |
| `src/news/digests.py` | due-time logic + digest payloads | 20 |
| `src/news/llm.py` | backend chain + daily cap | 22 |
| `src/news/prompts.py` | editor / writer prompts + JSON schemas | 23 |
| `src/news/grounding.py` | evidence + numeric grounding | 23 |
| `src/news/explain.py` | editor + writer passes with retry and fallback | 23 |
| `src/analytics/sentiment.py` | store-backed `_fetch_news` | 25 |
| `src/claude/news_context.py` | store-first NEWS block | 26 |
| `src/news/briefs.py` | request queue (the only module `approval_service` imports) | 28 |
| `src/news/brief_builder.py` | builds and posts a ticker brief | 28 |
| `src/notify/approval_service.py`, `src/notify/formatters.py` | `/news` command + help line | 29 |
| `src/api/models/commands.py`, `src/notify/command_drain.py` | `news_brief` kind | 30 |
| `src/api/news_db.py`, `src/api/models/news.py`, `src/api/routers/news.py`, `src/api/main.py`, `src/api/routers/meta.py` | read-only news API + nav | 31 |
| `web/app/news/**`, `web/components/news/**`, `web/components/shell/RailSection.tsx` | web pages | 32 |
| `src/ops/watchdog.py`, `src/common/config.py` (`WatchdogCfg`) | news staleness check | 33 |
| `tests/test_news_*.py`, `tests/fixtures/news/*` | tests + fixtures | every task |
| `ARCHITECTURE.md`, `SETUP.md`, `STATUS.md`, `README.md`, `CLAUDE.md`, `docs/web/commands.md`, `docs/web/api.md`, `.env.example`, `pyproject.toml` | docs | 1, 34 |

## Conventions used by every task

- Test command prefix: `.venv/bin/python -m pytest` (the repo venv). If working in a worktree, symlink the main `.venv` first (see the "Fresh worktree setup" memory).
- The shared fixture added in Task 2, `news_db`, points `src.news.store.session` and `src.news.store.readonly` at a tmp file and creates the schema. Every later test that touches the store uses it.
- Commit messages: `feat(news): …`, `test(news): …`, `docs(news): …`, ending with the `Co-Authored-By` trailer from the session's attribution reminder.

---

## Milestone 1 — Store fills (spec §5)

### Task 1: Config, secrets, example YAML

**Files:**
- Modify: `src/common/config.py` (add classes before `class Config`; extend `Secrets`, `DataCfg`, `PRIVATE_CONFIG_FILES`, `Config`, `get_config`)
- Create: `config/news.example.yaml`
- Modify: `.env.example`, `pyproject.toml`
- Test: `tests/test_news_config.py`

**Interfaces:**
- Produces: `get_config().news: NewsCfg` with the sub-models below; `Config.news_db_url_abs() -> str`; `Secrets.telegram_thread_news: str`, `Secrets.finnhub_api_key: str`; `DataCfg.econ_schedule_provider = "forexfactory"`, `econ_actuals_provider = "nasdaq"`, `earnings_calendar_provider = "nasdaq"`, `intraday_price_provider = "yfinance"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_news_config.py
"""config/news.example.yaml loads into NewsCfg and its validators bite."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.common.config import NewsCfg, NewsDigestCfg, NewsQuietCfg, get_config


def test_example_config_loads_with_spec_defaults() -> None:
    cfg = get_config().news
    assert cfg.enabled is True
    assert cfg.llm.backend == "cli_then_ollama"
    assert cfg.llm.model == "claude-sonnet-5-5"
    assert cfg.llm.max_calls_per_day == 40
    assert cfg.quiet_hours.tz == "Asia/Singapore"
    assert (cfg.quiet_hours.start, cfg.quiet_hours.end) == ("00:00", "07:00")
    assert cfg.digests.premarket == "08:00" and cfg.digests.close == "16:30"
    assert cfg.alerts.held_sigma == 2.0 and cfg.alerts.universe_sigma == 3.0
    assert cfg.reaction.window_min == 15 and cfg.reaction.max_wait_min == 35
    assert cfg.sentiment.model == "vader"
    assert any(f.category == "government" for f in cfg.sources.rss_feeds)
    assert get_config().news_db_url_abs().endswith("data/news.db")


def test_bad_time_and_tz_are_refused() -> None:
    with pytest.raises(ValidationError):
        NewsDigestCfg(premarket="8:00")
    with pytest.raises(ValidationError):
        NewsQuietCfg(tz="Mars/Olympus")


def test_unknown_llm_backend_is_refused() -> None:
    with pytest.raises(ValidationError):
        NewsCfg.model_validate({"llm": {"backend": "gpt"}})


def test_new_secrets_and_data_keys_have_defaults() -> None:
    cfg = get_config()
    assert isinstance(cfg.secrets.telegram_thread_news, str)
    assert isinstance(cfg.secrets.finnhub_api_key, str)
    assert cfg.data.econ_schedule_provider == "forexfactory"
    assert cfg.data.econ_actuals_provider == "nasdaq"
    assert cfg.data.earnings_calendar_provider == "nasdaq"
    assert cfg.data.intraday_price_provider == "yfinance"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_news_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'NewsCfg'`.

- [ ] **Step 3: Implement**

In `src/common/config.py`:

1. Add `"news.yaml"` to `PRIVATE_CONFIG_FILES`.
2. In `Secrets`, after `telegram_thread_spreads`:

```python
    # News thread (docs/superpowers/specs/2026-10-09-news-thread-design.md).
    telegram_thread_news: str = Field(default="", alias="TELEGRAM_THREAD_NEWS")
    finnhub_api_key: str = Field(default="", alias="FINNHUB_API_KEY")
```

3. In `DataCfg`, after `bulk_price_provider`:

```python
    # News service sources (docs/superpowers/specs/2026-10-09-news-thread-design.md §5.1).
    econ_schedule_provider: str = "forexfactory"
    econ_actuals_provider: str = "nasdaq"
    earnings_calendar_provider: str = "nasdaq"
    intraday_price_provider: str = "yfinance"
```

4. Before `class Config`, add the news tree (reuse the module's existing `_hhmm` helper for HH:MM validation):

```python
NewsCategory = Literal["government", "geopolitics", "macro", "markets", "ticker"]


class NewsFeedCfg(BaseModel):
    name: str
    url: str
    category: NewsCategory


class NewsSourcesCfg(BaseModel):
    rss_feeds: list[NewsFeedCfg] = Field(default_factory=list)
    macro_queries: list[str] = Field(default_factory=list)
    google_news_days: int = 3
    rss_poll_minutes: int = 5
    macro_poll_minutes: int = 10
    ticker_round_robin_minutes: int = 30
    econ_poll_minutes: int = 60
    econ_fast_poll_seconds: int = 30
    econ_fast_window_before_min: int = 2
    econ_fast_window_after_min: int = 10
    earnings_poll_hours: int = 6
    finnhub_per_minute: int = 50


class NewsClusterCfg(BaseModel):
    similarity: float = 0.5
    window_hours: int = 48


class NewsTaggingCfg(BaseModel):
    rumor_terms: list[str] = Field(default_factory=list)
    forward_terms: list[str] = Field(default_factory=list)
    topic_terms: dict[str, list[str]] = Field(default_factory=dict)
    aliases: dict[str, list[str]] = Field(default_factory=dict)


class NewsAlertsCfg(BaseModel):
    index_symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "DIA"])
    index_levels_down: list[float] = Field(default_factory=lambda: [-1.0, -2.0, -3.0])
    index_levels_up: list[float] = Field(default_factory=lambda: [2.0, 3.0])
    critical_index_level: float = -2.0
    vix_jump_pct: float = 15.0
    vix_levels: list[float] = Field(default_factory=lambda: [25.0, 30.0])
    held_sigma: float = 2.0
    universe_sigma: float = 3.0
    ticker_scan_minutes: int = 5
    geo_min_sources: int = 2
    geo_reaction_pct: float = 0.5
    geo_reaction_window_min: int = 30
    geo_topics: list[str] = Field(
        default_factory=lambda: ["war", "ceasefire", "sanctions", "tariff", "fed", "fiscal", "energy"]
    )
    max_per_hour: int = 6
    max_edits: int = 3


class NewsReactionCfg(BaseModel):
    window_min: int = 15
    max_wait_min: int = 35
    instruments_rth: dict[str, str] = Field(
        default_factory=lambda: {
            "stocks": "SPY", "bonds": "^TNX", "dollar": "UUP",
            "gold": "GLD", "oil": "USO", "vol": "^VIX",
        }
    )
    instruments_ext: dict[str, str] = Field(
        default_factory=lambda: {
            "stocks": "ES=F", "bonds": "ZN=F", "dollar": "DX-Y.NYB",
            "gold": "GC=F", "oil": "CL=F",
        }
    )


class NewsQuietCfg(BaseModel):
    tz: str = "Asia/Singapore"
    start: str = "00:00"
    end: str = "07:00"
    critical_breaks_quiet: bool = True

    @field_validator("start", "end")
    @classmethod
    def _valid_hhmm(cls, v: str) -> str:
        return _hhmm(v)

    @field_validator("tz")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"news.quiet_hours.tz: unknown time zone {v!r}") from exc
        return v


class NewsDigestCfg(BaseModel):
    premarket: str = "08:00"
    close: str = "16:30"
    week_ahead_weekday: int = 6  # Monday=0 … Sunday=6
    week_ahead_time: str = "18:00"
    max_threads: int = 6
    max_movers: int = 5

    @field_validator("premarket", "close", "week_ahead_time")
    @classmethod
    def _valid_hhmm(cls, v: str) -> str:
        return _hhmm(v)


class NewsLlmCfg(BaseModel):
    backend: Literal["cli", "ollama", "cli_then_ollama"] = "cli_then_ollama"
    model: str = "claude-sonnet-5-5"
    ollama_model: str = ""  # empty = claude.ollama_model
    timeout_seconds: float = 120.0
    max_calls_per_day: int = 40


class NewsSentimentCfg(BaseModel):
    model: Literal["vader", "finbert"] = "vader"
    lookback_hours: int = 72
    half_life_hours: float = 24.0


class NewsGroundingCfg(BaseModel):
    rel_tol: float = 0.02


class NewsFlagsCfg(BaseModel):
    large_move_sigma: float = 2.0
    oversold_rsi: float = 30.0
    earnings_outsized: float = 1.5
    earnings_muted: float = 0.5
    sector_share: float = 1 / 3


class NewsBriefsCfg(BaseModel):
    poll_seconds: int = 5
    dedupe_minutes: int = 10


class NewsCfg(BaseModel):
    """News service (config/news.yaml). See docs/superpowers/specs/2026-10-09-news-thread-design.md."""

    enabled: bool = True
    db_url: str = "sqlite:///data/news.db"
    charts_dir: str = "data/news_charts"
    retention_days: int = 30
    lookback_hours: dict[str, int] = Field(
        default_factory=lambda: {
            "government": 168, "geopolitics": 168, "macro": 168, "markets": 36, "ticker": 72,
        }
    )
    source_rank: list[str] = Field(default_factory=list)
    tape_symbols_rth: list[str] = Field(
        default_factory=lambda: ["SPY", "QQQ", "DIA", "IWM", "^VIX", "^TNX", "UUP", "GLD", "USO"]
    )
    tape_symbols_ext: list[str] = Field(
        default_factory=lambda: ["ES=F", "NQ=F", "ZN=F", "DX-Y.NYB", "GC=F", "CL=F"]
    )
    sources: NewsSourcesCfg = Field(default_factory=NewsSourcesCfg)
    cluster: NewsClusterCfg = Field(default_factory=NewsClusterCfg)
    tagging: NewsTaggingCfg = Field(default_factory=NewsTaggingCfg)
    alerts: NewsAlertsCfg = Field(default_factory=NewsAlertsCfg)
    reaction: NewsReactionCfg = Field(default_factory=NewsReactionCfg)
    quiet_hours: NewsQuietCfg = Field(default_factory=NewsQuietCfg)
    digests: NewsDigestCfg = Field(default_factory=NewsDigestCfg)
    llm: NewsLlmCfg = Field(default_factory=NewsLlmCfg)
    sentiment: NewsSentimentCfg = Field(default_factory=NewsSentimentCfg)
    grounding: NewsGroundingCfg = Field(default_factory=NewsGroundingCfg)
    flags: NewsFlagsCfg = Field(default_factory=NewsFlagsCfg)
    briefs: NewsBriefsCfg = Field(default_factory=NewsBriefsCfg)
```

5. In `Config`: add `news: NewsCfg = Field(default_factory=NewsCfg)` after `spreads`, and a resolver beside `spreads_db_url_abs`:

```python
    def news_db_url_abs(self) -> str:
        """Resolve the relative news sqlite path against the project root."""
        url = self.news.db_url
        if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
            rel = url[len("sqlite:///") :]
            return f"sqlite:///{(ROOT / rel).as_posix()}"
        return url
```

6. In `get_config()` add `news=NewsCfg(**_load_yaml("news.yaml")),` after `spreads=…`.

Create `config/news.example.yaml`:

```yaml
# News service — docs/superpowers/specs/2026-10-09-news-thread-design.md
# Copy to config/news.yaml (git-ignored) to tune. Every key has a code default.
enabled: true
db_url: "sqlite:///data/news.db"
charts_dir: "data/news_charts"
retention_days: 30
lookback_hours: {government: 168, geopolitics: 168, macro: 168, markets: 36, ticker: 72}
# Preferred outlets for the card's primary link/preview, best first (matched on domain).
source_rank: [reuters.com, bloomberg.com, wsj.com, cnbc.com, ft.com, apnews.com, marketwatch.com, finance.yahoo.com, barrons.com]
sources:
  rss_feeds:
    - {name: "Federal Reserve press", url: "https://www.federalreserve.gov/feeds/press_all.xml", category: government}
    - {name: "BLS releases", url: "https://www.bls.gov/feed/bls_latest.rss", category: government}
    - {name: "BEA news", url: "https://apps.bea.gov/rss/rss.xml", category: government}
    - {name: "Treasury press", url: "https://home.treasury.gov/system/files/126/ofac.xml", category: government}
    - {name: "CNBC Top News", url: "https://www.cnbc.com/id/100003114/device/rss/rss.html", category: markets}
    - {name: "CNBC Economy", url: "https://www.cnbc.com/id/20910258/device/rss/rss.html", category: macro}
    - {name: "MarketWatch Top", url: "https://feeds.content.dowjones.io/public/rss/mw_topstories", category: markets}
    - {name: "Yahoo Finance", url: "https://finance.yahoo.com/news/rssindex", category: markets}
  macro_queries:
    - "CPI inflation report"
    - "Federal Reserve rate decision"
    - "jobs report nonfarm payrolls"
    - "tariffs trade war"
    - "ceasefire peace deal"
    - "war escalation markets"
    - "OPEC oil prices"
    - "Treasury yields bond market"
    - "stock market today"
  google_news_days: 3
  rss_poll_minutes: 5
  macro_poll_minutes: 10
  ticker_round_robin_minutes: 30
  econ_poll_minutes: 60
  econ_fast_poll_seconds: 30
  econ_fast_window_before_min: 2
  econ_fast_window_after_min: 10
  earnings_poll_hours: 6
  finnhub_per_minute: 50
cluster: {similarity: 0.5, window_hours: 48}
tagging:
  rumor_terms: [reportedly, "sources say", "people familiar", "in talks", considering, weighs, "according to sources", rumor, rumour]
  forward_terms: [guidance, outlook, forecast, expects, "raises", "cuts", "sees", projects]
  topic_terms:
    war: [war, invasion, missile, airstrike, strike on, troops, attack]
    ceasefire: [ceasefire, truce, "peace deal", "peace talks", armistice]
    sanctions: [sanction, sanctions, embargo, blacklist]
    tariff: [tariff, tariffs, "trade war", "import duties"]
    fed: [fed, fomc, powell, "rate cut", "rate hike", "federal reserve"]
    fiscal: [shutdown, "debt ceiling", deficit, stimulus, "spending bill"]
    energy: [opec, "oil price", crude, "natural gas", pipeline]
  aliases:
    GOOGL: [Alphabet, Google]
    META: [Meta, Facebook]
    BRK.B: [Berkshire]
alerts:
  index_symbols: [SPY, QQQ, DIA]
  index_levels_down: [-1.0, -2.0, -3.0]
  index_levels_up: [2.0, 3.0]
  critical_index_level: -2.0
  vix_jump_pct: 15.0
  vix_levels: [25.0, 30.0]
  held_sigma: 2.0
  universe_sigma: 3.0
  ticker_scan_minutes: 5
  geo_min_sources: 2
  geo_reaction_pct: 0.5
  geo_reaction_window_min: 30
  geo_topics: [war, ceasefire, sanctions, tariff, fed, fiscal, energy]
  max_per_hour: 6
  max_edits: 3
reaction:
  window_min: 15
  max_wait_min: 35
quiet_hours: {tz: "Asia/Singapore", start: "00:00", end: "07:00", critical_breaks_quiet: true}
digests: {premarket: "08:00", close: "16:30", week_ahead_weekday: 6, week_ahead_time: "18:00", max_threads: 6, max_movers: 5}
llm: {backend: cli_then_ollama, model: "claude-sonnet-5-5", ollama_model: "", timeout_seconds: 120, max_calls_per_day: 40}
sentiment: {model: vader, lookback_hours: 72, half_life_hours: 24}
grounding: {rel_tol: 0.02}
flags: {large_move_sigma: 2.0, oversold_rsi: 30, earnings_outsized: 1.5, earnings_muted: 0.5}
briefs: {poll_seconds: 5, dedupe_minutes: 10}
```

Feed URLs are best-effort public feeds: Task 7's probe script (`scripts/news_probe.py`) prints which return items, and the operator prunes dead ones in the private copy. Do **not** block on feed URLs — a dead feed only costs one breaker.

In `.env.example`, after the `TELEGRAM_THREAD_SPREADS` line add:

```
TELEGRAM_THREAD_NEWS=4409  # News thread (src/news/)
# Optional: Finnhub free key (personal use) — company news with images, general news, earnings.
FINNHUB_API_KEY=
```

In `pyproject.toml` `dependencies`, add `"matplotlib>=3.8",`; in `[project.optional-dependencies]` add `finbert = ["transformers>=4.40", "torch>=2.2"]`. Then install: `.venv/bin/pip install "matplotlib>=3.8"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_news_config.py tests/test_spreads_config.py -v`
Expected: PASS.

- [ ] **Step 5: Gate + commit**

Run: `.venv/bin/python -m pytest -q && ruff check . && mypy src`

```bash
git add src/common/config.py config/news.example.yaml .env.example pyproject.toml tests/test_news_config.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): NewsCfg, news.example.yaml, news secrets and data-provider keys"
```

---

### Task 2: News store (`data/news.db`)

**Files:**
- Create: `src/news/__init__.py`, `src/news/store/__init__.py`, `src/news/store/models.py`, `src/news/store/session.py`, `src/news/store/readonly.py`, `src/news/store/state.py`, `src/news/store/queries.py`
- Modify: `tests/conftest.py` (add the `news_db` fixture)
- Test: `tests/test_news_store.py`

**Interfaces:**
- Produces:
  - `src.news.store.models`: `NewsBase`, `NewsItemRow`, `NewsClusterRow`, `EconEventRow`, `EarningsEventRow`, `FeedStateRow`, `NewsPostRow`, `AlertStateRow`, `NewsRequestRow`, `NewsStateRow`, `TickerAliasRow` (columns exactly as below).
  - `src.news.store.session`: `get_news_engine() -> Engine`, `init_news_db() -> None`, `news_session() -> ContextManager[Session]` (commits on exit), `_resolve_url() -> str` (patched in tests).
  - `src.news.store.readonly`: `read_only_session() -> ContextManager[Session | None]` — yields `None` when the DB file does not exist or cannot be opened; `_resolve_path() -> str` (patched in tests); `reset_engine() -> None`.
  - `src.news.store.state`: `HEARTBEAT_KEY = "heartbeat"`, `set_state(key: str, value: str, *, now: datetime | None = None) -> None`, `get_state(key: str) -> str | None`, `touch_heartbeat(now: datetime) -> None`, `record_source_ok(source: str, now: datetime) -> None`, `incr_llm_calls(day: date) -> int`, `llm_calls(day: date) -> int`.
  - `src.news.store.queries`: `naive_utc(dt: datetime) -> datetime`, `aware_utc(dt: datetime) -> datetime` (more helpers added in Tasks 31/25).
  - Fixture `news_db` (returns the tmp `Path`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_news_store.py
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import inspect


def test_schema_has_every_table(news_db) -> None:
    from src.news.store.session import get_news_engine

    names = set(inspect(get_news_engine()).get_table_names())
    assert {
        "news_items", "news_clusters", "econ_events", "earnings_events", "feed_state",
        "news_posts", "alert_state", "news_requests", "news_state", "ticker_aliases",
    } <= names


def test_news_base_is_not_the_trading_base() -> None:
    from src.news.store.models import NewsBase
    from src.storage.models import Base

    assert NewsBase.metadata is not Base.metadata
    assert "news_items" not in Base.metadata.tables


def test_state_round_trip_and_llm_counter(news_db) -> None:
    from src.news.store import state

    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    state.touch_heartbeat(now)
    assert state.get_state(state.HEARTBEAT_KEY) == now.isoformat()
    d = date(2026, 10, 9)
    assert state.llm_calls(d) == 0
    assert state.incr_llm_calls(d) == 1
    assert state.incr_llm_calls(d) == 2
    assert state.llm_calls(date(2026, 10, 10)) == 0


def test_readonly_session_yields_none_when_db_missing(tmp_path, monkeypatch) -> None:
    from src.news.store import readonly

    readonly.reset_engine()
    monkeypatch.setattr(readonly, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    with readonly.read_only_session() as s:
        assert s is None


def test_readonly_session_cannot_write(news_db) -> None:
    import pytest
    from sqlalchemy.exc import OperationalError

    from src.news.store import readonly
    from src.news.store.models import NewsStateRow

    with readonly.read_only_session() as s:
        assert s is not None
        s.add(NewsStateRow(key="x", value="y", updated_at=datetime(2026, 1, 1)))
        with pytest.raises(OperationalError):
            s.flush()
```

Add to `tests/conftest.py` (end of file):

```python
@pytest.fixture()
def news_db(tmp_path, monkeypatch):
    """An isolated data/news.db for src.news tests (both the rw and ro engines)."""
    import src.news.store.readonly as ro
    import src.news.store.session as rw

    path = tmp_path / "news.db"
    monkeypatch.setattr(rw, "_engine", None)
    monkeypatch.setattr(rw, "_SessionLocal", None)
    monkeypatch.setattr(rw, "_resolve_url", lambda: f"sqlite:///{path}")
    ro.reset_engine()
    monkeypatch.setattr(ro, "_resolve_path", lambda: str(path))
    rw.init_news_db()
    yield path
    ro.reset_engine()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_news_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.news'`.

- [ ] **Step 3: Implement**

`src/news/__init__.py`:

```python
"""News service — macro, market and ticker news with grounded implications.

Spec: docs/superpowers/specs/2026-10-09-news-thread-design.md.

Fence (CLAUDE.md, spec §10): enrichment tier. Nothing here is importable from src/engine/,
src/execution/, src/strategies/ or src/spreads/; this package imports none of them, nor
src.orchestrator or src.notify.approval_service. data/news.db is written only from here.
"""
```

`src/news/store/__init__.py`: `"""data/news.db — the news service's own database (NewsBase)."""`

`src/news/store/models.py`:

```python
"""The news service's own SQLite database (``data/news.db``).

A separate engine and DeclarativeBase from the trading DB (the ``src/spreads/store.py``
pattern), so ``create_all`` can never build a news table in ``income_system.db``.
Timestamps are stored naive-UTC; convert with ``queries.aware_utc`` at the edges.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class NewsBase(DeclarativeBase):
    pass


class NewsItemRow(NewsBase):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url_hash: Mapped[str] = mapped_column(String(40), unique=True)
    title_hash: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_domain: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str] = mapped_column(String(16), index=True)
    origin: Mapped[str] = mapped_column(String(16))  # rss | google | yfinance | finnhub
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    tickers: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    det_sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cluster_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


class NewsClusterRow(NewsBase):
    __tablename__ = "news_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    headline: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(16), index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, index=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime, index=True)
    source_domains: Mapped[list] = mapped_column(JSON, default=list)
    source_count: Mapped[int] = mapped_column(Integer, default=1)
    tickers: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    topic_class: Mapped[str] = mapped_column(String(16), default="other")
    title_tokens: Mapped[list] = mapped_column(JSON, default=list)


class EconEventRow(NewsBase):
    __tablename__ = "econ_events"

    event_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    playbook_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # naive UTC
    impact: Mapped[str] = mapped_column(String(16))
    forecast: Mapped[str | None] = mapped_column(String(40), nullable=True)
    previous: Mapped[str | None] = mapped_column(String(40), nullable=True)
    consensus: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actual: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actual_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    surprise_dir: Mapped[str | None] = mapped_column(String(8), nullable=True)
    alerted: Mapped[bool] = mapped_column(Boolean, default=False)


class EarningsEventRow(NewsBase):
    __tablename__ = "earnings_events"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    timing: Mapped[str] = mapped_column(String(8), default="unknown")  # bmo | amc | unknown
    eps_est: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    rev_est: Mapped[float | None] = mapped_column(Float, nullable=True)
    rev_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="scheduled")  # scheduled | released
    released_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    alerted: Mapped[bool] = mapped_column(Boolean, default=False)


class FeedStateRow(NewsBase):
    __tablename__ = "feed_state"

    feed_url: Mapped[str] = mapped_column(String(1000), primary_key=True)
    etag: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_polled: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_ok: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NewsPostRow(NewsBase):
    __tablename__ = "news_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chart_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cluster_ids: Mapped[list] = mapped_column(JSON, default=list)
    posted_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stage: Mapped[str] = mapped_column(String(12), default="facts")  # facts|explained|fallback
    llm_backend: Mapped[str | None] = mapped_column(String(16), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    silent: Mapped[bool] = mapped_column(Boolean, default=False)
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    edits: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # CardPayload.model_dump(mode="json")
    chart_path: Mapped[str | None] = mapped_column(String(300), nullable=True)


class AlertStateRow(NewsBase):
    __tablename__ = "alert_state"
    __table_args__ = (UniqueConstraint("trigger", "subject", "trade_date", name="uq_alert_once"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(200))
    trade_date: Mapped[date] = mapped_column(Date)
    fired_at: Mapped[datetime] = mapped_column(DateTime)


class NewsRequestRow(NewsBase):
    __tablename__ = "news_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    origin: Mapped[str] = mapped_column(String(12))  # telegram | web
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    post_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)


class NewsStateRow(NewsBase):
    __tablename__ = "news_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(2000))
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class TickerAliasRow(NewsBase):
    __tablename__ = "ticker_aliases"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
```

`src/news/store/session.py`:

```python
"""Read-write engine for data/news.db — imported only by the news process's modules.

src/api/ must never import this module (spec §10.6); it reads through src/api/news_db.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config
from src.news.store.models import NewsBase

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_url() -> str:
    """Absolute sqlite URL for data/news.db. Patched in tests."""
    return get_config().news_db_url_abs()


def get_news_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = _resolve_url()
        if url.startswith("sqlite:///"):
            Path(url[len("sqlite:///") :]).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True, connect_args={"timeout": 15})

        @event.listens_for(_engine, "connect")
        def _set_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def init_news_db() -> None:
    NewsBase.metadata.create_all(get_news_engine())


@contextmanager
def news_session() -> Iterator[Session]:
    get_news_engine()
    assert _SessionLocal is not None
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
```

`src/news/store/readonly.py`:

```python
"""Read-only access to data/news.db for readers outside the news process.

Used by src/analytics/sentiment.py, src/claude/news_context.py, src/news/briefs.py's
reads and the watchdog. Opens SQLite with ``mode=ro`` so an accidental write raises.
Yields ``None`` when the file does not exist yet (fresh install) or cannot be opened —
callers treat that as "no news" and fall back (Review Focus 5).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config

log = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_path() -> str:
    """Filesystem path of data/news.db. Patched in tests."""
    url = get_config().news_db_url_abs()
    return url[len("sqlite:///") :] if url.startswith("sqlite:///") else url


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


@contextmanager
def read_only_session() -> Iterator[Session | None]:
    global _engine, _SessionLocal
    path = _resolve_path()
    if not Path(path).exists():
        yield None
        return
    try:
        if _engine is None:
            _engine = create_engine(
                f"sqlite:///file:{path}?mode=ro&uri=true",
                future=True,
                connect_args={"timeout": 5},
            )
            _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
        assert _SessionLocal is not None
        s = _SessionLocal()
        s.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — readers must degrade, never raise
        log.debug("news readonly: cannot open %s: %s", path, exc)
        yield None
        return
    try:
        yield s
    finally:
        s.rollback()
        s.close()
```

`src/news/store/state.py`:

```python
"""Small key/value state in news_state: heartbeat, LLM call counter, per-source last-ok."""

from __future__ import annotations

from datetime import UTC, date, datetime

from src.news.store.models import NewsStateRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session

HEARTBEAT_KEY = "heartbeat"


def _llm_key(day: date) -> str:
    return f"llm_calls:{day.isoformat()}"


def set_state(key: str, value: str, *, now: datetime | None = None) -> None:
    when = naive_utc(now or datetime.now(UTC))
    with news_session() as s:
        row = s.get(NewsStateRow, key)
        if row is None:
            s.add(NewsStateRow(key=key, value=value, updated_at=when))
        else:
            row.value = value
            row.updated_at = when


def get_state(key: str) -> str | None:
    with news_session() as s:
        row = s.get(NewsStateRow, key)
        return None if row is None else row.value


def touch_heartbeat(now: datetime) -> None:
    set_state(HEARTBEAT_KEY, now.astimezone(UTC).isoformat(), now=now)


def record_source_ok(source: str, now: datetime) -> None:
    set_state(f"source_ok:{source}", now.astimezone(UTC).isoformat(), now=now)


def llm_calls(day: date) -> int:
    raw = get_state(_llm_key(day))
    return int(raw) if raw else 0


def incr_llm_calls(day: date) -> int:
    with news_session() as s:
        row = s.get(NewsStateRow, _llm_key(day))
        now = naive_utc(datetime.now(UTC))
        if row is None:
            s.add(NewsStateRow(key=_llm_key(day), value="1", updated_at=now))
            return 1
        row.value = str(int(row.value) + 1)
        row.updated_at = now
        return int(row.value)
```

`src/news/store/queries.py` (starts small; Tasks 25/28/31 add readers):

```python
"""Session-parameterised read helpers over data/news.db.

Takes a Session and never opens one, so the news process (read-write engine), the API
(src/api/news_db.py, read-only) and the read-only readers share one query implementation.
Imports no engine module — src/api/ may import this file (spec §10.6).
"""

from __future__ import annotations

from datetime import UTC, datetime


def naive_utc(dt: datetime) -> datetime:
    """Aware → naive UTC for storage (the spreads-store convention). Naive input is assumed UTC."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def aware_utc(dt: datetime) -> datetime:
    """Stored naive-UTC → aware UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_news_store.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Gate + commit**

Run: `.venv/bin/python -m pytest -q && ruff check . && mypy src`

```bash
git add src/news tests/test_news_store.py tests/conftest.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): data/news.db store — models, rw/ro engines, key-value state"
```

---

### Task 3: Text utilities and deterministic tagging

**Files:**
- Create: `src/news/text.py`, `src/news/tagging.py`
- Modify: `src/data/protocols.py` (two optional fields on `NewsItem` — done here because Task 4's ingest persists them)
- Test: `tests/test_news_text_tagging.py`

**Interfaces:**
- Produces (`src.data.protocols.NewsItem`): new fields `summary: str | None = None`, `image_url: str | None = None` (defaults keep every existing caller valid).
- Produces (`src.news.text`): `canonical_url(url: str) -> str`, `sha1(s: str) -> str`, `url_hash(url: str | None, title: str) -> str` (falls back to `"t:" + title_hash` when no URL), `normalize_title(title: str, source: str | None = None) -> str`, `title_hash(title: str, source: str | None = None) -> str`, `title_tokens(title: str) -> frozenset[str]`, `jaccard(a: Iterable[str], b: Iterable[str]) -> float`, `domain_of(url: str | None) -> str | None`.
- Produces (`src.news.tagging`): `AliasIndex = dict[str, re.Pattern[str]]`, `build_alias_index(symbols: Iterable[str], aliases: dict[str, list[str]]) -> AliasIndex`, `tag_tickers(title: str, index: AliasIndex) -> list[str]`, `tag_events(title: str, *, scheduled: bool, cfg: NewsTaggingCfg) -> list[str]`, `topic_class(title: str, cfg: NewsTaggingCfg) -> str`, `det_sentiment(text: str) -> float` (−1..+1; Task 27 adds the FinBERT branch).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_news_text_tagging.py
from __future__ import annotations

from src.common.config import NewsTaggingCfg, get_config
from src.news import tagging, text


def test_canonical_url_strips_tracking_and_case() -> None:
    a = text.canonical_url("HTTPS://WWW.Reuters.com/markets/x?utm_source=tw&id=3&fbclid=zz#frag")
    assert a == "https://www.reuters.com/markets/x?id=3"
    assert text.url_hash("https://a.com/x?utm_medium=y", "T") == text.url_hash("https://a.com/x", "T")
    assert text.url_hash(None, "Fed holds rates").startswith("t:")


def test_normalize_title_drops_google_news_source_suffix() -> None:
    assert text.normalize_title("Fed Holds Rates Steady - Reuters", "Reuters") == "fed holds rates steady"
    assert text.title_hash("Fed holds rates steady!", None) == text.title_hash("fed holds  rates steady", None)


def test_tokens_and_jaccard() -> None:
    a = text.title_tokens("Nvidia shares fall after export curbs on China")
    b = text.title_tokens("Nvidia stock falls on new China export curbs")
    assert "the" not in a and "nvidia" in a
    assert 0.3 < text.jaccard(a, b) <= 1.0
    assert text.jaccard([], []) == 0.0


def test_domain_of() -> None:
    assert text.domain_of("https://www.cnbc.com/2026/10/09/x.html") == "cnbc.com"
    assert text.domain_of(None) is None


def test_ticker_tagging_requires_word_cashtag_or_alias() -> None:
    idx = tagging.build_alias_index(["NVDA", "GOOGL", "V", "BRK.B"], {"GOOGL": ["Alphabet", "Google"]})
    assert tagging.tag_tickers("Alphabet unveils new chip; NVDA slips", idx) == ["GOOGL", "NVDA"]
    assert tagging.tag_tickers("$V beats on volume", idx) == ["V"]
    # A one-letter ticker never matches as a bare word inside prose ("V-shaped recovery").
    assert tagging.tag_tickers("Markets see a V-shaped recovery", idx) == []
    assert tagging.tag_tickers("BRK.B adds to stake", idx) == ["BRK.B"]
    assert tagging.tag_tickers("Investors cheer Nvidia-adjacent names", idx) == []


def test_event_tags_and_topic() -> None:
    cfg = get_config().news.tagging
    tags = tagging.tag_events("Apple reportedly in talks to buy studio for $5 billion", scheduled=False, cfg=cfg)
    assert set(tags) == {"rumor", "quantified"}
    tags = tagging.tag_events("Microsoft raises guidance", scheduled=True, cfg=cfg)
    assert set(tags) == {"forward_looking", "scheduled"}
    assert tagging.topic_class("Ceasefire agreed in Gaza after talks", cfg) == "ceasefire"
    assert tagging.topic_class("Apple launches phone", cfg) == "other"


def test_det_sentiment_range() -> None:
    assert -1.0 <= tagging.det_sentiment("Stocks crash as recession fears grow") < 0
    assert tagging.det_sentiment("") == 0.0


def test_empty_tagging_cfg_is_safe() -> None:
    assert tagging.tag_events("x", scheduled=False, cfg=NewsTaggingCfg()) == []


def test_newsitem_new_fields_default_none() -> None:
    from src.data.protocols import NewsItem

    item = NewsItem(title="x")
    assert item.summary is None and item.image_url is None
    assert NewsItem(title="x", summary="s", image_url="u").image_url == "u"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_news_text_tagging.py -v`
Expected: FAIL — `ImportError: cannot import name 'tagging'`.

- [ ] **Step 3: Implement**

In `src/data/protocols.py`, add to `NewsItem` (after `url`):

```python
    summary: str | None = None  # plain-text teaser (Finnhub/RSS); never HTML
    image_url: str | None = None  # article image when the source supplies one
```

`src/news/text.py`:

```python
"""Pure text helpers for dedupe and clustering. No I/O."""

from __future__ import annotations

import hashlib
import re
import string
from collections.abc import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|cmpid|guccounter)$", re.I)
_PUNCT = str.maketrans({c: " " for c in string.punctuation if c not in "$%."})
_STOP = frozenset(
    "a an the and or of to in on for at by with from as is are be was were after before over "
    "amid into its it this that these those new says said report reports update live".split()
)


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), "")
    )


def normalize_title(title: str, source: str | None = None) -> str:
    t = title.strip()
    if source and t.lower().endswith(f" - {source.lower()}"):
        t = t[: -(len(source) + 3)]
    t = t.lower().translate(_PUNCT).replace("…", " ")
    return " ".join(t.split()).strip(" .")


def title_hash(title: str, source: str | None = None) -> str:
    return sha1(normalize_title(title, source))


def url_hash(url: str | None, title: str, source: str | None = None) -> str:
    if url:
        return sha1(canonical_url(url))
    return "t:" + title_hash(title, source)[:38]


def title_tokens(title: str) -> frozenset[str]:
    return frozenset(w for w in normalize_title(title).split() if len(w) >= 2 and w not in _STOP)


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host or None
```

`src/news/tagging.py`:

```python
"""Deterministic tags computed before any LLM sees an item (spec §5.4)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from src.common.config import NewsTaggingCfg

AliasIndex = dict[str, re.Pattern[str]]

_QUANT = re.compile(r"(\d+(?:\.\d+)?\s?%|[$€£]\s?\d|\d+(?:\.\d+)?\s?(?:bp|bps|basis points)\b|\b\d[\d,.]*\s?(?:billion|million|trillion|bn|mn)\b)", re.I)


def build_alias_index(symbols: Iterable[str], aliases: dict[str, list[str]]) -> AliasIndex:
    """One compiled regex per symbol: ``$SYM`` always; bare ``SYM`` only when ≥ 2 chars and
    upper-case in the title (case-sensitive); company aliases case-insensitive whole words.
    A trailing hyphen is excluded so "V-shaped" / "Nvidia-adjacent" never match."""
    out: AliasIndex = {}
    for sym in sorted({s.upper() for s in symbols}):
        esc = re.escape(sym)
        parts = [rf"\${esc}\b"]
        if len(sym) >= 2:
            parts.append(rf"(?<![A-Za-z$]){esc}(?![A-Za-z0-9-])")
        for alias in aliases.get(sym, []):
            parts.append(rf"(?i:(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z-]))")
        out[sym] = re.compile("|".join(parts))
    return out


def tag_tickers(title: str, index: AliasIndex) -> list[str]:
    return sorted(sym for sym, pat in index.items() if pat.search(title))


def _has_any(text_lower: str, terms: Iterable[str]) -> bool:
    return any(re.search(rf"(?<![a-z]){re.escape(t.lower())}(?![a-z])", text_lower) for t in terms)


def tag_events(title: str, *, scheduled: bool, cfg: NewsTaggingCfg) -> list[str]:
    low = title.lower()
    tags: list[str] = []
    if scheduled:
        tags.append("scheduled")
    if _has_any(low, cfg.rumor_terms):
        tags.append("rumor")
    if _QUANT.search(title):
        tags.append("quantified")
    if _has_any(low, cfg.forward_terms):
        tags.append("forward_looking")
    return tags


def topic_class(title: str, cfg: NewsTaggingCfg) -> str:
    low = title.lower()
    for topic, terms in cfg.topic_terms.items():
        if _has_any(low, terms):
            return topic
    return "other"


def det_sentiment(text: str) -> float:
    """−1..+1 polarity. VADER (+ the existing keyword bias) — reuses src.analytics.sentiment's
    helpers so the news store and the scan score with one lexicon."""
    if not text:
        return 0.0
    from src.analytics.sentiment import _keyword_bias, _vader_compound

    kb = _keyword_bias(text)
    return kb if kb != 0.0 else _vader_compound(text)
```

Note `tag_tickers` returns sorted symbols; the first test's expected `["GOOGL", "NVDA"]` is that sort order.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_news_text_tagging.py -v`
Expected: PASS. (If `vaderSentiment` is not installed in the venv, `det_sentiment` still returns a keyword bias ≤ 0 for "crash"; the range test holds either way.)

- [ ] **Step 5: Gate + commit**

```bash
git add src/data/protocols.py src/news/text.py src/news/tagging.py tests/test_news_text_tagging.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): text normalisation, ticker/event/topic tagging"
```

---

### Task 4: Ingest — dedupe, cluster, persist

**Files:**
- Create: `src/news/ingest.py`
- Test: `tests/test_news_ingest.py`

**Interfaces:**
- Consumes: `NewsItem` (with Task 3's `summary`/`image_url`), `text.*`, `tagging.*`, `news_session`, models.
- Produces: `IngestResult(new_items: int, cluster_ids: set[int])` dataclass; `ingest(items: list[NewsItem], *, category: str, origin: str, alias_index: AliasIndex, cfg: NewsCfg, now: datetime, scheduled_symbols: frozenset[str] = frozenset(), scheduled_terms: tuple[str, ...] = ()) -> IngestResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_news_ingest.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.common.config import get_config
from src.data.protocols import NewsItem
from src.news.tagging import build_alias_index

NOW = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
IDX = build_alias_index(["NVDA", "AAPL"], {})


def _ingest(items, **kw):
    from src.news.ingest import ingest

    return ingest(items, category=kw.pop("category", "ticker"), origin="google",
                  alias_index=IDX, cfg=get_config().news, now=kw.pop("now", NOW), **kw)


def test_same_url_and_same_title_dedupe(news_db) -> None:
    a = NewsItem(title="NVDA falls on export curbs - Reuters", source="Reuters", url="https://reuters.com/a?utm_source=x")
    b = NewsItem(title="NVDA falls on export curbs", source="Yahoo", url="https://reuters.com/a")
    c = NewsItem(title="nvda falls on export curbs!", source="CNBC", url="https://cnbc.com/c")
    r = _ingest([a, b, c])
    assert r.new_items == 1


def test_similar_titles_join_one_cluster_and_count_domains(news_db) -> None:
    from src.news.store.models import NewsClusterRow
    from src.news.store.session import news_session

    r = _ingest([
        NewsItem(title="Nvidia shares fall after new China export curbs", url="https://reuters.com/1"),
        NewsItem(title="Nvidia stock falls on fresh China export curbs", url="https://cnbc.com/2"),
        NewsItem(title="Apple unveils new iPhone lineup", url="https://cnbc.com/3"),
    ])
    assert r.new_items == 3 and len(r.cluster_ids) == 2
    with news_session() as s:
        rows = {c.headline: c for c in s.query(NewsClusterRow)}
    nv = next(c for h, c in rows.items() if "Nvidia" in h)
    assert nv.source_count == 2 and set(nv.source_domains) == {"reuters.com", "cnbc.com"}


def test_cluster_window_expires(news_db) -> None:
    _ingest([NewsItem(title="Nvidia shares fall after China export curbs", url="https://a.com/1")])
    later = NOW + timedelta(hours=get_config().news.cluster.window_hours + 1)
    r = _ingest([NewsItem(title="Nvidia shares fall after China export curbs again", url="https://b.com/2")], now=later)
    assert len(r.cluster_ids) == 1
    from src.news.store.models import NewsClusterRow
    from src.news.store.session import news_session

    with news_session() as s:
        assert s.query(NewsClusterRow).count() == 2


def test_tags_and_tickers_persist(news_db) -> None:
    from src.news.store.models import NewsItemRow
    from src.news.store.session import news_session

    _ingest(
        [NewsItem(title="NVDA reportedly weighs $2 billion deal", url="https://x.com/1", summary="s", image_url="https://img/1.png")],
        scheduled_symbols=frozenset({"NVDA"}),
    )
    with news_session() as s:
        row = s.query(NewsItemRow).one()
    assert row.tickers == ["NVDA"]
    assert {"rumor", "quantified", "scheduled"} <= set(row.tags)
    assert row.image_url == "https://img/1.png" and row.summary == "s"
    assert row.det_sentiment is not None


def test_ticker_query_item_without_match_is_background(news_db) -> None:
    from src.news.store.models import NewsItemRow
    from src.news.store.session import news_session

    _ingest([NewsItem(title="Chipmakers rally as AI demand grows", url="https://x.com/2")])
    with news_session() as s:
        assert s.query(NewsItemRow).one().tickers == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_news_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.news.ingest'`.

- [ ] **Step 3: Implement**

`src/news/ingest.py`:

```python
"""Normalise → dedupe → tag → cluster → persist (spec §5.3–5.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select

from src.common.config import NewsCfg
from src.data.protocols import NewsItem
from src.news import tagging, text
from src.news.store.models import NewsClusterRow, NewsItemRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session


@dataclass
class IngestResult:
    new_items: int = 0
    cluster_ids: set[int] = field(default_factory=set)


def _best_cluster(
    clusters: list[NewsClusterRow], tokens: frozenset[str], threshold: float
) -> NewsClusterRow | None:
    best, best_score = None, 0.0
    for c in clusters:
        score = text.jaccard(tokens, c.title_tokens)
        if score > best_score:
            best, best_score = c, score
    return best if best is not None and best_score >= threshold else None


def ingest(
    items: list[NewsItem],
    *,
    category: str,
    origin: str,
    alias_index: tagging.AliasIndex,
    cfg: NewsCfg,
    now: datetime,
    scheduled_symbols: frozenset[str] = frozenset(),
    scheduled_terms: tuple[str, ...] = (),
) -> IngestResult:
    result = IngestResult()
    now_n = naive_utc(now)
    window_start = now_n - timedelta(hours=cfg.cluster.window_hours)
    with news_session() as s:
        clusters = list(
            s.scalars(
                select(NewsClusterRow).where(
                    NewsClusterRow.category == category, NewsClusterRow.last_seen >= window_start
                )
            )
        )
        seen_url: set[str] = set()
        seen_title: set[str] = set()
        for item in items:
            title = (item.title or "").strip()
            if not title:
                continue
            uh = text.url_hash(item.url, title, item.source)
            th = text.title_hash(title, item.source)
            if uh in seen_url or th in seen_title:
                continue
            if s.scalar(select(NewsItemRow.id).where(NewsItemRow.url_hash == uh)) is not None:
                continue
            dup_title = s.scalar(
                select(NewsItemRow.id).where(
                    NewsItemRow.title_hash == th, NewsItemRow.fetched_at >= window_start
                )
            )
            if dup_title is not None:
                continue
            seen_url.add(uh)
            seen_title.add(th)

            tickers = tagging.tag_tickers(title, alias_index)
            low = title.lower()
            scheduled = bool(set(tickers) & scheduled_symbols) or any(t in low for t in scheduled_terms)
            tags = tagging.tag_events(title, scheduled=scheduled, cfg=cfg.tagging)
            domain = text.domain_of(item.url) or (item.source or "").lower() or None
            tokens = text.title_tokens(title)

            cluster = _best_cluster(clusters, tokens, cfg.cluster.similarity)
            if cluster is None:
                cluster = NewsClusterRow(
                    headline=title[:500],
                    category=category,
                    first_seen=now_n,
                    last_seen=now_n,
                    source_domains=[domain] if domain else [],
                    source_count=1 if domain else 0,
                    tickers=tickers,
                    tags=tags,
                    topic_class=tagging.topic_class(title, cfg.tagging),
                    title_tokens=sorted(tokens),
                )
                s.add(cluster)
                s.flush()
                clusters.append(cluster)
            else:
                domains = set(cluster.source_domains or [])
                if domain:
                    domains.add(domain)
                cluster.source_domains = sorted(domains)
                cluster.source_count = len(domains)
                cluster.tickers = sorted(set(cluster.tickers or []) | set(tickers))
                cluster.tags = sorted(set(cluster.tags or []) | set(tags))
                cluster.last_seen = now_n

            s.add(
                NewsItemRow(
                    url_hash=uh,
                    title_hash=th,
                    title=title[:500],
                    url=item.url,
                    source=item.source,
                    source_domain=domain,
                    category=category,
                    origin=origin,
                    published_at=naive_utc(item.published) if item.published else None,
                    fetched_at=now_n,
                    tickers=tickers,
                    tags=tags,
                    det_sentiment=tagging.det_sentiment(title),
                    summary=item.summary or None,
                    image_url=item.image_url or None,
                    cluster_id=cluster.id,
                )
            )
            result.new_items += 1
            result.cluster_ids.add(cluster.id)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_news_ingest.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Gate + commit**

```bash
git add src/news/ingest.py tests/test_news_ingest.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): ingest — URL/title dedupe, Jaccard clustering, tag persistence"
```

---

### Task 5: Data protocols + RSS backend

**Files:**
- Modify: `src/data/protocols.py`, `src/data/factory.py`
- Create: `src/data/rss_backend.py`, `tests/fixtures/news/rss_sample.xml`, `tests/fixtures/news/atom_sample.xml`
- Test: `tests/test_news_rss.py`

**Interfaces:**
- Produces (`src.data.protocols`):
  - `FeedFetch(BaseModel)`: `items: list[NewsItem]`, `etag: str | None = None`, `last_modified: str | None = None`, `not_modified: bool = False`.
  - `FeedProvider(Protocol)`: `fetch(url: str, *, etag: str | None = None, last_modified: str | None = None, limit: int = 50) -> FeedFetch` (never raises; failure → `FeedFetch(items=[])`).
  - `EconScheduleItem`, `EconActualItem`, `EarningsItem` schemas and `EconScheduleProvider`, `EconActualsProvider`, `EarningsCalendarProvider`, `IntradayPriceProvider` protocols (bodies below; implemented in Tasks 7–9).
- Produces (`src.data.rss_backend`): `RssFeedProvider`, `parse_feed(xml_text: str, limit: int) -> list[NewsItem]`.
- Produces (`src.data.factory`): `get_feed_provider() -> FeedProvider`.

- [ ] **Step 1: Write the failing test**

Create `tests/fixtures/news/rss_sample.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Sample</title>
    <item>
      <title>Fed holds rates steady, signals patience</title>
      <link>https://www.federalreserve.gov/newsevents/pressreleases/monetary20261009a.htm</link>
      <pubDate>Thu, 09 Oct 2026 18:00:00 GMT</pubDate>
      <description>&lt;p&gt;The Federal Open Market Committee decided…&lt;/p&gt;</description>
      <media:content url="https://img.example.com/fed.jpg" medium="image"/>
    </item>
    <item>
      <title></title>
      <link>https://example.com/empty</link>
    </item>
    <item>
      <title>CPI rises 0.4% in September</title>
      <link>https://www.bls.gov/news.release/cpi.nr0.htm</link>
      <pubDate>not a date</pubDate>
      <enclosure url="https://img.example.com/cpi.png" type="image/png"/>
    </item>
  </channel>
</rss>
```

Create `tests/fixtures/news/atom_sample.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom sample</title>
  <entry>
    <title>Treasury announces new sanctions</title>
    <link href="https://home.treasury.gov/news/press-releases/x1"/>
    <updated>2026-10-09T15:30:00Z</updated>
    <summary>Sanctions on…</summary>
  </entry>
</feed>
```

```python
# tests/test_news_rss.py
from __future__ import annotations

from pathlib import Path

import httpx

from src.data.protocols import FeedFetch
from src.data.rss_backend import RssFeedProvider, parse_feed

FIX = Path(__file__).parent / "fixtures" / "news"


def test_parse_rss_items_images_and_bad_dates() -> None:
    items = parse_feed((FIX / "rss_sample.xml").read_text(), limit=10)
    assert [i.title for i in items] == ["Fed holds rates steady, signals patience", "CPI rises 0.4% in September"]
    assert items[0].image_url == "https://img.example.com/fed.jpg"
    assert items[0].published is not None and items[0].published.year == 2026
    assert items[0].summary == "The Federal Open Market Committee decided…"
    assert items[1].published is None and items[1].image_url == "https://img.example.com/cpi.png"


def test_parse_atom() -> None:
    items = parse_feed((FIX / "atom_sample.xml").read_text(), limit=10)
    assert items[0].url == "https://home.treasury.gov/news/press-releases/x1"
    assert items[0].published is not None


def test_conditional_get_304_and_failure(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_get(url, headers, timeout, follow_redirects):
        calls.append(headers)
        if headers.get("If-None-Match") == '"abc"':
            return httpx.Response(304, request=httpx.Request("GET", url))
        return httpx.Response(
            200,
            text=(FIX / "rss_sample.xml").read_text(),
            headers={"ETag": '"abc"', "Last-Modified": "Thu, 09 Oct 2026 18:00:00 GMT"},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("src.data.rss_backend.httpx.get", fake_get)
    p = RssFeedProvider()
    first = p.fetch("https://feed.example/rss")
    assert isinstance(first, FeedFetch) and len(first.items) == 2 and first.etag == '"abc"'
    second = p.fetch("https://feed.example/rss", etag='"abc"')
    assert second.not_modified and second.items == []

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("src.data.rss_backend.httpx.get", boom)
    assert RssFeedProvider().fetch("https://other.example/rss").items == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_news_rss.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.data.rss_backend'`.

- [ ] **Step 3: Implement**

In `src/data/protocols.py`, add `from datetime import date` to the imports and append:

```python
class FeedFetch(BaseModel):
    """One conditional-GET of a feed. ``not_modified`` = HTTP 304 (keep the stored validators)."""

    items: list[NewsItem]
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False


@runtime_checkable
class FeedProvider(Protocol):
    """RSS/Atom feeds with HTTP conditional requests. Never raises."""

    def fetch(
        self, url: str, *, etag: str | None = None, last_modified: str | None = None, limit: int = 50
    ) -> FeedFetch: ...


class EconScheduleItem(BaseModel):
    """A scheduled economic release (ForexFactory). ``scheduled_at`` is tz-aware."""

    title: str
    country: str
    scheduled_at: datetime
    impact: str  # High | Medium | Low | Holiday | Non-Economic
    forecast: str | None = None
    previous: str | None = None


class EconActualItem(BaseModel):
    """A released (or scheduled) value from Nasdaq's economic calendar, US rows only.

    ``et_day``/``et_time`` are the US Eastern date and HH:MM the release belongs to, after the
    backend's D+1 correction (spec §5.1). ``et_time`` is None for untimed rows.
    """

    title: str
    et_day: date
    et_time: str | None = None
    actual: str | None = None
    consensus: str | None = None
    previous: str | None = None


@runtime_checkable
class EconScheduleProvider(Protocol):
    def this_week(self) -> list[EconScheduleItem]: ...


@runtime_checkable
class EconActualsProvider(Protocol):
    def actuals(self, et_day: date) -> list[EconActualItem]: ...


class EarningsItem(BaseModel):
    symbol: str
    report_date: date
    timing: str = "unknown"  # bmo | amc | unknown
    eps_est: float | None = None
    eps_actual: float | None = None
    rev_est: float | None = None
    rev_actual: float | None = None
    source: str = ""


@runtime_checkable
class EarningsCalendarProvider(Protocol):
    def on(self, et_day: date) -> list[EarningsItem]: ...


@runtime_checkable
class IntradayPriceProvider(Protocol):
    """Intraday bars incl. pre/post market. Index is tz-aware; columns Open/High/Low/Close/Volume.
    Empty DataFrame when unavailable. Never raises."""

    def get_intraday(self, symbol: str, *, interval: str = "1m", days: int = 1) -> pd.DataFrame: ...
```

Create `src/data/rss_backend.py`:

```python
"""RSS 2.0 / Atom feeds with HTTP conditional GET (ETag / Last-Modified), stdlib XML only.

The MarketGPT idea (spec §3): skip unchanged feeds with a 304 instead of re-downloading.
Never raises: network, HTTP and parse errors degrade to ``FeedFetch(items=[])`` and
record a breaker failure keyed by host, so one dead feed never blocks the others.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

from src.data.breaker import get_breaker
from src.data.protocols import FeedFetch, NewsItem

log = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; ibkr-income-system/1.0; news)"
_TIMEOUT = 10.0
_TAG = re.compile(r"<[^>]+>")
_ATOM = "{http://www.w3.org/2005/Atom}"
_MEDIA = "{http://search.yahoo.com/mrss/}"


def _clean(s: str | None, limit: int = 1000) -> str | None:
    if not s:
        return None
    t = " ".join(_TAG.sub(" ", html.unescape(html.unescape(s))).split())
    return t[:limit] or None


def _date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return parsedate_to_datetime(s)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _image(elem: ElementTree.Element) -> str | None:
    for tag in (f"{_MEDIA}content", f"{_MEDIA}thumbnail"):
        m = elem.find(tag)
        if m is not None and m.get("url"):
            return m.get("url")
    enc = elem.find("enclosure")
    if enc is not None and (enc.get("type") or "").startswith("image") and enc.get("url"):
        return enc.get("url")
    return None


def parse_feed(xml_text: str, limit: int) -> list[NewsItem]:
    root = ElementTree.fromstring(xml_text)
    out: list[NewsItem] = []
    if root.tag == f"{_ATOM}feed":
        for e in root.iter(f"{_ATOM}entry"):
            title = _clean(e.findtext(f"{_ATOM}title"), 500)
            if not title:
                continue
            link = e.find(f"{_ATOM}link")
            out.append(
                NewsItem(
                    title=title,
                    url=link.get("href") if link is not None else None,
                    published=_date(e.findtext(f"{_ATOM}updated") or e.findtext(f"{_ATOM}published")),
                    summary=_clean(e.findtext(f"{_ATOM}summary")),
                )
            )
            if len(out) >= limit:
                break
        return out
    for e in root.iter("item"):
        title = _clean(e.findtext("title"), 500)
        if not title:
            continue
        link = (e.findtext("link") or "").strip() or None
        out.append(
            NewsItem(
                title=title,
                url=link,
                source=_clean(e.findtext("source"), 120),
                published=_date(e.findtext("pubDate")),
                summary=_clean(e.findtext("description")),
                image_url=_image(e),
            )
        )
        if len(out) >= limit:
            break
    return out


class RssFeedProvider:
    def fetch(
        self, url: str, *, etag: str | None = None, last_modified: str | None = None, limit: int = 50
    ) -> FeedFetch:
        breaker = get_breaker(f"rss:{urlsplit(url).netloc}")
        if not breaker.allow():
            return FeedFetch(items=[], etag=etag, last_modified=last_modified)
        headers = {"User-Agent": _UA}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        try:
            resp = httpx.get(url, headers=headers, timeout=_TIMEOUT, follow_redirects=True)
            if resp.status_code == 304:
                breaker.record_success()
                return FeedFetch(items=[], etag=etag, last_modified=last_modified, not_modified=True)
            resp.raise_for_status()
            items = parse_feed(resp.text, limit)
        except Exception as exc:  # noqa: BLE001 — providers never raise
            log.debug("rss: fetch %s failed: %s", url, exc)
            breaker.record_failure()
            return FeedFetch(items=[], etag=etag, last_modified=last_modified)
        breaker.record_success()
        return FeedFetch(
            items=items,
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )
```

In `src/data/factory.py` add `FeedProvider` to the protocol imports and:

```python
@functools.lru_cache(maxsize=1)
def get_feed_provider() -> FeedProvider:
    """RSS/Atom feeds for the news service (stdlib parser, conditional GET)."""
    from src.data.rss_backend import RssFeedProvider

    return RssFeedProvider()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_news_rss.py tests/test_news_ingest.py tests/test_news_context.py -v`
Expected: PASS (the existing `test_news_context.py` proves `NewsItem`'s new defaults broke nothing).

- [ ] **Step 5: Gate + commit**

```bash
git add src/data/protocols.py src/data/rss_backend.py src/data/factory.py tests/fixtures/news tests/test_news_rss.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(data): news source protocols, NewsItem summary/image, RSS backend with conditional GET"
```

---

### Task 6: Finnhub backend

**Files:**
- Create: `src/data/finnhub_backend.py`, `tests/fixtures/news/finnhub_company_news.json`, `tests/fixtures/news/finnhub_earnings_calendar.json`
- Modify: `src/data/factory.py`
- Test: `tests/test_news_finnhub.py`

**Interfaces:**
- Produces: `FinnhubClient(api_key: str, *, per_minute: int = 50)` with `company_news(symbol: str, *, days: int = 3, today: date | None = None) -> list[NewsItem]`, `general_news() -> list[NewsItem]`, `earnings_calendar(start: date, end: date, symbol: str | None = None) -> list[EarningsItem]`; `get_finnhub_client() -> FinnhubClient | None` (None when `FINNHUB_API_KEY` is empty).

- [ ] **Step 1: Write the failing test**

`tests/fixtures/news/finnhub_company_news.json` (trimmed from the 2026-10-09 probe):

```json
[
  {"category": "company", "datetime": 1791525420, "headline": "3 Stocks Poised to Gain as Google Brings Its AI Chips to Market", "id": 142744403, "image": "https://s.yimg.com/rz/stage/p/yahoo_finance_en-US_h_p_finance_2.png", "related": "NVDA", "source": "Yahoo", "summary": "Google may become a major AI chipmaker, and there are some clear winners from that development.", "url": "https://finnhub.io/api/news?id=0088a"},
  {"category": "company", "datetime": 1791520000, "headline": "", "id": 1, "image": "", "related": "NVDA", "source": "X", "summary": "", "url": ""}
]
```

`tests/fixtures/news/finnhub_earnings_calendar.json`:

```json
{"earningsCalendar": [
  {"symbol": "BAC", "date": "2026-10-14", "hour": "bmo", "quarter": 3, "year": 2026, "epsEstimate": 1.12, "epsActual": null, "revenueEstimate": 27100000000, "revenueActual": null},
  {"symbol": "NFLX", "date": "2026-10-15", "hour": "amc", "quarter": 3, "year": 2026, "epsEstimate": 5.1, "epsActual": 5.4, "revenueEstimate": 11000000000, "revenueActual": 11200000000},
  {"symbol": "ZZZ", "date": "2026-10-16", "hour": "", "quarter": 3, "year": 2026, "epsEstimate": null, "epsActual": null, "revenueEstimate": null, "revenueActual": null}
]}
```

```python
# tests/test_news_finnhub.py
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from src.data.finnhub_backend import FinnhubClient

FIX = Path(__file__).parent / "fixtures" / "news"


def _router(monkeypatch, routes: dict[str, object], seen: list[str]) -> None:
    def fake_get(url, params, timeout, headers):
        seen.append(url)
        assert params["token"] == "KEY"
        for suffix, body in routes.items():
            if url.endswith(suffix):
                return httpx.Response(200, json=body, request=httpx.Request("GET", url))
        return httpx.Response(403, json={"error": "no"}, request=httpx.Request("GET", url))

    monkeypatch.setattr("src.data.finnhub_backend.httpx.get", fake_get)


def test_company_news_maps_fields_and_drops_empty(monkeypatch) -> None:
    seen: list[str] = []
    _router(monkeypatch, {"/company-news": json.loads((FIX / "finnhub_company_news.json").read_text())}, seen)
    items = FinnhubClient("KEY").company_news("NVDA", days=2, today=date(2026, 10, 9))
    assert len(items) == 1
    it = items[0]
    assert it.image_url.startswith("https://s.yimg.com") and it.summary.startswith("Google may")
    assert it.source == "Yahoo" and it.published is not None


def test_earnings_calendar_timing_and_actuals(monkeypatch) -> None:
    seen: list[str] = []
    _router(monkeypatch, {"/calendar/earnings": json.loads((FIX / "finnhub_earnings_calendar.json").read_text())}, seen)
    rows = FinnhubClient("KEY").earnings_calendar(date(2026, 10, 9), date(2026, 10, 16))
    by = {r.symbol: r for r in rows}
    assert by["BAC"].timing == "bmo" and by["BAC"].eps_actual is None
    assert by["NFLX"].timing == "amc" and by["NFLX"].eps_actual == 5.4
    assert by["ZZZ"].timing == "unknown"


def test_errors_never_raise_and_key_never_logged(monkeypatch, caplog) -> None:
    seen: list[str] = []
    _router(monkeypatch, {}, seen)
    c = FinnhubClient("KEY")
    assert c.general_news() == []
    assert "KEY" not in caplog.text


def test_factory_returns_none_without_key(monkeypatch) -> None:
    from src.common.config import get_config
    from src.data import factory

    monkeypatch.setattr(get_config().secrets, "finnhub_api_key", "")
    factory.get_finnhub_client.cache_clear()
    assert factory.get_finnhub_client() is None
    factory.get_finnhub_client.cache_clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_news_finnhub.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

`src/data/finnhub_backend.py`:

```python
"""Finnhub free tier (personal use): company/general news with images, earnings calendar.

Probed 2026-10-09 with the operator's key (spec §5.1): company-news, news?category=general,
calendar/earnings and stock/earnings return 200; calendar/economic returns 403 (premium) and
is not used. The key travels only as the ``token`` query parameter and is never logged.
A client-side token bucket keeps us under ``per_minute`` (free tier: 60/min).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, date, datetime, timedelta

import httpx

from src.data.breaker import get_breaker
from src.data.protocols import EarningsItem, NewsItem

log = logging.getLogger(__name__)

_BASE = "https://finnhub.io/api/v1"
_TIMEOUT = 10.0
_HOUR = {"bmo": "bmo", "amc": "amc", "dmh": "unknown", "": "unknown"}


class _Bucket:
    def __init__(self, per_minute: int) -> None:
        self._interval = 60.0 / max(1, per_minute)
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._interval
        if delay:
            time.sleep(delay)


class FinnhubClient:
    def __init__(self, api_key: str, *, per_minute: int = 50) -> None:
        self._key = api_key
        self._bucket = _Bucket(per_minute)

    def _get(self, path: str, **params: object) -> object | None:
        breaker = get_breaker("finnhub")
        if not breaker.allow():
            return None
        self._bucket.wait()
        try:
            resp = httpx.get(
                f"{_BASE}{path}",
                params={**params, "token": self._key},
                timeout=_TIMEOUT,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:  # noqa: BLE001 — never raise; never log the URL (it has no key, but params do)
            log.debug("finnhub: %s failed: %s", path, type(exc).__name__)
            breaker.record_failure()
            return None
        breaker.record_success()
        return body

    @staticmethod
    def _news(rows: object) -> list[NewsItem]:
        out: list[NewsItem] = []
        for r in rows if isinstance(rows, list) else []:
            title = (r.get("headline") or "").strip()
            if not title:
                continue
            ts = r.get("datetime")
            out.append(
                NewsItem(
                    title=title,
                    source=r.get("source") or None,
                    url=r.get("url") or None,
                    published=datetime.fromtimestamp(ts, UTC) if isinstance(ts, int | float) and ts > 0 else None,
                    summary=(r.get("summary") or "").strip()[:1000] or None,
                    image_url=r.get("image") or None,
                )
            )
        return out

    def company_news(self, symbol: str, *, days: int = 3, today: date | None = None) -> list[NewsItem]:
        end = today or datetime.now(UTC).date()
        start = end - timedelta(days=days)
        return self._news(self._get("/company-news", symbol=symbol.upper(), **{"from": start.isoformat(), "to": end.isoformat()}))

    def general_news(self) -> list[NewsItem]:
        return self._news(self._get("/news", category="general"))

    def earnings_calendar(self, start: date, end: date, symbol: str | None = None) -> list[EarningsItem]:
        params: dict[str, object] = {"from": start.isoformat(), "to": end.isoformat()}
        if symbol:
            params["symbol"] = symbol.upper()
        body = self._get("/calendar/earnings", **params)
        rows = body.get("earningsCalendar", []) if isinstance(body, dict) else []
        out: list[EarningsItem] = []
        for r in rows:
            try:
                out.append(
                    EarningsItem(
                        symbol=str(r["symbol"]).upper(),
                        report_date=date.fromisoformat(r["date"]),
                        timing=_HOUR.get(str(r.get("hour") or "").lower(), "unknown"),
                        eps_est=r.get("epsEstimate"),
                        eps_actual=r.get("epsActual"),
                        rev_est=r.get("revenueEstimate"),
                        rev_actual=r.get("revenueActual"),
                        source="finnhub",
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return out
```

In `src/data/factory.py`:

```python
@functools.lru_cache(maxsize=1)
def get_finnhub_client():  # -> FinnhubClient | None
    """Finnhub client, or None when FINNHUB_API_KEY is unset (the source is then dormant)."""
    cfg = get_config()
    key = cfg.secrets.finnhub_api_key
    if not key:
        return None
    from src.data.finnhub_backend import FinnhubClient

    return FinnhubClient(key, per_minute=cfg.news.sources.finnhub_per_minute)
```

Annotate the return as `"FinnhubClient | None"` with `from __future__ import annotations` already present and a `TYPE_CHECKING` import of `FinnhubClient` so mypy is happy.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_news_finnhub.py -v` → PASS.

- [ ] **Step 5: Gate + commit**

```bash
git add src/data/finnhub_backend.py src/data/factory.py tests/fixtures/news/finnhub_*.json tests/test_news_finnhub.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(data): Finnhub backend — company/general news with images, earnings calendar"
```

### Task 7: Economic schedule (ForexFactory) + actuals (Nasdaq) + live probe script

**Files:**
- Create: `src/data/forexfactory_backend.py`, `src/data/nasdaq_backend.py`, `scripts/news_probe.py`
- Create fixtures: `tests/fixtures/news/ff_thisweek.json`, `tests/fixtures/news/nasdaq_econ_2026-10-09.json`
- Modify: `src/data/factory.py`, `src/common/config.py` (`NewsSourcesCfg`), `config/news.example.yaml`
- Test: `tests/test_news_econ_sources.py`

**Interfaces:**
- Produces: `parse_ff(rows: list[dict]) -> list[EconScheduleItem]`, `ForexFactoryScheduleProvider.this_week()`; `parse_nasdaq_econ(body: dict, et_day: date) -> list[EconActualItem]`, `NasdaqEconActualsProvider(date_offset_days: int).actuals(et_day)`; `clean_value(v: object) -> str | None` (shared with Task 8); factory `get_econ_schedule_provider()`, `get_econ_actuals_provider()`; config `NewsSourcesCfg.nasdaq_econ_date_offset_days: int = 1`, `nasdaq_earnings_date_offset_days: int = 0`; `scripts.news_probe.infer_offset(ff_titles_by_day: dict[date, set[str]], nasdaq_titles_by_request_day: dict[date, set[str]]) -> int | None`.

**Facts this task pins (probed live 2026-10-09):** ForexFactory's weekly JSON has keys `title, country, date, impact, forecast, previous` and **no `actual`**. Nasdaq's `economicevents?date=D` returns all countries; the US rows for ET day D−1 come back under `date=D`, and the column named `gmt` holds **ET** `HH:MM`. Non-values appear as `"&nbsp;"`, `" "`, or `""`.

- [ ] **Step 1: Write fixtures and the failing test**

`tests/fixtures/news/ff_thisweek.json` (verbatim subset of the 2026-10-09 probe):

```json
[
  {"title": "ISM Services PMI", "country": "USD", "date": "2026-10-05T10:00:00-04:00", "impact": "Medium", "forecast": "55.1", "previous": "55.4"},
  {"title": "FOMC Meeting Minutes", "country": "USD", "date": "2026-10-07T14:00:00-04:00", "impact": "High", "forecast": "", "previous": ""},
  {"title": "Unemployment Claims", "country": "USD", "date": "2026-10-08T08:30:00-04:00", "impact": "Medium", "forecast": "200K", "previous": "197K"},
  {"title": "Prelim UoM Consumer Sentiment", "country": "USD", "date": "2026-10-09T10:00:00-04:00", "impact": "Medium", "forecast": "47.5", "previous": "47.8"},
  {"title": "German Industrial Production m/m", "country": "EUR", "date": "2026-10-08T02:00:00-04:00", "impact": "Medium", "forecast": "0.3%", "previous": "-0.2%"},
  {"title": "Bank Holiday", "country": "USD", "date": "2026-10-12T00:00:00-04:00", "impact": "Holiday", "forecast": "", "previous": ""},
  {"title": "Broken", "country": "USD", "date": "not-a-date", "impact": "High"}
]
```

`tests/fixtures/news/nasdaq_econ_2026-10-09.json` (subset of the probe's `date=2026-10-09` response, plus two synthetic edge rows marked in `description`):

```json
{"data": {"headers": {"gmt": "Time", "country": "Country", "eventName": "Event", "actual": "Actual", "consensus": "Consensus", "previous": "Previous", "description": "Description"},
 "rows": [
  {"gmt": "00:30", "country": "India", "eventName": "Interest Rate Decision", "actual": "5.50%", "consensus": "5.50%", "previous": "5.25%", "description": ""},
  {"gmt": "08:30", "country": "United States", "eventName": "Initial Jobless Claims", "actual": "197K", "consensus": "200K", "previous": "199K", "description": ""},
  {"gmt": "08:30", "country": "United States", "eventName": "Continuing Jobless Claims", "actual": "1,716K", "consensus": "1,710K", "previous": "1,699K", "description": ""},
  {"gmt": "04:30", "country": "United States", "eventName": "Fed Waller Speaks", "actual": "&nbsp;", "consensus": " ", "previous": "&nbsp;", "description": ""},
  {"gmt": "All Day", "country": "United States", "eventName": "Synthetic untimed row", "actual": "", "consensus": "", "previous": "", "description": "synthetic"},
  {"gmt": "Tentative", "country": "United States", "eventName": "Synthetic tentative row", "actual": "1.0%", "consensus": "", "previous": "", "description": "synthetic"}
 ]}}
```

```python
# tests/test_news_econ_sources.py
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx

from src.data.forexfactory_backend import parse_ff
from src.data.nasdaq_backend import NasdaqEconActualsProvider, clean_value, parse_nasdaq_econ

FIX = Path(__file__).parent / "fixtures" / "news"


def test_ff_parses_aware_et_times_and_skips_garbage() -> None:
    items = parse_ff(json.loads((FIX / "ff_thisweek.json").read_text()))
    assert "Broken" not in {i.title for i in items}
    claims = next(i for i in items if i.title == "Unemployment Claims")
    assert claims.scheduled_at.utcoffset().total_seconds() == -4 * 3600
    assert (claims.forecast, claims.previous) == ("200K", "197K")
    assert next(i for i in items if i.title == "FOMC Meeting Minutes").forecast is None


def test_clean_value() -> None:
    assert clean_value("&nbsp;") is None and clean_value(" ") is None and clean_value("") is None
    assert clean_value(None) is None
    assert clean_value(" 1,716K ") == "1,716K"


def test_nasdaq_non_values_and_untimed_rows() -> None:
    rows = parse_nasdaq_econ(json.loads((FIX / "nasdaq_econ_2026-10-09.json").read_text()), date(2026, 10, 8))
    assert all(r.et_day == date(2026, 10, 8) for r in rows)
    titles = {r.title: r for r in rows}
    assert "Interest Rate Decision" not in titles  # India filtered out
    assert titles["Initial Jobless Claims"].actual == "197K" and titles["Initial Jobless Claims"].et_time == "08:30"
    assert titles["Fed Waller Speaks"].actual is None and titles["Fed Waller Speaks"].consensus is None
    assert titles["Synthetic untimed row"].et_time is None
    assert titles["Synthetic tentative row"].et_time is None


def test_actuals_requests_et_day_plus_offset(monkeypatch) -> None:
    asked: list[str] = []

    def fake_get(url, params, headers, timeout):
        asked.append(params["date"])
        return httpx.Response(200, json=json.loads((FIX / "nasdaq_econ_2026-10-09.json").read_text()), request=httpx.Request("GET", url))

    monkeypatch.setattr("src.data.nasdaq_backend.httpx.get", fake_get)
    rows = NasdaqEconActualsProvider(date_offset_days=1).actuals(date(2026, 10, 8))
    assert asked == ["2026-10-09"] and rows and rows[0].et_day == date(2026, 10, 8)


def test_probe_infers_offset() -> None:
    from scripts.news_probe import infer_offset

    ff = {date(2026, 10, 8): {"unemployment claims"}}
    nd = {date(2026, 10, 8): {"mba mortgage applications"}, date(2026, 10, 9): {"initial jobless claims", "continuing jobless claims"}}
    assert infer_offset(ff, nd, synonyms={"unemployment claims": "initial jobless claims"}) == 1
    assert infer_offset({}, {}, synonyms={}) is None
```

- [ ] **Step 2: Run test to verify it fails** — `.venv/bin/python -m pytest tests/test_news_econ_sources.py -v` → FAIL (modules missing).

- [ ] **Step 3: Implement**

Add to `NewsSourcesCfg` (Task 1) and to `config/news.example.yaml` under `sources:`:

```python
    # Probed 2026-10-09: Nasdaq's economicevents?date=D returns ET day D-1's US releases.
    # scripts/news_probe.py re-checks this; set to 0 if the probe says so.
    nasdaq_econ_date_offset_days: int = 1
    nasdaq_earnings_date_offset_days: int = 0
```

```yaml
  nasdaq_econ_date_offset_days: 1   # probed 2026-10-09; re-check with python -m scripts.news_probe
  nasdaq_earnings_date_offset_days: 0
```

`src/data/forexfactory_backend.py`:

```python
"""ForexFactory weekly calendar JSON — the economic *schedule* (no actuals; spec §5.1).

Unofficial public feed. Cached in-process for 30 minutes (polling it harder gains nothing:
the schedule changes rarely) behind the "forexfactory" breaker. Never raises.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

import httpx

from src.data.breaker import get_breaker
from src.data.protocols import EconScheduleItem

log = logging.getLogger(__name__)

_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
_UA = "Mozilla/5.0 (compatible; ibkr-income-system/1.0; news)"
_TTL = 30 * 60
_cache: tuple[float, list[EconScheduleItem]] | None = None
_lock = threading.Lock()


def parse_ff(rows: list[dict]) -> list[EconScheduleItem]:
    out: list[EconScheduleItem] = []
    for r in rows if isinstance(rows, list) else []:
        try:
            when = datetime.fromisoformat(str(r["date"]))
            if when.tzinfo is None:
                continue
            out.append(
                EconScheduleItem(
                    title=str(r["title"]).strip(),
                    country=str(r.get("country") or "").upper(),
                    scheduled_at=when,
                    impact=str(r.get("impact") or ""),
                    forecast=(str(r.get("forecast") or "").strip() or None),
                    previous=(str(r.get("previous") or "").strip() or None),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out


class ForexFactoryScheduleProvider:
    def this_week(self) -> list[EconScheduleItem]:
        global _cache
        with _lock:
            if _cache is not None and time.monotonic() - _cache[0] < _TTL:
                return _cache[1]
        breaker = get_breaker("forexfactory")
        if not breaker.allow():
            return _cache[1] if _cache else []
        try:
            resp = httpx.get(_URL, headers={"User-Agent": _UA}, timeout=10.0)
            resp.raise_for_status()
            items = parse_ff(resp.json())
        except Exception as exc:  # noqa: BLE001
            log.debug("forexfactory: fetch failed: %s", exc)
            breaker.record_failure()
            return _cache[1] if _cache else []
        breaker.record_success()
        with _lock:
            _cache = (time.monotonic(), items)
        return items
```

`src/data/nasdaq_backend.py` (Task 8 appends the earnings half):

```python
"""Nasdaq's public calendar API — economic actuals (and, Task 8, earnings timing).

Undocumented; needs browser-like headers. Probed 2026-10-09 (spec §5.1): ``date=D`` returns
the US releases of ET day D−1, and the ``gmt`` column holds ET HH:MM. The request date is
``et_day + date_offset_days`` (config ``news.sources.nasdaq_econ_date_offset_days``).
Never raises.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date, timedelta

import httpx

from src.data.breaker import get_breaker
from src.data.protocols import EconActualItem

log = logging.getLogger(__name__)

_BASE = "https://api.nasdaq.com/api/calendar"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
_HHMM = re.compile(r"^\d{2}:\d{2}$")


def clean_value(v: object) -> str | None:
    if v is None:
        return None
    s = html.unescape(str(v)).replace("\xa0", " ").strip()
    return None if s in ("", "-", "—", "N/A") else s


def _get(path: str, day: date) -> dict | None:
    breaker = get_breaker("nasdaq")
    if not breaker.allow():
        return None
    try:
        resp = httpx.get(f"{_BASE}/{path}", params={"date": day.isoformat()}, headers=_HEADERS, timeout=12.0)
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.debug("nasdaq: %s %s failed: %s", path, day, exc)
        breaker.record_failure()
        return None
    breaker.record_success()
    return body if isinstance(body, dict) else None


def _rows(body: dict | None) -> list[dict]:
    data = (body or {}).get("data") or {}
    rows = data.get("rows") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def parse_nasdaq_econ(body: dict, et_day: date) -> list[EconActualItem]:
    out: list[EconActualItem] = []
    for r in _rows(body):
        if str(r.get("country") or "") != "United States":
            continue
        title = clean_value(r.get("eventName"))
        if not title:
            continue
        t = str(r.get("gmt") or "").strip()
        out.append(
            EconActualItem(
                title=title,
                et_day=et_day,
                et_time=t if _HHMM.match(t) else None,
                actual=clean_value(r.get("actual")),
                consensus=clean_value(r.get("consensus")),
                previous=clean_value(r.get("previous")),
            )
        )
    return out


class NasdaqEconActualsProvider:
    def __init__(self, date_offset_days: int = 1) -> None:
        self._offset = date_offset_days

    def actuals(self, et_day: date) -> list[EconActualItem]:
        body = _get("economicevents", et_day + timedelta(days=self._offset))
        return parse_nasdaq_econ(body, et_day) if body else []
```

In `src/data/factory.py`:

```python
@functools.lru_cache(maxsize=1)
def get_econ_schedule_provider() -> EconScheduleProvider:
    name = get_config().data.econ_schedule_provider
    if name == "forexfactory":
        from src.data.forexfactory_backend import ForexFactoryScheduleProvider

        return ForexFactoryScheduleProvider()
    raise ValueError(f"Unknown data.econ_schedule_provider backend: {name!r}")


@functools.lru_cache(maxsize=1)
def get_econ_actuals_provider() -> EconActualsProvider:
    cfg = get_config()
    name = cfg.data.econ_actuals_provider
    if name == "nasdaq":
        from src.data.nasdaq_backend import NasdaqEconActualsProvider

        return NasdaqEconActualsProvider(cfg.news.sources.nasdaq_econ_date_offset_days)
    raise ValueError(f"Unknown data.econ_actuals_provider backend: {name!r}")
```

(import `EconScheduleProvider`, `EconActualsProvider` from `src.data.protocols`.)

`scripts/news_probe.py`:

```python
"""Live probe of every news source — run before go-live and whenever a source looks dead.

Usage:
    python -m scripts.news_probe

Prints, per source, whether it answered and how many items it returned, and re-derives the
Nasdaq economic-calendar date offset (spec §5.1) by matching this week's past ForexFactory
events against Nasdaq's rows for date=D and date=D+1. Read-only; writes nothing.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.common.config import get_config
from src.news.text import normalize_title


def _norm(title: str) -> str:
    t = normalize_title(title)
    for suffix in (" m m", " y y", " q q", " mom", " yoy"):
        t = t.replace(suffix, "")
    return t.strip()


def infer_offset(
    ff_titles_by_day: dict[date, set[str]],
    nasdaq_titles_by_request_day: dict[date, set[str]],
    *,
    synonyms: dict[str, str],
) -> int | None:
    """The offset k such that Nasdaq's rows for date=D+k best contain ForexFactory's day-D titles."""
    scores: dict[int, int] = {}
    for day, titles in ff_titles_by_day.items():
        wanted = {synonyms.get(t, t) for t in titles}
        for k in (0, 1):
            got = nasdaq_titles_by_request_day.get(day + timedelta(days=k), set())
            scores[k] = scores.get(k, 0) + len(wanted & got)
    if not scores or max(scores.values()) == 0:
        return None
    return max(scores, key=lambda k: scores[k])


def main() -> None:
    from src.data import factory
    from src.data.nasdaq_backend import _get, parse_nasdaq_econ
    from src.news.playbook import load_playbook

    cfg = get_config()
    pb = load_playbook()
    today = date.today()

    ff = factory.get_econ_schedule_provider().this_week()
    print(f"forexfactory: {len(ff)} events this week")
    ff_by_day: dict[date, set[str]] = {}
    for e in ff:
        d = e.scheduled_at.date()
        if e.country == "USD" and d < today:
            ff_by_day.setdefault(d, set()).add(_norm(e.title))
    nd: dict[date, set[str]] = {}
    for d in sorted(ff_by_day):
        for k in (0, 1):
            body = _get("economicevents", d + timedelta(days=k))
            nd[d + timedelta(days=k)] = {_norm(r.title) for r in parse_nasdaq_econ(body or {}, d)}
    synonyms = {_norm(a): _norm(e.aliases[0]) for e in pb.entries for a in e.aliases}
    off = infer_offset(ff_by_day, nd, synonyms=synonyms)
    print(f"nasdaq econ date offset: inferred {off} (configured {cfg.news.sources.nasdaq_econ_date_offset_days})")

    for feed in cfg.news.sources.rss_feeds:
        res = factory.get_feed_provider().fetch(feed.url)
        print(f"rss {feed.name}: {len(res.items)} items")
    fh = factory.get_finnhub_client()
    print("finnhub:", "dormant (no key)" if fh is None else f"{len(fh.general_news())} general items")


if __name__ == "__main__":
    main()
```

`main()` imports `src.news.playbook`, built in Task 10; the probe's `main` is run only manually after Task 10, while `infer_offset` (tested here) has no such dependency.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_news_econ_sources.py -v` → PASS.

- [ ] **Step 5: Gate + commit**

```bash
git add src/data/forexfactory_backend.py src/data/nasdaq_backend.py src/data/factory.py src/common/config.py config/news.example.yaml scripts/news_probe.py tests/fixtures/news/ff_thisweek.json tests/fixtures/news/nasdaq_econ_2026-10-09.json tests/test_news_econ_sources.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(data): ForexFactory schedule + Nasdaq econ actuals (D+1 rule), live probe script"
```

---

### Task 8: Earnings sources + merge + release detection

**Files:**
- Modify: `src/data/nasdaq_backend.py` (earnings half), `src/data/yfinance_backend.py` (`YFinanceEarningsHistory`), `src/data/factory.py`
- Create: `src/news/earnings.py`, `tests/fixtures/news/nasdaq_earnings_2026-10-14.json`
- Test: `tests/test_news_earnings.py`

**Interfaces:**
- Produces: `parse_nasdaq_earnings(body: dict, et_day: date) -> list[EarningsItem]`, `NasdaqEarningsProvider(date_offset_days: int).on(et_day)`; `YFinanceEarningsHistory.past_report_dates(symbol: str, limit: int = 8) -> list[date]`; factory `get_earnings_calendar_provider()`, `get_earnings_history()`; `src.news.earnings.merge_earnings(nasdaq: list[EarningsItem], finnhub: list[EarningsItem], yf_next: dict[str, date]) -> list[EarningsItem]`, `upsert_earnings(items: list[EarningsItem], *, now: datetime) -> list[tuple[str, date]]` (returns newly released `(symbol, report_date)`).

- [ ] **Step 1: Fixture + failing test**

`tests/fixtures/news/nasdaq_earnings_2026-10-14.json` (subset of the probe):

```json
{"data": {"headers": {"time": "Time", "symbol": "Symbol"}, "rows": [
  {"lastYearRptDt": "10/15/2025", "lastYearEPS": "$1.06", "time": "time-pre-market", "symbol": "BAC", "name": "Bank of America Corporation", "marketCap": "$374,251,880,000", "fiscalQuarterEnding": "Sep/2026", "epsForecast": "$1.12", "noOfEsts": "6"},
  {"lastYearRptDt": "10/15/2025", "lastYearEPS": "$6.41", "time": "time-pre-market", "symbol": "ASML", "name": "ASML Holding N.V.", "marketCap": "$695,663,460,000", "fiscalQuarterEnding": "Sep/2026", "epsForecast": "$12.47", "noOfEsts": "3"},
  {"lastYearRptDt": "N/A", "lastYearEPS": "N/A", "time": "time-after-hours", "symbol": "LOSS", "name": "Synthetic loss maker", "marketCap": "N/A", "fiscalQuarterEnding": "Sep/2026", "epsForecast": "($0.12)", "noOfEsts": "2"},
  {"time": "time-not-supplied", "symbol": "NOTIME", "epsForecast": "", "noOfEsts": ""}
]}}
```

```python
# tests/test_news_earnings.py
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from src.data.nasdaq_backend import parse_nasdaq_earnings
from src.data.protocols import EarningsItem

FIX = Path(__file__).parent / "fixtures" / "news"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_nasdaq_earnings_timing_and_money() -> None:
    rows = {r.symbol: r for r in parse_nasdaq_earnings(json.loads((FIX / "nasdaq_earnings_2026-10-14.json").read_text()), date(2026, 10, 14))}
    assert rows["BAC"].timing == "bmo" and rows["BAC"].eps_est == 1.12
    assert rows["LOSS"].timing == "amc" and rows["LOSS"].eps_est == -0.12
    assert rows["NOTIME"].timing == "unknown" and rows["NOTIME"].eps_est is None


def test_merge_prefers_finnhub_actuals_and_nasdaq_timing() -> None:
    from src.news.earnings import merge_earnings

    nd = [EarningsItem(symbol="BAC", report_date=date(2026, 10, 14), timing="bmo", eps_est=1.12, source="nasdaq")]
    fh = [EarningsItem(symbol="BAC", report_date=date(2026, 10, 14), timing="unknown", eps_est=1.10, eps_actual=1.20, rev_est=27e9, rev_actual=27.5e9, source="finnhub")]
    merged = {(m.symbol, m.report_date): m for m in merge_earnings(nd, fh, {"NVDA": date(2026, 11, 18)})}
    bac = merged[("BAC", date(2026, 10, 14))]
    assert bac.timing == "bmo" and bac.eps_est == 1.12 and bac.eps_actual == 1.20 and bac.rev_actual == 27.5e9
    assert ("NVDA", date(2026, 11, 18)) in merged


def test_upsert_reports_each_release_once(news_db) -> None:
    from src.news.earnings import upsert_earnings

    sched = EarningsItem(symbol="BAC", report_date=date(2026, 10, 14), timing="bmo", eps_est=1.12)
    assert upsert_earnings([sched], now=NOW) == []
    released = sched.model_copy(update={"eps_actual": 1.2})
    assert upsert_earnings([released], now=NOW) == [("BAC", date(2026, 10, 14))]
    assert upsert_earnings([released], now=NOW) == []
```

- [ ] **Step 2: Run to fail** — `.venv/bin/python -m pytest tests/test_news_earnings.py -v` → FAIL.

- [ ] **Step 3: Implement**

Append to `src/data/nasdaq_backend.py`:

```python
from src.data.protocols import EarningsItem  # noqa: E402  (add to the top import block instead)

_TIMING = {"time-pre-market": "bmo", "time-after-hours": "amc"}


def _money(v: object) -> float | None:
    s = clean_value(v)
    if s is None:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace("$", "").replace(",", "")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def parse_nasdaq_earnings(body: dict, et_day: date) -> list[EarningsItem]:
    out: list[EarningsItem] = []
    for r in _rows(body):
        sym = clean_value(r.get("symbol"))
        if not sym:
            continue
        out.append(
            EarningsItem(
                symbol=sym.upper(),
                report_date=et_day,
                timing=_TIMING.get(str(r.get("time") or ""), "unknown"),
                eps_est=_money(r.get("epsForecast")),
                source="nasdaq",
            )
        )
    return out


class NasdaqEarningsProvider:
    def __init__(self, date_offset_days: int = 0) -> None:
        self._offset = date_offset_days

    def on(self, et_day: date) -> list[EarningsItem]:
        body = _get("earnings", et_day + timedelta(days=self._offset))
        return parse_nasdaq_earnings(body, et_day) if body else []
```

(Move the `EarningsItem` import into the module's top import line; the comment above is only to show the dependency.)

Append to `src/data/yfinance_backend.py`:

```python
class YFinanceEarningsHistory:
    """Past earnings report dates (for the 'last N post-earnings moves' fact, spec §6.1)."""

    def past_report_dates(self, symbol: str, limit: int = 8) -> list[date]:
        try:
            df = yf.Ticker(symbol.upper()).get_earnings_dates(limit=limit + 4)
        except Exception:
            return []
        if df is None or df.empty:
            return []
        today = datetime.now(UTC).date()
        days = sorted({ts.date() for ts in df.index if ts.date() <= today}, reverse=True)
        return days[:limit]
```

(add `from datetime import UTC, date, datetime` to its imports.)

In `src/data/factory.py`:

```python
@functools.lru_cache(maxsize=1)
def get_earnings_calendar_provider() -> EarningsCalendarProvider:
    cfg = get_config()
    name = cfg.data.earnings_calendar_provider
    if name == "nasdaq":
        from src.data.nasdaq_backend import NasdaqEarningsProvider

        return NasdaqEarningsProvider(cfg.news.sources.nasdaq_earnings_date_offset_days)
    raise ValueError(f"Unknown data.earnings_calendar_provider backend: {name!r}")


@functools.lru_cache(maxsize=1)
def get_earnings_history():  # -> YFinanceEarningsHistory
    from src.data.yfinance_backend import YFinanceEarningsHistory

    return YFinanceEarningsHistory()
```

`src/news/earnings.py`:

```python
"""Earnings calendar: merge three sources, persist, and report each release exactly once."""

from __future__ import annotations

from datetime import date, datetime

from src.data.protocols import EarningsItem
from src.news.store.models import EarningsEventRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session


def merge_earnings(
    nasdaq: list[EarningsItem], finnhub: list[EarningsItem], yf_next: dict[str, date]
) -> list[EarningsItem]:
    """Nasdaq wins timing and consensus EPS; Finnhub wins actuals and revenue; yfinance only
    supplies a date when neither calendar lists the symbol."""
    merged: dict[tuple[str, date], EarningsItem] = {}
    for it in finnhub:
        merged[(it.symbol, it.report_date)] = it
    for it in nasdaq:
        key = (it.symbol, it.report_date)
        base = merged.get(key)
        if base is None:
            merged[key] = it
            continue
        merged[key] = base.model_copy(
            update={
                "timing": it.timing if it.timing != "unknown" else base.timing,
                "eps_est": it.eps_est if it.eps_est is not None else base.eps_est,
                "source": "nasdaq+finnhub",
            }
        )
    listed = {s for s, _ in merged}
    for sym, d in yf_next.items():
        if sym not in listed:
            merged[(sym, d)] = EarningsItem(symbol=sym, report_date=d, source="yfinance")
    return list(merged.values())


def upsert_earnings(items: list[EarningsItem], *, now: datetime) -> list[tuple[str, date]]:
    released: list[tuple[str, date]] = []
    now_n = naive_utc(now)
    with news_session() as s:
        for it in items:
            row = s.get(EarningsEventRow, (it.symbol, it.report_date))
            if row is None:
                row = EarningsEventRow(symbol=it.symbol, report_date=it.report_date)
                s.add(row)
            if it.timing != "unknown":
                row.timing = it.timing
            for f in ("eps_est", "eps_actual", "rev_est", "rev_actual"):
                v = getattr(it, f)
                if v is not None:
                    setattr(row, f, v)
            if row.eps_actual is not None and row.status != "released":
                row.status = "released"
                row.released_seen_at = now_n
                released.append((it.symbol, it.report_date))
    return released
```

Note: `EarningsEventRow`'s `timing`/`status` defaults are applied by SQLAlchemy at flush, so set them explicitly when constructing: `EarningsEventRow(symbol=…, report_date=…, timing="unknown", status="scheduled", alerted=False)`.

- [ ] **Step 4: Run tests** → PASS.

- [ ] **Step 5: Gate + commit**

```bash
git add src/data/nasdaq_backend.py src/data/yfinance_backend.py src/data/factory.py src/news/earnings.py tests/fixtures/news/nasdaq_earnings_2026-10-14.json tests/test_news_earnings.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): earnings calendar — Nasdaq timing, Finnhub actuals, yfinance fallback, release detection"
```

---

### Task 9: Intraday price provider + tape

**Files:**
- Modify: `src/data/yfinance_backend.py`, `src/data/factory.py`
- Create: `src/news/tape.py`
- Test: `tests/test_news_tape.py`

**Interfaces:**
- Produces: `YFinanceIntradayProvider.get_intraday(symbol, *, interval="1m", days=1) -> pd.DataFrame` (tz-aware index, includes pre/post); factory `get_intraday_price_provider()`.
- Produces (`src.news.tape`): `Quote(BaseModel)`: `symbol: str`, `last: float | None`, `prev_close: float | None`, `change_pct: float | None`; `prev_close_from(df: pd.DataFrame, today: date) -> float | None`; `quote(symbol: str, *, today: date | None = None) -> Quote`; `tape(symbols: list[str], *, today: date | None = None) -> dict[str, Quote]`.

- [ ] **Step 1: Failing test**

```python
# tests/test_news_tape.py
from __future__ import annotations

from datetime import date

import pandas as pd

from src.news import tape


def _daily(dates, closes):
    return pd.DataFrame({"Close": closes}, index=pd.DatetimeIndex(pd.to_datetime(dates)))


def test_prev_close_skips_todays_forming_bar() -> None:
    df = _daily(["2026-10-07", "2026-10-08", "2026-10-09"], [100.0, 102.0, 99.0])
    assert tape.prev_close_from(df, date(2026, 10, 9)) == 102.0
    assert tape.prev_close_from(df, date(2026, 10, 10)) == 99.0
    assert tape.prev_close_from(pd.DataFrame(), date(2026, 10, 9)) is None


def test_quote_change_pct(monkeypatch) -> None:
    class P:
        def get_last_price(self, s):
            return 97.92

        def get_ohlcv(self, s, lookback_days=10):
            return _daily(["2026-10-08", "2026-10-09"], [102.0, 98.0])

    monkeypatch.setattr(tape, "get_price_provider", lambda: P())
    q = tape.quote("SPY", today=date(2026, 10, 9))
    assert q.prev_close == 102.0 and round(q.change_pct, 2) == -4.0


def test_quote_degrades_to_none(monkeypatch) -> None:
    class P:
        def get_last_price(self, s):
            return None

        def get_ohlcv(self, s, lookback_days=10):
            return pd.DataFrame()

    monkeypatch.setattr(tape, "get_price_provider", lambda: P())
    q = tape.quote("ZZZ", today=date(2026, 10, 9))
    assert q.last is None and q.change_pct is None
```

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement**

Append to `src/data/yfinance_backend.py`:

```python
class YFinanceIntradayProvider:
    """``IntradayPriceProvider``: 1-minute bars incl. pre/post market. yfinance futures/index
    quotes can lag ~10 min (spec §6.4) — callers window on bar timestamps, never wall clock."""

    def get_intraday(self, symbol: str, *, interval: str = "1m", days: int = 1) -> pd.DataFrame:
        breaker = get_breaker("yfinance_intraday")
        if not breaker.allow():
            return pd.DataFrame()
        try:
            df = yf.Ticker(symbol).history(period=f"{max(1, days)}d", interval=interval, prepost=True)
        except Exception:
            breaker.record_failure()
            return pd.DataFrame()
        breaker.record_success()
        return df if df is not None else pd.DataFrame()
```

Factory:

```python
@functools.lru_cache(maxsize=1)
def get_intraday_price_provider() -> IntradayPriceProvider:
    name = get_config().data.intraday_price_provider
    if name == "yfinance":
        from src.data.yfinance_backend import YFinanceIntradayProvider

        return YFinanceIntradayProvider()
    raise ValueError(f"Unknown data.intraday_price_provider backend: {name!r}")
```

`src/news/tape.py`:

```python
"""Index/ticker quotes for alerts and digests. Deterministic; reads src/data only."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel

from src.common.market_hours import today_et
from src.data.factory import get_price_provider


class Quote(BaseModel):
    symbol: str
    last: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None


def prev_close_from(df: pd.DataFrame, today: date) -> float | None:
    if df is None or df.empty or "Close" not in df:
        return None
    closes = df["Close"].dropna()
    if closes.empty:
        return None
    last_day = pd.Timestamp(closes.index[-1]).date()
    if last_day >= today:
        return float(closes.iloc[-2]) if len(closes) >= 2 else None
    return float(closes.iloc[-1])


def quote(symbol: str, *, today: date | None = None) -> Quote:
    p = get_price_provider()
    day = today or today_et()
    try:
        last = p.get_last_price(symbol)
    except Exception:
        last = None
    try:
        prev = prev_close_from(p.get_ohlcv(symbol, lookback_days=10), day)
    except Exception:
        prev = None
    chg = (last / prev - 1) * 100 if last is not None and prev else None
    return Quote(symbol=symbol, last=last, prev_close=prev, change_pct=chg)


def tape(symbols: list[str], *, today: date | None = None) -> dict[str, Quote]:
    return {s: quote(s, today=today) for s in symbols}
```

- [ ] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/data/yfinance_backend.py src/data/factory.py src/news/tape.py tests/test_news_tape.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): intraday price provider and tape quotes"
```

---

### Task 10: Playbook (📘 textbook implications)

**Files:**
- Create: `config/news_playbook.yaml`, `src/news/playbook.py`
- Test: `tests/test_news_playbook.py`

**Interfaces:**
- Produces: `ASSETS = ("stocks", "bonds", "dollar", "gold", "oil", "vol")`; `Direction = Literal["up", "down", "flat"]`; `PlaybookEntry(BaseModel)`: `key`, `aliases: list[str]`, `tolerance: float`, `inverse: bool = False`, `hot: dict[str, Direction]`, `cold: dict[str, Direction]`, `rationale_hot: str`, `rationale_cold: str`; `Playbook(entries: list[PlaybookEntry])` with `.match(title: str) -> PlaybookEntry | None`, `.priority(key: str) -> int` (lower = more important); `load_playbook(path: Path | None = None) -> Playbook` (cached); `norm_event_title(title: str) -> str`; `parse_value(s: str | None) -> float | None`; `surprise_dir(entry, actual: str | None, expected: str | None) -> Literal["hot", "cold", "inline"] | None`; `PlaybookPrior(BaseModel)`: `key`, `direction`, `arrows: dict[str, str]` (emoji), `rationale: str`; `prior_for(entry, direction) -> PlaybookPrior | None` (None for `inline`); `ARROW = {"up": "🟢", "down": "🔴", "flat": "⚪"}`.

- [ ] **Step 1: Failing test**

```python
# tests/test_news_playbook.py
from __future__ import annotations

import pytest

from src.news import playbook as pb


def test_titles_from_both_sources_map_to_one_key() -> None:
    p = pb.load_playbook()
    assert p.match("Unemployment Claims").key == "jobless_claims"  # ForexFactory
    assert p.match("Initial Jobless Claims").key == "jobless_claims"  # Nasdaq
    assert p.match("CPI m/m").key == "cpi" and p.match("CPI (YoY)").key == "cpi"
    assert p.match("Core CPI m/m").key == "core_cpi"
    assert p.match("Non-Farm Employment Change").key == "nfp"
    assert p.match("Fed Waller Speaks") is None


def test_priority_orders_cpi_before_core() -> None:
    p = pb.load_playbook()
    assert p.priority("fomc_rate") < p.priority("cpi") < p.priority("core_cpi")


@pytest.mark.parametrize(
    "raw, val",
    [("0.4%", 0.4), ("1,716K", 1_716_000.0), ("197K", 197_000.0), ("8.28B", 8.28e9), ("-3.186M", -3_186_000.0),
     ("(0.2)%", -0.2), ("&nbsp;", None), ("", None), (None, None), ("abc", None), ("5.300%", 5.3)],
)
def test_parse_value(raw, val) -> None:
    assert pb.parse_value(raw) == val


def test_surprise_direction_incl_inverse() -> None:
    p = pb.load_playbook()
    cpi = p.match("CPI m/m")
    assert pb.surprise_dir(cpi, "0.4%", "0.3%") == "hot"
    assert pb.surprise_dir(cpi, "0.3%", "0.3%") == "inline"
    assert pb.surprise_dir(cpi, "0.2%", "0.3%") == "cold"
    claims = p.match("Initial Jobless Claims")
    assert pb.surprise_dir(claims, "180K", "200K") == "hot"  # fewer claims = stronger economy
    assert pb.surprise_dir(claims, "230K", "200K") == "cold"
    assert pb.surprise_dir(cpi, None, "0.3%") is None


def test_prior_arrows() -> None:
    p = pb.load_playbook()
    prior = pb.prior_for(p.match("CPI m/m"), "hot")
    assert prior.arrows["stocks"] == "🔴" and prior.arrows["bonds"] == "🔴" and prior.arrows["dollar"] == "🟢"
    assert set(prior.arrows) == set(pb.ASSETS)
    assert pb.prior_for(p.match("CPI m/m"), "inline") is None


def test_every_entry_is_complete() -> None:
    for e in pb.load_playbook().entries:
        assert set(e.hot) == set(pb.ASSETS) and set(e.cold) == set(pb.ASSETS), e.key
        assert e.tolerance > 0 and e.aliases and e.rationale_hot and e.rationale_cold
```

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement**

`config/news_playbook.yaml` (committed reference data — order = priority; bonds are **price**: yields up ⇒ `down`):

```yaml
# 📘 Textbook first-reaction priors per US release (spec §6.3). A PRIOR, never the outcome:
# cards always show it beside the measured 📈 reaction, and the 🧠 read explains gaps.
# hot = stronger/hotter than expected (for `inverse: true` keys, a LOWER number is "hot").
# Directions per asset: up | down | flat. Bonds = bond PRICE (yields up => down).
entries:
  - key: fomc_rate
    aliases: ["Federal Funds Rate", "Fed Interest Rate Decision", "FOMC Statement", "Interest Rate Decision"]
    tolerance: 0.01
    hot:  {stocks: down, bonds: down, dollar: up,   gold: down, oil: down, vol: up}
    cold: {stocks: up,   bonds: up,   dollar: down, gold: up,   oil: up,   vol: down}
    rationale_hot: "Tighter-than-expected Fed: higher discount rates weigh on equities and bonds."
    rationale_cold: "Easier-than-expected Fed: lower rates lift risk assets and bonds."
  - key: cpi
    aliases: ["CPI", "Consumer Price Index", "Inflation Rate"]
    tolerance: 0.05
    hot:  {stocks: down, bonds: down, dollar: up,   gold: flat, oil: flat, vol: up}
    cold: {stocks: up,   bonds: up,   dollar: down, gold: flat, oil: flat, vol: down}
    rationale_hot: "Hotter inflation pushes rate-cut odds out and yields up."
    rationale_cold: "Cooler inflation pulls rate-cut odds in and yields down."
  - key: core_cpi
    aliases: ["Core CPI", "Core Inflation Rate"]
    tolerance: 0.05
    hot:  {stocks: down, bonds: down, dollar: up,   gold: flat, oil: flat, vol: up}
    cold: {stocks: up,   bonds: up,   dollar: down, gold: flat, oil: flat, vol: down}
    rationale_hot: "Sticky core inflation is what the Fed targets; fewer cuts priced."
    rationale_cold: "Core cooling gives the Fed room to ease."
  - key: nfp
    aliases: ["Non-Farm Employment Change", "Nonfarm Payrolls", "Non Farm Payrolls"]
    tolerance: 25000
    hot:  {stocks: flat, bonds: down, dollar: up,   gold: down, oil: up,   vol: flat}
    cold: {stocks: flat, bonds: up,   dollar: down, gold: up,   oil: down, vol: up}
    rationale_hot: "Strong hiring: growth is fine but fewer cuts; stocks pulled both ways."
    rationale_cold: "Weak hiring: cuts come sooner but growth fears rise."
  - key: core_pce
    aliases: ["Core PCE Price Index", "Core PCE Prices"]
    tolerance: 0.05
    hot:  {stocks: down, bonds: down, dollar: up,   gold: flat, oil: flat, vol: up}
    cold: {stocks: up,   bonds: up,   dollar: down, gold: flat, oil: flat, vol: down}
    rationale_hot: "The Fed's preferred gauge running hot keeps policy tight."
    rationale_cold: "The Fed's preferred gauge cooling supports easing."
  - key: pce
    aliases: ["PCE Price Index", "PCE Prices"]
    tolerance: 0.05
    hot:  {stocks: down, bonds: down, dollar: up,   gold: flat, oil: flat, vol: up}
    cold: {stocks: up,   bonds: up,   dollar: down, gold: flat, oil: flat, vol: down}
    rationale_hot: "Headline PCE hot: inflation pressure persists."
    rationale_cold: "Headline PCE cool: inflation pressure easing."
  - key: unemployment
    aliases: ["Unemployment Rate"]
    tolerance: 0.05
    inverse: true
    hot:  {stocks: flat, bonds: down, dollar: up,   gold: down, oil: up,   vol: flat}
    cold: {stocks: down, bonds: up,   dollar: down, gold: up,   oil: down, vol: up}
    rationale_hot: "Lower unemployment: tight labour market, fewer cuts."
    rationale_cold: "Rising unemployment: slowdown risk, cuts sooner."
  - key: avg_hourly_earnings
    aliases: ["Average Hourly Earnings"]
    tolerance: 0.05
    hot:  {stocks: down, bonds: down, dollar: up,   gold: flat, oil: flat, vol: up}
    cold: {stocks: up,   bonds: up,   dollar: down, gold: flat, oil: flat, vol: down}
    rationale_hot: "Wage growth hot: services inflation risk."
    rationale_cold: "Wage growth cooling: less inflation pressure."
  - key: ppi
    aliases: ["PPI", "Producer Price Index", "Core PPI"]
    tolerance: 0.1
    hot:  {stocks: down, bonds: down, dollar: up,   gold: flat, oil: flat, vol: up}
    cold: {stocks: up,   bonds: up,   dollar: down, gold: flat, oil: flat, vol: down}
    rationale_hot: "Pipeline inflation building at producers."
    rationale_cold: "Pipeline inflation easing at producers."
  - key: gdp
    aliases: ["Advance GDP", "Prelim GDP", "Final GDP", "GDP", "GDP Growth Rate"]
    tolerance: 0.2
    hot:  {stocks: up,   bonds: down, dollar: up,   gold: flat, oil: up,   vol: down}
    cold: {stocks: down, bonds: up,   dollar: down, gold: flat, oil: down, vol: up}
    rationale_hot: "Faster growth supports earnings; yields drift up."
    rationale_cold: "Slower growth raises recession odds."
  - key: retail_sales
    aliases: ["Retail Sales", "Core Retail Sales"]
    tolerance: 0.2
    hot:  {stocks: up,   bonds: down, dollar: up,   gold: flat, oil: up,   vol: down}
    cold: {stocks: down, bonds: up,   dollar: down, gold: flat, oil: down, vol: up}
    rationale_hot: "Consumer spending strong."
    rationale_cold: "Consumer spending weakening."
  - key: ism_manufacturing
    aliases: ["ISM Manufacturing PMI"]
    tolerance: 0.5
    hot:  {stocks: up,   bonds: down, dollar: up,   gold: flat, oil: up,   vol: down}
    cold: {stocks: down, bonds: up,   dollar: down, gold: flat, oil: down, vol: up}
    rationale_hot: "Factory activity expanding faster than expected."
    rationale_cold: "Factory activity softer than expected."
  - key: ism_services
    aliases: ["ISM Services PMI", "ISM Non-Manufacturing PMI"]
    tolerance: 0.5
    hot:  {stocks: up,   bonds: down, dollar: up,   gold: flat, oil: flat, vol: down}
    cold: {stocks: down, bonds: up,   dollar: down, gold: flat, oil: flat, vol: up}
    rationale_hot: "Services (most of the economy) running hot."
    rationale_cold: "Services activity cooling."
  - key: jobless_claims
    aliases: ["Unemployment Claims", "Initial Jobless Claims"]
    tolerance: 8000
    inverse: true
    hot:  {stocks: flat, bonds: down, dollar: up,   gold: flat, oil: flat, vol: flat}
    cold: {stocks: down, bonds: up,   dollar: down, gold: up,   oil: flat, vol: up}
    rationale_hot: "Fewer layoffs than expected: labour market holding."
    rationale_cold: "Layoffs picking up: early slowdown signal."
  - key: jolts
    aliases: ["JOLTS Job Openings", "JOLTs Job Openings"]
    tolerance: 150000
    hot:  {stocks: flat, bonds: down, dollar: up,   gold: flat, oil: flat, vol: flat}
    cold: {stocks: flat, bonds: up,   dollar: down, gold: flat, oil: flat, vol: flat}
    rationale_hot: "Labour demand firm."
    rationale_cold: "Labour demand cooling."
  - key: umich_sentiment
    aliases: ["Prelim UoM Consumer Sentiment", "Revised UoM Consumer Sentiment", "Michigan Consumer Sentiment"]
    tolerance: 1.5
    hot:  {stocks: up,   bonds: flat, dollar: flat, gold: flat, oil: flat, vol: down}
    cold: {stocks: down, bonds: flat, dollar: flat, gold: flat, oil: flat, vol: up}
    rationale_hot: "Consumers more upbeat than expected."
    rationale_cold: "Consumers gloomier than expected."
```

`src/news/playbook.py`:

```python
"""📘 Playbook — textbook first-reaction priors per US release (spec §6.3). Deterministic.

Reads committed reference data from config/news_playbook.yaml (not an operator-private file).
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from src.common.config import CONFIG_DIR

ASSETS = ("stocks", "bonds", "dollar", "gold", "oil", "vol")
Direction = Literal["up", "down", "flat"]
Surprise = Literal["hot", "cold", "inline"]
ARROW = {"up": "🟢", "down": "🔴", "flat": "⚪"}

_PERIOD = re.compile(r"\b(m/m|y/y|q/q|mom|yoy|qoq)\b|\((mom|yoy|qoq)\)", re.I)
_MULT = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def norm_event_title(title: str) -> str:
    t = _PERIOD.sub(" ", title.lower())
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return " ".join(t.split())


class PlaybookEntry(BaseModel):
    key: str
    aliases: list[str]
    tolerance: float
    inverse: bool = False
    hot: dict[str, Direction]
    cold: dict[str, Direction]
    rationale_hot: str
    rationale_cold: str


class PlaybookPrior(BaseModel):
    key: str
    direction: Literal["hot", "cold"]
    arrows: dict[str, str]
    rationale: str


class Playbook:
    def __init__(self, entries: list[PlaybookEntry]) -> None:
        self.entries = entries
        self._by_alias = {norm_event_title(a): e for e in entries for a in e.aliases}
        self._rank = {e.key: i for i, e in enumerate(entries)}

    def match(self, title: str) -> PlaybookEntry | None:
        return self._by_alias.get(norm_event_title(title))

    def priority(self, key: str) -> int:
        return self._rank.get(key, len(self._rank))


@functools.lru_cache(maxsize=1)
def load_playbook(path: Path | None = None) -> Playbook:
    p = path or (CONFIG_DIR / "news_playbook.yaml")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Playbook([PlaybookEntry.model_validate(e) for e in raw.get("entries", [])])


def parse_value(s: str | None) -> float | None:
    if s is None:
        return None
    t = s.replace("&nbsp;", "").replace("\xa0", "").replace(",", "").replace("$", "").strip()
    if not t:
        return None
    neg = False
    if t.startswith("(") and ")" in t:
        neg, t = True, t.replace("(", "").replace(")", "")
    t = t.rstrip("%").strip()
    mult = 1.0
    if t and t[-1].upper() in _MULT:
        mult, t = _MULT[t[-1].upper()], t[:-1]
    try:
        v = float(t) * mult
    except ValueError:
        return None
    return -v if neg else v


def surprise_dir(entry: PlaybookEntry, actual: str | None, expected: str | None) -> Surprise | None:
    a, e = parse_value(actual), parse_value(expected)
    if a is None or e is None:
        return None
    diff = (e - a) if entry.inverse else (a - e)
    if diff > entry.tolerance:
        return "hot"
    if diff < -entry.tolerance:
        return "cold"
    return "inline"


def prior_for(entry: PlaybookEntry, direction: Surprise | None) -> PlaybookPrior | None:
    if direction not in ("hot", "cold"):
        return None
    dirs = entry.hot if direction == "hot" else entry.cold
    return PlaybookPrior(
        key=entry.key,
        direction=direction,
        arrows={a: ARROW[dirs[a]] for a in ASSETS},
        rationale=entry.rationale_hot if direction == "hot" else entry.rationale_cold,
    )
```

Note on the `(0.2)%` case: `t.startswith("(")` handles it after `$`/`,` stripping; the `%` sits outside the parentheses, so remove parentheses before stripping `%` (the code does).

- [ ] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add config/news_playbook.yaml src/news/playbook.py tests/test_news_playbook.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): 📘 playbook — release aliases, value parser, surprise direction, priors"
```

---

### Task 11: Aliases, read views, collectors

**Files:**
- Create: `src/news/aliases.py`, `src/news/schemas.py`, `src/news/collectors.py`
- Modify: `src/news/store/queries.py` (view readers)
- Test: `tests/test_news_collectors.py`

**Interfaces:**
- Produces (`src.news.schemas`, read views — later tasks extend this file):
  - `ItemView`: `title, url, source, source_domain, published_at: datetime | None, summary, image_url, det_sentiment: float | None`
  - `ClusterView`: `id, headline, category, first_seen: datetime, last_seen: datetime, source_count, source_domains: list[str], tickers: list[str], tags: list[str], topic_class, items: list[ItemView]`
  - `EconEventView`: `event_key, title, playbook_key: str | None, scheduled_at: datetime (aware UTC), impact, forecast, previous, consensus, actual, surprise_dir: str | None`
  - `EarningsView`: `symbol, report_date: date, timing, eps_est, eps_actual, rev_est, rev_actual, status`
- Produces (`src.news.store.queries`): `cluster_view(s, cid: int, *, max_items: int = 6) -> ClusterView | None`, `clusters_since(s, since: datetime, *, category: str | None = None, symbol: str | None = None, limit: int = 50) -> list[ClusterView]`, `econ_events_between(s, start: datetime, end: datetime) -> list[EconEventView]`, `earnings_between(s, start: date, end: date, symbols: set[str] | None = None) -> list[EarningsView]`.
- Produces (`src.news.aliases`): `load_aliases(symbols: list[str], *, overrides: dict[str, list[str]], now: datetime) -> dict[str, list[str]]`, `clean_company_name(name: str) -> str | None`.
- Produces (`src.news.collectors`): `watch_symbols() -> list[str]`, `held_positions() -> list[PositionSnapshot]`, `held_underlyings() -> set[str]`, `universe_lists(symbol: str) -> list[str]`, `class Collector` with `alias_index(now) -> AliasIndex`, `collect_rss(now) -> int`, `collect_macro(now) -> int`, `collect_ticker_batch(now, *, batch: int) -> int`, `collect_symbol(symbol, now) -> IngestResult`, `refresh_econ_schedule(now) -> int`, `refresh_econ_actuals(now) -> list[str]` (event keys newly released), `refresh_earnings(now, *, days: int = 14) -> list[tuple[str, date]]`, `in_fast_econ_window(now) -> bool`.

- [x] **Step 1: Failing test**

```python
# tests/test_news_collectors.py
from __future__ import annotations

from datetime import UTC, date, datetime

from src.data.protocols import EconActualItem, EconScheduleItem, FeedFetch, NewsItem


class FakeFeeds:
    def fetch(self, url, *, etag=None, last_modified=None, limit=50):
        if etag == "e1":
            return FeedFetch(items=[], etag="e1", not_modified=True)
        return FeedFetch(items=[NewsItem(title="Fed holds rates steady", url="https://fed.gov/a")], etag="e1")


class FakeSearch:
    def search(self, query, *, days=7, limit=10):
        return [NewsItem(title=f"{query} headline", url=f"https://g.com/{abs(hash(query))}")]


def _patch(monkeypatch, *, schedule=(), actuals=()):
    import src.news.collectors as c

    monkeypatch.setattr(c, "get_feed_provider", lambda: FakeFeeds())
    monkeypatch.setattr(c, "get_news_search_provider", lambda: FakeSearch())
    monkeypatch.setattr(c, "get_news_provider", lambda: type("Y", (), {"get_headlines": lambda self, s, limit=50: []})())
    monkeypatch.setattr(c, "get_finnhub_client", lambda: None)
    monkeypatch.setattr(c, "watch_symbols", lambda: ["NVDA", "AAPL"])
    monkeypatch.setattr(c, "load_aliases", lambda symbols, overrides, now: {"NVDA": ["Nvidia"]})
    monkeypatch.setattr(c, "get_econ_schedule_provider", lambda: type("S", (), {"this_week": lambda self: list(schedule)})())
    monkeypatch.setattr(c, "get_econ_actuals_provider", lambda: type("A", (), {"actuals": lambda self, d: list(actuals)})())


NOW = datetime(2026, 10, 8, 12, 31, tzinfo=UTC)  # 08:31 ET


def test_rss_uses_conditional_get_state(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news.collectors import Collector

    _patch(monkeypatch)
    col = Collector(get_config().news)
    assert col.collect_rss(NOW) >= 1
    assert col.collect_rss(NOW) == 0  # second poll sends the stored ETag and gets 304


def test_ticker_batch_round_robins(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news.collectors import Collector

    _patch(monkeypatch)
    col = Collector(get_config().news)
    col.collect_ticker_batch(NOW, batch=1)
    col.collect_ticker_batch(NOW, batch=1)
    from src.news.store.models import NewsItemRow
    from src.news.store.session import news_session

    with news_session() as s:
        titles = {r.title for r in s.query(NewsItemRow)}
    assert {"NVDA headline", "AAPL headline"} <= titles


def test_econ_schedule_then_actual_matched_by_playbook_and_time(news_db, monkeypatch) -> None:
    from zoneinfo import ZoneInfo

    from src.common.config import get_config
    from src.news.collectors import Collector

    et = ZoneInfo("America/New_York")
    sched = [EconScheduleItem(title="Unemployment Claims", country="USD", scheduled_at=datetime(2026, 10, 8, 8, 30, tzinfo=et), impact="Medium", forecast="200K", previous="197K"),
             EconScheduleItem(title="German IP", country="EUR", scheduled_at=datetime(2026, 10, 8, 2, 0, tzinfo=et), impact="High")]
    acts = [EconActualItem(title="Initial Jobless Claims", et_day=date(2026, 10, 8), et_time="08:30", actual="197K", consensus="200K", previous="199K"),
            EconActualItem(title="Continuing Jobless Claims", et_day=date(2026, 10, 8), et_time="08:30", actual="1,716K")]
    _patch(monkeypatch, schedule=sched, actuals=acts)
    col = Collector(get_config().news)
    assert col.refresh_econ_schedule(NOW) == 1  # USD only
    released = col.refresh_econ_actuals(NOW)
    assert len(released) == 1
    from src.news.store.models import EconEventRow
    from src.news.store.session import news_session

    with news_session() as s:
        row = s.query(EconEventRow).one()
    assert row.actual == "197K" and row.playbook_key == "jobless_claims" and row.surprise_dir == "hot"
    assert col.refresh_econ_actuals(NOW) == []  # reported once


def test_fast_window(news_db, monkeypatch) -> None:
    from zoneinfo import ZoneInfo

    from src.common.config import get_config
    from src.news.collectors import Collector

    et = ZoneInfo("America/New_York")
    _patch(monkeypatch, schedule=[EconScheduleItem(title="CPI m/m", country="USD", scheduled_at=datetime(2026, 10, 8, 8, 30, tzinfo=et), impact="High", forecast="0.3%")])
    col = Collector(get_config().news)
    col.refresh_econ_schedule(NOW)
    assert col.in_fast_econ_window(datetime(2026, 10, 8, 12, 29, tzinfo=UTC))
    assert not col.in_fast_econ_window(datetime(2026, 10, 8, 13, 0, tzinfo=UTC))


def test_clean_company_name() -> None:
    from src.news.aliases import clean_company_name

    assert clean_company_name("NVIDIA Corporation") == "NVIDIA"
    assert clean_company_name("Alphabet Inc. Class A") == "Alphabet"
    assert clean_company_name("ProShares UltraPro QQQ") is None  # fund names are not useful aliases
```

- [x] **Step 2: Run to fail.**

- [x] **Step 3: Implement**

`src/news/schemas.py` (initial content):

```python
"""Schemas for the news service. Views are the read-side types; nothing passes ORM rows
across a module boundary (CLAUDE.md). Later tasks add Fact/FactSheet (13), card payloads (15)
and LLM outputs (23)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ItemView(BaseModel):
    title: str
    url: str | None = None
    source: str | None = None
    source_domain: str | None = None
    published_at: datetime | None = None
    summary: str | None = None
    image_url: str | None = None
    det_sentiment: float | None = None


class ClusterView(BaseModel):
    id: int
    headline: str
    category: str
    first_seen: datetime
    last_seen: datetime
    source_count: int
    source_domains: list[str] = Field(default_factory=list)
    tickers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    topic_class: str = "other"
    items: list[ItemView] = Field(default_factory=list)


class EconEventView(BaseModel):
    event_key: str
    title: str
    playbook_key: str | None = None
    scheduled_at: datetime
    impact: str
    forecast: str | None = None
    previous: str | None = None
    consensus: str | None = None
    actual: str | None = None
    surprise_dir: str | None = None


class EarningsView(BaseModel):
    symbol: str
    report_date: date
    timing: str = "unknown"
    eps_est: float | None = None
    eps_actual: float | None = None
    rev_est: float | None = None
    rev_actual: float | None = None
    status: str = "scheduled"
```

Append to `src/news/store/queries.py`:

```python
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.news.schemas import ClusterView, EarningsView, EconEventView, ItemView
from src.news.store.models import EarningsEventRow, EconEventRow, NewsClusterRow, NewsItemRow


def _cluster(s: Session, c: NewsClusterRow, max_items: int) -> ClusterView:
    items = s.scalars(
        select(NewsItemRow).where(NewsItemRow.cluster_id == c.id).order_by(NewsItemRow.fetched_at).limit(max_items)
    )
    return ClusterView(
        id=c.id, headline=c.headline, category=c.category,
        first_seen=aware_utc(c.first_seen), last_seen=aware_utc(c.last_seen),
        source_count=c.source_count, source_domains=list(c.source_domains or []),
        tickers=list(c.tickers or []), tags=list(c.tags or []), topic_class=c.topic_class,
        items=[
            ItemView(
                title=i.title, url=i.url, source=i.source, source_domain=i.source_domain,
                published_at=aware_utc(i.published_at) if i.published_at else None,
                summary=i.summary, image_url=i.image_url, det_sentiment=i.det_sentiment,
            )
            for i in items
        ],
    )


def cluster_view(s: Session, cid: int, *, max_items: int = 6) -> ClusterView | None:
    c = s.get(NewsClusterRow, cid)
    return None if c is None else _cluster(s, c, max_items)


def clusters_since(
    s: Session, since: datetime, *, category: str | None = None, symbol: str | None = None, limit: int = 50
) -> list[ClusterView]:
    q = select(NewsClusterRow).where(NewsClusterRow.last_seen >= naive_utc(since))
    if category:
        q = q.where(NewsClusterRow.category == category)
    rows = list(s.scalars(q.order_by(NewsClusterRow.source_count.desc(), NewsClusterRow.last_seen.desc()).limit(limit * 4)))
    if symbol:
        rows = [r for r in rows if symbol.upper() in (r.tickers or [])]
    return [_cluster(s, r, 6) for r in rows[:limit]]


def econ_view(r: EconEventRow) -> EconEventView:
    return EconEventView(
        event_key=r.event_key, title=r.title, playbook_key=r.playbook_key,
        scheduled_at=aware_utc(r.scheduled_at), impact=r.impact, forecast=r.forecast,
        previous=r.previous, consensus=r.consensus, actual=r.actual, surprise_dir=r.surprise_dir,
    )


def econ_events_between(s: Session, start: datetime, end: datetime) -> list[EconEventView]:
    rows = s.scalars(
        select(EconEventRow)
        .where(EconEventRow.scheduled_at >= naive_utc(start), EconEventRow.scheduled_at < naive_utc(end))
        .order_by(EconEventRow.scheduled_at)
    )
    return [econ_view(r) for r in rows]


def earnings_between(s: Session, start: date, end: date, symbols: set[str] | None = None) -> list[EarningsView]:
    rows = s.scalars(
        select(EarningsEventRow)
        .where(EarningsEventRow.report_date >= start, EarningsEventRow.report_date <= end)
        .order_by(EarningsEventRow.report_date, EarningsEventRow.symbol)
    )
    return [
        EarningsView(
            symbol=r.symbol, report_date=r.report_date, timing=r.timing, eps_est=r.eps_est,
            eps_actual=r.eps_actual, rev_est=r.rev_est, rev_actual=r.rev_actual, status=r.status,
        )
        for r in rows
        if symbols is None or r.symbol in symbols
    ]
```

(Merge the new imports into the file's top import block.)

`src/news/aliases.py`:

```python
"""Ticker → company-name aliases for headline tagging, cached 30 days in ticker_aliases."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from src.data.factory import get_fundamentals_provider
from src.news.store.models import TickerAliasRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session

_SUFFIX = re.compile(
    r"[,.]?\s+(inc|corp|corporation|co|company|holdings?|group|plc|ltd|limited|n\.?v|s\.?a|class [a-c]|ord|adr)\.?\b.*$",
    re.I,
)
_FUND = re.compile(r"\b(etf|trust|fund|proshares|direxion|spdr|ishares|invesco|ultra|bull|bear|2x|3x)\b", re.I)
_TTL = timedelta(days=30)


def clean_company_name(name: str) -> str | None:
    if not name or _FUND.search(name):
        return None
    t = _SUFFIX.sub("", name.strip()).strip(" ,.")
    return t if len(t) >= 3 else None


def load_aliases(symbols: list[str], *, overrides: dict[str, list[str]], now: datetime) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    now_n = naive_utc(now)
    with news_session() as s:
        for sym in symbols:
            row = s.get(TickerAliasRow, sym)
            if row is None or now_n - row.fetched_at > _TTL:
                info = get_fundamentals_provider().get_info(sym) or {}
                names = {clean_company_name(str(info.get(k) or "")) for k in ("shortName", "longName")}
                aliases = sorted(n for n in names if n)
                if row is None:
                    s.add(TickerAliasRow(symbol=sym, aliases=aliases, fetched_at=now_n))
                else:
                    row.aliases, row.fetched_at = aliases, now_n
            else:
                aliases = list(row.aliases or [])
            out[sym] = sorted(set(aliases) | set(overrides.get(sym, [])))
    return out
```

`src/news/collectors.py`:

```python
"""Poll every source into data/news.db (spec §5.1). Each method is one source, never raises
past its own boundary (sources already never raise), and is called from service loops."""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.common.books import is_spreads_underlying
from src.common.config import NewsCfg
from src.common.schemas import PositionSnapshot
from src.common.universe import effective_universe
from src.data.factory import (
    get_earnings_calendar_provider,
    get_econ_actuals_provider,
    get_econ_schedule_provider,
    get_feed_provider,
    get_finnhub_client,
    get_fundamentals_provider,
    get_news_provider,
    get_news_search_provider,
)
from src.data.protocols import NewsItem
from src.news.aliases import load_aliases
from src.news.earnings import merge_earnings, upsert_earnings
from src.news.ingest import IngestResult, ingest
from src.news.playbook import load_playbook, norm_event_title, surprise_dir
from src.news.store.models import EconEventRow, FeedStateRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from src.news.store.state import record_source_ok
from src.news.tagging import AliasIndex, build_alias_index
from src.storage.portfolio_snapshots import load_latest_portfolio_snapshot

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
_UNIVERSE_LISTS = ("indexes", "watchlist", "would_own", "actively_wheeling")


def held_positions() -> list[PositionSnapshot]:
    snap = load_latest_portfolio_snapshot()
    return list(snap.positions) if snap else []


def held_underlyings() -> set[str]:
    return {(p.underlying or p.symbol).upper() for p in held_positions() if p.position != 0}


def universe_lists(symbol: str) -> list[str]:
    u = effective_universe()
    return [name for name in _UNIVERSE_LISTS if symbol.upper() in {str(x).upper() for x in (u.get(name) or [])}]


def watch_symbols() -> list[str]:
    u = effective_universe()
    syms = {str(x).upper() for name in _UNIVERSE_LISTS for x in (u.get(name) or [])}
    syms |= held_underlyings()
    return sorted(s for s in syms if not is_spreads_underlying(s))


def _yf_items(raw: list[dict]) -> list[NewsItem]:
    from src.claude.news_context import _news_item_from_yfinance

    return [i for i in (_news_item_from_yfinance(r) for r in raw) if i is not None]


def _event_key(scheduled_at: datetime, title: str) -> str:
    return f"{scheduled_at.astimezone(UTC):%Y-%m-%dT%H:%M}|{title}"


class Collector:
    def __init__(self, cfg: NewsCfg) -> None:
        self.cfg = cfg
        self._cursor = 0
        self._alias: AliasIndex | None = None
        self._alias_at: datetime | None = None

    # -- tagging context ---------------------------------------------------------------
    def alias_index(self, now: datetime) -> AliasIndex:
        if self._alias is None or self._alias_at is None or now - self._alias_at > timedelta(hours=1):
            syms = watch_symbols()
            self._alias = build_alias_index(syms, load_aliases(syms, overrides=self.cfg.tagging.aliases, now=now))
            self._alias_at = now
        return self._alias

    def _scheduled(self, now: datetime) -> tuple[frozenset[str], tuple[str, ...]]:
        lo, hi = naive_utc(now - timedelta(days=1)), naive_utc(now + timedelta(days=1))
        with news_session() as s:
            titles = s.scalars(select(EconEventRow.title).where(EconEventRow.scheduled_at.between(lo, hi)))
            terms = tuple(sorted({norm_event_title(t) for t in titles if norm_event_title(t)}))
        from src.news.store.models import EarningsEventRow

        with news_session() as s:
            syms = frozenset(
                s.scalars(
                    select(EarningsEventRow.symbol).where(
                        EarningsEventRow.report_date.between((now - timedelta(days=1)).date(), (now + timedelta(days=1)).date())
                    )
                )
            )
        return syms, terms

    def _ingest(self, items: list[NewsItem], *, category: str, origin: str, now: datetime) -> IngestResult:
        if not items:
            return IngestResult()
        syms, terms = self._scheduled(now)
        return ingest(
            items, category=category, origin=origin, alias_index=self.alias_index(now),
            cfg=self.cfg, now=now, scheduled_symbols=syms, scheduled_terms=terms,
        )

    # -- sources -----------------------------------------------------------------------
    def collect_rss(self, now: datetime) -> int:
        total = 0
        provider = get_feed_provider()
        for feed in self.cfg.sources.rss_feeds:
            with news_session() as s:
                st = s.get(FeedStateRow, feed.url)
                etag, lm = (st.etag, st.last_modified) if st else (None, None)
            res = provider.fetch(feed.url, etag=etag, last_modified=lm)
            with news_session() as s:
                st = s.get(FeedStateRow, feed.url) or FeedStateRow(feed_url=feed.url)
                st.last_polled = naive_utc(now)
                if res.items or res.not_modified:
                    st.etag, st.last_modified, st.last_ok = res.etag, res.last_modified, naive_utc(now)
                s.merge(st)
            total += self._ingest(res.items, category=feed.category, origin="rss", now=now).new_items
        record_source_ok("rss", now)
        return total

    def collect_macro(self, now: datetime) -> int:
        total = 0
        search = get_news_search_provider()
        for q in self.cfg.sources.macro_queries:
            items = search.search(q, days=self.cfg.sources.google_news_days, limit=15)
            total += self._ingest(items, category="macro", origin="google", now=now).new_items
        fh = get_finnhub_client()
        if fh is not None:
            total += self._ingest(fh.general_news(), category="markets", origin="finnhub", now=now).new_items
        record_source_ok("macro", now)
        return total

    def collect_symbol(self, symbol: str, now: datetime) -> IngestResult:
        items: list[NewsItem] = []
        items += get_news_search_provider().search(symbol, days=self.cfg.sources.google_news_days, limit=10)
        items += _yf_items(get_news_provider().get_headlines(symbol, limit=15) or [])
        fh = get_finnhub_client()
        if fh is not None:
            items += fh.company_news(symbol, days=self.cfg.sources.google_news_days)
        return self._ingest(items, category="ticker", origin="mixed", now=now)

    def collect_ticker_batch(self, now: datetime, *, batch: int) -> int:
        syms = watch_symbols()
        if not syms:
            return 0
        total = 0
        for _ in range(min(batch, len(syms))):
            sym = syms[self._cursor % len(syms)]
            self._cursor += 1
            total += self.collect_symbol(sym, now).new_items
        record_source_ok("tickers", now)
        return total

    def ticker_batch_size(self, loop_minutes: float) -> int:
        n = len(watch_symbols())
        return max(1, math.ceil(n * loop_minutes / self.cfg.sources.ticker_round_robin_minutes))

    def refresh_econ_schedule(self, now: datetime) -> int:
        pb = load_playbook()
        n = 0
        with news_session() as s:
            for e in get_econ_schedule_provider().this_week():
                if e.country != "USD" or e.impact not in ("High", "Medium"):
                    continue
                key = _event_key(e.scheduled_at, e.title)
                row = s.get(EconEventRow, key)
                entry = pb.match(e.title)
                if row is None:
                    s.add(
                        EconEventRow(
                            event_key=key, title=e.title, playbook_key=entry.key if entry else None,
                            scheduled_at=naive_utc(e.scheduled_at), impact=e.impact,
                            forecast=e.forecast, previous=e.previous, alerted=False,
                        )
                    )
                    n += 1
                else:
                    row.forecast, row.previous, row.impact = e.forecast, e.previous, e.impact
        record_source_ok("econ_schedule", now)
        return n

    def refresh_econ_actuals(self, now: datetime) -> list[str]:
        pb = load_playbook()
        released: list[str] = []
        today = now.astimezone(ET).date()
        with news_session() as s:
            pending = list(
                s.scalars(
                    select(EconEventRow).where(
                        EconEventRow.actual.is_(None),
                        EconEventRow.scheduled_at <= naive_utc(now),
                        EconEventRow.scheduled_at >= naive_utc(now - timedelta(days=2)),
                    )
                )
            )
            days = sorted({r.scheduled_at.replace(tzinfo=UTC).astimezone(ET).date() for r in pending} | {today})
            rows_by_day = {d: get_econ_actuals_provider().actuals(d) for d in days if pending}
            for r in pending:
                et_at = r.scheduled_at.replace(tzinfo=UTC).astimezone(ET)
                for a in rows_by_day.get(et_at.date(), []):
                    if a.et_time != f"{et_at:%H:%M}" or a.actual is None:
                        continue
                    same_key = r.playbook_key and (m := pb.match(a.title)) is not None and m.key == r.playbook_key
                    same_title = norm_event_title(a.title) == norm_event_title(r.title)
                    if not (same_key or same_title):
                        continue
                    r.actual, r.consensus, r.actual_seen_at = a.actual, a.consensus, naive_utc(now)
                    entry = pb.match(r.title)
                    if entry is not None:
                        r.surprise_dir = surprise_dir(entry, a.actual, r.forecast or a.consensus)
                    released.append(r.event_key)
                    break
        record_source_ok("econ_actuals", now)
        return released

    def in_fast_econ_window(self, now: datetime) -> bool:
        before = timedelta(minutes=self.cfg.sources.econ_fast_window_before_min)
        after = timedelta(minutes=self.cfg.sources.econ_fast_window_after_min)
        with news_session() as s:
            hit = s.scalar(
                select(EconEventRow.event_key).where(
                    EconEventRow.actual.is_(None),
                    EconEventRow.scheduled_at.between(naive_utc(now - after), naive_utc(now + before)),
                )
            )
        return hit is not None

    def refresh_earnings(self, now: datetime, *, days: int = 14) -> list[tuple[str, date]]:
        syms = set(watch_symbols())
        start = now.astimezone(ET).date() - timedelta(days=1)
        end = start + timedelta(days=days)
        nd = []
        d = start
        cal = get_earnings_calendar_provider()
        while d <= end:
            if d.weekday() < 5:
                nd += [e for e in cal.on(d) if e.symbol in syms]
            d += timedelta(days=1)
        fh_rows = []
        fh = get_finnhub_client()
        if fh is not None:
            fh_rows = [e for e in fh.earnings_calendar(start, end) if e.symbol in syms]
        yf_next: dict[str, date] = {}
        from src.analytics.fundamentals import get_fundamental_stats

        for sym in syms:
            try:
                nxt = get_fundamental_stats(sym).next_earnings
            except Exception:
                nxt = None
            if nxt and start <= nxt <= end:
                yf_next[sym] = nxt
        released = upsert_earnings(merge_earnings(nd, fh_rows, yf_next), now=now)
        record_source_ok("earnings", now)
        return released
```

`src.analytics.fundamentals.get_fundamental_stats(symbol) -> FundamentalStats` is the accessor (verified 2026-10-09). Remove `get_fundamentals_provider` from `collectors.py`'s import list (only `aliases.py` uses it) so ruff passes.

- [x] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_news_collectors.py -v` → PASS.

- [x] **Step 5: Gate + commit**

```bash
git add src/news/aliases.py src/news/schemas.py src/news/collectors.py src/news/store/queries.py tests/test_news_collectors.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): collectors — RSS (conditional GET), macro + ticker round-robin, econ schedule/actuals, earnings"
```

---

### Task 12: Service skeleton, entrypoint, supervisor entry, fence tests

**Files:**
- Create: `src/news/service.py`, `scripts/run_news.py`, `tests/test_news_fence.py`
- Modify: `scripts/start.py` (`SERVICES`), `tests/test_eval_skills.py` (`_ENRICHMENT_ONLY`)
- Test: `tests/test_news_service.py`, `tests/test_news_fence.py`

**Interfaces:**
- Produces: `class NewsService(cfg: Config, *, clock: Callable[[], datetime] = utcnow)` with `async run(stop: asyncio.Event) -> None`, `async _loop(name: str, interval_s: float, fn: Callable[[datetime], object], stop: asyncio.Event) -> None`, `run_once_ingest(now) -> None` (one pass of every source; used by tests and by `/news` briefs warm-up); module `async run(stop)` entry used by the script. Later tasks add loops to `NewsService.loops()`.

- [x] **Step 1: Failing tests**

```python
# tests/test_news_service.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime


async def test_loop_survives_exceptions_and_beats_heartbeat(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news.service import NewsService
    from src.news.store import state

    svc = NewsService(get_config(), clock=lambda: datetime(2026, 10, 9, 12, tzinfo=UTC))
    calls = {"n": 0}

    def flaky(now):
        calls["n"] += 1
        raise RuntimeError("boom")

    stop = asyncio.Event()
    task = asyncio.create_task(svc._loop("flaky", 0.01, flaky, stop))
    await asyncio.sleep(0.05)
    stop.set()
    await task
    assert calls["n"] >= 2
    assert state.get_state(state.HEARTBEAT_KEY) is not None


async def test_disabled_service_idles(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news.service import NewsService

    cfg = get_config().model_copy(update={"news": get_config().news.model_copy(update={"enabled": False})})
    stop = asyncio.Event()
    stop.set()
    await NewsService(cfg).run(stop)  # returns promptly, no loops started
```

```python
# tests/test_news_fence.py
"""The news fence (spec §10). Imports parsed with ast, reusing the spreads fence's resolver."""

from __future__ import annotations

from pathlib import Path

from tests.test_spreads_fence import imported_modules

ROOT = Path(__file__).resolve().parents[1]
NEWS = sorted((ROOT / "src" / "news").rglob("*.py"))
_ROW_CLASSES = (
    "NewsItemRow(", "NewsClusterRow(", "EconEventRow(", "EarningsEventRow(", "FeedStateRow(",
    "NewsPostRow(", "AlertStateRow(", "NewsRequestRow(", "NewsStateRow(", "TickerAliasRow(",
)


def _pkg_files(*parts: str) -> list[Path]:
    return sorted((ROOT.joinpath(*parts)).rglob("*.py"))


def test_trading_path_never_imports_news() -> None:
    for pkg in (("src", "engine"), ("src", "execution"), ("src", "strategies"), ("src", "spreads")):
        for path in _pkg_files(*pkg):
            bad = [m for m in imported_modules(path) if m == "src.news" or m.startswith("src.news.")]
            assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


def test_news_never_imports_the_trading_path() -> None:
    forbidden = ("src.engine", "src.execution", "src.strategies", "src.spreads", "src.orchestrator", "src.notify.approval_service")
    for path in NEWS:
        bad = [m for m in imported_modules(path) if any(m == f or m.startswith(f + ".") for f in forbidden)]
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


def test_only_src_news_constructs_news_rows() -> None:
    for path in (ROOT / "src").rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[:2] == ("src", "news"):
            continue
        text = path.read_text(encoding="utf-8")
        for cls in _ROW_CLASSES:
            assert cls not in text, f"{rel} constructs {cls[:-1]} — only src/news/ may write news.db"


def test_notify_imports_only_the_brief_queue() -> None:
    for path in _pkg_files("src", "notify"):
        mods = [m for m in imported_modules(path) if m == "src.news" or m.startswith("src.news.")]
        bad = [m for m in mods if not (m == "src.news.briefs" or m.startswith("src.news.briefs."))]
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


def test_api_never_imports_the_rw_engine() -> None:
    for path in _pkg_files("src", "api"):
        bad = [m for m in imported_modules(path) if m.startswith("src.news.store.session")]
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"
```

In `tests/test_eval_skills.py` add `"src.news",` to `_ENRICHMENT_ONLY` (with a comment `# News service (2026-10-09 spec §10.5)`).

- [x] **Step 2: Run to fail** — service module missing.

- [x] **Step 3: Implement**

`src/news/service.py`:

```python
"""The news process: asyncio loops over blocking source/LLM work run in threads.

Every loop body is wrapped — an exception is logged and the loop continues (spec §11) —
and every completed iteration beats the heartbeat the watchdog reads (Task 33).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from src.common.config import Config
from src.news.collectors import Collector
from src.news.store.session import init_news_db
from src.news.store.state import touch_heartbeat

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(UTC)


class NewsService:
    def __init__(self, cfg: Config, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.cfg = cfg
        self.ncfg = cfg.news
        self.clock = clock
        self.collector = Collector(cfg.news)

    async def _loop(
        self, name: str, interval_s: float, fn: Callable[[datetime], object], stop: asyncio.Event
    ) -> None:
        while not stop.is_set():
            now = self.clock()
            try:
                result = fn(now)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                log.exception("news loop %s failed", name)
            try:
                await asyncio.to_thread(touch_heartbeat, self.clock())
            except Exception:
                log.debug("heartbeat write failed", exc_info=True)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_s)
            except TimeoutError:
                pass

    def _threaded(self, fn: Callable[[datetime], object]) -> Callable[[datetime], object]:
        async def run(now: datetime) -> object:
            return await asyncio.to_thread(fn, now)

        return run

    def loops(self) -> list[tuple[str, float, Callable[[datetime], object]]]:
        s = self.ncfg.sources
        return [
            ("rss", s.rss_poll_minutes * 60, self._threaded(self.collector.collect_rss)),
            ("macro", s.macro_poll_minutes * 60, self._threaded(self.collector.collect_macro)),
            ("tickers", 60, self._threaded(lambda now: self.collector.collect_ticker_batch(now, batch=self.collector.ticker_batch_size(1)))),
            ("econ_schedule", s.econ_poll_minutes * 60, self._threaded(self.collector.refresh_econ_schedule)),
            ("earnings", s.earnings_poll_hours * 3600, self._threaded(self.collector.refresh_earnings)),
        ]

    def run_once_ingest(self, now: datetime) -> None:
        self.collector.refresh_econ_schedule(now)
        self.collector.collect_rss(now)
        self.collector.collect_macro(now)

    async def run(self, stop: asyncio.Event) -> None:
        if not self.ncfg.enabled:
            log.info("news: disabled in config/news.yaml — idling")
            await stop.wait()
            return
        await asyncio.to_thread(init_news_db)
        tasks = [asyncio.create_task(self._loop(n, i, f, stop)) for n, i, f in self.loops()]
        await stop.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run(stop: asyncio.Event) -> None:
    from src.common.config import get_config

    await NewsService(get_config()).run(stop)
```

Note the `test_disabled_service_idles` test sets `stop` before calling `run`, so `await stop.wait()` returns immediately.

`scripts/run_news.py`:

```python
"""News service entrypoint (docs/superpowers/specs/2026-10-09-news-thread-design.md).

Usage:
    python -m scripts.run_news

No IBKR connection, no clientId. Idles when config/news.yaml → enabled is false. Runs until
SIGINT/SIGTERM. Supervised by scripts.start like the other daemons.
"""

import asyncio
import signal

from src.common.logging import setup_logging
from src.news.service import run


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await run(stop)


def main() -> None:
    setup_logging()
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

In `scripts/start.py` `SERVICES`, after `"spreads"`:

```python
    "news": {
        "label": "news_service",
        "module": "scripts.run_news",
        "log": PROJECT_ROOT / "logs" / "news.log",
    },
```

Then check `scripts/launchd.py` and `tests/test_start*.py` for any hard-coded list of service names (`grep -rn '"spreads"' scripts tests | grep -i service`) and add `"news"` wherever the spreads service is enumerated; record what was found in the progress log.

- [x] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_news_service.py tests/test_news_fence.py tests/test_eval_skills.py tests/test_spreads_fence.py -v` → PASS.

- [ ] **Step 5: Smoke run (manual, networked — optional for the executor, required before go-live):** `timeout 90 .venv/bin/python -m scripts.run_news` then `sqlite3 data/news.db "select category, count(*) from news_items group by 1;"` shows rows. Record the counts in the progress log.

- [x] **Step 6: Gate + commit**

```bash
git add src/news/service.py scripts/run_news.py scripts/start.py tests/test_news_service.py tests/test_news_fence.py tests/test_eval_skills.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): news service process, supervisor entry, news fence tests"
```

---

## Milestone 2 — Deterministic cards in the News thread (spec §6.1–6.4, §7)

### Task 13: Fact sheet + flags

**Files:**
- Modify: `src/news/schemas.py` (add `Fact`, `FactSheet`)
- Create: `src/news/facts.py`
- Test: `tests/test_news_facts.py`

**Interfaces:**
- Produces (`schemas`): `Fact(id: str, label: str, value: float | None = None, display: str)`; `FactSheet` with `facts: list[Fact]`, `flags: dict[str, list[str]]` and methods `add(label, value, display) -> Fact`, `get(label) -> Fact | None`, `flag(name: str, *evidence: Fact | None) -> None`, `render() -> str`, `numbers() -> list[float]`, `ids() -> set[str]`.
- Produces (`facts`): `Analytics` dataclass (`technicals`, `iv`, `sector`, `quote`, `daily`, `past_earnings` callables; `Analytics.live()`); `sigma_move(ret_pct, iv_pct) -> float | None`; `expected_move(spot, iv_pct, dte) -> float`; `post_earnings_moves(daily, dates) -> list[float]`; `build_ticker_facts(symbol, *, an, positions, lists, earnings, cluster_tags, today, cfg) -> FactSheet`; `build_macro_facts(events, *, reaction, backdrop) -> FactSheet`; `build_market_facts(tape, backdrop) -> FactSheet`.

- [x] **Step 1: Failing test**

```python
# tests/test_news_facts.py
from __future__ import annotations

import math
from datetime import date

import pandas as pd

from src.common.config import get_config
from src.common.schemas import IVStats, OptionRight, PositionSnapshot, SectorContext, TechnicalStats
from src.news import facts as F
from src.news.schemas import EarningsView
from src.news.tape import Quote

TODAY = date(2026, 10, 9)


def _an(*, chg=-6.2, iv=48.0, rsi=27.0, sma200=172.0, support=(170.0,), prev=180.0) -> F.Analytics:
    last = prev * (1 + chg / 100)
    quotes = {
        "NVDA": Quote(symbol="NVDA", last=last, prev_close=prev, change_pct=chg),
        "SPY": Quote(symbol="SPY", last=600, prev_close=606, change_pct=-1.0),
        "XLK": Quote(symbol="XLK", last=200, prev_close=204, change_pct=-2.0),
    }
    return F.Analytics(
        technicals=lambda s: TechnicalStats(symbol=s, price=last, rsi_14=rsi, atr_14=4.0, sma_50=178.0, sma_200=sma200, support_levels=list(support), resistance_levels=[190.0]),
        iv=lambda s: IVStats(symbol=s, current_iv=iv, iv_rank=62.0, hv_30=40.0),
        sector=lambda s: SectorContext(symbol=s, sector="Technology", sector_etf="XLK"),
        quote=lambda s: quotes.get(s, Quote(symbol=s)),
        daily=lambda s: pd.DataFrame(),
        past_earnings=lambda s: [],
    )


def test_sigma_and_expected_move() -> None:
    assert round(F.sigma_move(-6.2, 48.0), 2) == round(6.2 / (48 / math.sqrt(252)), 2)
    assert F.sigma_move(1.0, None) is None and F.sigma_move(None, 30.0) is None
    assert round(F.expected_move(100.0, 40.0, 365), 2) == 40.0


def test_ticker_facts_numbered_and_book_aware() -> None:
    pos = [PositionSnapshot(symbol="NVDA", sec_type="OPT", position=-1, avg_cost=1.2, right=OptionRight.PUT, strike=165.0, expiry=date(2026, 10, 23), underlying="NVDA")]
    sheet = F.build_ticker_facts("NVDA", an=_an(), positions=pos, lists=["actively_wheeling"], earnings=None,
                                 cluster_tags=set(), today=TODAY, cfg=get_config().news)
    assert [f.id for f in sheet.facts] == [f"F{i}" for i in range(1, len(sheet.facts) + 1)]
    assert sheet.get("Move today").display == "-6.2%"
    assert sheet.get("Move vs SPY").value == -5.2
    assert sheet.get("Move vs XLK").value == -4.2
    book = next(f for f in sheet.facts if f.label.startswith("Position NVDA 165P"))
    assert "14 DTE" in book.display and "% OTM" in book.display and "exp. moves" in book.display
    assert "large_move_no_hard_news" in sheet.flags
    assert "oversold_at_support" in sheet.flags
    assert "sector_move" not in sheet.flags
    assert "F1" in sheet.render()


def test_sector_move_flag_and_rumor() -> None:
    an = _an(chg=-2.2)
    sheet = F.build_ticker_facts("NVDA", an=an, positions=[], lists=[], earnings=None, cluster_tags={"rumor", "quantified"},
                                 today=TODAY, cfg=get_config().news)
    assert "sector_move" in sheet.flags and "rumor_driven" in sheet.flags
    assert "large_move_no_hard_news" not in sheet.flags
    assert sheet.get("Universe").display == "not in universe"


def test_earnings_facts() -> None:
    e = EarningsView(symbol="NVDA", report_date=TODAY, timing="amc", eps_est=2.0, eps_actual=2.3, rev_est=40e9, rev_actual=42e9, status="released")
    sheet = F.build_ticker_facts("NVDA", an=_an(chg=-9.0), positions=[], lists=["watchlist"], earnings=e, cluster_tags=set(),
                                 today=TODAY, cfg=get_config().news)
    assert sheet.get("EPS vs est").display == "EPS 2.30 vs 2.00 est"
    assert sheet.get("Revenue vs est").display == "Rev 42.0B vs 40.0B est"
    assert "earnings_outsized" in sheet.flags


def test_degrades_when_analytics_missing() -> None:
    an = F.Analytics(technicals=lambda s: None, iv=lambda s: None, sector=lambda s: None,
                     quote=lambda s: Quote(symbol=s), daily=lambda s: pd.DataFrame(), past_earnings=lambda s: [])
    sheet = F.build_ticker_facts("ZZZ", an=an, positions=[], lists=[], earnings=None, cluster_tags=set(), today=TODAY, cfg=get_config().news)
    assert sheet.get("Move today") is None and sheet.flags == {}


def test_post_earnings_moves() -> None:
    idx = pd.to_datetime(["2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31"])
    df = pd.DataFrame({"Close": [100.0, 101.0, 91.0, 92.0]}, index=idx)
    assert [round(x, 2) for x in F.post_earnings_moves(df, [date(2026, 7, 29)])] == [-9.9]
```

- [x] **Step 2: Run to fail.**

- [x] **Step 3: Implement**

Append to `src/news/schemas.py`:

```python
import re as _re

_NUM = _re.compile(r"[-+]?\d[\d,]*\.?\d*")


class Fact(BaseModel):
    id: str
    label: str
    value: float | None = None
    display: str


class FactSheet(BaseModel):
    """Numbered facts (F1…Fk) computed by deterministic code — the LLM's only source of numbers
    (spec §6.1) and the grounding checker's reference set (§6.6)."""

    facts: list[Fact] = Field(default_factory=list)
    flags: dict[str, list[str]] = Field(default_factory=dict)

    def add(self, label: str, value: float | None, display: str) -> Fact:
        f = Fact(id=f"F{len(self.facts) + 1}", label=label, value=value, display=display)
        self.facts.append(f)
        return f

    def get(self, label: str) -> Fact | None:
        return next((f for f in self.facts if f.label == label), None)

    def flag(self, name: str, *evidence: Fact | None) -> None:
        self.flags[name] = [f.id for f in evidence if f is not None]

    def ids(self) -> set[str]:
        return {f.id for f in self.facts}

    def numbers(self) -> list[float]:
        out = [f.value for f in self.facts if f.value is not None]
        for f in self.facts:
            for m in _NUM.findall(f.display):
                try:
                    out.append(float(m.replace(",", "")))
                except ValueError:
                    continue
        return out

    def render(self) -> str:
        lines = [f"{f.id} {f.label}: {f.display}" for f in self.facts]
        lines += [f"FLAG {name} ← {', '.join(ev) or '-'}" for name, ev in self.flags.items()]
        return "\n".join(lines)
```

`src/news/facts.py`:

```python
"""Deterministic fact sheet + overreaction/continuation flags (spec §6.1–6.2).

Reads only the deterministic analytics tier (technicals, iv, sector_context, price data)
and the read-side views. The LLM interprets these; it never computes them.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd

from src.common.config import NewsCfg
from src.common.schemas import (
    IVStats,
    MarketConditions,
    OptionRight,
    PositionSnapshot,
    SectorContext,
    TechnicalStats,
)
from src.news.playbook import parse_value
from src.news.schemas import EarningsView, EconEventView, FactSheet
from src.news.tape import Quote


def _safe(fn: Callable, *a: object) -> object | None:
    try:
        return fn(*a)
    except Exception:
        return None


@dataclass
class Analytics:
    technicals: Callable[[str], TechnicalStats | None]
    iv: Callable[[str], IVStats | None]
    sector: Callable[[str], SectorContext | None]
    quote: Callable[[str], Quote]
    daily: Callable[[str], pd.DataFrame]
    past_earnings: Callable[[str], list[date]]

    @classmethod
    def live(cls) -> Analytics:
        from src.analytics.iv import get_iv_stats
        from src.analytics.sector_context import get_sector_context
        from src.analytics.technicals import get_technical_stats
        from src.data.factory import get_earnings_history, get_price_provider
        from src.news.tape import quote

        return cls(
            technicals=lambda s: _safe(get_technical_stats, s),  # type: ignore[return-value]
            iv=lambda s: _safe(get_iv_stats, s),  # type: ignore[return-value]
            sector=lambda s: _safe(get_sector_context, s),  # type: ignore[return-value]
            quote=lambda s: _safe(quote, s) or Quote(symbol=s),  # type: ignore[return-value]
            daily=lambda s: _safe(get_price_provider().get_ohlcv, s, 260) or pd.DataFrame(),  # type: ignore[return-value]
            past_earnings=lambda s: _safe(get_earnings_history().past_report_dates, s, 4) or [],  # type: ignore[return-value]
        )


def sigma_move(ret_pct: float | None, iv_pct: float | None) -> float | None:
    if ret_pct is None or not iv_pct:
        return None
    return abs(ret_pct) / (iv_pct / math.sqrt(252))


def expected_move(spot: float, iv_pct: float, dte: int) -> float:
    return spot * iv_pct / 100 * math.sqrt(max(dte, 1) / 365)


def post_earnings_moves(daily: pd.DataFrame, dates: list[date]) -> list[float]:
    """Close of the last session before the report → close of the first session after it.
    A two-session window covers both before-open and after-close reports without timing."""
    if daily is None or daily.empty or "Close" not in daily:
        return []
    closes = daily["Close"].dropna()
    days = [pd.Timestamp(i).date() for i in closes.index]
    out: list[float] = []
    for d in dates:
        before = [i for i, x in enumerate(days) if x < d]
        after = [i for i, x in enumerate(days) if x > d]
        if before and after:
            out.append((float(closes.iloc[after[0]]) / float(closes.iloc[before[-1]]) - 1) * 100)
    return out


def _r1(x: float) -> float:
    return round(x, 1)


def build_ticker_facts(
    symbol: str,
    *,
    an: Analytics,
    positions: list[PositionSnapshot],
    lists: list[str],
    earnings: EarningsView | None,
    cluster_tags: set[str],
    today: date,
    cfg: NewsCfg,
) -> FactSheet:
    sh = FactSheet()
    q = an.quote(symbol)
    tech = an.technicals(symbol)
    iv = an.iv(symbol)
    sec = an.sector(symbol)
    chg = q.change_pct
    iv_pct = (iv.current_iv or iv.hv_30) if iv else None

    move = sh.add("Move today", _r1(chg), f"{chg:+.1f}%") if chg is not None else None
    sig_v = sigma_move(chg, iv_pct)
    sig = sh.add("Move in σ", _r1(sig_v), f"{sig_v:.1f}σ") if sig_v is not None else None
    if chg is not None and tech and tech.atr_14 and q.last:
        x = abs(chg / 100 * q.last) / tech.atr_14
        sh.add("Move ÷ ATR14", _r1(x), f"{x:.1f}× ATR")
    abn_sector = None
    if chg is not None and symbol != "SPY":
        spy = an.quote("SPY").change_pct
        if spy is not None:
            sh.add("SPY today", _r1(spy), f"{spy:+.1f}%")
            sh.add("Move vs SPY", _r1(chg - spy), f"{chg - spy:+.1f}% vs SPY")
        etf = sec.sector_etf if sec else None
        if etf and etf != symbol:
            e_chg = an.quote(etf).change_pct
            if e_chg is not None:
                abn_sector = sh.add(f"Move vs {etf}", _r1(chg - e_chg), f"{chg - e_chg:+.1f}% vs {etf}")

    rsi = support_f = None
    near_support = False
    if tech:
        if tech.rsi_14 is not None:
            rsi = sh.add("RSI14", _r1(tech.rsi_14), f"RSI {tech.rsi_14:.0f}")
        if tech.sma_200 and q.last:
            pct = (q.last / tech.sma_200 - 1) * 100
            sh.add("Price vs SMA200", _r1(pct), f"{pct:+.1f}% vs SMA200")
        if tech.phase is not None:
            sh.add("Phase", None, str(tech.phase))
        if q.last:
            below = [s for s in tech.support_levels if s <= q.last]
            above = [r for r in tech.resistance_levels if r >= q.last]
            atr = tech.atr_14 or 0
            if below:
                s = max(below)
                support_f = sh.add("Nearest support", s, f"${s:.2f} ({(s / q.last - 1) * 100:+.1f}%)")
                near_support = (q.last - s) <= atr
            if tech.sma_200 is not None and abs(q.last - tech.sma_200) <= atr:
                near_support = True
            if above:
                r = min(above)
                sh.add("Nearest resistance", r, f"${r:.2f} ({(r / q.last - 1) * 100:+.1f}%)")
    if iv:
        if iv.iv_rank is not None:
            sh.add("IV rank", _r1(iv.iv_rank), f"IV rank {iv.iv_rank:.0f}")
        if iv.current_iv is not None and iv.hv_30 is not None:
            sh.add("IV30 vs HV30", _r1(iv.current_iv - iv.hv_30), f"IV {iv.current_iv:.0f}% vs HV {iv.hv_30:.0f}%")

    implied = None
    if iv_pct:
        im = iv_pct / math.sqrt(252)
        implied = sh.add("IV-implied 1-day move", _r1(im), f"±{im:.1f}%")
    if earnings:
        sh.add("Earnings date", None, f"{earnings.report_date:%Y-%m-%d} {earnings.timing.upper()}")
        if earnings.eps_actual is not None and earnings.eps_est is not None:
            sh.add("EPS vs est", earnings.eps_actual, f"EPS {earnings.eps_actual:.2f} vs {earnings.eps_est:.2f} est")
        if earnings.rev_actual is not None and earnings.rev_est is not None:
            sh.add("Revenue vs est", earnings.rev_actual / 1e9, f"Rev {earnings.rev_actual / 1e9:.1f}B vs {earnings.rev_est / 1e9:.1f}B est")
        past = post_earnings_moves(an.daily(symbol), an.past_earnings(symbol))
        if past:
            avg = sum(abs(x) for x in past) / len(past)
            sh.add("Avg post-earnings move", _r1(avg), f"±{avg:.1f}% avg over last {len(past)}")
        if earnings.status == "released" and chg is not None and implied is not None and implied.value:
            ratio = abs(chg) / implied.value
            r = sh.add("Move ÷ implied", round(ratio, 2), f"{ratio:.1f}× implied")
            if ratio >= cfg.flags.earnings_outsized:
                sh.flag("earnings_outsized", move, implied, r)
            elif ratio <= cfg.flags.earnings_muted:
                sh.flag("earnings_muted", move, implied, r)

    for p in positions:
        if (p.underlying or p.symbol).upper() != symbol.upper() or p.position == 0:
            continue
        if p.sec_type == "OPT" and p.strike and p.expiry and q.last:
            dte = (p.expiry - today).days
            right = "P" if p.right == OptionRight.PUT else "C"
            otm = (q.last - p.strike) / q.last * 100 if right == "P" else (p.strike - q.last) / q.last * 100
            units = abs(q.last - p.strike) / expected_move(q.last, iv_pct, dte) if iv_pct else None
            word = "OTM" if otm >= 0 else "ITM"
            unit_txt = f" = {units:.1f} exp. moves" if units is not None else ""
            sh.add(f"Position {symbol} {p.strike:g}{right}", _r1(otm), f"{p.strike:g}{right} {dte} DTE · {abs(otm):.1f}% {word}{unit_txt}")
        elif p.sec_type == "STK":
            sh.add(f"Shares {symbol}", p.position, f"{p.position:g} shares @ {p.avg_cost:.2f}")
    sh.add("Universe", None, ", ".join(lists) if lists else "not in universe")

    fl = cfg.flags
    if sig_v is not None and sig_v >= fl.large_move_sigma and "quantified" not in cluster_tags:
        sh.flag("large_move_no_hard_news", move, sig)
    if "rumor" in cluster_tags:
        sh.flag("rumor_driven")
    if abn_sector is not None and chg and abs(abn_sector.value or 0) < fl.sector_share * abs(chg):
        sh.flag("sector_move", move, abn_sector)
    if rsi is not None and (rsi.value or 100) < fl.oversold_rsi and near_support:
        sh.flag("oversold_at_support", rsi, support_f)
    if tech and tech.sma_200 and q.last is not None and q.prev_close is not None:
        if q.last < tech.sma_200 <= q.prev_close:
            sh.flag("trend_break", move)
    return sh


def build_macro_facts(
    events: list[EconEventView], *, reaction: object | None, backdrop: MarketConditions | None
) -> FactSheet:
    """Facts for a group of simultaneous releases. *reaction* is a ``reaction.Reaction`` (Task 14)."""
    sh = FactSheet()
    for e in events:
        exp = e.forecast or e.consensus
        sh.add(
            e.title,
            parse_value(e.actual),
            f"{e.actual or 'n/a'} vs {exp or 'n/a'} est (prev {e.previous or 'n/a'})",
        )
    moves = getattr(reaction, "moves", None) or []
    for m in moves:
        if m.move is not None:
            sh.add(f"{m.asset} reaction ({m.symbol})", round(m.move, 2), f"{m.symbol} {m.move:+.2f}{m.unit}")
    _backdrop(sh, backdrop)
    return sh


def build_market_facts(tape: dict[str, Quote], backdrop: MarketConditions | None) -> FactSheet:
    sh = FactSheet()
    for sym, q in tape.items():
        if q.change_pct is not None:
            sh.add(f"{sym} today", _r1(q.change_pct), f"{sym} {q.change_pct:+.1f}%")
    _backdrop(sh, backdrop)
    return sh


def _backdrop(sh: FactSheet, b: MarketConditions | None) -> None:
    if b is None:
        return
    if b.vix is not None:
        sh.add("VIX", _r1(b.vix), f"VIX {b.vix:.1f}")
    if b.vix_term_ratio is not None:
        sh.add("VIX/VIX3M", round(b.vix_term_ratio, 2), f"VIX/VIX3M {b.vix_term_ratio:.2f}")
    if b.ten_year_yield is not None:
        sh.add("10y yield", round(b.ten_year_yield, 2), f"10y {b.ten_year_yield:.2f}%")
    if b.ten_year_change_5d_bp is not None:
        sh.add("10y 5d change", round(b.ten_year_change_5d_bp), f"10y {b.ten_year_change_5d_bp:+.0f}bp 5d")
```

Check the test arithmetic while implementing: `_an(chg=-6.2)` → SPY −1.0 ⇒ "Move vs SPY" = −5.2; XLK −2.0 ⇒ −4.2. `chg=-2.2` ⇒ vs XLK −0.2, |−0.2| < ⅓·2.2 ⇒ `sector_move`. Oversold: RSI 27 < 30 and last = 180·0.938 = 168.84; support 170 is *above* last so there is no "Nearest support" fact, but SMA200 172 is within one ATR (|168.84 − 172| = 3.16 ≤ 4), so `near_support` is True and the flag fires with evidence `[F(rsi)]`.

The earnings test: chg −9.0, IV 48 ⇒ implied 3.02, ratio 2.98 ≥ 1.5 ⇒ `earnings_outsized`.

- [x] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/news/schemas.py src/news/facts.py tests/test_news_facts.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): deterministic fact sheet and overreaction/continuation flags"
```

---

### Task 14: Measured reaction (📈)

**Files:**
- Create: `src/news/reaction.py`
- Test: `tests/test_news_reaction.py`

**Interfaces:**
- Produces: `AssetMove(asset, symbol, move: float | None, unit: Literal["%", "bp"], arrow: str)`; `Reaction(release_at: datetime, window_min: int, complete: bool, moves: list[AssetMove])` with `.display(asset) -> str | None`; `instruments_for(release_at, cfg) -> dict[str, str]`; `measure_reaction(release_at, *, cfg: NewsReactionCfg, provider: IntradayPriceProvider | None = None) -> Reaction`; `waited_too_long(release_at, now, cfg) -> bool`. Yield symbols `{"^TNX", "^FVX", "^TYX", "^IRX"}` are reported in bp (quote ×10 ⇒ bp, matching `market_conditions`' `^TNX / 10` convention) and their arrow is inverted (yield up ⇒ bond price 🔴).

- [x] **Step 1: Failing test**

```python
# tests/test_news_reaction.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from src.common.config import get_config
from src.news import reaction as R

REL = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)  # 08:30 ET (pre-market)


def _bars(start: datetime, n: int, f) -> pd.DataFrame:
    idx = pd.DatetimeIndex([start + timedelta(minutes=i) for i in range(n)])
    return pd.DataFrame({"Close": [f(i) for i in range(n)]}, index=idx)


class P:
    def __init__(self, frames):
        self.frames = frames

    def get_intraday(self, symbol, *, interval="1m", days=1):
        return self.frames.get(symbol, pd.DataFrame())


def test_premarket_release_uses_futures_and_windows_on_bar_time() -> None:
    cfg = get_config().news.reaction
    assert R.instruments_for(REL, cfg)["stocks"] == "ES=F"
    start = REL - timedelta(minutes=5)
    frames = {
        "ES=F": _bars(start, 30, lambda i: 6000.0 if i < 5 else 5928.0),  # −1.2%
        "ZN=F": _bars(start, 30, lambda i: 110.0 if i < 5 else 109.5),
    }
    r = R.measure_reaction(REL, cfg=cfg, provider=P(frames))
    stocks = next(m for m in r.moves if m.asset == "stocks")
    assert round(stocks.move, 2) == -1.2 and stocks.arrow == "🔴"
    assert r.complete is False  # dollar/gold/oil frames missing


def test_delayed_data_is_incomplete_not_wrong() -> None:
    cfg = get_config().news.reaction
    frames = {"ES=F": _bars(REL - timedelta(minutes=5), 10, lambda i: 6000.0)}  # ends before release+15
    r = R.measure_reaction(REL, cfg=cfg, provider=P(frames))
    assert next(m for m in r.moves if m.asset == "stocks").move is None


def test_rth_yield_reported_in_bp_with_inverted_arrow() -> None:
    cfg = get_config().news.reaction
    rel = datetime(2026, 10, 14, 18, 0, tzinfo=UTC)  # 14:00 ET
    assert R.instruments_for(rel, cfg)["bonds"] == "^TNX"
    frames = {"^TNX": _bars(rel - timedelta(minutes=3), 25, lambda i: 42.0 if i < 3 else 42.9)}
    bonds = next(m for m in R.measure_reaction(rel, cfg=cfg, provider=P(frames)).moves if m.asset == "bonds")
    assert bonds.unit == "bp" and round(bonds.move) == 9 and bonds.arrow == "🔴"


def test_waited_too_long() -> None:
    cfg = get_config().news.reaction
    assert not R.waited_too_long(REL, REL + timedelta(minutes=20), cfg)
    assert R.waited_too_long(REL, REL + timedelta(minutes=36), cfg)
```

- [x] **Step 2: Run to fail.** **Step 3: Implement** `src/news/reaction.py`:

```python
"""📈 Measured post-release reaction (spec §6.4). Deterministic.

Windows on BAR TIMESTAMPS, never wall clock: yfinance futures/index bars can lag ~10 min,
so "15 minutes after" means the first bar stamped ≥ release + 15m. Missing → move None.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

import pandas as pd
from pydantic import BaseModel

from src.common.config import NewsReactionCfg
from src.common.market_hours import is_rth
from src.data.protocols import IntradayPriceProvider

YIELD_SYMBOLS = frozenset({"^TNX", "^FVX", "^TYX", "^IRX"})
_FLAT_PCT = 0.05
_FLAT_BP = 0.5


class AssetMove(BaseModel):
    asset: str
    symbol: str
    move: float | None = None
    unit: Literal["%", "bp"] = "%"
    arrow: str = "⚪"


class Reaction(BaseModel):
    release_at: datetime
    window_min: int
    complete: bool
    moves: list[AssetMove]

    def display(self, asset: str) -> str | None:
        m = next((x for x in self.moves if x.asset == asset), None)
        if m is None or m.move is None:
            return None
        return f"{m.arrow} {m.symbol} {m.move:+.2f}{m.unit}" if m.unit == "%" else f"{m.arrow} 10y {m.move:+.0f}bp"


def instruments_for(release_at: datetime, cfg: NewsReactionCfg) -> dict[str, str]:
    return cfg.instruments_rth if is_rth(release_at) else cfg.instruments_ext


def _utc_index(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "Close" not in df:
        return pd.DataFrame()
    out = df.copy()
    idx = pd.DatetimeIndex(out.index)
    out.index = idx.tz_localize(UTC) if idx.tz is None else idx.tz_convert(UTC)
    return out.sort_index()


def _arrow(move: float, unit: str, inverse: bool) -> str:
    flat = _FLAT_BP if unit == "bp" else _FLAT_PCT
    if abs(move) < flat:
        return "⚪"
    up = move > 0
    if inverse:
        up = not up
    return "🟢" if up else "🔴"


def measure_reaction(
    release_at: datetime, *, cfg: NewsReactionCfg, provider: IntradayPriceProvider | None = None
) -> Reaction:
    if provider is None:
        from src.data.factory import get_intraday_price_provider

        provider = get_intraday_price_provider()
    rel = release_at.astimezone(UTC)
    target = rel + timedelta(minutes=cfg.window_min)
    moves: list[AssetMove] = []
    complete = True
    for asset, sym in instruments_for(rel, cfg).items():
        df = _utc_index(provider.get_intraday(sym, interval="1m", days=2))
        unit: Literal["%", "bp"] = "bp" if sym in YIELD_SYMBOLS else "%"
        before = df[df.index < rel]["Close"] if not df.empty else pd.Series(dtype=float)
        after = df[df.index >= target]["Close"] if not df.empty else pd.Series(dtype=float)
        if before.empty or after.empty:
            complete = False
            moves.append(AssetMove(asset=asset, symbol=sym, unit=unit))
            continue
        b, a = float(before.iloc[-1]), float(after.iloc[0])
        mv = (a - b) * 10 if unit == "bp" else (a / b - 1) * 100
        moves.append(AssetMove(asset=asset, symbol=sym, move=mv, unit=unit, arrow=_arrow(mv, unit, inverse=unit == "bp")))
    return Reaction(release_at=rel, window_min=cfg.window_min, complete=complete, moves=moves)


def waited_too_long(release_at: datetime, now: datetime, cfg: NewsReactionCfg) -> bool:
    return now >= release_at + timedelta(minutes=cfg.max_wait_min)
```

Check `is_rth`'s signature in `src/common/market_hours.py` (line 192: `is_rth(now: datetime | None = None) -> bool`) — it accepts an aware datetime; verify it converts to ET internally, and convert with `.astimezone(ZoneInfo("America/New_York"))` before calling if it does not.

- [x] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/news/reaction.py tests/test_news_reaction.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): 📈 measured reaction windowed on bar timestamps"
```

---

### Task 15: Card schemas + Telegram HTML render

**Files:**
- Modify: `src/news/schemas.py`
- Create: `src/news/render.py`
- Test: `tests/test_news_render.py`

**Interfaces:**
- Produces (`schemas`): `Verdict = Literal["further_downside_likely", "further_upside_likely", "overreaction_likely", "priced_in", "unclear"]`; `Confidence = Literal["low", "medium", "high"]`; `Explanation` (fields and `max_length` budgets exactly as spec §6.5: `headline` 80, `what_happened` 180, `read` 240, `bull` 100, `bear` 100, `verdict`, `confidence`, `book_impact` 200 default `""`, `setup_impact` 160 default `""`, `evidence: list[str]`); `DigestRead(cluster_id, headline ≤80, read ≤200, verdict, evidence)`, `DigestReads(items ≤10)`, `EditorThread(cluster_ids, title ≤80)`, `EditorOutput(regime, threads ≤10, dropped)`; `SourceLink(name, url)`; `GridRow(asset, textbook: str | None, actual: str | None)`; `DigestItem(text, read: str | None, verdict: Verdict | None, links: list[SourceLink])`; `DigestSection(title, items)`; `CardKind` literal; `CardPayload` (fields below).
- Produces (`render`): `RenderedMessage(text: str, preview_url: str | None, show_above: bool)` dataclass; `fmt_when(dt) -> str`; `render_card(p: CardPayload) -> RenderedMessage`; `split_message(text, limit=4096) -> list[str]`; `VERDICT_LABEL: dict[str, str]`.

- [x] **Step 1: Failing test**

```python
# tests/test_news_render.py
from __future__ import annotations

from datetime import UTC, datetime

from src.news.render import fmt_when, render_card, split_message
from src.news.schemas import CardPayload, DigestItem, DigestSection, Explanation, GridRow, SourceLink

WHEN = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)


def _macro(**kw) -> CardPayload:
    base = dict(
        kind="macro_print", title="CPI hotter than expected", emoji="🔴", when=WHEN,
        headline_line="Sep CPI +0.4% m/m vs +0.3% est",
        grid=[GridRow(asset="stocks", textbook="🔴", actual="🔴 ES=F -1.20%"), GridRow(asset="bonds", textbook="🔴", actual=None)],
        links=[SourceLink(name="BLS", url="https://www.bls.gov/x?a=1&b=2")],
    )
    base.update(kw)
    return CardPayload(**base)


def test_when_shows_sgt_and_et() -> None:
    assert fmt_when(WHEN) == "20:30 SGT (08:30 ET)"
    assert fmt_when(datetime(2026, 11, 3, 13, 30, tzinfo=UTC)) == "21:30 SGT (08:30 ET)"  # after US DST ends


def test_macro_card_layout() -> None:
    m = render_card(_macro())
    assert m.text.startswith("🔴 <b>CPI hotter than expected</b> · 20:30 SGT (08:30 ET)")
    assert "<pre>" in m.text and "📘 Textbook" in m.text and "Stocks" in m.text
    assert '<a href="https://www.bls.gov/x?a=1&amp;b=2">BLS</a>' in m.text


def test_explanation_sections_and_verdict_label() -> None:
    e = Explanation(headline="h", what_happened="w", read="Inflation re-accelerating.", bull="core cooling", bear="shelter sticky",
                    verdict="further_downside_likely", confidence="medium", book_impact="NVDA 165P 3.1% OTM", setup_impact="", evidence=["F1"])
    t = render_card(_macro(explanation=e)).text
    assert "🧠 Inflation re-accelerating." in t
    assert "⚖️ Bull: core cooling · Bear: shelter sticky" in t
    assert "🎯 Further downside likely · medium" in t
    assert "💼 NVDA 165P 3.1% OTM" in t and "🛒" not in t


def test_every_dynamic_field_is_escaped() -> None:
    evil = "<b>x</b> & <script>"
    e = Explanation(headline=evil, what_happened=evil, read=evil, bull=evil, bear=evil, verdict="unclear",
                    confidence="low", book_impact=evil, setup_impact=evil, evidence=[])
    p = _macro(title=evil, headline_line=evil, facts_line=evil, explanation=e,
               grid=[GridRow(asset=evil, textbook=evil, actual=evil)],
               links=[SourceLink(name=evil, url='https://x.com/"><script>')], updates=[evil],
               sections=[DigestSection(title=evil, items=[DigestItem(text=evil, read=evil, links=[])])])
    t = render_card(p).text
    assert "<script>" not in t and "<b>x</b>" not in t
    assert "&lt;b&gt;x&lt;/b&gt; &amp; &lt;script&gt;" in t


def test_preview_prefers_image() -> None:
    m = render_card(_macro(image_url="https://img/x.png", preview_url="https://article"))
    assert m.preview_url == "https://img/x.png" and m.show_above
    m2 = render_card(_macro(preview_url="https://article"))
    assert m2.preview_url == "https://article" and not m2.show_above


def test_split_respects_limit_and_blocks() -> None:
    text = "\n\n".join(["A" * 3000, "B" * 3000, "C" * 5000])
    parts = split_message(text, 4096)
    assert all(len(p) <= 4096 for p in parts)
    assert parts[0] == "A" * 3000 and parts[1] == "B" * 3000
```

- [x] **Step 2: Run to fail.** **Step 3: Implement**

Append to `src/news/schemas.py` (add `from typing import Literal`):

```python
Verdict = Literal["further_downside_likely", "further_upside_likely", "overreaction_likely", "priced_in", "unclear"]
Confidence = Literal["low", "medium", "high"]
CardKind = Literal[
    "macro_print", "earnings", "market_move", "vix_spike", "ticker_move", "breaking", "brief",
    "digest_premarket", "digest_close", "digest_week",
]


class Explanation(BaseModel):
    """The writer pass's output (spec §6.5). Budgets are enforced here, not by asking nicely."""

    headline: str = Field(max_length=80)
    what_happened: str = Field(max_length=180)
    read: str = Field(max_length=240)
    bull: str = Field(max_length=100)
    bear: str = Field(max_length=100)
    verdict: Verdict
    confidence: Confidence
    book_impact: str = Field(default="", max_length=200)
    setup_impact: str = Field(default="", max_length=160)
    evidence: list[str] = Field(default_factory=list)


class DigestRead(BaseModel):
    """One thread's read inside a digest — produced by ONE batched writer call per digest (Task 24)."""

    cluster_id: int
    headline: str = Field(max_length=80)
    read: str = Field(max_length=200)
    verdict: Verdict
    evidence: list[str] = Field(default_factory=list)


class DigestReads(BaseModel):
    items: list[DigestRead] = Field(default_factory=list, max_length=10)


class EditorThread(BaseModel):
    cluster_ids: list[int] = Field(min_length=1)
    title: str = Field(max_length=80)


class EditorOutput(BaseModel):
    """The editor pass (spec §6.5 pass 1): regime, ranked threads, dropped noise."""

    regime: Literal["risk_on", "risk_off", "rotation", "mixed"]
    threads: list[EditorThread] = Field(default_factory=list, max_length=10)
    dropped: list[int] = Field(default_factory=list)


class SourceLink(BaseModel):
    name: str
    url: str


class GridRow(BaseModel):
    asset: str
    textbook: str | None = None
    actual: str | None = None


class DigestItem(BaseModel):
    text: str
    read: str | None = None
    verdict: Verdict | None = None
    links: list[SourceLink] = Field(default_factory=list)


class DigestSection(BaseModel):
    title: str
    items: list[DigestItem] = Field(default_factory=list)


class CardPayload(BaseModel):
    """Everything a post shows — rendered to Telegram HTML here and to React on the web (§7.6)."""

    kind: CardKind
    subject: str | None = None
    title: str
    emoji: str
    when: datetime
    headline_line: str | None = None
    facts_line: str | None = None
    grid: list[GridRow] = Field(default_factory=list)
    grid_note: str | None = None
    facts: FactSheet | None = None
    explanation: Explanation | None = None
    trimmed: bool = False
    llm_note: str | None = None
    regime: str | None = None
    sections: list[DigestSection] = Field(default_factory=list)
    links: list[SourceLink] = Field(default_factory=list)
    image_url: str | None = None
    preview_url: str | None = None
    critical: bool = False
    updates: list[str] = Field(default_factory=list)
    cluster_ids: list[int] = Field(default_factory=list)
    event_keys: list[str] = Field(default_factory=list)
```

`src/news/render.py`:

```python
"""Telegram HTML for news cards (spec §7.1). Every dynamic string goes through esc()."""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from src.news.schemas import CardPayload, DigestSection, SourceLink

SGT = ZoneInfo("Asia/Singapore")
ET = ZoneInfo("America/New_York")
LIMIT = 4096

VERDICT_LABEL = {
    "further_downside_likely": "Further downside likely",
    "further_upside_likely": "Further upside likely",
    "overreaction_likely": "Overreaction likely",
    "priced_in": "Priced in",
    "unclear": "Unclear",
}
_REGIME = {"risk_on": "🟢 Risk-on", "risk_off": "🔴 Risk-off", "rotation": "🔄 Rotation", "mixed": "⚪ Mixed"}


@dataclass
class RenderedMessage:
    text: str
    preview_url: str | None
    show_above: bool


def esc(s: str | None) -> str:
    return html.escape(s or "", quote=False)


def link(l: SourceLink) -> str:
    return f'<a href="{html.escape(l.url, quote=True)}">{esc(l.name)}</a>'


def fmt_when(dt: datetime) -> str:
    return f"{dt.astimezone(SGT):%H:%M} SGT ({dt.astimezone(ET):%H:%M} ET)"


def _grid(p: CardPayload) -> list[str]:
    if not p.grid:
        return []
    rows = [f"{'':<9} {'📘 Textbook':<12} 📈 Actual ({15}m)"]
    for g in p.grid:
        rows.append(f"{esc(g.asset.title()):<9} {esc(g.textbook or '·'):<12} {esc(g.actual or '·')}")
    out = ["<pre>" + "\n".join(rows) + "</pre>"]
    if p.grid_note:
        out.append(f"<i>{esc(p.grid_note)}</i>")
    return out


def _section(sec: DigestSection) -> list[str]:
    out = [f"<b>{esc(sec.title)}</b>"]
    for it in sec.items:
        line = f"• {esc(it.text)}"
        if it.links:
            line += " — " + " · ".join(link(l) for l in it.links[:3])
        out.append(line)
        if it.read:
            out.append(f"  🧠 {esc(it.read)}")
        if it.verdict:
            out.append(f"  🎯 {VERDICT_LABEL[it.verdict]}")
    return out


def render_card(p: CardPayload) -> RenderedMessage:
    blocks: list[list[str]] = []
    head = [f"{esc(p.emoji)} <b>{esc(p.title)}</b> · {fmt_when(p.when)}"]
    if p.regime:
        head.append(_REGIME.get(p.regime, esc(p.regime)))
    if p.headline_line:
        line = esc(p.headline_line)
        if p.links:
            line += " — " + " · ".join(link(l) for l in p.links[:3])
        head.append(line)
    if p.facts_line:
        head.append(esc(p.facts_line))
    blocks.append(head)
    if p.grid:
        blocks.append(_grid(p))
    e = p.explanation
    if e is not None:
        ex = [f"🧠 {esc(e.read)}", f"⚖️ Bull: {esc(e.bull)} · Bear: {esc(e.bear)}",
              f"🎯 {VERDICT_LABEL[e.verdict]} · {e.confidence}"]
        if e.book_impact:
            ex.append(f"💼 {esc(e.book_impact)}")
        if e.setup_impact:
            ex.append(f"🛒 {esc(e.setup_impact)}")
        if p.trimmed:
            ex.append("<i>⚠︎ trimmed</i>")
        blocks.append(ex)
    if p.llm_note:
        blocks.append([f"<i>{esc(p.llm_note)}</i>"])
    for sec in p.sections:
        blocks.append(_section(sec))
    if p.updates:
        blocks.append([esc(u) for u in p.updates])
    if p.links and not p.headline_line:
        blocks.append(["🔗 " + " · ".join(link(l) for l in p.links[:4])])
    text = "\n\n".join("\n".join(b) for b in blocks if b)
    if p.image_url:
        return RenderedMessage(text=text, preview_url=p.image_url, show_above=True)
    return RenderedMessage(text=text, preview_url=p.preview_url, show_above=False)


def split_message(text: str, limit: int = LIMIT) -> list[str]:
    parts: list[str] = []
    cur = ""
    for block in text.split("\n\n"):
        while len(block) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(block[:limit])
            block = block[limit:]
        candidate = f"{cur}\n\n{block}" if cur else block
        if len(candidate) > limit:
            parts.append(cur)
            cur = block
        else:
            cur = candidate
    if cur:
        parts.append(cur)
    return parts
```

A hard split inside a `<pre>`/`<a>` could leave unbalanced tags; sections are short by construction (budgets), so only digest text with many sections reaches the limit and splits on `\n\n`. Record in STATUS (Task 34) that a single block > 4096 chars is hard-split.

- [x] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/news/schemas.py src/news/render.py tests/test_news_render.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): card payload schema and escaped Telegram HTML renderer"
```

---

### Task 16: Charts

**Files:**
- Create: `src/news/charts.py`
- Test: `tests/test_news_charts.py`

**Interfaces:**
- Produces: `build_figure(daily: pd.DataFrame, *, title: str, support: list[float], resistance: list[float], strikes: list[tuple[float, str]], event_day: date | None) -> Figure | None`; `to_png(fig: Figure) -> bytes`; `price_chart(...) -> bytes | None` (same args as `build_figure`); `save_chart(png: bytes, charts_dir: Path, post_id: int) -> str`.

- [x] **Step 1: Failing test**

```python
# tests/test_news_charts.py
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.news import charts


def _daily(n=200):
    idx = pd.bdate_range("2026-01-02", periods=n)
    return pd.DataFrame({"Close": np.linspace(150, 180, n)}, index=idx)


def test_figure_has_close_smas_levels_and_strike() -> None:
    fig = charts.build_figure(_daily(), title="NVDA", support=[170.0], resistance=[190.0],
                              strikes=[(165.0, "165P 14 DTE")], event_day=date(2026, 9, 30))
    ax = fig.axes[0]
    labels = {l.get_label() for l in ax.get_lines()}
    assert {"Close", "SMA50", "SMA200"} <= labels
    assert any("165P" in t.get_text() for t in ax.texts)
    png = charts.to_png(fig)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_empty_data_returns_none(tmp_path) -> None:
    assert charts.price_chart(pd.DataFrame(), title="x", support=[], resistance=[], strikes=[], event_day=None) is None
    path = charts.save_chart(b"\x89PNG", tmp_path, 7)
    assert path.endswith("7.png")
```

- [x] **Step 2: Run to fail.** **Step 3: Implement** `src/news/charts.py`:

```python
"""Static price charts for ticker/earnings/close-recap cards (spec §7.1). Headless (Agg)."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

_BG, _FG, _MUTED = "#111418", "#e6e8eb", "#8a9099"


def build_figure(
    daily: pd.DataFrame,
    *,
    title: str,
    support: list[float],
    resistance: list[float],
    strikes: list[tuple[float, str]],
    event_day: date | None,
) -> Figure | None:
    if daily is None or daily.empty or "Close" not in daily:
        return None
    close = daily["Close"].dropna().iloc[-130:]
    full = daily["Close"].dropna()
    fig, ax = plt.subplots(figsize=(8, 4), dpi=120)
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)
    ax.plot(close.index, close.values, color=_FG, lw=1.4, label="Close")
    ax.plot(close.index, full.rolling(50).mean().reindex(close.index).values, color="#5b9bd5", lw=1, label="SMA50")
    ax.plot(close.index, full.rolling(200).mean().reindex(close.index).values, color="#c9a227", lw=1, label="SMA200")
    for s in support:
        ax.axhline(s, color="#3fa34d", lw=0.8, ls=":")
    for r in resistance:
        ax.axhline(r, color="#d9534f", lw=0.8, ls=":")
    for k, label in strikes:
        ax.axhline(k, color="#e07b39", lw=1.2, ls="--")
        ax.text(close.index[0], k, f" {label}", color="#e07b39", va="bottom", fontsize=8)
    if event_day is not None:
        ax.axvline(pd.Timestamp(event_day), color=_MUTED, lw=0.8)
    ax.set_title(title, color=_FG, fontsize=11, loc="left")
    ax.tick_params(colors=_MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#2a2f36")
    ax.legend(loc="upper left", fontsize=7, facecolor=_BG, edgecolor="#2a2f36", labelcolor=_FG)
    fig.tight_layout()
    return fig


def to_png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def price_chart(
    daily: pd.DataFrame, *, title: str, support: list[float], resistance: list[float],
    strikes: list[tuple[float, str]], event_day: date | None,
) -> bytes | None:
    fig = build_figure(daily, title=title, support=support, resistance=resistance, strikes=strikes, event_day=event_day)
    return None if fig is None else to_png(fig)


def save_chart(png: bytes, charts_dir: Path, post_id: int) -> str:
    charts_dir.mkdir(parents=True, exist_ok=True)
    path = charts_dir / f"{post_id}.png"
    path.write_bytes(png)
    return str(path)
```

- [x] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/news/charts.py tests/test_news_charts.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): matplotlib price chart with levels and short-strike line"
```

---

### Task 17: Publisher + quiet hours

**Files:**
- Create: `src/news/publish.py`, `src/news/quiet.py`
- Test: `tests/test_news_publish.py`

**Interfaces:**
- Produces (`quiet`): `is_quiet(now: datetime, cfg: NewsQuietCfg) -> bool`; `silent_for(now, *, critical: bool, cfg) -> bool`.
- Produces (`publish`): `class Publisher(bot, chat_id: str, thread_id: int | None)` with `from_config(cfg: Config) -> Publisher | None`; `async send(text, *, silent=False, preview_url=None, show_above=False) -> int | None` (returns the first chunk's message id; later chunks are sent without preview); `async edit(message_id, text, *, preview_url=None, show_above=False) -> bool` (False when the message is gone); `async send_photo(png: bytes, *, reply_to: int | None, silent: bool, caption: str | None = None) -> int | None`.

- [x] **Step 1: Failing test**

```python
# tests/test_news_publish.py
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import BadRequest, NetworkError

from src.common.config import NewsQuietCfg
from src.news import quiet
from src.news.publish import Publisher

Q = NewsQuietCfg()


@pytest.mark.parametrize(
    "utc, expected",
    [
        (datetime(2026, 10, 30, 15, 59, tzinfo=UTC), False),  # 23:59 SGT, before US DST end
        (datetime(2026, 10, 30, 16, 1, tzinfo=UTC), True),    # 00:01 SGT
        (datetime(2026, 11, 2, 22, 59, tzinfo=UTC), True),    # 06:59 SGT, after US DST end
        (datetime(2026, 11, 2, 23, 1, tzinfo=UTC), False),    # 07:01 SGT
    ],
)
def test_quiet_hours_across_us_dst_end(utc, expected) -> None:
    assert quiet.is_quiet(utc, Q) is expected


def test_window_crossing_midnight_and_critical() -> None:
    cfg = NewsQuietCfg(start="22:00", end="06:00")
    assert quiet.is_quiet(datetime(2026, 10, 9, 15, 0, tzinfo=UTC), cfg)  # 23:00 SGT
    assert not quiet.silent_for(datetime(2026, 10, 9, 15, 0, tzinfo=UTC), critical=True, cfg=cfg)
    assert quiet.silent_for(datetime(2026, 10, 9, 15, 0, tzinfo=UTC), critical=False, cfg=cfg)


async def test_send_splits_and_previews_first_chunk_only() -> None:
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=[SimpleNamespace(message_id=11), SimpleNamespace(message_id=12)]))
    pub = Publisher(bot, "-100", 4409)
    mid = await pub.send("A" * 3000 + "\n\n" + "B" * 3000, silent=True, preview_url="https://img/x.png", show_above=True)
    assert mid == 11
    first, second = bot.send_message.await_args_list
    assert first.kwargs["message_thread_id"] == 4409 and first.kwargs["disable_notification"] is True
    assert first.kwargs["link_preview_options"].url == "https://img/x.png"
    assert second.kwargs["link_preview_options"].is_disabled is True


async def test_retry_then_give_up_and_edit_gone() -> None:
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=[NetworkError("x"), SimpleNamespace(message_id=5)]),
                          edit_message_text=AsyncMock(side_effect=BadRequest("Message to edit not found")))
    pub = Publisher(bot, "-100", None, backoff=(0, 0, 0))
    assert await pub.send("hi") == 5
    assert await pub.edit(5, "x") is False


async def test_edit_not_modified_is_success() -> None:
    bot = SimpleNamespace(edit_message_text=AsyncMock(side_effect=BadRequest("Message is not modified")))
    assert await Publisher(bot, "-100", None, backoff=(0,)).edit(5, "x") is True
```

Also add an autouse fixture to `tests/conftest.py` so no news test can ever reach real Telegram (the operator's `.env` holds a live bot token, and `Secrets` reads it in tests):

```python
@pytest.fixture(autouse=True)
def _no_real_telegram_for_news(monkeypatch):
    """src.news.publish builds its own Bot from .env; never let a test talk to Telegram."""
    from unittest.mock import AsyncMock, MagicMock

    fake = MagicMock()
    fake.return_value.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    fake.return_value.edit_message_text = AsyncMock(return_value=True)
    fake.return_value.send_photo = AsyncMock(return_value=MagicMock(message_id=2))
    try:
        monkeypatch.setattr("src.news.publish.Bot", fake)
    except (ImportError, AttributeError):
        pass  # before Task 17 exists
```

- [x] **Step 2: Run to fail.** **Step 3: Implement**

`src/news/quiet.py`:

```python
"""Quiet hours (spec §7.2, D8): non-critical posts go out silently, nothing is held."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from src.common.config import NewsQuietCfg


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def is_quiet(now: datetime, cfg: NewsQuietCfg) -> bool:
    local = now.astimezone(ZoneInfo(cfg.tz)).time()
    start, end = _t(cfg.start), _t(cfg.end)
    if start <= end:
        return start <= local < end
    return local >= start or local < end


def silent_for(now: datetime, *, critical: bool, cfg: NewsQuietCfg) -> bool:
    if not is_quiet(now, cfg):
        return False
    return not (critical and cfg.critical_breaks_quiet)
```

`src/news/publish.py`:

```python
"""Telegram output for the news thread — its own Bot, no src.notify import (the spreads pattern).

Best effort: failures are retried with backoff and then logged; nothing raises into a loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import Bot, LinkPreviewOptions, ReplyParameters
from telegram.error import BadRequest, RetryAfter, TelegramError

from src.common.config import Config
from src.news.render import split_message

log = logging.getLogger(__name__)


class Publisher:
    def __init__(self, bot: Any, chat_id: str, thread_id: int | None, *, backoff: tuple[float, ...] = (0.5, 1.0, 2.0)) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.backoff = backoff

    @classmethod
    def from_config(cls, cfg: Config) -> Publisher | None:
        s = cfg.secrets
        if not s.telegram_bot_token or not s.telegram_chat_id:
            log.warning("news: TELEGRAM_BOT_TOKEN/CHAT_ID unset — posts are stored, not sent")
            return None
        thread = int(s.telegram_thread_news) if s.telegram_thread_news else None
        return cls(Bot(s.telegram_bot_token), s.telegram_chat_id, thread)

    async def _retry(self, op: Callable[[], Awaitable[Any]]) -> Any:
        last: Exception | None = None
        for delay in (*self.backoff, None):
            try:
                return await op()
            except BadRequest:
                raise
            except RetryAfter as exc:
                last = exc
                await asyncio.sleep(float(getattr(exc, "retry_after", 1)))
            except TelegramError as exc:
                last = exc
                if delay is None:
                    break
                await asyncio.sleep(delay)
        log.warning("news: telegram op failed after retries: %s", last)
        return None

    def _preview(self, url: str | None, above: bool) -> LinkPreviewOptions:
        if not url:
            return LinkPreviewOptions(is_disabled=True)
        return LinkPreviewOptions(url=url, prefer_large_media=True, show_above_text=above)

    async def send(self, text: str, *, silent: bool = False, preview_url: str | None = None, show_above: bool = False) -> int | None:
        first_id: int | None = None
        for i, chunk in enumerate(split_message(text)):
            preview = self._preview(preview_url if i == 0 else None, show_above)
            try:
                msg = await self._retry(
                    lambda c=chunk, p=preview: self.bot.send_message(
                        chat_id=self.chat_id, text=c, parse_mode="HTML", message_thread_id=self.thread_id,
                        disable_notification=silent, link_preview_options=p,
                    )
                )
            except BadRequest as exc:
                log.warning("news: send rejected: %s", exc)
                return first_id
            if msg is not None and first_id is None:
                first_id = msg.message_id
        return first_id

    async def edit(self, message_id: int, text: str, *, preview_url: str | None = None, show_above: bool = False) -> bool:
        chunk = split_message(text)[0]
        try:
            res = await self._retry(
                lambda: self.bot.edit_message_text(
                    text=chunk, chat_id=self.chat_id, message_id=message_id, parse_mode="HTML",
                    link_preview_options=self._preview(preview_url, show_above),
                )
            )
        except BadRequest as exc:
            msg = str(exc).lower()
            if "not modified" in msg:
                return True
            log.info("news: edit of %s failed: %s", message_id, exc)
            return False
        return res is not None

    async def send_photo(self, png: bytes, *, reply_to: int | None, silent: bool, caption: str | None = None) -> int | None:
        reply = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True) if reply_to else None
        try:
            msg = await self._retry(
                lambda: self.bot.send_photo(
                    chat_id=self.chat_id, photo=png, caption=caption, parse_mode="HTML",
                    message_thread_id=self.thread_id, disable_notification=silent, reply_parameters=reply,
                )
            )
        except BadRequest as exc:
            log.warning("news: photo rejected: %s", exc)
            return None
        return None if msg is None else msg.message_id
```

- [x] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/news/publish.py src/news/quiet.py tests/test_news_publish.py tests/conftest.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): Telegram publisher (split, preview, retry, edit) and SGT quiet hours"
```

---

### Task 18: Triggers + alert gate

**Files:**
- Create: `src/news/triggers.py`
- Test: `tests/test_news_triggers.py`

**Interfaces:**
- Produces: `AlertKind` literal (`macro_print, earnings, market_move, vix_spike, ticker_move, breaking`); `AlertCandidate(kind, subject: str, critical: bool, symbols: list[str] = [], event_keys: list[str] = [], cluster_ids: list[int] = [], detail: dict[str, float | str | None] = {})`; `TickerMove(symbol, change_pct: float | None, abnormal_pct: float | None, sigma: float | None)`; pure detectors `group_macro_releases(events: list[EconEventView], pb: Playbook) -> list[AlertCandidate]`, `detect_earnings(released: list[EarningsView], *, held: set[str], universe: set[str]) -> list[AlertCandidate]`, `detect_index_levels(tape: dict[str, Quote], cfg: NewsAlertsCfg) -> list[AlertCandidate]` (all crossed levels), `pick_new_levels(cands: list[AlertCandidate], fired: set[str]) -> list[AlertCandidate]`, `detect_vix(q: Quote, cfg) -> list[AlertCandidate]`, `detect_ticker_moves(moves: list[TickerMove], *, held, universe, cfg) -> list[AlertCandidate]`, `detect_breaking(clusters: list[ClusterView], *, reaction_pct: float | None, cfg) -> list[AlertCandidate]`; `class AlertGate(cfg: NewsAlertsCfg)` with `fired_subjects(trigger: str, day: date) -> set[str]`, `mark(trigger, subject, day, now) -> None`, `hourly_noncritical(now) -> int`, `admit(c: AlertCandidate, *, now: datetime, day: date) -> bool`.

- [x] **Step 1: Failing test**

```python
# tests/test_news_triggers.py
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.common.config import get_config
from src.news import triggers as T
from src.news.playbook import load_playbook
from src.news.schemas import ClusterView, EarningsView, EconEventView
from src.news.tape import Quote

A = get_config().news.alerts
NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
DAY = date(2026, 10, 14)


def _ev(title, at, actual="1"):
    return EconEventView(event_key=f"{at:%H:%M}|{title}", title=title, scheduled_at=at, impact="High", actual=actual)


def test_simultaneous_releases_group_into_one_alert() -> None:
    at = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
    evs = [_ev("Core CPI m/m", at), _ev("CPI m/m", at), _ev("CPI y/y", at), _ev("Unemployment Claims", at)]
    cands = T.group_macro_releases(evs, load_playbook())
    assert len(cands) == 1
    c = cands[0]
    assert c.critical and c.detail["primary"] == "CPI m/m" and len(c.event_keys) == 4


def test_earnings_critical_only_for_held() -> None:
    rel = [EarningsView(symbol="NVDA", report_date=DAY, status="released"), EarningsView(symbol="AAPL", report_date=DAY, status="released"),
           EarningsView(symbol="ZZZ", report_date=DAY, status="released")]
    cands = {c.subject: c for c in T.detect_earnings(rel, held={"NVDA"}, universe={"NVDA", "AAPL"})}
    assert cands["NVDA"].critical and not cands["AAPL"].critical and "ZZZ" not in cands


def test_index_levels_pick_most_extreme_unfired() -> None:
    tape = {"SPY": Quote(symbol="SPY", change_pct=-2.4), "QQQ": Quote(symbol="QQQ", change_pct=0.3)}
    crossed = T.detect_index_levels(tape, A)
    assert {c.subject for c in crossed} == {"SPY:-1", "SPY:-2"}
    new = T.pick_new_levels(crossed, fired=set())
    assert [c.subject for c in new] == ["SPY:-2"] and new[0].critical
    assert T.pick_new_levels(crossed, fired={"SPY:-1", "SPY:-2"}) == []


def test_vix_jump_and_level() -> None:
    subs = {c.subject for c in T.detect_vix(Quote(symbol="^VIX", last=26.0, prev_close=21.0, change_pct=23.8), A)}
    assert subs == {"VIX:jump", "VIX:25"}


def test_ticker_moves_thresholds() -> None:
    moves = [T.TickerMove(symbol="NVDA", change_pct=-6, abnormal_pct=-5, sigma=2.2),
             T.TickerMove(symbol="AAPL", change_pct=-4, abnormal_pct=-3, sigma=2.5),
             T.TickerMove(symbol="PLTR", change_pct=-9, abnormal_pct=-8, sigma=3.4)]
    subs = {c.subject: c for c in T.detect_ticker_moves(moves, held={"NVDA"}, universe={"NVDA", "AAPL", "PLTR"}, cfg=A)}
    assert set(subs) == {"NVDA", "PLTR"} and subs["NVDA"].critical and not subs["PLTR"].critical


def test_breaking_needs_sources_topic_and_reaction() -> None:
    c = ClusterView(id=1, headline="Ceasefire agreed", category="geopolitics", first_seen=NOW, last_seen=NOW,
                    source_count=3, topic_class="ceasefire")
    assert T.detect_breaking([c], reaction_pct=0.7, cfg=A)[0].cluster_ids == [1]
    assert T.detect_breaking([c], reaction_pct=0.2, cfg=A) == []
    assert T.detect_breaking([c.model_copy(update={"source_count": 1})], reaction_pct=0.9, cfg=A) == []
    assert T.detect_breaking([c.model_copy(update={"topic_class": "other"})], reaction_pct=0.9, cfg=A) == []


def test_gate_once_per_day_and_hourly_cap(news_db) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    g = T.AlertGate(A)
    c = T.AlertCandidate(kind="ticker_move", subject="AAPL", critical=False)
    assert g.admit(c, now=NOW, day=DAY)
    assert not g.admit(c, now=NOW, day=DAY)
    with news_session() as s:
        for i in range(A.max_per_hour):
            s.add(NewsPostRow(kind="ticker_move", posted_at=naive_utc(NOW - timedelta(minutes=i)), critical=False, payload={}, cluster_ids=[], silent=False, edits=0, stage="facts"))
    other = T.AlertCandidate(kind="ticker_move", subject="MSFT", critical=False)
    assert not g.admit(other, now=NOW, day=DAY)
    assert g.admit(other.model_copy(update={"critical": True}), now=NOW, day=DAY)
```

- [x] **Step 2: Run to fail.** **Step 3: Implement** `src/news/triggers.py`:

```python
"""Alert detection (spec §7.2). Detectors are pure; AlertGate holds the once-per-day and
hourly-cap bookkeeping in data/news.db."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.common.config import NewsAlertsCfg
from src.news.playbook import Playbook
from src.news.schemas import ClusterView, EarningsView, EconEventView
from src.news.store.models import AlertStateRow, NewsPostRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session
from src.news.tape import Quote

AlertKind = Literal["macro_print", "earnings", "market_move", "vix_spike", "ticker_move", "breaking"]


class AlertCandidate(BaseModel):
    kind: AlertKind
    subject: str
    critical: bool
    symbols: list[str] = Field(default_factory=list)
    event_keys: list[str] = Field(default_factory=list)
    cluster_ids: list[int] = Field(default_factory=list)
    detail: dict[str, float | str | None] = Field(default_factory=dict)


class TickerMove(BaseModel):
    symbol: str
    change_pct: float | None = None
    abnormal_pct: float | None = None
    sigma: float | None = None


def group_macro_releases(events: list[EconEventView], pb: Playbook) -> list[AlertCandidate]:
    groups: dict[datetime, list[EconEventView]] = {}
    for e in events:
        groups.setdefault(e.scheduled_at, []).append(e)
    out = []
    for at, evs in sorted(groups.items()):
        ranked = sorted(evs, key=lambda e: pb.priority(m.key) if (m := pb.match(e.title)) else 999)
        out.append(
            AlertCandidate(
                kind="macro_print", subject=f"{at:%Y-%m-%dT%H:%M}", critical=True,
                event_keys=[e.event_key for e in ranked], detail={"primary": ranked[0].title},
            )
        )
    return out


def detect_earnings(released: list[EarningsView], *, held: set[str], universe: set[str]) -> list[AlertCandidate]:
    return [
        AlertCandidate(kind="earnings", subject=e.symbol, critical=e.symbol in held, symbols=[e.symbol])
        for e in released
        if e.symbol in held or e.symbol in universe
    ]


def detect_index_levels(tape: dict[str, Quote], cfg: NewsAlertsCfg) -> list[AlertCandidate]:
    out = []
    for sym in cfg.index_symbols:
        chg = (tape.get(sym) or Quote(symbol=sym)).change_pct
        if chg is None:
            continue
        for lvl in cfg.index_levels_down:
            if chg <= lvl:
                out.append(AlertCandidate(kind="market_move", subject=f"{sym}:{lvl:+.0f}", critical=lvl <= cfg.critical_index_level,
                                          symbols=[sym], detail={"level": lvl, "change_pct": chg}))
        for lvl in cfg.index_levels_up:
            if chg >= lvl:
                out.append(AlertCandidate(kind="market_move", subject=f"{sym}:{lvl:+.0f}", critical=False,
                                          symbols=[sym], detail={"level": lvl, "change_pct": chg}))
    return out


def pick_new_levels(cands: list[AlertCandidate], fired: set[str]) -> list[AlertCandidate]:
    best: dict[str, AlertCandidate] = {}
    for c in cands:
        if c.subject in fired:
            continue
        sym = c.symbols[0]
        cur = best.get(sym)
        if cur is None or abs(float(c.detail["level"] or 0)) > abs(float(cur.detail["level"] or 0)):
            best[sym] = c
    return list(best.values())


def detect_vix(q: Quote, cfg: NewsAlertsCfg) -> list[AlertCandidate]:
    out = []
    if q.change_pct is not None and q.change_pct >= cfg.vix_jump_pct:
        out.append(AlertCandidate(kind="vix_spike", subject="VIX:jump", critical=True, symbols=["^VIX"], detail={"change_pct": q.change_pct}))
    for lvl in cfg.vix_levels:
        if q.last is not None and q.last >= lvl and (q.prev_close is None or q.prev_close < lvl):
            out.append(AlertCandidate(kind="vix_spike", subject=f"VIX:{lvl:.0f}", critical=True, symbols=["^VIX"], detail={"level": lvl, "last": q.last}))
    return out


def detect_ticker_moves(moves: list[TickerMove], *, held: set[str], universe: set[str], cfg: NewsAlertsCfg) -> list[AlertCandidate]:
    out = []
    for m in moves:
        if m.sigma is None:
            continue
        is_held = m.symbol in held
        threshold = cfg.held_sigma if is_held else cfg.universe_sigma
        if (is_held or m.symbol in universe) and m.sigma >= threshold:
            out.append(AlertCandidate(kind="ticker_move", subject=m.symbol, critical=is_held, symbols=[m.symbol],
                                      detail={"change_pct": m.change_pct, "abnormal_pct": m.abnormal_pct, "sigma": m.sigma}))
    return out


def detect_breaking(clusters: list[ClusterView], *, reaction_pct: float | None, cfg: NewsAlertsCfg) -> list[AlertCandidate]:
    if reaction_pct is None or abs(reaction_pct) < cfg.geo_reaction_pct:
        return []
    return [
        AlertCandidate(kind="breaking", subject=f"cluster:{c.id}", critical=True, cluster_ids=[c.id], detail={"reaction_pct": reaction_pct})
        for c in clusters
        if c.source_count >= cfg.geo_min_sources and c.topic_class in cfg.geo_topics
    ]


class AlertGate:
    def __init__(self, cfg: NewsAlertsCfg) -> None:
        self.cfg = cfg

    def fired_subjects(self, trigger: str, day: date) -> set[str]:
        with news_session() as s:
            return set(s.scalars(select(AlertStateRow.subject).where(AlertStateRow.trigger == trigger, AlertStateRow.trade_date == day)))

    def mark(self, trigger: str, subject: str, day: date, now: datetime) -> None:
        try:
            with news_session() as s:
                s.add(AlertStateRow(trigger=trigger, subject=subject, trade_date=day, fired_at=naive_utc(now)))
        except IntegrityError:
            pass

    def hourly_noncritical(self, now: datetime) -> int:
        kinds = ("macro_print", "earnings", "market_move", "vix_spike", "ticker_move", "breaking")
        with news_session() as s:
            return int(
                s.scalar(
                    select(func.count(NewsPostRow.id)).where(
                        NewsPostRow.posted_at >= naive_utc(now - timedelta(hours=1)),
                        NewsPostRow.critical.is_(False),
                        NewsPostRow.kind.in_(kinds),
                    )
                )
                or 0
            )

    def admit(self, c: AlertCandidate, *, now: datetime, day: date) -> bool:
        if c.subject in self.fired_subjects(c.kind, day):
            return False
        if not c.critical and self.hourly_noncritical(now) >= self.cfg.max_per_hour:
            return False
        self.mark(c.kind, c.subject, day, now)
        return True
```

(`detect_index_levels` subjects use `f"{lvl:+.0f}"` → `"-1"`, `"-2"`, `"+2"`; the test asserts `"SPY:-1"`.)

- [x] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/news/triggers.py tests/test_news_triggers.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): alert detectors and once-per-day / hourly-cap gate"
```

---

### Task 19: Alert assembly (candidate → card, new vs update)

**Files:**
- Create: `src/news/links.py` (dependency-free link helpers — the API imports these, so they must not pull in the rw engine), `src/news/alerts.py`
- Test: `tests/test_news_alerts.py`

**Interfaces:**
- Consumes: Tasks 10–18.
- Produces (`src.news.links`, imports only `src.news.schemas`): `pick_primary(items: list[ItemView], rank: list[str]) -> ItemView | None`; `links_for(cluster: ClusterView, rank) -> list[SourceLink]` (re-exported from `alerts`). Produces (`alerts`): `AlertContext` dataclass (`cfg: Config`, `an: Analytics`, `pb: Playbook`, `now: datetime`, `today: date`, `positions: list[PositionSnapshot]`, `held: set[str]`, `universe: set[str]`, `backdrop: MarketConditions | None`, `tape: dict[str, Quote]`); `build_card(c: AlertCandidate, ctx: AlertContext) -> CardPayload` (reads views it needs through `news_session` + `queries`); `AlertAction(action: Literal["new", "update", "reply"], payload: CardPayload, post_id: int | None = None)`; `plan_alert(c, payload, *, now, max_edits) -> AlertAction` (looks for a post today sharing a `cluster_id` or `event_key` or (`kind`, `subject`)); `apply_update(existing: CardPayload, new: CardPayload, now) -> CardPayload` (appends `🔄 Update HH:MM SGT · <new title>` to `updates`).

- [ ] **Step 1: Failing test**

```python
# tests/test_news_alerts.py
from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from src.common.config import get_config
from src.news import alerts as AL
from src.news.facts import Analytics
from src.news.playbook import load_playbook
from src.news.schemas import ItemView
from src.news.tape import Quote
from src.news.triggers import AlertCandidate

NOW = datetime(2026, 10, 14, 12, 31, tzinfo=UTC)


def _ctx() -> AL.AlertContext:
    an = Analytics(technicals=lambda s: None, iv=lambda s: None, sector=lambda s: None,
                   quote=lambda s: Quote(symbol=s, last=100, prev_close=102, change_pct=-1.96),
                   daily=lambda s: pd.DataFrame(), past_earnings=lambda s: [])
    return AL.AlertContext(cfg=get_config(), an=an, pb=load_playbook(), now=NOW, today=date(2026, 10, 14),
                           positions=[], held=set(), universe={"NVDA"}, backdrop=None, tape={"SPY": Quote(symbol="SPY", change_pct=-2.1)})


def test_pick_primary_by_rank() -> None:
    items = [ItemView(title="a", source_domain="yahoo.com", url="u1"), ItemView(title="b", source_domain="reuters.com", url="u2")]
    assert AL.pick_primary(items, ["reuters.com", "cnbc.com"]).url == "u2"
    assert AL.pick_primary([], ["reuters.com"]) is None


def test_macro_card_has_textbook_grid_and_pending_actual(news_db) -> None:
    from src.news.store.models import EconEventRow
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(EconEventRow(event_key="k1", title="CPI m/m", playbook_key="cpi", scheduled_at=datetime(2026, 10, 14, 12, 30),
                           impact="High", forecast="0.3%", previous="0.2%", actual="0.4%", surprise_dir="hot", alerted=False))
    c = AlertCandidate(kind="macro_print", subject="2026-10-14T12:30", critical=True, event_keys=["k1"], detail={"primary": "CPI m/m"})
    p = AL.build_card(c, _ctx())
    assert p.emoji == "🔴" and "hotter" in p.title.lower()
    assert p.headline_line.startswith("CPI m/m 0.4% vs 0.3% est")
    stocks = next(g for g in p.grid if g.asset == "stocks")
    assert stocks.textbook == "🔴" and stocks.actual is None
    assert p.grid_note == "📈 reaction in ~15 min"


def test_cluster_already_posted_becomes_update(news_db) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    first = AL.CardPayload(kind="breaking", title="Ceasefire agreed", emoji="🕊️", when=NOW, cluster_ids=[7])
    with news_session() as s:
        s.add(NewsPostRow(kind="breaking", subject="cluster:7", telegram_message_id=99, cluster_ids=[7], posted_at=naive_utc(NOW),
                          payload=first.model_dump(mode="json"), critical=True, silent=False, edits=0, stage="facts"))
    second = AL.CardPayload(kind="market_move", title="SPY +2%", emoji="🟢", when=NOW, cluster_ids=[7])
    act = AL.plan_alert(AlertCandidate(kind="market_move", subject="SPY:+2", critical=False, cluster_ids=[7]), second, now=NOW, max_edits=3)
    assert act.action == "update" and act.post_id is not None
    assert act.payload.updates and "SPY +2%" in act.payload.updates[0]


def test_update_cap_turns_into_reply(news_db) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    base = AL.CardPayload(kind="breaking", title="x", emoji="•", when=NOW, cluster_ids=[8])
    with news_session() as s:
        s.add(NewsPostRow(kind="breaking", subject="cluster:8", telegram_message_id=5, cluster_ids=[8], posted_at=naive_utc(NOW),
                          payload=base.model_dump(mode="json"), critical=True, silent=False, edits=3, stage="facts"))
    act = AL.plan_alert(AlertCandidate(kind="breaking", subject="cluster:8b", critical=True, cluster_ids=[8]), base, now=NOW, max_edits=3)
    assert act.action == "reply"
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement**

`src/news/links.py`:

```python
"""Primary-source choice and inline links for a cluster. Imports only schemas, so the web API
can use it without loading the news process's read-write engine (fence §10.6)."""

from __future__ import annotations

from src.news.schemas import ClusterView, ItemView, SourceLink


def pick_primary(items: list[ItemView], rank: list[str]) -> ItemView | None:
    if not items:
        return None
    order = {d: i for i, d in enumerate(rank)}
    return min(items, key=lambda it: order.get(it.source_domain or "", len(order)))


def links_for(cluster: ClusterView, rank: list[str]) -> list[SourceLink]:
    order = {d: i for i, d in enumerate(rank)}
    seen: set[str] = set()
    out: list[SourceLink] = []
    for it in sorted(cluster.items, key=lambda it: order.get(it.source_domain or "", len(order))):
        name = it.source or it.source_domain
        if it.url and name and name not in seen:
            seen.add(name)
            out.append(SourceLink(name=name, url=it.url))
    return out[:4]
```

`src/news/alerts.py`:

```python
"""Turn an admitted AlertCandidate into a CardPayload, and decide new / update / reply (spec §7.2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from sqlalchemy import select

from src.common.config import Config
from src.common.schemas import MarketConditions, PositionSnapshot
from src.news.facts import Analytics, build_macro_facts, build_market_facts, build_ticker_facts
from src.news.links import links_for, pick_primary  # noqa: F401  (re-exported)
from src.news.playbook import ASSETS, Playbook, prior_for
from src.news.render import SGT
from src.news.schemas import CardPayload, ClusterView, EarningsView, EconEventView, GridRow
from src.news.store import queries
from src.news.store.models import EarningsEventRow, EconEventRow, NewsPostRow
from src.news.store.queries import aware_utc, naive_utc
from src.news.store.session import news_session
from src.news.tape import Quote
from src.news.triggers import AlertCandidate

_SURPRISE_WORD = {"hot": "hotter than expected", "cold": "cooler than expected", "inline": "in line"}
_SURPRISE_EMOJI = {"hot": "🔴", "cold": "🟢", "inline": "⚪"}


@dataclass
class AlertContext:
    cfg: Config
    an: Analytics
    pb: Playbook
    now: datetime
    today: date
    positions: list[PositionSnapshot]
    held: set[str]
    universe: set[str]
    backdrop: MarketConditions | None
    tape: dict[str, Quote]


@dataclass
class AlertAction:
    action: Literal["new", "update", "reply"]
    payload: CardPayload
    post_id: int | None = None


def _events(keys: list[str]) -> list[EconEventView]:
    with news_session() as s:
        rows = [s.get(EconEventRow, k) for k in keys]
        return [queries.econ_view(r) for r in rows if r is not None]


def _macro_card(c: AlertCandidate, ctx: AlertContext) -> CardPayload:
    evs = _events(c.event_keys)
    primary = evs[0]
    entry = ctx.pb.match(primary.title)
    direction = primary.surprise_dir
    prior = prior_for(entry, direction) if entry else None  # type: ignore[arg-type]
    exp = primary.forecast or primary.consensus
    line = " · ".join(f"{e.title} {e.actual or 'n/a'} vs {e.forecast or e.consensus or 'n/a'} est" for e in evs[:4])
    word = _SURPRISE_WORD.get(direction or "", "released")
    title = f"{(entry.key.replace('_', ' ').upper() if entry else primary.title)} {word}"
    return CardPayload(
        kind="macro_print", subject=c.subject, title=title, emoji=_SURPRISE_EMOJI.get(direction or "", "📊"),
        when=primary.scheduled_at, headline_line=line,
        grid=[GridRow(asset=a, textbook=prior.arrows[a] if prior else None) for a in ASSETS],
        grid_note=f"📈 reaction in ~{ctx.cfg.news.reaction.window_min} min",
        facts=build_macro_facts(evs, reaction=None, backdrop=ctx.backdrop),
        critical=True, event_keys=c.event_keys,
        llm_note=None if prior else (f"Expected {exp}" if exp else None),
    )


def _ticker_clusters(symbol: str, now: datetime) -> list[ClusterView]:
    with news_session() as s:
        return queries.clusters_since(s, now - timedelta(hours=24), symbol=symbol, limit=5)


def _earnings_view(symbol: str, today: date) -> EarningsView | None:
    with news_session() as s:
        rows = queries.earnings_between(s, today - timedelta(days=1), today, {symbol})
        return rows[-1] if rows else None


def _ticker_card(c: AlertCandidate, ctx: AlertContext, *, kind: Literal["ticker_move", "earnings", "brief"]) -> CardPayload:
    from src.news.collectors import universe_lists

    sym = c.symbols[0]
    clusters = _ticker_clusters(sym, ctx.now)
    tags = {t for cl in clusters for t in cl.tags}
    earn = _earnings_view(sym, ctx.today) if kind != "ticker_move" else None
    sheet = build_ticker_facts(sym, an=ctx.an, positions=ctx.positions, lists=universe_lists(sym), earnings=earn,
                               cluster_tags=tags, today=ctx.today, cfg=ctx.cfg.news)
    parts = [f.display for f in (sheet.get("Move today"), sheet.get("Move in σ"), sheet.get(f"Move vs SPY"),
                                  sheet.get("RSI14"), sheet.get("Price vs SMA200")) if f is not None]
    if earn is not None:
        parts = [f.display for f in (sheet.get("EPS vs est"), sheet.get("Revenue vs est"), sheet.get("Move ÷ implied")) if f] + parts
    top = clusters[0] if clusters else None
    primary = pick_primary(top.items, ctx.cfg.news.source_rank) if top else None
    chg = (sheet.get("Move today").value if sheet.get("Move today") else None) or 0.0
    if kind == "earnings":
        title = f"{sym} earnings"
    elif kind == "brief":
        title = f"{sym} brief"
    else:
        title = f"{sym} {chg:+.1f}%" + ("" if top else " · no identifiable catalyst")
    return CardPayload(
        kind=kind, subject=sym, title=title, emoji="📉" if chg < 0 else "📈", when=ctx.now,
        headline_line=top.headline if top else None, facts_line=" · ".join(parts) or None, facts=sheet,
        links=links_for(top, ctx.cfg.news.source_rank) if top else [],
        image_url=primary.image_url if primary else None, preview_url=primary.url if primary else None,
        critical=c.critical, cluster_ids=[cl.id for cl in clusters],
    )


def _market_card(c: AlertCandidate, ctx: AlertContext) -> CardPayload:
    sym = c.symbols[0]
    chg = float(c.detail.get("change_pct") or 0.0)
    if c.kind == "vix_spike":
        title = f"VIX {float(c.detail.get('last') or 0):.1f}" if "level" in c.detail else f"VIX +{chg:.0f}%"
        emoji = "⚠️"
    else:
        title = f"{sym} {chg:+.1f}% (crossed {float(c.detail.get('level') or 0):+.0f}%)"
        emoji = "🔴" if chg < 0 else "🟢"
    facts = build_market_facts({k: v for k, v in ctx.tape.items() if v.change_pct is not None}, ctx.backdrop)
    line = " · ".join(f.display for f in facts.facts[:6])
    return CardPayload(kind=c.kind, subject=c.subject, title=title, emoji=emoji, when=ctx.now, facts_line=line,
                       facts=facts, critical=c.critical)


def _breaking_card(c: AlertCandidate, ctx: AlertContext) -> CardPayload:
    with news_session() as s:
        cl = queries.cluster_view(s, c.cluster_ids[0])
    assert cl is not None
    primary = pick_primary(cl.items, ctx.cfg.news.source_rank)
    facts = build_market_facts({k: v for k, v in ctx.tape.items() if v.change_pct is not None}, ctx.backdrop)
    return CardPayload(
        kind="breaking", subject=c.subject, title=cl.headline[:120], emoji="🌍", when=ctx.now,
        headline_line=f"{cl.source_count} sources · {cl.topic_class}", facts_line=" · ".join(f.display for f in facts.facts[:4]),
        facts=facts, links=links_for(cl, ctx.cfg.news.source_rank),
        image_url=primary.image_url if primary else None, preview_url=primary.url if primary else None,
        critical=True, cluster_ids=[cl.id],
    )


def build_card(c: AlertCandidate, ctx: AlertContext) -> CardPayload:
    if c.kind == "macro_print":
        return _macro_card(c, ctx)
    if c.kind in ("ticker_move", "earnings"):
        return _ticker_card(c, ctx, kind=c.kind)  # type: ignore[arg-type]
    if c.kind == "breaking":
        return _breaking_card(c, ctx)
    return _market_card(c, ctx)


def apply_update(existing: CardPayload, new: CardPayload, now: datetime) -> CardPayload:
    line = f"🔄 Update {now.astimezone(SGT):%H:%M} SGT · {new.title}"
    if new.facts_line:
        line += f" · {new.facts_line}"
    return existing.model_copy(update={"updates": [*existing.updates, line],
                                       "cluster_ids": sorted(set(existing.cluster_ids) | set(new.cluster_ids))})


def plan_alert(c: AlertCandidate, payload: CardPayload, *, now: datetime, max_edits: int) -> AlertAction:
    start = naive_utc(now - timedelta(hours=18))
    with news_session() as s:
        posts = list(s.scalars(select(NewsPostRow).where(NewsPostRow.posted_at >= start).order_by(NewsPostRow.posted_at)))
    for post in posts:
        shares = bool(set(post.cluster_ids or []) & set(c.cluster_ids)) or bool(
            set(post.payload.get("event_keys") or []) & set(c.event_keys)
        )
        if not shares:
            continue
        existing = CardPayload.model_validate(post.payload)
        if post.edits >= max_edits:
            return AlertAction("reply", payload, post.id)
        return AlertAction("update", apply_update(existing, payload, now), post.id)
    return AlertAction("new", payload)
```

- [ ] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/news/links.py src/news/alerts.py tests/test_news_alerts.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): alert cards and new/update/reply planning"
```

---

### Task 20: Digests

**Files:**
- Create: `src/news/digests.py`
- Test: `tests/test_news_digests.py`

**Interfaces:**
- Produces: `due_digests(now: datetime, sent: dict[str, str], cfg: NewsDigestCfg) -> list[Literal["premarket", "close", "week"]]` (pure; `sent[name]` is the ET date ISO it last went out); `DigestInputs` dataclass (`now`, `tape: dict[str, Quote]`, `clusters: list[ClusterView]`, `econ: list[EconEventView]`, `earnings: list[EarningsView]`, `held: set[str]`, `positions: list[PositionSnapshot]`, `movers: list[TickerMove]`, `regime: str | None = None`, `thread_order: list[list[int]] | None = None`, `reads: dict[int, DigestRead] = {}`, `rank: list[str] = []`, `max_threads: int = 6`, `max_movers: int = 5`); `build_digest(name, inp) -> CardPayload`; `gather_inputs(name, *, now, cfg: Config, an: Analytics) -> DigestInputs` (reads store + tape; used by the service).

- [ ] **Step 1: Failing test**

```python
# tests/test_news_digests.py
from __future__ import annotations

from datetime import UTC, date, datetime

from src.common.config import NewsDigestCfg
from src.news import digests as D
from src.news.schemas import ClusterView, DigestRead, EarningsView, EconEventView, ItemView
from src.news.tape import Quote
from src.news.triggers import TickerMove

C = NewsDigestCfg()


def test_premarket_due_across_dst_end() -> None:
    # 08:00 ET is 12:00 UTC before 2026-11-01 and 13:00 UTC after.
    assert "premarket" in D.due_digests(datetime(2026, 10, 30, 12, 1, tzinfo=UTC), {}, C)
    assert "premarket" not in D.due_digests(datetime(2026, 11, 2, 12, 1, tzinfo=UTC), {}, C)
    assert "premarket" in D.due_digests(datetime(2026, 11, 2, 13, 1, tzinfo=UTC), {}, C)


def test_sent_today_and_holidays_and_week() -> None:
    now = datetime(2026, 10, 14, 12, 5, tzinfo=UTC)
    assert D.due_digests(now, {"premarket": "2026-10-14"}, C) == []
    assert D.due_digests(datetime(2026, 11, 26, 13, 5, tzinfo=UTC), {}, C) == []  # Thanksgiving
    assert D.due_digests(datetime(2026, 10, 18, 22, 1, tzinfo=UTC), {}, C) == ["week"]  # Sunday 18:01 ET


def _inp(**kw) -> D.DigestInputs:
    now = datetime(2026, 10, 14, 20, 30, tzinfo=UTC)
    base = dict(
        now=now,
        tape={"SPY": Quote(symbol="SPY", change_pct=-1.2), "QQQ": Quote(symbol="QQQ", change_pct=-1.8)},
        clusters=[ClusterView(id=1, headline="Fed minutes show split", category="macro", first_seen=now, last_seen=now, source_count=3,
                              items=[ItemView(title="t", url="https://reuters.com/x", source="Reuters", source_domain="reuters.com")])],
        econ=[EconEventView(event_key="k", title="CPI m/m", scheduled_at=datetime(2026, 10, 15, 12, 30, tzinfo=UTC), impact="High", forecast="0.3%")],
        earnings=[EarningsView(symbol="NVDA", report_date=date(2026, 10, 15), timing="amc", eps_est=2.0)],
        held={"NVDA"}, positions=[], movers=[TickerMove(symbol="PLTR", change_pct=-7.0, abnormal_pct=-5.8, sigma=2.5)],
    )
    base.update(kw)
    return D.DigestInputs(**base)


def test_close_digest_sections() -> None:
    p = D.build_digest("close", _inp())
    titles = [s.title for s in p.sections]
    assert titles[:2] == ["Market", "Top stories"] and "Movers" in titles and "Tonight / tomorrow" in titles
    assert p.kind == "digest_close"
    movers = next(s for s in p.sections if s.title == "Movers")
    assert "PLTR -7.0%" in movers.items[0].text


def test_reads_attach_to_threads() -> None:
    e = DigestRead(cluster_id=1, headline="Fed split on cuts", read="Split Fed means fewer cuts.", verdict="priced_in", evidence=["N1"])
    p = D.build_digest("premarket", _inp(thread_order=[[1]], reads={1: e}, regime="risk_off"))
    top = next(s for s in p.sections if s.title == "Overnight")
    assert top.items[0].read == "Split Fed means fewer cuts." and top.items[0].verdict == "priced_in"
    assert p.regime == "risk_off"


def test_week_ahead_flags_earnings_before_expiry() -> None:
    from src.common.schemas import OptionRight, PositionSnapshot

    pos = [PositionSnapshot(symbol="NVDA", sec_type="OPT", position=-1, avg_cost=1, right=OptionRight.PUT, strike=165, expiry=date(2026, 10, 23), underlying="NVDA")]
    p = D.build_digest("week", _inp(positions=pos))
    risk = next(s for s in p.sections if s.title == "Earnings before your expiries")
    assert "NVDA" in risk.items[0].text
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement** `src/news/digests.py`:

```python
"""Scheduled digests (spec §7.3): pre-market, close recap, week ahead. ET wall-clock schedule,
US trading days only (week-ahead runs on its weekday regardless)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from src.common.config import Config, NewsDigestCfg
from src.common.market_hours import is_trading_day
from src.common.schemas import PositionSnapshot
from src.news.links import links_for
from src.news.render import SGT
from src.news.schemas import (
    CardPayload,
    ClusterView,
    DigestItem,
    DigestRead,
    DigestSection,
    EarningsView,
    EconEventView,
)
from src.news.tape import Quote
from src.news.triggers import TickerMove

ET = ZoneInfo("America/New_York")
DigestName = Literal["premarket", "close", "week"]
_KIND = {"premarket": "digest_premarket", "close": "digest_close", "week": "digest_week"}
_TITLE = {"premarket": "Pre-market brief", "close": "Close recap", "week": "Week ahead"}


def _hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def due_digests(now: datetime, sent: dict[str, str], cfg: NewsDigestCfg) -> list[DigestName]:
    et = now.astimezone(ET)
    today = et.date().isoformat()
    out: list[DigestName] = []
    if is_trading_day(et.date()):
        for name, at in (("premarket", cfg.premarket), ("close", cfg.close)):
            h, m = _hhmm(at)
            if (et.hour, et.minute) >= (h, m) and sent.get(name) != today:
                out.append(name)  # type: ignore[arg-type]
    h, m = _hhmm(cfg.week_ahead_time)
    if et.weekday() == cfg.week_ahead_weekday and (et.hour, et.minute) >= (h, m) and sent.get("week") != today:
        out.append("week")
    return out


@dataclass
class DigestInputs:
    now: datetime
    tape: dict[str, Quote]
    clusters: list[ClusterView]
    econ: list[EconEventView]
    earnings: list[EarningsView]
    held: set[str]
    positions: list[PositionSnapshot]
    movers: list[TickerMove]
    regime: str | None = None
    thread_order: list[list[int]] | None = None
    reads: dict[int, DigestRead] = field(default_factory=dict)
    rank: list[str] = field(default_factory=list)
    max_threads: int = 6
    max_movers: int = 5


def _market(inp: DigestInputs) -> DigestSection:
    parts = [f"{s} {q.change_pct:+.1f}%" for s, q in inp.tape.items() if q.change_pct is not None]
    return DigestSection(title="Market", items=[DigestItem(text=" · ".join(parts) or "No quotes")])


def _stories(inp: DigestInputs, title: str) -> DigestSection:
    by_id = {c.id: c for c in inp.clusters}
    order = inp.thread_order or [[c.id] for c in inp.clusters]
    items = []
    for ids in order[: inp.max_threads]:
        cl = by_id.get(ids[0])
        if cl is None:
            continue
        e = inp.reads.get(ids[0])
        items.append(DigestItem(text=e.headline if e else cl.headline, read=e.read if e else None,
                                verdict=e.verdict if e else None, links=links_for(cl, inp.rank)[:2]))
    return DigestSection(title=title, items=items)


def _calendar(inp: DigestInputs, title: str, start: date, end: date) -> DigestSection:
    items = [
        DigestItem(text=f"{e.scheduled_at.astimezone(SGT):%a %H:%M} SGT · {e.title} (est {e.forecast or e.consensus or 'n/a'})")
        for e in inp.econ
        if start <= e.scheduled_at.astimezone(ET).date() <= end
    ]
    items += [
        DigestItem(text=f"{e.report_date:%a} · {e.symbol} earnings {e.timing.upper()}" + (" · HELD" if e.symbol in inp.held else ""))
        for e in inp.earnings
        if start <= e.report_date <= end
    ]
    return DigestSection(title=title, items=items)


def _movers(inp: DigestInputs) -> DigestSection:
    ranked = sorted((m for m in inp.movers if m.change_pct is not None), key=lambda m: abs(m.change_pct or 0), reverse=True)
    return DigestSection(
        title="Movers",
        items=[
            DigestItem(text=f"{m.symbol} {m.change_pct:+.1f}%" + (f" ({m.abnormal_pct:+.1f}% vs SPY)" if m.abnormal_pct is not None else "")
                       + (f" · {m.sigma:.1f}σ" if m.sigma is not None else "") + (" · HELD" if m.symbol in inp.held else ""))
            for m in ranked[: inp.max_movers]
        ],
    )


def _expiry_risk(inp: DigestInputs) -> DigestSection:
    items = []
    for p in inp.positions:
        if p.sec_type != "OPT" or not p.expiry:
            continue
        sym = (p.underlying or p.symbol).upper()
        for e in inp.earnings:
            if e.symbol == sym and inp.now.astimezone(ET).date() <= e.report_date <= p.expiry:
                items.append(DigestItem(text=f"{sym} reports {e.report_date:%a %d %b} {e.timing.upper()} before your {p.strike:g}{p.right} expiring {p.expiry:%d %b}"))
    return DigestSection(title="Earnings before your expiries", items=items)


def build_digest(name: DigestName, inp: DigestInputs) -> CardPayload:
    today = inp.now.astimezone(ET).date()
    if name == "premarket":
        sections = [_market(inp), _stories(inp, "Overnight"), _calendar(inp, "Today", today, today)]
    elif name == "close":
        tomorrow = today + timedelta(days=1)
        sections = [_market(inp), _stories(inp, "Top stories"), _movers(inp), _calendar(inp, "Tonight / tomorrow", today, tomorrow)]
    else:
        sections = [_calendar(inp, "This week", today, today + timedelta(days=6)), _expiry_risk(inp), _stories(inp, "Weekend stories")]
    return CardPayload(kind=_KIND[name], title=_TITLE[name], emoji="🗞️", when=inp.now, regime=inp.regime,  # type: ignore[arg-type]
                       sections=[s for s in sections if s.items])


def gather_inputs(name: DigestName, *, now: datetime, cfg: Config, an: object) -> DigestInputs:
    """Read the store + tape for a digest. Movers come from the service's last ticker sweep."""
    from src.news.collectors import held_positions, held_underlyings
    from src.news.store import queries
    from src.news.store.session import news_session
    from src.news.tape import tape

    since = now - timedelta(hours=16 if name != "week" else 72)
    today = now.astimezone(ET).date()
    with news_session() as s:
        clusters = queries.clusters_since(s, since, limit=30)
        econ = queries.econ_events_between(s, now - timedelta(hours=2), now + timedelta(days=7))
        earnings = queries.earnings_between(s, today, today + timedelta(days=7))
    syms = cfg.news.tape_symbols_rth if name != "premarket" else cfg.news.tape_symbols_ext
    return DigestInputs(
        now=now, tape=tape(syms), clusters=[c for c in clusters if c.category != "ticker" or c.source_count >= 2],
        econ=econ, earnings=earnings, held=held_underlyings(), positions=held_positions(), movers=[],
        rank=cfg.news.source_rank, max_threads=cfg.news.digests.max_threads, max_movers=cfg.news.digests.max_movers,
    )
```

- [ ] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/news/digests.py tests/test_news_digests.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): digest schedule (ET, trading days, DST-safe) and digest payloads"
```

---

### Task 21: Service — deterministic posting loops

**Files:**
- Modify: `src/news/service.py`
- Create: `src/news/posting.py`
- Test: `tests/test_news_posting.py`

**Interfaces:**
- Produces (`src.news.posting`): `async post_card(payload: CardPayload, *, publisher: Publisher | None, cfg: Config, now: datetime, chart: bytes | None = None, reply_to: int | None = None) -> int` (renders, sends with `silent_for(...)`, stores `NewsPostRow` with `payload`, `silent`, `critical`, `stage="facts"`, saves the chart under `news.charts_dir/<post_id>.png` and sends it as a reply; returns the post id); `async update_post(post_id: int, payload: CardPayload, *, publisher, stage: str | None = None, llm_backend: str | None = None, count_edit: bool = True) -> bool` (re-renders, edits the Telegram message, persists payload/edits/stage); `ticker_chart(symbol: str, sheet: FactSheet, an: Analytics, positions, today) -> bytes | None`.
- Produces (`NewsService`): new loops `econ_actuals` (interval 30 s inside the fast window, else `econ_poll_minutes`), `tape` (every 120 s), `tickers_sweep` (every `alerts.ticker_scan_minutes`), `earnings_alerts` (every 5 min), `breaking` (every 2 min), `digests` (every 60 s); `self.publisher`, `self.gate`, `self.last_movers: list[TickerMove]`; `_alert_ctx(now) -> AlertContext`; `async _dispatch(cands: list[AlertCandidate], now) -> list[int]`.

- [ ] **Step 1: Failing test**

```python
# tests/test_news_posting.py
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.common.config import get_config
from src.news.posting import post_card, update_post
from src.news.schemas import CardPayload

NOW = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)  # 01:00 SGT → quiet


class FakePub:
    def __init__(self):
        self.send = AsyncMock(return_value=101)
        self.edit = AsyncMock(return_value=True)
        self.send_photo = AsyncMock(return_value=102)


async def test_post_card_stores_payload_silences_and_attaches_chart(news_db, tmp_path, monkeypatch) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    cfg = get_config()
    monkeypatch.setattr(cfg.news, "charts_dir", str(tmp_path / "charts"))
    pub = FakePub()
    p = CardPayload(kind="ticker_move", subject="PLTR", title="PLTR -9.0%", emoji="📉", when=NOW, critical=False)
    pid = await post_card(p, publisher=pub, cfg=cfg, now=NOW, chart=b"\x89PNG")
    assert pub.send.await_args.kwargs["silent"] is True
    assert pub.send_photo.await_args.kwargs["reply_to"] == 101
    with news_session() as s:
        row = s.get(NewsPostRow, pid)
    assert row.telegram_message_id == 101 and row.chart_message_id == 102 and row.silent is True
    assert row.payload["title"] == "PLTR -9.0%" and row.chart_path.endswith(f"{pid}.png")


async def test_critical_breaks_quiet_and_no_publisher_still_stores(news_db) -> None:
    cfg = get_config()
    pub = FakePub()
    p = CardPayload(kind="macro_print", title="CPI", emoji="🔴", when=NOW, critical=True)
    await post_card(p, publisher=pub, cfg=cfg, now=NOW)
    assert pub.send.await_args.kwargs["silent"] is False
    assert await post_card(p, publisher=None, cfg=cfg, now=NOW) > 0


async def test_update_post_edits_and_counts(news_db) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    cfg = get_config()
    pub = FakePub()
    p = CardPayload(kind="breaking", title="x", emoji="•", when=NOW, critical=True)
    pid = await post_card(p, publisher=pub, cfg=cfg, now=NOW)
    ok = await update_post(pid, p.model_copy(update={"updates": ["🔄 Update"]}), publisher=pub, stage="explained", llm_backend="cli")
    assert ok
    with news_session() as s:
        row = s.get(NewsPostRow, pid)
    assert row.edits == 1 and row.stage == "explained" and row.llm_backend == "cli"
    assert pub.edit.await_args.args[0] == 101


async def test_update_reposts_when_message_gone(news_db) -> None:
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    pub = FakePub()
    p = CardPayload(kind="breaking", title="x", emoji="•", when=NOW, critical=True)
    pid = await post_card(p, publisher=pub, cfg=get_config(), now=NOW)
    pub.edit = AsyncMock(return_value=False)
    pub.send = AsyncMock(return_value=555)
    assert await update_post(pid, p, publisher=pub)
    with news_session() as s:
        assert s.get(NewsPostRow, pid).telegram_message_id == 555
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement**

`src/news/posting.py`:

```python
"""Persist + publish a card (spec §7). The store is written first-class: a post that cannot
reach Telegram is still recorded (the web page shows it)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from src.common.config import ROOT, Config
from src.common.schemas import OptionRight, PositionSnapshot
from src.news.charts import price_chart, save_chart
from src.news.facts import Analytics
from src.news.publish import Publisher
from src.news.quiet import silent_for
from src.news.render import render_card
from src.news.schemas import CardPayload, FactSheet
from src.news.store.models import NewsPostRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session


async def post_card(
    payload: CardPayload, *, publisher: Publisher | None, cfg: Config, now: datetime,
    chart: bytes | None = None, reply_to: int | None = None,
) -> int:
    silent = silent_for(now, critical=payload.critical, cfg=cfg.news.quiet_hours)
    msg = render_card(payload)
    mid = None
    if publisher is not None:
        mid = await publisher.send(msg.text, silent=silent, preview_url=msg.preview_url, show_above=msg.show_above)
    with news_session() as s:
        row = NewsPostRow(
            kind=payload.kind, subject=payload.subject, telegram_message_id=mid, cluster_ids=payload.cluster_ids,
            posted_at=naive_utc(now), payload=payload.model_dump(mode="json"), silent=silent,
            critical=payload.critical, edits=0, stage="facts",
        )
        s.add(row)
        s.flush()
        pid = row.id
    if chart:
        path = save_chart(chart, ROOT / cfg.news.charts_dir if not Path(cfg.news.charts_dir).is_absolute() else Path(cfg.news.charts_dir), pid)
        cmid = await publisher.send_photo(chart, reply_to=mid, silent=True) if publisher is not None and mid else None
        with news_session() as s:
            row2 = s.get(NewsPostRow, pid)
            assert row2 is not None
            row2.chart_path, row2.chart_message_id = path, cmid
    return pid


async def update_post(
    post_id: int, payload: CardPayload, *, publisher: Publisher | None,
    stage: str | None = None, llm_backend: str | None = None, count_edit: bool = True,
) -> bool:
    with news_session() as s:
        row = s.get(NewsPostRow, post_id)
        if row is None:
            return False
        mid = row.telegram_message_id
    ok = True
    new_mid = None
    if publisher is not None and mid:
        msg = render_card(payload)
        ok = await publisher.edit(mid, msg.text, preview_url=msg.preview_url, show_above=msg.show_above)
        if not ok:  # the message is gone (deleted in Telegram): post a fresh card (spec §11)
            new_mid = await publisher.send(msg.text, silent=True, preview_url=msg.preview_url, show_above=msg.show_above)
            ok = new_mid is not None
    with news_session() as s:
        row = s.get(NewsPostRow, post_id)
        assert row is not None
        if new_mid is not None:
            row.telegram_message_id = new_mid
        row.payload = payload.model_dump(mode="json")
        row.edited_at = naive_utc(datetime.now(UTC))
        if count_edit:
            row.edits += 1
        if stage:
            row.stage = stage
        if llm_backend:
            row.llm_backend = llm_backend
    return ok


def ticker_chart(symbol: str, sheet: FactSheet, an: Analytics, positions: list[PositionSnapshot], today: date) -> bytes | None:
    strikes = []
    for p in positions:
        if (p.underlying or p.symbol).upper() == symbol and p.sec_type == "OPT" and p.strike and p.expiry:
            right = "P" if p.right == OptionRight.PUT else "C"
            strikes.append((p.strike, f"{p.strike:g}{right} {(p.expiry - today).days} DTE"))
    sup = sheet.get("Nearest support")
    res = sheet.get("Nearest resistance")
    return price_chart(
        an.daily(symbol), title=symbol,
        support=[sup.value] if sup and sup.value else [], resistance=[res.value] if res and res.value else [],
        strikes=strikes, event_day=today,
    )
```

The test passes a fake publisher whose `edit` takes `(message_id, text, ...)` positionally — `update_post` calls `publisher.edit(mid, msg.text, ...)`, matching.

In `src/news/service.py`, extend `NewsService` (keep Task 12's loops):

```python
from datetime import timedelta
from zoneinfo import ZoneInfo

from src.analytics.market_conditions import get_market_conditions
from src.common.market_hours import is_trading_day
from src.news import triggers as T
from src.news.alerts import AlertContext, build_card, plan_alert
from src.news.collectors import held_positions, held_underlyings, watch_symbols
from src.news.digests import build_digest, due_digests, gather_inputs
from src.news.facts import Analytics, sigma_move
from src.news.playbook import load_playbook
from src.news.posting import post_card, ticker_chart, update_post
from src.news.publish import Publisher
from src.news.store import queries
from src.news.store.session import news_session
from src.news.store.state import get_state, set_state
from src.news.tape import tape

ET = ZoneInfo("America/New_York")
```

Add to `__init__`: `self.publisher = Publisher.from_config(cfg)`, `self.gate = T.AlertGate(cfg.news.alerts)`, `self.an = Analytics.live()`, `self.last_movers: list[T.TickerMove] = []`, `self._backdrop_cache: tuple[datetime, object] | None = None`.

Change `_loop` to accept `interval_s: float | Callable[[datetime], float]` (call it with `self.clock()` when callable).

Add methods:

```python
    def _backdrop(self, now: datetime):
        if self._backdrop_cache and now - self._backdrop_cache[0] < timedelta(minutes=10):
            return self._backdrop_cache[1]
        try:
            b = get_market_conditions()
        except Exception:
            b = None
        self._backdrop_cache = (now, b)
        return b

    def _alert_ctx(self, now: datetime, tape_now: dict | None = None) -> AlertContext:
        u = set(watch_symbols())
        return AlertContext(cfg=self.cfg, an=self.an, pb=load_playbook(), now=now, today=now.astimezone(ET).date(),
                            positions=held_positions(), held=held_underlyings(), universe=u,
                            backdrop=self._backdrop(now), tape=tape_now or {})

    async def _dispatch(self, cands: list[T.AlertCandidate], now: datetime, *, tape_now: dict | None = None) -> list[int]:
        ids: list[int] = []
        day = now.astimezone(ET).date()
        for c in cands:
            if not await asyncio.to_thread(self.gate.admit, c, now=now, day=day):
                continue
            ctx = await asyncio.to_thread(self._alert_ctx, now, tape_now)
            payload = await asyncio.to_thread(build_card, c, ctx)
            act = await asyncio.to_thread(plan_alert, c, payload, now=now, max_edits=self.ncfg.alerts.max_edits)
            if act.action == "update" and act.post_id is not None:
                await update_post(act.post_id, act.payload, publisher=self.publisher)
                ids.append(act.post_id)
                continue
            chart = None
            if c.kind in ("ticker_move", "earnings") and act.payload.facts is not None:
                chart = await asyncio.to_thread(ticker_chart, c.symbols[0], act.payload.facts, self.an, ctx.positions, ctx.today)
            reply_to = None
            if act.action == "reply" and act.post_id is not None:
                with news_session() as s:
                    from src.news.store.models import NewsPostRow
                    row = s.get(NewsPostRow, act.post_id)
                    reply_to = row.telegram_message_id if row else None
            ids.append(await post_card(act.payload, publisher=self.publisher, cfg=self.cfg, now=now, chart=chart, reply_to=reply_to))
        return ids

    def _econ_interval(self, now: datetime) -> float:
        s = self.ncfg.sources
        return s.econ_fast_poll_seconds if self.collector.in_fast_econ_window(now) else s.econ_poll_minutes * 60

    async def _econ_actuals(self, now: datetime) -> None:
        keys = await asyncio.to_thread(self.collector.refresh_econ_actuals, now)
        if not keys:
            return
        with news_session() as s:
            evs = [queries.econ_view(r) for r in (s.get(EconEventRow, k) for k in keys) if r is not None]
        await self._dispatch(T.group_macro_releases(evs, load_playbook()), now)

    async def _tape_alerts(self, now: datetime) -> None:
        if not is_trading_day(now.astimezone(ET).date()):
            return
        syms = sorted(set(self.ncfg.alerts.index_symbols) | {"^VIX"})
        tp = await asyncio.to_thread(tape, syms)
        day = now.astimezone(ET).date()
        crossed = T.detect_index_levels(tp, self.ncfg.alerts)
        fired = await asyncio.to_thread(self.gate.fired_subjects, "market_move", day)
        new = T.pick_new_levels(crossed, fired)
        for c in crossed:  # mark every crossed level so a later, smaller level never re-alerts
            if c.subject not in fired and c not in new:
                await asyncio.to_thread(self.gate.mark, "market_move", c.subject, day, now)
        vix = tp.get("^VIX")
        vix_cands = T.detect_vix(vix, self.ncfg.alerts) if vix is not None else []
        await self._dispatch(new + vix_cands, now, tape_now=tp)

    async def _ticker_sweep(self, now: datetime) -> None:
        if not is_trading_day(now.astimezone(ET).date()):
            return
        syms = await asyncio.to_thread(watch_symbols)
        tp = await asyncio.to_thread(tape, [*syms, "SPY"])
        spy = tp.get("SPY")
        moves = []
        for sym in syms:
            q = tp.get(sym)
            if q is None or q.change_pct is None:
                continue
            ivs = await asyncio.to_thread(self.an.iv, sym)
            iv_pct = (ivs.current_iv or ivs.hv_30) if ivs else None
            abn = q.change_pct - spy.change_pct if spy and spy.change_pct is not None else None
            moves.append(T.TickerMove(symbol=sym, change_pct=q.change_pct, abnormal_pct=abn,
                                      sigma=sigma_move(abn if abn is not None else q.change_pct, iv_pct)))
        self.last_movers = moves
        cands = T.detect_ticker_moves(moves, held=held_underlyings(), universe=set(syms), cfg=self.ncfg.alerts)
        await self._dispatch(cands, now, tape_now=tp)

    async def _earnings_alerts(self, now: datetime) -> None:
        released = await asyncio.to_thread(self.collector.refresh_earnings, now, days=2)
        if not released:
            return
        with news_session() as s:
            views = [v for sym, d in released for v in queries.earnings_between(s, d, d, {sym})]
        cands = T.detect_earnings(views, held=held_underlyings(), universe=set(watch_symbols()))
        await self._dispatch(cands, now)

    async def _breaking(self, now: datetime) -> None:
        win = timedelta(minutes=self.ncfg.alerts.geo_reaction_window_min)
        with news_session() as s:
            clusters = [c for cat in ("geopolitics", "macro", "government", "markets")
                        for c in queries.clusters_since(s, now - win, category=cat, limit=20)]
        if not clusters:
            return
        sym = "SPY" if is_rth(now) else "ES=F"
        q = await asyncio.to_thread(tape, [sym])
        await self._dispatch(T.detect_breaking(clusters, reaction_pct=q[sym].change_pct, cfg=self.ncfg.alerts), now, tape_now=q)

    async def _digests(self, now: datetime) -> None:
        sent = {n: get_state(f"digest_sent:{n}") or "" for n in ("premarket", "close", "week")}
        for name in due_digests(now, sent, self.ncfg.digests):
            inp = await asyncio.to_thread(gather_inputs, name, now=now, cfg=self.cfg, an=self.an)
            if name == "close":
                inp.movers = list(self.last_movers)
            payload = build_digest(name, inp)
            await post_card(payload, publisher=self.publisher, cfg=self.cfg, now=now)
            set_state(f"digest_sent:{name}", now.astimezone(ET).date().isoformat())
```

(Also import `is_rth` from `src.common.market_hours` and `EconEventRow` from `src.news.store.models`.)

Extend `loops()`:

```python
            ("econ_actuals", self._econ_interval, self._econ_actuals),
            ("tape", 120, self._tape_alerts),
            ("tickers_sweep", self.ncfg.alerts.ticker_scan_minutes * 60, self._ticker_sweep),
            ("earnings_alerts", 300, self._earnings_alerts),
            ("breaking", 120, self._breaking),
            ("digests", 60, self._digests),
```

In `run()`, after `init_news_db` and before starting the loops, reset any `news_requests` rows left `running` (Task 28 adds the table's use) and post the startup banner (spec §9):

```python
        if self.publisher is not None:
            await self.publisher.send(f"📰 News service online (backend: {self.ncfg.llm.backend})", silent=True)
```

Add a daily prune loop (spec §5.2 retention) — create `src/news/store/prune.py`:

```python
"""Retention (spec §5.2): headlines older than news.retention_days, empty clusters and
alert bookkeeping older than 7 days are deleted. Posts (and their charts) are kept."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select

from src.news.store.models import AlertStateRow, NewsClusterRow, NewsItemRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session


def prune(now: datetime, *, retention_days: int) -> int:
    cutoff = naive_utc(now - timedelta(days=retention_days))
    with news_session() as s:
        n = s.execute(delete(NewsItemRow).where(NewsItemRow.fetched_at < cutoff)).rowcount or 0
        live = select(NewsItemRow.cluster_id).where(NewsItemRow.cluster_id.is_not(None))
        s.execute(delete(NewsClusterRow).where(NewsClusterRow.last_seen < cutoff, NewsClusterRow.id.not_in(live)))
        s.execute(delete(AlertStateRow).where(AlertStateRow.fired_at < naive_utc(now - timedelta(days=7))))
    return int(n)
```

with loop `("prune", 24 * 3600, self._threaded(lambda now: prune(now, retention_days=self.ncfg.retention_days)))`, and this test in `tests/test_news_service.py`:

```python
def test_prune_keeps_recent_and_posts(news_db) -> None:
    from datetime import timedelta

    from src.news.store.models import NewsItemRow, NewsPostRow
    from src.news.store.prune import prune
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    now = datetime(2026, 10, 14, tzinfo=UTC)
    with news_session() as s:
        for i, age in enumerate((1, 40)):
            s.add(NewsItemRow(url_hash=f"u{i}", title_hash=f"t{i}", title="x", category="macro", origin="rss",
                              fetched_at=naive_utc(now - timedelta(days=age)), tickers=[], tags=[]))
        s.add(NewsPostRow(kind="digest_close", posted_at=naive_utc(now - timedelta(days=90)), payload={}, cluster_ids=[],
                          silent=False, critical=False, edits=0, stage="explained"))
    assert prune(now, retention_days=30) == 1
    with news_session() as s:
        assert s.query(NewsItemRow).count() == 1 and s.query(NewsPostRow).count() == 1
```

Mark econ rows `alerted=True` inside `_econ_actuals` after dispatch (so a restart does not re-alert; `AlertGate` already dedupes per day, this is belt-and-braces), and likewise `EarningsEventRow.alerted`.

Add a service-level test to `tests/test_news_service.py`:

```python
async def test_dispatch_posts_admitted_candidates_once(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news import service as S
    from src.news.schemas import CardPayload
    from src.news.triggers import AlertCandidate

    svc = S.NewsService(get_config())
    svc.publisher = None
    monkeypatch.setattr(S, "build_card", lambda c, ctx: CardPayload(kind="market_move", subject=c.subject, title="SPY -2%", emoji="🔴", when=datetime(2026, 10, 14, 15, tzinfo=UTC)))
    monkeypatch.setattr(svc, "_alert_ctx", lambda now, tape_now=None: None)
    c = AlertCandidate(kind="market_move", subject="SPY:-2", critical=True)
    now = datetime(2026, 10, 14, 15, tzinfo=UTC)
    assert len(await svc._dispatch([c], now)) == 1
    assert await svc._dispatch([c], now) == []
```

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_news_posting.py tests/test_news_service.py -v` → PASS.

- [ ] **Step 5: Live smoke (manual, before go-live):** with `TELEGRAM_THREAD_NEWS=4409` set, run the service for one premarket window (or temporarily set `digests.premarket` to a minute from now in the private `config/news.yaml`) and confirm a "Pre-market brief" lands in thread 4409 and in `news_posts`. Record the result in the progress log.

- [ ] **Step 6: Gate + commit**

```bash
git add src/news/posting.py src/news/service.py src/news/store/prune.py tests/test_news_posting.py tests/test_news_service.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): deterministic alert and digest posting loops"
```

---

## Milestone 3 — 🧠 LLM explanations (spec §6.5–6.6)

### Task 22: LLM transport — backend chain + daily cap

**Files:**
- Create: `src/news/llm.py`
- Test: `tests/test_news_llm.py`

**Interfaces:**
- Consumes: `src.claude.runner._build_cmd`, `src.claude.runner._run_cli`, `src.claude.parser._unwrap_cli`, `src.claude.ollama_runner._generate` (reused, never copied — spec §6.5), `state.llm_calls/incr_llm_calls`.
- Produces: `LlmResult(text: str, backend: Literal["cli", "ollama"])` NamedTuple; `cap_reached(now: datetime) -> bool`; `call_llm(prompt: str, *, schema: dict, prefix: str, now: datetime) -> LlmResult | None` — tries backends in `news.llm.backend` order, counts **every attempt** against `news.llm.max_calls_per_day` (keyed by the ET date), returns `None` when the cap is hit or every backend fails.

- [ ] **Step 1: Failing test**

```python
# tests/test_news_llm.py
from __future__ import annotations

from datetime import UTC, datetime

from src.common.config import get_config
from src.news import llm

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)


def _cfg(monkeypatch, **kw):
    cfg = get_config().news.llm
    for k, v in kw.items():
        monkeypatch.setattr(cfg, k, v)


def test_cli_first_then_ollama_fallback(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli_then_ollama")
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: None)
    monkeypatch.setattr(llm, "_ollama", lambda prompt, schema, cfg: '{"ok": 1}')
    res = llm.call_llm("p", schema={}, prefix="t", now=NOW)
    assert res == llm.LlmResult('{"ok": 1}', "ollama")
    from src.news.store.state import llm_calls

    assert llm_calls(datetime(2026, 10, 14).date()) == 2


def test_cap_stops_calls(news_db, monkeypatch) -> None:
    _cfg(monkeypatch, backend="cli", max_calls_per_day=1)
    calls = []
    monkeypatch.setattr(llm, "_cli", lambda prompt, prefix, cfg: calls.append(1) or "x")
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW).backend == "cli"
    assert llm.call_llm("p", schema={}, prefix="t", now=NOW) is None
    assert calls == [1] and llm.cap_reached(NOW)


def test_cli_command_pins_news_model(monkeypatch) -> None:
    seen = {}

    def fake_run(prompt, prefix, parse_fn, *, cmd, timeout_seconds, max_retries):
        seen["cmd"] = cmd
        return parse_fn('{"type":"result","result":"{\\"a\\":1}"}')

    monkeypatch.setattr("src.claude.runner._run_cli", fake_run)
    out = llm._cli("p", "t", get_config().news.llm)
    assert out == '{"a":1}'
    assert seen["cmd"][seen["cmd"].index("--model") + 1] == "claude-sonnet-5-5"
    assert "--disallowedTools" in seen["cmd"]
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement** `src/news/llm.py`:

```python
"""Backend chain for news explanations: claude -p → Ollama, with a daily call cap (spec §6.5).

Reuses the trading pipeline's hardened CLI invocation (single turn, tool denylist) and the
Ollama /api/generate call with a JSON-schema grammar — never a third copy. Every attempt
counts toward news.llm.max_calls_per_day (ET date), so a flapping CLI cannot burn the cap
twice as fast unnoticed: it is visible in news_state and on GET /news/status.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, NamedTuple
from zoneinfo import ZoneInfo

from src.common.config import NewsLlmCfg, get_config
from src.news.store.state import incr_llm_calls, llm_calls

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
_ORDER: dict[str, tuple[Literal["cli", "ollama"], ...]] = {
    "cli": ("cli",), "ollama": ("ollama",), "cli_then_ollama": ("cli", "ollama"),
}


class LlmResult(NamedTuple):
    text: str
    backend: Literal["cli", "ollama"]


def _cli(prompt: str, prefix: str, cfg: NewsLlmCfg) -> str | None:
    from src.claude import runner
    from src.claude.parser import _unwrap_cli

    ccfg = get_config().claude.model_copy(update={"model": cfg.model})
    return runner._run_cli(
        prompt, prefix, lambda out: _unwrap_cli(out, prefix),
        cmd=runner._build_cmd(ccfg), timeout_seconds=cfg.timeout_seconds, max_retries=0,
    )


def _ollama(prompt: str, schema: dict, cfg: NewsLlmCfg) -> str | None:
    from src.claude.ollama_runner import _generate

    ccfg = get_config().claude
    if cfg.ollama_model:
        ccfg = ccfg.model_copy(update={"ollama_model": cfg.ollama_model})
    return _generate(prompt, ccfg, schema, timeout=cfg.timeout_seconds)


def cap_reached(now: datetime) -> bool:
    cfg = get_config().news.llm
    return llm_calls(now.astimezone(ET).date()) >= cfg.max_calls_per_day


def call_llm(prompt: str, *, schema: dict, prefix: str, now: datetime) -> LlmResult | None:
    cfg = get_config().news.llm
    day = now.astimezone(ET).date()
    for backend in _ORDER[cfg.backend]:
        if llm_calls(day) >= cfg.max_calls_per_day:
            log.info("news llm: daily cap %d reached — deterministic cards only", cfg.max_calls_per_day)
            return None
        incr_llm_calls(day)
        try:
            text = _cli(prompt, prefix, cfg) if backend == "cli" else _ollama(prompt, schema, cfg)
        except Exception:
            log.exception("news llm: %s backend raised", backend)
            text = None
        if text:
            return LlmResult(text, backend)
    return None
```

Note the third test patches `src.claude.runner._run_cli` and `_cli` resolves it through the module attribute (`runner._run_cli`), which is why `_cli` imports the module, not the function.

- [ ] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/news/llm.py tests/test_news_llm.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): LLM backend chain (claude -p → Ollama) with daily cap"
```

---

### Task 23: Prompts, grounding check, explain (editor + writer + digest batch)

**Files:**
- Create: `src/news/prompts.py`, `src/news/grounding.py`, `src/news/explain.py`
- Test: `tests/test_news_grounding.py`, `tests/test_news_explain.py`

**Interfaces:**
- Produces (`prompts`): `EXPLANATION_SCHEMA`, `EDITOR_SCHEMA`, `DIGEST_SCHEMA` (Pydantic `model_json_schema()` of `Explanation`, `EditorOutput`, `DigestReads`); `number_headlines(items: list[ItemView], start: int = 1) -> tuple[str, dict[str, ItemView]]`; `writer_prompt(kind: str, *, headlines: str, facts: FactSheet, prior: PlaybookPrior | None, reaction: Reaction | None) -> str`; `editor_prompt(clusters: list[ClusterView], backdrop: FactSheet) -> str`; `digest_prompt(threads: list[ClusterView], backdrop: FactSheet) -> str`.
- Produces (`grounding`): `extract_numbers(text: str) -> list[tuple[float, int, bool]]` (value, decimals, must_ground); `grounded(value: float, decimals: int, refs: list[float], rel_tol: float) -> bool`; `strip_ungrounded(text: str, refs: list[float], rel_tol: float) -> tuple[str, bool]`; `ground(e: Explanation, *, facts: FactSheet, news_numbers: list[float], news_ids: set[str], rel_tol: float, fallback_what: str | None) -> tuple[Explanation, bool]`; `ground_digest(r: DigestReads, *, refs: list[float], valid_ids: set[str], rel_tol: float) -> DigestReads`.
- Produces (`explain`): `ExplainOutcome(explanation: Explanation | None, backend: str | None, trimmed: bool, stage: Literal["explained", "fallback"], note: str | None)`; `explain_card(kind: str, *, headlines: list[ItemView], facts: FactSheet, prior: PlaybookPrior | None, reaction: Reaction | None, now: datetime, fallback_what: str | None = None) -> ExplainOutcome`; `edit_digest(clusters: list[ClusterView], backdrop: FactSheet, *, now: datetime) -> EditorOutput | None`; `digest_reads(threads: list[ClusterView], backdrop: FactSheet, *, now: datetime) -> dict[int, DigestRead]`.

**Grounding rule (spec §6.6, made precise here):** a number *must* be grounded when it carries a unit (`%`, `bp`, `bps`, `σ`, `x`, `×`, `$`, `K/M/B`), has a decimal point, or its absolute value is > 10. Bare integers 0–10 ("2nd month", "3 sources") are allowed as counts. A number is grounded when some reference value `r` (fact values, numbers in fact displays, numbers in the prompt's headlines) satisfies `|v − r| ≤ max(rel_tol·|r|, 10^−decimals)` **or** the same for `|v|` vs `|r|` (so "fell 6.2%" matches the fact `−6.2`).

- [ ] **Step 1: Failing tests**

```python
# tests/test_news_grounding.py
from __future__ import annotations

from src.news import grounding as G
from src.news.schemas import DigestRead, DigestReads, Explanation, FactSheet


def _facts() -> FactSheet:
    s = FactSheet()
    s.add("Move today", -6.2, "-6.2%")
    s.add("RSI14", 27.0, "RSI 27")
    s.add("Position NVDA 165P", 3.1, "165P 14 DTE · 3.1% OTM = 0.9 exp. moves")
    return s


def test_extract_numbers_marks_what_must_ground() -> None:
    nums = {v: must for v, _d, must in G.extract_numbers("fell 6.2% in its 2nd drop, 3 sources, $165, 14 DTE, 12bp")}
    assert nums[6.2] and nums[165.0] and nums[14.0] and nums[12.0]
    assert nums[2.0] is False and nums[3.0] is False


def test_grounded_tolerances_and_sign() -> None:
    refs = _facts().numbers()
    assert G.grounded(6.2, 1, refs, 0.02)
    assert G.grounded(0.9, 1, refs, 0.02)
    assert not G.grounded(8.4, 1, refs, 0.02)


def test_ground_strips_sentences_and_fixes_evidence() -> None:
    e = Explanation(headline="NVDA slides", what_happened="NVDA fell 8.4% on curbs.",
                    read="A 6.2% drop at RSI 27 looks stretched. Analysts see 40% downside.",
                    bull="b", bear="c", verdict="overreaction_likely", confidence="medium",
                    book_impact="165P is 3.1% OTM.", evidence=["F1", "F99", "N7"])
    out, trimmed = G.ground(e, facts=_facts(), news_numbers=[], news_ids={"N1"}, rel_tol=0.02,
                            fallback_what="Move today: -6.2%")
    assert trimmed
    assert out.what_happened == "Move today: -6.2%"
    assert out.read == "A 6.2% drop at RSI 27 looks stretched."
    assert out.evidence == ["F1"] and out.verdict == "overreaction_likely"


def test_no_valid_evidence_downgrades_verdict() -> None:
    e = Explanation(headline="h", what_happened="w", read="r", bull="b", bear="c", verdict="further_downside_likely",
                    confidence="high", evidence=["F42"])
    out, _ = G.ground(e, facts=_facts(), news_numbers=[], news_ids=set(), rel_tol=0.02, fallback_what=None)
    assert out.verdict == "unclear" and out.confidence == "low"


def test_ground_digest_drops_bad_items() -> None:
    r = DigestReads(items=[DigestRead(cluster_id=1, headline="Fed", read="Yields up 9bp.", verdict="priced_in", evidence=["N1"]),
                           DigestRead(cluster_id=2, headline="Oil", read="Crude +14%.", verdict="unclear", evidence=[])])
    out = G.ground_digest(r, refs=[9.0], valid_ids={"N1"}, rel_tol=0.02)
    assert out.items[0].read == "Yields up 9bp." and out.items[1].read == ""
```

```python
# tests/test_news_explain.py
from __future__ import annotations

import json
from datetime import UTC, datetime

from src.news import explain as X
from src.news.llm import LlmResult
from src.news.schemas import ClusterView, FactSheet, ItemView

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)
GOOD = {"headline": "NVDA slides on curbs", "what_happened": "NVDA fell 6.2% on export curbs.", "read": "Move is 2x implied.",
        "bull": "AI demand intact", "bear": "China revenue at risk", "verdict": "overreaction_likely", "confidence": "medium",
        "book_impact": "", "setup_impact": "", "evidence": ["F1", "N1"]}


def _facts():
    s = FactSheet()
    s.add("Move today", -6.2, "-6.2%")
    s.add("Move ÷ implied", 2.0, "2.0× implied")
    return s


def test_explain_happy_path(news_db, monkeypatch) -> None:
    monkeypatch.setattr(X, "call_llm", lambda prompt, **kw: LlmResult(json.dumps(GOOD), "cli"))
    out = X.explain_card("ticker_move", headlines=[ItemView(title="Nvidia hit by curbs")], facts=_facts(), prior=None, reaction=None, now=NOW)
    assert out.stage == "explained" and out.backend == "cli" and out.explanation.verdict == "overreaction_likely"


def test_invalid_then_valid_retries_once(news_db, monkeypatch) -> None:
    replies = iter([LlmResult('{"headline": "x"}', "cli"), LlmResult(json.dumps(GOOD), "cli")])
    prompts = []
    monkeypatch.setattr(X, "call_llm", lambda prompt, **kw: prompts.append(prompt) or next(replies))
    out = X.explain_card("ticker_move", headlines=[], facts=_facts(), prior=None, reaction=None, now=NOW)
    assert out.stage == "explained" and "validation error" in prompts[1].lower()


def test_unavailable_is_fallback(news_db, monkeypatch) -> None:
    monkeypatch.setattr(X, "call_llm", lambda prompt, **kw: None)
    monkeypatch.setattr(X, "cap_reached", lambda now: True)
    out = X.explain_card("ticker_move", headlines=[], facts=_facts(), prior=None, reaction=None, now=NOW)
    assert out.stage == "fallback" and out.explanation is None and out.note == "🧠 off (daily cap)"


def test_digest_reads_batch_one_call(news_db, monkeypatch) -> None:
    calls = []
    body = {"items": [{"cluster_id": 1, "headline": "Fed split", "read": "Fewer cuts.", "verdict": "priced_in", "evidence": ["N1"]}]}
    monkeypatch.setattr(X, "call_llm", lambda prompt, **kw: calls.append(1) or LlmResult(json.dumps(body), "cli"))
    cl = ClusterView(id=1, headline="Fed minutes show split", category="macro", first_seen=NOW, last_seen=NOW, source_count=2,
                     items=[ItemView(title="Fed minutes show split")])
    reads = X.digest_reads([cl], FactSheet(), now=NOW)
    assert calls == [1] and reads[1].read == "Fewer cuts."
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement**

`src/news/prompts.py`:

```python
"""Prompts for the news LLM passes. The model may use ONLY the numbered facts (F#) and
headlines (N#); every verdict must cite them. Output is one JSON object per schema."""

from __future__ import annotations

import json

from src.news.playbook import PlaybookPrior
from src.news.reaction import Reaction
from src.news.schemas import ClusterView, DigestReads, EditorOutput, Explanation, FactSheet, ItemView

EXPLANATION_SCHEMA = Explanation.model_json_schema()
EDITOR_SCHEMA = EditorOutput.model_json_schema()
DIGEST_SCHEMA = DigestReads.model_json_schema()

RULES = """You are a markets news analyst writing for an options premium seller (cash-secured puts, covered calls).
Rules:
- Use ONLY the facts (F#) and headlines (N#) below. Every number you write must appear in them.
- Cite the ids that support your verdict in "evidence". No ids, no verdict: use "unclear".
- Call a move an overreaction only when the facts or FLAG lines support it (e.g. large_move_no_hard_news,
  rumor_driven, oversold_at_support, earnings_outsized). Say "further downside" only when facts support it.
- If 📘 TEXTBOOK and 📈 ACTUAL disagree, the "read" field must explain the gap.
- Be terse and concrete. No trading advice, no hedging filler, no em dashes.
- Reply with ONE JSON object matching the schema. Nothing outside the JSON."""


def number_headlines(items: list[ItemView], start: int = 1) -> tuple[str, dict[str, ItemView]]:
    index: dict[str, ItemView] = {}
    lines = []
    for i, it in enumerate(items, start):
        nid = f"N{i}"
        index[nid] = it
        src = f"[{it.source}] " if it.source else ""
        summ = f" — {it.summary[:200]}" if it.summary else ""
        lines.append(f"{nid} {src}{it.title}{summ}")
    return "\n".join(lines), index


def _prior_block(prior: PlaybookPrior | None, reaction: Reaction | None) -> str:
    if prior is None and reaction is None:
        return ""
    lines = ["=== 📘 TEXTBOOK vs 📈 ACTUAL ==="]
    for asset in ("stocks", "bonds", "dollar", "gold", "oil", "vol"):
        tb = prior.arrows.get(asset) if prior else None
        act = reaction.display(asset) if reaction else None
        if tb or act:
            lines.append(f"{asset}: textbook {tb or '-'} | actual {act or 'pending'}")
    if prior:
        lines.append(f"textbook rationale: {prior.rationale}")
    return "\n".join(lines)


def writer_prompt(kind: str, *, headlines: str, facts: FactSheet, prior: PlaybookPrior | None, reaction: Reaction | None) -> str:
    return "\n\n".join(
        x for x in (
            RULES,
            f"EVENT TYPE: {kind}",
            "=== FACTS ===\n" + facts.render(),
            _prior_block(prior, reaction),
            "=== HEADLINES ===\n" + (headlines or "(none)"),
            "=== JSON SCHEMA ===\n" + json.dumps(EXPLANATION_SCHEMA),
        ) if x
    )


def editor_prompt(clusters: list[ClusterView], backdrop: FactSheet) -> str:
    lines = [f"C{c.id} [{c.category}/{c.topic_class}, {c.source_count} sources] {c.headline}" for c in clusters]
    return "\n\n".join([
        RULES.replace("Cite the ids that support your verdict in \"evidence\". No ids, no verdict: use \"unclear\".", ""),
        "TASK: label the market regime, group these stories into at most 6 threads ranked by market importance "
        "for a US options seller, and list cluster ids that are noise.",
        "=== BACKDROP ===\n" + backdrop.render(),
        "=== CLUSTERS ===\n" + "\n".join(lines),
        "=== JSON SCHEMA ===\n" + json.dumps(EDITOR_SCHEMA),
    ])


def digest_prompt(threads: list[ClusterView], backdrop: FactSheet) -> str:
    items = [it for c in threads for it in c.items[:2]]
    heads, _ = number_headlines(items)
    ids = "\n".join(f"cluster_id {c.id}: {c.headline}" for c in threads)
    return "\n\n".join([
        RULES,
        "TASK: for EACH cluster below write a one-line read (what it means for US stocks / rates) and a verdict.",
        "=== FACTS ===\n" + backdrop.render(),
        "=== CLUSTERS ===\n" + ids,
        "=== HEADLINES ===\n" + heads,
        "=== JSON SCHEMA ===\n" + json.dumps(DIGEST_SCHEMA),
    ])
```

`src/news/grounding.py`:

```python
"""Deterministic grounding (spec §6.6): numbers must come from facts/headlines; evidence ids
must exist; a verdict without valid evidence is downgraded to "unclear"."""

from __future__ import annotations

import re

from src.news.schemas import DigestReads, Explanation, FactSheet

_NUM = re.compile(r"(?<![A-Za-z0-9])(\$)?([-+]?\d[\d,]*(?:\.(\d+))?)\s?(%|bps|bp|σ|x|×|[KMB]\b)?")
_SENT = re.compile(r"(?<=[.!?;])\s+")
_TEXT_FIELDS = ("headline", "read", "bull", "bear", "book_impact", "setup_impact")


def extract_numbers(text: str) -> list[tuple[float, int, bool]]:
    out = []
    for m in _NUM.finditer(text):
        dollar, raw, dec, unit = m.group(1), m.group(2), m.group(3), m.group(4)
        try:
            v = float(raw.replace(",", ""))
        except ValueError:
            continue
        decimals = len(dec) if dec else 0
        must = bool(dollar or unit or dec) or abs(v) > 10
        out.append((v, decimals, must))
    return out


def grounded(value: float, decimals: int, refs: list[float], rel_tol: float) -> bool:
    step = 10 ** -decimals if decimals else 0.5
    for r in refs:
        tol = max(rel_tol * abs(r), step)
        if abs(value - r) <= tol or abs(abs(value) - abs(r)) <= tol:
            return True
    return False


def strip_ungrounded(text: str, refs: list[float], rel_tol: float) -> tuple[str, bool]:
    kept, trimmed = [], False
    for sent in _SENT.split(text.strip()) if text.strip() else []:
        bad = any(must and not grounded(v, d, refs, rel_tol) for v, d, must in extract_numbers(sent))
        if bad:
            trimmed = True
        else:
            kept.append(sent)
    return " ".join(kept), trimmed


def ground(
    e: Explanation, *, facts: FactSheet, news_numbers: list[float], news_ids: set[str],
    rel_tol: float, fallback_what: str | None,
) -> tuple[Explanation, bool]:
    refs = facts.numbers() + news_numbers
    update: dict[str, object] = {}
    trimmed = False
    for field in _TEXT_FIELDS:
        new, t = strip_ungrounded(getattr(e, field), refs, rel_tol)
        trimmed |= t
        update[field] = new
    what, t = strip_ungrounded(e.what_happened, refs, rel_tol)
    if t or not what:
        trimmed |= t
        what = (fallback_what or what)[:180]
    update["what_happened"] = what
    valid = facts.ids() | news_ids
    evidence = [x for x in e.evidence if x in valid]
    update["evidence"] = evidence
    if not evidence and e.verdict != "unclear":
        update["verdict"], update["confidence"] = "unclear", "low"
    return e.model_copy(update=update), trimmed


def ground_digest(r: DigestReads, *, refs: list[float], valid_ids: set[str], rel_tol: float) -> DigestReads:
    items = []
    for it in r.items:
        read, _ = strip_ungrounded(it.read, refs, rel_tol)
        head, _ = strip_ungrounded(it.headline, refs, rel_tol)
        ev = [x for x in it.evidence if x in valid_ids]
        items.append(it.model_copy(update={"read": read, "headline": head or it.headline[:80],
                                           "evidence": ev, "verdict": it.verdict if ev else "unclear"}))
    return DigestReads(items=items)
```

Check `test_ground_digest_drops_bad_items`: item 2 "Crude +14%." — 14 is ungrounded → read "" ; evidence empty ⇒ verdict "unclear" (already). Item 1 "Yields up 9bp." — 9 with unit bp grounded by ref 9.0 ✓.

`src/news/explain.py`:

```python
"""Editor and writer passes with one validation retry and the deterministic fallback (spec §6.5–6.6)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import ValidationError

from src.claude.parser import _parse_dict_payload
from src.common.config import get_config
from src.news.grounding import extract_numbers, ground, ground_digest
from src.news.llm import call_llm, cap_reached
from src.news.playbook import PlaybookPrior
from src.news.prompts import (
    DIGEST_SCHEMA,
    EDITOR_SCHEMA,
    EXPLANATION_SCHEMA,
    digest_prompt,
    editor_prompt,
    number_headlines,
    writer_prompt,
)
from src.news.reaction import Reaction
from src.news.schemas import ClusterView, DigestRead, DigestReads, EditorOutput, Explanation, FactSheet, ItemView

log = logging.getLogger(__name__)


@dataclass
class ExplainOutcome:
    explanation: Explanation | None
    backend: str | None
    trimmed: bool
    stage: Literal["explained", "fallback"]
    note: str | None


def _validated[M](model: type[M], prompt: str, *, schema: dict, prefix: str, now: datetime) -> tuple[M | None, str | None]:
    res = call_llm(prompt, schema=schema, prefix=prefix, now=now)
    for attempt in (0, 1):
        if res is None:
            return None, None
        payload = _parse_dict_payload(res.text, prefix)
        try:
            return model.model_validate(payload or {}), res.backend  # type: ignore[attr-defined]
        except ValidationError as exc:
            if attempt == 1:
                log.info("%s: invalid output after retry: %s", prefix, exc)
                return None, res.backend
            res = call_llm(
                f"{prompt}\n\nYour previous reply failed validation. Validation error:\n{exc}\nReply again with valid JSON only.",
                schema=schema, prefix=prefix, now=now,
            )
    return None, None


def _note(now: datetime) -> str:
    return "🧠 off (daily cap)" if cap_reached(now) else "🧠 unavailable"


def explain_card(
    kind: str, *, headlines: list[ItemView], facts: FactSheet, prior: PlaybookPrior | None,
    reaction: Reaction | None, now: datetime, fallback_what: str | None = None,
) -> ExplainOutcome:
    block, index = number_headlines(headlines)
    prompt = writer_prompt(kind, headlines=block, facts=facts, prior=prior, reaction=reaction)
    expl, backend = _validated(Explanation, prompt, schema=EXPLANATION_SCHEMA, prefix=f"news:{kind}", now=now)
    if expl is None:
        return ExplainOutcome(None, backend, False, "fallback", _note(now))
    news_numbers = [v for it in headlines for v, _d, _m in extract_numbers(f"{it.title} {it.summary or ''}")]
    grounded_e, trimmed = ground(
        expl, facts=facts, news_numbers=news_numbers, news_ids=set(index),
        rel_tol=get_config().news.grounding.rel_tol, fallback_what=fallback_what,
    )
    return ExplainOutcome(grounded_e, backend, trimmed, "explained", None)


def edit_digest(clusters: list[ClusterView], backdrop: FactSheet, *, now: datetime) -> EditorOutput | None:
    if not clusters:
        return None
    out, _ = _validated(EditorOutput, editor_prompt(clusters, backdrop), schema=EDITOR_SCHEMA, prefix="news:editor", now=now)
    if out is None:
        return None
    known = {c.id for c in clusters}
    threads = [t.model_copy(update={"cluster_ids": [i for i in t.cluster_ids if i in known]}) for t in out.threads]
    return out.model_copy(update={"threads": [t for t in threads if t.cluster_ids]})


def digest_reads(threads: list[ClusterView], backdrop: FactSheet, *, now: datetime) -> dict[int, DigestRead]:
    if not threads:
        return {}
    out, _ = _validated(DigestReads, digest_prompt(threads, backdrop), schema=DIGEST_SCHEMA, prefix="news:digest", now=now)
    if out is None:
        return {}
    items = [it for c in threads for it in c.items[:2]]
    _, index = number_headlines(items)
    refs = backdrop.numbers() + [v for it in items for v, _d, _m in extract_numbers(it.title)]
    grounded_r = ground_digest(out, refs=refs, valid_ids=set(index) | backdrop.ids(), rel_tol=get_config().news.grounding.rel_tol)
    known = {c.id for c in threads}
    return {r.cluster_id: r for r in grounded_r.items if r.cluster_id in known and r.read}
```

`_validated` uses PEP 695 generics (Python 3.12) like `runner._run_cli[T]`; if mypy complains about `model.model_validate` on a bare type var, bound it: `def _validated[M: BaseModel](model: type[M], …)`.

- [ ] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/news/prompts.py src/news/grounding.py src/news/explain.py tests/test_news_grounding.py tests/test_news_explain.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): writer/editor/digest LLM passes with numeric + evidence grounding"
```

---

### Task 24: Two-stage edit flow + digest editor wiring

**Files:**
- Modify: `src/news/service.py`
- Create: `src/news/followup.py`
- Test: `tests/test_news_followup.py`

**Interfaces:**
- Produces (`src.news.followup`): `pending_posts(now: datetime, *, horizon_h: int = 3) -> list[tuple[int, CardPayload]]` (posts with `stage == "facts"`, alert kinds, posted within the horizon); `async complete_post(post_id: int, payload: CardPayload, *, now: datetime, cfg: Config, publisher: Publisher | None, measure: Callable = measure_reaction) -> bool` (macro: waits for the reaction window — returns False to retry later unless complete or `waited_too_long`; fills 📈 grid + reaction facts; then `explain_card`; then `update_post(..., count_edit=False, stage=…)`); `fallback_what(payload) -> str | None`.
- Changes (`NewsService`): new loop `followup` (every 30 s) calling `complete_post` for each pending post; `_digests` runs `edit_digest` + `digest_reads` before `build_digest` (sets `inp.regime`, `inp.thread_order`, `inp.reads`; falls back to deterministic ordering when either returns nothing).

- [ ] **Step 1: Failing test**

```python
# tests/test_news_followup.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from src.common.config import get_config
from src.news import followup as FU
from src.news.explain import ExplainOutcome
from src.news.reaction import AssetMove, Reaction
from src.news.schemas import CardPayload, Explanation, GridRow

REL = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)


def _macro() -> CardPayload:
    return CardPayload(kind="macro_print", title="CPI hotter than expected", emoji="🔴", when=REL, critical=True,
                       grid=[GridRow(asset="stocks", textbook="🔴")], grid_note="📈 reaction in ~15 min", event_keys=["k1"])


async def _seed(payload) -> int:
    from src.news.posting import post_card

    return await post_card(payload, publisher=None, cfg=get_config(), now=REL)


async def test_macro_waits_for_reaction_then_explains(news_db, monkeypatch) -> None:
    pid = await _seed(_macro())
    incomplete = Reaction(release_at=REL, window_min=15, complete=False, moves=[AssetMove(asset="stocks", symbol="ES=F")])
    assert not await FU.complete_post(pid, _macro(), now=REL + timedelta(minutes=10), cfg=get_config(), publisher=None,
                                      measure=lambda rel, cfg: incomplete)
    done = Reaction(release_at=REL, window_min=15, complete=True,
                    moves=[AssetMove(asset="stocks", symbol="ES=F", move=-1.2, unit="%", arrow="🔴")])
    e = Explanation(headline="h", what_happened="w", read="r", bull="b", bear="c", verdict="priced_in", confidence="low", evidence=["F1"])
    monkeypatch.setattr(FU, "explain_card", lambda *a, **k: ExplainOutcome(e, "cli", False, "explained", None))
    pub = AsyncMock()
    assert await FU.complete_post(pid, _macro(), now=REL + timedelta(minutes=16), cfg=get_config(), publisher=None,
                                  measure=lambda rel, cfg: done)
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    with news_session() as s:
        row = s.get(NewsPostRow, pid)
    assert row.stage == "explained" and row.edits == 0
    assert row.payload["grid"][0]["actual"] == "🔴 ES=F -1.20%" and row.payload["grid_note"] is None
    assert row.payload["explanation"]["verdict"] == "priced_in"


async def test_gives_up_waiting_and_marks_pending(news_db, monkeypatch) -> None:
    pid = await _seed(_macro())
    incomplete = Reaction(release_at=REL, window_min=15, complete=False, moves=[])
    monkeypatch.setattr(FU, "explain_card", lambda *a, **k: ExplainOutcome(None, None, False, "fallback", "🧠 unavailable"))
    assert await FU.complete_post(pid, _macro(), now=REL + timedelta(minutes=40), cfg=get_config(), publisher=None,
                                  measure=lambda rel, cfg: incomplete)
    from src.news.store.models import NewsPostRow
    from src.news.store.session import news_session

    with news_session() as s:
        row = s.get(NewsPostRow, pid)
    assert row.stage == "fallback" and row.payload["grid_note"] == "📈 reaction pending (data delayed)"
    assert row.payload["llm_note"] == "🧠 unavailable"


async def test_pending_posts_lists_only_alert_facts(news_db) -> None:
    pid = await _seed(_macro())
    await _seed(CardPayload(kind="digest_close", title="Close recap", emoji="🗞️", when=REL))
    assert [p for p, _ in FU.pending_posts(REL + timedelta(minutes=1))] == [pid]
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement** `src/news/followup.py`:

```python
"""Stage 2 of every alert (spec §7.2): once the reaction window has closed, fill 📈 and 🧠
and EDIT the same Telegram message. Edits made here do not count toward news.alerts.max_edits."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select

from src.common.config import Config
from src.news.explain import explain_card
from src.news.facts import build_macro_facts
from src.news.playbook import load_playbook, prior_for
from src.news.posting import update_post
from src.news.publish import Publisher
from src.news.reaction import Reaction, measure_reaction, waited_too_long
from src.news.schemas import CardPayload, GridRow, ItemView
from src.news.store import queries
from src.news.store.models import EconEventRow, NewsPostRow
from src.news.store.queries import naive_utc
from src.news.store.session import news_session

_ALERT_KINDS = ("macro_print", "earnings", "market_move", "vix_spike", "ticker_move", "breaking")  # briefs explain themselves (Task 28)


def pending_posts(now: datetime, *, horizon_h: int = 3) -> list[tuple[int, CardPayload]]:
    with news_session() as s:
        rows = s.scalars(
            select(NewsPostRow).where(
                NewsPostRow.stage == "facts",
                NewsPostRow.kind.in_(_ALERT_KINDS),
                NewsPostRow.posted_at >= naive_utc(now - timedelta(hours=horizon_h)),
            ).order_by(NewsPostRow.posted_at)
        )
        return [(r.id, CardPayload.model_validate(r.payload)) for r in rows]


def fallback_what(p: CardPayload) -> str | None:
    if p.headline_line:
        return p.headline_line[:180]
    if p.facts and p.facts.facts:
        return "; ".join(f.display for f in p.facts.facts[:2])[:180]
    return None


def _headlines(p: CardPayload) -> list[ItemView]:
    out: list[ItemView] = []
    with news_session() as s:
        for cid in p.cluster_ids[:3]:
            cv = queries.cluster_view(s, cid, max_items=3)
            if cv:
                out += cv.items
    return out


async def complete_post(
    post_id: int, payload: CardPayload, *, now: datetime, cfg: Config, publisher: Publisher | None,
    measure: Callable[..., Reaction] = lambda rel, cfg: measure_reaction(rel, cfg=cfg),
) -> bool:
    prior = reaction = None
    update: dict[str, object] = {}
    if payload.kind == "macro_print":
        reaction = await asyncio.to_thread(measure, payload.when, cfg.news.reaction)
        if not reaction.complete and not waited_too_long(payload.when, now, cfg.news.reaction):
            return False
        with news_session() as s:
            evs = [queries.econ_view(r) for r in (s.get(EconEventRow, k) for k in payload.event_keys) if r is not None]
        pb = load_playbook()
        entry = pb.match(evs[0].title) if evs else None
        prior = prior_for(entry, evs[0].surprise_dir) if entry and evs else None  # type: ignore[arg-type]
        update["grid"] = [GridRow(asset=g.asset, textbook=g.textbook, actual=reaction.display(g.asset)) for g in payload.grid]
        update["grid_note"] = None if reaction.complete else "📈 reaction pending (data delayed)"
        update["facts"] = build_macro_facts(evs, reaction=reaction, backdrop=None)
        payload = payload.model_copy(update=update)
        update = {}
    facts = payload.facts
    if facts is None:
        from src.news.schemas import FactSheet

        facts = FactSheet()
    outcome = await asyncio.to_thread(
        explain_card, payload.kind, headlines=_headlines(payload), facts=facts, prior=prior,
        reaction=reaction, now=now, fallback_what=fallback_what(payload),
    )
    payload = payload.model_copy(update={"explanation": outcome.explanation, "trimmed": outcome.trimmed, "llm_note": outcome.note})
    await update_post(post_id, payload, publisher=publisher, stage=outcome.stage, llm_backend=outcome.backend, count_edit=False)
    return True
```

The test passes `measure=lambda rel, cfg: …` — `complete_post` calls `measure(payload.when, cfg.news.reaction)` positionally, so the default lambda wraps `measure_reaction(rel, cfg=cfg)` the same way.

In `src/news/service.py` add:

```python
    async def _followup(self, now: datetime) -> None:
        from src.news.followup import complete_post, pending_posts

        for pid, payload in await asyncio.to_thread(pending_posts, now):
            try:
                await complete_post(pid, payload, now=now, cfg=self.cfg, publisher=self.publisher)
            except Exception:
                log.exception("news followup failed for post %s", pid)
```

and the loop `("followup", 30, self._followup)`. In `_digests`, before `build_digest`:

```python
            from src.news.explain import digest_reads, edit_digest
            from src.news.facts import build_market_facts

            backdrop = build_market_facts(inp.tape, self._backdrop(now))
            editor = await asyncio.to_thread(edit_digest, inp.clusters[:25], backdrop, now=now)
            if editor is not None:
                inp.regime = editor.regime
                inp.thread_order = [t.cluster_ids for t in editor.threads]
            order = inp.thread_order or [[c.id] for c in inp.clusters]
            by_id = {c.id: c for c in inp.clusters}
            threads = [by_id[ids[0]] for ids in order[: inp.max_threads] if ids[0] in by_id]
            inp.reads = await asyncio.to_thread(digest_reads, threads, backdrop, now=now)
```

Digests are posted once, complete (no two-stage), with `stage` left `"facts"` — so mark them: after `post_card`, call `update_post(pid, payload, publisher=None, stage="explained" if inp.reads else "fallback", count_edit=False)`; `pending_posts` ignores digest kinds anyway.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_news_followup.py tests/test_news_service.py -v` → PASS.

- [ ] **Step 5: Live check (manual, before go-live):** with `news.llm.backend: cli_then_ollama`, wait for one ticker or macro alert (or run `/news NVDA` once Task 29 lands) and confirm the card is edited with 🧠/🎯 within ~1 minute of the reaction window. Record timings in the progress log.

- [ ] **Step 6: Gate + commit**

```bash
git add src/news/followup.py src/news/service.py tests/test_news_followup.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): two-stage alerts (facts now, 📈+🧠 edit later) and LLM-ranked digests"
```

---

## Milestone 4 — Sentiment and reviewer read the store (spec §8)

### Task 25: `sentiment.py` reads the news store (deterministic only)

**Files:**
- Modify: `src/analytics/sentiment.py`, `src/news/store/queries.py`
- Test: `tests/test_news_sentiment_integration.py`, `tests/test_news_fence.py` (add the column whitelist test)

**Interfaces:**
- Produces (`queries`): `ticker_sentiment_rows(s: Session, symbol: str, since: datetime) -> list[tuple[float, datetime, int | None, str]]` — `(det_sentiment, published_at or fetched_at (aware), cluster_id, title)`; selects only `NewsItemRow.det_sentiment, published_at, fetched_at, cluster_id, title, tickers`.
- Produces (`sentiment`): `_news_from_store(symbol: str, *, now: datetime | None = None) -> tuple[float | None, int, str | None] | None` (None = store unavailable/empty → caller falls back); `_fetch_news` tries it first.

- [ ] **Step 1: Failing test**

```python
# tests/test_news_sentiment_integration.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)


def _seed(rows):
    from src.news.store.models import NewsItemRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    with news_session() as s:
        for i, (score, hours_ago, cluster, sym) in enumerate(rows):
            s.add(NewsItemRow(url_hash=f"u{i}", title_hash=f"t{i}", title=f"headline {i}", category="ticker", origin="google",
                              fetched_at=naive_utc(NOW - timedelta(hours=hours_ago)), tickers=[sym], tags=[], det_sentiment=score,
                              cluster_id=cluster))


def test_recency_weighted_store_sentiment(news_db) -> None:
    from src.analytics.sentiment import _news_from_store

    _seed([(0.8, 1, 1, "NVDA"), (-0.8, 48, 2, "NVDA"), (0.5, 2, 1, "NVDA"), (0.9, 1, 3, "AAPL"), (0.9, 100, 4, "NVDA")])
    score, count, top = _news_from_store("NVDA", now=NOW)
    assert count == 2  # distinct clusters within 72h (the 100h-old item is out)
    assert 50 < score < 90  # recent positives outweigh the 48h-old negative
    assert top == "headline 0"


def test_store_missing_falls_back_to_yfinance(tmp_path, monkeypatch) -> None:
    from src.analytics import sentiment
    from src.news.store import readonly

    readonly.reset_engine()
    monkeypatch.setattr(readonly, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    assert sentiment._news_from_store("NVDA", now=NOW) is None
    monkeypatch.setattr(sentiment, "_load_sentiment_cache", lambda s, src: None)
    monkeypatch.setattr(sentiment, "_save_sentiment_cache", lambda *a: None)
    monkeypatch.setattr("src.data.factory.get_news_provider", lambda: type("P", (), {"get_headlines": lambda self, s, limit=50: [{"title": "NVDA surges to record"}]})())
    score, count, top = sentiment._fetch_news.__wrapped__("NVDA")  # daily_cached uses functools.wraps
    assert count == 1 and top == "NVDA surges to record"
```

Add to `tests/test_news_fence.py`:

```python
def test_sentiment_reads_only_deterministic_news_columns() -> None:
    text = (ROOT / "src" / "analytics" / "sentiment.py").read_text(encoding="utf-8")
    for forbidden in ("NewsPostRow", "news_posts", "Explanation", "payload", "explain", "src.news.llm"):
        assert forbidden not in text, f"sentiment.py must not touch {forbidden}"
    q = (ROOT / "src" / "news" / "store" / "queries.py").read_text(encoding="utf-8")
    body = q[q.index("def ticker_sentiment_rows"):].split("\ndef ", 1)[0]
    assert "NewsPostRow" not in body and "payload" not in body
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement**

Append to `src/news/store/queries.py`:

```python
def ticker_sentiment_rows(s: Session, symbol: str, since: datetime) -> list[tuple[float, datetime, int | None, str]]:
    """Deterministic sentiment inputs only (spec §8 whitelist). Never reads news_posts."""
    rows = s.execute(
        select(
            NewsItemRow.det_sentiment, NewsItemRow.published_at, NewsItemRow.fetched_at,
            NewsItemRow.cluster_id, NewsItemRow.title, NewsItemRow.tickers,
        ).where(NewsItemRow.fetched_at >= naive_utc(since), NewsItemRow.det_sentiment.is_not(None))
    )
    sym = symbol.upper()
    out = []
    for det, pub, fetched, cid, title, tickers in rows:
        if sym in (tickers or []):
            out.append((float(det), aware_utc(pub or fetched), cid, title))
    return out
```

In `src/analytics/sentiment.py` add (near `_fetch_news`):

```python
def _news_from_store(symbol: str, *, now: datetime | None = None) -> tuple[float | None, int, str | None] | None:
    """Recency-weighted mean of the news store's deterministic per-headline sentiment for *symbol*
    (spec §8). None when the store is missing, unreadable, or has nothing for the symbol —
    the caller then uses the yfinance-only path unchanged. LLM output is never read here."""
    try:
        from src.common.config import get_config
        from src.news.store.queries import ticker_sentiment_rows
        from src.news.store.readonly import read_only_session
    except Exception:
        return None
    cfg = get_config().news.sentiment
    now = now or datetime.now(UTC)
    try:
        with read_only_session() as s:
            if s is None:
                return None
            rows = ticker_sentiment_rows(s, symbol, now - timedelta(hours=cfg.lookback_hours))
    except Exception as exc:
        logger.debug("news store sentiment read failed for %s: %s", symbol, exc)
        return None
    if not rows:
        return None
    num = den = 0.0
    for det, when, _cid, _title in rows:
        age_h = max(0.0, (now - when).total_seconds() / 3600)
        w = 0.5 ** (age_h / cfg.half_life_hours)
        num += w * det
        den += w
    newest = max(rows, key=lambda r: r[1])
    clusters = {cid for _d, _w, cid, _t in rows if cid is not None}
    return _bias_to_score(num / den if den else 0.0), len(clusters) or len(rows), newest[3]
```

and at the top of `_fetch_news` (before the disk-cache lookup, and without writing the disk cache when the store answered):

```python
    from_store = _news_from_store(symbol)
    if from_store is not None:
        return from_store
```

`_fetch_news` stays `@daily_cached`, so the scan reads the store at most once per symbol per day; the score is stable within a day (record this in STATUS, Task 34). The 0.05 ranking weight and the blend weights are unchanged.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_news_sentiment_integration.py tests/test_news_fence.py tests/test_sentiment*.py -v` → PASS.

- [ ] **Step 5: Gate + commit**

```bash
git add src/analytics/sentiment.py src/news/store/queries.py tests/test_news_sentiment_integration.py tests/test_news_fence.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(sentiment): read deduped, recency-weighted deterministic headline sentiment from the news store"
```

---

### Task 26: `news_context.py` prefers the store

**Files:**
- Modify: `src/claude/news_context.py`, `src/news/store/queries.py`
- Test: `tests/test_news_context.py` (extend)

**Interfaces:**
- Produces (`queries`): `recent_items_for(s, symbol: str, since: datetime, limit: int) -> list[ItemView]` (newest first, one item per cluster).
- Changes (`news_context`): `_fetch(query, days, limit)` — for a ticker-shaped query, first `_from_store(query, days, limit)`; if it returns items, use them and skip the live providers.

- [ ] **Step 1: Failing test** (append to `tests/test_news_context.py`):

```python
def test_ticker_query_uses_store_first(news_db, monkeypatch) -> None:
    from datetime import UTC, datetime

    from src.claude import news_context
    from src.news.store.models import NewsItemRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    with news_session() as s:
        s.add(NewsItemRow(url_hash="u", title_hash="t", title="NVDA wins big contract", url="https://r.com/a", source="Reuters",
                          category="ticker", origin="google", fetched_at=naive_utc(datetime.now(UTC)), tickers=["NVDA"],
                          tags=[], det_sentiment=0.5, cluster_id=1))

    def boom():
        raise AssertionError("live provider must not be called when the store has items")

    monkeypatch.setattr("src.data.factory.get_news_search_provider", boom)
    items = news_context._fetch("NVDA", 7, 5)
    assert [i.title for i in items] == ["NVDA wins big contract"]


def test_market_query_still_goes_live(news_db, monkeypatch) -> None:
    from src.claude import news_context
    from src.data.protocols import NewsItem

    monkeypatch.setattr("src.data.factory.get_news_search_provider",
                        lambda: type("S", (), {"search": lambda self, q, days=7, limit=10: [NewsItem(title="Stocks rally")]})())
    assert [i.title for i in news_context._fetch("stock market today", 7, 3)] == ["Stocks rally"]
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement**

`queries.py`:

```python
def recent_items_for(s: Session, symbol: str, since: datetime, limit: int) -> list[ItemView]:
    rows = s.scalars(
        select(NewsItemRow).where(NewsItemRow.fetched_at >= naive_utc(since)).order_by(NewsItemRow.fetched_at.desc()).limit(500)
    )
    out, seen = [], set()
    for r in rows:
        if symbol.upper() not in (r.tickers or []) or r.cluster_id in seen:
            continue
        seen.add(r.cluster_id)
        out.append(ItemView(title=r.title, url=r.url, source=r.source, source_domain=r.source_domain,
                            published_at=aware_utc(r.published_at) if r.published_at else None,
                            summary=r.summary, image_url=r.image_url, det_sentiment=r.det_sentiment))
        if len(out) >= limit:
            break
    return out
```

`news_context.py`:

```python
def _from_store(symbol: str, days: int, limit: int) -> list[NewsItem]:
    """The news service's deduped store first (spec §8) — read-only, never raises."""
    try:
        from datetime import UTC, datetime, timedelta

        from src.news.store.queries import recent_items_for
        from src.news.store.readonly import read_only_session

        with read_only_session() as s:
            if s is None:
                return []
            views = recent_items_for(s, symbol, datetime.now(UTC) - timedelta(days=days), limit)
    except Exception as exc:  # noqa: BLE001
        log.debug("news_context: store read failed for %s: %s", symbol, exc)
        return []
    return [NewsItem(title=v.title, source=v.source, published=v.published_at, url=v.url) for v in views]
```

and in `_fetch`, as the first statement:

```python
    if _looks_like_ticker(query):
        stored = _from_store(query, days, limit)
        if stored:
            return stored
```

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_news_context.py tests/test_eval_skills.py -v` → PASS.

- [ ] **Step 5: Gate + commit**

```bash
git add src/claude/news_context.py src/news/store/queries.py tests/test_news_context.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news_context): prefer the news store's deduped clusters for candidate headlines"
```

---

### Task 27: FinBERT option

**Files:**
- Modify: `src/news/tagging.py`, `src/news/ingest.py`
- Test: `tests/test_news_finbert.py`

**Interfaces:**
- Changes: `det_sentiment(text: str, model: Literal["vader", "finbert"] = "vader") -> float`; `ingest` passes `cfg.sentiment.model`. Adds `_finbert_pipeline()` (lazy, cached; `None` when `transformers` is unavailable or the model cannot load — logged once).

- [ ] **Step 1: Failing test**

```python
# tests/test_news_finbert.py
from __future__ import annotations

from src.news import tagging


def test_finbert_maps_labels(monkeypatch) -> None:
    monkeypatch.setattr(tagging, "_finbert_pipeline", lambda: (lambda text, truncation=True: [{"label": "negative", "score": 0.9}]))
    assert tagging.det_sentiment("Profit warning", model="finbert") == -0.9
    monkeypatch.setattr(tagging, "_finbert_pipeline", lambda: (lambda text, truncation=True: [{"label": "neutral", "score": 0.99}]))
    assert tagging.det_sentiment("Company holds meeting", model="finbert") == 0.0


def test_finbert_unavailable_falls_back_to_vader(monkeypatch) -> None:
    monkeypatch.setattr(tagging, "_finbert_pipeline", lambda: None)
    assert tagging.det_sentiment("Stocks crash", model="finbert") == tagging.det_sentiment("Stocks crash", model="vader")
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement** in `src/news/tagging.py`:

```python
import functools
import logging
from typing import Any, Literal

log = logging.getLogger(__name__)
_FINBERT_MODEL = "ProsusAI/finbert"


@functools.lru_cache(maxsize=1)
def _finbert_pipeline() -> Any:
    """FinBERT text-classification pipeline, or None (optional extra `finbert`; deterministic
    inference, no generation — spec §8). Loaded once per process."""
    try:
        from transformers import pipeline

        return pipeline("text-classification", model=_FINBERT_MODEL)
    except Exception as exc:  # noqa: BLE001
        log.warning("FinBERT unavailable (%s) — using VADER for news sentiment", exc)
        return None


def det_sentiment(text: str, model: Literal["vader", "finbert"] = "vader") -> float:
    if not text:
        return 0.0
    if model == "finbert":
        pipe = _finbert_pipeline()
        if pipe is not None:
            try:
                res = pipe(text[:512], truncation=True)[0]
                label, score = str(res["label"]).lower(), float(res["score"])
                return score if label == "positive" else -score if label == "negative" else 0.0
            except Exception:
                pass
    from src.analytics.sentiment import _keyword_bias, _vader_compound

    kb = _keyword_bias(text)
    return kb if kb != 0.0 else _vader_compound(text)
```

(Replace the Task 3 `det_sentiment`.) In `ingest.py`: `det_sentiment=tagging.det_sentiment(title, cfg.sentiment.model)`.

FinBERT's model download (~440 MB) happens on first use inside the news process; document in SETUP (Task 34) that enabling it means `pip install -e ".[finbert]"` and a one-time download.

- [ ] **Step 4: Run tests** → PASS. **Step 5: Gate + commit**

```bash
git add src/news/tagging.py src/news/ingest.py tests/test_news_finbert.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): optional FinBERT headline sentiment (falls back to VADER)"
```

---

## Milestone 5 — `/news TICKER` and the web `/news` page (spec §7.5–7.6)

### Task 28: Brief request queue + brief builder

**Files:**
- Create: `src/news/briefs.py` (queue — the only module `approval_service` imports), `src/news/brief_builder.py`
- Modify: `src/news/alerts.py` (rename `_ticker_card` → public `ticker_card`), `src/news/service.py` (briefs loop)
- Test: `tests/test_news_briefs.py`, `tests/test_news_fence.py` (briefs import test)

**Interfaces:**
- Produces (`briefs`): `SYMBOL_RE = r"^[A-Z][A-Z0-9.\-]{0,9}$"`; `InvalidSymbol(ValueError)`; `normalize_symbol(raw: str) -> str` (strips a leading `$`, upper-cases, validates); `enqueue_brief(symbol: str, origin: Literal["telegram", "web"], *, now: datetime | None = None) -> int` (creates `news.db` schema if missing; returns the existing request id when the same symbol is pending/running or finished within `news.briefs.dedupe_minutes`); `claim_next(now: datetime) -> tuple[int, str] | None`; `finish(req_id: int, *, now: datetime, post_id: int | None = None, error: str | None = None) -> None`; `latest_digest_link(chat_id: str, thread: str) -> str | None` (`https://t.me/c/<chat id without -100>/<thread>/<message id>` of the newest digest).
- Produces (`brief_builder`): `async build_brief(symbol: str, *, svc: NewsService, now: datetime) -> int` (fresh `collect_symbol` → `ticker_card(kind="brief")` with `critical=True` (the operator asked, so it notifies) → chart → `post_card` → `complete_post` (explains immediately) → returns post id).
- Note: `followup._ALERT_KINDS` (Task 24) already excludes `"brief"` — the builder explains briefs itself, so the followup loop must never double-call the LLM. Changes: `NewsService` loop `("briefs", news.briefs.poll_seconds, self._briefs)`.

- [ ] **Step 1: Failing test**

```python
# tests/test_news_briefs.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)


def test_normalize_symbol() -> None:
    from src.news.briefs import InvalidSymbol, normalize_symbol

    assert normalize_symbol("$nvda") == "NVDA" and normalize_symbol("brk.b") == "BRK.B"
    for bad in ("", "123", "NVDA;DROP", "A" * 11, "nv da"):
        with pytest.raises(InvalidSymbol):
            normalize_symbol(bad)


def test_enqueue_dedupes_and_claims(news_db) -> None:
    from src.news.briefs import claim_next, enqueue_brief, finish

    a = enqueue_brief("nvda", "telegram", now=NOW)
    assert enqueue_brief("NVDA", "web", now=NOW + timedelta(minutes=1)) == a
    assert claim_next(NOW) == (a, "NVDA")
    assert claim_next(NOW) is None
    finish(a, now=NOW + timedelta(minutes=2), post_id=9)
    assert enqueue_brief("NVDA", "web", now=NOW + timedelta(minutes=5)) == a  # just finished → reuse
    assert enqueue_brief("NVDA", "web", now=NOW + timedelta(minutes=30)) != a


def test_enqueue_creates_schema_when_db_absent(tmp_path, monkeypatch) -> None:
    import src.news.store.session as rw
    from src.news.briefs import enqueue_brief

    monkeypatch.setattr(rw, "_engine", None)
    monkeypatch.setattr(rw, "_SessionLocal", None)
    monkeypatch.setattr(rw, "_resolve_url", lambda: f"sqlite:///{tmp_path / 'fresh.db'}")
    assert enqueue_brief("AAPL", "telegram", now=NOW) == 1


def test_latest_digest_link(news_db) -> None:
    from src.news.briefs import latest_digest_link
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    assert latest_digest_link("-1001234567890", "4409") is None
    with news_session() as s:
        s.add(NewsPostRow(kind="digest_close", telegram_message_id=77, posted_at=naive_utc(NOW), payload={}, cluster_ids=[],
                          silent=False, critical=False, edits=0, stage="explained"))
    assert latest_digest_link("-1001234567890", "4409") == "https://t.me/c/1234567890/4409/77"


async def test_build_brief_posts_and_explains(news_db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.news import brief_builder as BB
    from src.news.schemas import CardPayload
    from src.news.service import NewsService

    svc = NewsService(get_config())
    svc.publisher = None
    monkeypatch.setattr(svc.collector, "collect_symbol", lambda sym, now: None)
    monkeypatch.setattr(svc, "_alert_ctx", lambda now, tape_now=None: None)
    monkeypatch.setattr(BB, "ticker_card", lambda c, ctx, kind: CardPayload(kind="brief", subject="TSM", title="TSM brief", emoji="📰", when=NOW))
    monkeypatch.setattr(BB, "ticker_chart", lambda *a, **k: None)
    explained = []

    async def fake_complete(pid, payload, **kw):
        explained.append(pid)
        return True

    monkeypatch.setattr(BB, "complete_post", fake_complete)
    pid = await BB.build_brief("TSM", svc=svc, now=NOW)
    assert explained == [pid]
```

Add to `tests/test_news_fence.py`:

```python
def test_brief_queue_stays_light() -> None:
    """approval_service imports src.news.briefs; it must not drag LLM/ingest/publish code in (spec §10.7)."""
    heavy = ("src.news.llm", "src.news.explain", "src.news.collectors", "src.news.publish", "src.news.brief_builder",
             "src.news.service", "src.claude", "src.analytics")
    mods = imported_modules(ROOT / "src" / "news" / "briefs.py")
    bad = [m for m in mods if any(m == h or m.startswith(h + ".") for h in heavy)]
    assert not bad, f"src/news/briefs.py imports {bad}"
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement**

`src/news/briefs.py`:

```python
"""Brief request queue (spec §7.5) — the ONLY src.news module approval_service imports
(fence §10.7). One insert, one read, nothing else: no LLM, ingest or publish code is loaded
into the trading bot's process."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select

from src.common.config import get_config
from src.news.store.models import NewsPostRow, NewsRequestRow
from src.news.store.queries import naive_utc
from src.news.store.session import init_news_db, news_session

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class InvalidSymbol(ValueError):
    pass


def normalize_symbol(raw: str) -> str:
    sym = (raw or "").strip().lstrip("$").upper()
    if not SYMBOL_RE.match(sym):
        raise InvalidSymbol(raw)
    return sym


def enqueue_brief(symbol: str, origin: Literal["telegram", "web"], *, now: datetime | None = None) -> int:
    sym = normalize_symbol(symbol)
    now_n = naive_utc(now or datetime.now(UTC))
    recent = now_n - timedelta(minutes=get_config().news.briefs.dedupe_minutes)
    init_news_db()  # idempotent; the approval process may enqueue before the news process ever ran
    with news_session() as s:
        existing = s.scalar(
            select(NewsRequestRow)
            .where(NewsRequestRow.symbol == sym)
            .where(
                (NewsRequestRow.status.in_(("pending", "running")))
                | ((NewsRequestRow.status == "done") & (NewsRequestRow.finished_at >= recent))
            )
            .order_by(NewsRequestRow.id.desc())
        )
        if existing is not None:
            return existing.id
        row = NewsRequestRow(symbol=sym, origin=origin, status="pending", requested_at=now_n)
        s.add(row)
        s.flush()
        return row.id


def claim_next(now: datetime) -> tuple[int, str] | None:
    with news_session() as s:
        row = s.scalar(select(NewsRequestRow).where(NewsRequestRow.status == "pending").order_by(NewsRequestRow.id))
        if row is None:
            return None
        row.status, row.started_at = "running", naive_utc(now)
        return row.id, row.symbol


def finish(req_id: int, *, now: datetime, post_id: int | None = None, error: str | None = None) -> None:
    with news_session() as s:
        row = s.get(NewsRequestRow, req_id)
        if row is None:
            return
        row.status = "failed" if error else "done"
        row.finished_at, row.post_id, row.error = naive_utc(now), post_id, (error or None) and error[:300]


def latest_digest_link(chat_id: str, thread: str) -> str | None:
    with news_session() as s:
        mid = s.scalar(
            select(NewsPostRow.telegram_message_id)
            .where(NewsPostRow.kind.like("digest_%"), NewsPostRow.telegram_message_id.is_not(None))
            .order_by(NewsPostRow.posted_at.desc())
        )
    if mid is None or not chat_id.startswith("-100"):
        return None
    return f"https://t.me/c/{chat_id[4:]}/{thread}/{mid}" if thread else f"https://t.me/c/{chat_id[4:]}/{mid}"
```

`src/news/brief_builder.py`:

```python
"""Build and post an on-demand ticker brief (spec §7.5.2). Runs only in the news process."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from src.news.alerts import ticker_card
from src.news.followup import complete_post
from src.news.posting import post_card, ticker_chart
from src.news.triggers import AlertCandidate

if TYPE_CHECKING:
    from src.news.service import NewsService


async def build_brief(symbol: str, *, svc: NewsService, now: datetime) -> int:
    await asyncio.to_thread(svc.collector.collect_symbol, symbol, now)
    ctx = await asyncio.to_thread(svc._alert_ctx, now, None)
    cand = AlertCandidate(kind="ticker_move", subject=symbol, critical=True, symbols=[symbol])
    payload = await asyncio.to_thread(ticker_card, cand, ctx, kind="brief")
    payload = payload.model_copy(update={"critical": True})
    chart = None
    if payload.facts is not None and ctx is not None:
        chart = await asyncio.to_thread(ticker_chart, symbol, payload.facts, ctx.an, ctx.positions, ctx.today)
    pid = await post_card(payload, publisher=svc.publisher, cfg=svc.cfg, now=now, chart=chart)
    await complete_post(pid, payload, now=now, cfg=svc.cfg, publisher=svc.publisher)
    return pid
```

In `src/news/alerts.py` rename `_ticker_card` → `ticker_card` (update `build_card`).

In `src/news/service.py`:

```python
    async def _briefs(self, now: datetime) -> None:
        from src.news.brief_builder import build_brief
        from src.news.briefs import claim_next, finish

        while (job := await asyncio.to_thread(claim_next, now)) is not None:
            req_id, symbol = job
            try:
                pid = await build_brief(symbol, svc=self, now=self.clock())
                await asyncio.to_thread(finish, req_id, now=self.clock(), post_id=pid)
            except Exception as exc:
                log.exception("news brief %s failed", symbol)
                await asyncio.to_thread(finish, req_id, now=self.clock(), error=str(exc))
```

and the loop entry `("briefs", self.ncfg.briefs.poll_seconds, self._briefs)`. On service start, reset requests left `running` by a crash back to `pending` (one `UPDATE` in `run()` before the loops start).

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_news_briefs.py tests/test_news_fence.py tests/test_news_followup.py -v` → PASS.

- [ ] **Step 5: Gate + commit**

```bash
git add src/news/briefs.py src/news/brief_builder.py src/news/alerts.py src/news/service.py tests/test_news_briefs.py tests/test_news_fence.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(news): brief request queue and on-demand ticker brief builder"
```

---

### Task 29: `/news` Telegram command

**Files:**
- Modify: `src/notify/approval_service.py` (handler + registration), `src/notify/formatters.py` (`format_help`)
- Test: `tests/test_news_command.py`

**Interfaces:**
- Consumes: `src.news.briefs.enqueue_brief`, `normalize_symbol`, `InvalidSymbol`, `latest_digest_link`.
- Produces: `async handle_news_command(update, context) -> None`; `CommandHandler("news", handle_news_command)` registered next to `/scan`; help lines `"/news TICKER — News brief with implications \\(posts in the News thread\\)"` and `"/news — Link to the latest news digest"` under a new `*News*` heading.

- [ ] **Step 1: Failing test**

```python
# tests/test_news_command.py
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture()
def upd(monkeypatch):
    import src.notify.approval_service as svc

    monkeypatch.setattr(svc, "_is_authorized", lambda u: True)
    msg = SimpleNamespace(reply_text=AsyncMock())
    return SimpleNamespace(message=msg, effective_chat=SimpleNamespace(id=-1001234567890))


async def test_news_ticker_enqueues_and_replies(upd, monkeypatch) -> None:
    import src.notify.approval_service as svc

    seen = {}
    monkeypatch.setattr("src.news.briefs.enqueue_brief", lambda sym, origin: seen.update(sym=sym, origin=origin) or 5)
    await svc.handle_news_command(upd, SimpleNamespace(args=["nvda"]))
    assert seen == {"sym": "nvda", "origin": "telegram"}
    assert "NVDA" in upd.message.reply_text.await_args.args[0] and "News thread" in upd.message.reply_text.await_args.args[0]


async def test_news_rejects_garbage(upd) -> None:
    import src.notify.approval_service as svc

    await svc.handle_news_command(upd, SimpleNamespace(args=["DROP;TABLE"]))
    assert "not a ticker" in upd.message.reply_text.await_args.args[0].lower()


async def test_news_without_args_links_latest_digest(upd, monkeypatch) -> None:
    import src.notify.approval_service as svc

    monkeypatch.setattr("src.news.briefs.latest_digest_link", lambda chat, thread: "https://t.me/c/1/4409/77")
    await svc.handle_news_command(upd, SimpleNamespace(args=[]))
    text = upd.message.reply_text.await_args.args[0]
    assert "https://t.me/c/1/4409/77" in text and "/news TICKER" in text


def test_help_lists_news() -> None:
    from src.notify.formatters import format_help

    assert "/news TICKER" in format_help()
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement** in `src/notify/approval_service.py` (beside `handle_scan_command`):

```python
async def handle_news_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/news TICKER — queue an on-demand news brief (built and posted by the news process to the
    News thread). /news — link to the latest digest. Only the brief queue is imported here (spec §10.7)."""
    if not _is_authorized(update) or update.message is None:
        return
    from src.news import briefs

    cfg = get_config()
    if not context.args:
        link = await asyncio.to_thread(briefs.latest_digest_link, cfg.secrets.telegram_chat_id, cfg.secrets.telegram_thread_news)
        tail = f"\nLatest digest: {link}" if link else "\nNo digest posted yet."
        await update.message.reply_text("Usage: /news TICKER (e.g. /news NVDA)" + tail)
        return
    raw = context.args[0]
    try:
        sym = briefs.normalize_symbol(raw)
        await asyncio.to_thread(briefs.enqueue_brief, raw, "telegram")
    except briefs.InvalidSymbol:
        await update.message.reply_text(f"{raw!r} is not a ticker. Usage: /news NVDA")
        return
    await update.message.reply_text(f"📰 Building {sym} brief → News thread")
```

Registration: `app.add_handler(CommandHandler("news", handle_news_command))` after the `/scan` line. Help: add a `*News*` block to `format_help()` (MarkdownV2-escaped like its neighbours):

```python
        "*News*",
        "/news TICKER — News brief with implications \\(posts in the News thread\\)",
        "/news — Link to the latest news digest",
        "",
```

The first test patches `src.news.briefs.enqueue_brief` with a two-positional-arg lambda; the handler calls `enqueue_brief(raw, "telegram")` positionally, so it matches. `normalize_symbol` is not patched and accepts `"nvda"`.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_news_command.py tests/test_news_fence.py -v` → PASS.

- [ ] **Step 5: Gate + commit**

```bash
git add src/notify/approval_service.py src/notify/formatters.py tests/test_news_command.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(notify): /news TICKER command queues a news brief; /news links the latest digest"
```

---

### Task 30: `news_brief` command kind (web → drain → queue)

**Files:**
- Modify: `src/api/models/commands.py`, `src/notify/command_drain.py`, `docs/web/commands.md`
- Test: `tests/test_drain_news_brief.py`, plus any test that enumerates kinds (`grep -rn "LEDGER_CA_REVIEWED" tests` — update each expected set)

**Interfaces:**
- Produces: `CommandKind.NEWS_BRIEF = "news_brief"`; `NewsBriefPayload(symbol: str)` with `model_config = ConfigDict(extra="forbid")` and `symbol: str = Field(pattern=r"^\$?[A-Za-z][A-Za-z0-9.\-]{0,9}$")`; repeatable (`dedupe_key_for` returns `None`; the news process dedupes); drain handler `@register("news_brief") _news_brief(*, payload, **_) -> {"request_id": int, "symbol": str}`. Not in `_LIVE_CONFIRM_KINDS` (it cannot reach an order). No Telegram notification from the drain (the brief itself is the notification).

- [ ] **Step 1: Failing test**

```python
# tests/test_drain_news_brief.py
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.models.commands import CommandKind, NewsBriefPayload, dedupe_key_for, validate_payload


def test_payload_validation() -> None:
    assert validate_payload(CommandKind.NEWS_BRIEF, {"symbol": "nvda"}).symbol == "nvda"
    for bad in ({"symbol": "DROP;TABLE"}, {"symbol": ""}, {"symbol": "NVDA", "x": 1}):
        with pytest.raises(ValidationError):
            validate_payload(CommandKind.NEWS_BRIEF, bad)
    assert dedupe_key_for(CommandKind.NEWS_BRIEF, NewsBriefPayload(symbol="NVDA")) is None


async def test_drain_handler_enqueues(monkeypatch) -> None:
    from src.notify import command_drain

    monkeypatch.setattr("src.news.briefs.enqueue_brief", lambda sym, origin: 42)
    handler = command_drain.HANDLERS["news_brief"]
    out = handler(ib=None, bot=None, chat_id="x", command=None, payload={"symbol": "nvda"})
    assert out == {"request_id": 42, "symbol": "NVDA"}


def test_post_commands_accepts_news_brief(client) -> None:
    from tests.conftest import OWNER

    r = client.post("/commands", headers=OWNER, json={"kind": "news_brief", "payload": {"symbol": "TSM"}})
    assert r.status_code in (200, 201) and r.json()["kind"] == "news_brief"
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement**

`src/api/models/commands.py`: add `NEWS_BRIEF = "news_brief"` to `CommandKind`; add

```python
class NewsBriefPayload(BaseModel):
    """Ask the news process for an on-demand ticker brief (spec §7.6). Cannot reach an order."""

    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=r"^\$?[A-Za-z][A-Za-z0-9.\-]{0,9}$")
```

add `CommandKind.NEWS_BRIEF: NewsBriefPayload` to `PAYLOAD_FOR`, and `CommandKind.NEWS_BRIEF` to the repeatable tuple in `dedupe_key_for` (extend its docstring: "news_brief is repeatable — the news process dedupes a symbol within `news.briefs.dedupe_minutes`").

`src/notify/command_drain.py`:

```python
# ---------------------------------------------------------------------------
# News thread (docs/superpowers/specs/2026-10-09-news-thread-design.md §7.6) — news_brief.
#
# Inserts one news_requests row through src.news.briefs (the only src.news module this process
# may import, spec §10.7). Creates no candidate, approval or order; no live confirm token; no
# Telegram message from here — the brief itself lands in the News thread.
# ---------------------------------------------------------------------------


@register("news_brief")
def _news_brief(*, payload: dict, **_: Any) -> dict:
    from src.news import briefs

    try:
        sym = briefs.normalize_symbol(str(payload.get("symbol", "")))
        req = briefs.enqueue_brief(sym, "web")
    except briefs.InvalidSymbol as exc:
        raise CommandFailed("invalid_symbol") from exc
    return {"request_id": req, "symbol": sym}
```

`docs/web/commands.md`: add a `### \`news_brief\` — ask for an on-demand news brief` entry under "Every kind", matching the neighbours' layout: payload `{"symbol": "NVDA"}`, repeatable (no dedupe key), no confirmation, what the drain does (one `news_requests` insert via `src.news.briefs.enqueue_brief`), result `{"request_id": int, "symbol": str}`, failure reason `invalid_symbol`, and that the page polls `GET /news/ticker/{symbol}` for the brief.

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_drain_news_brief.py tests/test_command_schemas.py tests/test_api_commands.py tests/test_write_path_invariants.py tests/test_web_fence.py -v` → PASS.

- [ ] **Step 5: Gate + commit**

```bash
git add src/api/models/commands.py src/notify/command_drain.py docs/web/commands.md tests/test_drain_news_brief.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(web): news_brief command kind drained into the news brief queue"
```

---

### Task 31: Read-only `/news/*` API + nav section

**Files:**
- Create: `src/api/news_db.py`, `src/api/models/news.py`, `src/api/routers/news.py`
- Modify: `src/api/main.py` (include router), `src/api/routers/meta.py` (`_SECTIONS` gains `("news", "News", True, None)` after `ledger`), `src/news/store/queries.py` (API readers), `tests/test_api_meta.py` (expected sections), `docs/web/api.md`
- Test: `tests/test_api_news.py`

**Interfaces:**
- Produces (`src.api.news_db`): `_resolve_path() -> str` (patched in tests), `reset_engine() -> None`, `news_read_session() -> ContextManager[Session | None]` (`mode=ro`; `None` when the file is missing/unopenable).
- Produces (`queries`): `KIND_GROUPS = {"macro": ("macro_print", "breaking"), "market": ("market_move", "vix_spike", "digest_premarket", "digest_close", "digest_week"), "tickers": ("ticker_move",), "earnings": ("earnings",), "briefs": ("brief",)}`; `recent_posts(s, *, group: str | None, symbol: str | None, limit: int, before_id: int | None) -> list[NewsPostRow]`; `latest_brief(s, symbol) -> NewsPostRow | None`; `request_for(s, symbol) -> NewsRequestRow | None`; `state_values(s, prefix: str) -> dict[str, str]`.
- Produces (routes, owner-only): `GET /news/feed`, `GET /news/posts/{id}`, `GET /news/calendar?days=7`, `GET /news/ticker/{symbol}`, `GET /news/status` with response models in `src/api/models/news.py` (all subclass `Envelope`, all carry `available: bool`).

- [ ] **Step 1: Failing test**

```python
# tests/test_api_news.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import OWNER

NOW = datetime.now(UTC)


@pytest.fixture()
def news_client(client, news_db, monkeypatch):
    import src.api.news_db as nd

    nd.reset_engine()
    monkeypatch.setattr(nd, "_resolve_path", lambda: str(news_db))
    yield client
    nd.reset_engine()


def _post(kind="ticker_move", subject="NVDA", chart_path=None, **payload):
    from src.news.schemas import CardPayload
    from src.news.store.models import NewsPostRow
    from src.news.store.queries import naive_utc
    from src.news.store.session import news_session

    p = CardPayload(kind=kind, subject=subject, title=payload.get("title", f"{subject} -6.2%"), emoji="📉", when=NOW)
    with news_session() as s:
        row = NewsPostRow(kind=kind, subject=subject, posted_at=naive_utc(NOW), payload=p.model_dump(mode="json"), cluster_ids=[],
                          silent=False, critical=False, edits=0, stage="explained", chart_path=chart_path)
        s.add(row)
        s.flush()
        return row.id


def test_requires_owner(news_client) -> None:
    assert news_client.get("/news/feed").status_code == 401


def test_feed_filters_and_paginates(news_client) -> None:
    a = _post()
    _post(kind="earnings", subject="AAPL")
    _post(kind="digest_close", subject=None, title="Close recap")
    body = news_client.get("/news/feed", headers=OWNER).json()
    assert body["available"] is True and len(body["posts"]) == 3
    assert [p["kind"] for p in news_client.get("/news/feed?group=earnings", headers=OWNER).json()["posts"]] == ["earnings"]
    assert [p["subject"] for p in news_client.get("/news/feed?symbol=nvda", headers=OWNER).json()["posts"]] == ["NVDA"]
    older = news_client.get(f"/news/feed?before={a + 1}", headers=OWNER).json()["posts"]
    assert all(p["id"] <= a for p in older)
    assert news_client.get("/news/feed?group=bogus", headers=OWNER).status_code == 422


def test_post_detail_inlines_chart(news_client, tmp_path, monkeypatch) -> None:
    from src.common.config import get_config

    charts = tmp_path / "charts"
    charts.mkdir()
    (charts / "1.png").write_bytes(b"\x89PNG\r\n")
    monkeypatch.setattr(get_config().news, "charts_dir", str(charts))
    pid = _post(chart_path=str(charts / "1.png"))
    body = news_client.get(f"/news/posts/{pid}", headers=OWNER).json()
    assert body["post"]["payload"]["title"] == "NVDA -6.2%"
    assert body["chart_data_uri"].startswith("data:image/png;base64,")
    assert news_client.get("/news/posts/999", headers=OWNER).status_code == 404


def test_chart_outside_charts_dir_is_refused(news_client, tmp_path, monkeypatch) -> None:
    from src.common.config import get_config

    monkeypatch.setattr(get_config().news, "charts_dir", str(tmp_path / "charts"))
    evil = tmp_path / "secret.png"
    evil.write_bytes(b"x")
    pid = _post(chart_path=str(evil))
    assert news_client.get(f"/news/posts/{pid}", headers=OWNER).json()["chart_data_uri"] is None


def test_ticker_and_status(news_client) -> None:
    from src.news.briefs import enqueue_brief
    from src.news.store.state import set_state

    _post(kind="brief", subject="TSM", title="TSM brief")
    enqueue_brief("TSM", "web")
    set_state("heartbeat", NOW.isoformat())
    t = news_client.get("/news/ticker/tsm", headers=OWNER).json()
    assert t["latest_brief"]["payload"]["title"] == "TSM brief" and t["request"]["status"] == "pending"
    st = news_client.get("/news/status", headers=OWNER).json()
    assert st["available"] and st["heartbeat_age_s"] is not None and st["llm_cap"] == 40


def test_news_routes_when_db_missing(client, tmp_path, monkeypatch) -> None:
    import src.api.news_db as nd

    nd.reset_engine()
    monkeypatch.setattr(nd, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    for path in ("/news/feed", "/news/calendar", "/news/ticker/NVDA", "/news/status"):
        r = client.get(path, headers=OWNER)
        assert r.status_code == 200 and r.json()["available"] is False, path
```

- [ ] **Step 2: Run to fail.** **Step 3: Implement**

`src/api/news_db.py`:

```python
"""Read-only access to data/news.db for the web API (spec §7.6, fence §10.6).

The API never imports src.news.store.session (the news process's read-write engine). Opens
SQLite with mode=ro; yields None when the file does not exist yet, so every /news route can
answer `available: false` instead of a 500 on a fresh install.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.common.config import get_config

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_path() -> str:
    url = get_config().news_db_url_abs()
    return url[len("sqlite:///") :] if url.startswith("sqlite:///") else url


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None


@contextmanager
def news_read_session() -> Iterator[Session | None]:
    global _engine, _SessionLocal
    path = _resolve_path()
    if not Path(path).exists():
        yield None
        return
    try:
        if _engine is None:
            _engine = create_engine(f"sqlite:///file:{path}?mode=ro&uri=true", future=True, connect_args={"timeout": 5})
            _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
        assert _SessionLocal is not None
        s = _SessionLocal()
        s.execute(text("SELECT 1"))
    except Exception:
        yield None
        return
    try:
        yield s
    finally:
        s.rollback()
        s.close()
```

Append to `src/news/store/queries.py`:

```python
from src.news.store.models import NewsPostRow, NewsRequestRow, NewsStateRow  # merge into the top import

KIND_GROUPS: dict[str, tuple[str, ...]] = {
    "macro": ("macro_print", "breaking"),
    "market": ("market_move", "vix_spike", "digest_premarket", "digest_close", "digest_week"),
    "tickers": ("ticker_move",),
    "earnings": ("earnings",),
    "briefs": ("brief",),
}


def recent_posts(s: Session, *, group: str | None, symbol: str | None, limit: int, before_id: int | None) -> list[NewsPostRow]:
    q = select(NewsPostRow)
    if group:
        q = q.where(NewsPostRow.kind.in_(KIND_GROUPS[group]))
    if symbol:
        q = q.where(NewsPostRow.subject == symbol.upper())
    if before_id:
        q = q.where(NewsPostRow.id < before_id)
    return list(s.scalars(q.order_by(NewsPostRow.id.desc()).limit(limit)))


def latest_brief(s: Session, symbol: str) -> NewsPostRow | None:
    return s.scalar(
        select(NewsPostRow).where(NewsPostRow.kind == "brief", NewsPostRow.subject == symbol.upper()).order_by(NewsPostRow.id.desc())
    )


def request_for(s: Session, symbol: str) -> NewsRequestRow | None:
    return s.scalar(select(NewsRequestRow).where(NewsRequestRow.symbol == symbol.upper()).order_by(NewsRequestRow.id.desc()))


def state_values(s: Session, prefix: str) -> dict[str, str]:
    return {r.key: r.value for r in s.scalars(select(NewsStateRow).where(NewsStateRow.key.like(f"{prefix}%")))}
```

`src/api/models/news.py`:

```python
"""Response models for GET /news/* (spec §7.6)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from src.api.models.common import Envelope


class NewsPostOut(BaseModel):
    id: int
    kind: str
    subject: str | None
    posted_at: datetime
    stage: str
    critical: bool
    silent: bool
    has_chart: bool
    payload: dict


class NewsFeedResponse(Envelope):
    available: bool
    posts: list[NewsPostOut] = []


class NewsPostDetailResponse(Envelope):
    available: bool
    post: NewsPostOut
    chart_data_uri: str | None = None


class EconEventOut(BaseModel):
    title: str
    scheduled_at: datetime
    impact: str
    forecast: str | None
    previous: str | None
    actual: str | None
    surprise_dir: str | None


class EarningsOut(BaseModel):
    symbol: str
    report_date: date
    timing: str
    eps_est: float | None
    eps_actual: float | None
    status: str
    held: bool = False


class NewsCalendarResponse(Envelope):
    available: bool
    econ: list[EconEventOut] = []
    earnings: list[EarningsOut] = []


class ClusterOut(BaseModel):
    id: int
    headline: str
    source_count: int
    last_seen: datetime
    links: list[dict] = []


class NewsRequestOut(BaseModel):
    id: int
    status: str
    requested_at: datetime
    post_id: int | None
    error: str | None


class NewsTickerResponse(Envelope):
    available: bool
    symbol: str
    latest_brief: NewsPostOut | None = None
    clusters: list[ClusterOut] = []
    next_earnings: EarningsOut | None = None
    request: NewsRequestOut | None = None


class NewsStatusResponse(Envelope):
    available: bool
    heartbeat_at: datetime | None = None
    heartbeat_age_s: float | None = None
    sources_ok: dict[str, datetime] = {}
    llm_calls_today: int = 0
    llm_cap: int = 0
```

`src/api/routers/news.py`:

```python
"""GET /news/* — read-only views over data/news.db (spec §7.6). Every write is the news_brief
command (POST /commands); this router never writes and never imports the news process's engine."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from src.api.deps import OwnerUser, TradingDb
from src.api.models.news import (
    ClusterOut,
    EarningsOut,
    EconEventOut,
    NewsCalendarResponse,
    NewsFeedResponse,
    NewsPostDetailResponse,
    NewsPostOut,
    NewsRequestOut,
    NewsStatusResponse,
    NewsTickerResponse,
)
from src.api.news_db import news_read_session
from src.api.portfolio_source import read_portfolio
from src.common.config import ROOT, get_config
from src.news.links import links_for
from src.news.store import queries
from src.news.store.models import NewsPostRow
from src.news.store.queries import aware_utc

router = APIRouter(prefix="/news", tags=["news"])
ET = ZoneInfo("America/New_York")
Group = Literal["macro", "market", "tickers", "earnings", "briefs"]


def _now() -> datetime:
    return datetime.now(UTC)


def _post_out(r: NewsPostRow) -> NewsPostOut:
    return NewsPostOut(id=r.id, kind=r.kind, subject=r.subject, posted_at=aware_utc(r.posted_at), stage=r.stage,
                       critical=r.critical, silent=r.silent, has_chart=bool(r.chart_path), payload=r.payload or {})


def _charts_dir() -> Path:
    d = Path(get_config().news.charts_dir)
    return (d if d.is_absolute() else ROOT / d).resolve()


def _chart_uri(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path).resolve()
    if _charts_dir() not in p.parents or not p.is_file():
        return None
    return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()


@router.get("/feed", response_model=NewsFeedResponse)
def feed(_: OwnerUser, group: Group | None = None, symbol: str | None = None,
         limit: int = Query(30, ge=1, le=100), before: int | None = None) -> NewsFeedResponse:
    with news_read_session() as s:
        if s is None:
            return NewsFeedResponse(as_of=_now(), available=False)
        rows = queries.recent_posts(s, group=group, symbol=symbol, limit=limit, before_id=before)
        return NewsFeedResponse(as_of=_now(), available=True, posts=[_post_out(r) for r in rows])


@router.get("/posts/{post_id}", response_model=NewsPostDetailResponse)
def post_detail(post_id: int, _: OwnerUser) -> NewsPostDetailResponse:
    with news_read_session() as s:
        row = s.get(NewsPostRow, post_id) if s is not None else None
        if row is None:
            raise HTTPException(status_code=404, detail="Post not found")
        return NewsPostDetailResponse(as_of=_now(), available=True, post=_post_out(row), chart_data_uri=_chart_uri(row.chart_path))


def _held(db: Session) -> set[str]:
    """Held underlyings from the trading DB the API already reads (never src.news.collectors —
    that module loads the news process's read-write engine)."""
    snap = read_portfolio(db).snapshot
    return {(p.underlying or p.symbol).upper() for p in (snap.positions if snap else []) if p.position != 0}


@router.get("/calendar", response_model=NewsCalendarResponse)
def calendar(_: OwnerUser, db: TradingDb, days: int = Query(7, ge=1, le=21)) -> NewsCalendarResponse:
    now = _now()
    with news_read_session() as s:
        if s is None:
            return NewsCalendarResponse(as_of=now, available=False)
        econ = queries.econ_events_between(s, now - timedelta(hours=12), now + timedelta(days=days))
        today = now.astimezone(ET).date()
        earn = queries.earnings_between(s, today, today + timedelta(days=days))
    held = _held(db)
    return NewsCalendarResponse(
        as_of=now, available=True,
        econ=[EconEventOut(title=e.title, scheduled_at=e.scheduled_at, impact=e.impact, forecast=e.forecast,
                           previous=e.previous, actual=e.actual, surprise_dir=e.surprise_dir) for e in econ],
        earnings=[EarningsOut(symbol=e.symbol, report_date=e.report_date, timing=e.timing, eps_est=e.eps_est,
                              eps_actual=e.eps_actual, status=e.status, held=e.symbol in held) for e in earn],
    )


@router.get("/ticker/{symbol}", response_model=NewsTickerResponse)
def ticker(symbol: str, _: OwnerUser) -> NewsTickerResponse:
    sym = symbol.upper()
    now = _now()
    with news_read_session() as s:
        if s is None:
            return NewsTickerResponse(as_of=now, available=False, symbol=sym)
        brief = queries.latest_brief(s, sym)
        clusters = queries.clusters_since(s, now - timedelta(hours=72), symbol=sym, limit=10)
        today = now.astimezone(ET).date()
        upcoming = queries.earnings_between(s, today - timedelta(days=1), today + timedelta(days=60), {sym})
        req = queries.request_for(s, sym)
        rank = get_config().news.source_rank
        return NewsTickerResponse(
            as_of=now, available=True, symbol=sym,
            latest_brief=_post_out(brief) if brief else None,
            clusters=[ClusterOut(id=c.id, headline=c.headline, source_count=c.source_count, last_seen=c.last_seen,
                                 links=[l.model_dump() for l in links_for(c, rank)]) for c in clusters],
            next_earnings=(EarningsOut(symbol=sym, report_date=upcoming[0].report_date, timing=upcoming[0].timing,
                                       eps_est=upcoming[0].eps_est, eps_actual=upcoming[0].eps_actual, status=upcoming[0].status)
                           if upcoming else None),
            request=(NewsRequestOut(id=req.id, status=req.status, requested_at=aware_utc(req.requested_at),
                                    post_id=req.post_id, error=req.error) if req else None),
        )


@router.get("/status", response_model=NewsStatusResponse)
def status(_: OwnerUser) -> NewsStatusResponse:
    now = _now()
    cfg = get_config().news.llm
    with news_read_session() as s:
        if s is None:
            return NewsStatusResponse(as_of=now, available=False, llm_cap=cfg.max_calls_per_day)
        hb = queries.state_values(s, "heartbeat").get("heartbeat")
        src = queries.state_values(s, "source_ok:")
        calls = queries.state_values(s, f"llm_calls:{now.astimezone(ET).date().isoformat()}")
    hb_at = datetime.fromisoformat(hb) if hb else None
    return NewsStatusResponse(
        as_of=now, available=True, heartbeat_at=hb_at,
        heartbeat_age_s=(now - hb_at).total_seconds() if hb_at else None,
        sources_ok={k.split(":", 1)[1]: datetime.fromisoformat(v) for k, v in src.items()},
        llm_calls_today=int(next(iter(calls.values()), 0)), llm_cap=cfg.max_calls_per_day,
    )
```

The router reaches held positions through the trading DB (`read_portfolio`) and links through `src.news.links` — never `src.news.collectors`/`src.news.alerts`, which load the news process's read-write engine. `test_api_never_imports_the_rw_engine` (Task 12) checks direct imports only; add a transitive check to `tests/test_news_fence.py` now:

```python
def test_api_process_never_loads_the_rw_engine() -> None:
    import subprocess, sys
    code = "import src.api.main, sys; print('src.news.store.session' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, env={**__import__('os').environ, "IBKR_CONFIG_USE_EXAMPLES": "1"})
    assert out.stdout.strip() == "False", out.stderr
```

Register: in `src/api/main.py` import `news` with the other routers and `app.include_router(news.router)`. In `meta.py` add `("news", "News", True, None)` after `ledger` (comment: `# "news" added with the news thread (docs/superpowers/specs/2026-10-09-news-thread-design.md §7.6).`) and add `"news"` to `tests/test_api_meta.py`'s expected set. Document the five routes in `docs/web/api.md` (same table layout as the ledger routes). Then regenerate `docs/web/openapi.json` the way the repo does it (check `docs/web/api.md` for the command; the web `npm run gen:api` needs the API up).

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_api_news.py tests/test_api_meta.py tests/test_web_fence.py tests/test_news_fence.py -v` → PASS.

- [ ] **Step 5: Gate + commit**

```bash
git add src/api/news_db.py src/api/models/news.py src/api/routers/news.py src/api/main.py src/api/routers/meta.py src/news/store/queries.py tests/test_api_news.py tests/test_api_meta.py tests/test_news_fence.py docs/web/api.md docs/web/openapi.json docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(api): read-only /news feed, post, calendar, ticker and status routes"
```

---

### Task 32: Web `/news` and `/news/[symbol]` pages

**Files:**
- Create: `web/app/news/page.tsx`, `web/app/news/[symbol]/page.tsx`, `web/components/news/types.ts`, `web/components/news/format.ts`, `web/components/news/VerdictPill.tsx`, `web/components/news/NewsCard.tsx`, `web/components/news/NewsFeed.tsx`, `web/components/news/CalendarColumn.tsx`, `web/components/news/NewsTicker.tsx`, `web/components/news/BriefRequest.tsx`
- Modify: `web/components/shell/RailSection.tsx` (`HREF.news = "/news"`), `web/CLAUDE.md` (Layout block: `news/` entry)
- Test: `web/components/news/NewsCard.test.tsx`, `web/components/news/NewsFeed.test.tsx`, `web/components/news/NewsTicker.test.tsx`

**Interfaces:**
- Consumes: `GET /news/feed|posts/{id}|calendar|ticker/{symbol}|status` (Task 31), `submitCommand("news_brief", {symbol})`, `useCommandStatus`, `CommandReceipt` (existing), `apiFetch`, `renderWithQuery` test helper.
- Produces: React components; types mirror `src/api/models/news.py` and `CardPayload` (`web/components/news/types.ts`).

- [ ] **Step 1: Failing tests**

```tsx
// web/components/news/NewsCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NewsCard } from "./NewsCard";
import type { NewsPost } from "./types";

const POST: NewsPost = {
  id: 1, kind: "macro_print", subject: null, posted_at: "2026-10-14T12:31:00Z", stage: "explained",
  critical: true, silent: false, has_chart: false,
  payload: {
    kind: "macro_print", title: "CPI hotter than expected", emoji: "🔴", when: "2026-10-14T12:30:00Z",
    headline_line: "CPI m/m 0.4% vs 0.3% est",
    grid: [{ asset: "stocks", textbook: "🔴", actual: "🔴 ES=F -1.20%" }],
    explanation: { headline: "h", what_happened: "w", read: "Inflation re-accelerating.", bull: "core cooling", bear: "shelter sticky",
      verdict: "further_downside_likely", confidence: "medium", book_impact: "NVDA 165P 3.1% OTM", setup_impact: "", evidence: ["F1"] },
    links: [{ name: "BLS", url: "https://www.bls.gov/x" }], updates: [], sections: [],
  },
};

describe("NewsCard", () => {
  it("renders the grid, verdict as text plus icon, book line and inline links", () => {
    render(<NewsCard post={POST} />);
    expect(screen.getByText("CPI hotter than expected")).toBeInTheDocument();
    expect(screen.getByTestId("grid-stocks")).toHaveTextContent("ES=F -1.20%");
    expect(screen.getByTestId("verdict")).toHaveTextContent("Further downside likely");
    expect(screen.getByText(/NVDA 165P 3.1% OTM/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "BLS" })).toHaveAttribute("href", "https://www.bls.gov/x");
  });

  it("never renders an em dash in UI copy", () => {
    const { container } = render(<NewsCard post={POST} />);
    expect(container.textContent).not.toContain("—");
  });
});
```

```tsx
// web/components/news/NewsFeed.test.tsx
import { screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { NewsFeed } from "./NewsFeed";

const ISO = new Date().toISOString();
const post = (id: number, kind: string, title: string) => ({
  id, kind, subject: null, posted_at: ISO, stage: "explained", critical: false, silent: false, has_chart: false,
  payload: { kind, title, emoji: "📰", when: ISO, grid: [], links: [], updates: [], sections: [] },
});

describe("NewsFeed", () => {
  it("lists posts and switches group with the chips", async () => {
    renderWithQuery(<NewsFeed />, {
      "/news/feed?limit=30": { as_of: ISO, available: true, posts: [post(2, "earnings", "AAPL earnings"), post(1, "macro_print", "CPI")] },
      "/news/feed?group=earnings&limit=30": { as_of: ISO, available: true, posts: [post(2, "earnings", "AAPL earnings")] },
      "/news/calendar?days=7": { as_of: ISO, available: true, econ: [], earnings: [] },
    });
    expect(await screen.findByText("CPI")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Earnings" }));
    expect(await screen.findByText("AAPL earnings")).toBeInTheDocument();
    expect(apiFetchMock().mock.calls.some((c) => String(c[0]).includes("group=earnings"))).toBe(true);
  });

  it("says the news service has not run yet when unavailable", async () => {
    renderWithQuery(<NewsFeed />, {
      "/news/feed?limit=30": { as_of: ISO, available: false, posts: [] },
      "/news/calendar?days=7": { as_of: ISO, available: false, econ: [], earnings: [] },
    });
    expect(await screen.findByText(/news service has not written anything yet/i)).toBeInTheDocument();
  });
});
```

```tsx
// web/components/news/NewsTicker.test.tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { NewsTicker } from "./NewsTicker";

const ISO = new Date().toISOString();

describe("NewsTicker", () => {
  it("shows the latest brief and the request button", async () => {
    renderWithQuery(<NewsTicker symbol="tsm" />, {
      "/news/ticker/TSM": {
        as_of: ISO, available: true, symbol: "TSM",
        latest_brief: { id: 4, kind: "brief", subject: "TSM", posted_at: ISO, stage: "explained", critical: true, silent: false, has_chart: true,
          payload: { kind: "brief", title: "TSM brief", emoji: "📰", when: ISO, grid: [], links: [], updates: [], sections: [] } },
        clusters: [{ id: 1, headline: "TSMC beats on AI demand", source_count: 3, last_seen: ISO, links: [] }],
        next_earnings: null, request: null,
      },
      "/news/posts/4": { as_of: ISO, available: true, post: { id: 4 }, chart_data_uri: "data:image/png;base64,AAAA" },
      "/options/controls": { drain_healthy: true },
    });
    expect(await screen.findByText("TSM brief")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /request fresh brief/i })).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /TSM chart/i })).toHaveAttribute("src", "data:image/png;base64,AAAA");
    expect(screen.getByText("TSMC beats on AI demand")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to fail** — `cd web && npm run test -- news` → FAIL (modules missing).

- [ ] **Step 3: Implement**

`web/components/news/types.ts`:

```ts
export type Verdict = "further_downside_likely" | "further_upside_likely" | "overreaction_likely" | "priced_in" | "unclear";
export type SourceLink = { name: string; url: string };
export type GridRow = { asset: string; textbook: string | null; actual: string | null };
export type Explanation = {
  headline: string; what_happened: string; read: string; bull: string; bear: string;
  verdict: Verdict; confidence: "low" | "medium" | "high"; book_impact: string; setup_impact: string; evidence: string[];
};
export type DigestItem = { text: string; read?: string | null; verdict?: Verdict | null; links: SourceLink[] };
export type DigestSection = { title: string; items: DigestItem[] };
export type CardPayload = {
  kind: string; subject?: string | null; title: string; emoji: string; when: string;
  headline_line?: string | null; facts_line?: string | null; grid: GridRow[]; grid_note?: string | null;
  explanation?: Explanation | null; trimmed?: boolean; llm_note?: string | null; regime?: string | null;
  sections: DigestSection[]; links: SourceLink[]; image_url?: string | null; updates: string[];
};
export type NewsPost = {
  id: number; kind: string; subject: string | null; posted_at: string; stage: string;
  critical: boolean; silent: boolean; has_chart: boolean; payload: CardPayload;
};
export type NewsFeedResponse = { as_of: string; available: boolean; posts: NewsPost[] };
export type EconEvent = { title: string; scheduled_at: string; impact: string; forecast: string | null; previous: string | null; actual: string | null; surprise_dir: string | null };
export type Earnings = { symbol: string; report_date: string; timing: string; eps_est: number | null; eps_actual: number | null; status: string; held: boolean };
export type NewsCalendarResponse = { as_of: string; available: boolean; econ: EconEvent[]; earnings: Earnings[] };
export type Cluster = { id: number; headline: string; source_count: number; last_seen: string; links: SourceLink[] };
export type NewsTickerResponse = {
  as_of: string; available: boolean; symbol: string; latest_brief: NewsPost | null; clusters: Cluster[];
  next_earnings: Earnings | null; request: { id: number; status: string; requested_at: string; post_id: number | null; error: string | null } | null;
};
export type NewsPostDetail = { as_of: string; available: boolean; post: NewsPost; chart_data_uri: string | null };
```

`web/components/news/format.ts`:

```ts
const SGT = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Singapore", hour: "2-digit", minute: "2-digit", hour12: false });
const ET = new Intl.DateTimeFormat("en-GB", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false });
const DAY = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Singapore", weekday: "short", day: "2-digit", month: "short" });

export function whenLabel(iso: string): string {
  const d = new Date(iso);
  return `${SGT.format(d)} SGT (${ET.format(d)} ET)`;
}
export function dayLabel(iso: string): string {
  return DAY.format(new Date(iso));
}
export const VERDICT_LABEL: Record<string, string> = {
  further_downside_likely: "Further downside likely",
  further_upside_likely: "Further upside likely",
  overreaction_likely: "Overreaction likely",
  priced_in: "Priced in",
  unclear: "Unclear",
};
```

`web/components/news/VerdictPill.tsx` — state is text + icon, never colour alone:

```tsx
import type { Verdict } from "./types";
import { VERDICT_LABEL } from "./format";

const ICON: Record<Verdict, string> = {
  further_downside_likely: "▼", further_upside_likely: "▲", overreaction_likely: "↺", priced_in: "=", unclear: "?",
};
const TONE: Record<Verdict, string> = {
  further_downside_likely: "text-loss", further_upside_likely: "text-gain", overreaction_likely: "text-content",
  priced_in: "text-muted", unclear: "text-unknown",
};

export function VerdictPill({ verdict, confidence }: { verdict: Verdict; confidence?: string }) {
  return (
    <span data-testid="verdict" className={`inline-flex items-center gap-1 rounded-sm bg-elevated px-2 py-0.5 text-xs ${TONE[verdict]}`}>
      <span aria-hidden="true">{ICON[verdict]}</span>
      {VERDICT_LABEL[verdict]}
      {confidence ? <span className="text-muted"> · {confidence}</span> : null}
    </span>
  );
}
```

`web/components/news/NewsCard.tsx`:

```tsx
import type { NewsPost } from "./types";
import { whenLabel } from "./format";
import { VerdictPill } from "./VerdictPill";

export function NewsCard({ post, chartUri }: { post: NewsPost; chartUri?: string | null }) {
  const p = post.payload;
  const e = p.explanation;
  return (
    <article className="space-y-3 rounded-md bg-surface p-4" data-testid={`news-card-${post.id}`}>
      <header className="flex flex-wrap items-baseline gap-2">
        <span aria-hidden="true">{p.emoji}</span>
        <h3 className="text-sm font-medium text-content">{p.title}</h3>
        <span className="font-mono text-xs text-muted tabular">{whenLabel(p.when)}</span>
        {post.critical && <span className="text-xs text-unknown">critical</span>}
      </header>
      {p.image_url && <img src={p.image_url} alt="" className="max-h-48 w-full rounded-sm object-cover" />}
      {p.headline_line && (
        <p className="text-sm text-content">
          {p.headline_line}
          {p.links.length > 0 && <span className="text-muted"> · </span>}
          {p.links.slice(0, 3).map((l, i) => (
            <span key={l.url}>
              {i > 0 && <span className="text-muted"> · </span>}
              <a href={l.url} target="_blank" rel="noreferrer" className="underline decoration-border hover:text-content">{l.name}</a>
            </span>
          ))}
        </p>
      )}
      {p.facts_line && <p className="font-mono text-xs text-muted tabular">{p.facts_line}</p>}
      {p.grid.length > 0 && (
        <table className="w-full text-xs">
          <thead className="text-left text-muted"><tr><th className="pr-4">Asset</th><th className="pr-4">Textbook</th><th>Actual (15m)</th></tr></thead>
          <tbody>
            {p.grid.map((g) => (
              <tr key={g.asset} data-testid={`grid-${g.asset}`} className="border-t border-border">
                <td className="py-1 pr-4 capitalize">{g.asset}</td>
                <td className="py-1 pr-4">{g.textbook ?? "·"}</td>
                <td className="py-1 font-mono tabular">{g.actual ?? "pending"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {p.grid_note && <p className="text-xs text-muted">{p.grid_note}</p>}
      {e && (
        <div className="space-y-1 text-sm">
          <p className="text-content">{e.read}</p>
          <p className="text-muted">Bull: {e.bull} · Bear: {e.bear}</p>
          <VerdictPill verdict={e.verdict} confidence={e.confidence} />
          {e.book_impact && <p className="text-content">Your book: {e.book_impact}</p>}
          {e.setup_impact && <p className="text-content">Setups: {e.setup_impact}</p>}
          {p.trimmed && <p className="text-xs text-unknown">Some unsupported numbers were removed.</p>}
        </div>
      )}
      {p.llm_note && <p className="text-xs text-muted">{p.llm_note}</p>}
      {p.sections.map((s) => (
        <section key={s.title} className="space-y-1">
          <h4 className="text-xs font-medium text-muted">{s.title}</h4>
          <ul className="space-y-1 text-sm">
            {s.items.map((it, i) => (
              <li key={i}>
                {it.text}
                {it.read && <span className="block text-muted">{it.read}</span>}
                {it.verdict && <VerdictPill verdict={it.verdict} />}
              </li>
            ))}
          </ul>
        </section>
      ))}
      {p.updates.map((u) => <p key={u} className="text-xs text-muted">{u}</p>)}
      {chartUri && <img src={chartUri} alt={`${post.subject ?? "News"} chart`} className="w-full rounded-sm" />}
    </article>
  );
}
```

(`🔄 Update` strings come from the server with an em dash-free format — Task 19's `apply_update` uses `·`, never `—`. Keep it that way; the em-dash test covers card copy.)

`web/components/news/CalendarColumn.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { dayLabel, whenLabel } from "./format";
import type { NewsCalendarResponse } from "./types";

export function CalendarColumn() {
  const q = useQuery({ queryKey: ["news", "calendar"], queryFn: () => apiFetch<NewsCalendarResponse>("/news/calendar?days=7"),
                       placeholderData: (prev) => prev, refetchInterval: 5 * 60_000 });
  if (!q.data?.available) return null;
  return (
    <aside className="space-y-4" data-testid="news-calendar">
      <section>
        <h2 className="pb-2 text-sm font-medium text-content">Economic calendar</h2>
        <ul className="space-y-1 text-xs">
          {q.data.econ.map((e) => (
            <li key={`${e.scheduled_at}-${e.title}`} className="flex justify-between gap-2">
              <span>{e.title}</span>
              <span className="font-mono text-muted tabular">
                {e.actual ? `${e.actual} vs ${e.forecast ?? "n/a"}` : whenLabel(e.scheduled_at)}
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2 className="pb-2 text-sm font-medium text-content">Earnings</h2>
        <ul className="space-y-1 text-xs">
          {q.data.earnings.map((e) => (
            <li key={`${e.symbol}-${e.report_date}`} className="flex justify-between gap-2">
              <a href={`/news/${e.symbol}`} className="font-mono">{e.symbol}{e.held ? " · held" : ""}</a>
              <span className="text-muted">{dayLabel(e.report_date)} {e.timing.toUpperCase()}</span>
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
```

`web/components/news/NewsFeed.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { CalendarColumn } from "./CalendarColumn";
import { NewsCard } from "./NewsCard";
import type { NewsFeedResponse } from "./types";

const GROUPS: { key: string | null; label: string }[] = [
  { key: null, label: "All" }, { key: "macro", label: "Macro" }, { key: "market", label: "Market" },
  { key: "tickers", label: "Tickers" }, { key: "earnings", label: "Earnings" }, { key: "briefs", label: "Briefs" },
];

export function NewsFeed() {
  const [group, setGroup] = useState<string | null>(null);
  const [symbol, setSymbol] = useState("");
  const params = new URLSearchParams();
  if (group) params.set("group", group);
  if (symbol.trim()) params.set("symbol", symbol.trim().toUpperCase());
  params.set("limit", "30");
  const path = `/news/feed?${params.toString()}`;
  const q = useQuery({ queryKey: ["news", "feed", path], queryFn: () => apiFetch<NewsFeedResponse>(path),
                       placeholderData: (prev) => prev, refetchInterval: 60_000 });

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]" data-testid="news-feed">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {GROUPS.map((g) => (
            <button key={g.label} type="button" onClick={() => setGroup(g.key)} aria-pressed={group === g.key}
              className={`rounded-sm px-3 py-1 text-sm ${group === g.key ? "bg-elevated text-content" : "text-muted hover:text-content"} focus-visible:ring-focus`}>
              {g.label}
            </button>
          ))}
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="Symbol"
            className="ml-auto w-28 rounded-sm bg-background px-2 py-1 font-mono text-sm text-content" aria-label="Filter by symbol" />
        </div>
        {q.isError && <p className="text-sm text-muted">Could not load the news feed.</p>}
        {q.data && !q.data.available && <p className="text-sm text-muted">The news service has not written anything yet.</p>}
        {q.data?.available && q.data.posts.length === 0 && <p className="text-sm text-muted">No posts match.</p>}
        {q.data?.posts.map((p) => <NewsCard key={p.id} post={p} />)}
      </div>
      <CalendarColumn />
    </div>
  );
}
```

`web/components/news/BriefRequest.tsx` (mirrors `RefreshControl`):

```tsx
"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, ApiError } from "@/lib/api";
import { submitCommand, useCommandStatus, type CommandStatus } from "@/lib/commands";
import { CommandReceipt } from "@/components/options/CommandReceipt";
import type { ControlsResponse } from "@/components/options/types";

export function BriefRequest({ symbol }: { symbol: string }) {
  const [command, setCommand] = useState<CommandStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const qc = useQueryClient();
  const controls = useQuery({ queryKey: ["options", "controls"], queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
                              placeholderData: (prev) => prev, refetchInterval: 30_000 });
  const commandQuery = useCommandStatus(command?.id ?? null);
  const current = (commandQuery.data ?? command) as CommandStatus | null;

  useEffect(() => {
    if (current && current.status !== "pending") qc.invalidateQueries({ queryKey: ["news", "ticker", symbol] });
  }, [current, qc, symbol]);

  async function onClick() {
    setError(null);
    setSubmitting(true);
    try {
      setCommand(await submitCommand("news_brief", { symbol }));
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403 ? "You do not have permission to do this." : "The request could not be created.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button type="button" onClick={onClick} disabled={submitting || current?.status === "pending"}
        className="rounded-sm border border-border bg-background px-3 py-1.5 text-sm text-content enabled:hover:bg-elevated disabled:opacity-50 focus-visible:ring-focus">
        Request fresh brief
      </button>
      {error && <p className="text-xs text-loss" role="alert">{error}</p>}
      {current && <CommandReceipt command={current} order={null} drainHealthy={controls.data?.drain_healthy ?? true} plainReasons={["invalid_symbol"]} />}
    </div>
  );
}
```

`web/components/news/NewsTicker.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { BriefRequest } from "./BriefRequest";
import { NewsCard } from "./NewsCard";
import { dayLabel } from "./format";
import type { NewsPostDetail, NewsTickerResponse } from "./types";

export function NewsTicker({ symbol }: { symbol: string }) {
  const sym = symbol.toUpperCase();
  const t = useQuery({
    queryKey: ["news", "ticker", sym], queryFn: () => apiFetch<NewsTickerResponse>(`/news/ticker/${encodeURIComponent(sym)}`),
    placeholderData: (prev) => prev,
    refetchInterval: (q) => (q.state.data?.request && ["pending", "running"].includes(q.state.data.request.status) ? 3_000 : 60_000),
  });
  const briefId = t.data?.latest_brief?.id;
  const detail = useQuery({ queryKey: ["news", "post", briefId], enabled: Boolean(briefId && t.data?.latest_brief?.has_chart),
                            queryFn: () => apiFetch<NewsPostDetail>(`/news/posts/${briefId}`) });

  return (
    <div className="space-y-4" data-testid="news-ticker">
      <header className="flex items-center justify-between gap-4">
        <h1 className="font-mono text-lg text-content">{sym}</h1>
        <BriefRequest symbol={sym} />
      </header>
      {t.data?.next_earnings && (
        <p className="text-sm text-muted">Next earnings {dayLabel(t.data.next_earnings.report_date)} {t.data.next_earnings.timing.toUpperCase()}</p>
      )}
      {t.data && !t.data.available && <p className="text-sm text-muted">The news service has not written anything yet.</p>}
      {t.data?.available && !t.data.latest_brief && <p className="text-sm text-muted">No brief yet. Request one above.</p>}
      {t.data?.latest_brief && <NewsCard post={t.data.latest_brief} chartUri={detail.data?.chart_data_uri ?? null} />}
      {t.data && t.data.clusters.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-content">Recent stories</h2>
          <ul className="space-y-1 text-sm">
            {t.data.clusters.map((c) => (
              <li key={c.id}>
                {c.headline} <span className="text-muted">· {c.source_count} sources</span>
                {c.links.slice(0, 2).map((l) => (
                  <a key={l.url} href={l.url} target="_blank" rel="noreferrer" className="ml-2 text-xs underline decoration-border">{l.name}</a>
                ))}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
```

Pages:

```tsx
// web/app/news/page.tsx
import { NewsFeed } from "@/components/news/NewsFeed";

export default function NewsPage() {
  return <NewsFeed />;
}
```

```tsx
// web/app/news/[symbol]/page.tsx
"use client";

import { use } from "react";
import { NewsTicker } from "@/components/news/NewsTicker";

export default function NewsTickerPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  return <NewsTicker symbol={symbol} />;
}
```

`RailSection.tsx`: add `news: "/news",` to `HREF`. `web/CLAUDE.md` Layout: add a `news/` entry under `app/` describing the feed + calendar page and the ticker page with the brief request.

`NewsTicker.test.tsx`'s mock map keys are full paths; confirm `renderWithQuery`'s matching rule (exact path vs prefix) in `web/lib/test-query.tsx` and adjust keys (`/news/ticker/TSM`) if it needs the encoded form.

- [ ] **Step 4: Run tests** — `cd web && npm run test && npm run lint && npx tsc --noEmit` → PASS.

- [ ] **Step 5: Visual check (manual):** `cd web && npm run dev` with the API up; open `/news` and `/news/NVDA`; confirm dark tokens, mono numbers, verdict pill text, inline links open in a new tab, the chart renders, and "Request fresh brief" produces a receipt and (with the news service running) a brief within ~1–2 min. Record in the progress log.

- [ ] **Step 6: Gate + commit**

```bash
git add web/app/news web/components/news web/components/shell/RailSection.tsx web/CLAUDE.md docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(web): /news feed with calendar and /news/[symbol] brief page"
```

---

## Milestone 6 — Operable and documented

### Task 33: Watchdog news-staleness check

**Files:**
- Modify: `src/ops/watchdog.py`, `src/common/config.py` (`WatchdogCfg.news_max_age_minutes: int = 30`), `config/settings.example.yaml` (`watchdog.news_max_age_minutes: 30`)
- Test: `tests/test_news_watchdog.py`

**Interfaces:**
- Produces: `news_check(now: datetime, *, max_age_min: int) -> Check` (reads the heartbeat through `src.news.store.readonly`; `Check("news", False, "news: data/news.db missing — news service never ran")` when absent); `run_checks` appends it when `get_config().news.enabled`.

- [ ] **Step 1: Failing test**

```python
# tests/test_news_watchdog.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

NOW = datetime(2026, 10, 14, 15, tzinfo=UTC)


def test_news_check_fresh_and_stale(news_db) -> None:
    from src.news.store.state import touch_heartbeat
    from src.ops.watchdog import news_check

    touch_heartbeat(NOW - timedelta(minutes=5))
    assert news_check(NOW, max_age_min=30).ok
    touch_heartbeat(NOW - timedelta(minutes=45))
    c = news_check(NOW, max_age_min=30)
    assert not c.ok and "45" in c.detail


def test_news_check_when_db_missing(tmp_path, monkeypatch) -> None:
    from src.news.store import readonly
    from src.ops.watchdog import news_check

    readonly.reset_engine()
    monkeypatch.setattr(readonly, "_resolve_path", lambda: str(tmp_path / "absent.db"))
    c = news_check(NOW, max_age_min=30)
    assert not c.ok and "missing" in c.detail
```

`Check` is `NamedTuple(name, ok, detail)` (`src/ops/watchdog.py:62`, verified 2026-10-09).

- [ ] **Step 2: Run to fail.** **Step 3: Implement** in `src/ops/watchdog.py`:

```python
def news_check(now: datetime, *, max_age_min: int) -> Check:
    """The news service writes a heartbeat into data/news.db after every loop iteration."""
    from src.news.store.queries import state_values
    from src.news.store.readonly import read_only_session

    with read_only_session() as s:
        if s is None:
            return Check("news", False, "news: data/news.db missing — news service never ran")
        hb = state_values(s, "heartbeat").get("heartbeat")
    return heartbeat_check("news", hb, now, max_age_min=max_age_min)
```

and in `run_checks`, after the `command_drain` heartbeat:

```python
    if full_cfg.news.enabled:
        checks.append(news_check(now, max_age_min=cfg.news_max_age_minutes))
```

(`heartbeat_check` already produces "last heartbeat N min ago (limit M)".)

- [ ] **Step 4: Run tests** — `.venv/bin/python -m pytest tests/test_news_watchdog.py tests/test_watchdog*.py -v` → PASS.

- [ ] **Step 5: Gate + commit**

```bash
git add src/ops/watchdog.py src/common/config.py config/settings.example.yaml tests/test_news_watchdog.py docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "feat(ops): watchdog alerts when the news service heartbeat goes stale"
```

---

### Task 34: Documentation, final gate, live verification

**Files:**
- Modify: `ARCHITECTURE.md`, `SETUP.md`, `STATUS.md`, `README.md`, `CLAUDE.md`, `.env.example` (verify), `docs/superpowers/specs/2026-10-09-news-thread-design.md` (status line → "Implemented")

- [ ] **Step 1: ARCHITECTURE.md** — per CLAUDE.md's mandatory doc table:
  - Folder guide: new `src/news/` section listing every module with one line each (`store/models.py`, `store/session.py`, `store/readonly.py`, `store/state.py`, `store/queries.py`, `store/prune.py`, `text.py`, `tagging.py`, `ingest.py`, `aliases.py`, `collectors.py`, `earnings.py`, `tape.py`, `playbook.py`, `facts.py`, `reaction.py`, `schemas.py`, `render.py`, `charts.py`, `publish.py`, `quiet.py`, `triggers.py`, `alerts.py`, `links.py`, `digests.py`, `posting.py`, `llm.py`, `prompts.py`, `grounding.py`, `explain.py`, `followup.py`, `briefs.py`, `brief_builder.py`, `service.py`).
  - `src/data/`: `rss_backend.py`, `finnhub_backend.py`, `forexfactory_backend.py`, `nasdaq_backend.py`, the yfinance intraday/earnings-history classes, new factory accessors and protocols.
  - `scripts/`: `run_news.py`, `news_probe.py`. `config/`: `news.example.yaml`, `news_playbook.yaml`, new `data.*` and `watchdog.news_max_age_minutes` keys.
  - Storage: `data/news.db` and its ten tables. Process/clientId model: the news process holds **no** IBKR connection and no clientId.
  - `src/notify/` commands table: `/news TICKER`, `/news`. `command_drain` kinds: `news_brief`. `src/api/`: `news_db.py`, `routers/news.py`, `models/news.py`. `web/`: `/news` pages.
  - Data flow: the pipeline diagram from spec §4 and the fact → playbook → reaction → LLM → grounding → card path.
  - Invariants: the news fence (spec §10) and "LLM output never reaches sentiment_score".
- [ ] **Step 2: SETUP.md** — scripts table (`run_news`, `news_probe`); `.env` keys (`TELEGRAM_THREAD_NEWS`, `FINNHUB_API_KEY`); "Using the Telegram bot" commands table (`/news TICKER`, `/news`); a new "News thread" section: copy `config/news.example.yaml` to `config/news.yaml`, create the forum topic and set the thread id, run `python -m scripts.news_probe` and prune dead feeds / fix `nasdaq_econ_date_offset_days` if the probe disagrees, choose `news.llm.backend`, the optional FinBERT extra (`pip install -e ".[finbert]"`, ~440 MB one-time download), quiet hours in SGT; troubleshooting rows (no posts → check `/news/status` heartbeat and `logs/news.log`; "🧠 off (daily cap)" → raise `news.llm.max_calls_per_day`; reaction always "pending" → yfinance futures delay, raise `reaction.max_wait_min`).
- [ ] **Step 3: STATUS.md** — "Built": the news thread (M1–M6). "Known limitations": ForexFactory has no actuals (Nasdaq supplies them; D+1 date key probed 2026-10-09); Nasdaq/ForexFactory endpoints are unofficial; yfinance futures/intraday ~10 min delayed so 📈 can read "pending"; Finnhub free tier is personal-use and 60/min; sentiment from the store is read once per symbol per day (`@daily_cached`); a single message block > 4096 chars is hard-split; the playbook is a prior, not a forecast; the earnings "implied move" is IV30 scaled to one day (the news process holds no option chain, so not the nearest-expiry straddle); ticker charts are daily only (the spec's optional intraday inset is not built). "Needs live verification": first CPI/NFP end-to-end timing, Nasdaq actual latency after release, link-preview images inside the forum topic, FinBERT if enabled. "Deferred": spreads-book impact in "your book".
- [ ] **Step 4: README.md** — Telegram commands table: `/news TICKER`, `/news`. No new top-level directory, so the layout table is unchanged.
- [ ] **Step 5: CLAUDE.md** — add a "The news fence — `src/news/` is enrichment with its own database" section after the spreads fence, stating spec §10's seven rules and the enforcing tests (`tests/test_news_fence.py`, `tests/test_eval_skills.py`, `tests/test_web_fence.py`); add `news.example.yaml` to the private-config sentence in Conventions; add to the doc-update trigger table: "New module under `src/news/` or a new key in `config/news.example.yaml` → ARCHITECTURE.md `src/news/` section · SETUP.md News thread section if operator-facing · root CLAUDE.md news-fence section if it changes what the package may import". Add `news.yaml` to the Conventions list of private configs.
- [ ] **Step 6: Final gate**

```bash
.venv/bin/python -m pytest -q
ruff check . && ruff format --check .
mypy src
cd web && npm run test && npm run lint && npx tsc --noEmit && cd ..
```

Expected: all green. Record the test counts in the progress log.

- [ ] **Step 7: Live verification (operator machine, networked)** — record each result in the progress log:
  1. `python -m scripts.news_probe` — every source answers; inferred Nasdaq offset matches config.
  2. `./ibkr restart` (or `python -m scripts.start`) — `news_service` appears in the supervisor; `logs/news.log` shows loops starting; "📰" posts appear in thread 4409 within one digest window.
  3. `/news NVDA` in Telegram → reply "Building NVDA brief → News thread" → brief with chart and 🧠 within ~2 min.
  4. Web `/news` and `/news/NVDA` render; "Request fresh brief" round-trips.
  5. Next scheduled high-impact US release (check `/news/calendar`): fact card within ~2 min of release, 📈 + 🧠 edit within ~20 min.
  6. `python -m scripts.watchdog` shows the `news` check passing.
- [ ] **Step 8: Commit + hand off**

```bash
git add ARCHITECTURE.md SETUP.md STATUS.md README.md CLAUDE.md .env.example docs/superpowers/specs/2026-10-09-news-thread-design.md docs/superpowers/plans/2026-10-09-news-thread.md
git commit -m "docs(news): architecture, setup, status, README and CLAUDE.md for the news thread"
```

Then use superpowers:finishing-a-development-branch to merge `feat/news-thread`.

