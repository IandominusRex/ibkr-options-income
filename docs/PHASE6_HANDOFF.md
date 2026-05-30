# Phase 6 Handoff — Telegram Approval Loop

> Read this first, then `PLAN.md` (Phase 6 entry) and `CLAUDE.md`.

## Where things stand (end of Phase 5)

**Phases 0–5 are complete and verified** (162/162 tests pass, `ruff` clean, `mypy` clean).

What now exists and should be **reused, not rebuilt**:

| File | What it gives you |
|---|---|
| `src/claude/runner.py` | `review_candidates(candidates, account) -> list[ClaudeReview]` — shells out to `claude -p`, returns `[]` on any failure |
| `src/claude/parser.py` | `parse_claude_output(raw) -> list[ClaudeReview]` — double-envelope parse, all failure modes return `[]` |
| `src/claude/prompts/strategist.py` | `build_prompt(candidates, account) -> str` — full prompt for candidate review |
| `src/common/schemas.py` | `ClaudeReview`, `TradeCandidate`, `AccountSnapshot`, `RiskVerdict`, `ApprovalStatus`, `OrderState` — Phase 6 reads `ClaudeReview` and writes `ApprovalStatus` rows |
| `src/storage/models.py` | SQLAlchemy ORM models — check what tables exist before adding new ones |
| `src/common/config.py` | `get_config().secrets` → `telegram_bot_token`, `telegram_chat_id` |

The typical Phase 5→6 hand-off in the orchestrator:

```python
approved_candidates = [c for c, v in zip(top, verdicts) if v.verdict == Verdict.PASS]
reviews = review_candidates(approved_candidates, account)
# Phase 6: send Telegram summary; approval_service receives button callbacks
```

## Phase 6 goal (acceptance criterion)

> The `morning_scan` one-shot script sends a Telegram message for each approved candidate
> (with Claude review enrichment if available, raw scores if not). Inline Approve / Reject
> buttons appear under each message. Tapping a button in Telegram causes the `approval_service`
> daemon to write `approvals.status = 'approved' | 'rejected'` and — for approvals — insert a
> `QUEUED` row in the `orders` table.
>
> **Only the configured `TELEGRAM_CHAT_ID` can trigger approvals** (chat-id allowlist).
>
> `pytest` green, `mypy` clean, `ruff` clean. No live TWS or real Telegram needed for tests
> (mock `python-telegram-bot` Bot API calls).

## Files to create

```
src/notify/formatters.py          # TradeCandidate + ClaudeReview → Telegram message text
src/notify/sender.py              # stateless Bot-API send (used by one-shot morning_scan)
src/notify/approval_service.py   # LONG-RUNNING: polling bot, Approve/Reject callbacks
tests/test_notify.py              # unit tests; mock python-telegram-bot
```

`src/notify/__init__.py` already exists (empty). No new YAML config keys needed — secrets
come from `.env` (already wired through `get_config().secrets`).

## Implementation notes (the parts that bite)

### 1. `formatters.py` — message builder

```python
def format_candidate(
    candidate: TradeCandidate,
    review: ClaudeReview | None,
) -> str:
    """Build the human-readable Telegram message for one trade candidate."""
```

- Use Telegram's **MarkdownV2** escaping (`\\.`, `\\-`, `\\_` etc.) — unescaped special chars
  cause `Bad Request: can't parse entities` errors. Escape helper:
  ```python
  import re
  _ESCAPE_RE = re.compile(r'([_*\[\]()~`>#+\-=|{}.!\\])')
  def _md(text: str) -> str:
      return _ESCAPE_RE.sub(r'\\\1', str(text))
  ```
- Include: symbol, strategy, strike, expiry, DTE, premium, ROC%, ann. yield, delta, IV rank,
  blended score, rationale tags. If `review` is provided, append Claude's `recommendation`,
  `why_attractive`, `risks`, and `tradeoffs` (2-3 sentences each).
- Keep it under ~4096 chars (Telegram message limit).

### 2. `sender.py` — stateless send

```python
async def send_candidates(
    candidates: list[TradeCandidate],
    reviews: list[ClaudeReview],
    session: AsyncSession,
) -> None:
    """Send one Telegram message per candidate; persist the message_id to DB."""
```

- Use `python-telegram-bot` **v21+** (`telegram.Bot`, `bot.send_message`).
- Import: `from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup`.
- Each message gets an `InlineKeyboardMarkup` with two buttons:
  ```
  [✅ Approve] [❌ Reject]
  ```
  Button callback data: `"approve:{candidate_id}"` and `"reject:{candidate_id}"`.
- After sending, persist `message_id` + `chat_id` to the `approvals` table
  (status = `'pending'`). The `approval_service` needs the `candidate_id` ↔ `message_id`
  mapping to edit messages after button press.
- **Async context:** `sender.py` is called from the async `morning_scan` orchestrator. Use
  `async with Bot(token=...) as bot: await bot.send_message(...)`.

### 3. `approval_service.py` — long-running polling daemon

```python
def main() -> None:
    """Entry point for `python -m scripts.run_approval_service`."""
```

Key design decisions (from PLAN.md):
- Uses `python-telegram-bot` v21 **Application** + `CallbackQueryHandler`.
- **Chat-id allowlist:** at the top of the callback handler, check
  `update.effective_chat.id == int(cfg.secrets.telegram_chat_id)` — silently ignore others.
- On button press: parse `candidate_id` from `callback_data`, look up the `approvals` row,
  write `status = 'approved' | 'rejected'`, insert `QUEUED` order row for approvals.
- Edit the original message to show the decision (so the buttons disappear):
  `await query.edit_message_text(...)` or `await query.edit_message_reply_markup(reply_markup=None)`.
- **Hold the exec TWS connection here** (clientId 14) for Phase 7. For Phase 6, the service
  does NOT connect to TWS — it only writes to SQLite. Wire up the IB connection in Phase 7.
- **DB session:** use the `get_session()` context manager from `src/storage/db.py` (async SQLAlchemy).

### 4. Storage: what to check / add

Check `src/storage/models.py` for existing `Approval` and `Order` tables. They likely exist
(Phase 0 laid down all ORM models). Verify column names before writing to them:

Expected fields on `Approval`:
- `id`, `candidate_id`, `chat_id`, `message_id`, `status` (pending/approved/rejected/expired),
  `created_at`, `decided_at`, `ttl_minutes`

Expected fields on `Order` (to be inserted by approval_service):
- `id`, `approval_id`, `candidate_id`, `state` (QUEUED), `created_at`

If they don't exist as expected, add columns via SQLAlchemy `Column` and call
`Base.metadata.create_all(engine)` (already done in `db.py`).

### 5. `python-telegram-bot` version & async

`python-telegram-bot` v21 is fully async. Never use synchronous `Bot.send_message()` —
it doesn't exist in v21. The pattern is:

```python
# Sending (in morning_scan async context):
async with Bot(token=token) as bot:
    msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )

# Polling daemon:
from telegram.ext import Application, CallbackQueryHandler
app = Application.builder().token(token).build()
app.add_handler(CallbackQueryHandler(handle_button))
app.run_polling()  # blocks; internally manages the event loop
```

Add `python-telegram-bot[job-queue]` to `pyproject.toml` dependencies.

### 6. Approval TTL expiry

Approvals older than `approval.ttl_minutes` (default: 60, configurable in `settings.yaml`)
must not be sent to the broker. Phase 7 enforces this at send time; Phase 6 just needs to
persist `ttl_minutes` on the `Approval` row. Add a `ttl_minutes: int = 60` key under an
`approval:` section in `settings.yaml` and read it via `get_config()`.

### 7. Morning scan wiring

`src/orchestrator/morning_scan.py` should call:
```python
from src.notify.sender import send_candidates
await send_candidates(approved_candidates, reviews, session)
```
after the Claude review step. For Phase 6, `morning_scan.py` may be a stub that just calls
`send_candidates` with a hardcoded test candidate to verify the Telegram flow end-to-end.

## Testing without live Telegram

Mock `telegram.Bot` in tests — do NOT call the real Bot API:

```python
from unittest.mock import AsyncMock, patch, MagicMock

async def test_send_candidates_persists_approval():
    mock_bot = AsyncMock()
    mock_bot.send_message.return_value = MagicMock(message_id=42)

    with patch("src.notify.sender.Bot", return_value=AsyncMock(__aenter__=AsyncMock(return_value=mock_bot))):
        await send_candidates([candidate], [], session)

    # assert approval row was inserted with status='pending'
    row = session.execute(select(Approval)).scalar_one()
    assert row.status == "pending"
    assert row.message_id == 42
```

Minimum coverage:
- `format_candidate` with `ClaudeReview` — output contains symbol, recommendation
- `format_candidate` without `ClaudeReview` — output contains symbol, blended_score
- `format_candidate` escapes MarkdownV2 special chars in symbol/numbers
- `send_candidates` sends one message per candidate with inline keyboard
- `send_candidates` persists `Approval` rows with `status='pending'`
- `send_candidates` handles empty candidate list (no API calls)
- Callback handler ignores requests from wrong chat_id
- Callback handler on `"approve:..."` writes `status='approved'` and inserts `QUEUED` order
- Callback handler on `"reject:..."` writes `status='rejected'`, no order row
- Callback handler for unknown `candidate_id` doesn't crash

## Quick verification when ready

```bash
source .venv/bin/activate
python -m pytest -q && ruff check . && mypy src

# Manual smoke test (needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID in .env):
python -c "
import asyncio
from src.notify.sender import send_candidates
from tests.test_notify import _make_candidate, _make_account
# ... minimal stub
print('smoke test passed')
"
```

## Open decisions

- **Message format:** one message per candidate vs. a single summary message. One-per-candidate
  recommended (cleaner inline keyboard UX; each message has its own Approve/Reject).
- **Parse mode:** MarkdownV2 vs. HTML. MarkdownV2 is stricter but better-looking. HTML is
  easier to escape. Recommend MarkdownV2 for Phase 6.
- **`approval.ttl_minutes` config location:** under a new `approval:` key in `settings.yaml`,
  or folded into `scheduler:`? New key is cleaner.
- **`run_approval_service.py` script:** a thin `__main__` wrapper in `scripts/` that calls
  `src.notify.approval_service.main()`. Match the pattern of `scripts/healthcheck.py`.
- **Phase 7 TWS connection handoff:** `approval_service.py` will need to hold the exec TWS
  connection (clientId 14) in Phase 7. Design the service now so adding the connection in
  Phase 7 is a single import + init call, not a refactor.
