"""The P&L read surfaces (P3-P4 M5) — what every trade earned, and the curve.

Every route here is a thin renderer over `src/reporting/pnl.py` (M4): if a
route computed a P&L figure of its own, the single-accounting-rule invariant
M4 established would already be broken. `build_legs` feeds `build_campaigns`,
`build_summary`, and `equity_curve` alike, so the ledger's rows, the summary's
totals, and the curve's cumulative line can never disagree.

Shared conventions, set by Task 5.1:

- **`as_of` is request time here**, because the ledger is computed on read.
  `marks_as_of` is a different field: the snapshot time backing every
  unrealised figure, coerced through `as_utc_opt` like every other stored
  timestamp. Two fields, both present, documented as different — do not merge
  them to match the portfolio routes, which have no computed figures and read
  the capture time alone.
- **Marks come from `read_portfolio`, never a second query.** `marks_as_of` is
  that reading's `as_of`, so the ledger's unrealised figures and the portfolio
  page's agree by construction. The `none` rung passes `snapshot=None` into
  `build_campaigns` and returns `marks_as_of: null` — never a zero mark.
- **`book` defaults to `"all"` on the ledger and is explicit on the summary.**
  `build_summary` raises on a mixed list (M4 Task 4.5); this route turns that
  `ValueError` into a `422` naming the problem, never a mixed total and never
  a 500. The ledger may list both books; only the total is refused.
- **Filters are echoed back verbatim** on every response, so a client that
  sent `since` and got a full history can see its own bug.
- Every route is `owner_only`.

`GET /pnl/system` (P3-P4 M6 Task 6.1) is the one exception to "no route computes a figure of
its own": it reads behind the `src/claude/eval/` fence, returning `score_outcome_report`'s
score-vs-outcome evidence and a Claude-vs-baseline agreement figure computed here from the
ledger. This is the fence's intended use, not a breach — see the route's own docstring and
`docs/web/api.md`.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from src.api.deps import OwnerUser, TradingDb
from src.api.models.common import as_utc_opt
from src.api.models.pnl import (
    EquityResponse,
    LedgerFilters,
    LedgerResponse,
    SummaryResponse,
    SystemPerformanceResponse,
    VerdictAgreement,
)
from src.api.portfolio_source import read_portfolio
from src.claude.eval.ledger import load_records
from src.claude.eval.score_metrics import score_outcome_report
from src.common.schemas import (
    CampaignPnl,
    EquityCurve,
    PnlLeg,
    PnlSummary,
    PortfolioSnapshot,
    VerdictRecord,
)
from src.reporting.pnl import build_campaigns, build_legs, build_summary, equity_curve

router = APIRouter()

# The CSV column contract: unit-suffixed names, so a `credit` column cannot
# leave the app ambiguous about whether it is per share, per contract, or USD.
# `None` serialises as an empty cell (see `_csv_cell`), never `0`.
_CSV_COLUMNS: tuple[tuple[str, object], ...] = (
    ("candidate_id", None),
    ("campaign_id", None),
    ("underlying", None),
    ("symbol", None),
    ("strategy", None),
    ("right", None),
    ("strike", None),
    ("expiry", None),
    ("book", None),  # a paper row is identifiable after export
    ("opened_at", None),
    ("closed_at", None),
    ("contracts", None),
    ("credit_usd", None),
    ("debit_usd", None),
    ("commissions_usd", None),
    ("net_pnl_usd", None),
    ("unrealized_usd", None),
    ("roc_pct", None),
    ("annualized_pct", None),
    ("days_held", None),
    ("outcome", None),
)


def _filter_params(
    symbol: str | None,
    strategy: str | None,
    outcome: str | None,
    since: date | None,
    until: date | None,
    book: Literal["paper", "live", "all"],
) -> LedgerFilters:
    return LedgerFilters(
        as_of=datetime.now(UTC),
        symbol=symbol.upper() if symbol else None,
        strategy=strategy,
        outcome=outcome,
        since=since,
        until=until,
        book=book,
    )


def _leg_passes(leg: PnlLeg, filters: LedgerFilters) -> bool:
    """The filters `build_legs` cannot express, applied in one named place.

    `build_legs` itself owns `symbol`, `since`, and the paper/live split (M4's
    settled signature); everything else filters here so the rows, the summary,
    and the CSV all read one definition of "the same rows".
    """
    if filters.strategy is not None and leg.strategy.value != filters.strategy:
        return False
    if filters.outcome is not None and leg.outcome.value != filters.outcome:
        return False
    if filters.until is not None and leg.opened_at.date() > filters.until:
        return False
    return True


def _session_factory(db: TradingDb):
    """`src/reporting` takes a session *factory*, the API holds a session.

    The builders open and close their own sessions; the route's read-only
    session stays open for the request either way (it is dependency-scoped and
    never commits). The factory yields the same session — no second engine, no
    second connection, the read-only guarantee unchanged.
    """

    @contextmanager
    def _factory() -> Iterator[TradingDb]:
        try:
            yield db
        finally:
            pass

    return _factory


def _filtered_legs(db: TradingDb, filters: LedgerFilters) -> list[PnlLeg]:
    """The one `build_legs` call every route shares, under the echoed filters.

    `until` trims by open date here rather than inside `build_legs` because M4
    pinned that signature (`since`/`symbol`/paper-live only); the rows the JSON
    ledger, the summary, and the CSV render must all come through this one
    function or they could drift.
    """
    legs = build_legs(
        _session_factory(db),
        since=filters.since,
        symbol=filters.symbol,
        include_paper=filters.book in ("paper", "all"),
        include_live=filters.book in ("live", "all"),
    )
    return [leg for leg in legs if _leg_passes(leg, filters)]


def _snapshot_for_marks(db: TradingDb) -> tuple[PortfolioSnapshot | None, datetime | None]:
    """The snapshot the portfolio page renders, and its capture time.

    One `read_portfolio` call — never a second query. The `none` rung yields
    `(None, None)` so `build_campaigns` leaves every unrealised field null.
    """
    reading = read_portfolio(db)
    if reading.snapshot is None:
        return None, None
    return reading.snapshot, as_utc_opt(reading.as_of)


@router.get("/ledger", response_model=LedgerResponse)
def pnl_ledger(
    user: OwnerUser,  # noqa: ARG001
    db: TradingDb,
    symbol: str | None = None,
    strategy: str | None = None,
    outcome: str | None = None,
    since: date | None = None,
    until: date | None = None,
    book: Literal["paper", "live", "all"] = "all",
) -> LedgerResponse:
    """Leg rows grouped under their campaign threads — OVERVIEW's "Excel-shaped
    ledger of every position opened and closed", readable in a browser.

    The grouping is what stops an assignment reading as a leg that ended for
    no reason: a campaign-less leg lands in a synthetic per-symbol thread (M4
    Task 4.4), so `n_legs` always equals the sum of every campaign's leg count.
    """
    filters = _filter_params(symbol, strategy, outcome, since, until, book)
    legs = _filtered_legs(db, filters)
    snapshot, marks_as_of = _snapshot_for_marks(db)
    campaigns = build_campaigns(_session_factory(db), legs, snapshot=snapshot)

    return LedgerResponse(
        as_of=datetime.now(UTC),
        filters=filters,
        campaigns=campaigns,
        marks_as_of=marks_as_of,
        n_legs=sum(len(c.legs) for c in campaigns),
    )


@router.get("/summary", response_model=SummaryResponse)
def pnl_summary(
    user: OwnerUser,  # noqa: ARG001
    db: TradingDb,
    book: Literal["paper", "live", "all"] = Query(
        default="all",
        description=(
            "Which fills to total. 'all' is refused with 422 mixed_book when both "
            "paper and live fills are present, because a total across both is not "
            "a number that means anything."
        ),
    ),
    symbol: str | None = None,
    strategy: str | None = None,
    outcome: str | None = None,
    since: date | None = None,
    until: date | None = None,
) -> SummaryResponse:
    """The totals and breakdowns, computed from the same `PnlLeg` list the
    ledger renders — a total can never disagree with the rows above it.

    `build_summary` raises `ValueError` on a mixed paper/live list (M4 Task
    4.5); this route turns that into a `422` naming `mixed_book`, so the
    operator picks a book instead of reading a wrong number. A single-book
    summary over an empty list is a valid empty summary, not an error.
    """
    filters = _filter_params(symbol, strategy, outcome, since, until, book)
    legs = _filtered_legs(db, filters)

    try:
        summary: PnlSummary = build_summary(legs, [])
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "mixed_book",
                "detail": (
                    "This summary would total both paper and live fills, and a "
                    "total across both books is not a number that means anything. "
                    "Choose book=paper or book=live."
                ),
                "error": str(exc),
            },
        ) from exc

    _, marks_as_of = _snapshot_for_marks(db)

    return SummaryResponse(
        as_of=datetime.now(UTC),
        filters=filters,
        summary=summary,
        marks_as_of=marks_as_of,
    )


@router.get("/equity", response_model=EquityResponse)
def pnl_equity(
    user: OwnerUser,  # noqa: ARG001
    db: TradingDb,
    since: date | None = None,
    until: date | None = None,
    symbol: str | None = None,
    strategy: str | None = None,
    outcome: str | None = None,
    book: Literal["paper", "live", "all"] = "all",
) -> EquityResponse:
    """The equity curve — one point per journal day, plus the trading days
    between them that have no point, so the chart can render a gap rather than
    a fabricated straight line.

    The route computes nothing: `build_legs` feeds `equity_curve` exactly as it
    feeds the ledger. `book=all` is fine *here*, deliberately unlike
    `/pnl/summary`: the curve's `cumulative_realized` sums `net_pnl` per point,
    and mixing books in a curve is a display choice the client makes, not a
    headline total. Do not "fix" one to match the other.
    """
    filters = _filter_params(symbol, strategy, outcome, since, until, book)
    legs = _filtered_legs(db, filters)
    curve: EquityCurve = equity_curve(_session_factory(db), legs, since=filters.since)

    return EquityResponse(
        as_of=datetime.now(UTC),
        filters=filters,
        curve=curve,
    )


def _csv_cell(value: object) -> str:
    """`None` serialises as an empty cell, never as `0`.

    A spreadsheet reading `0` where the value was unknown is the same lie as
    `$0.00` on the page, and it is harder to spot.
    """
    if value is None:
        return ""
    return str(value)


def _ledger_csv(campaigns: list[CampaignPnl]) -> str:
    """One row per leg, flattened out of its campaign thread, in thread order."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([name for name, _ in _CSV_COLUMNS])
    for campaign in campaigns:
        for leg in campaign.legs:
            row = {
                "candidate_id": leg.candidate_id,
                "campaign_id": leg.campaign_id,
                "underlying": leg.underlying,
                "symbol": leg.symbol,
                "strategy": leg.strategy.value,
                "right": leg.right.value,
                "strike": leg.strike,
                "expiry": leg.expiry.isoformat(),
                "book": "live" if leg.is_live else "paper",
                "opened_at": leg.opened_at.isoformat(),
                "closed_at": leg.closed_at.isoformat() if leg.closed_at else None,
                "contracts": leg.contracts,
                "credit_usd": leg.credit,
                "debit_usd": leg.debit,
                "commissions_usd": leg.commissions,
                "net_pnl_usd": leg.net_pnl,
                "unrealized_usd": leg.unrealized_pnl,
                "roc_pct": leg.roc_pct,
                "annualized_pct": leg.annualized_pct,
                "days_held": leg.days_held,
                "outcome": leg.outcome.value,
            }
            writer.writerow([_csv_cell(row[name]) for name, _ in _CSV_COLUMNS])
    return buf.getvalue()


@router.get("/ledger.csv", response_class=Response)
def pnl_ledger_csv(
    user: OwnerUser,  # noqa: ARG001
    db: TradingDb,
    symbol: str | None = None,
    strategy: str | None = None,
    outcome: str | None = None,
    since: date | None = None,
    until: date | None = None,
    book: Literal["paper", "live", "all"] = "all",
) -> Response:
    """The same rows `/pnl/ledger` returns, under the same filters, as CSV.

    Built from the same `build_legs` call the JSON route uses — a second query
    would let the two drift. There is no mixed-book refusal here because a CSV
    has no headline total to be wrong; the `book` column identifies each row
    after export.
    """
    filters = _filter_params(symbol, strategy, outcome, since, until, book)
    legs = _filtered_legs(db, filters)
    snapshot, _ = _snapshot_for_marks(db)
    campaigns = build_campaigns(_session_factory(db), legs, snapshot=snapshot)
    body = _ledger_csv(campaigns)

    filename = f"pnl-ledger-{date.today().isoformat()}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _win_rate(records: list[VerdictRecord]) -> float | None:
    """Fraction of records with positive realized P&L. None with nothing to rate — never 0.0."""
    if not records:
        return None
    wins = sum(1 for r in records if (r.realized_pnl or 0.0) > 0)
    return round(wins / len(records), 4)


def _verdict_agreement(*, since: date | None, until: date | None) -> VerdictAgreement:
    """Claude-vs-baseline agreement over the same closed, since/until-windowed population
    the report windows by outcome_date. Reads the `agreement` flag scan.py already computed
    on each ledger row at scan time — never recomputed here.
    """
    records = load_records(closed_only=True)
    if since is not None:
        records = [r for r in records if r.outcome_date and r.outcome_date >= since]
    if until is not None:
        records = [r for r in records if r.outcome_date and r.outcome_date <= until]
    if not records:
        return VerdictAgreement(n_closed=0, n_agreed=0)
    n_agreed = sum(1 for r in records if r.agreement)
    return VerdictAgreement(
        n_closed=len(records),
        n_agreed=n_agreed,
        agreement_rate=round(n_agreed / len(records), 4),
        claude_win_rate=_win_rate([r for r in records if r.claude_recommendation == "sell"]),
        baseline_win_rate=_win_rate([r for r in records if r.baseline_recommendation == "sell"]),
    )


@router.get("/system", response_model=SystemPerformanceResponse)
def pnl_system(
    user: OwnerUser,  # noqa: ARG001
    since: date | None = None,
    until: date | None = None,
) -> SystemPerformanceResponse:
    """The score-vs-outcome evidence's human reader (P3-P4 M6 Task 6.1).

    Reads behind the fence CLAUDE.md draws around `src/claude/eval/`: this is the one route in
    the phase where that is the intended use, not a breach — `score_outcome_report`'s own notes
    already say the weights must be re-derived by hand, and this route only renders them. It
    calls `score_outcome_report` and returns exactly what it gets: no bucket recomputed, no
    correlation re-derived, no note filtered. `verdict_ledger` and `scoring_weights.yaml` are
    read-only from here — `tests/test_web_fence.py` (Task 6.3) asserts no module under `src/api/`
    can write either.
    """
    report = score_outcome_report(since=since, until=until)
    agreement = _verdict_agreement(since=since, until=until)
    return SystemPerformanceResponse(
        as_of=datetime.now(UTC),
        report=report,
        agreement=agreement,
        since=since,
        until=until,
    )
