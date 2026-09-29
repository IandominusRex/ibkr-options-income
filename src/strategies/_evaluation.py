"""Shared plumbing for strategy screens that report *why* a contract was rejected.

The generators used to drop a failing quote with a bare ``continue`` and a counter, so the
only trace a rejection ever left was one aggregate ``WARNING`` line. When every quote for a
symbol failed, the scan had nothing at all to show — no contract, no reason, just silence.

These helpers let each generator return the contracts it rejected alongside the ones it
passed, each tagged with **every** gate it failed (not just the first), so the UI can rank
them by how close they came and name what stood in the way.

Reason codes deliberately reuse the risk engine's vocabulary where the meaning is identical
(``delta_out_of_range``, ``roc_below_minimum``, …) so ``formatters._REJECT_REASON_LABELS``
humanizes generator-stage and gate-stage rejections through one table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.common.config import get_config
from src.common.schemas import TradeCandidate

# --- Generator-stage reason codes ---------------------------------------------------- #
REASON_DELTA_MISSING = "delta_missing"
REASON_DELTA_RANGE = "delta_out_of_range"
REASON_DTE_RANGE = "dte_out_of_range"
REASON_NO_MARKET = "no_two_sided_market"
# Legacy: collapsed all liquidity-gate failures into one undifferentiated code. Superseded by
# `analytics.liquidity.liquidity_failures`'s seven precise `illiquid_*` codes (Task 7,
# 2026-09-29 post-mortem — "SOXL failed liquidity 684 times" was unactionable). Kept only so
# `formatters._REJECT_REASON_LABELS` / `options._REASON_LABELS` can still humanize the ~14
# days of pre-existing `risk_verdicts` rows that still carry it; no generator emits it anymore.
REASON_ILLIQUID = "illiquid"
REASON_BELOW_BASIS = "strike_below_basis"
REASON_BELOW_FAIR_VALUE = "premium_below_fair_value"
REASON_INSUFFICIENT_CASH = "insufficient_cash"
REASON_NO_HEADROOM = "no_headroom"
REASON_ROC = "roc_below_minimum"
REASON_YIELD = "yield_below_minimum"
REASON_PHASE_DOWNTREND = "phase_downtrend"


@dataclass
class ScreenResult:
    """What a strategy generator saw for one symbol.

    Attributes:
        passed: Contracts that cleared every generator filter, ranked as before.
        rejected: ``(candidate, reasons)`` for contracts that failed at least one filter,
            ranked closest-to-passing first.
        evaluated: How many quotes of the relevant right were considered.
        skipped: Set when the symbol never reached the per-quote loop at all (e.g. no shares
            held for a covered call). Distinguishes "screened and found nothing" from
            "not eligible for this strategy", which read very differently to an operator.
    """

    passed: list[TradeCandidate] = field(default_factory=list)
    rejected: list[tuple[TradeCandidate, list[str]]] = field(default_factory=list)
    evaluated: int = 0
    skipped: str | None = None

    def tally(self) -> dict[str, int]:
        """Reason → count across all rejected contracts (for the diagnostic log line)."""
        counts: dict[str, int] = {}
        for _, reasons in self.rejected:
            for r in reasons:
                counts[r] = counts.get(r, 0) + 1
        return counts

    def market_data_outage(self) -> bool:
        """True when every evaluated quote came back with no live bid/ask.

        A missing market forces ``illiquid_no_quote`` to fire too (spread can't be computed
        without a market), so a symbol-wide IBKR data-feed outage is otherwise indistinguishable in
        the reason tally from a chain that is genuinely, individually illiquid contract by
        contract (2026-09-11: TQQQ/UPRO/AMZN/RKLB scan cycles where the entire chain came
        back with no market were silently counted the same as ordinary thin-liquidity
        rejects). Only meaningful when nothing passed — call after the loop, once
        ``evaluated`` is final.
        """
        if self.evaluated == 0:
            return False
        return self.tally().get(REASON_NO_MARKET, 0) == self.evaluated


def rank_rejects(
    rejects: list[tuple[TradeCandidate, list[str]]],
    *,
    delta_mid: float,
) -> list[tuple[TradeCandidate, list[str]]]:
    """Order rejects by how close they came to passing.

    1. Fewest distinct failed gates — one gate away beats four.
    2. Closest to the middle of the target delta band — the contract you'd actually have
       wanted, rather than a deep-OTM lottery ticket that failed for unrelated reasons.
    3. Highest ROC as the tiebreak, matching how the passing list is ranked.

    ``delta_mid`` is the midpoint of the strategy's configured delta band. A contract with no
    delta at all sorts last within its reason-count group.
    """

    def key(item: tuple[TradeCandidate, list[str]]) -> tuple[int, float, float]:
        cand, reasons = item
        delta_gap = abs(abs(cand.delta) - delta_mid) if cand.delta is not None else 99.0
        return (len(set(reasons)), delta_gap, -cand.roc_pct)

    return sorted(rejects, key=key)


def liquidity_limits_summary(*, enforce_volume: bool) -> str:
    """Render the active liquidity thresholds for the aggregate rejection WARNING line.

    Task 7: the tally already shows granular ``illiquid_*`` counts (e.g. ``illiquid_oi_low=12``)
    but not the threshold that made them fail, which still leaves an operator guessing whether
    ``risk_limits.yaml`` needs a look. Reads the live config rather than hard-coding the
    numbers, so a config change is reflected in the log without a code change. ``enforce_volume``
    reports whether the N19 day-volume gate was active this cycle (time-aware — off before
    ``liquidity.morning_volume_cutoff_et``).
    """
    cfg = get_config().risk["liquidity"]
    gate_state = "volume gate on" if enforce_volume else "volume gate off (pre-cutoff)"
    return (
        f"spread≤{cfg['max_bid_ask_spread_pct']:g}%, "
        f"OI≥{cfg['min_open_interest']:g}, "
        f"vol≥{cfg['min_option_volume']:g}, "
        f"{gate_state}"
    )


def display_premium(strict_mid: float | None, mid: float | None, last: float | None) -> float:
    """Best available price for a contract we are only *displaying*, never trading.

    The passing path prices strictly off ``strict_mid`` (N10 — never a stale ``last``). A
    rejected contract still has to render a number, so fall back through the looser sources;
    the accompanying ``no_two_sided_market`` reason tells the reader the price is untrusted.
    """
    for value in (strict_mid, mid, last):
        if value is not None and value > 0:
            return float(value)
    return 0.0
