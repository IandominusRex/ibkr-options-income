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
            <option value="">All</option><option value="system">System</option><option value="manual">Manual</option><option value="spreads">Spreads</option>
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
      {selected && <TradePanel key={selected} orderKey={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
