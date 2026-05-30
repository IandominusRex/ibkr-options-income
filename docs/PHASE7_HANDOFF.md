# Phase 7 Handoff — Execution Engine (Paper)

> Read this first, then `PLAN.md` (Phase 7 entry) and `CLAUDE.md`.

## Where things stand (end of Phase 6)

**Phases 0–6 are complete and verified** (186/186 tests pass, `ruff` clean, `mypy` clean).

What now exists and should be **reused, not rebuilt**:

| File | What it gives you |
|---|---|
| `src/notify/approval_service.py` | `handle_button` callback writes `approvals.status = 'approved'` and inserts `OrderRow(state='queued', approval_id=N)` — Phase 7 picks these up |
| `src/notify/sender.py` | `send_candidates(candidates, reviews, session)` — sends Telegram messages; already used by `morning_scan` |
| `src/storage/models.py` | `ApprovalRow` (has `expires_at`, `decided_at`, `candidate_id`) · `OrderRow` (has `approval_id`, `state`, `candidate_id`) |
| `src/common/schemas.py` | `ApprovalStatus`, `OrderState` (QUEUED/SUBMITTED/FILLED/PARTIAL/CANCELLED/REJECTED) |
| `src/common/config.py` | `ApprovalCfg` → `get_config().approval.ttl_minutes`; `get_config().ibkr.client_ids["exec"]` = 14 |
| `src/ibkr/connection.py` | `IBKRConnection` — connect/reconnect manager; use `client_ids.exec` (14) for the execution connection |
| `src/ibkr/contracts.py` | `build_option_contract()` + `qualify_contracts()` wrappers |

The DB flow already set up by Phase 6:
```
morning_scan → send_candidates → ApprovalRow(status='pending')
user taps Approve → approval_service → ApprovalRow(status='approved') + OrderRow(state='queued')
Phase 7 ────────────────────────────────────────────────────────────▶ pick up QUEUED rows, execute
```

## Phase 7 goal (acceptance criterion)

> The `approval_service` daemon polls for `QUEUED` `OrderRow`s, re-validates each against the
> Rules Engine + a fresh live quote from IBKR, builds a mid-price `LimitOrder`,
> `qualifyContracts`, transmits via `ib_async`, monitors fill, and confirms back to Telegram.
> Off-hours orders stay `QUEUED`; approvals older than `ttl_minutes` are marked `EXPIRED` and
> never sent. A paper-account CSP or CC fills and the result appears in the `fills` table and
> in a Telegram confirmation message.
>
> **`pytest` green, `mypy` clean, `ruff` clean.** No live TWS needed for unit tests (mock
> `ib_async` order placement).

## Files to create

```
src/execution/order_builder.py     # build mid-price LimitOrder from TradeCandidate
src/execution/executor.py          # place/monitor/cancel via ib_async; fill tracking
src/execution/approval.py          # QUEUED order → re-validate → execute loop
tests/test_execution.py            # unit tests; mock ib_async
```

Also extend:
- `src/notify/approval_service.py` — add the IB exec connection (clientId 14) and call the execution loop
- `src/storage/models.py` — add `FillRow` table (or verify it exists)

## Implementation notes

### 1. IB connection in `approval_service`

The `approval_service` is the only long-running process that needs the exec TWS connection
(clientId 14). Add the connection setup to `main()`:

```python
from src.ibkr.connection import IBKRConnection

def main() -> None:
    ...
    ib = IBKRConnection(client_id=cfg.ibkr.client_ids["exec"])
    ib.connect()          # blocking until connected
    app = Application.builder().token(token).build()
    # Wire ib into the app context so handle_button can reach it
    app.bot_data["ib"] = ib
    ...
    app.run_polling()
    ib.disconnect()
```

`python-telegram-bot` v21's `Application` starts its own asyncio event loop for polling.
`ib_async` also runs on an asyncio event loop. To avoid two competing loops, run the `ib_async`
loop on the same thread by using `ib_async`'s `util.startLoop()` pattern **or** pass the
existing `asyncio` event loop to `Application.builder().event_loop(...)`. The recommended
approach is to let `ib_async` manage the loop and run `Application` as a coroutine within it:

```python
import asyncio
from ib_async import IB, util

async def run_all() -> None:
    ib = IB()
    await ib.connectAsync(cfg.ibkr.host, cfg.ibkr_port, clientId=14)
    app = Application.builder().token(token).build()
    app.bot_data["ib"] = ib
    async with app:
        await app.start()
        await app.updater.start_polling()
        # Keep running until interrupted
        try:
            await asyncio.Event().wait()
        finally:
            await app.updater.stop()
            await app.stop()
    ib.disconnect()

def main() -> None:
    util.startLoop()
    asyncio.get_event_loop().run_until_complete(run_all())
```

### 2. `order_builder.py`

```python
from ib_async import LimitOrder, Option

def build_limit_order(candidate: TradeCandidate, quote: OptionQuote) -> LimitOrder:
    """Build a mid-price LimitOrder (sell to open) for the given candidate."""
    mid = quote.mid
    if mid is None:
        raise ValueError(f"No mid price for {candidate.candidate_id}")
    # Round to nearest $0.05 tick
    price = round(round(mid / 0.05) * 0.05, 2)
    return LimitOrder(
        action="SELL",
        totalQuantity=candidate.contracts,
        lmtPrice=price,
        tif="DAY",
    )
```

Never use `MarketOrder`. Always `LimitOrder` at mid (rounded to tick).

### 3. `executor.py` — place, monitor, confirm

Core flow:
1. Build `Option` contract from `TradeCandidate` fields
2. `ib.qualifyContractsAsync([contract])` — must succeed before sending
3. Place order: `trade = ib.placeOrder(contract, order)`
4. Monitor `trade.statusEvent` / `trade.fillEvent` until `FILLED` or `CANCELLED`/error
5. On fill: write `FillRow`, update `OrderRow(state='filled')`, send Telegram confirmation
6. On reject: update `OrderRow(state='rejected', detail=reason)`, send Telegram alert

Pacing: don't submit multiple orders without waiting for qualification response.

### 4. `approval.py` — QUEUED order poll loop

```python
async def process_queued_orders(ib: IB, bot: Bot, chat_id: str) -> None:
    """Pick up QUEUED orders, TTL-expire stale ones, execute live ones."""
    now = datetime.now(UTC)
    with session_scope() as session:
        queued = (
            session.query(OrderRow)
            .filter(OrderRow.state == OrderState.QUEUED)
            .all()
        )
        for order_row in queued:
            approval = session.get(ApprovalRow, order_row.approval_id)
            if approval is None:
                continue
            # TTL check
            if approval.expires_at and approval.expires_at < now:
                approval.status = ApprovalStatus.EXPIRED
                order_row.state = OrderState.CANCELLED
                order_row.detail = "TTL expired"
                continue
            # RTH check (optional — see settings.yaml transmit_only_in_rth)
            candidate = _load_candidate(session, order_row.candidate_id)
            if candidate is None:
                continue
            await _execute_one(ib, bot, chat_id, order_row, candidate, session)
```

### 5. `FillRow` table

Check `src/storage/models.py` — a `FillRow` / `fills` table may not exist yet. Add:

```python
class FillRow(Base):
    __tablename__ = "fills"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(Integer, index=True)
    candidate_id: Mapped[str] = mapped_column(String(64), index=True)
    ib_exec_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filled_qty: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    commission: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    filled_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
```

### 6. RTH gating

Add to `config/settings.yaml`:
```yaml
execution:
  transmit_only_in_rth: true   # if true, QUEUED orders wait for RTH before transmitting
```

The `approval.py` loop checks this flag and defers if outside 09:30–16:00 ET on weekdays.

### 7. Re-validation before sending

Before building the order, re-run the Rules Engine on a freshly fetched quote:
```python
from src.engine.risk_engine import RiskEngine
verdict = RiskEngine(cfg).evaluate(candidate, account_snapshot)
if verdict.verdict != Verdict.PASS:
    order_row.state = OrderState.CANCELLED
    order_row.detail = f"Re-validation failed: {verdict.reasons}"
    return
```

This is the second Rules Engine pass (first was at decision time in Phase 4).

## Testing without live TWS

Mock `ib_async.IB` for all unit tests:
```python
from unittest.mock import AsyncMock, MagicMock, patch

mock_ib = MagicMock()
mock_ib.qualifyContractsAsync = AsyncMock(return_value=[contract])
mock_ib.placeOrder.return_value = MagicMock(isDone=MagicMock(return_value=True))
```

Minimum test coverage:
- `build_limit_order` rounds mid to nearest $0.05 tick
- `build_limit_order` raises on no mid price
- `process_queued_orders` expires TTL-expired approvals
- `process_queued_orders` calls `_execute_one` for a live QUEUED order
- `_execute_one` writes `FillRow` and updates `OrderRow(state='filled')` on fill
- `_execute_one` writes `OrderRow(state='rejected')` on IB reject
- `_execute_one` re-validates and cancels if Rules Engine rejects second pass
- Telegram confirmation is sent after fill

## Quick verification when ready

```bash
source .venv/bin/activate
python -m pytest -q && ruff check . && mypy src

# Manual paper smoke test (needs TWS paper on port 7497):
# 1. Start approval_service: python -m scripts.run_approval_service
# 2. In another terminal, run morning scan: python -m scripts.run_morning
# 3. Tap Approve in Telegram
# 4. Verify the order appears in TWS and fills table
```

## Open decisions

- **TWS event loop integration:** `ib_async` + `python-telegram-bot` both want to own the asyncio loop. The `Application.builder().event_loop(loop)` API in PTB v21 is the cleanest hook — pass the loop that `ib_async` already started. Confirm this works before wiring everything together.
- **`transmit_only_in_rth` default:** `true` is safest for paper. Set to `false` for extended-hours testing if needed.
- **Order monitoring timeout:** how long to wait for a fill before marking as `CANCELLED`? Default: 5 minutes (configurable in `settings.yaml → execution.fill_timeout_minutes`).
- **Confirmation message format:** update the original Telegram approval message in-place (edit) or send a new message? Recommended: send a new short message ("Filled: AAPL CC $185 — 1 contract @ $1.52 mid").
