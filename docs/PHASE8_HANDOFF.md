# Phase 8 Handoff — Intraday Monitor + Assignment/Rolling

> Read this first, then `PLAN.md` (Phase 8 entry) and `CLAUDE.md`.

## Where things stand (end of Phase 7)

**Phases 0–7 are complete and verified** (202/202 tests pass, `ruff` clean, `mypy` clean).

What now exists and should be **reused, not rebuilt**:

| File | What it gives you |
|---|---|
| `src/execution/approval.py` | `process_queued_orders(ib, bot, chat_id)` — the pattern for an async IB + Telegram poll loop |
| `src/notify/approval_service.py` | `_run_service()` async pattern with IB + PTB in one event loop; extend for monitor connection |
| `src/storage/models.py` | `FillRow`, `OrderRow`, `ApprovalRow`, `CandidateRow` — all live tables |
| `src/common/schemas.py` | `RollAlert` schema already defined; `PositionSnapshot` has delta/expiry/right |
| `src/ibkr/portfolio.py` | `get_positions(ib)` → `list[PositionSnapshot]`; `get_account_snapshot(ib, acct)` |
| `src/ibkr/market_data.py` | option chain + live Greeks fetching (Phase 1) |
| `src/common/config.py` | `ExecutionCfg` (transmit_only_in_rth, fill_timeout_minutes, poll_interval_seconds) |
| `config/settings.yaml` | `scheduler.intraday_poll_seconds = 60`; clientId `monitor: 12` |

The DB tables and schemas Phase 8 can write to:
- `src/storage/models.py` — likely needs a new `RollAlertRow` table (or extend `journal`)
- `src/common/schemas.py` — `RollAlert` is already defined

## Phase 8 goal (acceptance criterion)

> `intraday_monitor` runs as a long-running asyncio process (clientId 12) that subscribes
> to live position ticks via `ib_async` events. When a trigger condition fires (delta drift,
> IV spike, DTE threshold, or dividend-assignment risk), it calls Claude with a focused roll
> prompt and sends a Telegram alert with the recommendation. A simulated delta-drift event
> fires a roll recommendation and delivers it to Telegram.
>
> **`pytest` green, `mypy` clean, `ruff` clean.** No live TWS needed for unit tests (mock
> `ib_async` events and portfolio data).

## Files to create

```
src/monitor/intraday.py      # event-driven ib_async watch; subscribes to position/tick events
src/monitor/triggers.py      # trigger conditions: delta_drift, iv_spike, dte, ex_div
scripts/run_monitor.py       # entrypoint: python -m scripts.run_monitor
tests/test_monitor.py        # unit tests; mock ib_async events and Claude runner
```

Also extend:
- `src/storage/models.py` — add `RollAlertRow` table
- `config/settings.yaml` — add `monitor:` section with trigger thresholds

## Implementation notes

### 1. Process model

The intraday monitor is a **separate long-running process** from `approval_service`.
Use clientId 12 (`monitor` in `settings.yaml`). It runs during RTH only (start after
09:30 ET, stop at 16:00 ET, or just let it run 24/7 and filter events by RTH).

### 2. Event-driven subscription pattern

```python
from ib_async import IB

async def run_monitor() -> None:
    ib = IB()
    await ib.connectAsync(host, port, clientId=12)

    # Subscribe to portfolio updates (position deltas, market values)
    ib.pendingTickersEvent += on_pending_tickers

    # Subscribe to position changes
    ib.positionEvent += on_position

    # Subscribe to order status (for monitoring fills from execution)
    # ib.orderStatusEvent += on_order_status  # optional for Phase 8

    # Initial portfolio load
    positions = get_positions(ib)
    for pos in positions:
        if pos.sec_type == "OPT":
            contract = build_option(pos.underlying, pos.expiry, pos.strike, pos.right)
            ib.reqMktData(contract, genericTickList="106", snapshot=False)

    # Run until interrupted
    stop_event = asyncio.Event()
    await stop_event.wait()
```

### 3. Trigger conditions (`triggers.py`)

Four triggers, each a function `check_*(position, quote) -> RollAlert | None`:

```python
def check_delta_drift(pos: PositionSnapshot, quote: OptionQuote, limits: dict) -> RollAlert | None:
    """Fire if |delta| has drifted above the configured ceiling."""
    if pos.delta is None or quote.delta is None:
        return None
    delta_ceiling = limits.get("delta_ceiling", 0.45)
    if abs(quote.delta) > delta_ceiling:
        return RollAlert(
            position_symbol=pos.symbol,
            underlying=pos.underlying,
            trigger="delta_drift",
            detail=f"delta={quote.delta:.2f} > ceiling={delta_ceiling}",
            current_delta=quote.delta,
            dte=quote.dte,
        )
    return None

def check_dte_threshold(pos: PositionSnapshot, dte_threshold: int) -> RollAlert | None:
    """Fire when DTE drops to or below the configured threshold."""
    ...

def check_iv_spike(pos: PositionSnapshot, quote: OptionQuote, spike_pct: float) -> RollAlert | None:
    """Fire when IV has spiked > spike_pct% relative to the IV at entry."""
    ...

def check_ex_div(pos: PositionSnapshot, fund_stats: FundamentalStats, days_ahead: int) -> RollAlert | None:
    """Fire when ex-dividend date is within days_ahead for a short call."""
    ...
```

Config thresholds live in a new `config/settings.yaml → monitor:` section:
```yaml
monitor:
  delta_ceiling: 0.45         # short call: roll if delta drifts above this
  dte_threshold: 7            # roll if DTE drops to this
  iv_spike_pct: 40            # roll if IV spikes > 40% from entry IV
  ex_div_days_ahead: 5        # warn if ex-div within this many days
```

### 4. Claude focused roll prompt

When a trigger fires, call Claude with a narrow prompt (not the full morning review):
```python
from src.claude.runner import run_claude
from src.claude.prompts import ROLL_PROMPT

context = {
    "alert": alert.model_dump(),
    "position": pos.model_dump(),
    "current_quote": quote.model_dump(),
}
review = run_claude(ROLL_PROMPT, context)
```

The roll prompt template lives in `src/claude/prompts/roll.txt` (already scaffolded in Phase 5).
Output: `ClaudeReview` with `recommendation` = "roll" / "hold" / "close".

### 5. Telegram alert format

```
⚠️ Roll Alert: AAPL CC $185 — delta drift
Delta: 0.47 (ceiling: 0.45) | DTE: 12 | IV: 72 (rank: 81)

Claude: roll up-and-out to $190 Aug expiry (0.30 delta, $1.85 credit)
Risk: stock in momentum; consider reducing size.
```

Send via `bot.send_message(chat_id, text)`. No Approve/Reject keyboard needed (alerts are informational; user decides manually).

### 6. `RollAlertRow` table

```python
class RollAlertRow(Base):
    __tablename__ = "roll_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_symbol: Mapped[str] = mapped_column(String(32), index=True)
    underlying: Mapped[str] = mapped_column(String(16), index=True)
    trigger: Mapped[str] = mapped_column(String(20))
    detail: Mapped[str] = mapped_column(Text)
    claude_recommendation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
```

## Testing without live TWS

Mock `ib_async.IB` and simulate events:
```python
mock_ib = MagicMock()
mock_ib.portfolio.return_value = [mock_portfolio_item]
mock_ib.pendingTickersEvent = MagicMock()  # or just call trigger functions directly

# Test triggers directly without the event loop:
from src.monitor.triggers import check_delta_drift
alert = check_delta_drift(pos, quote, {"delta_ceiling": 0.40})
assert alert is not None
assert alert.trigger == "delta_drift"
```

Minimum test coverage:
- `check_delta_drift` fires when delta exceeds ceiling
- `check_delta_drift` returns None when within bounds
- `check_dte_threshold` fires when DTE ≤ threshold
- `check_iv_spike` fires when IV spikes above threshold
- `check_ex_div` fires when ex-div date within days_ahead for a CC position
- Telegram alert is sent when any trigger fires
- `RollAlertRow` is written to DB when trigger fires
- Trigger does NOT fire again if same alert already exists and is recent (de-dup)

## Open decisions

- **Alert de-duplication:** once a delta-drift alert fires for a position, don't re-fire for
  30 min (or until DTE changes). Track last-alert timestamp per (symbol, trigger) in the DB.
- **Multiple concurrent triggers:** if both delta_drift and dte fire for the same position,
  send one combined alert or two separate ones? Recommended: one combined.
- **Monitor process shutdown:** should the monitor automatically stop after RTH and restart
  next day, or run 24/7 with RTH filtering? Simplest for Phase 8: filter events, run 24/7.
- **Claude integration in monitor:** use `run_claude()` from `src.claude.runner` synchronously
  (it's a subprocess call). Run in a `ThreadPoolExecutor` so it doesn't block the asyncio loop.
- **`iv_spike_pct` baseline:** what IV do we compare against? Use the IV in the candidate's
  `OptionQuote` at scan time (stored in `CandidateRow.payload`). Retrieve it when loading the
  position's corresponding candidate.
