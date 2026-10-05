# Trade Ledger & Position Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A broker-truth ledger of every execution ever made on the IBKR account. It is built from Activity Statement CSV uploads, a nightly Flex pull and live executions, rolled up into trades, tickers and a portfolio. It is viewable and editable on the web dashboard at `/ledger` and mirrored to the operator's Google Sheet.

**Architecture:**
- **Ingestion:** three feeds normalise to one `ParsedStatement` schema. A single writer, `src/ledger/ingest.py`, upserts by dedupe key and runs an order-level twin pass so overlapping feeds never double count.
- **Read side:** a pure, read-only builder, `src/reporting/trade_ledger.py`, turns executions into orders, FIFO trades, stock lots, ticker roll-ups and a USD summary.
- **Consumers:** the API router, the CSV export and the Sheets mirror all render that builder's output.
- **Writes from the web:** every web write is a `POST /commands` intent applied by the existing drain loop.

**Tech Stack:** Python 3.12, SQLAlchemy 2 / SQLite, Pydantic v2, FastAPI, httpx (Flex), gspread + google-auth (Sheets), ib_async (live hook), Next.js 15 + React Query + recharts + Vitest (web).

**Spec:** `docs/superpowers/specs/2026-10-04-trade-ledger-design.md`. **Read its "Revisions made while planning" block (R1–R11) first.** It overrides the body of the spec, and this plan implements the revised version.

## Before you start

The main working tree has **uncommitted, unrelated gateway-recovery work**. It touches `src/common/config.py`, `config/settings.yaml`, `src/notify/approval_service.py`, `scripts/launchd.py`, `tests/conftest.py` and the docs.
- Execute this plan in an isolated worktree (`superpowers:using-git-worktrees`), **or** have the operator commit that work first.
- Never `git add` a file wholesale if it carries someone else's hunks.
- Every edit below is located by an **anchor string**, not a line number.

## Global Constraints

- **Core invariant:** nothing in `src/ledger/` or `src/reporting/trade_ledger.py` may be imported by `src/engine/`, `src/execution/`, or `src/strategies/`. The ledger never places, sizes, or gates an order.
- `src/ledger/` and `src/reporting/` import nothing from `src.claude`.
- `src/reporting/trade_ledger.py` never writes. No `session.add`, `session.merge`, `session.delete` or `session.commit` appears in it; this is enforced by `tests/test_web_fence.py::test_reporting_never_writes_anything`.
- The API writes exactly one table, `app_commands`, through `src/api/commands.py`. Ledger writes go through `POST /commands` kinds `ledger_import`, `ledger_annotate` and `ledger_ca_reviewed`.
- `ib_async` objects are converted to `ParsedExecution` inside `src/ledger/live.py` and nowhere else.
- Secrets live in `.env` only:
  - `IBKR_FLEX_TOKEN`
  - `IBKR_FLEX_QUERY_ID`
  - `GOOGLE_SHEETS_CREDENTIALS_PATH`
  - `LEDGER_SHEET_ID`
- Tunables live in `config/settings.yaml → ledger.*`:
  - `account: ""`
  - `live_sweep_minutes: 5`
  - `sheets_min_interval_seconds: 60`
  - `upload_max_bytes: 5242880`
  - `flex_poll_timeout_seconds: 600`
  - `flex_poll_interval_seconds: 10`
  - `fx_max_gap_days: 7`
- **One trade-date definition:** the US/Eastern calendar date of the execution timestamp (`src.ledger.contracts.et_date`). Activity Statement and Flex timestamps are US/Eastern; live timestamps are UTC.
- Premium is the **gross** opening credit/debit (R4). `% Profit` is `premium / (strike × multiplier × lots) × 365 / DTE × 100` (short options only). Fixtures that must hold:
  - NVDA 138P 2025-06-17→2025-06-27, $131 → **34.65**
  - AMZN 207.5P 2025-06-25→2025-07-18, $325 → **24.86**
- Unknown is `None`/`null`/`n/a`, **never zero**: missing FX rates, missing marks, and missing deposits all follow this.
- `exclude_from_stats` removes a trade from win rate, averages and annualised figures. It **never** removes it from money totals.
- Web UI copy follows `web/CLAUDE.md`:
  - semantic colour tokens only (`text-gain`, `text-loss`, `text-muted`, `text-content`, `text-unknown`, `bg-surface`, `bg-elevated`, `border-border`);
  - no em dashes in UI copy;
  - charts never animate (`isAnimationActive={false}`);
  - state is never encoded by colour alone (pills carry their text).
- Quality gate after every task:
  - `python -m pytest -q`
  - `ruff check .`
  - `mypy src`
  - web tasks also run `cd web && npm test`
- Run `ruff format <new/changed .py files>` before every commit. The plan's code blocks are not pre-formatted, and E501 is ignored because the formatter owns line length.

## Review Focus

These five inputs aren't exercised by the spec's own examples but will happen to a real user. Each has a test in the owning task.

1. **An annual statement opens mid-position.** For example, the Apr-2025 statement contains the buy-to-close of a put sold in March. The closing row (code token `C`) must become an **orphan close**, reported and counted via IBKR's own realized P/L, and never turned into a fake long position (Task 5, Task 6).
2. **Overlapping statements.** Importing Apr-25→Apr-26 and then Jan-26→Jun-26 must insert only the rows that are new, with zero double counting (Task 4).
3. **Paper-account executions arriving live** while the ledger tracks the real account must be skipped silently. No import-run rows and no account lock are created from live data (Task 4, Task 11).
4. **Overnight SGX trades across the ET/UTC date line.** A live fill at `2025-11-03 03:30 UTC` and its CSV row `2025-11-02, 22:30:00` must land on the same ET trade date and twin-match (Task 4).
5. **Non-100 multipliers** (adjusted options after a corporate action): the multiplier from *Financial Instrument Information* must drive premium, capital and `% Profit` (Task 3, Task 5).

---

## File Structure

| Path | Responsibility |
|---|---|
| `src/common/schemas.py` (modify) | `LedgerContract`, `ParsedExecution`, `ParsedCashEvent`, `ParsedCorporateAction`, `ParsedFxRate`, `LedgerParseError`, `ParsedStatement`, `LedgerImportResult` (Task 1); `LedgerClose`, `LedgerTrade`, `LedgerOrphan` (Task 5); lots/tickers/summary/book models (Task 6) |
| `src/storage/models.py` (modify) | 6 ORM classes (Task 2) |
| `src/common/config.py`, `config/settings.yaml`, `.env.example` (modify) | `LedgerCfg`, four secrets (Task 2) |
| `src/ledger/__init__.py` | package |
| `src/ledger/contracts.py` | option-symbol parsing, ET time/date helpers, number parsing |
| `src/ledger/state.py` | `system_settings` keys + generation counter + account lock |
| `src/ledger/activity_csv.py` | Activity Statement CSV → `ParsedStatement` |
| `src/ledger/ingest.py` | the only writer of `broker_*`/`fx_rates`/`ledger_import_runs`; dedupe, twin pass, book tagging |
| `src/ledger/annotations.py` | writer for `trade_annotations` + corporate-action review flag |
| `src/ledger/flex.py` | Flex Web Service client, Flex XML parser, `run_flex_pull` |
| `src/ledger/live.py` | `ib_async` Fill → `ParsedExecution`, commission-report hook, sweep loop |
| `src/ledger/sheets_mirror.py` | Google Sheets writer + generation-driven mirror loop |
| `src/reporting/trade_ledger.py` | pure builders: orders, FIFO, trades, outcomes, rolls, lots, tickers, FX, summary, sheet rows, filters |
| `src/api/models/ledger.py`, `src/api/routers/ledger.py` | read-only `/ledger/*` routes |
| `src/api/models/commands.py`, `src/notify/command_drain.py` (modify) | three command kinds + handlers |
| `src/api/main.py`, `src/api/routers/meta.py` (modify) | router + nav entry |
| `src/orchestrator/eod_report.py`, `src/notify/approval_service.py` (modify) | EOD Flex step; live hook, sweep and mirror tasks |
| `scripts/ledger_import.py`, `scripts/ledger_flex_pull.py` | CLIs |
| `web/app/ledger/**`, `web/components/ledger/**`, `web/components/shell/RailSection.tsx` | dashboard |
| `tests/fixtures/ledger/activity_statement_sample.csv` + `tests/test_ledger_*.py`, `tests/test_trade_ledger_*.py`, `tests/test_api_ledger.py`, `tests/test_drain_ledger.py` | tests |

---

### Task 1: Ledger schemas and contract helpers

**Files:**
- Modify: `src/common/schemas.py` (append at end of file; add `Any` to the `typing` import and `ConfigDict` to the `pydantic` import)
- Create: `src/ledger/__init__.py`, `src/ledger/contracts.py`
- Test: `tests/test_ledger_contracts.py`

**Interfaces:**
- Produces:
  - `LedgerContract(underlying, sec_type, currency="USD", right=None, strike=None, expiry=None, multiplier=1.0)` with an `.ident` property
  - `ParsedExecution`, `ParsedCashEvent`, `ParsedCorporateAction`, `ParsedFxRate`, `LedgerParseError`, `ParsedStatement` (with `.fatal`), `LedgerImportResult`
  - Literal aliases `LedgerSourceKind = Literal["exec","order"]`, `LedgerSource = Literal["csv","flex","live"]`, `LedgerOutcome`
  - `parse_option_symbol(symbol, *, currency="USD", multiplier=100.0) -> LedgerContract`
  - `stock_contract(symbol, currency) -> LedgerContract`
  - `parse_et_timestamp(value) -> datetime` (aware UTC)
  - `parse_ibkr_date(value) -> date`
  - `et_date(ts) -> date`
  - `parse_number(value) -> float`
  - `ET: ZoneInfo`

- [ ] **Step 1: Write the failing test** — `tests/test_ledger_contracts.py`

```python
"""Contract identity + time helpers shared by every ledger feed (spec §5, R2)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.common.schemas import LedgerParseError, ParsedStatement
from src.ledger.contracts import (
    et_date,
    parse_et_timestamp,
    parse_ibkr_date,
    parse_number,
    parse_option_symbol,
    stock_contract,
)


def test_parses_activity_statement_option_symbol() -> None:
    c = parse_option_symbol("AMD 29AUG25 157.5 P")
    assert (c.underlying, c.sec_type, c.right, c.strike, c.expiry, c.multiplier) == (
        "AMD", "OPT", "P", 157.5, date(2025, 8, 29), 100.0,
    )
    assert c.ident == "OPT:AMD:20250829:P:157.5:USD"


def test_integer_strike_ident_has_no_trailing_zero() -> None:
    assert parse_option_symbol("NVDA 27JUN25 138 P").ident == "OPT:NVDA:20250627:P:138:USD"


def test_multiplier_is_carried_not_assumed() -> None:
    c = parse_option_symbol("OPEN1 19SEP25 3 C", multiplier=50.0)
    assert c.multiplier == 50.0


def test_rejects_garbage_symbol() -> None:
    with pytest.raises(ValueError):
        parse_option_symbol("AMD")


def test_stock_ident_includes_currency() -> None:
    assert stock_contract("A17U", "SGD").ident == "STK:A17U:SGD"


def test_statement_time_is_eastern_summer_and_winter() -> None:
    assert parse_et_timestamp("2025-08-22, 10:11:57") == datetime(2025, 8, 22, 14, 11, 57, tzinfo=UTC)
    assert parse_et_timestamp("20260106;064936") == datetime(2026, 1, 6, 11, 49, 36, tzinfo=UTC)
    assert parse_et_timestamp("2025-08-22;10:11:57") == datetime(2025, 8, 22, 14, 11, 57, tzinfo=UTC)


def test_overnight_sgx_trade_keeps_its_eastern_date() -> None:
    # Review Focus 4: 22:30 ET on Nov 2 is 03:30 UTC on Nov 3 — the ET date wins.
    assert et_date(datetime(2025, 11, 3, 3, 30, tzinfo=UTC)) == date(2025, 11, 2)
    assert et_date(parse_et_timestamp("2025-11-02, 22:30:00")) == date(2025, 11, 2)


def test_parse_ibkr_date_accepts_both_formats() -> None:
    assert parse_ibkr_date("2025-06-13") == parse_ibkr_date("20250613") == date(2025, 6, 13)


def test_parse_number_strips_commas_and_rejects_blank() -> None:
    assert parse_number("-1,385.5") == -1385.5
    with pytest.raises(ValueError):
        parse_number(" ")


def test_only_trades_errors_are_fatal() -> None:
    warn = ParsedStatement(errors=[LedgerParseError(line=3, section="Dividends", message="x")])
    bad = ParsedStatement(errors=[LedgerParseError(line=9, section="Trades", message="x")])
    assert warn.fatal is False
    assert bad.fatal is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ledger_contracts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ledger'` (or ImportError on `LedgerParseError`).

- [ ] **Step 3: Append the schemas to `src/common/schemas.py`**

Change the imports at the top: `from typing import Literal` → `from typing import Any, Literal`, and `from pydantic import BaseModel, Field, field_validator` → `from pydantic import BaseModel, ConfigDict, Field, field_validator`. If either name is already imported, leave it alone. Then append:

```python
# --------------------------------------------------------------------------- #
# Trade ledger — whole-account broker truth
# (docs/superpowers/specs/2026-10-04-trade-ledger-design.md). Read by src/ledger/,
# src/reporting/trade_ledger.py and src/api/ only — never by engine/execution/strategies.
# --------------------------------------------------------------------------- #
LedgerSourceKind = Literal["exec", "order"]
LedgerSource = Literal["csv", "flex", "live"]
LedgerOutcome = Literal[
    "Open",
    "Pending",
    "Expired",
    "Assigned",
    "Called away",
    "Exercised",
    "Bought back",
    "Sold",
    "Rolled",
]


class LedgerContract(BaseModel):
    """A normalized IBKR contract identity, independent of which feed reported it."""

    model_config = ConfigDict(frozen=True)

    underlying: str
    sec_type: Literal["OPT", "STK"]
    currency: str = "USD"
    right: Literal["P", "C"] | None = None
    strike: float | None = None
    expiry: date | None = None
    multiplier: float = 1.0

    @property
    def ident(self) -> str:
        if self.sec_type == "STK":
            return f"STK:{self.underlying}:{self.currency}"
        assert self.expiry is not None and self.strike is not None and self.right is not None
        return (
            f"OPT:{self.underlying}:{self.expiry:%Y%m%d}:{self.right}:"
            f"{self.strike:g}:{self.currency}"
        )


class ParsedExecution(BaseModel):
    """One execution (``exec_id`` set) or one order-level statement row (``exec_id`` None)."""

    contract: LedgerContract
    trade_time: datetime  # timezone-aware UTC
    quantity: float  # signed: + bought, - sold (contracts or shares)
    price: float  # per share
    proceeds: float  # signed cash, contract currency
    commission: float = 0.0  # signed; negative is a cost
    codes: str = ""  # raw IBKR code string, e.g. "A;O", "C;Ep"
    exec_id: str | None = None
    perm_id: int | None = None
    ib_order_id: int | None = None
    account: str | None = None
    ibkr_realized_pnl: float | None = None
    source_kind: LedgerSourceKind
    occurrence_idx: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class ParsedCashEvent(BaseModel):
    event_type: Literal["dividend", "withholding", "deposit", "withdrawal", "fee", "interest"]
    event_date: date
    currency: str
    amount: float  # signed
    description: str
    underlying: str | None = None
    occurrence_idx: int = 0


class ParsedCorporateAction(BaseModel):
    event_date: date
    underlying: str | None
    description: str
    quantity: float
    proceeds: float
    occurrence_idx: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class ParsedFxRate(BaseModel):
    rate_date: date
    currency: str
    usd_rate: float  # USD per 1 unit of `currency`


class LedgerParseError(BaseModel):
    line: int
    section: str
    message: str


class ParsedStatement(BaseModel):
    """What every feed (Activity CSV, Flex XML, live fills) normalises to before ingest."""

    account: str | None = None
    base_currency: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    executions: list[ParsedExecution] = Field(default_factory=list)
    cash_events: list[ParsedCashEvent] = Field(default_factory=list)
    corporate_actions: list[ParsedCorporateAction] = Field(default_factory=list)
    fx_rates: list[ParsedFxRate] = Field(default_factory=list)
    errors: list[LedgerParseError] = Field(default_factory=list)

    @property
    def fatal(self) -> bool:
        """A broken Trades row poisons the whole import; other sections only warn."""
        return any(e.section == "Trades" for e in self.errors)


class LedgerImportResult(BaseModel):
    run_id: int | None
    status: Literal["ok", "failed", "skipped"]
    reason: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    errors: list[LedgerParseError] = Field(default_factory=list)
```

- [ ] **Step 4: Create `src/ledger/__init__.py`**

```python
"""Trade ledger: whole-account broker truth (docs/superpowers/specs/2026-10-04-trade-ledger-design.md).

Reporting only. Nothing here is importable from src/engine/, src/execution/ or src/strategies/
(tests/test_web_fence.py).
"""
```

- [ ] **Step 5: Create `src/ledger/contracts.py`**

```python
"""Contract identity and time helpers shared by every ledger feed (CSV, Flex, live)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from src.common.schemas import LedgerContract

ET = ZoneInfo("America/New_York")

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"],
        start=1,
    )
}
_OPT_RE = re.compile(
    r"^(?P<und>\S+) (?P<day>\d{2})(?P<mon>[A-Z]{3})(?P<yy>\d{2}) "
    r"(?P<strike>\d+(?:\.\d+)?) (?P<right>[PC])$"
)
_TIMESTAMP_FORMATS = ("%Y-%m-%d, %H:%M:%S", "%Y%m%d;%H%M%S", "%Y-%m-%d;%H:%M:%S", "%Y%m%d")
_DATE_FORMATS = ("%Y-%m-%d", "%Y%m%d")


def parse_option_symbol(
    symbol: str, *, currency: str = "USD", multiplier: float = 100.0
) -> LedgerContract:
    """``"AMD 29AUG25 157.5 P"`` -> an OPT contract. Raises ValueError on anything else."""
    m = _OPT_RE.match(symbol.strip())
    if m is None:
        raise ValueError(f"unrecognised option symbol {symbol!r}")
    month = _MONTHS.get(m["mon"])
    if month is None:
        raise ValueError(f"unrecognised month in option symbol {symbol!r}")
    return LedgerContract(
        underlying=m["und"],
        sec_type="OPT",
        currency=currency,
        right="P" if m["right"] == "P" else "C",
        strike=float(m["strike"]),
        expiry=date(2000 + int(m["yy"]), month, int(m["day"])),
        multiplier=multiplier,
    )


def stock_contract(symbol: str, currency: str) -> LedgerContract:
    return LedgerContract(underlying=symbol.strip(), sec_type="STK", currency=currency.strip())


def parse_et_timestamp(value: str) -> datetime:
    """An IBKR statement timestamp (US/Eastern wall clock) -> timezone-aware UTC."""
    v = value.strip()
    for fmt in _TIMESTAMP_FORMATS:
        try:
            naive = datetime.strptime(v, fmt)
        except ValueError:
            continue
        return naive.replace(tzinfo=ET).astimezone(UTC)
    raise ValueError(f"unrecognised timestamp {value!r}")


def parse_ibkr_date(value: str) -> date:
    v = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {value!r}")


def et_date(ts: datetime) -> date:
    """The US/Eastern calendar date of a timestamp — the ledger's one trade-date definition."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(ET).date()


def parse_number(value: str) -> float:
    """``"1,385"`` -> 1385.0. Blank raises — callers decide whether blank is allowed."""
    v = value.strip().replace(",", "")
    if not v:
        raise ValueError("blank number")
    return float(v)
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_ledger_contracts.py -v`
Expected: all PASS. Then run `ruff check src/ledger src/common tests/test_ledger_contracts.py` and `mypy src`; expect them clean.

- [ ] **Step 7: Commit**

```bash
git add src/ledger/__init__.py src/ledger/contracts.py tests/test_ledger_contracts.py
git add -p src/common/schemas.py   # only the ledger hunks + import line
git commit -m "feat(ledger): contract identity, ET time helpers, ledger schemas"
```

---

### Task 2: ORM tables, ledger config and secrets

**Files:**
- Modify: `src/storage/models.py` (append), `src/common/config.py`, `config/settings.yaml`, `.env.example`
- Create: `src/ledger/state.py`
- Test: `tests/test_ledger_models.py`

**Interfaces:**
- Consumes: `src.storage.system_settings.get_setting/set_setting` (existing; `set_setting(key, value, *, session=None)`).
- Produces:
  - ORM classes `BrokerExecutionRow`, `BrokerCashEventRow`, `BrokerCorporateActionRow`, `FxRateRow`, `LedgerImportRunRow`, `TradeAnnotationRow`
  - `get_config().ledger` (`LedgerCfg`: `account`, `live_sweep_minutes`, `sheets_min_interval_seconds`, `upload_max_bytes`, `flex_poll_timeout_seconds`, `flex_poll_interval_seconds`, `fx_max_gap_days`)
  - Secrets `ibkr_flex_token`, `ibkr_flex_query_id`, `google_sheets_credentials_path`, `ledger_sheet_id`
  - `src.ledger.state`: constants `LEDGER_GENERATION_KEY`, `LEDGER_SYNCED_GENERATION_KEY`, `LEDGER_SHEETS_LAST_SYNC_KEY`, `LEDGER_SHEETS_LAST_ERROR_KEY`, `LEDGER_ACCOUNT_KEY`, `LEDGER_FLEX_LAST_RUN_KEY`, `LEDGER_FLEX_LAST_STATUS_KEY`
  - `bump_generation(session) -> None`
  - `read_int_setting(key) -> int`
  - `ledger_account(session) -> str | None`
  - `lock_account(session, account) -> None`

- [ ] **Step 1: Write the failing test** — `tests/test_ledger_models.py`

```python
"""Ledger tables, config and the generation/account-lock state (spec §3, §8, R8)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy.exc import IntegrityError


def _row(**kw):
    from src.storage.models import BrokerExecutionRow

    base = dict(
        dedupe_key="exec:1", source_kind="exec", source="live", trade_time=datetime(2025, 7, 1, 14),
        trade_date=date(2025, 7, 1), contract_ident="STK:NVDA:USD", underlying="NVDA",
        sec_type="STK", currency="USD", quantity=10, price=1.0, proceeds=-10.0,
    )
    base.update(kw)
    return BrokerExecutionRow(**base)


def test_dedupe_key_is_unique(db) -> None:
    with db() as s:
        s.add(_row())
    with pytest.raises(IntegrityError), db() as s:
        s.add(_row())


def test_annotation_order_key_is_unique(db) -> None:
    from src.storage.models import TradeAnnotationRow

    with db() as s:
        s.add(TradeAnnotationRow(order_key="a" * 16))
    with pytest.raises(IntegrityError), db() as s:
        s.add(TradeAnnotationRow(order_key="a" * 16))


def test_fx_rate_unique_per_date_and_currency(db) -> None:
    from src.storage.models import FxRateRow

    with db() as s:
        s.add(FxRateRow(rate_date=date(2026, 1, 6), currency="SGD", usd_rate=0.78, source="csv"))
    with pytest.raises(IntegrityError), db() as s:
        s.add(FxRateRow(rate_date=date(2026, 1, 6), currency="SGD", usd_rate=0.79, source="csv"))


def test_ledger_config_defaults() -> None:
    from src.common.config import get_config

    cfg = get_config().ledger
    assert cfg.live_sweep_minutes == 5
    assert cfg.sheets_min_interval_seconds == 60
    assert cfg.upload_max_bytes == 5_242_880
    assert cfg.fx_max_gap_days == 7


def test_generation_counter_increments(db) -> None:
    from src.ledger.state import LEDGER_GENERATION_KEY, bump_generation, read_int_setting

    assert read_int_setting(LEDGER_GENERATION_KEY) == 0
    with db() as s:
        bump_generation(s)
    with db() as s:
        bump_generation(s)
    assert read_int_setting(LEDGER_GENERATION_KEY) == 2


def test_account_lock_prefers_config_then_setting(db, monkeypatch) -> None:
    from src.common.config import get_config
    from src.ledger.state import ledger_account, lock_account

    with db() as s:
        assert ledger_account(s) is None
        lock_account(s, "U1")
    with db() as s:
        assert ledger_account(s) == "U1"
    monkeypatch.setattr(get_config().ledger, "account", "U9")
    with db() as s:
        assert ledger_account(s) == "U9"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ledger_models.py -v`
Expected: FAIL. ImportError on `BrokerExecutionRow`, and `Config` has no attribute `ledger`.

- [ ] **Step 3: Append the ORM classes to `src/storage/models.py`**

```python
# --------------------------------------------------------------------------- #
# Trade ledger — whole-account broker truth (docs/superpowers/specs/2026-10-04-trade-ledger-design.md).
# Written only by src/ledger/ingest.py and src/ledger/annotations.py; read by
# src/reporting/trade_ledger.py. Never read by the engine, execution, or strategies.
# --------------------------------------------------------------------------- #
class BrokerExecutionRow(Base):
    """One IBKR execution (``source_kind="exec"``) or one order-level statement row (``"order"``).

    ``superseded_by`` is set on a row whose twin from a higher-priority feed exists (spec R2);
    builders ignore superseded rows. ``trade_time`` is naive UTC; ``trade_date`` is the
    US/Eastern date.
    """

    __tablename__ = "broker_executions"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_broker_executions_dedupe_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(96))
    source_kind: Mapped[str] = mapped_column(String(8))  # "exec" | "order"
    source: Mapped[str] = mapped_column(String(8))  # "csv" | "flex" | "live"
    exec_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    perm_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    ib_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trade_time: Mapped[datetime] = mapped_column(DateTime)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    contract_ident: Mapped[str] = mapped_column(String(80), index=True)
    underlying: Mapped[str] = mapped_column(String(24), index=True)
    sec_type: Mapped[str] = mapped_column(String(4))
    right: Mapped[str | None] = mapped_column(String(1), nullable=True)
    strike: Mapped[float | None] = mapped_column(Float, nullable=True)
    expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    currency: Mapped[str] = mapped_column(String(3))
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    proceeds: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    codes: Mapped[str] = mapped_column(String(32), default="")
    ibkr_realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    occurrence_idx: Mapped[int] = mapped_column(Integer, default=0)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    book: Mapped[str] = mapped_column(String(8), default="manual")  # "system" | "manual"
    import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class BrokerCashEventRow(Base):
    """Dividend, withholding, deposit/withdrawal, fee or interest cash line."""

    __tablename__ = "broker_cash_events"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_broker_cash_events_dedupe_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(96))
    event_type: Mapped[str] = mapped_column(String(12))
    event_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text, default="")
    underlying: Mapped[str | None] = mapped_column(String(24), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(8))
    import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class BrokerCorporateActionRow(Base):
    """Stored and flagged for human review — never auto-applied to cost basis (spec §3)."""

    __tablename__ = "broker_corporate_actions"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_broker_corporate_actions_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dedupe_key: Mapped[str] = mapped_column(String(96))
    event_date: Mapped[date] = mapped_column(Date)
    underlying: Mapped[str | None] = mapped_column(String(24), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    proceeds: Mapped[float] = mapped_column(Float, default=0.0)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(8))
    import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class FxRateRow(Base):
    """USD per 1 unit of ``currency`` on ``rate_date`` (from Forex trades / Flex ConversionRates)."""

    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("rate_date", "currency", name="uq_fx_rates_date_currency"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rate_date: Mapped[date] = mapped_column(Date, index=True)
    currency: Mapped[str] = mapped_column(String(3))
    usd_rate: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(8))


class LedgerImportRunRow(Base):
    """One ingest call — its source, outcome, counts and (capped) parse errors."""

    __tablename__ = "ledger_import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(8))
    filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="running")
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)


class TradeAnnotationRow(Base):
    """Operator edits, keyed by the opening order's source-independent ``order_key`` (R3)."""

    __tablename__ = "trade_annotations"
    __table_args__ = (UniqueConstraint("order_key", name="uq_trade_annotations_order_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_key: Mapped[str] = mapped_column(String(16))
    notes: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    outcome_override: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exclude_from_stats: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[str] = mapped_column(String(64), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
```

Check the `from sqlalchemy import (...)` block at the top of `models.py` already includes `Boolean, Date, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint`; add any that are missing. New tables are created by the existing `Base.metadata.create_all` in `init_db`, so no `_ADDED_COLUMNS` entry is needed.

- [ ] **Step 4: Add `LedgerCfg` and secrets to `src/common/config.py`**

In `class Secrets`, after the `openai_api_key` line, add:

```python
    # Trade ledger (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §5.2, §7).
    ibkr_flex_token: str = Field(default="", alias="IBKR_FLEX_TOKEN")
    ibkr_flex_query_id: str = Field(default="", alias="IBKR_FLEX_QUERY_ID")
    google_sheets_credentials_path: str = Field(default="", alias="GOOGLE_SHEETS_CREDENTIALS_PATH")
    ledger_sheet_id: str = Field(default="", alias="LEDGER_SHEET_ID")
```

Immediately above `class Config(BaseModel):` add:

```python
class LedgerCfg(BaseModel):
    """Trade ledger tunables (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §8).

    ``account`` pins the IBKR account the ledger tracks. Empty means "lock to the account of the
    first CSV/Flex import" (R8) — live fills never set the lock, so a paper session can't claim
    the ledger before the real history is imported.
    """

    account: str = ""
    live_sweep_minutes: int = 5
    sheets_min_interval_seconds: int = 60
    upload_max_bytes: int = 5_242_880
    flex_poll_timeout_seconds: float = 600.0
    flex_poll_interval_seconds: float = 10.0
    fx_max_gap_days: int = 7
```

In `class Config`, directly after the line `research: ResearchCfg = Field(default_factory=ResearchCfg)`, add:

```python
    ledger: LedgerCfg = Field(default_factory=LedgerCfg)
```

- [ ] **Step 5: Add the YAML block and env keys**

Append to `config/settings.yaml`:

```yaml

# Trade ledger — whole-account history, dashboard /ledger, Google Sheet mirror.
# docs/superpowers/specs/2026-10-04-trade-ledger-design.md §8. Secrets live in .env.
ledger:
  account: ""                      # IBKR account to track; "" = lock to the first CSV/Flex import
  live_sweep_minutes: 5            # reqExecutions sweep cadence in the approval service
  sheets_min_interval_seconds: 60  # Google Sheet rewrite at most this often
  upload_max_bytes: 5242880        # dashboard CSV upload cap (5 MB)
  flex_poll_timeout_seconds: 600   # give up waiting for IBKR to generate a Flex statement
  flex_poll_interval_seconds: 10
  fx_max_gap_days: 7               # nearest FX rate may be at most this many days away
```

Append to `.env.example`:

```bash

# --- Trade ledger (optional) ---
# IBKR Flex Web Service: Client Portal -> Performance & Reports -> Flex Queries (see SETUP.md).
IBKR_FLEX_TOKEN=
IBKR_FLEX_QUERY_ID=
# Google Sheets mirror: service-account JSON key path + the spreadsheet id from its URL.
GOOGLE_SHEETS_CREDENTIALS_PATH=
LEDGER_SHEET_ID=
```

- [ ] **Step 6: Create `src/ledger/state.py`**

```python
"""Ledger-wide ``system_settings`` keys: the change generation the Sheets mirror follows, the
locked account (R8), and feed status the import page reads."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.config import get_config
from src.storage.models import SystemSettingRow
from src.storage.system_settings import get_setting, set_setting

LEDGER_GENERATION_KEY = "ledger_generation"
LEDGER_SYNCED_GENERATION_KEY = "ledger_sheets_synced_generation"
LEDGER_SHEETS_LAST_SYNC_KEY = "ledger_sheets_last_sync"
LEDGER_SHEETS_LAST_ERROR_KEY = "ledger_sheets_last_error"
LEDGER_ACCOUNT_KEY = "ledger_account"
LEDGER_FLEX_LAST_RUN_KEY = "ledger_flex_last_run"
LEDGER_FLEX_LAST_STATUS_KEY = "ledger_flex_last_status"


def _session_value(session: Session, key: str) -> str | None:
    row = session.scalar(select(SystemSettingRow).where(SystemSettingRow.key == key))
    return row.value if row is not None else None


def bump_generation(session: Session) -> None:
    """Mark the ledger changed, inside the caller's transaction."""
    current = _session_value(session, LEDGER_GENERATION_KEY) or "0"
    nxt = int(current) + 1 if current.isdigit() else 1
    set_setting(LEDGER_GENERATION_KEY, str(nxt), session=session)


def read_int_setting(key: str) -> int:
    value = get_setting(key, "0")
    return int(value) if value.isdigit() else 0


def ledger_account(session: Session) -> str | None:
    """The account the ledger tracks: ``ledger.account`` if set, else the locked one, else None."""
    configured = get_config().ledger.account.strip()
    if configured:
        return configured
    locked = (_session_value(session, LEDGER_ACCOUNT_KEY) or "").strip()
    return locked or None


def lock_account(session: Session, account: str) -> None:
    set_setting(LEDGER_ACCOUNT_KEY, account.strip(), session=session)
```

- [ ] **Step 7: Run the tests**

Run: `python -m pytest tests/test_ledger_models.py tests/test_ledger_contracts.py -v`
Expected: all PASS. `mypy src` should be clean.

- [ ] **Step 8: Commit**

```bash
git add src/ledger/state.py tests/test_ledger_models.py
git add -p src/storage/models.py src/common/config.py config/settings.yaml .env.example
git commit -m "feat(ledger): ledger tables, LedgerCfg, flex/sheets secrets, generation + account lock"
```

---

### Task 3: Activity Statement CSV parser

**Files:**
- Create: `src/ledger/activity_csv.py`, `tests/fixtures/ledger/activity_statement_sample.csv`
- Test: `tests/test_ledger_activity_csv.py`

**Interfaces:**
- Consumes: Task 1 schemas and helpers.
- Produces:
  - `parse_activity_csv(text: str) -> ParsedStatement`
  - `class NotAnActivityStatement(ValueError)`
  - `number_occurrences(statement: ParsedStatement) -> None` (also used by Flex in Task 10)

- [ ] **Step 1: Create the fixture** — `tests/fixtures/ledger/activity_statement_sample.csv`

This is a scrubbed copy of the real statement's row shapes. The account id is fake, and the file includes one deliberately non-100 multiplier contract (`OPEN1`, multiplier 50).

```csv
Statement,Header,Field Name,Field Value
Statement,Data,Title,Activity Statement
Statement,Data,Period,"April 1, 2025 - April 1, 2026"
Account Information,Header,Field Name,Field Value
Account Information,Data,Account,U0000001
Account Information,Data,Base Currency,SGD
Deposits & Withdrawals,Header,Currency,Settle Date,Description,Amount
Deposits & Withdrawals,Data,USD,2025-05-26,Electronic Fund Transfer,45000
Deposits & Withdrawals,Data,SGD,2026-01-02,Disbursement Initiated,-6371.24
Deposits & Withdrawals,Data,Total,,,-6371.24
Fees,Header,Subtitle,Currency,Date,Description,Amount
Fees,Data,Other Fees,SGD,2025-07-02,Snapshot fee for Jun 2025,-0.04
Dividends,Header,Currency,Date,Description,Amount
Dividends,Data,USD,2025-06-13,QDTE(US77926X3044) Cash Dividend USD 0.145807 per Share (Ordinary Dividend),29.16
Dividends,Data,Total,,,29.16
Withholding Tax,Header,Currency,Date,Description,Amount,Code
Withholding Tax,Data,USD,2025-06-13,QDTE(US77926X3044) Cash Dividend USD 0.145807 per Share - US Tax,-8.75,
Withholding Tax,Data,USD,2025-06-13,QDTE(US77926X3044) Cash Dividend USD 0.145807 per Share - US Tax,8.75,
Withholding Tax,Data,USD,2025-06-13,QDTE(US77926X3044) Cash Dividend USD 0.145807 per Share - US Tax,-8.75,
Interest,Header,Currency,Date,Description,Amount
Interest,Data,SGD,2025-04-03,SGD Credit Interest for Mar-2025,20.73
Interest,Data,Total,,,20.73
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code
Trades,Data,Order,Stocks,SGD,A17U,"2025-07-17, 01:31:33",500,2.77,2.78,-1385,-2.725,1387.725,0,5,O
Trades,Data,Order,Stocks,USD,AMZN,"2025-10-10, 16:20:00",100,215,216.37,-21500,0,21500,0,137,A;O
Trades,Data,Order,Stocks,USD,AMZN,"2025-10-31, 16:20:00",-100,235,244.22,23500,-0.018094,-21324.143072,2576.968262,-922,A;C
Trades,Data,Order,Stocks,USD,OPEN,"2025-09-19, 16:20:00",400,3,9.57,-1200,0,1200,0,2628,Ex;O
Trades,SubTotal,,Stocks,USD,AMZN,,0,,,2000,-0.02,,,,
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code
Trades,Data,Order,Equity and Index Options,USD,NVDA 27JUN25 138 P,"2025-06-17, 10:02:11",-1,1.31,1.30,131,-1.0446,-129.9554,0,1,O
Trades,Data,Order,Equity and Index Options,USD,NVDA 27JUN25 138 P,"2025-06-27, 11:09:57",1,0.01,0,-1,-1.1531655,129.843793,127.690628,-1,C
Trades,Data,Order,Equity and Index Options,USD,AMZN 18JUL25 207.5 P,"2025-06-25, 13:17:15",-1,3.25,3.325,325,-1.1562066,-323.8437934,0,-7.5,O
Trades,Data,Order,Equity and Index Options,USD,AMZN 18JUL25 207.5 P,"2025-07-18, 16:20:00",1,0,0,0,0,323.843793,323.843793,0,C;Ep
Trades,Data,Order,Equity and Index Options,USD,AMZN 10OCT25 215 P,"2025-10-03, 14:45:08",-1,1.77,1.785,177,-1.1430721,-175.8569279,0,-1.5,O
Trades,Data,Order,Equity and Index Options,USD,AMZN 10OCT25 215 P,"2025-10-10, 16:20:00",1,0,0,0,0,175.856928,0,0,A;C
Trades,Data,Order,Equity and Index Options,USD,AMZN 31OCT25 235 C,"2025-10-20, 10:30:00",-1,4.01,4.0,401,-1.0,-400,0,1,O
Trades,Data,Order,Equity and Index Options,USD,AMZN 31OCT25 235 C,"2025-10-31, 16:20:00",1,0,9.22,0,0,401.129428,0,922,A;C
Trades,Data,Order,Equity and Index Options,USD,OPEN 19SEP25 3 C,"2025-07-21, 10:00:00",4,1.2,1.2,-480,-2.6,482.6,0,0,O
Trades,Data,Order,Equity and Index Options,USD,OPEN 19SEP25 3 C,"2025-09-19, 16:20:00",-4,0,6.57,0,0,-615.078814,0,-2628,C;Ex
Trades,Data,Order,Equity and Index Options,USD,OPEN1 19DEC25 5 C,"2025-11-20, 10:00:00",-2,0.5,0.5,50,-1.0,-49,0,0,O
Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,T. Price,,Proceeds,Comm in SGD,,,MTM in SGD,Code
Trades,Data,Order,Forex,SGD,USD.SGD,"2026-01-06, 06:49:36",-15.88,1.2795,,20.31846,-2.5656,,,-0.017468,
Trades,Total,,Forex,SGD,,,,,,20.31846,-2.5656,,,-0.017468,
Corporate Actions,Header,Asset Category,Currency,Report Date,Date/Time,Description,Quantity,Proceeds,Value,Realized P/L,Code
Corporate Actions,Data,Warrants,USD,2025-11-18,"2025-11-17, 20:25:00","OPEN(US6837121036) Spinoff OPENW 1 for 30 (OPENW, OPENW 20NOV26 11.5 C, US6837121291)",30,0,7.056,0,
Corporate Actions,Data,Total,,,,,,0,7.056,0,
Financial Instrument Information,Header,Asset Category,Symbol,Description,Conid,Security ID,Underlying,Listing Exch,Multiplier,Expiry,Delivery Month,Type,Strike,Code
Financial Instrument Information,Data,Equity and Index Options,NVDA  250627P00138000,NVDA 27JUN25 138 P,1,,NVDA,CBOE,100,2025-06-27,2025-06,P,138,
Financial Instrument Information,Data,Equity and Index Options,OPEN1 251219C00005000,OPEN1 19DEC25 5 C,2,,OPEN,CBOE,50,2025-12-19,2025-12,C,5,
```

The fixture holds 4 stock rows and 11 option rows, so the parser should produce **15 executions**. The SubTotal, Total and Forex rows are not executions.

- [ ] **Step 2: Write the failing test** — `tests/test_ledger_activity_csv.py`

```python
"""Activity Statement CSV parser (spec §5.1; R1, R2, R7, R11; Review Focus 1, 5)."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.ledger.activity_csv import NotAnActivityStatement, parse_activity_csv

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"


@pytest.fixture(scope="module")
def st():
    return parse_activity_csv(FIXTURE.read_text(encoding="utf-8"))


def test_statement_metadata(st) -> None:
    assert st.account == "U0000001"
    assert st.base_currency == "SGD"
    assert (st.period_start, st.period_end) == (date(2025, 4, 1), date(2026, 4, 1))
    assert st.fatal is False


def test_execution_count_excludes_subtotals_totals_and_forex(st) -> None:
    assert len(st.executions) == 15
    assert all(e.source_kind == "order" and e.exec_id is None for e in st.executions)


def test_option_open_row_fields(st) -> None:
    e = next(x for x in st.executions if x.contract.ident == "OPT:NVDA:20250627:P:138:USD" and x.quantity < 0)
    assert (e.quantity, e.price, e.proceeds, e.codes) == (-1.0, 1.31, 131.0, "O")
    assert e.commission == pytest.approx(-1.0446)
    assert e.trade_time == datetime(2025, 6, 17, 14, 2, 11, tzinfo=UTC)


def test_expiry_and_assignment_codes_are_kept(st) -> None:
    exp = next(x for x in st.executions if x.contract.ident.startswith("OPT:AMZN:20250718") and x.quantity > 0)
    assert (exp.codes, exp.price) == ("C;Ep", 0.0)
    delivery = next(x for x in st.executions if x.contract.ident == "STK:AMZN:USD" and x.quantity > 0)
    assert delivery.codes == "A;O"


def test_multiplier_comes_from_instrument_section(st) -> None:
    # Review Focus 5 — OPEN1 is an adjusted contract with multiplier 50.
    e = next(x for x in st.executions if x.contract.underlying == "OPEN1")
    assert e.contract.multiplier == 50.0
    nvda = next(x for x in st.executions if x.contract.underlying == "NVDA")
    assert nvda.contract.multiplier == 100.0


def test_ibkr_realized_pnl_is_kept_for_cross_check(st) -> None:
    sold = next(x for x in st.executions if x.contract.ident == "STK:AMZN:USD" and x.quantity < 0)
    assert sold.ibkr_realized_pnl == pytest.approx(2576.968262)


def test_forex_row_becomes_an_fx_rate(st) -> None:
    assert len(st.fx_rates) == 1
    fx = st.fx_rates[0]
    assert (fx.currency, fx.rate_date) == ("SGD", date(2026, 1, 6))
    assert fx.usd_rate == pytest.approx(1 / 1.2795)


def test_cash_events(st) -> None:
    kinds = sorted((c.event_type, c.currency, c.amount) for c in st.cash_events)
    assert ("deposit", "USD", 45000.0) in kinds
    assert ("withdrawal", "SGD", -6371.24) in kinds
    assert ("dividend", "USD", 29.16) in kinds
    assert ("fee", "SGD", -0.04) in kinds
    assert ("interest", "SGD", 20.73) in kinds
    assert not any(c.currency.startswith("Total") for c in st.cash_events)
    div = next(c for c in st.cash_events if c.event_type == "dividend")
    assert div.underlying == "QDTE"


def test_identical_withholding_lines_get_distinct_occurrences(st) -> None:
    neg = [c for c in st.cash_events if c.event_type == "withholding" and c.amount == -8.75]
    assert sorted(c.occurrence_idx for c in neg) == [0, 1]


def test_corporate_action_parsed_and_total_skipped(st) -> None:
    assert len(st.corporate_actions) == 1
    ca = st.corporate_actions[0]
    assert (ca.event_date, ca.underlying, ca.quantity) == (date(2025, 11, 18), "OPEN", 30.0)


def test_pdf_is_rejected() -> None:
    with pytest.raises(NotAnActivityStatement):
        parse_activity_csv("%PDF-1.7 binary junk")


def test_random_csv_is_rejected() -> None:
    with pytest.raises(NotAnActivityStatement):
        parse_activity_csv("a,b,c\n1,2,3\n")


def test_broken_trades_row_is_fatal() -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace('"2025-06-17, 10:02:11",-1,', '"2025-06-17, 10:02:11",abc,')
    st = parse_activity_csv(text)
    assert st.fatal is True
    assert any(e.section == "Trades" for e in st.errors)


def test_unsupported_asset_category_only_warns() -> None:
    extra = 'Trades,Data,Order,Warrants,USD,OPENW,"2025-11-20, 10:00:00",30,0.2,0.2,-6,0,6,0,0,O\n'
    text = FIXTURE.read_text(encoding="utf-8").replace("Trades,SubTotal", extra + "Trades,SubTotal", 1)
    st = parse_activity_csv(text)
    assert st.fatal is False
    assert any(e.section == "Trades:unsupported" for e in st.errors)


@pytest.mark.skipif(
    not os.environ.get("LEDGER_REAL_STATEMENT"),
    reason="set LEDGER_REAL_STATEMENT=/path/to/real/activity.csv to run against the operator's file",
)
def test_operators_real_statement_parses_cleanly() -> None:
    st = parse_activity_csv(Path(os.environ["LEDGER_REAL_STATEMENT"]).read_text(encoding="utf-8-sig"))
    assert st.fatal is False, [e for e in st.errors if e.section == "Trades"][:5]
    assert len(st.executions) == 608  # 485 option + 123 stock order rows (Apr-2025..Apr-2026 file)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_ledger_activity_csv.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ledger.activity_csv'`.

- [ ] **Step 4: Write `src/ledger/activity_csv.py`**

```python
"""IBKR Activity Statement CSV -> ParsedStatement (spec §5.1; revisions R1, R2, R7, R11).

The file is multi-section: column 0 is the section name, column 1 is Header/Data/SubTotal/
Total/Notes. A section can carry several Header rows (Trades has one per asset class); every
Data row is zipped against the most recent Header for its section. Rows are ORDER-level
(DataDiscriminator "Order"), never execution-level — they carry no execId (R2).
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime

from src.common.schemas import (
    LedgerContract,
    LedgerParseError,
    ParsedCashEvent,
    ParsedCorporateAction,
    ParsedExecution,
    ParsedFxRate,
    ParsedStatement,
)
from src.ledger.contracts import (
    et_date,
    parse_et_timestamp,
    parse_ibkr_date,
    parse_number,
    parse_option_symbol,
    stock_contract,
)

_TICKER_PREFIX = re.compile(r"^([A-Z0-9.]+)\(")
_PERIOD = re.compile(r"^(?P<a>[A-Za-z]+ \d{1,2}, \d{4}) - (?P<b>[A-Za-z]+ \d{1,2}, \d{4})$")
_OPTION_CATEGORY = "Equity and Index Options"


class NotAnActivityStatement(ValueError):
    """The text is not an IBKR Activity Statement CSV (wrong file, or a PDF)."""


class _Acc:
    def __init__(self) -> None:
        self.st = ParsedStatement()
        self.pending_options: list[tuple[str, dict[str, str], int]] = []
        self.multipliers: dict[str, float] = {}
        self.is_activity_statement = False


Handler = Callable[[_Acc, dict[str, str], int], None]


def _optional_number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return parse_number(value)


def _underlying_from(description: str) -> str | None:
    m = _TICKER_PREFIX.match(description.strip())
    return m.group(1) if m else None


def _is_total(rec: dict[str, str], key: str) -> bool:
    return rec.get(key, "").strip().startswith("Total")


def _statement(acc: _Acc, rec: dict[str, str], line: int) -> None:
    name, value = rec.get("Field Name", ""), rec.get("Field Value", "").strip()
    if name == "Title" and value == "Activity Statement":
        acc.is_activity_statement = True
    elif name == "Period":
        m = _PERIOD.match(value)
        if m:
            acc.st.period_start = datetime.strptime(m["a"], "%B %d, %Y").date()
            acc.st.period_end = datetime.strptime(m["b"], "%B %d, %Y").date()


def _account_info(acc: _Acc, rec: dict[str, str], line: int) -> None:
    name, value = rec.get("Field Name", ""), rec.get("Field Value", "").strip()
    if name == "Account":
        acc.st.account = value
    elif name == "Base Currency":
        acc.st.base_currency = value


def _execution(contract: LedgerContract, rec: dict[str, str]) -> ParsedExecution:
    return ParsedExecution(
        contract=contract,
        trade_time=parse_et_timestamp(rec["Date/Time"]),
        quantity=parse_number(rec["Quantity"]),
        price=parse_number(rec["T. Price"]),
        proceeds=parse_number(rec["Proceeds"]),
        commission=_optional_number(rec.get("Comm/Fee")) or 0.0,
        codes=rec.get("Code", "").strip(),
        ibkr_realized_pnl=_optional_number(rec.get("Realized P/L")),
        source_kind="order",
        raw=dict(rec),
    )


def _forex(acc: _Acc, rec: dict[str, str]) -> None:
    pair = rec.get("Symbol", "")
    if "." not in pair:
        return
    base, quote = pair.split(".", 1)
    price = parse_number(rec["T. Price"])
    day = et_date(parse_et_timestamp(rec["Date/Time"]))
    if base == "USD" and price > 0:
        acc.st.fx_rates.append(ParsedFxRate(rate_date=day, currency=quote, usd_rate=1.0 / price))
    elif quote == "USD":
        acc.st.fx_rates.append(ParsedFxRate(rate_date=day, currency=base, usd_rate=price))


def _trade(acc: _Acc, rec: dict[str, str], line: int) -> None:
    if rec.get("DataDiscriminator") != "Order":
        return
    asset = rec.get("Asset Category", "")
    if asset == "Forex":
        _forex(acc, rec)
    elif asset == _OPTION_CATEGORY:
        # Multipliers live in "Financial Instrument Information", which comes AFTER Trades in
        # the file — options are finalised once the whole file has been read.
        acc.pending_options.append((rec["Symbol"], rec, line))
    elif asset == "Stocks":
        acc.st.executions.append(_execution(stock_contract(rec["Symbol"], rec["Currency"]), rec))
    else:
        acc.st.errors.append(
            LedgerParseError(
                line=line, section="Trades:unsupported", message=f"asset category {asset!r} not imported"
            )
        )


def _cash(event_type: str, date_key: str = "Date") -> Handler:
    def handler(acc: _Acc, rec: dict[str, str], line: int) -> None:
        if _is_total(rec, "Currency") or not rec.get(date_key, "").strip():
            return
        amount = parse_number(rec["Amount"])
        kind = "withdrawal" if event_type == "deposit" and amount < 0 else event_type
        description = rec.get("Description", "").strip()
        acc.st.cash_events.append(
            ParsedCashEvent(
                event_type=kind,  # type: ignore[arg-type]
                event_date=parse_ibkr_date(rec[date_key]),
                currency=rec["Currency"].strip(),
                amount=amount,
                description=description,
                underlying=_underlying_from(description) if kind in ("dividend", "withholding") else None,
            )
        )

    return handler


def _corporate_action(acc: _Acc, rec: dict[str, str], line: int) -> None:
    if _is_total(rec, "Asset Category"):
        return
    description = rec.get("Description", "").strip()
    acc.st.corporate_actions.append(
        ParsedCorporateAction(
            event_date=parse_ibkr_date(rec["Report Date"]),
            underlying=_underlying_from(description),
            description=description,
            quantity=_optional_number(rec.get("Quantity")) or 0.0,
            proceeds=_optional_number(rec.get("Proceeds")) or 0.0,
            raw=dict(rec),
        )
    )


def _instrument(acc: _Acc, rec: dict[str, str], line: int) -> None:
    if rec.get("Asset Category") != _OPTION_CATEGORY:
        return
    mult = _optional_number(rec.get("Multiplier"))
    if mult:
        acc.multipliers[rec.get("Description", "").strip()] = mult


_HANDLERS: dict[str, Handler] = {
    "Statement": _statement,
    "Account Information": _account_info,
    "Trades": _trade,
    "Dividends": _cash("dividend"),
    "Withholding Tax": _cash("withholding"),
    "Deposits & Withdrawals": _cash("deposit", date_key="Settle Date"),
    "Fees": _cash("fee"),
    "Interest": _cash("interest"),
    "Corporate Actions": _corporate_action,
    "Financial Instrument Information": _instrument,
}


def number_occurrences(st: ParsedStatement) -> None:
    """Distinguish genuinely identical rows within one file so both survive dedupe (R2)."""
    seen: Counter[tuple[object, ...]] = Counter()
    for e in st.executions:
        sig: tuple[object, ...] = ("x", e.contract.ident, e.trade_time, e.quantity, e.price)
        e.occurrence_idx = seen[sig]
        seen[sig] += 1
    for c in st.cash_events:
        sig = ("c", c.event_type, c.event_date, c.currency, round(c.amount, 2), c.underlying)
        c.occurrence_idx = seen[sig]
        seen[sig] += 1
    for a in st.corporate_actions:
        sig = ("a", a.event_date, a.description)
        a.occurrence_idx = seen[sig]
        seen[sig] += 1


def parse_activity_csv(text: str) -> ParsedStatement:
    """Parse an Activity Statement. Raises NotAnActivityStatement for a PDF or a foreign CSV."""
    body = text.lstrip("﻿")
    if body.lstrip().startswith("%PDF"):
        raise NotAnActivityStatement("PDF statements aren't supported; download the CSV version")
    acc = _Acc()
    headers: dict[str, list[str]] = {}
    for line_no, row in enumerate(csv.reader(io.StringIO(body)), start=1):
        if len(row) < 2:
            continue
        section, kind = row[0].lstrip("﻿"), row[1]
        if kind == "Header":
            headers[section] = row[2:]
            continue
        if kind != "Data" or section not in _HANDLERS or section not in headers:
            continue
        rec = dict(zip(headers[section], row[2:], strict=False))
        try:
            _HANDLERS[section](acc, rec, line_no)
        except (ValueError, KeyError) as exc:
            acc.st.errors.append(LedgerParseError(line=line_no, section=section, message=str(exc)))
    if not acc.is_activity_statement:
        raise NotAnActivityStatement("missing the 'Statement / Title / Activity Statement' row")
    for symbol, rec, line_no in acc.pending_options:
        try:
            contract = parse_option_symbol(
                symbol,
                currency=rec["Currency"].strip(),
                multiplier=acc.multipliers.get(symbol.strip(), 100.0),
            )
            acc.st.executions.append(_execution(contract, rec))
        except (ValueError, KeyError) as exc:
            acc.st.errors.append(LedgerParseError(line=line_no, section="Trades", message=str(exc)))
    number_occurrences(acc.st)
    return acc.st
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_ledger_activity_csv.py -v`
Expected: all PASS except the real-file test, which reports SKIPPED. Then run the real file once locally:

```bash
LEDGER_REAL_STATEMENT="$HOME/Downloads/U1234567_U1234567_20250401_20260401_AS_Fv2_<hash>.csv" \
  python -m pytest tests/test_ledger_activity_csv.py::test_operators_real_statement_parses_cleanly -v
```
Expected: PASS. If the count differs from 608, print the `Trades:unsupported` warnings and reconcile the count against the real file before changing the parser.

- [ ] **Step 6: Commit**

```bash
git add src/ledger/activity_csv.py tests/fixtures/ledger/activity_statement_sample.csv tests/test_ledger_activity_csv.py
git commit -m "feat(ledger): IBKR Activity Statement CSV parser"
```

---

### Task 4: Ingest — dedupe, twin pass, account lock, book tagging, CLI

**Files:**
- Create: `src/ledger/ingest.py`, `scripts/ledger_import.py`
- Test: `tests/test_ledger_ingest.py`

**Interfaces:**
- Consumes:
  - `ParsedStatement` (Task 1)
  - `parse_activity_csv`, `NotAnActivityStatement` (Task 3)
  - `bump_generation`, `ledger_account`, `lock_account` (Task 2)
  - `OrderRow` (existing: `ib_order_id`, `snapshot`)
- Produces:
  - `ingest(statement, *, source: LedgerSource, filename: str | None = None) -> LedgerImportResult`
  - `execution_dedupe_key(e: ParsedExecution) -> str`
  - `supersede_twins(session, affected: set[tuple[str, date]]) -> int`
  - CLI `python -m scripts.ledger_import PATH [--dry-run]`

**Rules this task implements:**
- **Dedupe keys:**
  - `exec:<execId>` when there is an execId;
  - otherwise `order:` + sha1(ident | UTC ISO time | qty | price to 6dp | occurrence)[:32].
- **Twin pass (R2), per affected (contract, ET date), over non-superseded rows:**
  1. Each `order` row is superseded by the best-matching unused `exec` group. A group is the rows sharing a `perm_id`, or a single row without one. To match, the group's summed quantity must equal the order row's quantity (±1e-6) and its VWAP must be within 0.005; the best match is the smallest |VWAP − price|. `superseded_by` is set to the smallest row id in the group.
  2. Remaining `order` rows from different `source`s with the same sign, quantity (±1e-6) and price (±0.005): the later id is superseded by the earlier one, one-to-one.
- **Account (R8):**
  - If the ledger account is set and the statement account (or the first execution's account) differs → `failed`, reason `account_mismatch`.
  - If the ledger account is unset: a `csv`/`flex` import locks it to the statement account; `live` → `skipped`, reason `no_ledger_account`, and no run row is written.
- **Book:** an inserted row whose `ib_order_id` matches an `OrderRow.ib_order_id` gets book `system`, provided the order's `snapshot` is null or `snapshot["underlying"]` equals the row's underlying.
- **Generation:** bumped when anything was inserted or superseded.

- [ ] **Step 1: Write the failing test** — `tests/test_ledger_ingest.py`

```python
"""Ingest: idempotent upsert, order-level twin pass, account lock, book tagging (spec §5.4, R2, R8).

Review Focus 2 (overlapping statements), 3 (paper fills vs real account, ingest side), 4 (ET date
line) are pinned here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.common.schemas import ParsedExecution, ParsedStatement
from src.ledger.activity_csv import parse_activity_csv
from src.ledger.contracts import parse_et_timestamp, parse_option_symbol, stock_contract

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"


def ex(symbol: str, when: str, qty: float, price: float, *, exec_id: str | None = None,
       perm: int | None = None, order_id: int | None = None, comm: float = -1.0, codes: str = "",
       account: str = "U0000001", currency: str = "USD", utc: datetime | None = None) -> ParsedExecution:
    contract = parse_option_symbol(symbol, currency=currency) if " " in symbol else stock_contract(symbol, currency)
    return ParsedExecution(
        contract=contract,
        trade_time=utc or parse_et_timestamp(when),
        quantity=qty, price=price, proceeds=-qty * price * contract.multiplier, commission=comm,
        codes=codes, exec_id=exec_id, perm_id=perm, ib_order_id=order_id, account=account,
        source_kind="exec" if exec_id else "order",
    )


def stmt(*execs: ParsedExecution, account: str | None = "U0000001") -> ParsedStatement:
    return ParsedStatement(account=account, executions=list(execs))


def _rows(db):
    from src.storage.models import BrokerExecutionRow

    with db() as s:
        return list(s.scalars(select(BrokerExecutionRow).order_by(BrokerExecutionRow.id)))


def test_reimporting_the_same_file_is_a_noop(db) -> None:
    from src.ledger.ingest import ingest

    st = parse_activity_csv(FIXTURE.read_text())
    first = ingest(st, source="csv", filename="a.csv")
    second = ingest(parse_activity_csv(FIXTURE.read_text()), source="csv", filename="a.csv")
    assert first.status == "ok" and first.counts["new"] == 15
    assert second.counts.get("new", 0) == 0 and second.counts["duplicate"] == 15
    assert len(_rows(db)) == 15


def test_overlapping_statement_inserts_only_new_rows(db) -> None:
    # Review Focus 2.
    from src.ledger.ingest import ingest

    a = ex("NVDA 18JUL25 170 P", "2025-07-11, 10:00:00", -1, 2.0)
    b = ex("NVDA 25JUL25 165 P", "2025-07-16, 10:00:00", -1, 1.5)
    c = ex("NVDA 01AUG25 160 P", "2025-07-23, 10:00:00", -1, 1.2)
    ingest(stmt(a, b), source="csv")
    result = ingest(stmt(b, c), source="csv")
    assert (result.counts["new"], result.counts["duplicate"]) == (1, 1)
    assert len(_rows(db)) == 3


def test_csv_order_superseded_by_exec_fills_arriving_later(db) -> None:
    from src.ledger.ingest import ingest

    ingest(stmt(ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -2, 1.935)), source="csv")
    r = ingest(stmt(
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.93, exec_id="e1", perm=77),
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:01", -1, 1.94, exec_id="e2", perm=77),
    ), source="flex")
    rows = _rows(db)
    csv_row = next(x for x in rows if x.source_kind == "order")
    exec_ids = sorted(x.id for x in rows if x.source_kind == "exec")
    assert csv_row.superseded_by == exec_ids[0]
    assert r.counts["superseded"] == 1


def test_exec_fills_first_then_csv_is_superseded_on_arrival(db) -> None:
    from src.ledger.ingest import ingest

    ingest(stmt(
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.93, exec_id="e1", perm=77),
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:01", -1, 1.94, exec_id="e2", perm=77),
    ), source="flex")
    ingest(stmt(ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -2, 1.935)), source="csv")
    csv_row = next(x for x in _rows(db) if x.source_kind == "order")
    assert csv_row.superseded_by is not None


def test_vwap_mismatch_is_not_a_twin(db) -> None:
    from src.ledger.ingest import ingest

    ingest(stmt(ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -2, 1.80)), source="csv")
    ingest(stmt(
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.93, exec_id="e1", perm=77),
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:01", -1, 1.94, exec_id="e2", perm=77),
    ), source="flex")
    assert all(x.superseded_by is None for x in _rows(db))


def test_two_identical_csv_orders_both_survive(db) -> None:
    from src.ledger.activity_csv import number_occurrences
    from src.ledger.ingest import ingest

    st = stmt(ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.9),
              ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.9))
    number_occurrences(st)
    assert ingest(st, source="csv").counts["new"] == 2
    assert all(x.superseded_by is None for x in _rows(db))


def test_flex_order_row_twin_of_csv_row_is_superseded(db) -> None:
    from src.ledger.ingest import ingest

    ingest(stmt(ex("AMZN 18JUL25 207.5 P", "2025-07-18, 16:20:00", 1, 0.0, codes="C;Ep")), source="csv")
    ingest(stmt(ex("AMZN 18JUL25 207.5 P", "2025-07-18, 16:20:02", 1, 0.0, codes="C;Ep")), source="flex")
    rows = _rows(db)
    assert rows[0].superseded_by is None and rows[1].superseded_by == rows[0].id


def test_overnight_sgx_live_fill_twins_its_csv_row(db) -> None:
    # Review Focus 4: 03:30 UTC Nov 3 == 22:30 ET Nov 2.
    from src.ledger.ingest import ingest

    ingest(stmt(ex("A17U", "2025-11-02, 22:30:00", 500, 2.77, currency="SGD")), source="csv")
    ingest(stmt(ex("A17U", "", 500, 2.77, exec_id="x1", perm=5, currency="SGD",
                   utc=datetime(2025, 11, 3, 3, 30, tzinfo=UTC))), source="live")
    rows = _rows(db)
    assert {r.trade_date.isoformat() for r in rows} == {"2025-11-02"}
    assert next(r for r in rows if r.source_kind == "order").superseded_by is not None


def test_parse_errors_fail_the_import_and_write_nothing(db) -> None:
    from src.ledger.ingest import ingest

    bad = parse_activity_csv(FIXTURE.read_text().replace('"2025-06-17, 10:02:11",-1,', '"2025-06-17, 10:02:11",abc,'))
    r = ingest(bad, source="csv")
    assert (r.status, r.reason) == ("failed", "parse_errors")
    assert _rows(db) == []


def test_first_import_locks_the_account_and_a_mismatch_is_refused(db) -> None:
    from src.ledger.ingest import ingest
    from src.ledger.state import ledger_account

    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0)), source="csv")
    with db() as s:
        assert ledger_account(s) == "U0000001"
    r = ingest(stmt(ex("NVDA", "2025-07-15, 10:00:00", 1, 100.0, account="DU999"), account="DU999"), source="csv")
    assert (r.status, r.reason) == ("failed", "account_mismatch")


def test_live_fills_never_set_the_account_lock(db) -> None:
    # Review Focus 3 (ingest side): a paper session running before the CSV import must not claim the ledger.
    from src.ledger.ingest import ingest
    from src.storage.models import LedgerImportRunRow

    r = ingest(stmt(ex("NVDA", "", 1, 100.0, exec_id="p1", account="DU999",
                       utc=datetime(2025, 7, 14, 14, tzinfo=UTC)), account="DU999"), source="live")
    assert (r.status, r.reason) == ("skipped", "no_ledger_account")
    assert _rows(db) == []
    with db() as s:
        assert s.scalar(select(func.count()).select_from(LedgerImportRunRow)) == 0


def test_system_book_tagging(db) -> None:
    from src.ledger.ingest import ingest
    from src.storage.models import OrderRow

    with db() as s:
        s.add(OrderRow(candidate_id="c1", ib_order_id=55, snapshot={"underlying": "NVDA"}))
    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0)), source="csv")  # locks the account
    ingest(stmt(ex("NVDA 18JUL25 170 P", "", -1, 1.9, exec_id="s1", perm=9, order_id=55,
                   utc=datetime(2025, 7, 15, 14, tzinfo=UTC))), source="live")
    live = next(r for r in _rows(db) if r.exec_id == "s1")
    assert live.book == "system"


def test_commission_backfilled_on_duplicate(db) -> None:
    from src.ledger.ingest import ingest

    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0, exec_id="e9", comm=0.0)), source="flex")
    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0, exec_id="e9", comm=-1.05)), source="flex")
    assert _rows(db)[0].commission == pytest.approx(-1.05)


def test_generation_bumps_only_on_change(db) -> None:
    from src.ledger.ingest import ingest
    from src.ledger.state import LEDGER_GENERATION_KEY, read_int_setting

    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0)), source="csv")
    g1 = read_int_setting(LEDGER_GENERATION_KEY)
    ingest(stmt(ex("NVDA", "2025-07-14, 10:00:00", 1, 100.0)), source="csv")
    assert g1 == 1 and read_int_setting(LEDGER_GENERATION_KEY) == 1


def test_cli_dry_run_writes_nothing_and_real_run_imports(db, capsys) -> None:
    from scripts.ledger_import import main

    assert main([str(FIXTURE), "--dry-run"]) == 0
    assert _rows(db) == []
    assert main([str(FIXTURE)]) == 0
    assert len(_rows(db)) == 15
    assert '"status": "ok"' in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ledger_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ledger.ingest'`.

- [ ] **Step 3: Write `src/ledger/ingest.py`**

```python
"""The only writer of the broker_* ledger tables (spec §5.4; revisions R2, R8).

Every feed — Activity Statement CSV, Flex XML, live fills — lands here as a ParsedStatement.
Rows upsert by dedupe key, then an order-level twin pass supersedes duplicates that arrive
from different feeds with different granularity, so arrival order never matters.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.schemas import (
    LedgerImportResult,
    LedgerSource,
    ParsedCashEvent,
    ParsedCorporateAction,
    ParsedExecution,
    ParsedFxRate,
    ParsedStatement,
)
from src.ledger.contracts import et_date
from src.ledger.state import bump_generation, ledger_account, lock_account
from src.storage.db import session_scope
from src.storage.models import (
    BrokerCashEventRow,
    BrokerCorporateActionRow,
    BrokerExecutionRow,
    FxRateRow,
    LedgerImportRunRow,
    OrderRow,
)

log = logging.getLogger(__name__)

_PRICE_TOLERANCE = 0.005
_QTY_TOLERANCE = 1e-6
_MAX_STORED_ERRORS = 200


def _sha(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def execution_dedupe_key(e: ParsedExecution) -> str:
    if e.exec_id:
        return f"exec:{e.exec_id}"
    return "order:" + _sha(
        e.contract.ident,
        e.trade_time.astimezone(UTC).isoformat(),
        f"{e.quantity:g}",
        f"{e.price:.6f}",
        e.occurrence_idx,
    )


def _statement_account(st: ParsedStatement) -> str | None:
    if st.account:
        return st.account
    return next((e.account for e in st.executions if e.account), None)


def _account_refusal(s: Session, st: ParsedStatement, source: LedgerSource) -> str | None:
    tracked = ledger_account(s)
    incoming = _statement_account(st)
    if tracked is None:
        if source == "live":
            return "no_ledger_account"
        if incoming:
            lock_account(s, incoming)
        return None
    if incoming and incoming != tracked:
        return "account_mismatch"
    return None


def _upsert_execution(s: Session, e: ParsedExecution, *, source: str, run_id: int) -> bool:
    key = execution_dedupe_key(e)
    row = s.scalar(select(BrokerExecutionRow).where(BrokerExecutionRow.dedupe_key == key))
    if row is not None:
        if not row.commission and e.commission:
            row.commission = e.commission
        if row.perm_id is None and e.perm_id is not None:
            row.perm_id = e.perm_id
        if row.ib_order_id is None and e.ib_order_id is not None:
            row.ib_order_id = e.ib_order_id
        if row.ibkr_realized_pnl is None and e.ibkr_realized_pnl is not None:
            row.ibkr_realized_pnl = e.ibkr_realized_pnl
        return False
    c = e.contract
    s.add(
        BrokerExecutionRow(
            dedupe_key=key,
            source_kind="exec" if e.exec_id else "order",
            source=source,
            exec_id=e.exec_id,
            perm_id=e.perm_id,
            ib_order_id=e.ib_order_id,
            account=e.account,
            trade_time=e.trade_time.astimezone(UTC).replace(tzinfo=None),
            trade_date=et_date(e.trade_time),
            contract_ident=c.ident,
            underlying=c.underlying,
            sec_type=c.sec_type,
            right=c.right,
            strike=c.strike,
            expiry=c.expiry,
            multiplier=c.multiplier,
            currency=c.currency,
            quantity=e.quantity,
            price=e.price,
            proceeds=e.proceeds,
            commission=e.commission,
            codes=e.codes,
            ibkr_realized_pnl=e.ibkr_realized_pnl,
            occurrence_idx=e.occurrence_idx,
            import_run_id=run_id,
            raw=e.raw,
        )
    )
    s.flush()
    return True


def _same_order(a: BrokerExecutionRow, b: BrokerExecutionRow) -> bool:
    return (
        (a.quantity > 0) == (b.quantity > 0)
        and abs(a.quantity - b.quantity) < _QTY_TOLERANCE
        and abs(a.price - b.price) <= _PRICE_TOLERANCE
    )


def _exec_groups(execs: list[BrokerExecutionRow]) -> list[list[BrokerExecutionRow]]:
    groups: dict[tuple[str, int], list[BrokerExecutionRow]] = defaultdict(list)
    for r in execs:
        key = ("perm", r.perm_id) if r.perm_id is not None else ("row", r.id)
        groups[key].append(r)
    return list(groups.values())


def _best_group(
    order: BrokerExecutionRow, groups: list[list[BrokerExecutionRow]], used: set[int]
) -> int | None:
    best: tuple[float, int] | None = None
    for idx, group in enumerate(groups):
        if idx in used:
            continue
        qty = sum(r.quantity for r in group)
        if abs(qty - order.quantity) >= _QTY_TOLERANCE or qty == 0:
            continue
        vwap = sum(r.quantity * r.price for r in group) / qty
        gap = abs(vwap - order.price)
        if gap <= _PRICE_TOLERANCE and (best is None or gap < best[0]):
            best = (gap, idx)
    return best[1] if best else None


def supersede_twins(s: Session, affected: set[tuple[str, date]]) -> int:
    """Run the R2 twin pass over each affected (contract ident, ET date). Returns rows superseded."""
    superseded = 0
    for ident, day in sorted(affected):
        rows = list(
            s.scalars(
                select(BrokerExecutionRow)
                .where(
                    BrokerExecutionRow.contract_ident == ident,
                    BrokerExecutionRow.trade_date == day,
                    BrokerExecutionRow.superseded_by.is_(None),
                )
                .order_by(BrokerExecutionRow.id)
            )
        )
        groups = _exec_groups([r for r in rows if r.source_kind == "exec"])
        used: set[int] = set()
        survivors: list[BrokerExecutionRow] = []
        for order in (r for r in rows if r.source_kind == "order"):
            idx = _best_group(order, groups, used)
            if idx is None:
                survivors.append(order)
                continue
            used.add(idx)
            order.superseded_by = min(r.id for r in groups[idx])
            superseded += 1
        matched: set[int] = set()
        for i, later in enumerate(survivors):
            for earlier in survivors[:i]:
                if (
                    earlier.id not in matched
                    and earlier.superseded_by is None
                    and earlier.source != later.source
                    and _same_order(earlier, later)
                ):
                    later.superseded_by = earlier.id
                    matched.add(earlier.id)
                    superseded += 1
                    break
    return superseded


def _tag_books(s: Session, run_id: int) -> int:
    tagged = 0
    rows = s.scalars(
        select(BrokerExecutionRow).where(
            BrokerExecutionRow.import_run_id == run_id, BrokerExecutionRow.ib_order_id.is_not(None)
        )
    )
    for r in rows:
        for order in s.scalars(select(OrderRow).where(OrderRow.ib_order_id == r.ib_order_id)):
            snap = order.snapshot or {}
            if not snap or snap.get("underlying") == r.underlying:
                r.book = "system"
                tagged += 1
                break
    return tagged


def _upsert_cash(s: Session, c: ParsedCashEvent, *, source: str, run_id: int) -> bool:
    key = "cash:" + _sha(
        c.event_type, c.event_date, c.currency, f"{c.amount:.2f}", c.underlying or "", c.occurrence_idx
    )
    if s.scalar(select(BrokerCashEventRow.id).where(BrokerCashEventRow.dedupe_key == key)):
        return False
    s.add(
        BrokerCashEventRow(
            dedupe_key=key, event_type=c.event_type, event_date=c.event_date, currency=c.currency,
            amount=c.amount, description=c.description, underlying=c.underlying, source=source,
            import_run_id=run_id,
        )
    )
    s.flush()
    return True


def _upsert_corporate_action(
    s: Session, a: ParsedCorporateAction, *, source: str, run_id: int
) -> bool:
    key = "ca:" + _sha(a.event_date, a.description, a.occurrence_idx)
    if s.scalar(select(BrokerCorporateActionRow.id).where(BrokerCorporateActionRow.dedupe_key == key)):
        return False
    s.add(
        BrokerCorporateActionRow(
            dedupe_key=key, event_date=a.event_date, underlying=a.underlying,
            description=a.description, quantity=a.quantity, proceeds=a.proceeds, source=source,
            import_run_id=run_id, raw=a.raw,
        )
    )
    s.flush()
    return True


def _upsert_fx(s: Session, fx: ParsedFxRate, *, source: str) -> None:
    row = s.scalar(
        select(FxRateRow).where(FxRateRow.rate_date == fx.rate_date, FxRateRow.currency == fx.currency)
    )
    if row is None:
        s.add(FxRateRow(rate_date=fx.rate_date, currency=fx.currency, usd_rate=fx.usd_rate, source=source))
    else:
        row.usd_rate = fx.usd_rate
    s.flush()


def ingest(
    statement: ParsedStatement, *, source: LedgerSource, filename: str | None = None
) -> LedgerImportResult:
    """Write one parsed statement. One transaction; never partially commits trades."""
    errors = statement.errors[:_MAX_STORED_ERRORS]
    with session_scope() as s:
        refusal = "parse_errors" if statement.fatal else _account_refusal(s, statement, source)
        if refusal == "no_ledger_account":
            return LedgerImportResult(run_id=None, status="skipped", reason=refusal)
        run = LedgerImportRunRow(
            source=source, filename=filename, status="running",
            period_start=statement.period_start, period_end=statement.period_end,
        )
        s.add(run)
        s.flush()
        if refusal is not None:
            run.status, run.reason, run.finished_at = "failed", refusal, _now()
            run.errors = [e.model_dump() for e in errors]
            return LedgerImportResult(run_id=run.id, status="failed", reason=refusal, errors=errors)

        counts: dict[str, int] = defaultdict(int)
        affected: set[tuple[str, date]] = set()
        for e in statement.executions:
            created = _upsert_execution(s, e, source=source, run_id=run.id)
            counts["new" if created else "duplicate"] += 1
            affected.add((e.contract.ident, et_date(e.trade_time)))
        counts["superseded"] = supersede_twins(s, affected)
        counts["system"] = _tag_books(s, run.id)
        for c in statement.cash_events:
            counts["cash_new" if _upsert_cash(s, c, source=source, run_id=run.id) else "cash_duplicate"] += 1
        for a in statement.corporate_actions:
            counts["ca_new" if _upsert_corporate_action(s, a, source=source, run_id=run.id) else "ca_duplicate"] += 1
        for fx in statement.fx_rates:
            _upsert_fx(s, fx, source=source)
        counts["warnings"] = len(statement.errors)

        run.status, run.counts, run.finished_at = "ok", dict(counts), _now()
        run.errors = [e.model_dump() for e in errors]
        if counts["new"] or counts["superseded"] or counts["cash_new"] or counts["ca_new"]:
            bump_generation(s)
        log.info("ledger ingest (%s %s): %s", source, filename or "", dict(counts))
        return LedgerImportResult(run_id=run.id, status="ok", counts=dict(counts), errors=errors)
```

- [ ] **Step 4: Write `scripts/ledger_import.py`**

```python
"""Import an IBKR Activity Statement CSV into the trade ledger.

    python -m scripts.ledger_import path/to/statement.csv            # import
    python -m scripts.ledger_import path/to/statement.csv --dry-run  # parse + count only

Same code path as the dashboard upload (the ``ledger_import`` drain handler).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from src.ledger.activity_csv import NotAnActivityStatement, parse_activity_csv
from src.ledger.ingest import ingest
from src.storage.db import init_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="parse and print counts; write nothing")
    args = parser.parse_args(argv)

    init_db()
    try:
        statement = parse_activity_csv(args.path.read_text(encoding="utf-8-sig"))
    except NotAnActivityStatement as exc:
        print(f"Not an IBKR Activity Statement CSV: {exc}")
        return 2

    if args.dry_run:
        by_kind = Counter(e.contract.sec_type for e in statement.executions)
        print(json.dumps({
            "account": statement.account,
            "period": [str(statement.period_start), str(statement.period_end)],
            "executions": dict(by_kind),
            "cash_events": len(statement.cash_events),
            "corporate_actions": len(statement.corporate_actions),
            "errors": [e.model_dump() for e in statement.errors[:20]],
            "fatal": statement.fatal,
        }, indent=2))
        return 1 if statement.fatal else 0

    result = ingest(statement, source="csv", filename=args.path.name)
    print(json.dumps(result.model_dump(), indent=2, default=str))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_ledger_ingest.py -v`
Expected: all PASS. Then run `ruff check . && mypy src`.

- [ ] **Step 6: Commit**

```bash
git add src/ledger/ingest.py scripts/ledger_import.py tests/test_ledger_ingest.py
git commit -m "feat(ledger): idempotent ingest with order-level twin pass, account lock, CLI import"
```

---

### Task 5: Trade builder — orders, FIFO, option trades, outcomes, rolls, orphans

**Files:**
- Modify: `src/common/schemas.py` (append `LedgerClose`, `LedgerTrade`, `LedgerOrphan`)
- Create: `src/reporting/trade_ledger.py`
- Test: `tests/test_trade_ledger_trades.py`

**Interfaces:**
- Consumes: `LedgerContract`, `LedgerOutcome` (Task 1); `BrokerExecutionRow`, `TradeAnnotationRow` (Task 2).
- Produces (all in `src/reporting/trade_ledger.py`):
  - `@dataclass(frozen=True) LedgerExec(row_id, contract, trade_time, trade_date, quantity, price, proceeds, commission, codes, perm_id, book, ibkr_realized_pnl)`
  - `@dataclass LedgerOrder(order_key, contract, trade_time, trade_date, quantity, price, proceeds, commission, codes, book, ibkr_realized_pnl, row_ids)` with `.share(qty) -> tuple[float, float]` and `.is_closing`
  - `group_orders(execs) -> list[LedgerOrder]`
  - `fifo(orders) -> tuple[list[Opening], list[tuple[LedgerOrder, float]]]` (openings, orphan slices)
  - `build_option_trades(orders, *, today) -> tuple[list[LedgerTrade], list[LedgerOrphan]]`
  - `@dataclass(frozen=True) LedgerAnnotation(order_key, notes, tags, outcome_override, exclude_from_stats)`
  - `apply_annotations(trades, annotations: dict[str, LedgerAnnotation]) -> None`
  - `load_execs(session) -> list[LedgerExec]`
  - `load_annotations(session) -> dict[str, LedgerAnnotation]`
  - Schemas `LedgerClose`, `LedgerTrade`, `LedgerOrphan` (field lists below)

- [ ] **Step 1: Append schemas to `src/common/schemas.py`**

```python
class LedgerClose(BaseModel):
    """One closing order's share of a trade (a trade may close in several orders)."""

    order_key: str
    close_date: date
    close_time: datetime
    quantity: float  # contracts closed by this order, positive
    cash: float  # signed proceeds attributable to this close
    commission: float  # signed
    codes: str


class LedgerTrade(BaseModel):
    """One opening option order and everything that closed it (spec §4.2, R3, R4, R9, R10)."""

    order_key: str
    underlying: str
    currency: str
    side: Literal["Sell", "Buy"]
    right: Literal["P", "C"]
    strike: float
    expiry: date
    multiplier: float
    lots: float
    order_date: date
    open_time: datetime
    close_date: date | None
    dte: int
    days_held: int
    premium: float  # gross opening credit (+) / debit (-), contract currency
    open_commission: float
    closes: list[LedgerClose] = Field(default_factory=list)
    outcome: LedgerOutcome
    computed_outcome: LedgerOutcome
    outcome_overridden: bool = False
    mixed_close: bool = False
    capital: float
    pct_profit: float | None  # the sheet's formula, in %; short options only
    net_pnl: float | None  # fully closed only, after all commissions
    return_pct: float | None
    annualised_net_pct: float | None
    stock_gain: float | None = None  # realized stock P&L when this call got the shares called away
    book: Literal["system", "manual"]
    rolled_from: str | None = None
    rolled_to: str | None = None
    ibkr_realized_pnl: float | None = None
    exec_row_ids: list[int] = Field(default_factory=list)
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    exclude_from_stats: bool = False


class LedgerOrphan(BaseModel):
    """A closing order with no opening in the imported history (Review Focus 1)."""

    order_key: str
    underlying: str
    sec_type: Literal["OPT", "STK"]
    contract_ident: str
    currency: str
    trade_date: date
    quantity: float
    price: float
    ibkr_realized_pnl: float | None
```

- [ ] **Step 2: Write the failing test** — `tests/test_trade_ledger_trades.py`

```python
"""Orders, FIFO, option trades, outcomes, rolls, orphans, annotations (spec §4.1–4.2; R3, R4, R9, R10)."""

from __future__ import annotations

import itertools
from datetime import date

import pytest

from src.ledger.contracts import et_date, parse_et_timestamp, parse_option_symbol, stock_contract
from src.reporting.trade_ledger import (
    LedgerAnnotation,
    LedgerExec,
    apply_annotations,
    build_option_trades,
    group_orders,
)

_ids = itertools.count(1)
TODAY = date(2026, 10, 5)


def ex(symbol: str, when: str, qty: float, price: float, *, comm: float = -1.0, codes: str = "",
       perm: int | None = None, book: str = "manual", multiplier: float = 100.0,
       realized: float | None = None, currency: str = "USD") -> LedgerExec:
    contract = (parse_option_symbol(symbol, currency=currency, multiplier=multiplier) if " " in symbol
                else stock_contract(symbol, currency))
    ts = parse_et_timestamp(when)
    return LedgerExec(
        row_id=next(_ids), contract=contract, trade_time=ts, trade_date=et_date(ts), quantity=qty,
        price=price, proceeds=-qty * price * contract.multiplier, commission=comm, codes=codes,
        perm_id=perm, book=book, ibkr_realized_pnl=realized,
    )


def trades_of(*execs: LedgerExec, today: date = TODAY):
    trades, orphans = build_option_trades(group_orders(list(execs)), today=today)
    return trades, orphans


def test_sheet_formula_nvda_bought_back_for_a_penny() -> None:
    (t,), _ = trades_of(
        ex("NVDA 27JUN25 138 P", "2025-06-17, 10:02:11", -1, 1.31, codes="O"),
        ex("NVDA 27JUN25 138 P", "2025-06-27, 11:09:57", 1, 0.01, codes="C"),
    )
    assert (t.side, t.right, t.lots, t.premium, t.dte) == ("Sell", "P", 1.0, 131.0, 10)
    assert round(t.pct_profit, 2) == 34.65
    assert t.outcome == "Bought back"  # R9: IBKR recorded a $0.01 buy-back, not an expiry
    assert t.net_pnl == pytest.approx(131 - 1 - 1 - 1)
    assert t.capital == 13800.0


def test_sheet_formula_amzn_expired() -> None:
    (t,), _ = trades_of(
        ex("AMZN 18JUL25 207.5 P", "2025-06-25, 13:17:15", -1, 3.25, codes="O"),
        ex("AMZN 18JUL25 207.5 P", "2025-07-18, 16:20:00", 1, 0.0, comm=0.0, codes="C;Ep"),
    )
    assert t.outcome == "Expired"
    assert round(t.pct_profit, 2) == 24.86
    assert t.close_date == date(2025, 7, 18)


def test_partial_fills_merge_into_one_order() -> None:
    (t,), _ = trades_of(
        ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:00", -1, 1.93, perm=9),
        ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:01", -1, 1.94, perm=9),
    )
    assert t.lots == 2.0 and t.premium == pytest.approx(387.0)
    assert len(t.exec_row_ids) == 2


def test_partial_close_stays_open_then_pending_after_expiry() -> None:
    legs = (ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:00", -2, 1.9),
            ex("NVDA 25JUL25 170 P", "2025-07-21, 10:00:00", 1, 0.5, codes="C"))
    (t,), _ = trades_of(*legs, today=date(2025, 7, 22))
    assert t.outcome == "Open" and t.net_pnl is None and len(t.closes) == 1
    (t2,), _ = trades_of(*legs, today=date(2025, 7, 28))
    assert t2.outcome == "Pending"  # R10


def test_mixed_close_takes_the_largest_and_flags_it() -> None:
    (t,), _ = trades_of(
        ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:00", -3, 1.9),
        ex("NVDA 25JUL25 170 P", "2025-07-21, 10:00:00", 1, 0.5, codes="C"),
        ex("NVDA 25JUL25 170 P", "2025-07-25, 16:20:00", 2, 0.0, comm=0.0, codes="C;Ep"),
    )
    assert t.outcome == "Expired" and t.mixed_close is True


@pytest.mark.parametrize(
    ("symbol", "open_qty", "close_codes", "expected"),
    [
        ("AMZN 10OCT25 215 P", -1, "A;C", "Assigned"),
        ("AMZN 31OCT25 235 C", -1, "A;C", "Called away"),
        ("OPEN 19SEP25 3 C", 4, "C;Ex", "Exercised"),
    ],
)
def test_assignment_and_exercise_outcomes(symbol, open_qty, close_codes, expected) -> None:
    (t,), _ = trades_of(
        ex(symbol, "2025-09-01, 10:00:00", open_qty, 1.0, codes="O"),
        ex(symbol, "2025-10-31, 16:20:00", -open_qty, 0.0, comm=0.0, codes=close_codes),
    )
    assert t.outcome == expected


def test_long_option_has_no_sheet_percentage() -> None:
    (t,), _ = trades_of(
        ex("OPEN 19SEP25 3 C", "2025-07-21, 10:00:00", 4, 1.2, codes="O"),
        ex("OPEN 19SEP25 3 C", "2025-09-19, 16:20:00", -4, 0.0, comm=0.0, codes="C;Ex"),
    )
    assert t.side == "Buy" and t.premium == pytest.approx(-480.0)
    assert t.pct_profit is None and t.capital == pytest.approx(480.0)


def test_same_session_buyback_and_new_short_is_a_roll() -> None:
    trades, _ = trades_of(
        ex("NVDA 18JUL25 170 P", "2025-07-11, 10:00:00", -1, 2.0, codes="O"),
        ex("NVDA 18JUL25 170 P", "2025-07-16, 10:00:00", 1, 1.0, codes="C"),
        ex("NVDA 25JUL25 165 P", "2025-07-16, 10:00:00", -1, 1.6, codes="O"),
    )
    first, second = sorted(trades, key=lambda t: t.open_time)
    assert first.outcome == "Rolled" and first.rolled_to == second.order_key
    assert second.rolled_from == first.order_key


def test_order_key_is_the_same_for_a_csv_order_and_its_exec_fills() -> None:
    csv_order = group_orders([ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -2, 1.935)])
    fills = group_orders([
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", -1, 1.93, perm=7),
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:01", -1, 1.94, perm=7),
    ])
    assert csv_order[0].order_key == fills[0].order_key
    assert len(csv_order[0].order_key) == 16


def test_an_order_that_closes_and_opens_splits() -> None:
    trades, _ = trades_of(
        ex("NVDA 18JUL25 170 P", "2025-07-11, 10:00:00", -1, 2.0),
        ex("NVDA 18JUL25 170 P", "2025-07-14, 10:00:00", 3, 1.0),
    )
    short, long = sorted(trades, key=lambda t: t.open_time)
    assert short.outcome == "Bought back" and short.closes[0].quantity == 1
    assert long.side == "Buy" and long.lots == 2.0
    assert long.premium == pytest.approx(-200.0)


def test_orphan_close_is_reported_not_turned_into_a_long() -> None:
    # Review Focus 1: the statement starts after the put was sold.
    trades, orphans = trades_of(
        ex("NVDA 11APR25 100 P", "2025-04-04, 10:00:00", 1, 0.2, codes="C", realized=150.0),
    )
    assert trades == []
    assert len(orphans) == 1 and orphans[0].ibkr_realized_pnl == 150.0


def test_non_100_multiplier_drives_premium_and_capital() -> None:
    # Review Focus 5.
    (t,), _ = trades_of(ex("OPEN1 19DEC25 5 C", "2025-11-20, 10:00:00", -2, 0.5, multiplier=50.0))
    assert t.premium == pytest.approx(50.0)
    assert t.capital == pytest.approx(5 * 50 * 2)


def test_annotation_override_and_notes() -> None:
    (t,), _ = trades_of(
        ex("NVDA 27JUN25 138 P", "2025-06-17, 10:02:11", -1, 1.31, codes="O"),
        ex("NVDA 27JUN25 138 P", "2025-06-27, 11:09:57", 1, 0.01, codes="C"),
    )
    apply_annotations([t], {t.order_key: LedgerAnnotation(
        order_key=t.order_key, notes="treat as expired", tags=["earnings"],
        outcome_override="Expired", exclude_from_stats=False)})
    assert (t.outcome, t.computed_outcome, t.outcome_overridden) == ("Expired", "Bought back", True)
    assert t.notes == "treat as expired" and t.tags == ["earnings"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_trade_ledger_trades.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.reporting.trade_ledger'`.

- [ ] **Step 4: Write `src/reporting/trade_ledger.py` (part 1)**

```python
"""Read-only builders for the whole-account trade ledger (spec §4; revisions R3–R5, R9, R10).

executions -> orders -> option trades + stock lots -> ticker roll-ups -> USD portfolio summary.
Every figure on /ledger, in the CSV export and in the Google Sheet mirror comes from here, so they
agree by construction. Pure over loaded rows; never writes (tests/test_web_fence.py).
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.schemas import (
    LedgerClose,
    LedgerContract,
    LedgerOrphan,
    LedgerOutcome,
    LedgerTrade,
)
from src.storage.models import BrokerExecutionRow, TradeAnnotationRow

_EPS = 1e-9
_ROLL_WINDOW = timedelta(minutes=5)
_VALID_OUTCOMES: frozenset[str] = frozenset(
    ["Open", "Pending", "Expired", "Assigned", "Called away", "Exercised", "Bought back", "Sold", "Rolled"]
)


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _tokens(codes: str) -> set[str]:
    return {c for c in codes.split(";") if c}


@dataclass(frozen=True)
class LedgerExec:
    """One non-superseded execution row, detached from the ORM."""

    row_id: int
    contract: LedgerContract
    trade_time: datetime  # aware UTC
    trade_date: date  # US/Eastern
    quantity: float
    price: float
    proceeds: float
    commission: float
    codes: str
    perm_id: int | None
    book: str
    ibkr_realized_pnl: float | None


@dataclass
class LedgerOrder:
    order_key: str
    contract: LedgerContract
    trade_time: datetime
    trade_date: date
    quantity: float
    price: float
    proceeds: float
    commission: float
    codes: str
    book: str
    ibkr_realized_pnl: float | None
    row_ids: list[int] = field(default_factory=list)

    def share(self, qty: float) -> tuple[float, float]:
        """(proceeds, commission) attributable to |qty| of this order."""
        frac = abs(qty) / abs(self.quantity) if self.quantity else 0.0
        return self.proceeds * frac, self.commission * frac

    @property
    def is_closing(self) -> bool:
        return "C" in _tokens(self.codes)


@dataclass
class Opening:
    order: LedgerOrder
    qty: float  # signed quantity this order opened
    remaining: float
    closes: list[tuple[LedgerOrder, float]] = field(default_factory=list)


@dataclass(frozen=True)
class LedgerAnnotation:
    order_key: str
    notes: str
    tags: list[str]
    outcome_override: str | None
    exclude_from_stats: bool


def group_orders(execs: list[LedgerExec]) -> list[LedgerOrder]:
    """Merge fills sharing a perm_id (per contract) and assign source-independent keys (R3)."""
    buckets: dict[tuple[object, ...], list[LedgerExec]] = defaultdict(list)
    for e in execs:
        key: tuple[object, ...] = (
            ("perm", e.perm_id, e.contract.ident) if e.perm_id is not None else ("row", e.row_id)
        )
        buckets[key].append(e)
    orders: list[LedgerOrder] = []
    for group in buckets.values():
        group.sort(key=lambda e: e.trade_time)
        qty = sum(e.quantity for e in group)
        if abs(qty) < _EPS:
            continue
        realized = [e.ibkr_realized_pnl for e in group if e.ibkr_realized_pnl is not None]
        first = group[0]
        orders.append(
            LedgerOrder(
                order_key="",
                contract=first.contract,
                trade_time=first.trade_time,
                trade_date=first.trade_date,
                quantity=qty,
                price=sum(e.quantity * e.price for e in group) / qty,
                proceeds=sum(e.proceeds for e in group),
                commission=sum(e.commission for e in group),
                codes=";".join(dict.fromkeys(c for e in group for c in e.codes.split(";") if c)),
                book="system" if any(e.book == "system" for e in group) else "manual",
                ibkr_realized_pnl=sum(realized) if realized else None,
                row_ids=[e.row_id for e in group],
            )
        )
    orders.sort(key=lambda o: (o.trade_time, o.contract.ident))
    ordinal: Counter[tuple[str, ...]] = Counter()
    for o in orders:
        sig = (
            o.contract.ident,
            o.trade_date.isoformat(),
            str(_sign(o.quantity)),
            f"{abs(o.quantity):g}",
            f"{o.price:.4f}",
        )
        o.order_key = hashlib.sha1("|".join([*sig, str(ordinal[sig])]).encode()).hexdigest()[:16]
        ordinal[sig] += 1
    return orders


def fifo(orders: list[LedgerOrder]) -> tuple[list[Opening], list[tuple[LedgerOrder, float]]]:
    """FIFO-match one contract's orders. Returns (openings with their closes, orphan slices).

    A closing-coded order (code token ``C``) with nothing left to close is an orphan — its
    opening predates the imported history — and never becomes a new opposite position.
    """
    openings: list[Opening] = []
    orphans: list[tuple[LedgerOrder, float]] = []
    queue: deque[Opening] = deque()
    for o in sorted(orders, key=lambda x: x.trade_time):
        q = o.quantity
        while abs(q) > _EPS and queue and _sign(queue[0].remaining) != _sign(q):
            head = queue[0]
            m = min(abs(q), abs(head.remaining))
            head.closes.append((o, m))
            head.remaining += m * _sign(q)
            q -= m * _sign(q)
            if abs(head.remaining) < _EPS:
                queue.popleft()
        if abs(q) <= _EPS:
            continue
        if o.is_closing:
            orphans.append((o, abs(q)))
            continue
        op = Opening(order=o, qty=q, remaining=q)
        openings.append(op)
        queue.append(op)
    return openings, orphans


def _close_kind(codes: str, *, right: str, short: bool) -> LedgerOutcome:
    t = _tokens(codes)
    if "Ep" in t:
        return "Expired"
    if "A" in t:
        if not short:
            return "Exercised"
        return "Assigned" if right == "P" else "Called away"
    if "Ex" in t:
        return "Exercised"
    return "Bought back" if short else "Sold"


def _trade_from_opening(op: Opening, *, today: date) -> LedgerTrade:
    o, c = op.order, op.order.contract
    assert c.right is not None and c.strike is not None and c.expiry is not None
    short = op.qty < 0
    lots = abs(op.qty)
    premium, open_comm = o.share(op.qty)
    closes: list[LedgerClose] = []
    realized: list[float] = []
    row_ids = list(o.row_ids)
    for close_order, m in op.closes:
        cash, comm = close_order.share(m)
        closes.append(
            LedgerClose(
                order_key=close_order.order_key, close_date=close_order.trade_date,
                close_time=close_order.trade_time, quantity=m, cash=cash, commission=comm,
                codes=close_order.codes,
            )
        )
        row_ids.extend(close_order.row_ids)
        if close_order.ibkr_realized_pnl is not None:
            realized.append(close_order.ibkr_realized_pnl * m / abs(close_order.quantity))
    fully_closed = abs(lots - sum(x.quantity for x in closes)) < _EPS
    kinds = [_close_kind(x.codes, right=c.right, short=short) for x in closes]
    outcome: LedgerOutcome
    if fully_closed:
        biggest = max(range(len(closes)), key=lambda i: (closes[i].quantity, -i))
        outcome = kinds[biggest]
    else:
        outcome = "Pending" if c.expiry < today else "Open"
    close_date = max(x.close_date for x in closes) if fully_closed else None
    dte = max(1, (c.expiry - o.trade_date).days)
    days_held = max(1, ((close_date or today) - o.trade_date).days)
    capital = c.strike * c.multiplier * lots if short else abs(premium)
    net = premium + open_comm + sum(x.cash + x.commission for x in closes) if fully_closed else None
    return LedgerTrade(
        order_key=o.order_key, underlying=c.underlying, currency=c.currency,
        side="Sell" if short else "Buy", right=c.right, strike=c.strike, expiry=c.expiry,
        multiplier=c.multiplier, lots=lots, order_date=o.trade_date, open_time=o.trade_time,
        close_date=close_date, dte=dte, days_held=days_held, premium=premium,
        open_commission=open_comm, closes=closes, outcome=outcome, computed_outcome=outcome,
        mixed_close=len(set(kinds)) > 1, capital=capital,
        pct_profit=premium / capital * 365 / dte * 100 if short and capital else None,
        net_pnl=net,
        return_pct=net / capital * 100 if net is not None and capital else None,
        annualised_net_pct=net / capital * 365 / days_held * 100 if net is not None and capital else None,
        book="system" if o.book == "system" else "manual",
        ibkr_realized_pnl=sum(realized) if realized else None, exec_row_ids=row_ids,
    )


def _link_rolls(trades: list[LedgerTrade]) -> None:
    """A buy-to-close followed within the session by a same-underlying, same-right new short."""
    opens: dict[tuple[str, str, date], list[LedgerTrade]] = defaultdict(list)
    for t in trades:
        if t.side == "Sell":
            opens[(t.underlying, t.right, t.order_date)].append(t)
    taken: set[str] = set()
    for t in sorted(trades, key=lambda x: x.open_time):
        if t.computed_outcome != "Bought back" or not t.closes:
            continue
        last = max(t.closes, key=lambda x: x.close_time)
        candidates = [
            n for n in opens.get((t.underlying, t.right, last.close_date), [])
            if n.order_key != t.order_key and n.order_key not in taken
            and n.open_time >= last.close_time - _ROLL_WINDOW
        ]
        if not candidates:
            continue
        nxt = min(candidates, key=lambda n: abs((n.open_time - last.close_time).total_seconds()))
        taken.add(nxt.order_key)
        t.outcome = t.computed_outcome = "Rolled"
        t.rolled_to = nxt.order_key
        nxt.rolled_from = t.order_key


def _orphan(order: LedgerOrder, qty: float) -> LedgerOrphan:
    c = order.contract
    realized = (
        order.ibkr_realized_pnl * qty / abs(order.quantity) if order.ibkr_realized_pnl is not None else None
    )
    return LedgerOrphan(
        order_key=order.order_key, underlying=c.underlying, sec_type=c.sec_type,
        contract_ident=c.ident, currency=c.currency, trade_date=order.trade_date,
        quantity=qty, price=order.price, ibkr_realized_pnl=realized,
    )


def build_option_trades(
    orders: list[LedgerOrder], *, today: date
) -> tuple[list[LedgerTrade], list[LedgerOrphan]]:
    by_contract: dict[str, list[LedgerOrder]] = defaultdict(list)
    for o in orders:
        if o.contract.sec_type == "OPT":
            by_contract[o.contract.ident].append(o)
    trades: list[LedgerTrade] = []
    orphans: list[LedgerOrphan] = []
    for group in by_contract.values():
        openings, orphan_slices = fifo(group)
        trades.extend(_trade_from_opening(op, today=today) for op in openings)
        orphans.extend(_orphan(o, q) for o, q in orphan_slices)
    _link_rolls(trades)
    trades.sort(key=lambda t: (t.open_time, t.order_key))
    return trades, orphans


def apply_annotations(trades: list[LedgerTrade], annotations: dict[str, LedgerAnnotation]) -> None:
    for t in trades:
        a = annotations.get(t.order_key)
        if a is None:
            continue
        t.notes, t.tags, t.exclude_from_stats = a.notes, list(a.tags), a.exclude_from_stats
        if a.outcome_override and a.outcome_override in _VALID_OUTCOMES:
            t.outcome = a.outcome_override  # type: ignore[assignment]
            t.outcome_overridden = True


def load_execs(session: Session) -> list[LedgerExec]:
    rows = session.scalars(
        select(BrokerExecutionRow).where(BrokerExecutionRow.superseded_by.is_(None))
    )
    return [
        LedgerExec(
            row_id=r.id,
            contract=LedgerContract(
                underlying=r.underlying, sec_type="OPT" if r.sec_type == "OPT" else "STK",
                currency=r.currency, right="P" if r.right == "P" else "C" if r.right == "C" else None,
                strike=r.strike, expiry=r.expiry, multiplier=r.multiplier,
            ),
            trade_time=r.trade_time.replace(tzinfo=UTC), trade_date=r.trade_date,
            quantity=r.quantity, price=r.price, proceeds=r.proceeds, commission=r.commission,
            codes=r.codes, perm_id=r.perm_id, book=r.book, ibkr_realized_pnl=r.ibkr_realized_pnl,
        )
        for r in rows
    ]


def load_annotations(session: Session) -> dict[str, LedgerAnnotation]:
    return {
        r.order_key: LedgerAnnotation(
            order_key=r.order_key, notes=r.notes or "", tags=list(r.tags or []),
            outcome_override=r.outcome_override, exclude_from_stats=bool(r.exclude_from_stats),
        )
        for r in session.scalars(select(TradeAnnotationRow))
    }
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_trade_ledger_trades.py tests/test_web_fence.py -v`
Expected: all PASS. `test_reporting_never_writes_anything` stays green.

- [ ] **Step 6: Commit**

```bash
git add src/reporting/trade_ledger.py tests/test_trade_ledger_trades.py
git add -p src/common/schemas.py
git commit -m "feat(ledger): order grouping, FIFO option trades, outcomes, rolls, orphans"
```

---

### Task 6: Stock lots, ticker roll-ups, FX, portfolio summary, `build_book`

**Files:**
- Modify: `src/common/schemas.py` (append), `src/reporting/trade_ledger.py` (append)
- Test: `tests/test_trade_ledger_book.py`

**Interfaces:**
- Consumes: Task 5 builders; `PortfolioSnapshot` / `PositionSnapshot` (existing; positions carry `sec_type`, `symbol`, `underlying`, `unrealized_pnl`); `BrokerCashEventRow`, `FxRateRow`, `BrokerCorporateActionRow`.
- Produces:
  - Schemas: `LedgerStockLot`, `LedgerStockDisposal`, `LedgerCashItem`, `LedgerTicker`, `LedgerBasisPoint`, `LedgerTickerDetail`, `LedgerMonth`, `LedgerCurvePoint`, `LedgerBucket`, `LedgerSummary`, `LedgerBook`
  - `build_stock_lots(orders) -> tuple[list[LedgerStockLot], list[LedgerStockDisposal], list[LedgerOrphan]]`
  - `attach_stock_gains(trades, disposals) -> None`
  - `class FxTable(rates: dict[str, list[tuple[date, float]]], max_gap_days: int)` with `.to_usd(amount, currency, on) -> float | None`
  - `build_tickers(trades, lots, disposals, cash, *, snapshot) -> list[LedgerTicker]`
  - `basis_walk(trades, lots) -> list[LedgerBasisPoint]`
  - `build_summary(...) -> LedgerSummary`
  - `build_book(session, *, today, snapshot, marks_as_of=None) -> LedgerBook`
  - `ticker_detail(book, symbol) -> LedgerTickerDetail | None`

- [ ] **Step 1: Append schemas to `src/common/schemas.py`**

```python
class LedgerStockLot(BaseModel):
    lot_key: str
    underlying: str
    currency: str
    acquired_date: date
    source: Literal["bought", "assigned", "exercised"]
    quantity: float  # signed quantity originally opened
    remaining: float
    cost_per_share: float  # commission-inclusive


class LedgerStockDisposal(BaseModel):
    lot_key: str
    underlying: str
    currency: str
    disposal_date: date
    quantity: float
    price: float
    realized: float
    codes: str


class LedgerCashItem(BaseModel):
    event_date: date
    event_type: str
    currency: str
    amount: float
    description: str
    underlying: str | None = None


class LedgerTicker(BaseModel):
    symbol: str
    currency: str
    option_premium_gross: float
    option_net_pnl: float
    stock_realized: float
    dividends_net: float
    total_realized: float
    unrealized: float | None
    n_trades: int
    n_open: int
    n_closed: int
    win_rate: float | None
    avg_premium: float | None
    best_trade: float | None
    worst_trade: float | None
    annualised_return_pct: float | None
    shares_held: float
    broker_avg_cost: float | None
    wheel_adjusted_basis: float | None
    first_trade: date | None
    last_trade: date | None


class LedgerBasisPoint(BaseModel):
    point_date: date
    label: str
    basis_per_share: float


class LedgerTickerDetail(BaseModel):
    ticker: LedgerTicker
    trades: list[LedgerTrade]
    lots: list[LedgerStockLot]
    disposals: list[LedgerStockDisposal]
    dividends: list[LedgerCashItem]
    basis_walk: list[LedgerBasisPoint]


class LedgerMonth(BaseModel):
    month: str  # "YYYY-MM"
    premium_usd: float
    realized_usd: float


class LedgerCurvePoint(BaseModel):
    point_date: date
    cumulative_usd: float


class LedgerBucket(BaseModel):
    label: str
    n_closed: int
    realized_usd: float
    win_rate: float | None


class LedgerSummary(BaseModel):
    total_realized_usd: float
    interest_and_fees_usd: float
    contributed_usd: float | None
    capital_utilised_usd: float
    available_usd: float | None
    unrealized_usd: float | None
    win_rate: float | None
    n_trades: int
    n_open: int
    premium_this_month_usd: float
    months: list[LedgerMonth]
    curve: list[LedgerCurvePoint]
    by_strategy: list[LedgerBucket]
    by_book: list[LedgerBucket]
    upcoming: list[LedgerTrade]
    fx_incomplete: bool
    orphan_closes: int
    unreviewed_corporate_actions: int
    marks_as_of: datetime | None


class LedgerBook(BaseModel):
    trades: list[LedgerTrade]
    orphans: list[LedgerOrphan]
    tickers: list[LedgerTicker]
    summary: LedgerSummary
    lots: list[LedgerStockLot]
    disposals: list[LedgerStockDisposal]
    cash: list[LedgerCashItem]
```

- [ ] **Step 2: Write the failing test** — `tests/test_trade_ledger_book.py`

```python
"""Stock lots, wheel cost basis, tickers, FX, summary, build_book (spec §4.3–4.5; R4, R5)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from src.common.schemas import LedgerCashItem, PortfolioSnapshot, PositionSnapshot
from src.reporting.trade_ledger import (
    FxTable,
    attach_stock_gains,
    build_option_trades,
    build_stock_lots,
    build_summary,
    build_tickers,
    group_orders,
)
from tests.test_trade_ledger_trades import ex

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"

# The AMZN wheel from the operator's real statement: CSP 215P -> assigned -> CC 235C -> called away.
WHEEL = [
    ex("AMZN 10OCT25 215 P", "2025-10-03, 14:45:08", -1, 1.77, comm=-1.1430721, codes="O"),
    ex("AMZN 10OCT25 215 P", "2025-10-10, 16:20:00", 1, 0.0, comm=0.0, codes="A;C"),
    ex("AMZN", "2025-10-10, 16:20:00", 100, 215.0, comm=0.0, codes="A;O"),
    ex("AMZN 31OCT25 235 C", "2025-10-20, 10:30:00", -1, 4.01, comm=-1.0, codes="O"),
    ex("AMZN 31OCT25 235 C", "2025-10-31, 16:20:00", 1, 0.0, comm=0.0, codes="A;C"),
    ex("AMZN", "2025-10-31, 16:20:00", -100, 235.0, comm=-0.018094, codes="A;C"),
]


def _book(execs, today, cash=(), snapshot=None, fx=None):
    orders = group_orders(list(execs))
    trades, orphans = build_option_trades(orders, today=today)
    lots, disposals, stock_orphans = build_stock_lots(orders)
    attach_stock_gains(trades, disposals)
    tickers = build_tickers(trades, lots, disposals, list(cash), snapshot=snapshot)
    summary = build_summary(
        trades, tickers, lots, disposals, list(cash), fx or FxTable({}, 7), today=today,
        snapshot=snapshot, orphans=orphans + stock_orphans, unreviewed_corporate_actions=0,
        marks_as_of=None,
    )
    return trades, lots, disposals, tickers, summary


def test_wheel_lot_disposal_and_stock_gain() -> None:
    trades, lots, disposals, tickers, _ = _book(WHEEL, date(2025, 11, 5))
    (lot,) = lots
    assert (lot.source, lot.cost_per_share, lot.remaining) == ("assigned", 215.0, 0.0)
    (d,) = disposals
    assert d.realized == pytest.approx(1999.98, abs=0.01)
    call = next(t for t in trades if t.right == "C")
    assert call.outcome == "Called away" and call.stock_gain == pytest.approx(1999.98, abs=0.01)
    (amzn,) = tickers
    assert amzn.total_realized == pytest.approx(175.857 + 400.0 + 1999.982, abs=0.01)
    assert amzn.shares_held == 0 and amzn.wheel_adjusted_basis is None


def test_wheel_adjusted_basis_while_the_call_is_open() -> None:
    _, _, _, tickers, _ = _book(WHEEL[:4], date(2025, 10, 21))
    (amzn,) = tickers
    assert amzn.shares_held == 100
    assert amzn.broker_avg_cost == pytest.approx(215.0)
    assert amzn.wheel_adjusted_basis == pytest.approx((21500 - 175.857 - 400.0) / 100, abs=1e-3)


def test_stock_sold_before_history_is_an_orphan_with_ibkr_realized() -> None:
    _, lots, disposals, _, summary = _book(
        [ex("MSTY", "2026-03-30, 11:19:46", -20, 21.55, codes="C;IA", realized=-973.37)], date(2026, 4, 1)
    )
    assert lots == [] and disposals == []
    assert summary.orphan_closes == 1
    assert summary.total_realized_usd == pytest.approx(-973.37)


def test_fx_conversion_and_missing_rate_flag() -> None:
    sgd_lot = [ex("A17U", "2025-07-17, 01:31:33", 500, 2.77, comm=-2.725, currency="SGD")]
    _, _, _, _, missing = _book(sgd_lot, date(2025, 7, 20))
    assert missing.fx_incomplete is True
    fx = FxTable({"SGD": [(date(2025, 7, 16), 0.78)]}, 7)
    _, _, _, _, ok = _book(sgd_lot, date(2025, 7, 20), fx=fx)
    assert ok.fx_incomplete is False
    assert ok.capital_utilised_usd == pytest.approx((1385 + 2.725) * 0.78, abs=0.01)


def test_fx_table_respects_max_gap() -> None:
    fx = FxTable({"SGD": [(date(2025, 1, 1), 0.75)]}, 7)
    assert fx.to_usd(100, "SGD", date(2025, 1, 5)) == pytest.approx(75.0)
    assert fx.to_usd(100, "SGD", date(2025, 2, 1)) is None
    assert fx.to_usd(100, "USD", date(2025, 2, 1)) == 100


def test_contributed_unknown_without_deposits_and_available_formula() -> None:
    _, _, _, _, s = _book(WHEEL, date(2025, 11, 5))
    assert s.contributed_usd is None and s.available_usd is None
    cash = [LedgerCashItem(event_date=date(2025, 5, 26), event_type="deposit", currency="USD",
                           amount=45000.0, description="EFT")]
    _, _, _, _, s2 = _book(WHEEL, date(2025, 11, 5), cash=cash)
    assert s2.contributed_usd == 45000.0
    assert s2.available_usd == pytest.approx(45000.0 + s2.total_realized_usd - s2.capital_utilised_usd)


def test_capital_utilised_counts_open_short_put_collateral() -> None:
    _, _, _, _, s = _book([ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:00", -2, 1.9)], date(2025, 7, 20))
    assert s.capital_utilised_usd == pytest.approx(170 * 100 * 2)


def test_excluded_trade_counts_in_money_not_in_win_rate() -> None:
    trades, lots, disposals, _, _ = _book(WHEEL, date(2025, 11, 5))
    for t in trades:
        t.exclude_from_stats = True
    tickers = build_tickers(trades, lots, disposals, [], snapshot=None)
    assert tickers[0].win_rate is None
    assert tickers[0].option_net_pnl == pytest.approx(575.857, abs=0.01)


def test_unrealized_is_none_without_a_snapshot_and_summed_with_one() -> None:
    open_put = [ex("NVDA 25JUL25 170 P", "2025-07-18, 10:00:00", -1, 1.9)]
    _, _, _, tickers, _ = _book(open_put, date(2025, 7, 20))
    assert tickers[0].unrealized is None
    snap = PortfolioSnapshot(
        captured_at=datetime(2025, 7, 20, 15, tzinfo=UTC), source="monitor",
        positions=[PositionSnapshot.model_validate({
            "symbol": "NVDA 250725P00170000", "sec_type": "OPT", "underlying": "NVDA",
            "quantity": -1, "avg_cost": 190.0, "unrealized_pnl": 55.0})],
    )
    _, _, _, tickers2, _ = _book(open_put, date(2025, 7, 20), snapshot=snap)
    assert tickers2[0].unrealized == 55.0


def test_build_book_end_to_end_from_the_fixture(db) -> None:
    from src.ledger.activity_csv import parse_activity_csv
    from src.ledger.ingest import ingest
    from src.reporting.trade_ledger import build_book, ticker_detail

    ingest(parse_activity_csv(FIXTURE.read_text()), source="csv")
    with db() as s:
        book = build_book(s, today=date(2026, 10, 5), snapshot=None)
    nvda = next(t for t in book.trades if t.underlying == "NVDA")
    assert round(nvda.pct_profit, 2) == 34.65
    assert {t.underlying for t in book.tickers} >= {"AMZN", "NVDA", "OPEN", "QDTE", "A17U"}
    amzn = ticker_detail(book, "AMZN")
    assert amzn is not None and len(amzn.trades) == 3 and len(amzn.disposals) == 1
    # A17U (SGD, Jul 2025) has no FX rate within 7 days; the SGD withdrawal (2026-01-02) converts
    # at the fixture's USD.SGD forex trade (2026-01-06, 4 days away).
    assert book.summary.fx_incomplete is True
    assert book.summary.contributed_usd == pytest.approx(45000 - 6371.24 / 1.2795, abs=0.01)
    assert book.summary.unreviewed_corporate_actions == 1
```

`PositionSnapshot`'s required fields may differ from the dict above. If so, open `src/common/schemas.py`, read `class PositionSnapshot`, and fill the required fields with neutral values. The test relies only on `sec_type`, `underlying`, `symbol` and `unrealized_pnl`.

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_trade_ledger_book.py -v`
Expected: FAIL with ImportError on `FxTable`, `build_stock_lots`, and the other new names.

- [ ] **Step 4: Append to `src/reporting/trade_ledger.py`**

Add to the imports: `import bisect`, `from sqlalchemy import func`, `from src.common.config import get_config`, the new schema names (`LedgerBasisPoint, LedgerBook, LedgerBucket, LedgerCashItem, LedgerCurvePoint, LedgerMonth, LedgerStockDisposal, LedgerStockLot, LedgerSummary, LedgerTicker, LedgerTickerDetail, PortfolioSnapshot`), and `BrokerCashEventRow, BrokerCorporateActionRow, FxRateRow` from `src.storage.models`. Then append:

```python
# --------------------------------------------------------------------------- #
# Stock lots (spec §4.3)
# --------------------------------------------------------------------------- #
def build_stock_lots(
    orders: list[LedgerOrder],
) -> tuple[list[LedgerStockLot], list[LedgerStockDisposal], list[LedgerOrphan]]:
    """FIFO share lots. Cost is commission-inclusive: ``-(proceeds + commission) / qty``."""
    lots: list[LedgerStockLot] = []
    disposals: list[LedgerStockDisposal] = []
    orphans: list[LedgerOrphan] = []
    by_contract: dict[str, list[LedgerOrder]] = defaultdict(list)
    for o in orders:
        if o.contract.sec_type == "STK":
            by_contract[o.contract.ident].append(o)
    for group in by_contract.values():
        queue: deque[LedgerStockLot] = deque()
        for o in sorted(group, key=lambda x: x.trade_time):
            basis = -(o.proceeds + o.commission) / o.quantity
            q = o.quantity
            while abs(q) > _EPS and queue and _sign(queue[0].remaining) != _sign(q):
                head = queue[0]
                m = min(abs(q), abs(head.remaining))
                disposals.append(
                    LedgerStockDisposal(
                        lot_key=head.lot_key, underlying=head.underlying, currency=head.currency,
                        disposal_date=o.trade_date, quantity=m, price=o.price,
                        realized=(basis - head.cost_per_share) * m * _sign(head.remaining),
                        codes=o.codes,
                    )
                )
                head.remaining += m * _sign(q)
                q -= m * _sign(q)
                if abs(head.remaining) < _EPS:
                    head.remaining = 0.0
                    queue.popleft()
            if abs(q) <= _EPS:
                continue
            if o.is_closing:
                orphans.append(_orphan(o, abs(q)))
                continue
            t = _tokens(o.codes)
            lot = LedgerStockLot(
                lot_key=o.order_key, underlying=o.contract.underlying, currency=o.contract.currency,
                acquired_date=o.trade_date,
                source="assigned" if "A" in t else "exercised" if "Ex" in t else "bought",
                quantity=q, remaining=q, cost_per_share=basis,
            )
            lots.append(lot)
            queue.append(lot)
    return lots, disposals, orphans


def attach_stock_gains(trades: list[LedgerTrade], disposals: list[LedgerStockDisposal]) -> None:
    """The sheet's "Capital" column: stock P&L realized when a short call got the shares called away."""
    for t in trades:
        if t.computed_outcome != "Called away" or t.close_date is None:
            continue
        gains = [
            d.realized for d in disposals
            if d.underlying == t.underlying and d.disposal_date == t.close_date
            and "A" in _tokens(d.codes) and abs(d.price - t.strike) < 1e-6
        ]
        t.stock_gain = sum(gains) if gains else None


# --------------------------------------------------------------------------- #
# FX (spec §3 fx_rates; R5)
# --------------------------------------------------------------------------- #
class FxTable:
    """USD conversion at the nearest rate within ``max_gap_days`` of the date; else None."""

    def __init__(self, rates: dict[str, list[tuple[date, float]]], max_gap_days: int) -> None:
        self._rates = {c: sorted(series) for c, series in rates.items()}
        self._dates = {c: [d for d, _ in series] for c, series in self._rates.items()}
        self._max_gap = max_gap_days

    def to_usd(self, amount: float, currency: str, on: date) -> float | None:
        if currency == "USD":
            return amount
        series = self._rates.get(currency)
        if not series:
            return None
        i = bisect.bisect_left(self._dates[currency], on)
        best: tuple[int, float] | None = None
        for j in (i - 1, i):
            if 0 <= j < len(series):
                d, rate = series[j]
                gap = abs((d - on).days)
                if gap <= self._max_gap and (best is None or gap < best[0]):
                    best = (gap, rate)
        return amount * best[1] if best else None


# --------------------------------------------------------------------------- #
# Ticker roll-ups (spec §4.4)
# --------------------------------------------------------------------------- #
def _collected(t: LedgerTrade) -> float:
    return t.net_pnl if t.net_pnl is not None else t.premium + t.open_commission


def _in_basis_scope(t: LedgerTrade, open_lots: list[LedgerStockLot]) -> bool:
    if t.side != "Sell":
        return False
    start = min(lot.acquired_date for lot in open_lots)
    assigned_on = {lot.acquired_date for lot in open_lots if lot.source == "assigned"}
    return t.order_date >= start or (t.computed_outcome == "Assigned" and t.close_date in assigned_on)


def _wheel_basis(trades: list[LedgerTrade], open_lots: list[LedgerStockLot], shares: float) -> float | None:
    if shares <= _EPS or not open_lots:
        return None
    cost = sum(lot.remaining * lot.cost_per_share for lot in open_lots)
    collected = sum(_collected(t) for t in trades if _in_basis_scope(t, open_lots))
    return (cost - collected) / shares


def basis_walk(trades: list[LedgerTrade], lots: list[LedgerStockLot]) -> list[LedgerBasisPoint]:
    open_lots = [lot for lot in lots if lot.remaining > _EPS]
    shares = sum(lot.remaining for lot in open_lots)
    if shares <= _EPS:
        return []
    cost = sum(lot.remaining * lot.cost_per_share for lot in open_lots)
    start = min(lot.acquired_date for lot in open_lots)
    points = [LedgerBasisPoint(point_date=start, label="Shares acquired", basis_per_share=cost / shares)]
    collected = 0.0
    scoped = sorted(
        (t for t in trades if _in_basis_scope(t, open_lots)),
        key=lambda t: (t.close_date or t.order_date, t.open_time),
    )
    for t in scoped:
        collected += _collected(t)
        points.append(
            LedgerBasisPoint(
                point_date=t.close_date or t.order_date,
                label=f"{t.side} {t.strike:g}{t.right} {t.outcome}",
                basis_per_share=(cost - collected) / shares,
            )
        )
    return points


def _unrealized(
    symbol: str, has_open: bool, snapshot: PortfolioSnapshot | None
) -> float | None:
    if snapshot is None:
        return None
    marks = [
        p.unrealized_pnl
        for p in snapshot.positions
        if p.unrealized_pnl is not None
        and ((p.sec_type == "OPT" and p.underlying == symbol) or (p.sec_type == "STK" and p.symbol == symbol))
    ]
    if marks:
        return sum(marks)
    return None if has_open else 0.0


def build_tickers(
    trades: list[LedgerTrade],
    lots: list[LedgerStockLot],
    disposals: list[LedgerStockDisposal],
    cash: list[LedgerCashItem],
    *,
    snapshot: PortfolioSnapshot | None,
) -> list[LedgerTicker]:
    income = [c for c in cash if c.underlying and c.event_type in ("dividend", "withholding")]
    symbols = sorted(
        {t.underlying for t in trades} | {lot.underlying for lot in lots} | {c.underlying for c in income if c.underlying}
    )
    out: list[LedgerTicker] = []
    for sym in symbols:
        ts = [t for t in trades if t.underlying == sym]
        closed = [t for t in ts if t.net_pnl is not None]
        stats = [t for t in closed if not t.exclude_from_stats]
        sym_lots = [lot for lot in lots if lot.underlying == sym]
        open_lots = [lot for lot in sym_lots if abs(lot.remaining) > _EPS]
        shares = sum(lot.remaining for lot in open_lots)
        currency = (ts[0].currency if ts else sym_lots[0].currency if sym_lots
                    else next(c.currency for c in income if c.underlying == sym))
        option_net = sum(t.net_pnl for t in closed if t.net_pnl is not None)
        stock_realized = sum(d.realized for d in disposals if d.underlying == sym)
        dividends = sum(c.amount for c in income if c.underlying == sym)
        capital_days = sum(t.capital * t.days_held for t in stats)
        stats_net = [t.net_pnl for t in stats if t.net_pnl is not None]
        open_trades = [t for t in ts if t.close_date is None]
        dates = [t.order_date for t in ts] + [lot.acquired_date for lot in sym_lots]
        out.append(
            LedgerTicker(
                symbol=sym, currency=currency,
                option_premium_gross=sum(t.premium for t in ts if t.side == "Sell"),
                option_net_pnl=option_net, stock_realized=stock_realized, dividends_net=dividends,
                total_realized=option_net + stock_realized + dividends,
                unrealized=_unrealized(sym, bool(open_trades) or shares > _EPS, snapshot),
                n_trades=len(ts), n_open=len(open_trades), n_closed=len(closed),
                win_rate=sum(1 for v in stats_net if v > 0) / len(stats_net) if stats_net else None,
                avg_premium=(sum(t.premium for t in stats) / len(stats)) if stats else None,
                best_trade=max(stats_net) if stats_net else None,
                worst_trade=min(stats_net) if stats_net else None,
                annualised_return_pct=(sum(stats_net) / capital_days * 365 * 100) if capital_days else None,
                shares_held=shares,
                broker_avg_cost=(sum(lot.remaining * lot.cost_per_share for lot in open_lots) / shares) if shares > _EPS else None,
                wheel_adjusted_basis=_wheel_basis(ts, open_lots, shares),
                first_trade=min(dates) if dates else None,
                last_trade=max(dates) if dates else None,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Portfolio summary (spec §4.5; R5)
# --------------------------------------------------------------------------- #
def _bucket(label: str, items: list[tuple[float, bool]]) -> LedgerBucket:
    """``items`` = (realized_usd, counts_for_win_rate)."""
    stats = [v for v, counts in items if counts]
    return LedgerBucket(
        label=label, n_closed=len(items), realized_usd=sum(v for v, _ in items),
        win_rate=sum(1 for v in stats if v > 0) / len(stats) if stats else None,
    )


def build_summary(
    trades: list[LedgerTrade],
    tickers: list[LedgerTicker],
    lots: list[LedgerStockLot],
    disposals: list[LedgerStockDisposal],
    cash: list[LedgerCashItem],
    fx: FxTable,
    *,
    today: date,
    snapshot: PortfolioSnapshot | None,
    orphans: list[LedgerOrphan],
    unreviewed_corporate_actions: int,
    marks_as_of: datetime | None,
) -> LedgerSummary:
    missing = False

    def usd(amount: float, currency: str, on: date) -> float:
        nonlocal missing
        value = fx.to_usd(amount, currency, on)
        if value is None:
            missing = True
            return 0.0
        return value

    realized: list[tuple[date, float]] = []
    strategy_items: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    book_items: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for t in trades:
        if t.net_pnl is None or t.close_date is None:
            continue
        v = usd(t.net_pnl, t.currency, t.close_date)
        realized.append((t.close_date, v))
        label = "Long" if t.side == "Buy" else "CSP" if t.right == "P" else "CC"
        strategy_items[label].append((v, not t.exclude_from_stats))
        book_items[t.book].append((v, not t.exclude_from_stats))
    for d in disposals:
        v = usd(d.realized, d.currency, d.disposal_date)
        realized.append((d.disposal_date, v))
        strategy_items["Stock"].append((v, False))
    for c in cash:
        if c.event_type in ("dividend", "withholding"):
            realized.append((c.event_date, usd(c.amount, c.currency, c.event_date)))
    for o in orphans:
        if o.ibkr_realized_pnl is not None:
            realized.append((o.trade_date, usd(o.ibkr_realized_pnl, o.currency, o.trade_date)))
    other = sum(
        usd(c.amount, c.currency, c.event_date) for c in cash if c.event_type in ("interest", "fee")
    )
    total = sum(v for _, v in realized) + other

    flows = [c for c in cash if c.event_type in ("deposit", "withdrawal")]
    contributed = sum(usd(c.amount, c.currency, c.event_date) for c in flows) if flows else None
    utilised = sum(
        usd(t.strike * t.multiplier * t.lots, t.currency, today)
        for t in trades if t.side == "Sell" and t.right == "P" and t.close_date is None
    ) + sum(
        usd(lot.remaining * lot.cost_per_share, lot.currency, lot.acquired_date)
        for lot in lots if lot.remaining > _EPS
    )
    unrealized = (
        None if snapshot is None
        else sum(usd(tk.unrealized, tk.currency, today) for tk in tickers if tk.unrealized is not None)
    )

    months: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for t in trades:
        if t.side == "Sell":
            months[t.order_date.strftime("%Y-%m")][0] += usd(t.premium, t.currency, t.order_date)
    for d, v in realized:
        months[d.strftime("%Y-%m")][1] += v
    curve: list[LedgerCurvePoint] = []
    running = 0.0
    by_day: dict[date, float] = defaultdict(float)
    for d, v in realized:
        by_day[d] += v
    for d in sorted(by_day):
        running += by_day[d]
        curve.append(LedgerCurvePoint(point_date=d, cumulative_usd=running))

    stats = [t.net_pnl for t in trades if t.net_pnl is not None and not t.exclude_from_stats]
    open_trades = sorted((t for t in trades if t.close_date is None), key=lambda t: t.expiry)
    this_month = today.strftime("%Y-%m")
    return LedgerSummary(
        total_realized_usd=total, interest_and_fees_usd=other, contributed_usd=contributed,
        capital_utilised_usd=utilised,
        available_usd=contributed + total - utilised if contributed is not None else None,
        unrealized_usd=unrealized,
        win_rate=sum(1 for v in stats if v > 0) / len(stats) if stats else None,
        n_trades=len(trades), n_open=len(open_trades),
        premium_this_month_usd=months[this_month][0] if this_month in months else 0.0,
        months=[LedgerMonth(month=m, premium_usd=v[0], realized_usd=v[1]) for m, v in sorted(months.items())],
        curve=curve,
        by_strategy=[_bucket(k, v) for k, v in sorted(strategy_items.items())],
        by_book=[_bucket(k, v) for k, v in sorted(book_items.items())],
        upcoming=open_trades[:20], fx_incomplete=missing, orphan_closes=len(orphans),
        unreviewed_corporate_actions=unreviewed_corporate_actions, marks_as_of=marks_as_of,
    )


# --------------------------------------------------------------------------- #
# Loading + the one entry point
# --------------------------------------------------------------------------- #
def load_cash(session: Session) -> list[LedgerCashItem]:
    return [
        LedgerCashItem(
            event_date=r.event_date, event_type=r.event_type, currency=r.currency,
            amount=r.amount, description=r.description, underlying=r.underlying,
        )
        for r in session.scalars(select(BrokerCashEventRow).order_by(BrokerCashEventRow.event_date))
    ]


def load_fx(session: Session, max_gap_days: int) -> FxTable:
    rates: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for r in session.scalars(select(FxRateRow)):
        rates[r.currency].append((r.rate_date, r.usd_rate))
    return FxTable(dict(rates), max_gap_days)


def build_book(
    session: Session,
    *,
    today: date,
    snapshot: PortfolioSnapshot | None,
    marks_as_of: datetime | None = None,
) -> LedgerBook:
    orders = group_orders(load_execs(session))
    trades, option_orphans = build_option_trades(orders, today=today)
    apply_annotations(trades, load_annotations(session))
    lots, disposals, stock_orphans = build_stock_lots(orders)
    attach_stock_gains(trades, disposals)
    cash = load_cash(session)
    tickers = build_tickers(trades, lots, disposals, cash, snapshot=snapshot)
    orphans = option_orphans + stock_orphans
    unreviewed = session.scalar(
        select(func.count()).select_from(BrokerCorporateActionRow).where(
            BrokerCorporateActionRow.reviewed.is_(False)
        )
    ) or 0
    summary = build_summary(
        trades, tickers, lots, disposals, cash, load_fx(session, get_config().ledger.fx_max_gap_days),
        today=today, snapshot=snapshot, orphans=orphans,
        unreviewed_corporate_actions=int(unreviewed), marks_as_of=marks_as_of,
    )
    return LedgerBook(
        trades=trades, orphans=orphans, tickers=tickers, summary=summary, lots=lots,
        disposals=disposals, cash=cash,
    )


def ticker_detail(book: LedgerBook, symbol: str) -> LedgerTickerDetail | None:
    sym = symbol.upper()
    ticker = next((t for t in book.tickers if t.symbol.upper() == sym), None)
    if ticker is None:
        return None
    trades = [t for t in book.trades if t.underlying.upper() == sym]
    lots = [lot for lot in book.lots if lot.underlying.upper() == sym]
    return LedgerTickerDetail(
        ticker=ticker, trades=trades, lots=lots,
        disposals=[d for d in book.disposals if d.underlying.upper() == sym],
        dividends=[c for c in book.cash if (c.underlying or "").upper() == sym],
        basis_walk=basis_walk(trades, lots),
    )
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_trade_ledger_book.py tests/test_trade_ledger_trades.py tests/test_web_fence.py -v`
Expected: all PASS. Then run `ruff check . && mypy src`.

- [ ] **Step 6: Commit**

```bash
git add src/reporting/trade_ledger.py tests/test_trade_ledger_book.py
git add -p src/common/schemas.py
git commit -m "feat(ledger): stock lots, wheel cost basis, ticker roll-ups, FX, USD summary, build_book"
```

---

### Task 7: Sheet rows and trade filters (shared by the API CSV and the Sheets mirror)

**Files:**
- Modify: `src/reporting/trade_ledger.py` (append)
- Test: `tests/test_trade_ledger_rows.py`

**Interfaces:**
- Produces:
  - `SHEET_HEADER: list[str]`
  - `sheet_row(t: LedgerTrade) -> list[object]`
  - `TICKER_HEADER: list[str]`
  - `ticker_row(t: LedgerTicker) -> list[object]`
  - `summary_rows(s: LedgerSummary) -> list[list[object]]`
  - `filter_trades(trades, *, symbol=None, right=None, outcome=None, book=None, tag=None, since=None, until=None, sort="-order_date") -> list[LedgerTrade]`
  - `TRADE_SORTS: tuple[str, ...]`

- [ ] **Step 1: Write the failing test** — `tests/test_trade_ledger_rows.py`

```python
"""The sheet-format row (one shape for CSV export + Google Sheet) and trade filters (spec §6, §7)."""

from __future__ import annotations

from datetime import date

from src.reporting.trade_ledger import (
    SHEET_HEADER,
    build_option_trades,
    filter_trades,
    group_orders,
    sheet_row,
)
from tests.test_trade_ledger_trades import ex


def _trades():
    trades, _ = build_option_trades(group_orders([
        ex("NVDA 27JUN25 138 P", "2025-06-17, 10:02:11", -1, 1.31, codes="O"),
        ex("NVDA 27JUN25 138 P", "2025-06-27, 11:09:57", 1, 0.01, codes="C"),
        ex("AMZN 18JUL25 207.5 P", "2025-06-25, 13:17:15", -1, 3.25, codes="O"),
        ex("AMZN 18JUL25 207.5 P", "2025-07-18, 16:20:00", 1, 0.0, comm=0.0, codes="C;Ep"),
        ex("GOOGL 01AUG25 197.5 C", "2025-07-28, 10:00:00", -1, 0.67, codes="O"),
    ]), today=date(2025, 7, 30))
    return trades


def test_sheet_header_starts_with_the_operators_columns() -> None:
    assert SHEET_HEADER[:13] == [
        "Sell/Buy", "Put/Call", "Order Date", "Expiration Date", "Ticker", "Lots",
        "Strike Price", "Premium", "Outcome", "Capital", "DTE", "% Profit", "Notes",
    ]


def test_sheet_row_values() -> None:
    nvda = next(t for t in _trades() if t.underlying == "NVDA")
    row = sheet_row(nvda)
    assert row[:9] == ["Sell", "Put", "2025-06-17", "2025-06-27", "NVDA", 1, 138, 131.0, "Bought back"]
    assert row[10] == 10 and row[11] == "34.65%"


def test_filters_and_sort() -> None:
    trades = _trades()
    assert [t.underlying for t in filter_trades(trades, symbol="amzn")] == ["AMZN"]
    assert [t.underlying for t in filter_trades(trades, outcome="Expired")] == ["AMZN"]
    assert [t.underlying for t in filter_trades(trades, right="C")] == ["GOOGL"]
    assert [t.underlying for t in filter_trades(trades, since=date(2025, 6, 20), until=date(2025, 6, 30))] == ["AMZN"]
    assert [t.underlying for t in filter_trades(trades, sort="order_date")] == ["NVDA", "AMZN", "GOOGL"]
    by_pct = filter_trades(trades, sort="-pct_profit")
    assert by_pct[0].pct_profit >= by_pct[1].pct_profit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_trade_ledger_rows.py -v`
Expected: FAIL with ImportError on `SHEET_HEADER`.

- [ ] **Step 3: Append to `src/reporting/trade_ledger.py`**

```python
# --------------------------------------------------------------------------- #
# Sheet-format rows (CSV export + Google Sheet mirror) and filters (spec §6.1, §7)
# --------------------------------------------------------------------------- #
SHEET_HEADER: list[str] = [
    "Sell/Buy", "Put/Call", "Order Date", "Expiration Date", "Ticker", "Lots", "Strike Price",
    "Premium", "Outcome", "Capital", "DTE", "% Profit", "Notes",
    "Close Date", "Net P&L", "Book", "Tags", "Commission",
]
TICKER_HEADER: list[str] = [
    "Ticker", "Currency", "Total realized", "Option net", "Stock realized", "Dividends",
    "Unrealized", "Trades", "Open", "Win rate", "Shares", "Broker avg cost",
    "Wheel-adjusted basis", "Annualised return %",
]
TRADE_SORTS: tuple[str, ...] = (
    "order_date", "-order_date", "expiry", "-expiry", "pct_profit", "-pct_profit",
    "net_pnl", "-net_pnl", "underlying", "-underlying",
)


def _num(v: float) -> float | int:
    return int(v) if float(v).is_integer() else round(v, 4)


def _blank(v: float | None, digits: int = 2) -> object:
    return "" if v is None else round(v, digits)


def sheet_row(t: LedgerTrade) -> list[object]:
    commission = t.open_commission + sum(c.commission for c in t.closes)
    return [
        t.side, "Put" if t.right == "P" else "Call", t.order_date.isoformat(), t.expiry.isoformat(),
        t.underlying, _num(t.lots), _num(t.strike), round(t.premium, 2), t.outcome,
        _blank(t.stock_gain), t.dte, "" if t.pct_profit is None else f"{t.pct_profit:.2f}%", t.notes,
        t.close_date.isoformat() if t.close_date else "", _blank(t.net_pnl), t.book,
        ", ".join(t.tags), round(commission, 2),
    ]


def ticker_row(t: LedgerTicker) -> list[object]:
    return [
        t.symbol, t.currency, round(t.total_realized, 2), round(t.option_net_pnl, 2),
        round(t.stock_realized, 2), round(t.dividends_net, 2), _blank(t.unrealized), t.n_trades,
        t.n_open, "" if t.win_rate is None else f"{t.win_rate * 100:.0f}%", _num(t.shares_held),
        _blank(t.broker_avg_cost, 4), _blank(t.wheel_adjusted_basis, 4),
        "" if t.annualised_return_pct is None else f"{t.annualised_return_pct:.2f}%",
    ]


def summary_rows(s: LedgerSummary) -> list[list[object]]:
    def money(v: float | None) -> object:
        return "n/a" if v is None else round(v, 2)

    return [
        ["Metric", "Value (USD)"],
        ["Total Profit", money(s.total_realized_usd)],
        ["Contributed capital", money(s.contributed_usd)],
        ["Capital utilised", money(s.capital_utilised_usd)],
        ["Available capital", money(s.available_usd)],
        ["Unrealized", money(s.unrealized_usd)],
        ["Win rate", "n/a" if s.win_rate is None else f"{s.win_rate * 100:.0f}%"],
        ["Premium this month", money(s.premium_this_month_usd)],
        ["Trades", s.n_trades],
        ["Open trades", s.n_open],
        ["FX incomplete", "yes" if s.fx_incomplete else "no"],
        ["Orphan closes", s.orphan_closes],
    ]


def filter_trades(
    trades: list[LedgerTrade],
    *,
    symbol: str | None = None,
    right: str | None = None,
    outcome: str | None = None,
    book: str | None = None,
    tag: str | None = None,
    since: date | None = None,
    until: date | None = None,
    sort: str = "-order_date",
) -> list[LedgerTrade]:
    out = [
        t for t in trades
        if (symbol is None or t.underlying.upper() == symbol.upper())
        and (right is None or t.right == right)
        and (outcome is None or t.outcome == outcome)
        and (book is None or t.book == book)
        and (tag is None or tag in t.tags)
        and (since is None or t.order_date >= since)
        and (until is None or t.order_date <= until)
    ]
    field_name = sort.lstrip("-")
    if sort not in TRADE_SORTS:
        raise ValueError(f"unknown sort {sort!r}")
    present = [t for t in out if getattr(t, field_name) is not None]
    absent = [t for t in out if getattr(t, field_name) is None]
    present.sort(key=lambda t: (getattr(t, field_name), t.open_time), reverse=sort.startswith("-"))
    return present + absent
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_trade_ledger_rows.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/reporting/trade_ledger.py tests/test_trade_ledger_rows.py
git commit -m "feat(ledger): sheet-format rows and trade filters"
```

---

### Task 8: Command kinds, annotations writer, drain handlers

**Files:**
- Modify: `src/api/models/commands.py`, `src/notify/command_drain.py`
- Create: `src/ledger/annotations.py`
- Test: `tests/test_drain_ledger.py`, plus extend `tests/test_command_schemas.py`

**Interfaces:**
- Consumes: `parse_activity_csv`/`NotAnActivityStatement` (Task 3), `ingest` (Task 4), `bump_generation` (Task 2), `CommandFailed` and `register` (existing in `command_drain.py`).
- Produces:
  - `CommandKind.LEDGER_IMPORT = "ledger_import"`, `CommandKind.LEDGER_ANNOTATE = "ledger_annotate"`, `CommandKind.LEDGER_CA_REVIEWED = "ledger_ca_reviewed"`
  - Payloads: `LedgerImportPayload(filename, content)`, `LedgerAnnotatePayload(order_key, notes?, tags?, outcome_override?, exclude_from_stats?)`, `LedgerCaReviewedPayload(corporate_action_id)`
  - `annotate(session, *, order_key, fields: dict, updated_by) -> None`
  - `mark_corporate_action_reviewed(session, ca_id) -> bool`
  - Drain results:
    - `ledger_import` → `{"run_id", "counts", "warnings"}`, or failed with reason `pdf_not_supported` | `not_an_activity_statement` | `parse_errors` | `account_mismatch`
    - `ledger_annotate` → `{"order_key", "updated": [...]}`
    - `ledger_ca_reviewed` → `{"corporate_action_id"}`, or failed with reason `not_found`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_command_schemas.py`:

```python
def test_ledger_payloads_validate_and_are_never_deduped() -> None:
    from src.api.models.commands import (
        LedgerAnnotatePayload,
        LedgerCaReviewedPayload,
        LedgerImportPayload,
    )

    imp = validate_payload(CommandKind.LEDGER_IMPORT, {"filename": "s.csv", "content": "x"})
    assert isinstance(imp, LedgerImportPayload)
    ann = validate_payload(CommandKind.LEDGER_ANNOTATE, {"order_key": "a" * 16, "notes": "hi"})
    assert isinstance(ann, LedgerAnnotatePayload) and ann.model_fields_set == {"order_key", "notes"}
    ca = validate_payload(CommandKind.LEDGER_CA_REVIEWED, {"corporate_action_id": 3})
    assert isinstance(ca, LedgerCaReviewedPayload)
    for kind, p in ((CommandKind.LEDGER_IMPORT, imp), (CommandKind.LEDGER_ANNOTATE, ann), (CommandKind.LEDGER_CA_REVIEWED, ca)):
        assert dedupe_key_for(kind, p) is None


def test_ledger_annotate_rejects_unknown_outcome_and_bad_key() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        validate_payload(CommandKind.LEDGER_ANNOTATE, {"order_key": "a" * 16, "outcome_override": "Won"})
    with pytest.raises(pydantic.ValidationError):
        validate_payload(CommandKind.LEDGER_ANNOTATE, {"order_key": "short"})
```

If `tests/test_command_schemas.py` doesn't already import `pytest`, add `import pytest`.

Create `tests/test_drain_ledger.py`:

```python
"""ledger_import / ledger_annotate / ledger_ca_reviewed drain handlers (spec §6.1, R7, R11)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"


@pytest.fixture
def run_command(monkeypatch, tmp_path):
    import src.storage.db as dbmod
    from src.common.config import Config

    monkeypatch.setattr(dbmod, "_engine", None)
    monkeypatch.setattr(dbmod, "_SessionLocal", None)
    monkeypatch.setattr(Config, "db_url_abs", lambda self: f"sqlite:///{tmp_path / 'drain.db'}")
    dbmod.init_db()

    from src.notify.command_drain import drain_once
    from src.storage.app_commands import enqueue_command
    from src.storage.models import AppCommandRow

    def run(kind: str, payload: dict):
        with dbmod.session_scope() as s:
            row, _ = enqueue_command(s, kind=kind, payload=payload, requested_by="owner", dedupe_key=None)
            cid = row.id
        asyncio.run(drain_once(None, MagicMock(), "chat"))
        with dbmod.session_scope() as s:
            r = s.get(AppCommandRow, cid)
            return r.status, r.result, r.payload

    return run


def test_import_applies_and_strips_the_file_from_the_command_row(run_command) -> None:
    status, result, payload = run_command(
        "ledger_import", {"filename": "stmt.csv", "content": FIXTURE.read_text()}
    )
    assert status == "applied"
    assert result["counts"]["new"] == 15
    assert "content" not in payload and payload["content_bytes"] > 1000


def test_pdf_upload_fails_with_a_pointer(run_command) -> None:
    status, result, _ = run_command("ledger_import", {"filename": "stmt.pdf", "content": "%PDF-1.7"})
    assert status == "failed" and result["reason"] == "pdf_not_supported"


def test_foreign_csv_fails(run_command) -> None:
    status, result, _ = run_command("ledger_import", {"filename": "x.csv", "content": "a,b\n1,2\n"})
    assert status == "failed" and result["reason"] == "not_an_activity_statement"


def test_annotate_sets_only_the_fields_sent(run_command) -> None:
    from src.storage.db import session_scope
    from src.storage.models import TradeAnnotationRow

    key = "b" * 16
    assert run_command("ledger_annotate", {"order_key": key, "notes": "first", "outcome_override": "Expired"})[0] == "applied"
    assert run_command("ledger_annotate", {"order_key": key, "tags": ["earnings", " earnings ", ""]})[0] == "applied"
    with session_scope() as s:
        row = s.scalar(select(TradeAnnotationRow).where(TradeAnnotationRow.order_key == key))
        assert (row.notes, row.tags, row.outcome_override) == ("first", ["earnings"], "Expired")
    run_command("ledger_annotate", {"order_key": key, "outcome_override": ""})
    with session_scope() as s:
        assert s.scalar(select(TradeAnnotationRow.outcome_override).where(TradeAnnotationRow.order_key == key)) is None


def test_corporate_action_reviewed(run_command) -> None:
    run_command("ledger_import", {"filename": "stmt.csv", "content": FIXTURE.read_text()})
    from src.storage.db import session_scope
    from src.storage.models import BrokerCorporateActionRow

    with session_scope() as s:
        ca_id = s.scalar(select(BrokerCorporateActionRow.id))
    assert run_command("ledger_ca_reviewed", {"corporate_action_id": ca_id})[0] == "applied"
    status, result, _ = run_command("ledger_ca_reviewed", {"corporate_action_id": 9999})
    assert status == "failed" and result["reason"] == "not_found"
```

`enqueue_command`'s signature is defined in `src/storage/app_commands.py`. If it differs from `(s, *, kind, payload, requested_by, dedupe_key)`, match the existing one; `tests/test_drain_refresh.py` shows real usage.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_drain_ledger.py tests/test_command_schemas.py -v`
Expected: FAIL. `CommandKind` has no `LEDGER_IMPORT`, and the drain marks these commands `unknown_kind`.

- [ ] **Step 3: Extend `src/api/models/commands.py`**

Add `from typing import Annotated` to the imports. If `Literal` is already imported from `typing`, extend that import. Then:

```python
# in class CommandKind, after REFRESH:
    LEDGER_IMPORT = "ledger_import"
    LEDGER_ANNOTATE = "ledger_annotate"
    LEDGER_CA_REVIEWED = "ledger_ca_reviewed"
```

After `class RefreshPayload`:

```python
# --- Trade ledger (docs/superpowers/specs/2026-10-04-trade-ledger-design.md, R7, R11) ---
_LEDGER_OUTCOMES = Literal[
    "", "Open", "Pending", "Expired", "Assigned", "Called away", "Exercised", "Bought back", "Sold", "Rolled",
]


class LedgerImportPayload(BaseModel):
    """An Activity Statement CSV, read as text by the browser (the proxy is JSON-only)."""

    model_config = ConfigDict(extra="forbid")
    filename: str = Field(max_length=200)
    content: str = Field(max_length=5_242_880)


class LedgerAnnotatePayload(BaseModel):
    """Only the fields present are applied (``model_fields_set``). ``outcome_override=""`` clears."""

    model_config = ConfigDict(extra="forbid")
    order_key: str = Field(min_length=16, max_length=16, pattern=r"^[0-9a-f]{16}$")
    notes: str | None = Field(default=None, max_length=2000)
    tags: list[Annotated[str, Field(max_length=32)]] | None = Field(default=None, max_length=20)
    outcome_override: _LEDGER_OUTCOMES | None = None
    exclude_from_stats: bool | None = None


class LedgerCaReviewedPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corporate_action_id: int
```

The test uses `"a" * 16` and `"b" * 16`, which are valid hex. Add these three entries to `PAYLOAD_FOR`:

```python
    CommandKind.LEDGER_IMPORT: LedgerImportPayload,
    CommandKind.LEDGER_ANNOTATE: LedgerAnnotatePayload,
    CommandKind.LEDGER_CA_REVIEWED: LedgerCaReviewedPayload,
```

Add the three kinds to the `None` tuple in `dedupe_key_for`. Then extend its docstring with one sentence: "The three ledger kinds are repeatable too — imports are idempotent upserts and annotations are last-write-wins."

- [ ] **Step 4: Create `src/ledger/annotations.py`**

```python
"""The only writer of ``trade_annotations`` and the corporate-action review flag.

Called from the exec process's drain handlers (src/notify/command_drain.py), never the API.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.ledger.state import bump_generation
from src.storage.models import BrokerCorporateActionRow, TradeAnnotationRow


def annotate(session: Session, *, order_key: str, fields: dict[str, Any], updated_by: str) -> None:
    row = session.scalar(select(TradeAnnotationRow).where(TradeAnnotationRow.order_key == order_key))
    if row is None:
        row = TradeAnnotationRow(order_key=order_key, notes="", tags=[], exclude_from_stats=False)
        session.add(row)
    if "notes" in fields:
        row.notes = fields["notes"] or ""
    if "tags" in fields:
        row.tags = sorted({t.strip() for t in (fields["tags"] or []) if t and t.strip()})
    if "outcome_override" in fields:
        row.outcome_override = fields["outcome_override"] or None
    if "exclude_from_stats" in fields:
        row.exclude_from_stats = bool(fields["exclude_from_stats"])
    row.updated_by = updated_by
    bump_generation(session)


def mark_corporate_action_reviewed(session: Session, ca_id: int) -> bool:
    row = session.get(BrokerCorporateActionRow, ca_id)
    if row is None:
        return False
    row.reviewed = True
    bump_generation(session)
    return True
```

- [ ] **Step 5: Register handlers in `src/notify/command_drain.py`**

Append at the end of the file:

```python
# ---------------------------------------------------------------------------
# Trade ledger (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §6.1, R7, R11).
#
# Reporting-only writes: none of these touch an approval, an order, or a gate. ``ledger_import``
# strips the uploaded file out of the command row once handled (applied or failed) so a 5 MB
# statement never lingers in app_commands.
# ---------------------------------------------------------------------------


def _strip_upload(command_id: int, filename: str, size: int) -> None:
    from src.storage.models import AppCommandRow

    with session_scope() as s:
        row = s.get(AppCommandRow, command_id)
        if row is not None:
            row.payload = {"filename": filename, "content_bytes": size}


@register("ledger_import")
def _ledger_import(*, command: Any, **_: Any) -> dict:
    from src.api.models.commands import LedgerImportPayload
    from src.ledger.activity_csv import NotAnActivityStatement, parse_activity_csv
    from src.ledger.ingest import ingest

    payload = LedgerImportPayload(**command.payload)
    try:
        if payload.filename.lower().endswith(".pdf") or payload.content.lstrip().startswith("%PDF"):
            raise CommandFailed("pdf_not_supported")
        try:
            statement = parse_activity_csv(payload.content)
        except NotAnActivityStatement as exc:
            raise CommandFailed("not_an_activity_statement", {"detail": str(exc)}) from exc
        result = ingest(statement, source="csv", filename=payload.filename)
        if result.status != "ok":
            raise CommandFailed(
                result.reason or "import_failed",
                {"run_id": result.run_id, "errors": [e.model_dump() for e in result.errors[:50]]},
            )
        return {"run_id": result.run_id, "counts": result.counts, "warnings": len(result.errors)}
    finally:
        _strip_upload(command.id, payload.filename, len(payload.content))


@register("ledger_annotate")
def _ledger_annotate(*, command: Any, **_: Any) -> dict:
    from src.api.models.commands import LedgerAnnotatePayload
    from src.ledger.annotations import annotate

    payload = LedgerAnnotatePayload(**command.payload)
    fields = payload.model_dump(include=payload.model_fields_set - {"order_key"})
    with session_scope() as s:
        annotate(s, order_key=payload.order_key, fields=fields, updated_by=command.requested_by)
    return {"order_key": payload.order_key, "updated": sorted(fields)}


@register("ledger_ca_reviewed")
def _ledger_ca_reviewed(*, command: Any, **_: Any) -> dict:
    from src.api.models.commands import LedgerCaReviewedPayload
    from src.ledger.annotations import mark_corporate_action_reviewed

    payload = LedgerCaReviewedPayload(**command.payload)
    with session_scope() as s:
        if not mark_corporate_action_reviewed(s, payload.corporate_action_id):
            raise CommandFailed("not_found")
    return {"corporate_action_id": payload.corporate_action_id}
```

`command.id` exists because `pending_commands` returns `AppCommandRow`s; confirm this by reading `src/storage/app_commands.py::pending_commands`. Note that `CommandFailed` raised inside the `try` still runs the `finally` block, which is intended.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_drain_ledger.py tests/test_command_schemas.py tests/test_write_path_invariants.py tests/test_api_command_engine.py -v`
Expected: all PASS. If `test_write_path_invariants.py` enumerates the control kinds that need no live confirmation, the ledger kinds must not join `ORDER_REACHING`; they don't, because they aren't added there.

- [ ] **Step 7: Commit**

```bash
git add src/ledger/annotations.py tests/test_drain_ledger.py
git add -p src/api/models/commands.py src/notify/command_drain.py tests/test_command_schemas.py
git commit -m "feat(ledger): ledger_import / ledger_annotate / ledger_ca_reviewed commands"
```

---

### Task 9: Read-only API — `/ledger/*`

**Files:**
- Create: `src/api/models/ledger.py`, `src/api/routers/ledger.py`
- Modify: `src/api/main.py` (import + `include_router`), `src/api/routers/meta.py` (`_SECTIONS`), `tests/test_api_meta.py` (expected section set)
- Test: `tests/test_api_ledger.py`

**Interfaces:**
- Consumes:
  - `build_book`, `ticker_detail`, `filter_trades`, `TRADE_SORTS`, `SHEET_HEADER`, `sheet_row` (Tasks 6–7)
  - `read_portfolio(db) -> PortfolioReading(snapshot, source, as_of, degraded)` (existing)
  - `TradingDb`, `OwnerUser` (existing)
  - `Envelope` (existing)
  - State keys (Task 2)
- Produces:
  - `GET /ledger/summary` → `{as_of, summary}`
  - `GET /ledger/tickers` → `{as_of, tickers}`
  - `GET /ledger/tickers/{symbol}` → `{as_of, detail}` or 404
  - `GET /ledger/trades?symbol&right&outcome&book&tag&since&until&sort` → `{as_of, filters, n, trades}`
  - `GET /ledger/trades.csv` (same filters) → `text/csv` attachment
  - `GET /ledger/trades/{order_key}` → `{as_of, trade, executions}` or 404
  - `GET /ledger/imports` → `{as_of, runs, flex, sheets, corporate_actions}`
  - Nav section `ledger`

- [ ] **Step 1: Write the failing test** — `tests/test_api_ledger.py`

```python
"""GET /ledger/* — thin renderers over src/reporting/trade_ledger.py (spec §6.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import OWNER

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"


@pytest.fixture()
def seeded(client, api_db):
    from src.ledger.activity_csv import parse_activity_csv
    from src.ledger.ingest import ingest

    ingest(parse_activity_csv(FIXTURE.read_text()), source="csv", filename="sample.csv")
    return client


def test_requires_owner(client) -> None:
    assert client.get("/ledger/summary").status_code == 401


def test_empty_ledger_is_empty_not_an_error(client) -> None:
    body = client.get("/ledger/summary", headers=OWNER).json()
    assert body["summary"]["n_trades"] == 0
    assert body["summary"]["contributed_usd"] is None
    assert client.get("/ledger/trades", headers=OWNER).json()["trades"] == []


def test_trades_and_sheet_percentage(seeded) -> None:
    body = seeded.get("/ledger/trades", headers=OWNER).json()
    assert body["n"] == 6  # NVDA, AMZN 207.5P, AMZN 215P, AMZN 235C, OPEN 3C, OPEN1 5C
    nvda = next(t for t in body["trades"] if t["underlying"] == "NVDA")
    assert round(nvda["pct_profit"], 2) == 34.65


def test_trade_filters(seeded) -> None:
    amzn = seeded.get("/ledger/trades?symbol=AMZN", headers=OWNER).json()
    assert amzn["n"] == 3 and amzn["filters"]["symbol"] == "AMZN"
    assert seeded.get("/ledger/trades?outcome=Expired", headers=OWNER).json()["n"] == 1
    assert seeded.get("/ledger/trades?sort=bogus", headers=OWNER).status_code == 422


def test_ticker_detail_and_404(seeded) -> None:
    d = seeded.get("/ledger/tickers/amzn", headers=OWNER).json()["detail"]
    assert d["ticker"]["symbol"] == "AMZN" and len(d["disposals"]) == 1
    assert seeded.get("/ledger/tickers/ZZZZ", headers=OWNER).status_code == 404


def test_trade_detail_shows_its_executions(seeded) -> None:
    key = seeded.get("/ledger/trades?symbol=NVDA", headers=OWNER).json()["trades"][0]["order_key"]
    body = seeded.get(f"/ledger/trades/{key}", headers=OWNER).json()
    assert len(body["executions"]) == 2
    assert seeded.get("/ledger/trades/0000000000000000", headers=OWNER).status_code == 404


def test_csv_export_uses_the_sheet_header(seeded) -> None:
    r = seeded.get("/ledger/trades.csv?symbol=NVDA", headers=OWNER)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0].startswith("Sell/Buy,Put/Call,Order Date,Expiration Date,Ticker")
    assert len(lines) == 2


def test_imports_lists_runs_and_feed_status(seeded) -> None:
    body = seeded.get("/ledger/imports", headers=OWNER).json()
    assert body["runs"][0]["filename"] == "sample.csv" and body["runs"][0]["status"] == "ok"
    assert body["flex"]["configured"] in (True, False)
    assert len(body["corporate_actions"]) == 1 and body["corporate_actions"][0]["reviewed"] is False


def test_annotation_goes_through_post_commands(seeded) -> None:
    key = seeded.get("/ledger/trades?symbol=NVDA", headers=OWNER).json()["trades"][0]["order_key"]
    r = seeded.post("/commands", headers=OWNER,
                    json={"kind": "ledger_annotate", "payload": {"order_key": key, "notes": "x"}})
    assert r.status_code in (200, 201, 202)
    assert r.json()["status"] == "pending"


def test_nav_has_a_ledger_section(client) -> None:
    sections = {s["key"]: s for s in client.get("/nav", headers=OWNER).json()["sections"]}
    assert sections["ledger"]["available"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_ledger.py -v`
Expected: FAIL with 404 on `/ledger/summary`.

- [ ] **Step 3: Create `src/api/models/ledger.py`**

```python
"""Response shapes for GET /ledger/* (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §6.1)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from src.api.models.common import Envelope
from src.common.schemas import LedgerSummary, LedgerTicker, LedgerTickerDetail, LedgerTrade


class LedgerSummaryResponse(Envelope):
    summary: LedgerSummary


class LedgerTickersResponse(Envelope):
    tickers: list[LedgerTicker]


class LedgerTickerResponse(Envelope):
    detail: LedgerTickerDetail


class LedgerTradesFilters(BaseModel):
    symbol: str | None = None
    right: str | None = None
    outcome: str | None = None
    book: str | None = None
    tag: str | None = None
    since: date | None = None
    until: date | None = None
    sort: str = "-order_date"


class LedgerTradesResponse(Envelope):
    filters: LedgerTradesFilters
    n: int
    trades: list[LedgerTrade]


class LedgerExecutionOut(BaseModel):
    id: int
    source: str
    source_kind: str
    exec_id: str | None
    trade_time: datetime
    quantity: float
    price: float
    proceeds: float
    commission: float
    codes: str
    book: str
    superseded_by: int | None


class LedgerTradeResponse(Envelope):
    trade: LedgerTrade
    executions: list[LedgerExecutionOut]


class LedgerImportRunOut(BaseModel):
    id: int
    source: str
    filename: str | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    reason: str | None
    counts: dict[str, int]
    errors: list[dict[str, object]]


class LedgerFeedStatus(BaseModel):
    configured: bool
    last_run: str | None
    last_status: str | None
    last_error: str | None


class LedgerCorporateActionOut(BaseModel):
    id: int
    event_date: date
    underlying: str | None
    description: str
    quantity: float
    proceeds: float
    reviewed: bool


class LedgerImportsResponse(Envelope):
    runs: list[LedgerImportRunOut]
    flex: LedgerFeedStatus
    sheets: LedgerFeedStatus
    corporate_actions: list[LedgerCorporateActionOut]
```

- [ ] **Step 4: Create `src/api/routers/ledger.py`**

```python
"""GET /ledger/* — the whole-account trade ledger (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §6).

Thin renderers over src/reporting/trade_ledger.py: every figure comes from ``build_book``, so the
trades table, ticker pages, summary tiles, CSV export and the Google Sheet mirror agree by
construction. Read-only — every write is a POST /commands intent (ledger_import,
ledger_annotate, ledger_ca_reviewed) that the drain applies (R11).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.api.deps import OwnerUser, TradingDb
from src.api.models.ledger import (
    LedgerCorporateActionOut,
    LedgerExecutionOut,
    LedgerFeedStatus,
    LedgerImportRunOut,
    LedgerImportsResponse,
    LedgerSummaryResponse,
    LedgerTickerResponse,
    LedgerTickersResponse,
    LedgerTradeResponse,
    LedgerTradesFilters,
    LedgerTradesResponse,
)
from src.api.portfolio_source import read_portfolio
from src.common.config import get_config
from src.common.schemas import LedgerBook, LedgerTrade
from src.ledger.state import (
    LEDGER_FLEX_LAST_RUN_KEY,
    LEDGER_FLEX_LAST_STATUS_KEY,
    LEDGER_SHEETS_LAST_ERROR_KEY,
    LEDGER_SHEETS_LAST_SYNC_KEY,
)
from src.reporting.trade_ledger import (
    SHEET_HEADER,
    TRADE_SORTS,
    build_book,
    filter_trades,
    sheet_row,
    ticker_detail,
)
from src.storage.models import (
    BrokerCorporateActionRow,
    BrokerExecutionRow,
    LedgerImportRunRow,
    SystemSettingRow,
)

router = APIRouter(prefix="/ledger", tags=["ledger"])

_ET = ZoneInfo("America/New_York")
SortKey = Literal[
    "order_date", "-order_date", "expiry", "-expiry", "pct_profit", "-pct_profit",
    "net_pnl", "-net_pnl", "underlying", "-underlying",
]
assert set(SortKey.__args__) == set(TRADE_SORTS)  # type: ignore[attr-defined]


def _book(db: Session) -> LedgerBook:
    reading = read_portfolio(db)
    return build_book(db, today=datetime.now(_ET).date(), snapshot=reading.snapshot, marks_as_of=reading.as_of)


def _now() -> datetime:
    return datetime.now(UTC)


def _filtered(db: Session, f: LedgerTradesFilters) -> list[LedgerTrade]:
    return filter_trades(
        _book(db).trades, symbol=f.symbol, right=f.right, outcome=f.outcome, book=f.book,
        tag=f.tag, since=f.since, until=f.until, sort=f.sort,
    )


def _filters(
    symbol: str | None, right: Literal["P", "C"] | None, outcome: str | None,
    book: Literal["system", "manual"] | None, tag: str | None, since: date | None,
    until: date | None, sort: SortKey,
) -> LedgerTradesFilters:
    return LedgerTradesFilters(
        symbol=symbol.upper() if symbol else None, right=right, outcome=outcome, book=book,
        tag=tag, since=since, until=until, sort=sort,
    )


def _setting(db: Session, key: str) -> str | None:
    value = db.scalar(select(SystemSettingRow.value).where(SystemSettingRow.key == key))
    return value or None


@router.get("/summary", response_model=LedgerSummaryResponse)
def get_summary(db: TradingDb, _user: OwnerUser) -> LedgerSummaryResponse:
    return LedgerSummaryResponse(as_of=_now(), summary=_book(db).summary)


@router.get("/tickers", response_model=LedgerTickersResponse)
def get_tickers(db: TradingDb, _user: OwnerUser) -> LedgerTickersResponse:
    tickers = sorted(_book(db).tickers, key=lambda t: t.total_realized, reverse=True)
    return LedgerTickersResponse(as_of=_now(), tickers=tickers)


@router.get("/tickers/{symbol}", response_model=LedgerTickerResponse)
def get_ticker(symbol: str, db: TradingDb, _user: OwnerUser) -> LedgerTickerResponse:
    detail = ticker_detail(_book(db), symbol)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"No ledger history for {symbol.upper()}")
    return LedgerTickerResponse(as_of=_now(), detail=detail)


@router.get("/trades", response_model=LedgerTradesResponse)
def get_trades(
    db: TradingDb, _user: OwnerUser,
    symbol: str | None = None, right: Literal["P", "C"] | None = None, outcome: str | None = None,
    book: Literal["system", "manual"] | None = None, tag: str | None = None,
    since: date | None = None, until: date | None = None, sort: SortKey = Query("-order_date"),
) -> LedgerTradesResponse:
    f = _filters(symbol, right, outcome, book, tag, since, until, sort)
    trades = _filtered(db, f)
    return LedgerTradesResponse(as_of=_now(), filters=f, n=len(trades), trades=trades)


@router.get("/trades.csv")
def get_trades_csv(
    db: TradingDb, _user: OwnerUser,
    symbol: str | None = None, right: Literal["P", "C"] | None = None, outcome: str | None = None,
    book: Literal["system", "manual"] | None = None, tag: str | None = None,
    since: date | None = None, until: date | None = None, sort: SortKey = Query("-order_date"),
) -> Response:
    trades = _filtered(db, _filters(symbol, right, outcome, book, tag, since, until, sort))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(SHEET_HEADER)
    writer.writerows(sheet_row(t) for t in trades)
    filename = f"trade-ledger-{datetime.now(_ET).date().isoformat()}.csv"
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/trades/{order_key}", response_model=LedgerTradeResponse)
def get_trade(order_key: str, db: TradingDb, _user: OwnerUser) -> LedgerTradeResponse:
    trade = next((t for t in _book(db).trades if t.order_key == order_key), None)
    if trade is None:
        raise HTTPException(status_code=404, detail="No such trade")
    ids = trade.exec_row_ids
    rows = db.scalars(
        select(BrokerExecutionRow)
        .where(or_(BrokerExecutionRow.id.in_(ids), BrokerExecutionRow.superseded_by.in_(ids)))
        .order_by(BrokerExecutionRow.trade_time, BrokerExecutionRow.id)
    )
    executions = [
        LedgerExecutionOut(
            id=r.id, source=r.source, source_kind=r.source_kind, exec_id=r.exec_id,
            trade_time=r.trade_time.replace(tzinfo=UTC), quantity=r.quantity, price=r.price,
            proceeds=r.proceeds, commission=r.commission, codes=r.codes, book=r.book,
            superseded_by=r.superseded_by,
        )
        for r in rows
    ]
    return LedgerTradeResponse(as_of=_now(), trade=trade, executions=executions)


@router.get("/imports", response_model=LedgerImportsResponse)
def get_imports(db: TradingDb, _user: OwnerUser) -> LedgerImportsResponse:
    secrets = get_config().secrets
    runs = db.scalars(
        select(LedgerImportRunRow)
        .where(LedgerImportRunRow.source.in_(("csv", "flex")))
        .order_by(LedgerImportRunRow.id.desc())
        .limit(50)
    )
    actions = db.scalars(
        select(BrokerCorporateActionRow)
        .order_by(BrokerCorporateActionRow.reviewed, BrokerCorporateActionRow.event_date.desc())
        .limit(100)
    )
    return LedgerImportsResponse(
        as_of=_now(),
        runs=[
            LedgerImportRunOut(
                id=r.id, source=r.source, filename=r.filename, started_at=r.started_at.replace(tzinfo=UTC),
                finished_at=r.finished_at.replace(tzinfo=UTC) if r.finished_at else None,
                status=r.status, reason=r.reason, counts=r.counts or {}, errors=(r.errors or [])[:50],
            )
            for r in runs
        ],
        flex=LedgerFeedStatus(
            configured=bool(secrets.ibkr_flex_token and secrets.ibkr_flex_query_id),
            last_run=_setting(db, LEDGER_FLEX_LAST_RUN_KEY),
            last_status=_setting(db, LEDGER_FLEX_LAST_STATUS_KEY), last_error=None,
        ),
        sheets=LedgerFeedStatus(
            configured=bool(secrets.google_sheets_credentials_path and secrets.ledger_sheet_id),
            last_run=_setting(db, LEDGER_SHEETS_LAST_SYNC_KEY), last_status=None,
            last_error=_setting(db, LEDGER_SHEETS_LAST_ERROR_KEY),
        ),
        corporate_actions=[
            LedgerCorporateActionOut(
                id=a.id, event_date=a.event_date, underlying=a.underlying, description=a.description,
                quantity=a.quantity, proceeds=a.proceeds, reviewed=a.reviewed,
            )
            for a in actions
        ],
    )
```

**Route-order note:** `/trades.csv` is declared before `/trades/{order_key}`, so FastAPI matches it first. Keep that order.

**Dependency note:** `src/ledger/state.py` imports `get_setting/set_setting` from `src.storage.system_settings`. The router only imports constants from it, which does not give the API a write handle. Run `tests/test_web_fence.py` to confirm.

- [ ] **Step 5: Wire the router and nav**

In `src/api/main.py`, add `ledger` to the `from src.api.routers import (...)` list, and add `app.include_router(ledger.router)` after `app.include_router(pnl.router, prefix="/pnl")`.

In `src/api/routers/meta.py`, add one comment line above `_SECTIONS`: `# "ledger" added with the trade ledger (docs/superpowers/specs/2026-10-04-trade-ledger-design.md).` Then insert `("ledger", "Ledger", True, None),` directly after the `("pnl", "P&L", True, None),` entry.

In `tests/test_api_meta.py`, add `"ledger"` to the expected section-key set.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_api_ledger.py tests/test_api_meta.py tests/test_web_fence.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/api/models/ledger.py src/api/routers/ledger.py tests/test_api_ledger.py
git add -p src/api/main.py src/api/routers/meta.py tests/test_api_meta.py
git commit -m "feat(ledger): read-only /ledger API, CSV export, nav section"
```

---

### Task 10: Flex Web Service — client, XML parser, EOD step, CLI

**Files:**
- Create: `src/ledger/flex.py`, `scripts/ledger_flex_pull.py`
- Modify: `src/orchestrator/eod_report.py` (one step before `# 7. Send Telegram.`)
- Test: `tests/test_ledger_flex.py`

**Interfaces:**
- Consumes: `ingest` (Task 4); `number_occurrences` (Task 3); helpers (Task 1); `set_setting`; state keys.
- Produces:
  - `class FlexError(RuntimeError)` with `.code`
  - `fetch_statement(token, query_id, *, client=None, poll_interval=10.0, timeout=600.0, sleep=time.sleep, clock=time.monotonic) -> str`
  - `parse_flex_xml(text) -> ParsedStatement`
  - `run_flex_pull(*, query_id=None, dry_run=False) -> LedgerImportResult | ParsedStatement | None`
  - CLI `python -m scripts.ledger_flex_pull [--query-id ID] [--dry-run]`

Flex specifics:
- Endpoint base: `https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService`, version `v=3`.
- `SendRequest` → `<FlexStatementResponse><Status>Success</Status><ReferenceCode/><Url/>`.
- `GetStatement` returns either `<FlexQueryResponse>` or a `<FlexStatementResponse>` with an `ErrorCode`. Codes `1019` (generation in progress) and `1018` (too many requests) are retried; anything else raises.
- **Trade rows:** take `<Trade>` with `assetCategory` STK/OPT and `levelOfDetail` absent or `EXECUTION`. The `notes` attribute carries the codes.
- **Cash rows:** take `<CashTransaction>` with `levelOfDetail` absent or `DETAIL`. Types map to: `Dividends`/`Payment In Lieu Of Dividends`→dividend, `Withholding Tax`→withholding, `Deposits/Withdrawals`→deposit/withdrawal (uses `settleDate`), `Broker Interest Received`/`Broker Interest Paid`→interest, `Other Fees`/`Commission Adjustments`→fee.
- **FX:** `<ConversionRate reportDate fromCurrency toCurrency rate>`. With base B = `toCurrency`, `usd_rate(c) = rate(c→B) / rate(USD→B)` and `usd_rate(B) = 1 / rate(USD→B)`.
- **OptionEAE:** ignored in v1 (R1).

- [ ] **Step 1: Write the failing test** — `tests/test_ledger_flex.py`

```python
"""Flex Web Service client + parser (spec §5.2; R1, R6)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pytest

from src.ledger.flex import FlexError, fetch_statement, parse_flex_xml, run_flex_pull

SEND_OK = """<FlexStatementResponse timestamp="x"><Status>Success</Status>
<ReferenceCode>1234</ReferenceCode><Url>https://example.test/GetStatement</Url></FlexStatementResponse>"""
IN_PROGRESS = """<FlexStatementResponse><Status>Warn</Status><ErrorCode>1019</ErrorCode>
<ErrorMessage>Statement generation in progress.</ErrorMessage></FlexStatementResponse>"""
BAD_TOKEN = """<FlexStatementResponse><Status>Fail</Status><ErrorCode>1012</ErrorCode>
<ErrorMessage>Token has expired.</ErrorMessage></FlexStatementResponse>"""
STATEMENT = """<FlexQueryResponse queryName="ledger" type="AF"><FlexStatements count="1">
<FlexStatement accountId="U0000001" fromDate="20250710" toDate="20250718">
<Trades>
<Trade accountId="U0000001" currency="USD" assetCategory="OPT" symbol="NVDA  250718P00170000"
 underlyingSymbol="NVDA" strike="170" expiry="20250718" putCall="P" multiplier="100"
 dateTime="20250711;100000" quantity="-1" tradePrice="2" proceeds="200" ibCommission="-1.05"
 ibExecID="0001.01" ibOrderID="555" notes="O" levelOfDetail="EXECUTION" fifoPnlRealized="0"/>
<Trade accountId="U0000001" currency="USD" assetCategory="OPT" symbol="NVDA  250718P00170000"
 underlyingSymbol="NVDA" strike="170" expiry="20250718" putCall="P" multiplier="100"
 dateTime="20250718;162000" quantity="1" tradePrice="0" proceeds="0" ibCommission="0"
 ibExecID="" ibOrderID="" notes="C;Ep" levelOfDetail="EXECUTION" fifoPnlRealized="198.95"/>
<Trade accountId="U0000001" currency="USD" assetCategory="OPT" symbol="NVDA  250718P00170000"
 underlyingSymbol="NVDA" strike="170" expiry="20250718" putCall="P" multiplier="100"
 dateTime="20250711;100000" quantity="-1" tradePrice="2" proceeds="200" ibCommission="-1.05"
 ibExecID="" ibOrderID="555" notes="O" levelOfDetail="ORDER"/>
<Trade accountId="U0000001" currency="USD" assetCategory="CASH" symbol="USD.SGD"
 dateTime="20250711;100000" quantity="10" tradePrice="1.28" proceeds="-12.8" ibCommission="0"/>
</Trades>
<CashTransactions>
<CashTransaction type="Deposits/Withdrawals" currency="USD" amount="45000" dateTime="20250526"
 settleDate="20250526" description="Electronic Fund Transfer" symbol="" levelOfDetail="DETAIL"/>
<CashTransaction type="Dividends" currency="USD" amount="29.16" dateTime="20250613;202000"
 description="QDTE(US77926X3044) Cash Dividend" symbol="QDTE" levelOfDetail="DETAIL"/>
<CashTransaction type="Dividends" currency="USD" amount="29.16" dateTime="20250613"
 description="summary" symbol="QDTE" levelOfDetail="SUMMARY"/>
</CashTransactions>
<ConversionRates>
<ConversionRate reportDate="20250711" fromCurrency="USD" toCurrency="SGD" rate="1.28"/>
<ConversionRate reportDate="20250711" fromCurrency="EUR" toCurrency="SGD" rate="1.50"/>
</ConversionRates>
<CorporateActions>
<CorporateAction reportDate="20251118" dateTime="20251117;202500" description="OPEN(US6837121036) Spinoff"
 quantity="30" proceeds="0" symbol="OPENW" underlyingSymbol="OPEN"/>
</CorporateActions>
</FlexStatement></FlexStatements></FlexQueryResponse>"""


def _client(responses: list[str]) -> httpx.Client:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=queue.pop(0))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_retries_while_generation_is_in_progress() -> None:
    sleeps: list[float] = []
    text = fetch_statement("t", "q", client=_client([SEND_OK, IN_PROGRESS, STATEMENT]),
                           poll_interval=1.0, sleep=sleeps.append)
    assert "<FlexQueryResponse" in text and sleeps == [1.0]


def test_fetch_raises_on_a_hard_error() -> None:
    with pytest.raises(FlexError) as exc:
        fetch_statement("t", "q", client=_client([BAD_TOKEN]), sleep=lambda _: None)
    assert exc.value.code == "1012"


def test_fetch_times_out() -> None:
    ticks = iter([0.0, 0.0, 1000.0])
    with pytest.raises(FlexError) as exc:
        fetch_statement("t", "q", client=_client([SEND_OK, IN_PROGRESS, IN_PROGRESS]),
                        timeout=10, sleep=lambda _: None, clock=lambda: next(ticks))
    assert exc.value.code == "timeout"


def test_parse_trades_cash_fx_and_corporate_actions() -> None:
    st = parse_flex_xml(STATEMENT)
    assert st.account == "U0000001"
    assert len(st.executions) == 2  # ORDER-level duplicate and CASH row skipped
    opened = next(e for e in st.executions if e.quantity < 0)
    assert (opened.exec_id, opened.perm_id, opened.commission) == ("0001.01", 555, -1.05)
    assert opened.trade_time == datetime(2025, 7, 11, 14, 0, tzinfo=UTC)
    assert opened.contract.ident == "OPT:NVDA:20250718:P:170:USD"
    expired = next(e for e in st.executions if e.quantity > 0)
    assert (expired.exec_id, expired.codes, expired.source_kind) == (None, "C;Ep", "order")
    assert sorted(c.event_type for c in st.cash_events) == ["deposit", "dividend"]
    rates = {f.currency: f.usd_rate for f in st.fx_rates}
    assert rates["SGD"] == pytest.approx(1 / 1.28)
    assert rates["EUR"] == pytest.approx(1.50 / 1.28)
    assert st.corporate_actions[0].event_date == date(2025, 11, 18)


def test_pull_is_a_noop_when_unconfigured(monkeypatch) -> None:
    from src.common.config import get_config

    monkeypatch.setattr(get_config().secrets, "ibkr_flex_token", "")
    assert run_flex_pull() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ledger_flex.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ledger.flex'`.

- [ ] **Step 3: Write `src/ledger/flex.py`**

```python
"""IBKR Flex Web Service client + Flex XML parser (spec §5.2; revisions R1, R6).

Configure once in Client Portal (SETUP.md "Trade ledger"): an Activity Flex Query with Trades
(Execution level), Cash Transactions, Corporate Actions and Conversion Rates; XML; date format
yyyyMMdd, time HHmmss, separator ';'. Option Exercises/Assignments/Expirations is not read in v1 —
those arrive as Trades rows (R1); confirm with ``scripts.ledger_flex_pull --dry-run``.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from xml.etree import ElementTree

import httpx

from src.common.config import get_config
from src.common.schemas import (
    LedgerContract,
    LedgerImportResult,
    LedgerParseError,
    ParsedCashEvent,
    ParsedCorporateAction,
    ParsedExecution,
    ParsedFxRate,
    ParsedStatement,
)
from src.ledger.activity_csv import number_occurrences
from src.ledger.contracts import parse_et_timestamp, parse_ibkr_date, stock_contract
from src.ledger.ingest import ingest
from src.ledger.state import LEDGER_FLEX_LAST_RUN_KEY, LEDGER_FLEX_LAST_STATUS_KEY
from src.storage.system_settings import set_setting

log = logging.getLogger(__name__)

_BASE = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
_RETRY_CODES = frozenset({"1018", "1019"})
_CASH_TYPES = {
    "Dividends": "dividend",
    "Payment In Lieu Of Dividends": "dividend",
    "Withholding Tax": "withholding",
    "Deposits/Withdrawals": "deposit",
    "Broker Interest Received": "interest",
    "Broker Interest Paid": "interest",
    "Other Fees": "fee",
    "Commission Adjustments": "fee",
}


class FlexError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"Flex error {code}: {message}")
        self.code = code


def _response_error(text: str) -> tuple[str, str]:
    root = ElementTree.fromstring(text)
    return (root.findtext("ErrorCode") or "?").strip(), (root.findtext("ErrorMessage") or "").strip()


def fetch_statement(
    token: str,
    query_id: str,
    *,
    client: httpx.Client | None = None,
    poll_interval: float = 10.0,
    timeout: float = 600.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Request a statement and poll until IBKR has generated it. Returns the statement XML."""
    own = client is None
    http = client or httpx.Client(timeout=60.0, headers={"User-Agent": "ibkr-options-income/1.0"})
    try:
        r = http.get(f"{_BASE}/SendRequest", params={"t": token, "q": query_id, "v": "3"})
        r.raise_for_status()
        root = ElementTree.fromstring(r.text)
        if (root.findtext("Status") or "").strip() != "Success":
            raise FlexError(*_response_error(r.text))
        reference = (root.findtext("ReferenceCode") or "").strip()
        url = (root.findtext("Url") or "").strip() or f"{_BASE}/GetStatement"
        deadline = clock() + timeout
        while True:
            r = http.get(url, params={"t": token, "q": reference, "v": "3"})
            r.raise_for_status()
            if "<FlexQueryResponse" in r.text:
                return r.text
            code, message = _response_error(r.text)
            if code not in _RETRY_CODES:
                raise FlexError(code, message)
            if clock() >= deadline:
                raise FlexError("timeout", f"statement not ready after {timeout:.0f}s")
            sleep(poll_interval)
    finally:
        if own:
            http.close()


def _float(el: ElementTree.Element, attr: str, default: float | None = None) -> float:
    raw = (el.get(attr) or "").strip()
    if not raw:
        if default is None:
            raise ValueError(f"missing {attr}")
        return default
    return float(raw)


def _int_or_none(raw: str | None) -> int | None:
    raw = (raw or "").strip()
    return int(raw) if raw.lstrip("-").isdigit() and int(raw) != 0 else None


def _flex_trade(el: ElementTree.Element) -> ParsedExecution | None:
    category = el.get("assetCategory")
    if category not in ("STK", "OPT"):
        return None
    if el.get("levelOfDetail") not in (None, "", "EXECUTION"):
        return None
    currency = el.get("currency") or "USD"
    contract: LedgerContract
    if category == "OPT":
        right = el.get("putCall")
        contract = LedgerContract(
            underlying=el.get("underlyingSymbol") or (el.get("symbol") or "").split()[0],
            sec_type="OPT", currency=currency, right="P" if right == "P" else "C",
            strike=_float(el, "strike"), expiry=parse_ibkr_date(el.get("expiry") or ""),
            multiplier=_float(el, "multiplier", 100.0),
        )
    else:
        contract = stock_contract(el.get("symbol") or "", currency)
    exec_id = (el.get("ibExecID") or "").strip() or None
    realized = (el.get("fifoPnlRealized") or "").strip()
    return ParsedExecution(
        contract=contract,
        trade_time=parse_et_timestamp(el.get("dateTime") or el.get("tradeDate") or ""),
        quantity=_float(el, "quantity"), price=_float(el, "tradePrice"),
        proceeds=_float(el, "proceeds", 0.0), commission=_float(el, "ibCommission", 0.0),
        codes=(el.get("notes") or "").strip(), exec_id=exec_id,
        perm_id=_int_or_none(el.get("ibOrderID")), account=el.get("accountId"),
        ibkr_realized_pnl=float(realized) if realized else None,
        source_kind="exec" if exec_id else "order", raw=dict(el.attrib),
    )


def _flex_cash(el: ElementTree.Element) -> ParsedCashEvent | None:
    kind = _CASH_TYPES.get(el.get("type") or "")
    if kind is None or el.get("levelOfDetail") not in (None, "", "DETAIL"):
        return None
    amount = _float(el, "amount")
    if kind == "deposit" and amount < 0:
        kind = "withdrawal"
    when = (el.get("settleDate") if kind in ("deposit", "withdrawal") else None) or el.get("dateTime") or ""
    return ParsedCashEvent(
        event_type=kind,  # type: ignore[arg-type]
        event_date=parse_ibkr_date(when.split(";")[0]),
        currency=el.get("currency") or "USD", amount=amount,
        description=(el.get("description") or "").strip(),
        underlying=(el.get("symbol") or None) if kind in ("dividend", "withholding") else None,
    )


def _flex_fx(root: ElementTree.Element) -> list[ParsedFxRate]:
    by_day: dict[str, dict[str, tuple[str, float]]] = defaultdict(dict)
    for el in root.iter("ConversionRate"):
        day, frm, to, rate = el.get("reportDate"), el.get("fromCurrency"), el.get("toCurrency"), el.get("rate")
        if day and frm and to and rate:
            by_day[day][frm] = (to, float(rate))
    out: list[ParsedFxRate] = []
    for day, rates in by_day.items():
        if "USD" not in rates:
            continue
        base, usd_to_base = rates["USD"]
        d = parse_ibkr_date(day)
        out.append(ParsedFxRate(rate_date=d, currency=base, usd_rate=1.0 / usd_to_base))
        for currency, (_, rate) in rates.items():
            if currency not in ("USD", base):
                out.append(ParsedFxRate(rate_date=d, currency=currency, usd_rate=rate / usd_to_base))
    return out


def parse_flex_xml(text: str) -> ParsedStatement:
    root = ElementTree.fromstring(text)
    st = ParsedStatement()
    stmt = root.find(".//FlexStatement")
    if stmt is not None:
        st.account = stmt.get("accountId")
        st.period_start = parse_ibkr_date(stmt.get("fromDate") or "") if stmt.get("fromDate") else None
        st.period_end = parse_ibkr_date(stmt.get("toDate") or "") if stmt.get("toDate") else None
    for i, el in enumerate(root.iter("Trade"), start=1):
        try:
            e = _flex_trade(el)
            if e is not None:
                st.executions.append(e)
        except (ValueError, KeyError, TypeError) as exc:
            st.errors.append(LedgerParseError(line=i, section="Trades", message=str(exc)))
    for i, el in enumerate(root.iter("CashTransaction"), start=1):
        try:
            c = _flex_cash(el)
            if c is not None:
                st.cash_events.append(c)
        except (ValueError, KeyError, TypeError) as exc:
            st.errors.append(LedgerParseError(line=i, section="CashTransactions", message=str(exc)))
    for el in root.iter("CorporateAction"):
        try:
            st.corporate_actions.append(
                ParsedCorporateAction(
                    event_date=parse_ibkr_date((el.get("reportDate") or "").split(";")[0]),
                    underlying=el.get("underlyingSymbol") or el.get("symbol") or None,
                    description=(el.get("description") or "").strip(),
                    quantity=_float(el, "quantity", 0.0), proceeds=_float(el, "proceeds", 0.0),
                    raw=dict(el.attrib),
                )
            )
        except (ValueError, KeyError, TypeError) as exc:
            st.errors.append(LedgerParseError(line=0, section="CorporateActions", message=str(exc)))
    st.fx_rates = _flex_fx(root)
    number_occurrences(st)
    return st


def run_flex_pull(
    *, query_id: str | None = None, dry_run: bool = False
) -> LedgerImportResult | ParsedStatement | None:
    """Fetch, parse and ingest one Flex statement. None when Flex isn't configured."""
    cfg = get_config()
    token = cfg.secrets.ibkr_flex_token.strip()
    qid = (query_id or cfg.secrets.ibkr_flex_query_id).strip()
    if not token or not qid:
        log.warning("Flex pull skipped: IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID not set")
        return None
    now = datetime.now(UTC).isoformat()
    try:
        xml = fetch_statement(
            token, qid, poll_interval=cfg.ledger.flex_poll_interval_seconds,
            timeout=cfg.ledger.flex_poll_timeout_seconds,
        )
    except (FlexError, httpx.HTTPError) as exc:
        set_setting(LEDGER_FLEX_LAST_RUN_KEY, now)
        set_setting(LEDGER_FLEX_LAST_STATUS_KEY, f"failed: {exc}"[:200])
        raise
    statement = parse_flex_xml(xml)
    if dry_run:
        return statement
    result = ingest(statement, source="flex", filename=f"flex:{qid}")
    set_setting(LEDGER_FLEX_LAST_RUN_KEY, now)
    set_setting(
        LEDGER_FLEX_LAST_STATUS_KEY,
        "ok" if result.status == "ok" else f"failed: {result.reason}",
    )
    return result
```

- [ ] **Step 4: Write `scripts/ledger_flex_pull.py`**

```python
"""Pull the IBKR Flex statement into the trade ledger now.

    python -m scripts.ledger_flex_pull                    # the nightly query (IBKR_FLEX_QUERY_ID)
    python -m scripts.ledger_flex_pull --query-id 123456  # e.g. a one-off 365-day backfill query
    python -m scripts.ledger_flex_pull --dry-run          # fetch + parse, print counts, write nothing
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

from src.common.schemas import ParsedStatement
from src.ledger.flex import run_flex_pull
from src.storage.db import init_db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    init_db()
    result = run_flex_pull(query_id=args.query_id, dry_run=args.dry_run)
    if result is None:
        print("Flex is not configured: set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in .env")
        return 2
    if isinstance(result, ParsedStatement):
        codes = Counter(e.codes for e in result.executions)
        print(json.dumps({
            "account": result.account,
            "executions": len(result.executions),
            "with_exec_id": sum(1 for e in result.executions if e.exec_id),
            "codes": dict(codes),
            "cash_events": len(result.cash_events),
            "fx_rates": len(result.fx_rates),
            "errors": [e.model_dump() for e in result.errors[:20]],
        }, indent=2))
        return 0
    print(json.dumps(result.model_dump(), indent=2, default=str))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Add the EOD step**

In `src/orchestrator/eod_report.py`, insert directly above the line `    # 7. Send Telegram.`:

```python
    # 6b. Trade ledger: pull recent executions from the IBKR Flex Web Service (spec R6).
    #     Reporting only — a Flex failure never fails the EOD report.
    try:
        from src.ledger.flex import run_flex_pull

        await asyncio.to_thread(run_flex_pull)
    except Exception:
        logger.exception("EOD: trade-ledger Flex pull failed — continuing")
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_ledger_flex.py -v` and then the full `python -m pytest -q`.
Expected: all PASS. Existing EOD tests are unaffected, because `run_flex_pull` returns `None` when unconfigured.

- [ ] **Step 7: Commit**

```bash
git add src/ledger/flex.py scripts/ledger_flex_pull.py tests/test_ledger_flex.py
git add -p src/orchestrator/eod_report.py
git commit -m "feat(ledger): Flex Web Service pull (EOD step + CLI)"
```

---

### Task 11: Live executions — commission-report hook and sweep in the approval service

**Files:**
- Create: `src/ledger/live.py`
- Modify: `src/notify/approval_service.py` (create task after the drain task; cancel in `finally`)
- Test: `tests/test_ledger_live.py`

**Interfaces:**
- Consumes: `ingest`, `ledger_account` (Tasks 2, 4); `session_scope`.
- Produces:
  - `fill_to_execution(fill) -> ParsedExecution | None`
  - `ingest_fills(fills) -> int` (new rows)
  - `on_commission_report(trade, fill, report) -> None`
  - `attach_live_hook(ib) -> None`
  - `async live_sweep_loop(ib, *, interval_minutes=None) -> None`

`ib_async` field reference (`ib_async_documentation.md`):
- `Fill.contract` has `secType`, `symbol`, `lastTradeDateOrContractMonth`, `strike`, `right`, `multiplier`, `currency`.
- `Fill.execution` has `execId`, `time` (UTC datetime), `acctNumber`, `side` (`"BOT"`/`"SLD"`), `shares`, `price`, `permId`, `orderId`.
- `Fill.commissionReport` has `commission` (positive cost) and `realizedPNL`. IB uses `sys.float_info.max` to mean "unset".

- [ ] **Step 1: Write the failing test** — `tests/test_ledger_live.py`

```python
"""Live fills -> ledger (spec §5.3; Review Focus 3)."""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select


def fill(*, sec="OPT", side="SLD", shares=1, price=1.9, account="U0000001", exec_id="e1",
         perm=7, order_id=55, commission=1.05, realized=sys.float_info.max):
    return SimpleNamespace(
        contract=SimpleNamespace(secType=sec, symbol="NVDA", lastTradeDateOrContractMonth="20250718",
                                 strike=170.0, right="P", multiplier="100" if sec == "OPT" else "",
                                 currency="USD"),
        execution=SimpleNamespace(execId=exec_id, time=datetime(2025, 7, 11, 14, 0, tzinfo=UTC),
                                  acctNumber=account, side=side, shares=shares, price=price,
                                  permId=perm, orderId=order_id),
        commissionReport=SimpleNamespace(commission=commission, realizedPNL=realized),
    )


def test_fill_to_execution_option_sell() -> None:
    from src.ledger.live import fill_to_execution

    e = fill_to_execution(fill())
    assert e is not None
    assert (e.quantity, e.proceeds, e.commission, e.exec_id, e.perm_id) == (-1.0, 190.0, -1.05, "e1", 7)
    assert e.ibkr_realized_pnl is None and e.source_kind == "exec"
    assert e.contract.expiry == date(2025, 7, 18)


def test_fill_to_execution_skips_combos() -> None:
    from src.ledger.live import fill_to_execution

    assert fill_to_execution(fill(sec="BAG")) is None


def test_live_fills_are_skipped_until_an_import_locks_the_account(db) -> None:
    from src.ledger.live import ingest_fills
    from src.storage.models import BrokerExecutionRow, LedgerImportRunRow

    assert ingest_fills([fill()]) == 0
    with db() as s:
        assert s.scalars(select(BrokerExecutionRow)).first() is None
        assert s.scalars(select(LedgerImportRunRow)).first() is None


def test_paper_fills_never_reach_the_real_ledger(db) -> None:
    # Review Focus 3.
    from src.ledger.live import ingest_fills
    from src.ledger.state import lock_account
    from src.storage.models import LedgerImportRunRow

    with db() as s:
        lock_account(s, "U0000001")
    assert ingest_fills([fill(account="DU999")]) == 0
    with db() as s:
        assert s.scalars(select(LedgerImportRunRow)).first() is None


def test_matching_account_fill_is_ingested(db) -> None:
    from src.ledger.live import ingest_fills
    from src.ledger.state import lock_account
    from src.storage.models import BrokerExecutionRow

    with db() as s:
        lock_account(s, "U0000001")
    assert ingest_fills([fill()]) == 1
    assert ingest_fills([fill()]) == 0  # same execId again
    with db() as s:
        row = s.scalars(select(BrokerExecutionRow)).one()
        assert (row.source, row.exec_id) == ("live", "e1")


def test_hook_swallows_errors(monkeypatch) -> None:
    import src.ledger.live as live

    def boom(_fills):
        raise RuntimeError("db locked")

    monkeypatch.setattr(live, "ingest_fills", boom)
    live.on_commission_report(None, fill(), None)  # must not raise


def test_approval_service_wires_the_ledger_tasks() -> None:
    text = Path("src/notify/approval_service.py").read_text()
    assert "attach_live_hook(ib)" in text and "live_sweep_loop(ib)" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ledger_live.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ledger.live'`.

- [ ] **Step 3: Write `src/ledger/live.py`**

```python
"""Live executions from the exec process's IBKR connection into the ledger (spec §5.3).

``ib_async`` objects are converted to ParsedExecution here and nowhere else. Everything is
best-effort: a failure here is logged and never propagates into order handling. Fills only ever
land once a CSV/Flex import has locked the ledger account (R8), so a paper session can't
pollute — or claim — the real account's ledger.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC
from typing import Any

from src.common.config import get_config
from src.common.schemas import LedgerContract, ParsedExecution, ParsedStatement
from src.ledger.contracts import parse_ibkr_date, stock_contract
from src.ledger.ingest import ingest
from src.ledger.state import ledger_account
from src.storage.db import session_scope

log = logging.getLogger(__name__)

_UNSET = sys.float_info.max / 2  # IB reports "no value" as sys.float_info.max
_SWEEP_TIMEOUT_SECONDS = 30.0


def _value(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if abs(v) >= _UNSET else v


def fill_to_execution(fill: Any) -> ParsedExecution | None:
    c, ex, rep = fill.contract, fill.execution, getattr(fill, "commissionReport", None)
    sec = getattr(c, "secType", "")
    if sec not in ("OPT", "STK"):
        return None
    currency = c.currency or "USD"
    contract: LedgerContract
    if sec == "OPT":
        multiplier = float(c.multiplier or 100)
        contract = LedgerContract(
            underlying=c.symbol, sec_type="OPT", currency=currency,
            right="P" if str(c.right).upper().startswith("P") else "C", strike=float(c.strike),
            expiry=parse_ibkr_date(str(c.lastTradeDateOrContractMonth)[:8]), multiplier=multiplier,
        )
    else:
        multiplier = 1.0
        contract = stock_contract(c.symbol, currency)
    qty = float(ex.shares) * (1 if ex.side == "BOT" else -1)
    ts = ex.time if ex.time.tzinfo else ex.time.replace(tzinfo=UTC)
    commission = _value(getattr(rep, "commission", None)) if rep is not None else None
    return ParsedExecution(
        contract=contract, trade_time=ts, quantity=qty, price=float(ex.price),
        proceeds=-qty * float(ex.price) * multiplier,
        commission=-abs(commission) if commission else 0.0,
        exec_id=ex.execId, perm_id=int(ex.permId) or None, ib_order_id=int(ex.orderId) or None,
        account=ex.acctNumber or None,
        ibkr_realized_pnl=_value(getattr(rep, "realizedPNL", None)) if rep is not None else None,
        source_kind="exec",
    )


def ingest_fills(fills: list[Any]) -> int:
    """Ingest fills for the tracked account only. Returns new rows written."""
    with session_scope() as s:
        tracked = ledger_account(s)
    if tracked is None:
        return 0
    execs = [e for f in fills if (e := fill_to_execution(f)) is not None and e.account == tracked]
    if not execs:
        return 0
    result = ingest(ParsedStatement(account=tracked, executions=execs), source="live")
    return result.counts.get("new", 0) if result.status == "ok" else 0


def on_commission_report(trade: Any, fill: Any, report: Any) -> None:
    try:
        ingest_fills([fill])
    except Exception:
        log.exception("ledger live hook failed — ignored (never affects order handling)")


def attach_live_hook(ib: Any) -> None:
    """Subscribe to commission reports (they arrive after the fill, with the commission known)."""
    ib.commissionReportEvent += on_commission_report


async def live_sweep_loop(ib: Any, *, interval_minutes: float | None = None) -> None:
    """Every few minutes, ingest whatever reqExecutions returns (catches missed events)."""
    minutes = interval_minutes if interval_minutes is not None else get_config().ledger.live_sweep_minutes
    while True:
        await asyncio.sleep(minutes * 60)
        if ib is None or not ib.isConnected():
            continue
        try:
            fills = await asyncio.wait_for(ib.reqExecutionsAsync(), timeout=_SWEEP_TIMEOUT_SECONDS)
            new = ingest_fills(list(fills or []))
            if new:
                log.info("ledger sweep: %d new execution(s)", new)
        except Exception:
            log.warning("ledger sweep failed — will retry next cycle", exc_info=True)
```

- [ ] **Step 4: Wire it into `src/notify/approval_service.py`**

Directly after the block that creates `drain_task` and logs `"Command drain loop started (poll every %ss)"`, add:

```python
        # Trade ledger (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §5.3): live
        # executions + a periodic reqExecutions sweep. Ledger-table writes only; never touches
        # order handling, and skips everything until a CSV/Flex import has locked the account.
        from src.ledger.live import attach_live_hook, live_sweep_loop

        if ib is not None:
            attach_live_hook(ib)
        ledger_sweep_task = asyncio.create_task(live_sweep_loop(ib))
```

In the `finally:` block that cancels `drain_task`, add right after the drain-task cancellation:

```python
            ledger_sweep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ledger_sweep_task
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_ledger_live.py tests/test_web_fence.py -v`, then `python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/ledger/live.py tests/test_ledger_live.py
git add -p src/notify/approval_service.py
git commit -m "feat(ledger): live executions via commission-report hook + reqExecutions sweep"
```

---

### Task 12: Google Sheets mirror

**Files:**
- Modify: `pyproject.toml` (dependencies), `src/notify/approval_service.py` (mirror task)
- Create: `src/ledger/sheets_mirror.py`
- Test: `tests/test_ledger_sheets_mirror.py`

**Interfaces:**
- Consumes: `build_book`, `SHEET_HEADER`, `sheet_row`, `TICKER_HEADER`, `ticker_row`, `summary_rows` (Tasks 6–7); state keys (Task 2).
- Produces:
  - `LEDGER_TAB = "Ledger (auto)"`, `TICKERS_TAB = "Tickers (auto)"`, `SUMMARY_TAB = "Summary (auto)"`
  - `class SheetsWriter(Protocol)` with `write_tab(title, rows, *, outcome_column=None)`
  - `class GspreadWriter`
  - `mirror_configured() -> bool`
  - `sync_once(writer, book) -> None`
  - `sync_if_due(*, writer_factory=default_writer) -> bool`
  - `async sheets_mirror_loop(*, poll_seconds=15.0) -> None`

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`'s `dependencies` list, add `"gspread>=6.1",` and `"google-auth>=2.30",`. Then run `pip install -e .` (or `pip install "gspread>=6.1" "google-auth>=2.30"` in the venv).

- [ ] **Step 2: Write the failing test** — `tests/test_ledger_sheets_mirror.py`

```python
"""Google Sheet mirror: three (auto) tabs, full rewrite, generation-driven (spec §7)."""

from __future__ import annotations

import asyncio
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "ledger" / "activity_statement_sample.csv"


class FakeWriter:
    def __init__(self, fail: bool = False) -> None:
        self.tabs: dict[str, list[list[object]]] = {}
        self.fail = fail

    def write_tab(self, title, rows, *, outcome_column=None) -> None:
        if self.fail:
            raise RuntimeError("quota exceeded")
        self.tabs[title] = rows


def _seed():
    from src.ledger.activity_csv import parse_activity_csv
    from src.ledger.ingest import ingest

    ingest(parse_activity_csv(FIXTURE.read_text()), source="csv")


def test_sync_writes_three_tabs_in_sheet_layout(db) -> None:
    from src.ledger.sheets_mirror import LEDGER_TAB, SUMMARY_TAB, TICKERS_TAB, sync_if_due

    _seed()
    w = FakeWriter()
    assert sync_if_due(writer_factory=lambda: w) is True
    assert set(w.tabs) == {LEDGER_TAB, TICKERS_TAB, SUMMARY_TAB}
    assert w.tabs[LEDGER_TAB][0][:3] == ["Sell/Buy", "Put/Call", "Order Date"]
    assert len(w.tabs[LEDGER_TAB]) == 1 + 6


def test_nothing_to_do_when_generation_unchanged(db) -> None:
    from src.ledger.sheets_mirror import sync_if_due

    _seed()
    w = FakeWriter()
    assert sync_if_due(writer_factory=lambda: w) is True
    w.tabs.clear()
    assert sync_if_due(writer_factory=lambda: w) is False and w.tabs == {}


def test_failure_records_the_error_and_retries_later(db) -> None:
    from src.ledger.sheets_mirror import sync_if_due
    from src.ledger.state import LEDGER_SHEETS_LAST_ERROR_KEY, LEDGER_SYNCED_GENERATION_KEY, read_int_setting
    from src.storage.system_settings import get_setting

    _seed()
    assert sync_if_due(writer_factory=lambda: FakeWriter(fail=True)) is False
    assert "quota exceeded" in get_setting(LEDGER_SHEETS_LAST_ERROR_KEY)
    assert read_int_setting(LEDGER_SYNCED_GENERATION_KEY) == 0
    assert sync_if_due(writer_factory=lambda: FakeWriter()) is True
    assert get_setting(LEDGER_SHEETS_LAST_ERROR_KEY) == ""


def test_loop_exits_quietly_when_unconfigured(monkeypatch) -> None:
    from src.common.config import get_config
    from src.ledger.sheets_mirror import mirror_configured, sheets_mirror_loop

    monkeypatch.setattr(get_config().secrets, "google_sheets_credentials_path", "")
    assert mirror_configured() is False
    asyncio.run(asyncio.wait_for(sheets_mirror_loop(poll_seconds=0.01), timeout=1))


def test_approval_service_wires_the_mirror() -> None:
    assert "sheets_mirror_loop()" in Path("src/notify/approval_service.py").read_text()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_ledger_sheets_mirror.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ledger.sheets_mirror'`.

- [ ] **Step 4: Write `src/ledger/sheets_mirror.py`**

```python
"""One-way mirror of the ledger into the operator's Google Sheet (spec §7).

Writes three tabs it owns — "Ledger (auto)", "Tickers (auto)", "Summary (auto)" — as a full
rewrite each time, so corrections and outcome overrides always propagate. The operator's own
tabs are never read or written. Driven by the ledger generation counter (src/ledger/state.py):
any ingest or annotation bumps it; the mirror syncs when it is ahead of the last synced value,
at most once per ``ledger.sheets_min_interval_seconds``. Failures are recorded and retried; they
never block ingestion. Unrealized P&L is deliberately not mirrored (no live marks here).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from src.common.config import get_config
from src.common.schemas import LedgerBook
from src.ledger.contracts import ET
from src.ledger.state import (
    LEDGER_GENERATION_KEY,
    LEDGER_SHEETS_LAST_ERROR_KEY,
    LEDGER_SHEETS_LAST_SYNC_KEY,
    LEDGER_SYNCED_GENERATION_KEY,
    read_int_setting,
)
from src.reporting.trade_ledger import (
    SHEET_HEADER,
    TICKER_HEADER,
    build_book,
    sheet_row,
    summary_rows,
    ticker_row,
)
from src.storage.db import session_scope
from src.storage.system_settings import set_setting

log = logging.getLogger(__name__)

LEDGER_TAB = "Ledger (auto)"
TICKERS_TAB = "Tickers (auto)"
SUMMARY_TAB = "Summary (auto)"
_OUTCOME_COLUMN = SHEET_HEADER.index("Outcome")
_OUTCOME_COLOURS: dict[str, tuple[float, float, float]] = {
    "Expired": (0.85, 0.94, 0.83),
    "Bought back": (0.90, 0.95, 0.88),
    "Assigned": (0.96, 0.80, 0.80),
    "Called away": (1.00, 0.95, 0.80),
    "Rolled": (0.81, 0.89, 0.97),
    "Open": (0.93, 0.93, 0.93),
    "Pending": (0.93, 0.93, 0.93),
}


class SheetsWriter(Protocol):
    def write_tab(self, title: str, rows: list[list[Any]], *, outcome_column: int | None = None) -> None: ...


def _outcome_rules(sheet_id: int, column: int) -> list[dict[str, Any]]:
    return [
        {
            "addConditionalFormatRule": {
                "index": 0,
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 1,
                                "startColumnIndex": column, "endColumnIndex": column + 1}],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": label}]},
                        "format": {"backgroundColor": {"red": r, "green": g, "blue": b}},
                    },
                },
            }
        }
        for label, (r, g, b) in _OUTCOME_COLOURS.items()
    ]


class GspreadWriter:
    """The real writer. Needs the spreadsheet shared with the service account's email."""

    def __init__(self, credentials_path: str, sheet_id: str) -> None:
        import gspread

        self._spreadsheet = gspread.service_account(filename=credentials_path).open_by_key(sheet_id)

    def write_tab(self, title: str, rows: list[list[Any]], *, outcome_column: int | None = None) -> None:
        import gspread

        width = max(len(r) for r in rows)
        try:
            ws = self._spreadsheet.worksheet(title)
            created = False
        except gspread.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(title=title, rows=len(rows) + 50, cols=width)
            created = True
        ws.clear()
        ws.resize(rows=len(rows) + 50, cols=width)
        ws.update(values=rows, range_name="A1", value_input_option="USER_ENTERED")
        if created:
            ws.freeze(rows=1)
            if outcome_column is not None:
                self._spreadsheet.batch_update({"requests": _outcome_rules(ws.id, outcome_column)})


def mirror_configured() -> bool:
    s = get_config().secrets
    return bool(s.google_sheets_credentials_path.strip() and s.ledger_sheet_id.strip())


def default_writer() -> SheetsWriter | None:
    if not mirror_configured():
        return None
    s = get_config().secrets
    return GspreadWriter(s.google_sheets_credentials_path, s.ledger_sheet_id)


def sync_once(writer: SheetsWriter, book: LedgerBook) -> None:
    writer.write_tab(
        LEDGER_TAB, [SHEET_HEADER, *(sheet_row(t) for t in book.trades)], outcome_column=_OUTCOME_COLUMN
    )
    writer.write_tab(TICKERS_TAB, [TICKER_HEADER, *(ticker_row(t) for t in book.tickers)])
    writer.write_tab(
        SUMMARY_TAB, [*summary_rows(book.summary), ["Updated (UTC)", datetime.now(UTC).isoformat()]]
    )


def sync_if_due(*, writer_factory: Callable[[], SheetsWriter | None] = default_writer) -> bool:
    """Sync when the ledger generation is ahead of the last synced one. Returns True on a write."""
    generation = read_int_setting(LEDGER_GENERATION_KEY)
    if generation <= read_int_setting(LEDGER_SYNCED_GENERATION_KEY):
        return False
    try:
        writer = writer_factory()
        if writer is None:
            return False
        with session_scope() as s:
            book = build_book(s, today=datetime.now(ET).date(), snapshot=None)
        sync_once(writer, book)
    except Exception as exc:
        set_setting(LEDGER_SHEETS_LAST_ERROR_KEY, f"{type(exc).__name__}: {exc}"[:500])
        log.warning("Google Sheet mirror failed — will retry on the next change", exc_info=True)
        return False
    set_setting(LEDGER_SYNCED_GENERATION_KEY, str(generation))
    set_setting(LEDGER_SHEETS_LAST_SYNC_KEY, datetime.now(UTC).isoformat())
    set_setting(LEDGER_SHEETS_LAST_ERROR_KEY, "")
    return True


async def sheets_mirror_loop(*, poll_seconds: float = 15.0) -> None:
    if not mirror_configured():
        log.info("Google Sheet mirror disabled (GOOGLE_SHEETS_CREDENTIALS_PATH / LEDGER_SHEET_ID not set)")
        return
    min_interval = get_config().ledger.sheets_min_interval_seconds
    last_attempt = float("-inf")
    while True:
        await asyncio.sleep(poll_seconds)
        if time.monotonic() - last_attempt < min_interval:
            continue
        if read_int_setting(LEDGER_GENERATION_KEY) <= read_int_setting(LEDGER_SYNCED_GENERATION_KEY):
            continue
        last_attempt = time.monotonic()
        await asyncio.to_thread(sync_if_due)
```

- [ ] **Step 5: Wire the mirror into `src/notify/approval_service.py`**

Directly after `ledger_sweep_task = asyncio.create_task(live_sweep_loop(ib))` (Task 11), add:

```python
        from src.ledger.sheets_mirror import sheets_mirror_loop

        ledger_mirror_task = asyncio.create_task(sheets_mirror_loop())
```

In the `finally:` block, after the `ledger_sweep_task` cancellation, add:

```python
            ledger_mirror_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ledger_mirror_task
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_ledger_sheets_mirror.py -v`, then `python -m pytest -q && ruff check . && mypy src`.
Expected: all PASS. If mypy complains that `gspread` lacks stubs, add `[[tool.mypy.overrides]] module = ["gspread", "gspread.*"] ignore_missing_imports = true` to `pyproject.toml`, following any existing override style there.

- [ ] **Step 7: Commit**

```bash
git add src/ledger/sheets_mirror.py tests/test_ledger_sheets_mirror.py
git add -p pyproject.toml src/notify/approval_service.py
git commit -m "feat(ledger): Google Sheet mirror (three auto tabs, generation-driven)"
```

---

### Task 13: Web — ledger types, helpers, nav, Overview page

**Files:**
- Create:
  - `web/components/ledger/types.ts`
  - `web/components/ledger/format.ts`
  - `web/components/ledger/LedgerNav.tsx`
  - `web/components/ledger/OutcomePill.tsx`
  - `web/components/ledger/LedgerOverview.tsx`
  - `web/components/ledger/TickerTable.tsx`
  - `web/components/ledger/Charts.tsx`
  - `web/app/ledger/page.tsx`
- Modify: `web/components/shell/RailSection.tsx` (add `ledger: "/ledger"` to `HREF`)
- Test: `web/components/ledger/LedgerOverview.test.tsx`

**Interfaces:**
- Consumes: `GET /ledger/summary`, `GET /ledger/tickers` (Task 9).
- Produces:
  - Types `LedgerOutcome`, `LedgerClose`, `LedgerTrade`, `LedgerTicker`, `LedgerSummary`, `LedgerTickerDetail`, and the response types
  - Helpers `money(v, currency?)`, `pct(v)`, `rate(v)`, `signClass(v)`
  - Components `<LedgerNav/>`, `<OutcomePill outcome overridden?/>`, `<TickerTable tickers/>`, `<PnlCurve points/>`, `<MonthlyBars months/>`

- [ ] **Step 1: Write the failing test** — `web/components/ledger/LedgerOverview.test.tsx`

```tsx
import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithQuery } from "@/lib/test-query";
import { LedgerOverview } from "./LedgerOverview";
import type { LedgerSummary, LedgerTicker } from "./types";

vi.mock("next/navigation", () => ({ usePathname: () => "/ledger" }));

const ISO = new Date().toISOString();

function aSummary(over: Partial<LedgerSummary> = {}): LedgerSummary {
  return {
    total_realized_usd: 2575.84, interest_and_fees_usd: 0, contributed_usd: null,
    capital_utilised_usd: 17000, available_usd: null, unrealized_usd: null, win_rate: 0.75,
    n_trades: 6, n_open: 1, premium_this_month_usd: 401, months: [], curve: [],
    by_strategy: [], by_book: [], upcoming: [], fx_incomplete: false, orphan_closes: 0,
    unreviewed_corporate_actions: 0, marks_as_of: null, ...over,
  };
}

function aTicker(over: Partial<LedgerTicker> = {}): LedgerTicker {
  return {
    symbol: "AMZN", currency: "USD", option_premium_gross: 578, option_net_pnl: 575.86,
    stock_realized: 1999.98, dividends_net: 0, total_realized: 2575.84, unrealized: null,
    n_trades: 3, n_open: 0, n_closed: 3, win_rate: 1, avg_premium: 192.67, best_trade: 400,
    worst_trade: 175.86, annualised_return_pct: 42.1, shares_held: 0, broker_avg_cost: null,
    wheel_adjusted_basis: null, first_trade: "2025-06-25", last_trade: "2025-10-31", ...over,
  };
}

describe("LedgerOverview", () => {
  it("renders the headline tiles and says n/a for unknowns, never $0", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary() },
      "/ledger/tickers": { as_of: ISO, tickers: [aTicker()] },
    });
    const tiles = await screen.findByTestId("ledger-tiles");
    expect(within(tiles).getByText("$2,575.84")).toBeInTheDocument();
    expect(within(tiles).getByTestId("tile-contributed")).toHaveTextContent("n/a");
    expect(within(tiles).getByTestId("tile-available")).toHaveTextContent("n/a");
    expect(within(tiles).getByTestId("tile-win-rate")).toHaveTextContent("75%");
  });

  it("links each ticker to its drill-down page", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary() },
      "/ledger/tickers": { as_of: ISO, tickers: [aTicker()] },
    });
    const link = await screen.findByRole("link", { name: "AMZN" });
    expect(link).toHaveAttribute("href", "/ledger/ticker/AMZN");
  });

  it("breaks results down by strategy and by book", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary({
        by_strategy: [{ label: "CSP", n_closed: 4, realized_usd: 900, win_rate: 0.75 }],
        by_book: [{ label: "manual", n_closed: 4, realized_usd: 900, win_rate: 0.75 }],
      }) },
      "/ledger/tickers": { as_of: ISO, tickers: [] },
    });
    expect(await screen.findByTestId("buckets-strategy")).toHaveTextContent("CSP");
    expect(screen.getByTestId("buckets-book")).toHaveTextContent("manual");
  });

  it("warns about orphan closes and missing FX", async () => {
    renderWithQuery(<LedgerOverview />, {
      "/ledger/summary": { as_of: ISO, summary: aSummary({ orphan_closes: 2, fx_incomplete: true }) },
      "/ledger/tickers": { as_of: ISO, tickers: [] },
    });
    expect(await screen.findByText(/2 closing trades have no opening/)).toBeInTheDocument();
    expect(screen.getByText(/no FX rate yet/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run components/ledger/LedgerOverview.test.tsx`
Expected: FAIL with `Cannot find module './LedgerOverview'`.

- [ ] **Step 3: Create `web/components/ledger/types.ts`**

```ts
// Hand-mirrors the Ledger* models in src/common/schemas.py and src/api/models/ledger.py.
// Keep in step with those files when they change (these are not generated).

export type LedgerOutcome =
  | "Open" | "Pending" | "Expired" | "Assigned" | "Called away"
  | "Exercised" | "Bought back" | "Sold" | "Rolled";

export const OUTCOMES: LedgerOutcome[] = [
  "Open", "Pending", "Expired", "Assigned", "Called away", "Exercised", "Bought back", "Sold", "Rolled",
];

export type LedgerClose = {
  order_key: string; close_date: string; close_time: string; quantity: number;
  cash: number; commission: number; codes: string;
};

export type LedgerTrade = {
  order_key: string; underlying: string; currency: string; side: "Sell" | "Buy";
  right: "P" | "C"; strike: number; expiry: string; multiplier: number; lots: number;
  order_date: string; open_time: string; close_date: string | null; dte: number; days_held: number;
  premium: number; open_commission: number; closes: LedgerClose[]; outcome: LedgerOutcome;
  computed_outcome: LedgerOutcome; outcome_overridden: boolean; mixed_close: boolean;
  capital: number; pct_profit: number | null; net_pnl: number | null; return_pct: number | null;
  annualised_net_pct: number | null; stock_gain: number | null; book: "system" | "manual";
  rolled_from: string | null; rolled_to: string | null; ibkr_realized_pnl: number | null;
  exec_row_ids: number[]; notes: string; tags: string[]; exclude_from_stats: boolean;
};

export type LedgerTicker = {
  symbol: string; currency: string; option_premium_gross: number; option_net_pnl: number;
  stock_realized: number; dividends_net: number; total_realized: number; unrealized: number | null;
  n_trades: number; n_open: number; n_closed: number; win_rate: number | null;
  avg_premium: number | null; best_trade: number | null; worst_trade: number | null;
  annualised_return_pct: number | null; shares_held: number; broker_avg_cost: number | null;
  wheel_adjusted_basis: number | null; first_trade: string | null; last_trade: string | null;
};

export type LedgerMonth = { month: string; premium_usd: number; realized_usd: number };
export type LedgerCurvePoint = { point_date: string; cumulative_usd: number };
export type LedgerBucket = { label: string; n_closed: number; realized_usd: number; win_rate: number | null };

export type LedgerSummary = {
  total_realized_usd: number; interest_and_fees_usd: number; contributed_usd: number | null;
  capital_utilised_usd: number; available_usd: number | null; unrealized_usd: number | null;
  win_rate: number | null; n_trades: number; n_open: number; premium_this_month_usd: number;
  months: LedgerMonth[]; curve: LedgerCurvePoint[]; by_strategy: LedgerBucket[];
  by_book: LedgerBucket[]; upcoming: LedgerTrade[]; fx_incomplete: boolean; orphan_closes: number;
  unreviewed_corporate_actions: number; marks_as_of: string | null;
};

export type LedgerStockLot = {
  lot_key: string; underlying: string; currency: string; acquired_date: string;
  source: "bought" | "assigned" | "exercised"; quantity: number; remaining: number; cost_per_share: number;
};
export type LedgerStockDisposal = {
  lot_key: string; underlying: string; currency: string; disposal_date: string;
  quantity: number; price: number; realized: number; codes: string;
};
export type LedgerCashItem = {
  event_date: string; event_type: string; currency: string; amount: number;
  description: string; underlying: string | null;
};
export type LedgerBasisPoint = { point_date: string; label: string; basis_per_share: number };
export type LedgerTickerDetail = {
  ticker: LedgerTicker; trades: LedgerTrade[]; lots: LedgerStockLot[];
  disposals: LedgerStockDisposal[]; dividends: LedgerCashItem[]; basis_walk: LedgerBasisPoint[];
};

export type LedgerExecution = {
  id: number; source: string; source_kind: string; exec_id: string | null; trade_time: string;
  quantity: number; price: number; proceeds: number; commission: number; codes: string;
  book: string; superseded_by: number | null;
};
export type LedgerImportRun = {
  id: number; source: string; filename: string | null; started_at: string; finished_at: string | null;
  status: string; reason: string | null; counts: Record<string, number>;
  errors: { line?: number; section?: string; message?: string }[];
};
export type LedgerFeedStatus = {
  configured: boolean; last_run: string | null; last_status: string | null; last_error: string | null;
};
export type LedgerCorporateAction = {
  id: number; event_date: string; underlying: string | null; description: string;
  quantity: number; proceeds: number; reviewed: boolean;
};

export type LedgerSummaryResponse = { as_of: string; summary: LedgerSummary };
export type LedgerTickersResponse = { as_of: string; tickers: LedgerTicker[] };
export type LedgerTickerResponse = { as_of: string; detail: LedgerTickerDetail };
export type LedgerTradesResponse = {
  as_of: string; n: number; trades: LedgerTrade[]; filters: Record<string, string | null>;
};
export type LedgerTradeResponse = { as_of: string; trade: LedgerTrade; executions: LedgerExecution[] };
export type LedgerImportsResponse = {
  as_of: string; runs: LedgerImportRun[]; flex: LedgerFeedStatus; sheets: LedgerFeedStatus;
  corporate_actions: LedgerCorporateAction[];
};
```

- [ ] **Step 4: Create `web/components/ledger/format.ts`**

```ts
// Ledger number formatting. Unknown renders "n/a" - an unknown is never shown as zero.

export function money(v: number | null | undefined, currency = "USD"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  const abs = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const prefix = currency === "USD" ? "$" : `${currency} `;
  return `${v < 0 ? "-" : ""}${prefix}${abs}`;
}

export function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "n/a" : `${v.toFixed(2)}%`;
}

export function rate(v: number | null | undefined): string {
  return v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`;
}

export function signClass(v: number | null | undefined): string {
  if (v === null || v === undefined) return "text-unknown";
  if (v > 0) return "text-gain";
  if (v < 0) return "text-loss";
  return "text-content";
}
```

- [ ] **Step 5: Create `LedgerNav.tsx`, `OutcomePill.tsx`, `Charts.tsx`, `TickerTable.tsx`**

`web/components/ledger/LedgerNav.tsx`:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";

const TABS = [
  { href: "/ledger", label: "Overview" },
  { href: "/ledger/trades", label: "Trades" },
  { href: "/ledger/import", label: "Import" },
];

export function LedgerNav() {
  const path = usePathname();
  return (
    <nav aria-label="Ledger sections" className="flex gap-2 border-b border-border pb-2">
      {TABS.map((t) => (
        <Link
          key={t.href}
          href={t.href}
          aria-current={path === t.href ? "page" : undefined}
          className={clsx(
            "rounded-md px-3 py-1.5 text-sm",
            path === t.href ? "bg-elevated text-content" : "text-muted hover:text-content",
          )}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
```

`web/components/ledger/OutcomePill.tsx`:

```tsx
import clsx from "clsx";
import type { LedgerOutcome } from "./types";

// The label is always printed - colour is a second cue, never the only one.
const TONE: Record<LedgerOutcome, string> = {
  Expired: "bg-gain/15 text-gain",
  "Bought back": "bg-gain/10 text-gain",
  Sold: "bg-gain/10 text-gain",
  Assigned: "bg-loss/15 text-loss",
  "Called away": "bg-focus/15 text-focus",
  Rolled: "bg-focus/10 text-focus",
  Exercised: "bg-elevated text-content",
  Open: "bg-elevated text-muted",
  Pending: "bg-elevated text-unknown",
};

export function OutcomePill({ outcome, overridden = false }: { outcome: LedgerOutcome; overridden?: boolean }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs", TONE[outcome])}>
      {outcome}
      {overridden && <span title="Outcome set by you" aria-label="overridden">*</span>}
    </span>
  );
}
```

`web/components/ledger/Charts.tsx`:

```tsx
"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { money } from "./format";
import type { LedgerCurvePoint, LedgerMonth } from "./types";

// Charts never animate their data in (web/CLAUDE.md).

export function PnlCurve({ points }: { points: LedgerCurvePoint[] }) {
  if (points.length === 0) return <p className="text-sm text-muted">No closed trades yet.</p>;
  return (
    <figure className="h-64" aria-label="Cumulative realised P&L">
      <figcaption className="pb-2 text-sm text-muted">Cumulative realised P&L (USD)</figcaption>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points}>
          <CartesianGrid stroke="var(--color-border)" vertical={false} />
          <XAxis dataKey="point_date" tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
          <YAxis tick={{ fill: "var(--color-muted)", fontSize: 11 }} width={70} />
          <Tooltip formatter={(v) => money(Number(v))} />
          <Line type="stepAfter" dataKey="cumulative_usd" stroke="var(--color-gain)" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </figure>
  );
}

export function MonthlyBars({ months }: { months: LedgerMonth[] }) {
  if (months.length === 0) return <p className="text-sm text-muted">No premium collected yet.</p>;
  return (
    <figure className="h-64" aria-label="Monthly premium and realised P&L">
      <figcaption className="pb-2 text-sm text-muted">Premium collected vs realised, by month (USD)</figcaption>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={months}>
          <CartesianGrid stroke="var(--color-border)" vertical={false} />
          <XAxis dataKey="month" tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
          <YAxis tick={{ fill: "var(--color-muted)", fontSize: 11 }} width={70} />
          <Tooltip formatter={(v) => money(Number(v))} />
          <Bar dataKey="premium_usd" name="Premium" fill="var(--color-focus)" isAnimationActive={false} />
          <Bar dataKey="realized_usd" name="Realised" fill="var(--color-gain)" isAnimationActive={false} />
        </BarChart>
      </ResponsiveContainer>
    </figure>
  );
}
```

`web/components/ledger/TickerTable.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useState } from "react";
import { money, pct, rate, signClass } from "./format";
import type { LedgerTicker } from "./types";

type Col = { key: keyof LedgerTicker; label: string };
const COLS: Col[] = [
  { key: "total_realized", label: "Total realised" },
  { key: "option_net_pnl", label: "Options" },
  { key: "stock_realized", label: "Stock" },
  { key: "dividends_net", label: "Dividends" },
  { key: "unrealized", label: "Unrealised" },
  { key: "n_trades", label: "Trades" },
  { key: "win_rate", label: "Win rate" },
  { key: "annualised_return_pct", label: "Annualised" },
  { key: "shares_held", label: "Shares" },
  { key: "wheel_adjusted_basis", label: "Wheel basis" },
];

export function TickerTable({ tickers }: { tickers: LedgerTicker[] }) {
  const [sortKey, setSortKey] = useState<keyof LedgerTicker>("total_realized");
  const [desc, setDesc] = useState(true);
  if (tickers.length === 0) return <p className="text-sm text-muted">No tickers yet. Import a statement to begin.</p>;
  const rows = [...tickers].sort((a, b) => {
    const av = a[sortKey] ?? -Infinity;
    const bv = b[sortKey] ?? -Infinity;
    return (av < bv ? -1 : av > bv ? 1 : 0) * (desc ? -1 : 1);
  });
  function sortBy(k: keyof LedgerTicker) {
    if (k === sortKey) setDesc(!desc);
    else { setSortKey(k); setDesc(true); }
  }
  return (
    <div className="overflow-x-auto" data-testid="ticker-table">
      <table className="w-full text-sm">
        <thead className="text-left text-muted">
          <tr>
            <th className="py-2 pr-4">Ticker</th>
            {COLS.map((c) => (
              <th key={c.key} className="py-2 pr-4 text-right">
                <button type="button" onClick={() => sortBy(c.key)} aria-sort={sortKey === c.key ? (desc ? "descending" : "ascending") : "none"}>
                  {c.label}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.symbol} className="border-t border-border">
              <td className="py-2 pr-4 font-mono">
                <Link href={`/ledger/ticker/${t.symbol}`} className="text-content underline-offset-2 hover:underline">{t.symbol}</Link>
              </td>
              <td className={`tabular py-2 pr-4 text-right ${signClass(t.total_realized)}`}>{money(t.total_realized, t.currency)}</td>
              <td className="tabular py-2 pr-4 text-right">{money(t.option_net_pnl, t.currency)}</td>
              <td className="tabular py-2 pr-4 text-right">{money(t.stock_realized, t.currency)}</td>
              <td className="tabular py-2 pr-4 text-right">{money(t.dividends_net, t.currency)}</td>
              <td className={`tabular py-2 pr-4 text-right ${signClass(t.unrealized)}`}>{money(t.unrealized, t.currency)}</td>
              <td className="tabular py-2 pr-4 text-right">{t.n_trades}</td>
              <td className="tabular py-2 pr-4 text-right">{rate(t.win_rate)}</td>
              <td className="tabular py-2 pr-4 text-right">{pct(t.annualised_return_pct)}</td>
              <td className="tabular py-2 pr-4 text-right">{t.shares_held}</td>
              <td className="tabular py-2 pr-4 text-right">{money(t.wheel_adjusted_basis, t.currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 6: Create `LedgerOverview.tsx` and the page**

`web/components/ledger/LedgerOverview.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { MonthlyBars, PnlCurve } from "./Charts";
import { money, rate, signClass } from "./format";
import { LedgerNav } from "./LedgerNav";
import { OutcomePill } from "./OutcomePill";
import { TickerTable } from "./TickerTable";
import type { LedgerBucket, LedgerSummary, LedgerSummaryResponse, LedgerTickersResponse } from "./types";

function Tile({ id, label, value, tone }: { id: string; label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg bg-surface p-4" data-testid={`tile-${id}`}>
      <div className="text-xs text-muted">{label}</div>
      <div className={`tabular pt-1 text-lg ${tone ?? "text-content"}`}>{value}</div>
    </div>
  );
}

function Tiles({ s }: { s: LedgerSummary }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7" data-testid="ledger-tiles">
      <Tile id="total" label="Total profit" value={money(s.total_realized_usd)} tone={signClass(s.total_realized_usd)} />
      <Tile id="contributed" label="Contributed capital" value={money(s.contributed_usd)} />
      <Tile id="utilised" label="Capital utilised" value={money(s.capital_utilised_usd)} />
      <Tile id="available" label="Available capital" value={money(s.available_usd)} />
      <Tile id="unrealized" label="Unrealised" value={money(s.unrealized_usd)} tone={signClass(s.unrealized_usd)} />
      <Tile id="win-rate" label="Win rate" value={rate(s.win_rate)} />
      <Tile id="month" label="Premium this month" value={money(s.premium_this_month_usd)} />
    </div>
  );
}

function Buckets({ title, rows }: { title: string; rows: LedgerBucket[] }) {
  return (
    <section className="space-y-2" data-testid={`buckets-${title.split(" ")[1]}`}>
      <h2 className="text-sm font-medium text-content">{title}</h2>
      <table className="w-full text-sm">
        <thead className="text-left text-muted">
          <tr><th className="py-1 pr-4">Group</th><th className="py-1 pr-4 text-right">Closed</th><th className="py-1 pr-4 text-right">Realised</th><th className="py-1 pr-4 text-right">Win rate</th></tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr key={b.label} className="border-t border-border">
              <td className="py-1 pr-4">{b.label}</td>
              <td className="tabular py-1 pr-4 text-right">{b.n_closed}</td>
              <td className={`tabular py-1 pr-4 text-right ${signClass(b.realized_usd)}`}>{money(b.realized_usd)}</td>
              <td className="tabular py-1 pr-4 text-right">{rate(b.win_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function LedgerOverview() {
  const summary = useQuery({
    queryKey: ["ledger", "summary"],
    queryFn: () => apiFetch<LedgerSummaryResponse>("/ledger/summary"),
  });
  const tickers = useQuery({
    queryKey: ["ledger", "tickers"],
    queryFn: () => apiFetch<LedgerTickersResponse>("/ledger/tickers"),
  });

  return (
    <div className="space-y-6" data-testid="ledger-overview">
      <LedgerNav />
      {summary.isError && <p className="text-sm text-muted">Could not load the ledger.</p>}
      {!summary.data && !summary.isError && <p className="text-sm text-muted">Loading the ledger</p>}
      {summary.data && (
        <>
          <Tiles s={summary.data.summary} />
          {summary.data.summary.orphan_closes > 0 && (
            <p className="text-sm text-unknown">
              {summary.data.summary.orphan_closes} closing trades have no opening in the imported
              history. Import the earlier statement to complete them.
            </p>
          )}
          {summary.data.summary.fx_incomplete && (
            <p className="text-sm text-unknown">
              Some non-USD figures have no FX rate yet and are left out of USD totals. A Flex pull fills them in.
            </p>
          )}
          <div className="grid gap-6 lg:grid-cols-2">
            <PnlCurve points={summary.data.summary.curve} />
            <MonthlyBars months={summary.data.summary.months} />
          </div>
        </>
      )}
      {summary.data && (summary.data.summary.by_strategy.length > 0 || summary.data.summary.by_book.length > 0) && (
        <div className="grid gap-6 md:grid-cols-2">
          <Buckets title="By strategy" rows={summary.data.summary.by_strategy} />
          <Buckets title="By book (system vs your own trades)" rows={summary.data.summary.by_book} />
        </div>
      )}
      <section className="space-y-2">
        <h2 className="text-sm font-medium text-content">By ticker</h2>
        <TickerTable tickers={tickers.data?.tickers ?? []} />
      </section>
      {summary.data && summary.data.summary.upcoming.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-content">Upcoming expiries</h2>
          <ul className="space-y-1 text-sm">
            {summary.data.summary.upcoming.map((t) => (
              <li key={t.order_key} className="flex flex-wrap items-center gap-3">
                <span className="tabular text-muted">{t.expiry}</span>
                <Link href={`/ledger/ticker/${t.underlying}`} className="font-mono text-content hover:underline">{t.underlying}</Link>
                <span className="tabular">{t.side} {t.lots} x {t.strike}{t.right}</span>
                <OutcomePill outcome={t.outcome} overridden={t.outcome_overridden} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
```

`web/app/ledger/page.tsx`:

```tsx
import { LedgerOverview } from "@/components/ledger/LedgerOverview";

export default function LedgerPage() {
  return <LedgerOverview />;
}
```

In `web/components/shell/RailSection.tsx`, add `ledger: "/ledger",` to the `HREF` map after `pnl: "/pnl",`.

- [ ] **Step 7: Run the tests**

Run: `cd web && npx vitest run components/ledger` then `npm test`
Expected: all PASS. The recharts `ResponsiveContainer` warns about zero size under jsdom; that's harmless.

- [ ] **Step 8: Commit**

```bash
git add web/components/ledger web/app/ledger/page.tsx web/components/shell/RailSection.tsx
git commit -m "feat(web): ledger overview - tiles, P&L curve, monthly bars, ticker table"
```

---

### Task 14: Web — Trades page with filters, side panel and annotation editing

**Files:**
- Create: `web/components/ledger/TradesTable.tsx`, `web/components/ledger/TradePanel.tsx`, `web/components/ledger/TradesView.tsx`, `web/app/ledger/trades/page.tsx`
- Test: `web/components/ledger/TradesView.test.tsx`

**Interfaces:**
- Consumes:
  - `GET /ledger/trades?…` and `GET /ledger/trades/{key}` (Task 9)
  - `submitCommand(kind, payload)` and `useCommandStatus(id)` from `@/lib/commands` (existing)
  - Task 13 types and helpers
- Produces:
  - `<TradesTable trades onSelect/>`
  - `<TradePanel orderKey onClose/>`
  - `<TradesView fixedSymbol?/>`, reused by the ticker page in Task 15

- [ ] **Step 1: Write the failing test** — `web/components/ledger/TradesView.test.tsx`

```tsx
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { TradesView } from "./TradesView";
import type { LedgerTrade } from "./types";

vi.mock("next/navigation", () => ({ usePathname: () => "/ledger/trades" }));

const ISO = new Date().toISOString();

function aTrade(over: Partial<LedgerTrade> = {}): LedgerTrade {
  return {
    order_key: "0123456789abcdef", underlying: "NVDA", currency: "USD", side: "Sell", right: "P",
    strike: 138, expiry: "2025-06-27", multiplier: 100, lots: 1, order_date: "2025-06-17",
    open_time: ISO, close_date: "2025-06-27", dte: 10, days_held: 10, premium: 131,
    open_commission: -1.04, closes: [], outcome: "Bought back", computed_outcome: "Bought back",
    outcome_overridden: false, mixed_close: false, capital: 13800, pct_profit: 34.6467,
    net_pnl: 127, return_pct: 0.92, annualised_net_pct: 33.6, stock_gain: null, book: "manual",
    rolled_from: null, rolled_to: null, ibkr_realized_pnl: 127.69, exec_row_ids: [1, 2],
    notes: "", tags: [], exclude_from_stats: false, ...over,
  };
}

describe("TradesView", () => {
  it("renders the sheet columns and the sheet percentage", async () => {
    renderWithQuery(<TradesView />, { "/ledger/trades": { as_of: ISO, n: 1, trades: [aTrade()], filters: {} } });
    expect(await screen.findByText("34.65%")).toBeInTheDocument();
    for (const h of ["Sell/Buy", "Put/Call", "Order Date", "Expiry", "Ticker", "Lots", "Strike", "Premium", "Outcome", "DTE", "% Profit"]) {
      expect(screen.getByRole("columnheader", { name: h })).toBeInTheDocument();
    }
  });

  it("puts the filters into the request and the CSV link", async () => {
    renderWithQuery(<TradesView />, { "/ledger/trades": { as_of: ISO, n: 0, trades: [], filters: {} } });
    fireEvent.change(await screen.findByLabelText("Ticker"), { target: { value: "amzn" } });
    fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "Expired" } });
    await waitFor(() => {
      const paths = apiFetchMock.mock.calls.map((c) => String(c[0]));
      expect(paths.some((p) => p.includes("symbol=AMZN") && p.includes("outcome=Expired"))).toBe(true);
    });
    expect(screen.getByRole("link", { name: "Export CSV" }).getAttribute("href")).toContain("symbol=AMZN");
  });

  it("saves notes through a ledger_annotate command", async () => {
    renderWithQuery(<TradesView />, {
      "/ledger/trades/0123456789abcdef": { as_of: ISO, trade: aTrade(), executions: [] },
      "/ledger/trades": { as_of: ISO, n: 1, trades: [aTrade()], filters: {} },
      "/commands/77": { id: 77, kind: "ledger_annotate", status: "applied", result: {}, needs_confirmation: false, confirm_token: null, created_at: ISO, applied_at: ISO, as_of: ISO },
      "/commands": { id: 77, kind: "ledger_annotate", status: "pending", result: null, needs_confirmation: false, confirm_token: null, created_at: ISO, applied_at: null, as_of: ISO, created: true },
    });
    fireEvent.click(await screen.findByText("NVDA"));
    fireEvent.change(await screen.findByLabelText("Notes"), { target: { value: "near-zero buyback" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const post = apiFetchMock.mock.calls.find((c) => c[0] === "/commands");
      expect(post).toBeTruthy();
      const body = JSON.parse((post![1] as RequestInit).body as string);
      expect(body).toMatchObject({ kind: "ledger_annotate", payload: { order_key: "0123456789abcdef", notes: "near-zero buyback" } });
    });
    expect(await screen.findByText("Saved")).toBeInTheDocument();
  });
});
```

`renderWithQuery` matches the longest exact key first and then falls back to prefix matching. That's why `/ledger/trades/0123…` and `/commands/77` are listed before their shorter prefixes. If the prefix order in `web/lib/test-query.tsx` differs, order the keys so that each exact path appears.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run components/ledger/TradesView.test.tsx`
Expected: FAIL with `Cannot find module './TradesView'`.

- [ ] **Step 3: Create `TradesTable.tsx`**

```tsx
"use client";

import { money, pct, signClass } from "./format";
import { OutcomePill } from "./OutcomePill";
import type { LedgerTrade } from "./types";

const HEADERS = [
  "Sell/Buy", "Put/Call", "Order Date", "Expiry", "Ticker", "Lots", "Strike", "Premium",
  "Outcome", "Stock gain", "DTE", "% Profit", "Net P&L", "Closed", "Book", "Notes",
];

export function TradesTable({ trades, onSelect }: { trades: LedgerTrade[]; onSelect: (key: string) => void }) {
  if (trades.length === 0) return <p className="text-sm text-muted">No trades match the current filters.</p>;
  return (
    <div className="overflow-x-auto" data-testid="trades-table">
      <table className="w-full text-sm">
        <thead className="text-left text-muted">
          <tr>{HEADERS.map((h) => <th key={h} scope="col" className="whitespace-nowrap py-2 pr-4">{h}</th>)}</tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr
              key={t.order_key}
              onClick={() => onSelect(t.order_key)}
              className="cursor-pointer border-t border-border hover:bg-elevated"
            >
              <td className="py-2 pr-4">{t.side}</td>
              <td className="py-2 pr-4">{t.right === "P" ? "Put" : "Call"}</td>
              <td className="tabular py-2 pr-4">{t.order_date}</td>
              <td className="tabular py-2 pr-4">{t.expiry}</td>
              <td className="py-2 pr-4 font-mono">{t.underlying}</td>
              <td className="tabular py-2 pr-4 text-right">{t.lots}</td>
              <td className="tabular py-2 pr-4 text-right">{t.strike}</td>
              <td className={`tabular py-2 pr-4 text-right ${signClass(t.premium)}`}>{money(t.premium, t.currency)}</td>
              <td className="py-2 pr-4"><OutcomePill outcome={t.outcome} overridden={t.outcome_overridden} /></td>
              <td className="tabular py-2 pr-4 text-right">{t.stock_gain === null ? "" : money(t.stock_gain, t.currency)}</td>
              <td className="tabular py-2 pr-4 text-right">{t.dte}</td>
              <td className="tabular py-2 pr-4 text-right">{pct(t.pct_profit)}</td>
              <td className={`tabular py-2 pr-4 text-right ${signClass(t.net_pnl)}`}>{money(t.net_pnl, t.currency)}</td>
              <td className="tabular py-2 pr-4">{t.close_date ?? ""}</td>
              <td className="py-2 pr-4 text-muted">{t.book}</td>
              <td className="max-w-[16rem] truncate py-2 pr-4 text-muted">{t.notes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Create `TradePanel.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { submitCommand, useCommandStatus } from "@/lib/commands";
import { money, pct } from "./format";
import { OutcomePill } from "./OutcomePill";
import { OUTCOMES, type LedgerTradeResponse } from "./types";

export function TradePanel({ orderKey, onClose }: { orderKey: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["ledger", "trade", orderKey],
    queryFn: () => apiFetch<LedgerTradeResponse>(`/ledger/trades/${orderKey}`),
  });
  const [notes, setNotes] = useState("");
  const [tags, setTags] = useState("");
  const [override, setOverride] = useState("");
  const [exclude, setExclude] = useState(false);
  const [commandId, setCommandId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const status = useCommandStatus(commandId);

  useEffect(() => {
    if (!data) return;
    setNotes(data.trade.notes);
    setTags(data.trade.tags.join(", "));
    setOverride(data.trade.outcome_overridden ? data.trade.outcome : "");
    setExclude(data.trade.exclude_from_stats);
  }, [data]);

  useEffect(() => {
    if (status.data?.status === "applied") void qc.invalidateQueries({ queryKey: ["ledger"] });
  }, [status.data?.status, qc]);

  async function save() {
    setError(null);
    try {
      const r = await submitCommand("ledger_annotate", {
        order_key: orderKey,
        notes,
        tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        outcome_override: override,
        exclude_from_stats: exclude,
      });
      setCommandId(r.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    }
  }

  const state = status.data?.status;
  return (
    <aside className="fixed inset-y-0 right-0 z-20 w-full max-w-md space-y-4 overflow-y-auto bg-surface p-5 shadow-lg" aria-label="Trade detail">
      <div className="flex items-start justify-between">
        <h2 className="text-base text-content">Trade</h2>
        <button type="button" onClick={onClose} className="text-sm text-muted hover:text-content">Close</button>
      </div>
      {!data && <p className="text-sm text-muted">Loading</p>}
      {data && (
        <>
          <div className="space-y-1 text-sm">
            <div className="font-mono text-content">
              {data.trade.side} {data.trade.lots} x {data.trade.underlying} {data.trade.expiry} {data.trade.strike}{data.trade.right}
            </div>
            <OutcomePill outcome={data.trade.outcome} overridden={data.trade.outcome_overridden} />
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 pt-2 text-muted">
              <dt>Premium</dt><dd className="tabular text-content">{money(data.trade.premium, data.trade.currency)}</dd>
              <dt>Net P&L</dt><dd className="tabular text-content">{money(data.trade.net_pnl, data.trade.currency)}</dd>
              <dt>% Profit (sheet)</dt><dd className="tabular text-content">{pct(data.trade.pct_profit)}</dd>
              <dt>Annualised net</dt><dd className="tabular text-content">{pct(data.trade.annualised_net_pct)}</dd>
              <dt>IBKR realised</dt><dd className="tabular text-content">{money(data.trade.ibkr_realized_pnl, data.trade.currency)}</dd>
              {data.trade.rolled_from && (<><dt>Rolled from</dt><dd className="font-mono text-content">{data.trade.rolled_from}</dd></>)}
              {data.trade.rolled_to && (<><dt>Rolled to</dt><dd className="font-mono text-content">{data.trade.rolled_to}</dd></>)}
            </dl>
          </div>
          <section className="space-y-1">
            <h3 className="text-sm text-content">Executions</h3>
            <ul className="space-y-1 text-xs text-muted">
              {data.executions.map((e) => (
                <li key={e.id} className="tabular">
                  {e.trade_time.slice(0, 19).replace("T", " ")} {e.quantity} @ {e.price} {e.codes} ({e.source}
                  {e.superseded_by ? ", superseded" : ""})
                </li>
              ))}
            </ul>
          </section>
          <section className="space-y-3">
            <label className="block text-sm">
              <span className="text-muted">Notes</span>
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className="mt-1 w-full rounded bg-elevated p-2 text-content" />
            </label>
            <label className="block text-sm">
              <span className="text-muted">Tags (comma separated)</span>
              <input value={tags} onChange={(e) => setTags(e.target.value)} className="mt-1 w-full rounded bg-elevated p-2 text-content" />
            </label>
            <label className="block text-sm">
              <span className="text-muted">Outcome override</span>
              <select value={override} onChange={(e) => setOverride(e.target.value)} className="mt-1 w-full rounded bg-elevated p-2 text-content">
                <option value="">Use computed ({data.trade.computed_outcome})</option>
                {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm text-muted">
              <input type="checkbox" checked={exclude} onChange={(e) => setExclude(e.target.checked)} />
              Exclude from win rate and averages (still counted in money totals)
            </label>
            <div className="flex items-center gap-3">
              <button type="button" onClick={save} className="rounded-md bg-elevated px-3 py-1.5 text-sm text-content hover:bg-focus/20">Save</button>
              {state === "pending" && <span className="text-sm text-muted">Saving</span>}
              {state === "applied" && <span className="text-sm text-gain">Saved</span>}
              {state === "failed" && <span className="text-sm text-loss">Not saved: {String(status.data?.result?.reason ?? "error")}</span>}
              {error && <span className="text-sm text-loss">{error}</span>}
            </div>
          </section>
        </>
      )}
    </aside>
  );
}
```

- [ ] **Step 5: Create `TradesView.tsx` and the page**

```tsx
"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { LedgerNav } from "./LedgerNav";
import { TradePanel } from "./TradePanel";
import { TradesTable } from "./TradesTable";
import { OUTCOMES, type LedgerTradesResponse } from "./types";

type Filters = { symbol: string; right: string; outcome: string; book: string; tag: string; since: string; until: string; sort: string };
const EMPTY: Filters = { symbol: "", right: "", outcome: "", book: "", tag: "", since: "", until: "", sort: "-order_date" };

/**
 * The operator's sheet as a filterable table. One composed query string drives both the
 * fetch and the CSV export link, so the export always carries the filters on screen.
 * `fixedSymbol` pins the ticker (the drill-down page) and hides the nav and ticker filter.
 */
export function TradesView({ fixedSymbol }: { fixedSymbol?: string }) {
  const [f, setF] = useState<Filters>(EMPTY);
  const [selected, setSelected] = useState<string | null>(null);
  const qs = useMemo(() => {
    const p = new URLSearchParams();
    const symbol = fixedSymbol ?? f.symbol.trim().toUpperCase();
    if (symbol) p.set("symbol", symbol);
    for (const k of ["right", "outcome", "book", "tag", "since", "until"] as const) if (f[k]) p.set(k, f[k]);
    p.set("sort", f.sort);
    return p.toString();
  }, [f, fixedSymbol]);
  const { data, isError } = useQuery({
    queryKey: ["ledger", "trades", qs],
    queryFn: () => apiFetch<LedgerTradesResponse>(`/ledger/trades?${qs}`),
  });
  const set = (k: keyof Filters) => (e: { target: { value: string } }) => setF((prev) => ({ ...prev, [k]: e.target.value }));
  const field = "rounded bg-elevated px-2 py-1 text-sm text-content";

  return (
    <div className="space-y-4" data-testid="trades-view">
      {!fixedSymbol && <LedgerNav />}
      <div className="flex flex-wrap items-end gap-3">
        {!fixedSymbol && (
          <label className="text-xs text-muted">Ticker<input aria-label="Ticker" value={f.symbol} onChange={set("symbol")} className={`${field} ml-2 w-24`} /></label>
        )}
        <label className="text-xs text-muted">Put/Call
          <select aria-label="Put/Call" value={f.right} onChange={set("right")} className={`${field} ml-2`}>
            <option value="">All</option><option value="P">Put</option><option value="C">Call</option>
          </select>
        </label>
        <label className="text-xs text-muted">Outcome
          <select aria-label="Outcome" value={f.outcome} onChange={set("outcome")} className={`${field} ml-2`}>
            <option value="">All</option>
            {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted">Book
          <select aria-label="Book" value={f.book} onChange={set("book")} className={`${field} ml-2`}>
            <option value="">All</option><option value="system">System</option><option value="manual">Manual</option>
          </select>
        </label>
        <label className="text-xs text-muted">Tag<input aria-label="Tag" value={f.tag} onChange={set("tag")} className={`${field} ml-2 w-24`} /></label>
        <label className="text-xs text-muted">From<input aria-label="From" type="date" value={f.since} onChange={set("since")} className={`${field} ml-2`} /></label>
        <label className="text-xs text-muted">To<input aria-label="To" type="date" value={f.until} onChange={set("until")} className={`${field} ml-2`} /></label>
        <label className="text-xs text-muted">Sort
          <select aria-label="Sort" value={f.sort} onChange={set("sort")} className={`${field} ml-2`}>
            <option value="-order_date">Newest first</option><option value="order_date">Oldest first</option>
            <option value="-pct_profit">% Profit high to low</option><option value="-net_pnl">Net P&L high to low</option>
            <option value="net_pnl">Net P&L low to high</option><option value="expiry">Expiry soonest</option>
          </select>
        </label>
        <a href={`/api/ledger/trades.csv?${qs}`} className="ml-auto text-sm text-muted underline-offset-2 hover:text-content hover:underline">Export CSV</a>
      </div>
      {isError && <p className="text-sm text-muted">Could not load trades.</p>}
      {data && <p className="text-xs text-muted">{data.n} trades</p>}
      {data && <TradesTable trades={data.trades} onSelect={setSelected} />}
      {selected && <TradePanel orderKey={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
```

`web/app/ledger/trades/page.tsx`:

```tsx
import { TradesView } from "@/components/ledger/TradesView";

export default function LedgerTradesPage() {
  return <TradesView />;
}
```

`submitCommand` posts to `/commands` and `useCommandStatus` polls `/commands/{id}`; confirm both by reading `web/lib/commands.ts`. If `useCommandStatus(null)` doesn't disable itself, guard it the same way other callers in `web/components/options/` do.

- [ ] **Step 6: Run the tests**

Run: `cd web && npx vitest run components/ledger` then `npm test`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add web/components/ledger/TradesTable.tsx web/components/ledger/TradePanel.tsx web/components/ledger/TradesView.tsx web/components/ledger/TradesView.test.tsx web/app/ledger/trades/page.tsx
git commit -m "feat(web): ledger trades table with filters, CSV export, trade panel + annotations"
```

---

### Task 15: Web — Ticker drill-down page

**Files:**
- Create: `web/components/ledger/TickerView.tsx`, `web/app/ledger/ticker/[symbol]/page.tsx`
- Test: `web/components/ledger/TickerView.test.tsx`

**Interfaces:**
- Consumes: `GET /ledger/tickers/{symbol}` (Task 9); `<TradesView fixedSymbol/>` (Task 14); Task 13 helpers.
- Produces: `<TickerView symbol/>`.

- [ ] **Step 1: Write the failing test** — `web/components/ledger/TickerView.test.tsx`

```tsx
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { TickerView } from "./TickerView";

vi.mock("next/navigation", () => ({ usePathname: () => "/ledger/ticker/AMZN" }));

const ISO = new Date().toISOString();
const DETAIL = {
  ticker: {
    symbol: "AMZN", currency: "USD", option_premium_gross: 578, option_net_pnl: 575.86, stock_realized: 0,
    dividends_net: 0, total_realized: 575.86, unrealized: null, n_trades: 2, n_open: 1, n_closed: 1,
    win_rate: 1, avg_premium: 177, best_trade: 175.86, worst_trade: 175.86, annualised_return_pct: 40,
    shares_held: 100, broker_avg_cost: 215, wheel_adjusted_basis: 209.2414, first_trade: "2025-10-03", last_trade: "2025-10-20",
  },
  trades: [], lots: [{ lot_key: "k", underlying: "AMZN", currency: "USD", acquired_date: "2025-10-10", source: "assigned", quantity: 100, remaining: 100, cost_per_share: 215 }],
  disposals: [], dividends: [],
  basis_walk: [
    { point_date: "2025-10-10", label: "Shares acquired", basis_per_share: 215 },
    { point_date: "2025-10-20", label: "Sell 235C Open", basis_per_share: 209.2414 },
  ],
};

describe("TickerView", () => {
  it("shows broker cost and wheel-adjusted basis side by side", async () => {
    renderWithQuery(<TickerView symbol="amzn" />, {
      "/ledger/tickers/AMZN": { as_of: ISO, detail: DETAIL },
      "/ledger/trades": { as_of: ISO, n: 0, trades: [], filters: {} },
    });
    expect(await screen.findByTestId("tile-broker-cost")).toHaveTextContent("$215.00");
    expect(screen.getByTestId("tile-wheel-basis")).toHaveTextContent("$209.24");
    expect(screen.getByText("assigned")).toBeInTheDocument();
    expect(screen.getByText("Sell 235C Open")).toBeInTheDocument();
  });

  it("says so when the ticker has no history", async () => {
    // Set the 404 BEFORE rendering: renderWithQuery would install its own map, and the
    // query fires during render's act() flush.
    apiFetchMock.mockImplementation(async () => { throw new ApiError(404, "No ledger history"); });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><TickerView symbol="ZZZZ" /></QueryClientProvider>);
    expect(await screen.findByText(/No ledger history for ZZZZ/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run components/ledger/TickerView.test.tsx`
Expected: FAIL with `Cannot find module './TickerView'`.

- [ ] **Step 3: Create `TickerView.tsx`**

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ApiError, apiFetch } from "@/lib/api";
import { money, pct, rate, signClass } from "./format";
import { LedgerNav } from "./LedgerNav";
import { TradesView } from "./TradesView";
import type { LedgerTickerResponse } from "./types";

function Tile({ id, label, value, tone }: { id: string; label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg bg-surface p-4" data-testid={`tile-${id}`}>
      <div className="text-xs text-muted">{label}</div>
      <div className={`tabular pt-1 text-lg ${tone ?? "text-content"}`}>{value}</div>
    </div>
  );
}

export function TickerView({ symbol }: { symbol: string }) {
  const upper = symbol.toUpperCase();
  const { data, error } = useQuery({
    queryKey: ["ledger", "ticker", upper],
    queryFn: () => apiFetch<LedgerTickerResponse>(`/ledger/tickers/${upper}`),
    retry: false,
  });

  if (error instanceof ApiError && error.status === 404) {
    return (<div className="space-y-4"><LedgerNav /><p className="text-sm text-muted">No ledger history for {upper}.</p></div>);
  }
  if (error) return <p className="text-sm text-muted">Could not load {upper}.</p>;
  if (!data) return <p className="text-sm text-muted">Loading {upper}</p>;

  const d = data.detail;
  const t = d.ticker;
  return (
    <div className="space-y-6" data-testid="ticker-view">
      <LedgerNav />
      <h1 className="font-mono text-xl text-content">{t.symbol}</h1>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-8">
        <Tile id="total" label="Total realised" value={money(t.total_realized, t.currency)} tone={signClass(t.total_realized)} />
        <Tile id="options" label="Options net" value={money(t.option_net_pnl, t.currency)} />
        <Tile id="stock" label="Stock realised" value={money(t.stock_realized, t.currency)} />
        <Tile id="dividends" label="Dividends net" value={money(t.dividends_net, t.currency)} />
        <Tile id="unrealized" label="Unrealised" value={money(t.unrealized, t.currency)} tone={signClass(t.unrealized)} />
        <Tile id="win-rate" label="Win rate" value={rate(t.win_rate)} />
        <Tile id="broker-cost" label="Broker avg cost" value={money(t.broker_avg_cost, t.currency)} />
        <Tile id="wheel-basis" label="Wheel-adjusted basis" value={money(t.wheel_adjusted_basis, t.currency)} />
      </div>
      <p className="text-xs text-muted">
        {t.n_trades} trades, {t.n_open} open. Annualised return on capital-days {pct(t.annualised_return_pct)}. Shares held {t.shares_held}.
      </p>

      {d.basis_walk.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm text-content">Cost-basis walk</h2>
          <figure className="h-56" aria-label="Wheel-adjusted cost basis per share">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={d.basis_walk}>
                <XAxis dataKey="point_date" tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
                <YAxis domain={["auto", "auto"]} tick={{ fill: "var(--color-muted)", fontSize: 11 }} width={60} />
                <Tooltip formatter={(v) => money(Number(v), t.currency)} labelFormatter={(_, p) => p?.[0]?.payload?.label ?? ""} />
                <Line type="stepAfter" dataKey="basis_per_share" stroke="var(--color-focus)" isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </figure>
          <ol className="space-y-1 text-xs text-muted">
            {d.basis_walk.map((p, i) => (
              <li key={i} className="tabular">{p.point_date} {p.label}: {money(p.basis_per_share, t.currency)}</li>
            ))}
          </ol>
        </section>
      )}

      {d.lots.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm text-content">Share lots</h2>
          <table className="w-full text-sm">
            <thead className="text-left text-muted"><tr><th className="py-1 pr-4">Acquired</th><th className="py-1 pr-4">How</th><th className="py-1 pr-4 text-right">Qty</th><th className="py-1 pr-4 text-right">Remaining</th><th className="py-1 pr-4 text-right">Cost/share</th></tr></thead>
            <tbody>
              {d.lots.map((l) => (
                <tr key={l.lot_key} className="border-t border-border">
                  <td className="tabular py-1 pr-4">{l.acquired_date}</td><td className="py-1 pr-4">{l.source}</td>
                  <td className="tabular py-1 pr-4 text-right">{l.quantity}</td><td className="tabular py-1 pr-4 text-right">{l.remaining}</td>
                  <td className="tabular py-1 pr-4 text-right">{money(l.cost_per_share, l.currency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {d.dividends.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm text-content">Dividends and withholding</h2>
          <ul className="space-y-1 text-sm">
            {d.dividends.map((c, i) => (
              <li key={i} className="tabular"><span className="text-muted">{c.event_date}</span> <span className={signClass(c.amount)}>{money(c.amount, c.currency)}</span> <span className="text-muted">{c.event_type}</span></li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm text-content">Every trade</h2>
        <TradesView fixedSymbol={upper} />
      </section>
    </div>
  );
}
```

`web/app/ledger/ticker/[symbol]/page.tsx`:

```tsx
"use client";

import { use } from "react";
import { TickerView } from "@/components/ledger/TickerView";

export default function LedgerTickerPage({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  return <TickerView symbol={symbol} />;
}
```

- [ ] **Step 4: Run the tests**

Run: `cd web && npx vitest run components/ledger` then `npm test`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/ledger/TickerView.tsx web/components/ledger/TickerView.test.tsx "web/app/ledger/ticker/[symbol]/page.tsx"
git commit -m "feat(web): ledger ticker drill-down - basis walk, lots, dividends, every trade"
```

---

### Task 16: Web — Import page

**Files:**
- Create: `web/components/ledger/ImportView.tsx`, `web/app/ledger/import/page.tsx`
- Test: `web/components/ledger/ImportView.test.tsx`

**Interfaces:**
- Consumes: `GET /ledger/imports` (Task 9); `submitCommand`/`useCommandStatus`; commands `ledger_import` and `ledger_ca_reviewed` (Task 8).
- Produces: `<ImportView/>`.

- [ ] **Step 1: Write the failing test** — `web/components/ledger/ImportView.test.tsx`

```tsx
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
import { ImportView } from "./ImportView";

vi.mock("next/navigation", () => ({ usePathname: () => "/ledger/import" }));

const ISO = new Date().toISOString();
const IMPORTS = {
  as_of: ISO,
  runs: [{ id: 1, source: "csv", filename: "stmt.csv", started_at: ISO, finished_at: ISO, status: "ok", reason: null, counts: { new: 15, duplicate: 0 }, errors: [] }],
  flex: { configured: false, last_run: null, last_status: null, last_error: null },
  sheets: { configured: true, last_run: ISO, last_status: null, last_error: null },
  corporate_actions: [{ id: 4, event_date: "2025-11-18", underlying: "OPEN", description: "Spinoff OPENW", quantity: 30, proceeds: 0, reviewed: false }],
};
const PENDING = { id: 9, kind: "ledger_import", status: "pending", result: null, needs_confirmation: false, confirm_token: null, created_at: ISO, applied_at: null, as_of: ISO, created: true };

function file(name: string, text: string) {
  return new File([text], name, { type: name.endsWith(".pdf") ? "application/pdf" : "text/csv" });
}

describe("ImportView", () => {
  it("lists import runs, feed status and corporate actions", async () => {
    renderWithQuery(<ImportView />, { "/ledger/imports": IMPORTS });
    expect(await screen.findByText("stmt.csv")).toBeInTheDocument();
    expect(screen.getByText(/Flex pull: not set up/)).toBeInTheDocument();
    expect(screen.getByText("Spinoff OPENW")).toBeInTheDocument();
  });

  it("rejects a PDF in the browser with a pointer to the CSV", async () => {
    renderWithQuery(<ImportView />, { "/ledger/imports": IMPORTS });
    fireEvent.change(await screen.findByLabelText("Activity Statement CSV"), { target: { files: [file("s.pdf", "%PDF")] } });
    expect(await screen.findByText(/PDF statements are not supported/)).toBeInTheDocument();
    expect(apiFetchMock.mock.calls.some((c) => c[0] === "/commands")).toBe(false);
  });

  it("uploads a CSV as a ledger_import command", async () => {
    renderWithQuery(<ImportView />, { "/commands/9": { ...PENDING, status: "applied", result: { counts: { new: 3 } } }, "/ledger/imports": IMPORTS, "/commands": PENDING });
    fireEvent.change(await screen.findByLabelText("Activity Statement CSV"), { target: { files: [file("s.csv", "Statement,Header\n")] } });
    await waitFor(() => {
      const post = apiFetchMock.mock.calls.find((c) => c[0] === "/commands");
      expect(post).toBeTruthy();
      expect(JSON.parse((post![1] as RequestInit).body as string)).toMatchObject({ kind: "ledger_import", payload: { filename: "s.csv" } });
    });
    expect(await screen.findByText(/Imported: 3 new/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run components/ledger/ImportView.test.tsx`
Expected: FAIL with `Cannot find module './ImportView'`.

- [ ] **Step 3: Create `ImportView.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { submitCommand, useCommandStatus } from "@/lib/commands";
import { LedgerNav } from "./LedgerNav";
import type { LedgerFeedStatus, LedgerImportsResponse } from "./types";

const MAX_BYTES = 5 * 1024 * 1024;

// FileReader rather than File.text(): same result, and it exists in every browser and in jsdom.
function readText(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result ?? ""));
    r.onerror = () => reject(r.error);
    r.readAsText(f);
  });
}

function Feed({ label, s }: { label: string; s: LedgerFeedStatus }) {
  let text = "not set up (see SETUP.md, Trade ledger)";
  if (s.configured) text = s.last_error ? `failing: ${s.last_error}` : s.last_run ? `last run ${s.last_run.slice(0, 16).replace("T", " ")} UTC${s.last_status ? ` (${s.last_status})` : ""}` : "set up, not run yet";
  return <li className="text-sm text-muted">{label}: {text}</li>;
}

export function ImportView() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["ledger", "imports"], queryFn: () => apiFetch<LedgerImportsResponse>("/ledger/imports") });
  const [commandId, setCommandId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const status = useCommandStatus(commandId);

  useEffect(() => {
    const st = status.data;
    if (!st) return;
    if (st.status === "applied") {
      const counts = (st.result?.counts ?? {}) as Record<string, number>;
      setMessage(`Imported: ${counts.new ?? 0} new, ${counts.duplicate ?? 0} already present, ${counts.superseded ?? 0} merged with broker fills.`);
      void qc.invalidateQueries({ queryKey: ["ledger"] });
    } else if (st.status === "failed") {
      setMessage(`Import failed: ${String(st.result?.reason ?? "error")}`);
    }
  }, [status.data, qc]);

  async function onFile(f: File | undefined) {
    setMessage(null);
    if (!f) return;
    if (f.name.toLowerCase().endsWith(".pdf")) {
      setMessage("PDF statements are not supported. In Client Portal, open the same statement and choose CSV as the format.");
      return;
    }
    if (f.size > MAX_BYTES) {
      setMessage("That file is over 5 MB. Split the period into two statements.");
      return;
    }
    const content = await readText(f);
    try {
      const r = await submitCommand("ledger_import", { filename: f.name, content });
      setCommandId(r.id);
      setMessage("Importing");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Upload failed");
    }
  }

  async function markReviewed(id: number) {
    await submitCommand("ledger_ca_reviewed", { corporate_action_id: id });
    void qc.invalidateQueries({ queryKey: ["ledger", "imports"] });
  }

  return (
    <div className="space-y-6" data-testid="import-view">
      <LedgerNav />
      <section className="space-y-2 rounded-lg bg-surface p-5">
        <h2 className="text-sm text-content">Upload an IBKR Activity Statement</h2>
        <p className="text-xs text-muted">Client Portal, Performance and Reports, Statements, Activity, format CSV. Re-uploading the same file changes nothing.</p>
        <label className="block text-sm text-muted">
          Activity Statement CSV
          <input type="file" accept=".csv,text/csv" aria-label="Activity Statement CSV" onChange={(e) => void onFile(e.target.files?.[0])} className="mt-2 block text-sm text-content" />
        </label>
        {message && <p className="text-sm text-content" role="status">{message}</p>}
      </section>

      {data && (
        <>
          <ul className="space-y-1">
            <Feed label="Flex pull" s={data.flex} />
            <Feed label="Google Sheet mirror" s={data.sheets} />
          </ul>

          {data.corporate_actions.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-sm text-content">Corporate actions</h2>
              <p className="text-xs text-muted">These are stored but never applied to cost basis automatically. Check each one, then mark it reviewed.</p>
              <ul className="space-y-2 text-sm">
                {data.corporate_actions.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-3">
                    <span className="tabular text-muted">{a.event_date}</span>
                    <span className="text-content">{a.description}</span>
                    {a.reviewed ? <span className="text-xs text-muted">reviewed</span> : (
                      <button type="button" onClick={() => void markReviewed(a.id)} className="rounded bg-elevated px-2 py-0.5 text-xs text-content">Mark reviewed</button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="space-y-2">
            <h2 className="text-sm text-content">Import history</h2>
            <table className="w-full text-sm">
              <thead className="text-left text-muted"><tr><th className="py-1 pr-4">When</th><th className="py-1 pr-4">Source</th><th className="py-1 pr-4">File</th><th className="py-1 pr-4">Result</th><th className="py-1 pr-4">Counts</th></tr></thead>
              <tbody>
                {data.runs.map((r) => (
                  <tr key={r.id} className="border-t border-border align-top">
                    <td className="tabular py-1 pr-4">{r.started_at.slice(0, 16).replace("T", " ")}</td>
                    <td className="py-1 pr-4">{r.source}</td>
                    <td className="py-1 pr-4">{r.filename}</td>
                    <td className={`py-1 pr-4 ${r.status === "ok" ? "text-gain" : "text-loss"}`}>{r.status}{r.reason ? ` (${r.reason})` : ""}</td>
                    <td className="tabular py-1 pr-4 text-muted">{Object.entries(r.counts).map(([k, v]) => `${k} ${v}`).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
```

`web/app/ledger/import/page.tsx`:

```tsx
import { ImportView } from "@/components/ledger/ImportView";

export default function LedgerImportPage() {
  return <ImportView />;
}
```

- [ ] **Step 4: Run the tests**

Run: `cd web && npx vitest run components/ledger` then `npm test` and `npx tsc --noEmit`
Expected: all PASS and type-clean.

- [ ] **Step 5: Commit**

```bash
git add web/components/ledger/ImportView.tsx web/components/ledger/ImportView.test.tsx web/app/ledger/import/page.tsx
git commit -m "feat(web): ledger import page - CSV upload, feed status, corporate actions, history"
```

---

### Task 17: Fences, docs, and the full gate

**Files:**
- Modify:
  - `tests/test_web_fence.py`
  - `ARCHITECTURE.md`, `SETUP.md`, `STATUS.md`, `README.md`, `CLAUDE.md`, `docs/web/commands.md`
- Test: `tests/test_web_fence.py`

- [ ] **Step 1: Add the fence tests** — append to `tests/test_web_fence.py`

```python
# ---------------------------------------------------------------------------
# Trade ledger (docs/superpowers/specs/2026-10-04-trade-ledger-design.md §9).
# ---------------------------------------------------------------------------

_LEDGER_WRITERS = (
    "BrokerExecutionRow(", "BrokerCashEventRow(", "BrokerCorporateActionRow(",
    "FxRateRow(", "LedgerImportRunRow(", "TradeAnnotationRow(",
)


def test_the_trading_path_never_imports_the_ledger() -> None:
    """The ledger is reporting. It must never reach a gate, a size, or a screen."""
    for pkg in ("engine", "execution", "strategies"):
        for path in (ROOT / "src" / pkg).rglob("*.py"):
            text = path.read_text()
            assert "src.ledger" not in text, f"{path} imports the trade ledger"
            assert "trade_ledger" not in text, f"{path} imports the trade-ledger builder"


def test_the_ledger_never_imports_the_enrichment_layer() -> None:
    ledger = ROOT / "src" / "ledger"
    assert ledger.is_dir()
    for path in ledger.rglob("*.py"):
        assert "src.claude" not in path.read_text(), f"{path} imports the enrichment layer"


def test_only_the_ledger_package_writes_the_ledger_tables() -> None:
    for path in Path("src").rglob("*.py"):
        if path.parts[:2] == ("src", "ledger") or path.name == "models.py":
            continue
        text = path.read_text()
        for writer in _LEDGER_WRITERS:
            assert writer not in text, f"{path} constructs {writer[:-1]} — only src/ledger/ may write it"
```

Run: `python -m pytest tests/test_web_fence.py -v`
Expected: all PASS, including the existing `test_the_api_still_writes_exactly_one_table` and `test_reporting_never_writes_anything`.

- [ ] **Step 2: Update `ARCHITECTURE.md`**
  - **Folder guide.** Add a `src/ledger/` entry listing each module and its one-line role: `contracts.py`, `state.py`, `activity_csv.py`, `ingest.py`, `annotations.py`, `flex.py`, `live.py` and `sheets_mirror.py`. Use the descriptions from this plan's File Structure table. Also state the fence: unreachable from engine/execution/strategies, and imports nothing from `src.claude`.
  - **`src/reporting/`.** Add `trade_ledger.py`, the whole-account builder: orders, FIFO trades, outcomes, rolls, orphans, lots, wheel basis, tickers, FX and the USD summary. Note that it is read-only, like `pnl.py`.
  - **`src/api/`.** Add `routers/ledger.py` and `models/ledger.py`, listing the `/ledger/*` routes.
  - **`src/storage/`.** List the six new ORM classes with one line each.
  - **`src/common/`.** List the new `Ledger*`/`Parsed*` schemas.
  - **Data-flow section.** Add the ingestion diagram from spec §2, with R6 applied: Flex runs inside EOD.
  - **`config/`.** Add the `ledger.*` keys.
  - **`scripts/`.** Add `ledger_import.py` and `ledger_flex_pull.py`.
  - **`web/`.** Add `app/ledger/{page,trades,ticker/[symbol],import}` and `components/ledger/`.

- [ ] **Step 3: Update `SETUP.md`**

Add a "Trade ledger" section covering these steps:
1. **Import history:** `python -m scripts.ledger_import ~/Downloads/<statement>.csv`, or use the dashboard `/ledger/import` page. The first import locks the ledger to that account (`ledger.account` in `settings.yaml` overrides this).
2. **Flex query** (Client Portal → Performance & Reports → Flex Queries → Activity Flex Query):
   - Sections: Trades (level of detail **Execution**), Cash Transactions, Corporate Actions, Conversion Rates.
   - Format: XML. Date `yyyyMMdd`, time `HHmmss`, separator `;`.
   - Period: Last 7 Calendar Days.
   - Then enable the Flex Web Service, generate a token, and put `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY_ID` in `.env`.
   - Optionally, create a second query with a 365-day period and run `python -m scripts.ledger_flex_pull --query-id <id>` once to backfill FX rates.
   - Run `python -m scripts.ledger_flex_pull --dry-run` first, and check that expiries and assignments appear with codes `C;Ep` / `A;C`.
3. **Google Sheet:**
   - Create a Google Cloud project, enable the Google Sheets API, and create a service account with a JSON key.
   - Share the spreadsheet with the service account's email as Editor.
   - Set `GOOGLE_SHEETS_CREDENTIALS_PATH` and `LEDGER_SHEET_ID` (the id from the sheet URL) in `.env`.
   - The system writes `Ledger (auto)`, `Tickers (auto)` and `Summary (auto)` and never touches your other tabs.
4. **Optional intraday visibility of manual TWS trades:** in TWS, Global Configuration → API → Settings → Master API client ID = `14`. Without it, manual trades arrive with the nightly Flex pull instead.

Also update:
- The scripts table: add the two CLIs.
- The `.env` keys table, if there is one.
- Troubleshooting rows:
  - `account_mismatch` on import → wrong account or a paper statement.
  - Flex `1012` → token expired, so regenerate it.
  - The sheet isn't updating → see `/ledger/import` "Google Sheet mirror: failing: …".

- [ ] **Step 4: Update `STATUS.md`**
  - **Built:** the trade ledger (all of the above).
  - **Live-verification items:**
    1. The Flex Trades section carries expiries, assignments and exercises as BookTrade rows with `notes` codes (R1). Verify with `--dry-run` against an imported CSV period.
    2. Flex `dateTime` is US/Eastern.
    3. Flex `ibOrderID` equals the API `permId`.
    4. Live manual-trade visibility depends on the Master API client ID.
  - **Known limitations:**
    - Paper-account fills are excluded once the ledger is locked to the real account. The bot's paper trades won't appear until live cutover.
    - USD totals need FX rates, which are sparse without a Flex backfill.
    - Corporate actions are flagged, not applied.
    - Flex OptionEAE is unused.
    - The Sheets mirror is one-way and carries no unrealized P&L.
    - There is no PDF import.

- [ ] **Step 5: Update the remaining docs**
  - **`docs/web/commands.md`:** add a `### \`ledger_import\``, `### \`ledger_annotate\`` and `### \`ledger_ca_reviewed\`` section under "Every kind". Each needs its payload, its result shape and its failure-reason table:
    - `ledger_import`: `pdf_not_supported`, `not_an_activity_statement`, `parse_errors`, `account_mismatch`.
    - `ledger_ca_reviewed`: `not_found`.
    - Also note that the import strips the file from the command row once it has been handled.
  - **`README.md`:** add one line to the feature pitch: "Trade ledger: every IBKR execution, per-ticker P&L and wheel cost basis, CSV/Flex/live ingestion, mirrored to Google Sheets".
  - **`CLAUDE.md`:** in "The third, read-only tier — `src/reporting/`", add `trade_ledger.py` (the whole-account builder). Add a short paragraph stating the `src/ledger/` fence and naming `tests/test_web_fence.py::test_the_trading_path_never_imports_the_ledger`.

- [ ] **Step 6: Run the full gate**

```bash
python -m pytest -q
ruff format --check src/ledger src/reporting/trade_ledger.py src/api/routers/ledger.py src/api/models/ledger.py \
  scripts/ledger_import.py scripts/ledger_flex_pull.py tests/test_ledger_*.py tests/test_trade_ledger_*.py \
  tests/test_api_ledger.py tests/test_drain_ledger.py   # never `ruff format .` - the tree has others' work
ruff check .
mypy src
cd web && npm test && npx tsc --noEmit && cd ..
```
Expected: everything passes. Report the actual counts; don't claim a pass without the output.

- [ ] **Step 7: End-to-end smoke on the real file (local, not committed)**

```bash
python -m scripts.ledger_import ~/Downloads/U1234567_U1234567_20250401_20260401_AS_Fv2_<hash>.csv --dry-run
```
Expected: `"fatal": false`, with 485 OPT + 123 STK executions. Do **not** run the non-dry import against the operator's real DB unless the operator asks for it.

- [ ] **Step 8: Commit**

```bash
git add tests/test_web_fence.py docs/web/commands.md
git add -p ARCHITECTURE.md SETUP.md STATUS.md README.md CLAUDE.md
git commit -m "docs(ledger): fences, architecture, setup (Flex + Sheets), status, commands"
```
