"""Minute-by-minute replay of the live spreads rules over ThetaData history.

The backtest trades SPX dailies as a stand-in for SPY (SPY ≈ SPX/10 less accrued dividends, and SPX history
is deeper and tighter): every dollar threshold is scaled by ``backtest.trade_scale`` and P&L is
reported in SPY-equivalent dollars after SPY commissions. It reuses the service's pure modules
— gex, selector, risk, manager — so a result is a statement about the exact rules that trade.
Known differences from live: OI is the prior close (same as live), IV is backed out of each
minute's mid, fills pay ``fill_haircut`` of the mid→natural gap, 0DTE expiry only for GEX.
The entry trigger's tape is rebuilt from the minute index prices (open = the first print at or
after 09:30, a running high/low, prior close = the previous session's last print), and every
trade carries the same tags as the live trade log, so ``report.tag_breakdowns`` reads both.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal, Protocol

from src.common.config import SpreadsBacktestCfg, SpreadsCfg
from src.common.market_hours import is_trading_day, previous_session
from src.common.schemas import (
    ChainOption,
    ChainSnapshot,
    EntryTrigger,
    SessionSnapshot,
    SpreadPosition,
    SpreadRiskContext,
    SpreadSide,
)
from src.spreads.gex import build_levels, expected_move, regime_at
from src.spreads.manager import debit_to_close, evaluate_exit, intrinsic_debit
from src.spreads.pricing import ET, delta, implied_vol, years_to_close
from src.spreads.risk import validate
from src.spreads.selector import select_candidates
from src.spreads.tape import SessionTape, trigger


class HistorySource(Protocol):
    def option_quotes(
        self, symbol: str, expiration: date, day: date, interval: str = "1m"
    ) -> list[dict[str, str]]: ...
    def open_interest(self, symbol: str, expiration: date, day: date) -> list[dict[str, str]]: ...
    def index_prices(
        self, symbol: str, day: date, interval: str = "1m"
    ) -> list[dict[str, str]]: ...


@dataclass
class DayData:
    day: date
    spot: dict[datetime, float]  # aware-UTC minute → index price
    quotes: dict[
        datetime, dict[tuple[float, str], tuple[float, float]]
    ]  # minute → (strike, right) → (bid, ask)
    oi: dict[tuple[float, str], int]
    prior_close: float | None = None  # the previous session's last index print


@dataclass(frozen=True)
class BacktestTrade:
    day: date
    side: str
    short_strike: float
    long_strike: float
    contracts: int
    entry_time: datetime
    exit_time: datetime
    entry_credit: float  # SPX points
    exit_debit: float  # SPX points
    exit_reason: str
    regime: str
    pnl_usd: float  # SPY-equivalent, after commissions
    trigger: str
    move_em: float | None
    gap_pct: float | None
    gap_day: bool
    minutes_after_open: int
    hold_minutes: float
    mae_usd: float  # SPY-equivalent: the worst mark against the position while open


@dataclass
class _Held:
    """An open backtest position and the tags it was opened with."""

    pos: SpreadPosition
    opened: datetime
    regime: str
    move_em: float | None
    gap_pct: float | None
    gap_day: bool
    minutes_after_open: int
    worst_debit: float  # highest mid debit-to-close seen, SPX points


def _minute(raw: str) -> datetime:
    dt = datetime.fromisoformat(raw.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(UTC).replace(second=0, microsecond=0)


def _right(raw: str) -> str:
    return "C" if raw.strip().upper().startswith("C") else "P"


def load_day(client: HistorySource, cfg: SpreadsBacktestCfg, day: date) -> DayData:
    spot: dict[datetime, float] = {}
    for r in client.index_prices(cfg.index_symbol, day):
        price = float(r.get("price") or 0.0)
        if price > 0:
            spot[_minute(r["timestamp"])] = price
    before = [
        float(r.get("price") or 0.0)
        for r in client.index_prices(cfg.index_symbol, previous_session(day))
    ]
    prior_close = next((p for p in reversed(before) if p > 0), None)
    quotes: dict[datetime, dict[tuple[float, str], tuple[float, float]]] = defaultdict(dict)
    for r in client.option_quotes(cfg.option_symbol, day, day):
        bid, ask = float(r.get("bid") or 0.0), float(r.get("ask") or 0.0)
        if ask <= 0:
            continue
        quotes[_minute(r["timestamp"])][(float(r["strike"]), _right(r["right"]))] = (bid, ask)
    oi = {
        (float(r["strike"]), _right(r["right"])): int(float(r["open_interest"]))
        for r in client.open_interest(cfg.option_symbol, day, day)
        if r.get("open_interest")
    }
    return DayData(day=day, spot=spot, quotes=dict(quotes), oi=oi, prior_close=prior_close)


def chain_at(data: DayData, minute: datetime, symbol: str) -> ChainSnapshot | None:
    spot = data.spot.get(minute)
    book = data.quotes.get(minute)
    if spot is None or not book:
        return None
    t = years_to_close(minute, data.day)
    options = []
    for (k, r), (bid, ask) in book.items():
        mid = (bid + ask) / 2 if ask >= bid >= 0 else None
        iv = implied_vol(mid, spot, k, t, r) if mid else None
        options.append(
            ChainOption(
                strike=k,
                right=r,  # type: ignore[arg-type]
                expiry=data.day,
                bid=bid,
                ask=ask,
                iv=iv,
                delta=delta(spot, k, t, iv, r) if iv else None,
                open_interest=data.oi.get((k, r)),
            )
        )
    return ChainSnapshot(symbol=symbol, spot=spot, as_of=minute, options=options)


def backtest_cfg(cfg: SpreadsCfg) -> SpreadsCfg:
    """The live rules restated in SPX units (every dollar/point threshold × trade_scale)."""
    k = cfg.backtest.trade_scale
    return cfg.model_copy(
        update={
            "enabled": True,
            "mode": "shadow",
            "gex": cfg.gex.model_copy(update={"scale_to_underlying": 1.0}),
            "selection": cfg.selection.model_copy(update={"width": cfg.selection.width * k}),
            # The risk caps are shares of capital, so they need no scaling; run_day passes the
            # capital itself in SPX dollars (× trade_scale).
            "risk": cfg.risk.model_copy(
                update={"min_excess_liquidity_usd": 0.0, "max_quote_age_seconds": 1e9}
            ),
            "exits": cfg.exits.model_copy(
                update={"let_expire_max_debit": cfg.exits.let_expire_max_debit * k}
            ),
        }
    )


def with_overrides(
    cfg: SpreadsCfg,
    *,
    profit_take_pct: float | None = None,
    entry_trigger: EntryTrigger | None = None,
    negative_gamma: Literal["allow", "skip"] | None = None,
) -> SpreadsCfg:
    """The backtest CLI's comparison switches (None keeps the configured value)."""
    out = cfg
    if profit_take_pct is not None:
        out = out.model_copy(
            update={"exits": out.exits.model_copy(update={"profit_take_pct": profit_take_pct})}
        )
    if entry_trigger is not None:
        out = out.model_copy(
            update={"entry": out.entry.model_copy(update={"trigger": entry_trigger})}
        )
    if negative_gamma is not None:
        out = out.model_copy(
            update={"gex": out.gex.model_copy(update={"negative_gamma_action": negative_gamma})}
        )
    return out


def _leg(data: DayData, minute: datetime, strike: float, right: str) -> ChainOption | None:
    bidask = data.quotes.get(minute, {}).get((strike, right))
    if bidask is None:
        return None
    return ChainOption(strike=strike, right=right, expiry=data.day, bid=bidask[0], ask=bidask[1])  # type: ignore[arg-type]


def _fill(mid: float, natural: float, haircut: float) -> float:
    return mid + haircut * (natural - mid)


def run_day(
    data: DayData, cfg: SpreadsCfg, capital_usd: float | None = None
) -> list[BacktestTrade]:
    """One day of the live rules. *capital_usd* (default: the starting capital) sizes every trade."""
    bcfg = backtest_cfg(cfg)
    k, h = cfg.backtest.trade_scale, cfg.backtest.fill_haircut
    capital = cfg.risk.starting_capital_usd if capital_usd is None else capital_usd
    comm = cfg.execution.commission_per_contract
    s = cfg.schedule
    symbol = cfg.backtest.option_symbol
    refresh = timedelta(minutes=s.map_refresh_minutes)
    entry_every = timedelta(minutes=s.entry_check_minutes)
    minutes = sorted(m for m in data.quotes if m in data.spot)
    bell = datetime.combine(data.day, time(9, 30), tzinfo=ET)

    gex_chain: ChainSnapshot | None = None
    levels = None
    map_at: datetime | None = None
    last_entry: datetime | None = None
    tape = SessionTape(day=data.day)
    day_open: float | None = None
    high: float | None = None
    low: float | None = None
    open_: list[_Held] = []
    expiring: list[_Held] = []
    trades: list[BacktestTrade] = []
    sides_today: list[SpreadSide] = []
    realized_scaled = 0.0
    last_spot: float | None = None

    def book(held: _Held, t1: datetime, debit: float, reason: str, legs: int) -> BacktestTrade:
        pos = held.pos
        pnl = (pos.entry_credit - debit) * 100 * pos.contracts / k - (
            2 + legs
        ) * comm * pos.contracts
        mae = max(0.0, held.worst_debit - pos.entry_credit) * 100 * pos.contracts / k
        return BacktestTrade(
            day=data.day,
            side=pos.side,
            short_strike=pos.short_strike,
            long_strike=pos.long_strike,
            contracts=pos.contracts,
            entry_time=held.opened,
            exit_time=t1,
            entry_credit=pos.entry_credit,
            exit_debit=debit,
            exit_reason=reason,
            regime=held.regime,
            pnl_usd=pnl,
            trigger=cfg.entry.trigger,
            move_em=held.move_em,
            gap_pct=held.gap_pct,
            gap_day=held.gap_day,
            minutes_after_open=held.minutes_after_open,
            hold_minutes=(t1 - held.opened).total_seconds() / 60.0,
            mae_usd=mae,
        )

    for m in minutes:
        hhmm = m.astimezone(ET).strftime("%H:%M")
        spot = data.spot[m]
        last_spot = spot
        if m >= bell:  # the session tape, as the live service would have sampled it
            day_open = spot if day_open is None else day_open
            high = spot if high is None else max(high, spot)
            low = spot if low is None else min(low, spot)
            tape.observe(
                SessionSnapshot(
                    as_of=m,
                    last=spot,
                    open=day_open,
                    high=high,
                    low=low,
                    prior_close=data.prior_close,
                )
            )
        if s.map_time <= hhmm < s.force_close and (map_at is None or m - map_at >= refresh):
            chain = chain_at(data, m, symbol)
            if chain is not None:
                gex_chain, map_at = chain, m
                levels = build_levels(chain, chain, bcfg, m)
                if tape.day_em is None:
                    tape.day_em = levels.expected_move  # the day's first expected move

        for held in list(open_):
            pos = held.pos
            right = "P" if pos.side == "put" else "C"
            sq, lq = _leg(data, m, pos.short_strike, right), _leg(data, m, pos.long_strike, right)
            mid, nat = debit_to_close(sq, lq)
            if mid is not None:
                held.worst_debit = max(held.worst_debit, mid)
            decision = evaluate_exit(pos, sq, lq, spot, m, bcfg)
            if decision is None:
                continue
            open_.remove(held)
            if not decision.close:
                expiring.append(held)
                continue
            base = mid if mid is not None else nat if nat is not None else pos.width
            debit = min(pos.width, _fill(base, nat if nat is not None else base, h))
            trade = book(held, m, debit, decision.reason, 2)
            trades.append(trade)
            realized_scaled += trade.pnl_usd * k

        if levels is None or gex_chain is None or not (s.entry_start <= hhmm < s.entry_end):
            continue
        allowed = trigger(tape, m, bcfg)
        if not allowed.sides or (last_entry is not None and m - last_entry < entry_every):
            continue
        last_entry = m
        chain = chain_at(data, m, symbol)
        if chain is None:
            continue
        lv = levels.model_copy(
            update={
                "as_of": m,
                "spot": chain.spot,
                "regime": regime_at(gex_chain, chain.spot, levels.scale, m),
                "expected_move": expected_move(
                    chain.options, chain.spot, data.day, bcfg.selection.em_straddle_factor
                ),
            }
        )
        for c in select_candidates(chain, lv, bcfg, m, sides=allowed.sides):
            held_now = open_ + expiring
            ctx = SpreadRiskContext(
                now=m,
                levels=lv,
                open_spreads=len(held_now),
                open_risk_usd=sum(
                    (x.pos.width - x.pos.entry_credit) * 100 * x.pos.contracts for x in held_now
                ),
                trades_today=len(sides_today),
                realized_pnl_today_usd=realized_scaled,
                excess_liquidity_usd=1e12,
                capital_usd=capital * k,  # SPX-scale dollars, like every other amount here
                sides_today=list(sides_today),
            )
            v = validate(c, ctx, bcfg)
            if not v.approved:
                continue
            credit = _fill(c.credit_mid, c.credit_natural, h)
            pos = SpreadPosition(
                spread_id=c.spread_id,
                mode="shadow",
                side=c.side,
                expiry=c.expiry,
                short_strike=c.short_strike,
                long_strike=c.long_strike,
                width=c.width,
                contracts=v.contracts,
                entry_credit=credit,
                opened_at=m,
            )
            gap = tape.gap_pct()
            open_.append(
                _Held(
                    pos=pos,
                    opened=m,
                    regime=lv.regime,
                    move_em=tape.move_em(c.side),
                    gap_pct=gap,
                    gap_day=gap is not None and abs(gap) >= cfg.entry.gap_day_pct,
                    minutes_after_open=max(0, int((m - bell).total_seconds() // 60)),
                    worst_debit=credit,
                )
            )
            sides_today.append(c.side)

    end = minutes[-1] if minutes else None
    for held in expiring + open_:
        debit = intrinsic_debit(held.pos, last_spot) if last_spot is not None else held.pos.width
        trades.append(book(held, end or held.opened, debit, "expired", 0))
    return trades


def run_backtest(
    client: HistorySource, cfg: SpreadsCfg, start: date, end: date
) -> list[BacktestTrade]:
    """Every trading day in [start, end]; each day sizes off the capital the days before left."""
    trades: list[BacktestTrade] = []
    capital = cfg.risk.starting_capital_usd
    day = start
    while day <= end:
        if is_trading_day(day):
            data = load_day(client, cfg.backtest, day)
            if data.quotes:
                today = run_day(data, cfg, capital)
                capital += sum(t.pnl_usd for t in today)
                trades.extend(today)
        day += timedelta(days=1)
    return trades
