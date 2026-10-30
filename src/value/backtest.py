"""Stage 1b (spec §12): a point-in-time backtest of Python's rules. No I/O of its own:
``scripts/value_backtest.py`` hands in the bars, the raw companyfacts payloads (read-only, one
name at a time) and the frozen config.

On the first session of each month in the window every name is scored as it stood then: filings
first filed on or before that day (``select_periods(as_of=)``), bars up to its close, the run's
own relative-strength line. A READY verdict enters at the next session's open, exactly as the
shadow record does, and is marked at 21/63/126 sessions against SPY; the ranked record's top
tenth, bottom tenth and whole list are held to the next formation. The report is
``src/value/report.py``'s, under the caveats below. Claude is never backtested (spec §12).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from src.common.config import ValueCfg
from src.common.value_inputs import build_price_series, build_value_financials
from src.common.value_types import Classification, PriceSeries, ValueInputs
from src.research.ingest.concepts import load_concept_map, resolve_line_item
from src.value import gates
from src.value.metrics import SPLIT_RATIO
from src.value.rank import rank_list, rs_cutoff
from src.value.ranked import BUCKETS, buckets, equal_weight_return
from src.value.report import (
    GO_LIVE_HORIZON,
    HORIZONS,
    SURVIVORSHIP,
    EntryView,
    RankedView,
    clustered_mean,
    horizon_section,
    ranked_section,
)
from src.value.schemas import LISTS, ListEvaluation, ValueScorecard
from src.value.scorecard import build_scorecard

TRACK = "backtest"
PERIODIC_FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")
CAVEATS = (
    SURVIVORSHIP,
    "The universe is today's snapshot: names that left the index (failed, acquired, demoted) "
    "are missing, a second survivorship bias on top of the prices'.",
    "Earnings dates are not known point-in-time: the next 10-Q/10-K's filing date stands in, and "
    "it follows the release, so the earnings window errs late.",
    "The market-cap cross-check (spec §6.3) has no historical yfinance value: EDGAR's own count "
    "times the price stands in, so it always passes.",
    "The regime is taken as normal throughout (no point-in-time regime record): the required "
    "margins are the normal regime's.",
    "Classification (sector, industry) is today's.",
    "Prices are the provider's adjusted history, rewritten for every dividend paid after each "
    "formation: a past price reads lower than it traded, so margins of safety err high (a "
    "look-ahead the cached bars cannot undo). Splits are handled: a name whose share count "
    "jumps in a filing made after a formation is not scored at that formation, because its "
    "as-filed per-share figures and its adjusted prices are on different bases.",
    "Claude cannot be backtested (its training data holds the outcomes): this is Python's "
    "baseline only.",
)


@dataclass(frozen=True, slots=True)
class BacktestName:
    symbol: str
    sector: str | None = None
    industry: str | None = None


@dataclass(slots=True)
class BacktestResult:
    version: str
    digest: str
    dates: list[date]
    names: int
    scored: int = 0  # scorecards whose data quality passed
    excluded: dict[str, int] = field(default_factory=dict)  # symbol -> formations not scored
    entries: list[EntryView] = field(default_factory=list)
    ranked: list[RankedView] = field(default_factory=list)


Scorer = Callable[[ValueInputs, ValueCfg], ValueScorecard]


def formation_dates(sessions: Iterable[date], start: date, end: date) -> list[date]:
    """The first session of each month within [start, end]."""
    out: list[date] = []
    for day in sorted(sessions):
        if start <= day <= end and (
            not out or (day.year, day.month) != (out[-1].year, out[-1].month)
        ):
            out.append(day)
    return out


def next_periodic_filing(payload: dict | None, after: date) -> date | None:
    """The first 10-Q/10-K filed after *after* in the payload: the earnings-date stand-in."""
    best: date | None = None
    for taxonomy in ((payload or {}).get("facts") or {}).values():
        for concept in (taxonomy or {}).values():
            for entries in ((concept or {}).get("units") or {}).values():
                for e in entries or []:
                    raw = e.get("filed") if isinstance(e, dict) else None
                    if e.get("form") not in PERIODIC_FORMS or not isinstance(raw, str):
                        continue
                    filed = date.fromisoformat(raw)
                    if filed > after and (best is None or filed < best):
                        best = filed
    return best


def split_filing_dates(payload: dict | None) -> list[date]:
    """The filing dates whose diluted share count jumps by a split's size against the period
    before it. The bars are adjusted for every later split while the filings are as filed, so a
    name with such a filing after a formation has per-share figures and prices on different
    bases there. Each period counts as its first filing reported it (a later filing's restated
    comparative would hide the jump); a jump of 1.8x either way is a split or something as
    large, and either way the basis cannot be reconciled."""
    spec = load_concept_map().get("shares_diluted")
    facts = resolve_line_item(payload, spec) if payload and spec else None
    first: dict[date, tuple[date, int, float]] = {}
    for f in facts or []:
        span = (f.end - f.start).days if f.start else 0
        key = (f.filed, span)
        if f.value > 0 and (f.end not in first or key < first[f.end][:2]):
            first[f.end] = (f.filed, span, f.value)
    out: list[date] = []
    ends = sorted(first)
    for older, newer in zip(ends, ends[1:], strict=False):
        ratio = first[newer][2] / first[older][2]
        if not (1.0 / SPLIT_RATIO < ratio < SPLIT_RATIO):
            out.append(first[newer][0])
    return sorted(out)


def _cut(bars: pd.DataFrame, as_of: date) -> pd.DataFrame:
    return bars[bars.index <= as_of]


def price_at(bars: pd.DataFrame, spy: pd.DataFrame, as_of: date) -> PriceSeries | None:
    return build_price_series(_cut(bars, as_of), _cut(spy, as_of))


def inputs_at(
    name: BacktestName,
    payload: dict | None,
    price: PriceSeries | None,
    as_of: date,
    cfg: ValueCfg,
    cutoff: float | None,
) -> ValueInputs:
    """One name as it stood on *as_of* (the caveats say what stands in for what is unknown)."""
    stale = cfg.rules.data_quality.stale_item_days
    fin = (
        None
        if payload is None
        else build_value_financials(payload, as_of=as_of, stale_item_days=stale)
    )
    draft = ValueInputs(
        symbol=name.symbol,
        as_of=as_of,
        financials=fin,
        price=price,
        classification=Classification(
            sector=name.sector,
            industry=name.industry,
            source="snapshot" if name.industry else "none",
        ),
        next_earnings=next_periodic_filing(payload, as_of),
        regime="normal",
        rs_cutoff_6m=cutoff,
    )
    shares = gates.edgar_shares(draft)
    cap = shares * price.close if shares and price is not None else None
    return draft.model_copy(update={"yf_market_cap": cap})


def slim(card: ValueScorecard) -> ValueScorecard:
    """What the backtest keeps of a scorecard: the verdicts and what the rank score reads."""
    lists = {
        k: ListEvaluation(
            list_name=ev.list_name,
            entry=ev.entry,
            fair_value=ev.fair_value,
            required_mos_pct=ev.required_mos_pct,
            margin_of_safety=ev.margin_of_safety,
            verdict=ev.verdict,
        )
        for k, ev in card.lists.items()
    }
    return card.model_copy(update={"lists": lists, "data_quality_checks": [], "adjustments": []})


def _open_or_close(row: pd.Series) -> float:
    o = row.get("open")
    return float(row["close"]) if o is None or pd.isna(o) else float(o)


def forward_returns(
    bars: pd.DataFrame, spy: pd.DataFrame, signal: date
) -> tuple[date | None, float | None, dict[int, float | None], dict[int, float | None]]:
    """Entry at the open of the name's first session after *signal* (SPY must have that
    session too); horizon h is the close of the h-th SPY session after the entry session, the
    name's close on or before it (None once the name's bars stop before it)."""
    after = [d for d in bars.index if d > signal]
    if not after or after[0] not in spy.index:
        return None, None, {}, {}
    entry = after[0]
    px, spy_px = _open_or_close(bars.loc[entry]), _open_or_close(spy.loc[entry])
    sessions = [d for d in spy.index if d >= entry]
    rets: dict[int, float | None] = {}
    spys: dict[int, float | None] = {}
    last = bars.index[-1]
    for h in HORIZONS:
        if len(sessions) <= h or last < sessions[h]:
            rets[h] = spys[h] = None
            continue
        mark = sessions[h]
        close = float(_cut(bars, mark)["close"].iloc[-1])
        rets[h] = close / px - 1.0
        spys[h] = float(spy.loc[mark]["close"]) / spy_px - 1.0
    return entry, px, rets, spys


def run(
    names: list[BacktestName],
    *,
    bars: dict[str, pd.DataFrame],
    spy: pd.DataFrame,
    load_payload: Callable[[str], dict | None],
    dates: list[date],
    cfg: ValueCfg,
    version: str,
    digest: str,
    score: Scorer = build_scorecard,
) -> BacktestResult:
    """Two passes, so only one payload is held at a time: the run's relative-strength line per
    date from every name's prices, then each name scored on every date."""
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    cutoffs = {
        d: rs_cutoff(
            [price_at(bars.get(n.symbol, empty), spy, d) for n in names],
            cfg.rules.timing.rs_bottom_pct,
        )
        for d in dates
    }
    cards: dict[date, list[ValueScorecard]] = {d: [] for d in dates}
    excluded: dict[str, int] = {}
    for n in names:
        frame = bars.get(n.symbol, empty)
        payload = load_payload(n.symbol)
        splits = split_filing_dates(payload)
        for d in dates:
            if any(filed > d for filed in splits):
                excluded[n.symbol] = excluded.get(n.symbol, 0) + 1
                continue
            price = price_at(frame, spy, d)
            cards[d].append(slim(score(inputs_at(n, payload, price, d, cfg, cutoffs[d]), cfg)))
    out = BacktestResult(
        version=version, digest=digest, dates=dates, names=len(names), excluded=excluded
    )
    entry_id = 0
    for k, d in enumerate(dates):
        out.scored += sum(1 for c in cards[d] if c.data_quality == "pass")
        for c in cards[d]:
            for list_name in LISTS:
                if c.verdict_for(list_name) != "READY":
                    continue
                entry, px, rets, spys = forward_returns(bars.get(c.symbol, empty), spy, d)
                entry_id += 1
                ev = c.lists[list_name]
                out.entries.append(
                    EntryView(
                        id=entry_id,
                        track=TRACK,
                        kind="ready",
                        list_name=list_name,
                        symbol=c.symbol,
                        universe="backtest",
                        status="closed" if entry else "void",
                        signal_date=d,
                        entry_date=entry,
                        entry_price=px,
                        fair_value=ev.fair_value,
                        margin_of_safety=ev.margin_of_safety,
                        ruleset_version=version,
                        returns=rets,
                        spy=spys,
                    )
                )
        end = dates[k + 1] if k + 1 < len(dates) else None
        for list_name in LISTS:
            picked = buckets({s: e.score for s, e in rank_list(cards[d], list_name).items()})
            if picked is None:
                continue
            for bucket in BUCKETS:
                members = picked[bucket]
                ret = spy_ret = None
                missing = 0
                if end is not None:
                    start_px = _closes(bars, members, d)
                    end_px = _closes(bars, members, end)
                    ret, missing = equal_weight_return(members, start_px, end_px)
                    s0, s1 = _close(spy, d), _close(spy, end)
                    spy_ret = s1 / s0 - 1.0 if s0 and s1 else None
                out.ranked.append(
                    RankedView(
                        formed_on=d,
                        list_name=list_name,
                        bucket=bucket,
                        n=len(members),
                        closed_on=end,
                        ret=ret,
                        spy_ret=spy_ret,
                        missing=missing,
                    )
                )
    return out


def _close(frame: pd.DataFrame, day: date) -> float | None:
    return float(frame.loc[day]["close"]) if day in frame.index else None


def _closes(bars: dict[str, pd.DataFrame], symbols: list[str], day: date) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in symbols:
        c = _close(bars[s], day) if s in bars else None
        if c is not None:
            out[s] = c
    return out


def _excluded_lines(excluded: dict[str, int]) -> list[str]:
    if not excluded:
        return []
    count = len(excluded)
    plural = "" if count == 1 else "s"
    listing = ", ".join(f"{s} ({n})" for s, n in sorted(excluded.items()))
    return [
        f"! {count} name{plural} excluded from at least one formation (formations skipped), "
        f"a split or a share-count jump following it: {listing}"
    ]


def render(result: BacktestResult) -> str:
    """The backtest's report: the caveats first, then the shadow report's sections."""
    span = f"{result.dates[0]}..{result.dates[-1]}" if result.dates else "no dates"
    lines = [
        f"== Value book Stage 1b: point-in-time backtest of value_rules {result.version} "
        f"({result.digest}) ==",
        f"{result.names} names, {len(result.dates)} monthly formations {span}, "
        f"{result.scored} scorecards with data quality passing",
        *(f"! {c}" for c in CAVEATS),
        *_excluded_lines(result.excluded),
        "",
        *horizon_section(result.entries),
        "",
        *ranked_section(result.ranked),
        "",
        f"-- Spec §12: do the rules lose to SPY? ({GO_LIVE_HORIZON}-session excess, READY) --",
    ]
    for list_name in LISTS:
        points = [
            (
                e.entry_date,
                (e.returns.get(GO_LIVE_HORIZON) or 0.0) - (e.spy.get(GO_LIVE_HORIZON) or 0.0),
            )
            for e in result.entries
            if e.list_name == list_name
            and e.entry_date is not None
            and e.returns.get(GO_LIVE_HORIZON) is not None
            and e.spy.get(GO_LIVE_HORIZON) is not None
        ]
        s = clustered_mean(points)
        if s.mean is None:
            lines.append(f"  {list_name:<15} no marked entries")
            continue
        t = "n/a" if s.t is None else f"{s.t:.2f}"
        verdict = "the rules beat SPY" if s.mean > 0 else "the rules lose to SPY: do not go live"
        lines.append(
            f"  {list_name:<15} n {s.n} ({s.clusters} dates) mean excess {s.mean * 100:+.1f}% "
            f"t {t}: {verdict}"
        )
    return "\n".join(lines)
