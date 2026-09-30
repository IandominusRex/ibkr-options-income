# Scan-Loop Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the faults found in the 14–28 Sep intraday-scan post-mortem. Make the loop self-healing and loud when it fails. Make rejection reasons and the local-LLM review genuinely informative. Then run the paper account on full autonomy so the system's behaviour can be observed end to end.

**Architecture:** Most tasks are narrow bug fixes inside existing modules (`src/ibkr/market_data.py`, `src/notify/approval_service.py`, `src/analytics/liquidity.py`, `src/orchestrator/eod_report.py`). Three additions are new:
- An out-of-process **watchdog** (`src/ops/watchdog.py` + `scripts/watchdog.py`) run by launchd every 5 minutes. It alerts over the raw Telegram Bot API, so it keeps working when the trading process itself is dead.
- A single **`./ibkr` control script** that installs and manages two launchd agents (supervisor and watchdog, plus optional Gateway).
- A **news-grounded Ollama review**: a deterministic FACTS block, a keyless news provider, and an optional bounded tool-calling research turn. All of it stays in the enrichment tier, behind the fence.

**Tech Stack:** Python 3.12, ib_async, SQLAlchemy/SQLite, python-telegram-bot, httpx, Ollama (`/api/generate` + `/api/chat`, local `qwen3:8b` or a smaller/newer candidate chosen in Task 10), macOS launchd, pytest/ruff/mypy.

**Spec / context:** The post-mortem artifact (https://claude.ai/artifact/M6R4haPnxYnkPfx5F3c7yZ, sections A–D) and the verified root causes below. The executor must also read `CLAUDE.md`, `ARCHITECTURE.md` and `STATUS.md` before starting.

## Global Constraints

- **The Rules Engine (`src/engine/risk_engine.py`) remains the only path to an order.** Nothing in this plan lets the LLM, the news layer, the watchdog or `./ibkr` place, size or gate an order.
- **Fence:** new news and tool-calling code is **enrichment tier**. It must never be importable from `src/engine/`, `src/execution/` or `src/strategies/`. Extend `tests/test_eval_skills.py` fence tests to cover it.
- **Tunables live in YAML** (`config/*.yaml`), never hard-coded. Secrets live only in `.env`.
- **Paper first.** The autonomy bypass in Task 12 must be impossible when `LIVE_TRADING=true`.
- `ib_async` only (never `ib_insync`). Check signatures against `ib_async_documentation.md`.
- One clientId per process (`config/settings.yaml → ibkr.client_ids`). The watchdog opens **no** IBKR connection.
- The reasoning backend stays **`claude.backend: "ollama"`**. The user has no Anthropic API key and runs the model locally.
- Every task ends green on `python -m pytest -q`, `ruff check .` and `mypy src`. Docs follow the CLAUDE.md doc-update table, rows cited per task.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Verified root causes (evidence gathered 2026-09-29)

| # | Symptom (artifact ref) | Root cause | Evidence |
|---|---|---|---|
| R1 | AMD/GOOGL "No qualified option contracts" (E2) | `reqSecDefOptParams` returns a second, **adjusted** chain (`tradingClass=2AMD`/`2GOOGL`, one expiry `20261002`, one strike `443`/`306`). `get_option_chain_quotes[_async]` takes the *first* SMART chain with expirations, and IBKR's list order varies, so the adjusted chain is picked some of the time. Its expiry falls outside DTE 7–28, so `expirations=[]` and `strikes=0`. Option contracts are also built without `tradingClass`, so the class is ambiguous at qualification. | Live probe (clientId 29, read-only): AMD returns 41 chains, `SMART tc=2AMD` listed **before** `SMART tc=AMD`. |
| R2 | "Scan blocked" alert never arrives (E1/E3) | `_notify_scan_blocked` sends MarkdownV2. The pre-scan caller interpolates `probe.action_hint` **unescaped**, so Telegram rejects it with `BadRequest: Can't parse entities: character '.' is reserved`. The notice has failed 6 out of 6 times. | `logs/approval.log`, 6 × "failed to send scan-blocked notice". |
| R3 | 6-day silent outage (E1) | Nothing restarts `scripts.start` if it or the laptop stops, and nothing outside the process notices. The monitor was down over the same days (`monitor.log` has no lines for 16–22 Sep). | No launchd agents present in `~/Library/LaunchAgents`. |
| R4 | `illiquid` reason is opaque (E7) | `passes_liquidity_gates` returns a bare bool, so the generator appends one code for 5+ distinct failure modes. | `src/analytics/liquidity.py:39`. |
| R5 | Review always "wait", summaries empty (E5) | (a) `format:"json"` makes qwen3:8b emit **one object**, so a 3-candidate call reviews only 1. (b) There is no rubric for sell/wait/skip. (c) The model derives moneyness and earnings timing itself and gets them wrong ("put is ITM if stock rises"; treats earnings on 10-29 as a risk for a 09-30 expiry). (d) There is no news input for full-universe scans. (e) `summary` is only requested on single-ticker scans. | Replayed the stored prompts on qwen3:8b: **6/6 "wait"** on single-candidate prompts, and **1 review from 3 candidates** on the multi-candidate prompt. |
| R6 | 33 stale `pending` approvals (E6) | Only `process_queued_orders` expires approvals, and only ones already tapped (queued orders). | `src/execution/approval.py:173`. |
| R7 | TQQQ 44–48 vs 55 floor (finding 8) | TQQQ/UPRO/MAGS had **1** `iv_history` row and BAC had **0**, so `iv_rank=None`. `cash_secured_put.py` then scores `iv_score=0.0` under a **30%** weight. Separately, the EOD IV append had stalled for most names since 11 Sep: it timed out and aborted after 5 consecutive failures, always on the same alphabetical head. | TQQQ blended = 0·0.30 + 50·0.20 + 70·0.25 + L·0.15 + ~70·0.10 + 50·0.05 = **37 + 0.15·L**, i.e. 44–48 at liquidity 47–73. After the backfill TQQQ IVR = 30.15, which adds **+9.0**, so ≈53–57. |
| R8 | Auto mode refused (D) | `promotion_blockers` requires ≥20 fills, ≥60% fill rate and ≥1 close. Today there is 1 fill, an 11% rate and 0 closes. | `src/storage/system_settings.py:112`. |

**Already done (pre-flight, 2026-09-29 15:30 SGT):** `python -m scripts.backfill_iv` ran once. It has no argparse, so `--help` executed it. It filled `iv_history` for all 40 indexes/watchlist/would_own symbols up to 2026-09-28 (TQQQ, UPRO and MAGS now have 251 rows each). AMD and BAC were **not** covered because they aren't in those lists. Task 4 fixes that.

**Decision on the score floor (finding 8):** keep `min_candidate_score: 55`. TQQQ's shortfall was missing data, not a mis-set floor. With real IV history it sits at ~53–57, right where an IV rank of 30 (the gate minimum, "barely acceptable premium") should put it. UPRO (IVR 18.8), MAGS (19.7), RKLB (18.6) and NBIS (13.4) fall short on genuinely cheap premium, and the IV-rank gate already rejects them for that. Lowering the floor would only admit trades with thin premium. Task 9 makes missing IV rank **neutral** rather than zero, so a data gap can't cause this again.

## File structure

| File | Status | Responsibility |
|---|---|---|
| `src/ibkr/market_data.py` | modify | `_select_chain()`; pass `tradingClass` into built contracts |
| `src/ibkr/contracts.py` | modify | `build_option(..., trading_class="")` |
| `config/universe.yaml` | modify | AMD and BAC in `watchlist` + `sectors` |
| `src/notify/approval_service.py` | modify | escape fix + plain-text fallback; scan-completed heartbeat; approval sweep in poll loop |
| `src/storage/system_settings.py` | modify | `SCAN_COMPLETED_KEY`; paper promotion bypass |
| `src/ops/__init__.py`, `src/ops/watchdog.py` | **create** | pure watchdog checks + alert state machine + raw Telegram sender |
| `scripts/watchdog.py` | **create** | one-shot watchdog entrypoint (launchd `StartInterval`) |
| `scripts/launchd.py` | **create** | renders/installs/uninstalls the launchd plists |
| `ibkr` (repo root, executable) | **create** | the single control script |
| `src/analytics/liquidity.py` | modify | `liquidity_failures()` with granular codes |
| `src/strategies/_evaluation.py`, `cash_secured_put.py`, `covered_call.py` | modify | emit granular codes and carry quote microstructure |
| `src/common/schemas.py` | modify | `TradeCandidate` optional `quote_bid/quote_ask/open_interest/option_volume` |
| `src/storage/models.py`, `db.py`, `risk_verdicts.py` | modify | `risk_verdicts.liquidity` JSON column |
| `src/notify/formatters.py`, `src/api/routers/options.py` | modify | labels for the new codes (parity test) |
| `src/storage/approvals.py` | **create** | `expire_stale_approvals()` |
| `src/strategies/cash_secured_put.py`, `covered_call.py` | modify | missing IV rank → neutral 50 + tag |
| `src/orchestrator/eod_report.py` | modify | staleness-ordered IV append, retry pass, include holdings |
| `scripts/backfill_iv.py` | modify | argparse (`--symbols`), include holdings |
| `src/claude/prompts/strategist.py` | modify | FACTS block, rubric, NEWS block, `{"reviews":[…]}` contract |
| `src/claude/ollama_runner.py`, `src/claude/parser.py` | modify | JSON-schema `format`, `reviews` wrapper, tool-research turn |
| `src/data/protocols.py`, `src/data/google_news_backend.py`, `src/data/factory.py` | modify/**create** | keyless `NewsSearchProvider` (Google News RSS) |
| `src/claude/news_context.py`, `src/claude/ollama_tools.py` | **create** | per-candidate news block; bounded tool loop |
| `scripts/review_eval.py` | **create** | replay stored candidates through the reviewer, print verdict distribution |
| `config/settings.yaml`, `config/risk_limits.yaml` | modify | new keys (listed per task) |

---

### Task 1: Pick the right option chain (AMD/GOOGL)

**Files:**
- Modify: `src/ibkr/contracts.py:24-25`
- Modify: `src/ibkr/market_data.py:657-677` (`_build_chain_contracts`), `:894-918` (sync), `:951-975` (async)
- Test: `tests/test_market_data.py`

**Interfaces:**
- Produces: `_select_chain(chains: Sequence[Any], symbol: str) -> Any | None`; `build_option(symbol, expiry, strike, right, trading_class: str = "") -> Option`; `_build_chain_contracts(symbol, expirations, strikes, spot, trading_class: str = "") -> list[Option]`

- [x] **Step 1: Write the failing tests** (append to `tests/test_market_data.py`)

```python
from types import SimpleNamespace

from src.ibkr.market_data import _build_chain_contracts, _select_chain


def _chain(tc: str, exps: set[str], strikes: set[float], exchange: str = "SMART"):
    return SimpleNamespace(exchange=exchange, tradingClass=tc, expirations=exps, strikes=strikes)


def test_select_chain_prefers_standard_class_over_adjusted_regardless_of_order():
    adjusted = _chain("2AMD", {"20261002"}, {443.0})
    standard = _chain("AMD", {"20261009", "20261016"}, {600.0, 630.0, 660.0})
    assert _select_chain([adjusted, standard], "AMD") is standard
    assert _select_chain([standard, adjusted], "AMD") is standard


def test_select_chain_prefers_smart_among_same_class():
    cboe = _chain("AMD", {"20261009"}, {600.0}, exchange="CBOE")
    smart = _chain("AMD", {"20261009"}, {600.0})
    assert _select_chain([cboe, smart], "AMD") is smart


def test_select_chain_falls_back_to_richest_chain_when_no_class_matches():
    thin = _chain("XYZ1", {"20261002"}, {10.0})
    rich = _chain("XYZ2", {"20261009", "20261016"}, {10.0, 11.0})
    assert _select_chain([thin, rich], "ABC") is rich


def test_select_chain_none_when_nothing_has_expirations():
    assert _select_chain([_chain("AMD", set(), set())], "AMD") is None


def test_build_chain_contracts_sets_trading_class():
    from datetime import date, timedelta

    exp = (date.today() + timedelta(days=14)).strftime("%Y%m%d")
    contracts = _build_chain_contracts("AMD", [exp], [600.0, 660.0], 630.0, trading_class="AMD")
    assert contracts and all(c.tradingClass == "AMD" for c in contracts)
```

- [x] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_market_data.py -k "select_chain or trading_class" -v`
Expected: FAIL with `ImportError: cannot import name '_select_chain'`.

- [x] **Step 3: Implement**

In `src/ibkr/contracts.py`:

```python
def build_option(
    symbol: str, expiry: date, strike: float, right: str, trading_class: str = ""
) -> Option:
    """SMART-routed option. *trading_class* disambiguates when IBKR lists an adjusted chain
    (e.g. ``2AMD`` after a corporate action) beside the standard one; empty = let IBKR pick."""
    return Option(
        symbol, expiry.strftime("%Y%m%d"), strike, right, "SMART", tradingClass=trading_class
    )
```

In `src/ibkr/market_data.py`, add below `_filter_strikes`:

```python
def _select_chain(chains: Sequence[Any], symbol: str) -> Any | None:
    """Pick the standard option chain for *symbol* from ``reqSecDefOptParams`` output.

    IBKR returns one entry per (exchange, tradingClass). After a corporate action it also lists
    an *adjusted* class (``2AMD``/``2GOOGL``: one expiry, one odd strike) whose position in the
    list varies call to call. Taking "the first SMART chain with expirations" therefore
    picked the adjusted chain intermittently and the scan saw ``expirations=[] strikes=0``
    (2026-09 AMD/GOOGL incident). Rank: tradingClass == symbol, then SMART, then the most
    expirations, then the most strikes.
    """
    candidates = [c for c in chains if c.expirations]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda c: (
            c.tradingClass == symbol,
            c.exchange == "SMART",
            len(c.expirations),
            len(c.strikes),
        ),
    )
```

Add `Sequence` to the existing `typing`/`collections.abc` import. Change `_build_chain_contracts` to accept `trading_class: str = ""` and pass it to `build_option(..., trading_class)`. In **both** `get_option_chain_quotes` and `get_option_chain_quotes_async`, replace the two `next(...)` lines with:

```python
    chain = _select_chain(chains, symbol)
    if chain is None:
        log.warning("No option chain params returned for %s", symbol)
        return []
```

Rename every later use of `smart` to `chain`. Log `tradingClass` in the existing `symbol=%s expirations=%s …` line (append `tc=%s`, `chain.tradingClass`). Pass `trading_class=chain.tradingClass` to `_build_chain_contracts`.

- [x] **Step 4: Run tests**

Run: `python -m pytest tests/test_market_data.py -v`
Expected: all PASS (including the pre-existing `build_chain_contracts` tests, which use the default `trading_class=""`).

- [x] **Step 5: Live verification (read-only, TWS/Gateway up)**

Run:
```bash
.venv/bin/python - <<'EOF'
import asyncio
from ib_async import IB
from src.ibkr.market_data import get_option_chain_quotes_async
async def main():
    ib = IB(); await ib.connectAsync("127.0.0.1", 4002, clientId=29, readonly=True)
    for s in ("AMD", "GOOGL", "META"):
        q = await get_option_chain_quotes_async(ib, s); print(s, len(q), "quotes")
    ib.disconnect()
asyncio.run(main())
EOF
```
Expected: AMD and GOOGL each return **> 0** quotes (before the fix: 0). Run it three times, since the bug was order-dependent.

- [x] **Step 6: Commit**

```bash
git add src/ibkr/contracts.py src/ibkr/market_data.py tests/test_market_data.py
git commit -m "fix(ibkr): select the standard option chain, not IBKR's adjusted class (AMD/GOOGL)"
```

---

### Task 2: AMD and BAC in the universe

**Files:**
- Modify: `config/universe.yaml` (`watchlist`, `sectors`)
- Modify: `src/claude/prompts/strategist.py` (`_UNIVERSE_CONTEXT`), `docs/archive/UNIVERSE_RESEARCH.md`
- Test: `tests/test_universe_consumers.py`

**Placement decision (operator-confirmed 2026-09-29):**
- **AMD**: `watchlist` + `sectors: semis`. CC-only while held; **no CSPs**.
- **BAC**: `watchlist` + `sectors: financials` + **`would_own` + `actively_wheeling`**. CSPs wanted. Actively wheeling so it's scanned every cycle: a low-vol bank would rarely trip the 3% dip-watch trigger.
- **DPST** (3× regional-bank ETF, already in `indexes`/`leveraged_etfs`/`sectors: financials`): add to **`would_own` + `actively_wheeling`**. This moves it from the "CC-only leveraged" set into the deliberate-exception set alongside TQQQ/UPRO/SOXL. The `leveraged_etfs` comment block derives the split from `would_own`, so no other file decides it. Update that comment's example lists (CC-only → LABU/TSLL; exception → TQQQ/UPRO/SOXL/DPST, "confirmed 2026-09-29"), and the header's "Leveraged ETFs (LABU/TSLL/DPST) — CC-only" line.

- [x] **Step 1: Write the failing guard test** (append to `tests/test_universe_consumers.py`)

```python
def test_every_universe_symbol_has_a_sector():
    """A symbol missing from `sectors:` silently bypasses the per-sector concentration cap
    (2026-09: AMD/BAC). Every scanned list must be covered."""
    from src.common.config import get_config

    u = get_config().universe
    scanned = set(u.get("indexes", [])) | set(u.get("watchlist", [])) | set(u.get("would_own", []))
    missing = sorted(scanned - set(u.get("sectors", {})))
    assert missing == [], f"add to universe.yaml → sectors: {missing}"


def test_amd_and_bac_are_in_the_universe():
    from src.common.config import get_config

    u = get_config().universe
    assert {"AMD", "BAC"} <= set(u["watchlist"])
    assert u["sectors"]["AMD"] == "semis" and u["sectors"]["BAC"] == "financials"


def test_csp_eligibility_matches_operator_decision():
    from src.common.config import get_config

    u = get_config().universe
    assert {"BAC", "DPST"} <= set(u["would_own"]) and {"BAC", "DPST"} <= set(u["actively_wheeling"])
    assert "AMD" not in u["would_own"]  # AMD: covered calls only
    # DPST is now a deliberate leveraged exception, not CC-only
    assert "DPST" in set(u["leveraged_etfs"]) & set(u["would_own"])
```

- [x] **Step 2: Run** `python -m pytest tests/test_universe_consumers.py -k "sector or amd" -v`. Expected: FAIL on the second test (the first may also list other gaps; fix every one it names).

- [x] **Step 3: Edit `config/universe.yaml`**

Under `watchlist:` → `# safe_bets` add:

```yaml
  - AMD          # Held (300 sh); semis; liquid chains; CC-eligible while held; dip-watch only if added to would_own
  - BAC          # Held (1000 sh); money-centre bank; liquid chains; CC-eligible while held
```

Under `sectors:` → `# safe_bets stocks` add `AMD: semis` and `BAC: financials`.

Add `BAC` and `DPST` to `actively_wheeling` (BAC under `# safe_bets`; DPST under `# risky — leveraged, deliberate would_own exception`) and to the matching block of `would_own`. Update the leveraged-ETF comments as described above. `tests/test_etf_warnings.py` / `src/research/checks/warnings.py` read the split from config. Run them and update any fixture that hard-codes DPST as CC-only.

- [x] **Step 4: Update the prompt table and research doc**

In `_UNIVERSE_CONTEXT` add two rows in the existing column format, with no stale price anchors (the scan-time spot block overrides them):

```
  AMD  held   IVR 30-55  CC      1.5-3.0%/mo   semis; held 300sh — CC income on existing shares
  BAC  held   IVR 20-40  CC      0.8-1.5%/mo   money-centre bank; held 1000sh — CC income
```

In `docs/archive/UNIVERSE_RESEARCH.md`, add AMD and BAC sections in the same template as neighbouring tickers (tier, CC vs CSP appropriateness: AMD "held — CC only", BAC "held — CC + CSP, actively wheeling"). Also change DPST's section from CC-only to "deliberate would_own exception (2026-09-29): 3× regional banks, so assignment means holding a daily-reset product; size small and prefer short DTE". Change the prompt table's BAC row to `CC+CSP`, and DPST's row the same way.

- [x] **Step 5: Run** `python -m pytest tests/test_universe_consumers.py tests/test_config_keys.py -v`. Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add config/universe.yaml src/claude/prompts/strategist.py docs/archive/UNIVERSE_RESEARCH.md tests/
git commit -m "feat(universe): AMD (CC-only) and BAC to universe; BAC + DPST CSP-eligible; sector guard"
```

Docs: `How the scan works.md` (actively_wheeling now includes BAC/DPST); `ARCHITECTURE.md` if it lists the leveraged split.

---

### Task 3: Make the "scan blocked" alert actually send

**Files:**
- Modify: `src/notify/approval_service.py:1105-1146` (`_notify_scan_blocked`), `:1391-1398` (pre-scan caller)
- Test: `tests/test_notify.py`

- [x] **Step 1: Write the failing tests** (append to `tests/test_notify.py`)

```python
import pytest


class _FakeBot:
    def __init__(self, fail_markdown: bool = False):
        self.calls: list[dict] = []
        self.fail_markdown = fail_markdown

    async def send_message(self, **kw):
        self.calls.append(kw)
        if self.fail_markdown and kw.get("parse_mode") == "MarkdownV2":
            from telegram.error import BadRequest

            raise BadRequest("Can't parse entities: character '.' is reserved")


@pytest.mark.asyncio
async def test_scan_blocked_falls_back_to_plain_text_on_markdown_error():
    from src.notify.approval_service import _notify_scan_blocked

    bot = _FakeBot(fail_markdown=True)
    await _notify_scan_blocked(bot, "1", "Data farm down", "Restart Gateway (Error 1100).")
    assert len(bot.calls) == 2
    assert "parse_mode" not in bot.calls[1]
    assert "\\" not in bot.calls[1]["text"]  # escapes stripped for the plain-text copy
    assert "Restart Gateway (Error 1100)." in bot.calls[1]["text"]


def test_probe_action_hint_is_escaped_at_the_call_site():
    import inspect

    from src.notify import approval_service

    src = inspect.getsource(approval_service._intraday_scan_loop)
    assert "{probe.action_hint}" not in src
    assert "_md_escape(probe.action_hint)" in src
```

(Use the repo's existing async-test marker. Check `tests/conftest.py`. If `pytest-asyncio` isn't configured, wrap the call in `asyncio.run(...)` instead.)

- [x] **Step 2: Run** `python -m pytest tests/test_notify.py -k "scan_blocked or action_hint" -v`. Expected: FAIL.

- [x] **Step 3: Implement**

At the pre-scan caller, change `f"{code_line}\n\n{probe.action_hint}"` to `f"{code_line}\n\n{_md_escape(probe.action_hint)}"`. Also escape `probe.diagnosis` where it's passed as `reason`: `_notify_scan_blocked` already wraps `reason` in `_md_escape`, so leave that alone.

In `_notify_scan_blocked`, replace the `try/except` body with:

```python
    text = (
        f"\U0001f6d1 *Scan blocked* · {now_et_hhmm()}\n\n"
        f"*{_md_escape(reason)}*\n{detail}\n\n"
        f"Forcing a reconnect; the next 15\\-min cycle should recover\\."
        f"{retry_line}"
    )
    cfg_s = get_config().secrets
    thread = thread_id(cfg_s.telegram_thread_scan)
    try:
        await bot.send_message(  # type: ignore[attr-defined]
            chat_id=chat_id, message_thread_id=thread, text=text, parse_mode="MarkdownV2"
        )
    except Exception:
        logger.warning("scan-blocked notice: MarkdownV2 send failed — retrying as plain text",
                       exc_info=True)
        try:
            await bot.send_message(  # type: ignore[attr-defined]
                chat_id=chat_id, message_thread_id=thread, text=text.replace("\\", "")
            )
        except Exception:
            logger.exception("Intraday loop: failed to send scan-blocked notice")
```

- [x] **Step 4: Run** `python -m pytest tests/test_notify.py -v`. Expected: PASS.

- [x] **Step 5: Docs:** `SETUP.md` troubleshooting table gets a row: "No 'Scan blocked' Telegram message during a data-farm outage → fixed 2026-09-29 (unescaped hint); if still silent, check `logs/approval.log` for `scan-blocked notice`".

- [x] **Step 6: Commit**

```bash
git add src/notify/approval_service.py tests/test_notify.py SETUP.md
git commit -m "fix(notify): escape the probe hint and fall back to plain text so scan-blocked alerts send"
```

---

### Task 4: Scan heartbeat + IV-history completeness (holdings, retries, staleness order)

**Files:**
- Modify: `src/storage/system_settings.py` (key constant), `src/notify/approval_service.py:~1275` (write heartbeat on completed scan)
- Modify: `src/orchestrator/eod_report.py:109-196` (`_universe_symbols`, `_append_daily_iv`)
- Modify: `scripts/backfill_iv.py` (argparse + holdings)
- Test: `tests/test_eod.py`, `tests/test_monitor_heartbeat.py`

**Interfaces:**
- Produces: `SCAN_COMPLETED_KEY = "intraday_scan_completed"` (ISO-8601 UTC string) in `src/storage/system_settings.py`, which Task 5's watchdog reads. Also `_iv_symbols(held: list[str]) -> list[str]` in `eod_report.py`, ordered oldest-observation-first.

- [x] **Step 1: Write the failing tests**

In `tests/test_eod.py`:

```python
def test_iv_symbols_include_holdings_and_order_oldest_first(monkeypatch):
    from datetime import date

    from src.orchestrator import eod_report

    monkeypatch.setattr(eod_report, "_universe_symbols", lambda: ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(
        "src.storage.iv_history.latest_obs_dates",
        lambda syms: {"AAA": date(2026, 9, 28), "BBB": date(2026, 9, 11)},
    )
    out = eod_report._iv_symbols(held=["ZZZ", "AAA"])
    # never-observed first (ZZZ, CCC — alphabetical tie-break), then oldest (BBB), then AAA
    assert out == ["CCC", "ZZZ", "BBB", "AAA"]
```

```python
def test_append_daily_iv_retries_failed_symbols_once(monkeypatch):
    """A symbol that times out on the first pass gets one more attempt after the pass."""
    import asyncio

    from src.orchestrator import eod_report

    attempts: dict[str, int] = {}

    async def fake_one(ib, sym, timeout):
        attempts[sym] = attempts.get(sym, 0) + 1
        if sym == "TQQQ" and attempts[sym] == 1:
            raise TimeoutError
        return True

    monkeypatch.setattr(eod_report, "_append_one_iv", fake_one)
    asyncio.run(eod_report._append_daily_iv(object(), ["AMZN", "TQQQ"]))
    assert attempts == {"AMZN": 1, "TQQQ": 2}
```

In `tests/test_monitor_heartbeat.py`:

```python
def test_scan_completed_key_is_exported():
    from src.storage.system_settings import SCAN_COMPLETED_KEY

    assert SCAN_COMPLETED_KEY == "intraday_scan_completed"
```

- [x] **Step 2: Run** `python -m pytest tests/test_eod.py tests/test_monitor_heartbeat.py -k "iv_symbols or retries or scan_completed" -v`. Expected: FAIL.

- [x] **Step 3: Implement**

`system_settings.py`: add `SCAN_COMPLETED_KEY = "intraday_scan_completed"` beside `MONITOR_HEARTBEAT_KEY`.

`approval_service.py`, in the `else:` branch that logs "Intraday scan complete", add:

```python
                set_setting(SCAN_COMPLETED_KEY, datetime.now(UTC).isoformat())
```

`eod_report.py`:
1. Extract the per-symbol body of `_append_daily_iv` into `async def _append_one_iv(ib, sym: str, timeout: float) -> bool` (qualify, `reqHistoricalDataAsync(... "OPTION_IMPLIED_VOLATILITY" ...)`, `append_observation`; return True if a row was inserted; exceptions propagate).
2. Add:

```python
def _iv_symbols(held: list[str]) -> list[str]:
    """Universe ∪ held symbols, never-observed first, then oldest observation first.

    Ordering by staleness (not alphabet) means a mid-run abort starves whichever names were
    freshest, not the same alphabetical tail every night (2026-09 TQQQ/UPRO/MAGS incident).
    """
    from src.storage.iv_history import latest_obs_dates

    symbols = sorted(set(_universe_symbols()) | {s.upper() for s in held})
    last = latest_obs_dates(symbols)
    return sorted(symbols, key=lambda s: (s in last, last.get(s, date.min), s))
```

3. In `_append_daily_iv`, after the main loop, retry each symbol in `failed_symbols` **once** with `timeout=_IV_REQUEST_TIMEOUT_S * 2`. Log `"EOD: IV retry pass recovered %d/%d"`. Keep the existing dead-farm abort for the first pass only.
4. The caller of `_append_daily_iv` passes `_iv_symbols(held=[p.symbol for p in positions if p.sec_type == "STK"])`. Use the positions the EOD run already fetched.

`scripts/backfill_iv.py`: add `argparse` with `--symbols` (comma list; default = universe ∪ currently-held from the latest `position_snapshots` row) and a real `--help`. Keep the existing insert logic.

- [x] **Step 4: Run** `python -m pytest tests/test_eod.py tests/test_eod_idempotency.py tests/test_monitor_heartbeat.py tests/test_iv_history.py -v`. Expected: PASS.

- [x] **Step 5: Backfill the two holdings**

Run: `python -m scripts.backfill_iv --symbols AMD,BAC`
Then: `sqlite3 data/income_system.db "select symbol,count(*),max(obs_date) from iv_history where symbol in ('AMD','BAC') group by 1"`
Expected: both have ≥ 200 rows, and `max(obs_date)` is the last trading day.

- [x] **Step 6: Docs:** `SETUP.md` scripts table (`backfill_iv --symbols`); `ARCHITECTURE.md` EOD section (staleness order + retry + holdings).

- [x] **Step 7: Commit**

```bash
git add src/storage/system_settings.py src/notify/approval_service.py src/orchestrator/eod_report.py scripts/backfill_iv.py tests/ SETUP.md ARCHITECTURE.md
git commit -m "fix(eod): IV append covers holdings, retries failures, orders by staleness; add scan heartbeat"
```

---

### Task 4b: The EOD run must never hang

**Evidence (added 2026-09-29):** the IV append aborted or appended ≤3 rows on 15 Aug, 22 Aug, 28 Aug, 9 Sep and 26 Sep. The 24 and 25 Sep runs logged no append line at all. The only full success since August was 12 Sep. The 29 Sep run (started 04:33 SGT) was **still alive at 15:30 SGT**:
- it took 10 min to connect;
- the account-summary fetch took ~4 h, looping on `Error 322: Maximum number of account summary requests exceeded` through Gateway's 1100/1102 flaps (this was IBKR's nightly reset window, ~23:45–00:45 ET);
- then IV requests timed out.

`scripts/start.py` only spawns a new EOD once `eod_proc.poll()` is not None (`:399-405`), so **one hung EOD blocks every later EOD**. The approval service's IB objects already get the 1102 account-summary guard (`src/ibkr/connection.py:403-440`); the EOD connection (clientId 11) does not.

**Files:** `src/orchestrator/eod_report.py`, `scripts/start.py:272-405`, `src/ibkr/connection.py` (reuse the existing guard), `config/settings.yaml` (`scheduler.eod_timeout_minutes: 60`), `src/storage/system_settings.py` (`EOD_COMPLETED_KEY = "eod_completed"`). Tests: `tests/test_start_scheduler.py`, `tests/test_eod.py`.

**Note:** `src/ibkr/connection.py` and `tests/test_connection.py` had uncommitted operator changes on 2026-09-29. Read `git diff` first and build on them, never over them.

- [x] **Step 1: Failing tests**
  - `test_start_scheduler.py`: an `eod_proc` running longer than `eod_timeout_minutes` is terminated (SIGTERM, then SIGKILL after `STOP_GRACE_SECONDS`) with an ERROR log line, and a new EOD may be scheduled the next trading day. Use a fake `Popen` with a controllable `poll()` and a fake clock, following the existing scheduler tests.
  - `test_eod.py`: the EOD connection has the 1102 account-summary guard applied (assert the helper from `connection.py` was called on the EOD `IB` object). A successful run writes `EOD_COMPLETED_KEY`.
- [x] **Step 2: Run** `python -m pytest tests/test_start_scheduler.py tests/test_eod.py -v`. Expected: FAIL.
- [x] **Step 3: Implement**
  - In `start.py`'s loop, record the EOD start time. Past the deadline, terminate/kill, log `"EOD exceeded %d min — killed"`, and set `eod_proc = None`.
  - In `eod_report.py`, apply the existing connection guard right after connect.
  - Wrap the account-summary fetch in `asyncio.wait_for(..., 120)`, falling back to the last `portfolio_snapshots` row with a WARNING.
  - Write `EOD_COMPLETED_KEY` (ISO UTC) at the end of a successful run.
  - Add `scheduler.eod_timeout_minutes: 60` to `settings.yaml` + config model.
- [x] **Step 4: Run** the tests again. Expected: PASS.
- [x] **Step 5:** Task 5's watchdog gets one more check, `eod`: on a trading day, after `scheduler.eod_report` + 90 min ET, `eod_completed` must be dated today (ET). Add it to the checks table and to `tests/test_watchdog.py`, with a pure `eod_check(iso, now_et, due_hhmm, grace_min)` test mirroring `scan_loop_check`.
- [x] **Step 6: Docs:** `ARCHITECTURE.md` (EOD timeout + completion key), `SETUP.md` troubleshooting ("EOD summary missing → check `logs/eod.log`; the launcher now kills a run after 60 min").
- [x] **Step 7: Commit** `git commit -m "fix(eod): hard timeout, 1102 account-summary guard, completion heartbeat"`

---

### Task 5: Watchdog (out-of-process alerting)

**Files:**
- Create: `src/ops/__init__.py`, `src/ops/watchdog.py`, `scripts/watchdog.py`
- Modify: `config/settings.yaml` (new `watchdog:` block), `src/common/config.py` (`WatchdogCfg`)
- Test: `tests/test_watchdog.py`

**Interfaces:**
- Consumes: `SCAN_COMPLETED_KEY`, `MONITOR_HEARTBEAT_KEY`, `"command_drain_heartbeat"` from `system_settings`; `is_rth()`/`is_trading_day()` from `src/common/market_hours.py`; `latest_obs_dates()`.
- Produces:
  - `Check = NamedTuple(name: str, ok: bool, detail: str)`
  - `run_checks(now: datetime, cfg: WatchdogCfg) -> list[Check]`
  - `decide_alerts(checks, state: dict, now) -> tuple[list[str], dict]` (messages to send, new state)
  - `send_telegram(text: str) -> bool` (plain text, no parse_mode)
  - `main() -> int`

**Checks** (each is a pure function taking its inputs, so it's testable without a DB):

| name | fails when |
|---|---|
| `supervisor` | no process matching `scripts.start` (via `pgrep -f "scripts.start"`) |
| `gateway_port` | TCP connect to `127.0.0.1:{ibkr_port}` refused/times out (2 s) |
| `command_drain` | `command_drain_heartbeat` older than `watchdog.heartbeat_max_age_minutes` (default 10) |
| `monitor` | `monitor_heartbeat` older than the same limit, **only during RTH** |
| `scan_loop` | during RTH on a trading day, and more than `scan_grace_minutes` (default 20) after the open: `intraday_scan_completed` older than `scan_max_age_minutes` (default 35) |
| `iv_history` | any universe∪held symbol's latest `iv_history.obs_date` more than `iv_max_stale_trading_days` (default 3) trading days old. Evaluated once per day and reported in one message listing the symbols |

**Alert state machine** (`data/watchdog_state.json`): send on an ok→fail transition. While a check keeps failing, re-send every `realert_minutes` (default 60). Send "✅ recovered: <name>" on fail→ok. When `watchdog.deadman_url` is set, GET it on every run where all checks pass (optional external dead-man switch, e.g. healthchecks.io). That's the only thing that can notice the Mac itself being off or asleep. Document this limitation.

- [x] **Step 1: Write the failing tests** (`tests/test_watchdog.py`)

```python
from datetime import UTC, datetime, timedelta

from src.ops.watchdog import Check, decide_alerts, heartbeat_check, scan_loop_check

NOW = datetime(2026, 9, 29, 15, 0, tzinfo=UTC)  # 11:00 ET, a Tuesday


def test_heartbeat_check_fails_when_stale():
    c = heartbeat_check("monitor", (NOW - timedelta(minutes=30)).isoformat(), NOW, max_age_min=10)
    assert c.ok is False and "30 min" in c.detail


def test_heartbeat_check_fails_when_missing():
    assert heartbeat_check("monitor", None, NOW, max_age_min=10).ok is False


def test_scan_loop_check_only_applies_in_rth():
    stale = (NOW - timedelta(hours=3)).isoformat()
    assert scan_loop_check(stale, NOW, in_rth=True, minutes_since_open=90, max_age_min=35,
                           grace_min=20).ok is False
    assert scan_loop_check(stale, NOW, in_rth=False, minutes_since_open=0, max_age_min=35,
                           grace_min=20).ok is True
    assert scan_loop_check(stale, NOW, in_rth=True, minutes_since_open=10, max_age_min=35,
                           grace_min=20).ok is True  # inside the post-open grace window


def test_decide_alerts_transition_realert_and_recovery():
    fail = [Check("scan_loop", False, "no completed scan for 40 min")]
    msgs, state = decide_alerts(fail, {}, NOW, realert_minutes=60)
    assert len(msgs) == 1 and "scan_loop" in msgs[0]
    msgs, state = decide_alerts(fail, state, NOW + timedelta(minutes=10), realert_minutes=60)
    assert msgs == []  # still failing, inside the re-alert window
    msgs, state = decide_alerts(fail, state, NOW + timedelta(minutes=61), realert_minutes=60)
    assert len(msgs) == 1
    ok = [Check("scan_loop", True, "")]
    msgs, state = decide_alerts(ok, state, NOW + timedelta(minutes=70), realert_minutes=60)
    assert len(msgs) == 1 and "recovered" in msgs[0]


def test_send_telegram_uses_plain_text(monkeypatch):
    from src.ops import watchdog

    sent = {}

    class _Resp:
        status_code = 200

    def fake_post(url, json, timeout):
        sent.update(json)
        return _Resp()

    monkeypatch.setattr(watchdog.httpx, "post", fake_post)
    monkeypatch.setattr(watchdog, "_telegram_target", lambda: ("TOKEN", "CHAT", "2"))
    assert watchdog.send_telegram("hello (world).") is True
    assert "parse_mode" not in sent and sent["text"].startswith("🐕")
```

- [x] **Step 2: Run** `python -m pytest tests/test_watchdog.py -v`. Expected: FAIL (`ModuleNotFoundError: src.ops`).

- [x] **Step 3: Implement `src/ops/watchdog.py`**

```python
"""Out-of-process health watchdog — alerts when the trading stack stops doing its job.

Runs as a one-shot every ``watchdog.interval_seconds`` under launchd (``com.ibkr.watchdog``),
**never** inside the processes it watches: the 2026-09-15..22 outage went unnoticed because
the only alerting lived in the process that had stopped. It opens no IBKR connection (no
clientId), reads heartbeats from ``system_settings``, and sends plain-text Telegram messages
through the raw Bot API so a MarkdownV2 escaping bug can never silence it.
Read-only with respect to trading state; it writes only ``data/watchdog_state.json``.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

import httpx

log = logging.getLogger(__name__)
STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "watchdog_state.json"


class Check(NamedTuple):
    name: str
    ok: bool
    detail: str


def _age_minutes(iso: str | None, now: datetime) -> float | None:
    if not iso:
        return None
    ts = datetime.fromisoformat(iso)
    ts = ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    return (now - ts).total_seconds() / 60


def heartbeat_check(name: str, iso: str | None, now: datetime, *, max_age_min: int) -> Check:
    age = _age_minutes(iso, now)
    if age is None:
        return Check(name, False, f"{name}: no heartbeat recorded")
    if age > max_age_min:
        return Check(name, False, f"{name}: last heartbeat {age:.0f} min ago (limit {max_age_min})")
    return Check(name, True, "")


def scan_loop_check(iso: str | None, now: datetime, *, in_rth: bool, minutes_since_open: float,
                    max_age_min: int, grace_min: int) -> Check:
    if not in_rth or minutes_since_open < grace_min:
        return Check("scan_loop", True, "")
    age = _age_minutes(iso, now)
    if age is None or age > max_age_min:
        shown = "never" if age is None else f"{age:.0f} min ago"
        return Check("scan_loop", False, f"scan_loop: last completed intraday scan {shown} "
                                         f"(limit {max_age_min} min during RTH)")
    return Check("scan_loop", True, "")


def port_check(port: int) -> Check:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return Check("gateway_port", True, "")
    except OSError as exc:
        return Check("gateway_port", False, f"gateway_port: 127.0.0.1:{port} unreachable ({exc})")


def supervisor_check() -> Check:
    r = subprocess.run(["pgrep", "-f", "scripts.start"], capture_output=True, text=True)
    ok = r.returncode == 0 and bool(r.stdout.strip())
    return Check("supervisor", ok, "" if ok else "supervisor: scripts.start is not running")


def decide_alerts(checks: list[Check], state: dict, now: datetime, *,
                  realert_minutes: int) -> tuple[list[str], dict]:
    msgs: list[str] = []
    new = dict(state)
    for c in checks:
        prev = state.get(c.name, {})
        if not c.ok:
            last = prev.get("last_alert")
            due = (not prev.get("failing")) or (
                last and now - datetime.fromisoformat(last) >= timedelta(minutes=realert_minutes)
            )
            if due:
                msgs.append(f"⚠️ {c.detail}")
                new[c.name] = {"failing": True, "last_alert": now.isoformat()}
            else:
                new[c.name] = {**prev, "failing": True}
        else:
            if prev.get("failing"):
                msgs.append(f"✅ recovered: {c.name}")
            new[c.name] = {"failing": False}
    return msgs, new


def _telegram_target() -> tuple[str, str, str]:
    from src.common.config import get_config

    s = get_config().secrets
    return s.telegram_bot_token, s.telegram_chat_id, s.telegram_thread_scan


def send_telegram(text: str) -> bool:
    token, chat, thread = _telegram_target()
    if not token or not chat:
        log.error("watchdog: Telegram not configured")
        return False
    body: dict = {"chat_id": chat, "text": f"🐕 Watchdog\n{text}"}
    if thread:
        body["message_thread_id"] = int(thread)
    try:
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json=body, timeout=10)
        return r.status_code == 200
    except httpx.HTTPError:
        log.exception("watchdog: Telegram send failed")
        return False
```

Also add `iv_history_check(now, max_stale_trading_days) -> Check`, built on `latest_obs_dates` and the trading-day count from `market_hours.is_trading_day`, and `run_checks(now, cfg) -> list[Check]`, which reads settings with `get_setting` and composes the checks above. `main()` loads `STATE_PATH` (a missing or corrupt file gives `{}`), runs the checks, runs `decide_alerts`, sends each message, writes the state back, pings `deadman_url` when every check is ok, and returns 0. Wrap everything in `try/except` that tries to `send_telegram("watchdog crashed: …")`, so the watchdog never dies silently.

`scripts/watchdog.py`:

```python
"""One-shot health check — run by launchd every 5 min (see ./ibkr install)."""

from src.common.logging import setup_logging
from src.ops.watchdog import main

if __name__ == "__main__":
    setup_logging("watchdog")
    raise SystemExit(main())
```

(Match the real logging helper name in `src/common/logging.py`.)

`config/settings.yaml`:

```yaml
# Out-of-process watchdog (src/ops/watchdog.py), run by launchd every interval_seconds.
watchdog:
  interval_seconds: 300
  heartbeat_max_age_minutes: 10
  scan_max_age_minutes: 35       # two 15-min cycles + slack
  scan_grace_minutes: 20         # ignore the first minutes after the open
  iv_max_stale_trading_days: 3
  realert_minutes: 60
  deadman_url: ""                # optional: e.g. a healthchecks.io ping URL — catches the Mac being off
```

Add a matching `WatchdogCfg` pydantic model in `src/common/config.py` and wire it into `Config`, following the `AutomationCfg` pattern.

- [x] **Step 4: Run** `python -m pytest tests/test_watchdog.py tests/test_config_keys.py -v`. Expected: PASS.

- [x] **Step 5: Manual smoke:** `python -m scripts.watchdog` with the stack stopped should send a Telegram message naming `supervisor`. Run it again immediately: no message (inside the re-alert window).

- [x] **Step 6: Docs:** `README.md` layout table (`src/ops/`, `scripts/watchdog.py`); `ARCHITECTURE.md` folder guide + config section (`watchdog:`); `STATUS.md` (built; limitation: can't detect a powered-off Mac unless `deadman_url` is set).

- [x] **Step 7: Commit**

```bash
git add src/ops scripts/watchdog.py src/common/config.py config/settings.yaml tests/test_watchdog.py README.md ARCHITECTURE.md STATUS.md
git commit -m "feat(ops): out-of-process watchdog with plain-text Telegram alerts and recovery notices"
```

---

### Task 6: launchd agents + the single `./ibkr` control script

**Files:**
- Create: `scripts/launchd.py`, `ibkr` (repo root, `chmod +x`)
- Test: `tests/test_launchd.py`

**Interfaces:**
- Consumes: `scripts/start.py` (supervisor, unchanged), `scripts/watchdog.py`, `scripts/ibc/start_gateway.sh`
- Produces: `render_plists(repo: Path, python: Path, *, with_gateway: bool, watchdog_interval: int) -> dict[str, bytes]` (label → plist bytes); labels `com.ibkr.supervisor`, `com.ibkr.watchdog`, `com.ibkr.gateway`

**Agent design:**

| Label | Program | Key settings |
|---|---|---|
| `com.ibkr.supervisor` | `/usr/bin/caffeinate -i -s <venv>/bin/python -m scripts.start` | `RunAtLoad`, `KeepAlive=true`, `ThrottleInterval=30`, `WorkingDirectory=<repo>`, stdout/stderr → `logs/launchd-supervisor.log`, `EnvironmentVariables.PATH` includes `/opt/homebrew/bin:/usr/local/bin` (so `ollama` resolves). `caffeinate -i -s` prevents idle and system sleep while the stack runs on AC power. |
| `com.ibkr.watchdog` | `<venv>/bin/python -m scripts.watchdog` | `RunAtLoad`, `StartInterval=watchdog.interval_seconds`, logs → `logs/watchdog.log` |
| `com.ibkr.gateway` (opt-in: `./ibkr install --with-gateway`) | `scripts/ibc/start_gateway.sh` | `RunAtLoad`, `KeepAlive=false` (IBC owns Gateway's restart cycle) |

`scripts.start` already supervises the approval service, monitor, API, research worker and EOD, and kills strays on boot. launchd only has to keep **it** alive.

**`./ibkr` subcommands:** `install [--with-gateway]`, `uninstall`, `start`, `stop`, `restart`, `status`, `logs [approval|monitor|api|research|eod|watchdog|supervisor]`, `watchdog` (run a check now), `autonomy [level]` (Task 12). Everything except `npm run dev`.

- [x] **Step 1: Write the failing tests** (`tests/test_launchd.py`)

```python
import plistlib
from pathlib import Path

from scripts.launchd import render_plists


def test_render_supervisor_and_watchdog(tmp_path):
    out = render_plists(tmp_path, tmp_path / ".venv/bin/python", with_gateway=False,
                        watchdog_interval=300)
    assert set(out) == {"com.ibkr.supervisor", "com.ibkr.watchdog"}
    sup = plistlib.loads(out["com.ibkr.supervisor"])
    assert sup["KeepAlive"] is True and sup["RunAtLoad"] is True
    assert sup["ProgramArguments"][:3] == ["/usr/bin/caffeinate", "-i", "-s"]
    assert sup["ProgramArguments"][-2:] == ["-m", "scripts.start"]
    assert sup["WorkingDirectory"] == str(tmp_path)
    wd = plistlib.loads(out["com.ibkr.watchdog"])
    assert wd["StartInterval"] == 300 and wd["ProgramArguments"][-1] == "scripts.watchdog"


def test_render_with_gateway_is_opt_in(tmp_path):
    out = render_plists(tmp_path, tmp_path / "py", with_gateway=True, watchdog_interval=300)
    gw = plistlib.loads(out["com.ibkr.gateway"])
    assert gw["KeepAlive"] is False
    assert gw["ProgramArguments"][0].endswith("scripts/ibc/start_gateway.sh")


def test_control_script_exists_and_is_executable():
    p = Path(__file__).resolve().parents[1] / "ibkr"
    assert p.exists() and p.stat().st_mode & 0o111
```

- [x] **Step 2: Run** `python -m pytest tests/test_launchd.py -v`. Expected: FAIL.

- [x] **Step 3: Implement `scripts/launchd.py`**: `render_plists` (built with `plistlib.dumps`, no string templates), plus a CLI:
  - `install`: writes to `~/Library/LaunchAgents/<label>.plist`, then `launchctl bootstrap gui/$UID <plist>`; if already loaded, `bootout` first.
  - `uninstall`: `bootout` then delete.
  - `start` / `stop`: `launchctl kickstart -k gui/$UID/<label>` / `launchctl bootout …`.
  - `status`: `launchctl print gui/$UID/<label>`, summarised to state and pid, then prints the `/system/status`-equivalent heartbeat ages via `src.ops.watchdog.run_checks`.

- [x] **Step 4: Implement `ibkr`** (bash, `set -euo pipefail`). It resolves `REPO` from `BASH_SOURCE`, uses `.venv/bin/python`, and dispatches:
  - `install|uninstall|start|stop|restart|status` → `python -m scripts.launchd <cmd> "$@"`
  - `logs` → `tail -F logs/<name>.log`
  - `watchdog` → `python -m scripts.watchdog`
  - `autonomy` → `python -m scripts.autonomy "$@"` (Task 12)
  - no args → usage

  `restart` = `stop` then `start`. Before `install`, refuse if a non-launchd `scripts.start` is already running (`pgrep -f scripts.start` while the supervisor label isn't loaded) and print "stop the terminal-launched stack first (Ctrl-C)". Two supervisors would fight over clientIds.

- [x] **Step 5: Run** `python -m pytest tests/test_launchd.py tests/test_start_launcher.py -v`. Expected: PASS.

- [x] **Step 6: Live verification**
  1. Stop any terminal-run stack. Run `./ibkr install`, then `./ibkr status`: supervisor running with a pid, watchdog loaded.
  2. `kill <supervisor pid>`. Within ~30 s, `./ibkr status` shows a **new** pid (KeepAlive worked).
  3. `./ibkr stop`. Within 5 min a Telegram "⚠️ supervisor: scripts.start is not running" arrives. `./ibkr start` then gives "✅ recovered: supervisor".

- [x] **Step 7: Docs:** `SETUP.md` — a new "Run it as a background service (launchd)" section with every `./ibkr` subcommand, the caffeinate/AC-power note, and the `deadman_url` suggestion. Scripts table rows for `./ibkr`, `scripts.launchd`, `scripts.watchdog`. `README.md` quick start uses `./ibkr install`, and the layout table gets `ibkr`. `ARCHITECTURE.md` process model (launchd → scripts.start → children; watchdog separate).

- [x] **Step 8: Commit**

```bash
git add ibkr scripts/launchd.py tests/test_launchd.py SETUP.md README.md ARCHITECTURE.md
git commit -m "feat(ops): launchd supervisor + watchdog agents and a single ./ibkr control script"
```

---

### Task 7: Split `illiquid` into precise, logged sub-reasons

**Files:**
- Modify: `src/analytics/liquidity.py`, `src/strategies/_evaluation.py`, `src/strategies/cash_secured_put.py:137-139`, `src/strategies/covered_call.py:171-173`
- Modify: `src/common/schemas.py` (`TradeCandidate`), `src/storage/models.py` (`RiskVerdictRow.liquidity`), `src/storage/db.py` (`_ADDED_COLUMNS["risk_verdicts"]["liquidity"] = "JSON"`), `src/storage/risk_verdicts.py:_to_row`
- Modify: `src/notify/formatters.py:~561`, `src/api/routers/options.py:~93`
- Test: `tests/test_analytics.py`, `tests/test_strategies.py`, `tests/test_risk_verdicts_store.py`, `tests/test_reason_label_parity.py` (already enforces parity)

**Interfaces:**
- Produces: `liquidity_failures(quote: OptionQuote, *, enforce_volume: bool = True) -> list[str]`; `passes_liquidity_gates(...)` becomes `not liquidity_failures(...)` (same signature, `rolling.py` unchanged); `TradeCandidate.quote_bid/quote_ask/open_interest/option_volume: float|int|None = None`; `RiskVerdictRow.liquidity: dict | None`

**Reason codes** (evaluated in this order; **all** that apply are emitted):

| Code | Condition | Label |
|---|---|---|
| `illiquid_no_quote` | bid or ask is None/≤0 for ask, so spread can't be computed | "liquidity: no usable bid/ask to measure spread" |
| `illiquid_zero_bid` | bid == 0 and ask > 0 (spread is 200% by construction) | "liquidity: zero bid (no buyer at any price)" |
| `illiquid_spread_wide` | spread_pct > `max_bid_ask_spread_pct` | "liquidity: bid/ask spread wider than limit" |
| `illiquid_oi_missing` | open_interest is None | "liquidity: open interest not reported" |
| `illiquid_oi_low` | OI < `min_open_interest` | "liquidity: open interest below minimum" |
| `illiquid_volume_missing` | volume gate enforced and volume None | "liquidity: day volume not reported" |
| `illiquid_volume_low` | volume gate enforced and volume < `min_option_volume` | "liquidity: day volume below minimum" |

Keep the legacy `"illiquid"` label in both tables, because 14 days of existing `risk_verdicts` rows still carry it.

- [x] **Step 1: Write the failing tests** (`tests/test_analytics.py`)

```python
from datetime import date, timedelta

import pytest

from src.analytics.liquidity import liquidity_failures, passes_liquidity_gates
from src.common.schemas import OptionQuote, OptionRight


def _q(**kw) -> OptionQuote:
    base = dict(underlying="X", right=OptionRight.PUT, strike=10.0,
                expiry=date.today() + timedelta(days=14), bid=1.00, ask=1.04,
                open_interest=500, volume=50)
    base.update(kw)
    return OptionQuote(**base)


@pytest.mark.parametrize("kw,expected", [
    (dict(bid=None), ["illiquid_no_quote"]),
    (dict(bid=0.0, ask=0.05), ["illiquid_zero_bid", "illiquid_spread_wide"]),
    (dict(bid=1.00, ask=1.30), ["illiquid_spread_wide"]),
    (dict(open_interest=None), ["illiquid_oi_missing"]),
    (dict(open_interest=5), ["illiquid_oi_low"]),
    (dict(volume=None), ["illiquid_volume_missing"]),
    (dict(volume=1), ["illiquid_volume_low"]),
    (dict(), []),
])
def test_liquidity_failures_codes(kw, expected):
    assert liquidity_failures(_q(**kw)) == expected


def test_volume_codes_suppressed_before_cutoff():
    assert liquidity_failures(_q(volume=None), enforce_volume=False) == []


def test_passes_gate_is_negation():
    assert passes_liquidity_gates(_q()) is True
    assert passes_liquidity_gates(_q(open_interest=5)) is False
```

In `tests/test_strategies.py`, add one test per generator: a put quote with OI=5 produces a rejected candidate whose reasons contain `"illiquid_oi_low"` and **not** `"illiquid"`, and whose `open_interest == 5`. Build the fixture exactly as the neighbouring CSP generator tests do.

In `tests/test_risk_verdicts_store.py`: a recorded assessment writes `liquidity == {"bid": …, "ask": …, "spread_pct": …, "open_interest": 5, "volume": …}`.

- [x] **Step 2: Run** `python -m pytest tests/test_analytics.py tests/test_strategies.py tests/test_risk_verdicts_store.py -k "liquidity or illiquid" -v`. Expected: FAIL.

- [x] **Step 3: Implement**

```python
def liquidity_failures(quote: OptionQuote, *, enforce_volume: bool = True) -> list[str]:
    """Every liquidity gate *quote* fails, as precise reason codes (empty = passes).

    Replaces a bare bool that collapsed five distinct failure modes into one ``illiquid``
    code, which made "SOXL failed liquidity 684 times" impossible to act on (2026-09 post-
    mortem). Missing data fails its gate (conservative default), but gets its own *_missing
    code so an IBKR data gap is distinguishable from a genuinely thin contract.
    """
    cfg = get_config().risk["liquidity"]
    out: list[str] = []
    if quote.bid is None or quote.ask is None or quote.ask <= 0:
        out.append("illiquid_no_quote")
    else:
        if quote.bid == 0:
            out.append("illiquid_zero_bid")
        spread = quote.spread_pct
        if spread is None or spread > cfg["max_bid_ask_spread_pct"]:
            out.append("illiquid_spread_wide")
    if quote.open_interest is None:
        out.append("illiquid_oi_missing")
    elif quote.open_interest < cfg["min_open_interest"]:
        out.append("illiquid_oi_low")
    if enforce_volume:
        if quote.volume is None:
            out.append("illiquid_volume_missing")
        elif quote.volume < cfg["min_option_volume"]:
            out.append("illiquid_volume_low")
    return out


def passes_liquidity_gates(quote: OptionQuote, *, enforce_volume: bool = True) -> bool:
    """True iff the quote clears every liquidity gate. See :func:`liquidity_failures`."""
    return not liquidity_failures(quote, enforce_volume=enforce_volume)
```

In both generators, replace the two-line `passes_liquidity_gates → REASON_ILLIQUID` with `reasons.extend(liquidity_failures(quote, enforce_volume=enforce_volume))`. Set `quote_bid=quote.bid, quote_ask=quote.ask, open_interest=quote.open_interest, option_volume=quote.volume` on the `TradeCandidate`. Keep `REASON_ILLIQUID` in `_evaluation.py` as a legacy constant with a comment. `ScreenResult.market_data_outage` is unchanged (it keys on `no_two_sided_market`).

`_to_row`: `liquidity={"bid": cand.quote_bid, "ask": cand.quote_ask, "spread_pct": <computed or None>, "open_interest": cand.open_interest, "volume": cand.option_volume}`.

Add the 7 labels to **both** `formatters._REJECT_REASON_LABELS` and `options.py`'s table.

The generators' existing aggregate WARNING line (`rejections: …`) automatically shows the granular codes. Extend it with the threshold values once per symbol: `(limits: spread≤10%, OI≥100, vol≥10, volume gate on)`.

- [x] **Step 4: Run** `python -m pytest tests/test_analytics.py tests/test_strategies.py tests/test_risk_verdicts_store.py tests/test_reason_label_parity.py tests/test_assessed_contracts.py tests/test_storage_db_migrations.py -v`. Expected: PASS. If fixtures assert the literal `"illiquid"` on *newly generated* rejects, update them to the granular code. Leave read-side fixtures on legacy rows alone.

- [x] **Step 5: Docs:** `ARCHITECTURE.md` src/analytics (liquidity codes), src/storage (`risk_verdicts.liquidity` column), data-flow (`TradeCandidate` new optional fields). `How the scan works.md`: a short "reading rejection codes" note.

- [x] **Step 6: Commit**

```bash
git add src/analytics/liquidity.py src/strategies src/common/schemas.py src/storage src/notify/formatters.py src/api/routers/options.py tests ARCHITECTURE.md "How the scan works.md"
git commit -m "feat(scan): split illiquid into 7 precise liquidity codes and persist quote microstructure"
```

---

### Task 8: Expire stale approval cards

**Files:**
- Create: `src/storage/approvals.py`
- Modify: `src/notify/approval_service.py:1013-1020` (`_order_poll_loop`), `:974-1010` (`/expire` reuses the helper)
- Test: `tests/test_execution.py` (or a new `tests/test_storage_approvals.py`)

**Interfaces:**
- Produces: `expire_stale_approvals(now: datetime | None = None) -> int`: flips `pending` rows with `expires_at < now` (or a NULL `expires_at` older than `approval.ttl_minutes`) to `expired`, sets `decided_at=now`, returns the count. It never touches `approved` rows (those belong to `process_queued_orders`).

- [x] **Step 1: Write the failing test** (`tests/test_storage_approvals.py`; reuse the `_db_setup` fixture pattern from `tests/test_autonomy.py`)

```python
from datetime import UTC, datetime, timedelta


def test_expire_stale_approvals_only_touches_pending_past_ttl(db):
    from src.storage.approvals import expire_stale_approvals
    from src.storage.db import session_scope
    from src.storage.models import ApprovalRow

    now = datetime(2026, 9, 29, tzinfo=UTC)
    with session_scope() as s:
        s.add_all([
            ApprovalRow(candidate_id="a", status="pending", expires_at=now - timedelta(minutes=1)),
            ApprovalRow(candidate_id="b", status="pending", expires_at=now + timedelta(minutes=30)),
            ApprovalRow(candidate_id="c", status="approved", expires_at=now - timedelta(days=1)),
        ])
    assert expire_stale_approvals(now) == 1
    with session_scope() as s:
        by = {r.candidate_id: r.status for r in s.query(ApprovalRow)}
    assert by == {"a": "expired", "b": "pending", "c": "approved"}
```

- [x] **Step 2: Run**. Expected: FAIL (`ModuleNotFoundError`).

- [x] **Step 3: Implement** `src/storage/approvals.py` with a module docstring explaining R6. Call it at the top of each `_order_poll_loop` iteration (cheap: one UPDATE on an indexed status). Log at INFO only when count > 0.

- [x] **Step 4: One-off cleanup** after deploy: the first poll cycle flips the 33 historical rows. Verify with `sqlite3 data/income_system.db "select status,count(*) from approvals group by 1"`. Expected: no `pending` row past `expires_at`.

- [x] **Step 5: Docs:** `ARCHITECTURE.md` src/storage (new module) + src/notify (poll loop sweep); `README.md` layout table row.

- [x] **Step 6: Commit** `git commit -m "fix(approvals): sweep untapped approvals past TTL to expired"`

---

### Task 9: Missing IV rank is neutral, not zero

**Files:**
- Modify: `src/strategies/cash_secured_put.py:~205` and `src/strategies/covered_call.py` (same `iv_score=` line)
- Modify: `config/scoring_weights.yaml` (new key `missing_iv_rank_score: 50`)
- Test: `tests/test_strategies.py`

**Why:** A missing IV rank already passes the IV gate as "data unavailable" (it never blocks). Scoring it as 0 under a 30% weight contradicts that and silently sinks the name (R7). Neutral mirrors how missing sentiment is treated in `engine/scoring.py`. The `iv_rank_unavailable` rationale tag makes the gap visible on the card. With Task 4 and the watchdog's `iv_history` check, this should now be rare. The value lives in YAML so a human can set it back to 0.

- [x] **Step 1: Failing test:** build a CSP via the generator with `IVStats(iv_rank=None)`. Assert `scores.iv_score == 50.0` and `"iv_rank_unavailable" in candidate.rationale_tags`. Same for CC.
- [x] **Step 2: Run**. Expected: FAIL (`iv_score == 0.0`).
- [x] **Step 3: Implement:**
  - Read `get_config().weights.get("missing_iv_rank_score", 50.0)` and use it when `iv_stats.iv_rank is None`.
  - Append the tag where rationale tags are assembled.
  - Add to `scoring_weights.yaml`, with a comment citing R7:

  ```yaml
  # Score used for the IV component when a symbol has no IV rank (no/flat iv_history).
  # Neutral by design: missing IV rank already passes the IV gate as "data unavailable";
  # scoring it 0 under a 30% weight silently sank TQQQ/UPRO/MAGS/BAC (2026-09). 0 = old behaviour.
  missing_iv_rank_score: 50
  ```

- [x] **Step 4: Run** `python -m pytest tests/test_strategies.py tests/test_config_keys.py tests/test_engine.py -v`. Expected: PASS.
- [x] **Step 5: Docs:** `ARCHITECTURE.md` config section; `STATUS.md` known-limitations. Add the finding-8 explanation (the "Decision on the score floor" paragraph above, with the component arithmetic) to `How the scan works.md` under a "Why a name misses the score floor" heading.
- [x] **Step 6: Commit** `git commit -m "fix(scoring): missing IV rank scores neutral (configurable) and tags the card"`

---

### Task 10: Ollama review — structured output, FACTS block, rubric

**Files:**
- Modify: `src/claude/ollama_runner.py:112-146` (`_generate`), `src/claude/parser.py:112-133` (`_parse_reviews`), `src/claude/prompts/strategist.py:317-534`
- Create: `scripts/review_eval.py`
- Test: `tests/test_ollama_runner.py`, `tests/test_claude.py`

**Interfaces:**
- Produces:
  - `REVIEW_SCHEMA: dict` (JSON schema, `{"reviews": [ClaudeReview-shaped]}`) in `ollama_runner.py`
  - `_candidate_facts(c: TradeCandidate, spot: float | None) -> list[str]` in `strategist.py`
  - `ClaudeReview.summary` is requested for every candidate, not just single-ticker scans
  - New `ClaudeReview.evidence: list[str] = []` (fact/news ids the verdict cites)

- [x] **Step 1: Write the failing tests**

`tests/test_claude.py`:

```python
def test_parse_reviews_accepts_reviews_wrapper():
    from src.claude.parser import parse_ollama_review_output

    raw = ('{"reviews": [{"candidate_id": "a", "priority": 1, "recommendation": "sell", '
           '"why_attractive": "x", "risks": "y", "tradeoffs": "z", '
           '"assignment_considerations": "w"}, {"candidate_id": "b", "priority": 2, '
           '"recommendation": "wait", "why_attractive": "x", "risks": "y", "tradeoffs": "z", '
           '"assignment_considerations": "w"}]}')
    assert [r.candidate_id for r in parse_ollama_review_output(raw)] == ["a", "b"]


def test_facts_state_moneyness_and_earnings_relative_to_expiry():
    from datetime import date

    from src.claude.prompts.strategist import _candidate_facts

    c = _make_csp(strike=720.0, expiry=date(2026, 9, 30), premium=8.75,
                  next_earnings=date(2026, 10, 29))  # use the file's existing candidate factory
    facts = "\n".join(_candidate_facts(c, spot=744.10))
    assert "F1" in facts and "3.2% BELOW spot" in facts and "out-of-the-money" in facts
    assert "AFTER expiry" in facts and "no earnings inside this trade" in facts
```

`tests/test_ollama_runner.py`:

```python
def test_generate_sends_json_schema_format(monkeypatch):
    from src.claude import ollama_runner

    sent = {}

    class _R:
        def raise_for_status(self): ...
        def json(self): return {"response": '{"reviews": []}'}

    monkeypatch.setattr(ollama_runner.httpx, "post", lambda url, json, timeout: sent.update(json) or _R())
    ollama_runner._generate("p", ollama_runner.get_config().claude)
    assert sent["format"]["type"] == "object" and "reviews" in sent["format"]["properties"]
```

- [x] **Step 2: Run** `python -m pytest tests/test_claude.py tests/test_ollama_runner.py -k "wrapper or facts or schema" -v`. Expected: FAIL.

- [x] **Step 3: Implement**

1. **Structured output.** `_generate(prompt, cfg, schema: dict | None = REVIEW_SCHEMA)` sends `"format": schema`. Ollama ≥0.5 grammar-constrains to a JSON schema, and the installed version is 0.33.2. Roll and EOD callers pass their own schemas, or `"json"` as before.

   ```python
   _REVIEW_ITEM = {
       "type": "object",
       "properties": {
           "candidate_id": {"type": "string"},
           "priority": {"type": "integer"},
           "recommendation": {"type": "string", "enum": ["sell", "wait", "skip"]},
           "why_attractive": {"type": "string"}, "risks": {"type": "string"},
           "tradeoffs": {"type": "string"}, "assignment_considerations": {"type": "string"},
           "rolling_considerations": {"type": "string"}, "summary": {"type": "string"},
           "evidence": {"type": "array", "items": {"type": "string"}},
           "confidence": {"type": "number"},
       },
       "required": ["candidate_id", "priority", "recommendation", "why_attractive", "risks",
                    "tradeoffs", "assignment_considerations", "summary", "evidence"],
   }
   REVIEW_SCHEMA = {"type": "object", "properties": {"reviews": {"type": "array",
                    "items": _REVIEW_ITEM}}, "required": ["reviews"]}
   ```

2. **Parser.** In `_parse_reviews`, when the payload is a dict with a `"reviews"` list, use that list. Then drop reviews whose `candidate_id` isn't in the requested set, and log how many requested ids came back unreviewed (`"ollama: reviewed %d/%d candidates"`).

3. **FACTS block.** `_candidate_facts` returns numbered, deterministic lines computed in Python so the model never derives them:
   - `F1 Strike $720.00 is 3.2% BELOW spot $744.10 → out-of-the-money put` (CALL: ABOVE/BELOW with the correct OTM/ITM wording)
   - `F2 Breakeven $711.25 = 4.4% cushion below spot`
   - `F3 Earnings 2026-10-29 is AFTER expiry 2026-09-30 → no earnings inside this trade` / `… is INSIDE this trade (N days before expiry) → event risk`
   - `F4 Credit $8.75 vs fair-value floor $8.39 → +4% edge over the variance-risk-premium floor` (from `c.ideal.min_credit` when present)
   - `F5 IV rank 100 → premium is RICH vs its own year` (buckets: <30 thin, 30–60 normal, >60 rich)
   - `F6 IV/RV 1.16 → options priced above realised movement` (when present)
   - `F7 Passed every deterministic gate (delta, liquidity, fair value, IV, earnings blackout, concentration)`

   Add `c.spot` via the existing `spot_prices` map.

4. **Rubric** (replaces the bare `"<sell | wait | skip>"`, inserted before YOUR TASK):

   ```
   === DECISION RUBRIC ===
   Every candidate below already PASSED the deterministic Rules Engine (F7). Default to "sell"
   unless you can cite a specific FACT (F#) or NEWS item (N#) that argues otherwise:
     sell — no concrete red flag inside this trade's window. Most gate-passing trades are "sell".
     wait — a dated catalyst falls INSIDE this trade (earnings per F3, a scheduled event in NEWS)
            that should pass first. Name it.
     skip — NEWS shows a thesis-breaking development (guidance cut, fraud, delisting, M&A) that
            makes being assigned undesirable. Name it.
   Put the F#/N# ids you relied on in "evidence". Do not restate numbers that are not in FACTS.
   Earnings dated AFTER expiry are NOT a risk to this trade.
   ```

5. Change the output contract to `Return ONLY {"reviews": [ … one object per candidate … ]}`, and request `summary` (2–3 sentences, plain English) for every candidate. Keep the single-ticker SUMMARY GUIDE as the longer variant.

6. **`scripts/review_eval.py`.** It replays stored `candidates` rows (default: every row since 2026-09-14, or `--ids`) through `ollama_runner.review_candidates` with `--model` and `--runs N`, then prints the per-candidate verdicts, the verdict distribution, how many candidates came back reviewed vs requested, and how many reviews had empty `evidence`. It is read-only (no DB writes) and bypasses the circuit breaker.

- [x] **Step 4: Run** `python -m pytest tests/test_claude.py tests/test_ollama_runner.py tests/test_scan_review_reuse.py tests/test_output_fidelity.py -v`. Expected: PASS.

- [x] **Step 5: Evaluate against the baseline** (Ollama running)

Run: `ollama pull qwen3.5:4b && ollama pull qwen3.5:9b && ollama pull gemma4:e4b-it-qat`, then `python -m scripts.review_eval --runs 2 --model <m>` for each of `qwen3:8b`, `qwen3.5:4b`, `qwen3.5:9b`, `gemma4:e4b-it-qat`. Quit Chrome tabs you don't need while doing it; the eval loads one model at a time.
Baseline (2026-09-29, old prompt): 6/6 "wait" on single-candidate prompts; 1/3 candidates reviewed on the multi-candidate prompt.
Expected after: every requested candidate reviewed, not all verdicts "wait", `evidence` non-empty on ≥90% of reviews, and no review calling an OTM put "in the money". Record every model's results in the commit message.

**Model choice is constrained by RAM (measured 2026-09-29):**
- The M3 Pro has 18 GB, ~14 GB of RSS is already in use (Chrome ~4.4 GB, VS Code ~3.2 GB, Gateway, Telegram, Claude), and **7.0 of 8 GB of swap is in use** before any model loads.
- **`qwen3:14b` is ruled out.** It needs ~9.3 GB of weights plus ~2.7 GB KV cache at 16k context, about 12 GB.

| Model | Download | Why try it |
|---|---|---|
| `qwen3:8b` (current) | 5.2 GB | baseline |
| `qwen3.5:4b` | 3.4 GB | newer generation, tools + thinking; saves ~1.8 GB |
| `qwen3.5:9b` | 6.6 GB | newer generation, tools + thinking; +1.4 GB over current |
| `gemma4:e4b-it-qat` | 6.1 GB | native function calling and structured output |

Pick the **smallest** model that meets the bar above. Whatever the model:
- **`claude.ollama_num_ctx: 8192`** halves the KV cache (~1.2 GB saved on an 8B model). Verify the longest eval prompt's `prompt_eval_count` stays below it.
- **`claude.ollama_keep_alive: "2m"`** unloads the model between 15-minute cycles instead of keeping it resident for 10 of every 15 minutes, at the cost of a ~5 s reload.

Also try `think: true` on the final call. It costs time, not memory; keep it only if grounding improves within `ollama_timeout_seconds`. Record the decision in `STATUS.md` and update the model comment block in `config/settings.yaml`.

- [x] **Step 6: Docs:** `ARCHITECTURE.md` src/claude (schema output, FACTS, rubric, `evidence` field); data-flow for `ClaudeReview.evidence`; `SETUP.md` scripts table (`review_eval`); `STATUS.md`.

- [x] **Step 7: Commit** `git commit -m "fix(claude): schema-constrained Ollama reviews, deterministic FACTS and a sell/wait/skip rubric"`

---

### Task 11: News-grounded review — keyless news search + bounded tool-calling research turn

**Files:**
- Modify: `src/data/protocols.py` (add `NewsSearchProvider`), `src/data/factory.py` (`get_news_search_provider()`)
- Create: `src/data/google_news_backend.py`, `src/claude/news_context.py`, `src/claude/ollama_tools.py`
- Modify: `src/claude/prompts/strategist.py` (NEWS block), `src/claude/ollama_runner.py` (`review_candidates` calls research turn when enabled), `config/settings.yaml` (`claude.news_*`, `claude.tool_research_*`, `data.news_search_provider`)
- Test: `tests/test_data_providers.py`, new `tests/test_news_context.py`, `tests/test_ollama_runner.py`, `tests/test_eval_skills.py` (fence)

**Interfaces:**
- Produces:
  - `NewsItem(BaseModel): id: str, title: str, source: str | None, published: datetime | None, url: str | None` in `src/data/protocols.py`
  - `NewsSearchProvider.search(query: str, *, days: int = 7, limit: int = 10) -> list[NewsItem]` (never raises; `[]` on failure)
  - `build_news_block(symbols: list[str], *, per_symbol: int, days: int) -> tuple[str, dict[str, NewsItem]]`: the rendered `=== NEWS ===` block with ids `N1…Nk`, plus an id→item map
  - `research_turn(prompt: str, cfg) -> list[dict]`: extra chat messages (tool calls + results) to prepend to the final structured call

**Sources (all keyless, local):** Google News RSS search (`https://news.google.com/rss/search?q=<q>+when:<days>d&hl=en-US&gl=US&ceid=US:en`, parsed with stdlib `xml.etree.ElementTree`) plus the existing yfinance `get_news_provider().get_headlines(symbol)`. Dedupe by normalised title. Wrap in the existing `src/data/breaker.py` circuit breaker (`get_breaker("google_news")`) and cache in-process for 15 min per query.

**Tool-calling research turn** (`claude.tool_research_enabled`, default `true`; `claude.max_tool_rounds: 2`; `claude.tool_research_timeout_seconds: 60`):
1. POST `/api/chat` with `tools=[search_news(query: str, days: int)]`, the FACTS+NEWS prompt and the instruction: *"Before judging, you MAY call search_news up to 2 times for anything the NEWS block leaves open (e.g. '<SYMBOL> guidance', 'Fed meeting this week'). Do not call it otherwise."*
2. Execute each `tool_calls[].function` against `NewsSearchProvider.search`. Cap at 5 results per call. Results are appended as `role: "tool"` messages, with new items numbered `N{k+1}…` so the rubric's evidence ids stay valid.
3. The final call is `/api/chat` with the accumulated messages and `format=REVIEW_SCHEMA`, and **no** tools.
4. Any failure (timeout, a model without tool support, malformed call) is logged and falls back to the Task 10 single-shot path. Enrichment never becomes a dependency.

**Fence.** `src/claude/news_context.py`, `src/claude/ollama_tools.py` and `src/data/google_news_backend.py` must not be importable from `src/engine/`, `src/execution/` or `src/strategies/`. Extend the existing import-walk test in `tests/test_eval_skills.py`:

```python
_ENRICHMENT_ONLY = ("src.claude.news_context", "src.claude.ollama_tools", "src.data.google_news_backend")


def test_news_and_tool_research_never_reach_the_deterministic_layer():
    for pkg in ("src/engine", "src/execution", "src/strategies"):
        for mod in _imports_under(pkg):  # reuse the helper the neighbouring fence tests use
            assert not mod.startswith(_ENRICHMENT_ONLY), f"{pkg} imports {mod}"
```

- [x] **Step 1: Write the failing tests**

`tests/test_data_providers.py`:

```python
def test_google_news_parses_rss(monkeypatch):
    from src.data import google_news_backend as g

    rss = """<rss><channel><item><title>META beats on ads - Reuters</title>
      <link>https://x/1</link><pubDate>Mon, 28 Sep 2026 13:00:00 GMT</pubDate>
      <source>Reuters</source></item></channel></rss>"""

    class _R:
        status_code = 200
        text = rss
        def raise_for_status(self): ...

    monkeypatch.setattr(g.httpx, "get", lambda *a, **k: _R())
    items = g.GoogleNewsSearchProvider().search("META", days=7)
    assert items[0].title.startswith("META beats") and items[0].source == "Reuters"


def test_google_news_never_raises(monkeypatch):
    from src.data import google_news_backend as g

    monkeypatch.setattr(g.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(g.httpx.ConnectError("x")))
    assert g.GoogleNewsSearchProvider().search("META") == []
```

`tests/test_news_context.py`:

```python
def test_news_block_numbers_and_dedupes(monkeypatch):
    from src.claude import news_context
    from src.data.protocols import NewsItem

    dup = NewsItem(id="", title="AMZN wins cloud deal", source="A", published=None, url=None)
    monkeypatch.setattr(news_context, "_fetch", lambda sym, days, limit: [dup, dup])
    block, index = news_context.build_news_block(["AMZN"], per_symbol=5, days=7)
    assert "N1" in block and "N2" not in block and index["N1"].title == "AMZN wins cloud deal"
```

`tests/test_ollama_runner.py`: with `httpx.post` faked to return one `tool_calls` message and then a final `{"reviews": [...]}`, assert that `search_news` ran once, the second request carries **no** `tools` and does carry `format`, and the review parses. Add a second test: a `/api/chat` HTTP error in the research turn falls back to `_generate` and still returns reviews.

- [x] **Step 2: Run**. Expected: FAIL.

- [x] **Step 3: Implement** the three new modules, the factory entry (`data.news_search_provider: google_news`), the NEWS block injection in `build_prompt` (for both full-universe and single-ticker scans; per candidate symbol `claude.news_per_symbol: 5`, plus 3 market headlines for the query `"stock market today"`; `claude.news_days: 7`) and the research turn in `ollama_runner.review_candidates`. Keep the prompt within `ollama_num_ctx`: trim headlines to 140 chars and cap the NEWS block at `claude.news_max_items: 25`.

- [x] **Step 4: Run** `python -m pytest tests/test_data_providers.py tests/test_news_context.py tests/test_ollama_runner.py tests/test_eval_skills.py tests/test_web_fence.py -v`. Expected: PASS.

- [x] **Step 5: Evaluate:** run `python -m scripts.review_eval --runs 2` and confirm that reviews cite `N#` ids where news is relevant and that runtime per scan stays under `ollama_timeout_seconds × candidates`. Record the timings in the commit message.

- [x] **Step 6: Docs:** `ARCHITECTURE.md` (src/data new provider; src/claude news + tools; the analytics-tier / enrichment rules restated for the new modules; config keys); `CLAUDE.md` enrichment-tier list gets the two new `src/claude/` modules; `SETUP.md` (no key needed; how to disable with `claude.tool_research_enabled: false`); `STATUS.md`.

- [x] **Step 7: Commit** `git commit -m "feat(claude): keyless news search and a bounded tool-calling research turn for Ollama reviews"`

---

### Task 12: Paper-only promotion bypass → run on FULL autonomy

**Files:**
- Modify: `src/storage/system_settings.py:112-151` (`promotion_blockers`), `src/common/config.py` (`AutomationCfg.paper_skip_promotion_gate: bool = False`), `config/settings.yaml`
- Create: `scripts/autonomy.py` (backs `./ibkr autonomy`)
- Test: `tests/test_autonomy.py`

**Interfaces:**
- Consumes: `get_config().is_live`, `automation.paper_skip_promotion_gate`
- Produces: `promotion_blockers(target)` returns `[]` when the flag is on **and** the process is in paper mode. In live mode the flag is ignored and a warning is logged. Telegram `/autonomy`, the web `set_autonomy` drain command and `./ibkr autonomy` all go through `promotion_blockers`, so no new back door is created.

**Preconditions (do not flip until all hold):** Tasks 1, 3, 5 and 6 are deployed; `./ibkr status` is healthy; the watchdog has been silent through one full RTH session; and `automation.max_auto_trades_per_day` (10), `daily_loss_halt_pct` (3.0), `drawdown_halt_pct` (10.0) and `auto_close_enabled` (true) are unchanged. The Rules Engine, concentration caps (≤25% net liq per name) and the send-time re-validation still gate every order.

- [x] **Step 1: Write the failing tests** (`tests/test_autonomy.py`)

```python
def test_paper_bypass_clears_blockers(monkeypatch):
    from src.common.config import get_config
    from src.storage.system_settings import promotion_blockers

    cfg = get_config()
    monkeypatch.setattr(cfg.automation, "paper_skip_promotion_gate", True)
    monkeypatch.setattr(type(cfg), "is_live", property(lambda self: False))
    assert promotion_blockers(AutonomyLevel.FULL) == []


def test_bypass_ignored_when_live(monkeypatch):
    from src.common.config import get_config
    from src.storage.system_settings import promotion_blockers

    cfg = get_config()
    monkeypatch.setattr(cfg.automation, "paper_skip_promotion_gate", True)
    monkeypatch.setattr(type(cfg), "is_live", property(lambda self: True))
    assert promotion_blockers(AutonomyLevel.FULL) != []  # fresh DB: 0 fills → blocked


def test_bypass_off_by_default():
    from src.common.config import get_config

    assert get_config().automation.paper_skip_promotion_gate is False
```

(The last test pins the **code** default. `config/settings.yaml` sets it `true` for this paper run, so load a config without the key, or assert on `AutomationCfg().paper_skip_promotion_gate`.)

- [x] **Step 2: Run**. Expected: FAIL.

- [x] **Step 3: Implement.** At the top of `promotion_blockers`, after the demotion early-return:

```python
    cfg = get_config()
    if cfg.automation.paper_skip_promotion_gate:
        if cfg.is_live:
            log.warning("automation.paper_skip_promotion_gate is set but LIVE_TRADING=true — ignored")
        else:
            log.warning("Promotion evidence gate SKIPPED (paper-only override) for %s", target.value)
            return []
```

`config/settings.yaml` → `automation:`:

```yaml
  # PAPER-ONLY: skip the autonomy promotion evidence gate (>=20 fills, >=60% fill rate, >=1 close)
  # so the paper account can run on FULL to observe end-to-end behaviour. Ignored — with a
  # warning — whenever LIVE_TRADING=true. Set back to false before any live cutover.
  paper_skip_promotion_gate: true
```

`scripts/autonomy.py`: `python -m scripts.autonomy` prints the level and blockers. `python -m scripts.autonomy full` checks `promotion_blockers` and calls `set_autonomy_level`, printing the result. It refuses with the blocker list otherwise.

Add a `STATUS.md` **live-cutover gate** line: "`automation.paper_skip_promotion_gate` must be `false`". Add an assertion for the same thing in `tests/test_live_cutover.py` if that file checks cutover preconditions.

- [x] **Step 4: Run** `python -m pytest tests/test_autonomy.py tests/test_command_drain.py tests/test_drain_controls.py tests/test_live_cutover.py -v`. Expected: PASS.

- [x] **Step 5: Flip** (only after the preconditions above hold)

Run: `./ibkr autonomy full`
Expected: `autonomy = full`. The next intraday cycle logs `autonomy=full`, and a candidate that passes the gate is auto-queued, with a thread-58 order notification instead of a view-only card. Watch one session with `./ibkr logs approval`. `/halt` in Telegram stops new orders immediately if anything looks wrong.

- [x] **Step 6: Docs:** `ARCHITECTURE.md` (autonomy ladder + paper override); `SETUP.md` (`./ibkr autonomy`, `/halt` reminder); `STATUS.md` (override on, live-cutover gate).

- [x] **Step 7: Commit** `git commit -m "feat(autonomy): paper-only promotion-gate override and ./ibkr autonomy; run paper on FULL"`

---

### Task 13: Final verification and doc sweep

- [x] **Step 1:** `python -m pytest -q && ruff check . && ruff format --check . && mypy src`. Expected: all green, and the test count is ≥ 2313 plus the new tests.
- [x] **Step 2:** Re-check every CLAUDE.md doc-update row against `git diff --stat main`: new modules (`src/ops/`, `src/storage/approvals.py`, `src/data/google_news_backend.py`, `src/claude/news_context.py`, `src/claude/ollama_tools.py`); new scripts (`ibkr`, `scripts/launchd.py`, `scripts/watchdog.py`, `scripts/review_eval.py`, `scripts/autonomy.py`); new config keys (`watchdog.*`, `claude.news_*`, `claude.tool_research_*`, `data.news_search_provider`, `automation.paper_skip_promotion_gate`, `missing_iv_rank_score`); the universe tickers; the ORM column; the schema fields.
- [ ] **Step 3:** _(Deferred to the operator: needs IB Gateway plus a full trading session on FULL. Autonomy was set to FULL on 2026-09-30.)_ One full RTH session under launchd on FULL. Afterwards, rerun the post-mortem queries (`risk_verdicts` reason breakdown by granular liquidity code, candidates → approvals → orders → fills) and update the artifact with a "post-remediation" section.
- [x] **Step 4:** Commit any doc fix-ups: `git commit -m "docs: sync architecture/setup/status for scan-loop remediation"`.

---

## Self-review

**Coverage of the request:**

| Request item | Task(s) |
|---|---|
| 1. AMD/GOOGL empty chains | 1 |
| 1. AMD/BAC into the universe; BAC + DPST CSP-eligible (follow-up) | 2 (and 4 for their IV history) |
| 2. Alert when the loop fails | 3, 4 (scan heartbeat), 4b (EOD hang + `eod` check), 5 |
| 3. Split illiquid | 7 (7 codes plus persisted bid/ask/OI/volume) |
| 4. Ollama-only review: diagnose why it adds no value and improve it | 10 (root causes R5a–e fixed), 11 (news search and tool calling) |
| 5. Expire stale approval cards | 8 |
| 8. TQQQ and similar names vs the score floor | Diagnosis R7 + the floor decision above; 4 (data); 9 (neutral missing IV) |
| 9. launchd + watchdog + single script | 5, 6 |
| 10. Flip to automatic | 12 (after 1/3/5/6) |

- **Placeholder scan:** None found. Every code step shows the code, and every test step shows the test.
- **Type consistency:** `SCAN_COMPLETED_KEY` is defined in Task 4 and used in Task 5. `REVIEW_SCHEMA` is defined in Task 10 and reused in Task 11. `NewsItem` and `NewsSearchProvider` are defined and used within Task 11. `liquidity_failures` is used by Task 7's generators. `promotion_blockers` keeps its signature.
