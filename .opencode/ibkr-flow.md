# IBKR options-income system — operating protocol (opencode)

Loaded into every opencode session via `instructions` in `opencode.json`. `CLAUDE.md` is still the
authority on *what the invariants and conventions are* — this file is about *how to run a session
in opencode specifically*, where the enforcement Claude Code has doesn't fully carry over. See
`CLAUDE.md` § "Running this repo in opencode" for the file-by-file summary.

## Read this before touching anything

`CLAUDE.md` (root) is auto-loaded by opencode's instruction resolver, and is also listed explicitly
above — belt and suspenders, in case a future `AGENTS.md` anywhere in the walk-up chain would
otherwise suppress it (see the CLAUDE.md section named above; **never create an `AGENTS.md` in this
repo**, and never run opencode's `/init` here). Read, in order, before any structural change:

1. **`CLAUDE.md`** — the core invariant (the Rules Engine is the only path to order execution, no
   LLM involvement), the fence (`src/claude/eval/`/`src/claude/skills/` may never reach
   `engine/`/`execution/`/`strategies/`), and the analytics-tier split (deterministic vs.
   enrichment — `fair_value.py` stays deterministic-only).
2. **`ARCHITECTURE.md`** — how it's built, folder by folder.
3. **`STATUS.md`** — what's built vs. deliberately not built, and the live-cutover gate. Do not
   assume anything runs against a live account; paper trading only unless the user says otherwise.
4. **`ib_async_documentation.md`** — consult before guessing any `ib_async` signature; do not invent
   IBKR API calls from memory.

## The doc-update rule is advisory in both harnesses

In Claude Code, a `PostToolUse` hook (`.claude/settings.json`) fires after every Write/Edit of a
non-test `.py` file and injects a reminder pointing at the doc-update trigger table in
`CLAUDE.md`. **It only ever adds context — it cannot block completion.** So unlike a repo enforced
by a blocking `Stop` hook, opencode loses comparatively little here: `.opencode/plugin/
session-checks.js` reproduces the same reminder via `tool.execute.after`, matching the same
Write/Edit + non-test-`.py` condition. Still, nothing in either harness can force the update — read
the trigger table in `CLAUDE.md` yourself and act on every row that matches before calling a task
done.

## Before you claim anything is done

Evidence before assertions — this is a financial system with a paper/live boundary; "should work"
is not an acceptable completion signal here more than almost anywhere else.

```bash
python -m pytest -q    # all tests must pass — IBKR is mocked, no TWS needed
ruff check .            # no lint issues
mypy src                # no type errors
```

If a test, lint, or type check fails, stop and fix it — do not comment out the failing part or
weaken an assertion to get green. If something was skipped, say so plainly rather than reporting
success.

## Ollama Cloud here is a coding assistant, not the production reviewer

`opencode.json` configures **Ollama Cloud** models (`:cloud` tags, routed to Ollama's datacenter —
`ollama signin` once to authorize) purely as a fallback CLI harness for **development sessions**,
the same role Claude Code plays. This is unrelated to `src/claude/ollama_runner.py`
(`config/settings.yaml → claude.backend: "ollama"`, `SETUP.md` §14), which runs a small **local**
model (`qwen3.5:4b`, no `:cloud` tag) as the trading pipeline's own strategist reviewer at
runtime. Both talk to the same `ollama serve` daemon on `localhost:11434`, but do not confuse a
coding-assistant session with the production review path — never let anything in an opencode
session touch `config/settings.yaml → claude.*` on the assumption it affects "the same Ollama
integration used here." It doesn't.

## Committing

opencode has no built-in equivalent of Claude Code's git safety rails — apply them deliberately:
stage explicit paths (never `git add -A` / `git add .`), confirm with `git status --short` before
committing, and never push or force anything without the user asking. Conventional commits, matching
this repo's history: `feat` · `fix` · `refactor` · `docs` · `chore`, imperative one-line summary,
body explains *why* when it is not obvious from the diff.

## Safety, restated

- **Paper first.** Never assume `LIVE_TRADING=true` is set or that the live port is in use.
- `LimitOrder` at mid, never `MarketOrder`, for anything touching option entries.
- `qualifyContracts` every option contract before an order — this applies whether the code path is
  reached from a Claude Code session or an opencode one; the harness does not change the invariant.
- Secrets live only in `.env` (gitignored) — never log or commit them, and never paste `.env`
  contents into a prompt, response, or commit.

opencode loads config once at startup and does not hot-reload it; restart the session after editing
`opencode.json` or any file under `.opencode/`.
