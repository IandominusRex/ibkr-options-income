"""The value book's input loader: one neutral, read-only module (spec §6.9, revision 3).

Reads ``data/research.db`` (``mode=ro``: the raw companyfacts payload through
``select_periods``/``select_ttm``, and daily bars) and the regime record through
``src.storage.regime_state.load_regime_state``, and computes the technical inputs with the
deterministic ``src/analytics/technicals.py``. The API and the value process load identical
inputs through it. It imports nothing from ``src.value`` and no enrichment module
(tests/test_value_fence.py), and it never writes.

``fetch_market_facts`` is the one network read here (yfinance through ``src/data``); callers
decide when to pay for it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from src.analytics.technicals import atr14_series, rsi14_series
from src.common.config import get_config
from src.common.value_types import (
    AnnualPeriod,
    DayBar,
    FilingEvent,
    InstantPoint,
    MarketFacts,
    PriceSeries,
    TtmPoint,
    ValueFinancials,
)
from src.research.ingest.concepts import (
    load_concept_map,
    resolve_line_item,
    select_periods,
    select_ttm,
)
from src.research.schemas import Fact
from src.research.store.models import (
    CompanyFactsRawRow,
    DailyBarRow,
    FilingIndexRow,
    FinancialRow,
    SymbolRow,
)

log = logging.getLogger(__name__)

ANNUAL_LIMIT = 11  # ten years of history plus the newest
CLOSES_KEPT = 260
_RS_SESSIONS = 126
_BETA_SESSIONS = 250


# ── pure: filings ───────────────────────────────────────────────────────────────────────────


def _dei_cover_shares(payload: dict, as_of: date) -> float | None:
    """The newest undimensioned cover-page share count filed on or before *as_of*."""
    try:
        entries = payload["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
    except (KeyError, TypeError):
        return None
    best: tuple[str, str, float] | None = None
    for e in entries or []:
        filed, end, val = e.get("filed"), e.get("end"), e.get("val")
        if (
            not isinstance(filed, str)
            or not isinstance(end, str)
            or not isinstance(val, int | float)
        ):
            continue
        if date.fromisoformat(filed) > as_of:
            continue
        key = (end, filed, float(val))
        if best is None or key[:2] > best[:2]:
            best = key
    return best[2] if best else None


def build_value_financials(
    payload: dict, *, as_of: date, stale_item_days: int = 200
) -> ValueFinancials:
    """Every line item of the concept map, as the filings stood on *as_of* (spec §6.2).

    Annual periods keep up to ``ANNUAL_LIMIT`` fiscal years. A TTM or latest-balance item whose
    period ends more than *stale_item_days* before the newest one is dropped: a concept the
    filer stopped tagging must not pass for a current figure.
    """
    concept_map = load_concept_map()
    us_gaap = (payload.get("facts") or {}).get("us-gaap")
    fin = ValueFinancials(entity_name=str(payload.get("entityName", "")), has_us_gaap=bool(us_gaap))
    if not us_gaap:
        return fin

    annual: dict[date, AnnualPeriod] = {}
    newest_fact: Fact | None = None
    for name, spec in concept_map.items():
        facts = resolve_line_item(payload, spec)
        if not facts:
            continue
        known = [f for f in facts if f.filed <= as_of]
        if known:
            top = max(known, key=lambda f: (f.filed, f.end))
            if newest_fact is None or (top.filed, top.end) > (newest_fact.filed, newest_fact.end):
                newest_fact = top
        for f in select_periods(
            facts, kind=spec.kind, period_type="annual", limit=ANNUAL_LIMIT, as_of=as_of
        ):
            period = annual.setdefault(f.end, AnnualPeriod(period_end=f.end))
            period.items[name] = f.value
            period.accns[name] = f.accn
        if spec.kind == "duration":
            ttm = select_ttm(facts, as_of=as_of)
            if ttm is not None:
                fin.ttm[name] = TtmPoint(value=ttm.value, end=ttm.end, basis=ttm.basis)
        else:
            latest = select_periods(
                facts, kind="instant", period_type="quarterly", limit=1, as_of=as_of
            )
            if latest:
                fin.latest[name] = InstantPoint(value=latest[0].value, end=latest[0].end)
        if name == "shares_diluted":
            quarter = select_periods(
                facts, kind="duration", period_type="quarterly", limit=1, as_of=as_of
            )
            if quarter:
                fin.shares_latest = quarter[0].value

    fin.annual = [annual[k] for k in sorted(annual, reverse=True)][:ANNUAL_LIMIT]
    ends = [p.end for p in fin.ttm.values()] + [p.end for p in fin.latest.values()]
    if ends:
        cutoff = max(ends) - timedelta(days=stale_item_days)
        fin.ttm = {k: v for k, v in fin.ttm.items() if v.end >= cutoff}
        fin.latest = {k: v for k, v in fin.latest.items() if v.end >= cutoff}
    fin.cover_shares = _dei_cover_shares(payload, as_of)
    if newest_fact is not None:
        fin.latest_accn = newest_fact.accn
        fin.latest_filed = newest_fact.filed
    return fin


# ── pure: prices ────────────────────────────────────────────────────────────────────────────


def _last(series: pd.Series) -> float | None:
    if series.empty:
        return None
    v = series.iloc[-1]
    return None if pd.isna(v) else float(v)


def build_price_series(bars: pd.DataFrame, spy: pd.DataFrame | None) -> PriceSeries | None:
    """Fixed-window technicals from daily bars (columns high, low, close, volume; a date index,
    ascending, already cut at as_of). None without a single bar."""
    if bars.empty:
        return None
    close = bars["close"].astype(float)
    sma20 = close.rolling(20).mean()
    atr = atr14_series(bars["high"].astype(float), bars["low"].astype(float), close)
    rsi = rsi14_series(close)
    n = len(close)
    ret_6m = float(close.iloc[-1] / close.iloc[-1 - _RS_SESSIONS] - 1) if n > _RS_SESSIONS else None
    spy_ret = beta = None
    if spy is not None and not spy.empty:
        spy_close = spy["close"].astype(float)
        if len(spy_close) > _RS_SESSIONS:
            spy_ret = float(spy_close.iloc[-1] / spy_close.iloc[-1 - _RS_SESSIONS] - 1)
        joined = pd.concat(
            [close.pct_change(), spy_close.pct_change()], axis=1, join="inner"
        ).dropna()
        joined = joined.iloc[-_BETA_SESSIONS:]
        if len(joined) >= 60:
            var = float(joined.iloc[:, 1].var())
            if var > 0:
                beta = float(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / var)
    dollar = (close * bars["volume"].astype(float)).iloc[-20:]
    tail = close.iloc[-CLOSES_KEPT:]
    return PriceSeries(
        as_of=pd.Timestamp(close.index[-1]).date(),
        close=float(close.iloc[-1]),
        sessions=n,
        closes=[float(c) for c in tail],
        sma20s=[None if pd.isna(s) else float(s) for s in sma20.iloc[-CLOSES_KEPT:]],
        sma20=_last(sma20) if n >= 20 else None,
        sma50=_last(close.rolling(50).mean()) if n >= 50 else None,
        sma200=_last(close.rolling(200).mean()) if n >= 200 else None,
        atr14=_last(atr) if n >= 15 else None,
        rsi14=_last(rsi) if n >= 15 else None,
        ret_6m=ret_6m,
        spy_ret_6m=spy_ret,
        beta_250=beta,
        adv_dollar_20=float(dollar.mean()) if len(dollar) else None,
    )


def _column(series: pd.Series, warmup: int = 0) -> list[float | None]:
    """A series as floats, None where it is NaN or inside its first *warmup* rows."""
    return [None if k + 1 < warmup or pd.isna(v) else float(v) for k, v in enumerate(series)]


def build_day_bars(bars: pd.DataFrame, after: date | None = None) -> list[DayBar]:
    """Every settled session after *after* (all of them when None) with the technicals the exit
    engine reads at its close. *bars* is ``read_bars``'s frame: the whole history up to the
    run's as_of, so a 50-day average is measured on real history, not on the days returned."""
    if bars.empty:
        return []
    close = bars["close"].astype(float)
    opens = _column(bars["open"]) if "open" in bars.columns else [None] * len(close)
    highs = _column(bars["high"].astype(float))
    lows = _column(bars["low"].astype(float))
    sma20 = _column(close.rolling(20).mean())
    sma50 = _column(close.rolling(50).mean())
    rsi = _column(rsi14_series(close), 15)
    atr = _column(atr14_series(bars["high"].astype(float), bars["low"].astype(float), close), 15)
    out: list[DayBar] = []
    for i, idx in enumerate(bars.index):
        day = pd.Timestamp(idx).date()
        if after is not None and day <= after:
            continue
        out.append(
            DayBar(
                date=day,
                open=opens[i],
                high=highs[i],
                low=lows[i],
                close=float(close.iloc[i]),
                sma20=sma20[i],
                sma50=sma50[i],
                rsi14=rsi[i],
                atr14=atr[i],
            )
        )
    return out


# ── I/O: read-only research.db ───────────────────────────────────────────────────────────────

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _resolve_path() -> str:
    """Filesystem path of data/research.db. Patched in tests."""
    url = get_config().research_db_url_abs()
    return url[len("sqlite:///") :] if url.startswith("sqlite:///") else url


def reset_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None


@contextmanager
def research_read() -> Iterator[Session | None]:
    """A ``mode=ro`` session on research.db; None when the file does not exist."""
    global _engine, _SessionLocal
    path = _resolve_path()
    if not Path(path).exists():
        yield None
        return
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///file:{path}?mode=ro&uri=true", future=True, connect_args={"timeout": 10}
        )
        _SessionLocal = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    assert _SessionLocal is not None
    s = _SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


def read_payload(session: Session, symbol: str) -> tuple[str | None, dict | None]:
    """(CIK, raw companyfacts payload) for *symbol*; None parts when missing or unparseable."""
    row = session.get(SymbolRow, symbol)
    cik = row.cik if row else None
    if not cik:
        return None, None
    raw = session.get(CompanyFactsRawRow, cik)
    if raw is None:
        return cik, None
    try:
        return cik, json.loads(raw.payload_json)
    except (json.JSONDecodeError, TypeError):
        log.warning("value_inputs: raw payload for %s is unparseable", symbol)
        return cik, None


def read_bars(session: Session, symbol: str, as_of: date) -> pd.DataFrame:
    rows = session.execute(
        select(DailyBarRow)
        .where(DailyBarRow.symbol == symbol, DailyBarRow.date <= as_of)
        .order_by(DailyBarRow.date)
    ).scalars()
    data = [
        (r.date, r.open, r.high, r.low, r.close, r.volume or 0.0)
        for r in rows
        if r.close is not None and r.high is not None and r.low is not None
    ]
    frame = pd.DataFrame(data, columns=["date", "open", "high", "low", "close", "volume"])
    return frame.set_index("date")


def filings_coverage(session: Session, symbols: list[str]) -> tuple[int, int]:
    """(names with a raw companyfacts payload, names asked about): how far the research worker's
    sweep has filled research.db for a universe."""
    if not symbols:
        return 0, 0
    have = session.scalar(
        select(func.count())
        .select_from(SymbolRow)
        .join(CompanyFactsRawRow, CompanyFactsRawRow.cik == SymbolRow.cik)
        .where(SymbolRow.symbol.in_(symbols))
    )
    return int(have or 0), len(symbols)


def symbol_is_etf(session: Session, symbol: str) -> bool:
    """The research directory's own ETF flag (spec §6.1: ETFs are not applicable)."""
    row = session.get(SymbolRow, symbol)
    return bool(row is not None and row.is_etf)


def newest_bar_before(session: Session, symbol: str, before: date) -> date | None:
    """The newest settled bar's date strictly before *before* (a bar dated today may still be
    forming: the research page's on-demand refresh writes it during the session)."""
    return session.execute(
        select(DailyBarRow.date)
        .where(DailyBarRow.symbol == symbol, DailyBarRow.date < before)
        .order_by(DailyBarRow.date.desc())
        .limit(1)
    ).scalar_one_or_none()


def closes_on(session: Session, symbols: list[str], day: date) -> dict[str, float]:
    """Each symbol's close on *day*, read from the bars as they stand now (one fetch, so a split
    or dividend adjustment applies to both ends of a return alike). Missing names are absent."""
    if not symbols:
        return {}
    rows = session.execute(
        select(DailyBarRow.symbol, DailyBarRow.close).where(
            DailyBarRow.date == day, DailyBarRow.symbol.in_(symbols)
        )
    )
    return {symbol: float(close) for symbol, close in rows if close is not None}


def filings_between(
    session: Session, symbols: list[str], start: date, end: date
) -> dict[str, list[FilingEvent]]:
    """Each symbol's indexed filings filed after *start* and on or before *end*, oldest first
    (spec §7.1 trigger 4). Empty when the research worker has not built the index yet."""
    if not symbols:
        return {}
    try:
        rows = session.execute(
            select(SymbolRow.symbol, FilingIndexRow)
            .join(FilingIndexRow, FilingIndexRow.cik == SymbolRow.cik)
            .where(
                SymbolRow.symbol.in_(symbols),
                FilingIndexRow.filed > start,
                FilingIndexRow.filed <= end,
            )
            .order_by(FilingIndexRow.filed, FilingIndexRow.accn)
        ).all()
    except OperationalError:  # a research.db the worker has not migrated yet
        log.warning("value_inputs: research.db has no filing_index yet")
        return {}
    out: dict[str, list[FilingEvent]] = {}
    for symbol, row in rows:
        out.setdefault(symbol, []).append(
            FilingEvent(
                accn=row.accn,
                form=row.form,
                filed=row.filed,
                items=[t for t in row.items.split(",") if t],
                going_concern=row.going_concern,
            )
        )
    return out


def going_concern_flags(session: Session, symbols: list[str], as_of: date) -> dict[str, bool]:
    """Each symbol's going-concern read of its newest **read** periodic filing filed on or before
    *as_of* (spec §7). A name none of whose recent periodic filings has been read is absent:
    unknown, never "no doubt"."""
    periodic = ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A")
    if not symbols:
        return {}
    try:
        rows = session.execute(
            select(SymbolRow.symbol, FilingIndexRow.going_concern)
            .join(FilingIndexRow, FilingIndexRow.cik == SymbolRow.cik)
            .where(
                SymbolRow.symbol.in_(symbols),
                FilingIndexRow.form.in_(periodic),
                FilingIndexRow.filed <= as_of,
                FilingIndexRow.going_concern.is_not(None),
            )
            .order_by(FilingIndexRow.filed, FilingIndexRow.accn)
        ).all()
    except OperationalError:
        return {}
    return {symbol: bool(flag) for symbol, flag in rows}  # the newest read wins


def current_fingerprint_parts(session: Session, symbol: str) -> dict[str, Any]:
    """The cheap half of the ticker-file fingerprint (spec §6.9): the newest accession in
    ``financials`` and the newest bar, without parsing the raw payload."""
    fin = session.execute(
        select(FinancialRow.accn, FinancialRow.filed)
        .where(FinancialRow.symbol == symbol, FinancialRow.filed.is_not(None))
        .order_by(FinancialRow.filed.desc(), FinancialRow.accn.desc())
        .limit(1)
    ).first()
    bar = session.execute(
        select(DailyBarRow.date, DailyBarRow.close)
        .where(DailyBarRow.symbol == symbol)
        .order_by(DailyBarRow.date.desc())
        .limit(1)
    ).first()
    return {
        "latest_accn": fin[0] if fin else None,
        "latest_filed": fin[1] if fin else None,
        "price_date": bar[0] if bar else None,
        "price_close": bar[1] if bar else None,
    }


def load_regime() -> str:
    """SPY's effective market regime, or "unknown" when none is recorded."""
    from src.storage.regime_state import load_regime_state

    state = load_regime_state()
    return state.spy.effective.value if state is not None else "unknown"


def fetch_market_facts(symbol: str) -> MarketFacts:
    """yfinance market cap, sector, industry, quote type and next earnings date. Never raises;
    a failed fetch is an empty ``MarketFacts`` (the data-quality gate then says UNKNOWN)."""
    from src.data.factory import get_fundamentals_provider

    provider = get_fundamentals_provider()
    try:
        info = provider.get_info(symbol) or {}
    except Exception:  # noqa: BLE001 - a provider failure is missing data, not a crash
        info = {}
    cap = info.get("marketCap")
    next_earnings: date | None = None
    if info.get("quoteType") != "ETF":
        try:
            cal = provider.get_calendar(symbol) or {}
            for ts in cal.get("Earnings Date", []) or []:
                d = ts.date() if hasattr(ts, "date") else ts
                if isinstance(d, date):
                    next_earnings = d if next_earnings is None else min(next_earnings, d)
        except Exception:  # noqa: BLE001
            next_earnings = None
    return MarketFacts(
        market_cap=float(cap) if isinstance(cap, int | float) and cap > 0 else None,
        sector=info.get("sector") if isinstance(info.get("sector"), str) else None,
        industry=info.get("industry") if isinstance(info.get("industry"), str) else None,
        quote_type=info.get("quoteType") if isinstance(info.get("quoteType"), str) else None,
        next_earnings=next_earnings,
    )
