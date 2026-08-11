"""Per-symbol scan pipeline — the data-producing half of a scan.

For one symbol this runs: option-chain fetch (bounded by a timeout), spot resolution, analytics,
sentiment, and the covered-call / cash-secured-put screens. It returns a :class:`SymbolOutcome`
describing *what happened* and *what was produced*, and does nothing else — no Telegram, no
progress tracker, no run-level state.

The split exists so a caller that only wants data (the 15-min daemon loop, a future HTTP API)
can drive a scan without importing the notify layer. That is a structural guarantee, not a
convention: ``tests/test_eval_skills.py::test_scan_pipeline_does_not_import_the_notify_layer``
fails if anything under ``src.notify`` (or ``telegram``) is imported here.

Two things deliberately stay with the caller (``scan.py``), because they span symbols and this
module sees exactly one:

* the **half-dead-socket circuit breaker** — a run of consecutive chain timeouts means the
  socket is dead, which only the loop can observe;
* the **accumulators** (candidate lists, analytics map, provenance tallies, scan-lease renewal)
  — the caller folds each :class:`SymbolOutcome` into them.

External collaborators arrive through :class:`SymbolDeps` rather than being imported and called
directly. That keeps the orchestrator in charge of which implementation runs, and gives the
existing scan tests a single seam to stub (they monkeypatch these names on
``src.orchestrator.scan``, which builds the deps).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field
from enum import StrEnum

from ib_async import IB

from src.analytics.iv import infer_spot_from_quotes
from src.common.schemas import (
    AccountSnapshot,
    FundamentalStats,
    IVStats,
    OptionQuote,
    OptionRight,
    PositionSnapshot,
    SentimentDetail,
    TechnicalStats,
    TradeCandidate,
)
from src.ibkr.market_data import drain_market_data_lines
from src.strategies._evaluation import ScreenResult

log = logging.getLogger(__name__)

# The analytics triple every downstream consumer passes around together.
Analytics = tuple[IVStats, TechnicalStats, FundamentalStats]

ChainFetcher = Callable[[IB, str], Awaitable[list[OptionQuote]]]
# (symbol, quotes, spot_override, cached_yf_price) -> analytics
AnalyticsFetcher = Callable[[str, list[OptionQuote] | None, float | None, float | None], Analytics]
SentimentFn = Callable[[str], SentimentDetail | None]
# Both screens take (symbol, quotes, …) plus strategy-specific keyword arguments.
ScreenFn = Callable[..., ScreenResult]


class ChainStatus(StrEnum):
    """What became of this symbol's option-chain fetch.

    The caller maps these onto the run-level provenance tallies and onto the circuit breaker:
    only ``TIMEOUT`` advances it, ``SKIPPED`` leaves it untouched (nothing was asked of the
    socket), and every other outcome proves the socket answered and resets it.
    """

    SKIPPED = "skipped"  # immaterial this intraday cycle — chain fetch deliberately not attempted
    FETCHED = "fetched"  # IBKR returned quotes
    EMPTY = "empty"  # the call returned, but with no quotes
    TIMEOUT = "timeout"  # exceeded symbol_timeout_seconds
    ERROR = "error"  # the call raised


@dataclass
class SymbolOutcome:
    """Everything one symbol produced, plus enough detail for the caller to report progress.

    ``analytics is None`` means analytics failed and the symbol should be skipped entirely —
    nothing else on this outcome is meaningful in that case.
    """

    symbol: str
    chain_status: ChainStatus
    quote_count: int = 0
    # Per-quote Greeks provenance for the symbols whose chain we actually got.
    greeks_ibkr: int = 0
    greeks_yfinance: int = 0
    analytics: Analytics | None = None
    cc_passed: list[TradeCandidate] = field(default_factory=list)
    csp_passed: list[TradeCandidate] = field(default_factory=list)
    # (candidate, reasons) for contracts the generators priced but rejected.
    rejected: list[tuple[TradeCandidate, list[str]]] = field(default_factory=list)
    # Operator-facing messages the caller pushes to whatever progress surface it owns.
    errors: list[str] = field(default_factory=list)

    @property
    def did_fetch(self) -> bool:
        """True when a chain fetch was attempted (successfully or not) — i.e. not gate-skipped.

        Only fetched symbols refresh their materiality baseline, so slow drift accrues from the
        last actual fetch rather than from a cycle that never looked.
        """
        return self.chain_status is not ChainStatus.SKIPPED


@dataclass(frozen=True)
class SymbolDeps:
    """The external collaborators :func:`scan_symbol` calls out to."""

    fetch_chain: ChainFetcher
    fetch_analytics: AnalyticsFetcher
    score_sentiment: SentimentFn
    screen_cc: ScreenFn
    screen_csp: ScreenFn


def apply_sentiment(screen: ScreenResult, detail: SentimentDetail | None) -> None:
    """Stamp composite sentiment onto every contract a screen produced, passed or rejected.

    ``overall`` drives scoring; the per-source detail is enrichment for the card and the
    prompt. Rejected contracts are rendered on the same cards, so they carry it too.
    """
    if detail is None:
        return
    for cand in screen.passed:
        cand.scores.sentiment_score = detail.overall
        cand.scores.sentiment_detail = detail
    for cand, _ in screen.rejected:
        cand.scores.sentiment_score = detail.overall
        cand.scores.sentiment_detail = detail


async def _fetch_chain(
    ib: IB,
    symbol: str,
    *,
    material: bool,
    symbol_timeout_seconds: float,
    fetch_chain: ChainFetcher,
    errors: list[str],
) -> tuple[list[OptionQuote], ChainStatus]:
    """Fetch one symbol's option chain, classifying the result rather than raising.

    IB calls run on the loop thread (async), NOT in a worker thread, and stay sequential per
    symbol to respect the ~100 market-data line cap. Bounded by *symbol_timeout_seconds*: a call
    that never responds (pacing violation, competing-session lockout) must not hang the whole
    scan — the symbol yields no quotes and the sweep moves on.
    """
    if not material:
        # Intraday gate (S1): immaterial this cycle (not held, spot unmoved, didn't clear the
        # floor last cycle). Skip the dominant option-chain fetch; the caller still runs
        # analytics (cheap/day-cached) so the buy-to-own list stays complete.
        log.debug("scan: skipping option chain for %s (immaterial this intraday cycle)", symbol)
        return [], ChainStatus.SKIPPED

    symbol_start = time.monotonic()
    try:
        quotes = await asyncio.wait_for(fetch_chain(ib, symbol), timeout=symbol_timeout_seconds)
    except TimeoutError:
        log.error(
            "scan: option chain for %s exceeded symbol_timeout_seconds=%.0f "
            "(ran %.1fs) — skipping this symbol",
            symbol,
            symbol_timeout_seconds,
            time.monotonic() - symbol_start,
        )
        # The timeout cancelled the chain fetch mid-flight; reclaim any market-data lines it
        # left open so they don't eat into the next symbol's ~100-line budget.
        drain_market_data_lines(ib)
        errors.append(f"{symbol} — option chain timed out, skipped")
        return [], ChainStatus.TIMEOUT
    except Exception:
        log.exception("scan: option chain failed for %s", symbol)
        drain_market_data_lines(ib)
        errors.append(f"{symbol} — option chain failed, skipped")
        return [], ChainStatus.ERROR

    elapsed = time.monotonic() - symbol_start
    level = logging.WARNING if elapsed > symbol_timeout_seconds / 3 else logging.DEBUG
    log.log(level, "scan: option chain for %s took %.1fs (%d quotes)", symbol, elapsed, len(quotes))
    return quotes, ChainStatus.FETCHED if quotes else ChainStatus.EMPTY


async def scan_symbol(
    ib: IB,
    symbol: str,
    *,
    material: bool,
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    would_own: Collection[str],
    probed_spot: float | None,
    symbol_timeout_seconds: float,
    deps: SymbolDeps,
) -> SymbolOutcome:
    """Run the full per-symbol pipeline and return what it produced.

    Never raises: every failure mode is folded into the returned :class:`SymbolOutcome` (a
    ``chain_status`` other than ``FETCHED``, an ``errors`` entry, and/or ``analytics=None``) so
    one bad symbol can never abort a sweep.

    Args:
        material: False when the intraday materiality gate (S1) decided this symbol's chain is
            not worth re-fetching this cycle. Analytics still run.
        would_own: symbols eligible for a cash-secured put.
        probed_spot: the materiality probe's live ``fast_info`` price, if one was taken. Reused
            as the technicals' cached price so a gate-skipped symbol doesn't pay for a second
            identical fetch.
        symbol_timeout_seconds: hard bound on the option-chain fetch.
    """
    loop = asyncio.get_running_loop()
    errors: list[str] = []

    quotes, chain_status = await _fetch_chain(
        ib,
        symbol,
        material=material,
        symbol_timeout_seconds=symbol_timeout_seconds,
        fetch_chain=deps.fetch_chain,
        errors=errors,
    )
    outcome = SymbolOutcome(
        symbol=symbol,
        chain_status=chain_status,
        quote_count=len(quotes),
        errors=errors,
    )
    if chain_status is ChainStatus.FETCHED:
        for q in quotes:
            if q.greeks_source == "black_scholes":
                outcome.greeks_yfinance += 1
            else:
                outcome.greeks_ibkr += 1

    # Spot price (N17 follow-up): prefer the IBKR chain's put-call-parity spot over yfinance
    # fast_info when we just paid for the chain fetch.
    spot_override = infer_spot_from_quotes(quotes) if quotes else None

    # Analytics (yfinance) and sentiment (Reddit) are independent external I/O — run them
    # concurrently in the default executor to cut per-symbol latency.
    analytics_res, sentiment_res = await asyncio.gather(
        loop.run_in_executor(
            None, deps.fetch_analytics, symbol, quotes, spot_override, probed_spot
        ),
        loop.run_in_executor(None, deps.score_sentiment, symbol),
        return_exceptions=True,
    )
    if isinstance(analytics_res, BaseException):
        log.exception("scan: analytics failed for %s", symbol, exc_info=analytics_res)
        outcome.errors.append(f"{symbol} — analytics failed, skipped")
        return outcome  # analytics is None → the caller drops this symbol
    iv_stats, tech_stats, fund_stats = analytics_res
    outcome.analytics = (iv_stats, tech_stats, fund_stats)
    # SentimentScorer.score() returns a SentimentDetail (or None from the test stub / on error).
    sentiment_detail = None if isinstance(sentiment_res, BaseException) else sentiment_res

    # CC candidates for held stock positions.
    stock_pos = next(
        (
            p
            for p in positions
            if (p.underlying or p.symbol) == symbol and p.sec_type == "STK" and p.position > 0
        ),
        None,
    )
    if stock_pos and quotes:
        # Calls already written against this underlying — netted out of CC sizing so a re-scan
        # never proposes calls on top of already-covered shares.
        existing_short_calls = sum(
            int(abs(p.position))
            for p in positions
            if (p.underlying or p.symbol) == symbol
            and p.sec_type == "OPT"
            and p.right == OptionRight.CALL
            and p.position < 0
        )
        cc_screen = deps.screen_cc(
            symbol,
            quotes,
            stock_pos,
            iv_stats,
            tech_stats,
            fund_stats,
            existing_short_calls=existing_short_calls,
        )
        # Inject composite sentiment into ScoreCard (overall drives scoring; detail enriches).
        # Rejected contracts get it too — they are shown on the same cards.
        apply_sentiment(cc_screen, sentiment_detail)
        outcome.cc_passed.extend(cc_screen.passed)
        outcome.rejected.extend(cc_screen.rejected)

    # CSP candidates for would_own symbols.
    if symbol in would_own and quotes:
        csp_screen = deps.screen_csp(
            symbol, quotes, account, iv_stats, tech_stats, fund_stats, positions=positions
        )
        apply_sentiment(csp_screen, sentiment_detail)
        outcome.csp_passed.extend(csp_screen.passed)
        outcome.rejected.extend(csp_screen.rejected)

    return outcome
