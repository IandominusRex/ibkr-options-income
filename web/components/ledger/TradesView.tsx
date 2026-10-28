"use client";

import clsx from "clsx";
import { useId, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";
import { apiFetch } from "@/lib/api";
import { BackToLedger } from "./BackToLedger";
import { TradePanel } from "./TradePanel";
import { TradesTable } from "./TradesTable";
import { OUTCOMES, type LedgerTradesResponse } from "./types";

type Filters = { symbol: string; right: string; outcome: string; book: string; tag: string; since: string; until: string; sort: string };
const EMPTY: Filters = { symbol: "", right: "", outcome: "", book: "", tag: "", since: "", until: "", sort: "-order_date" };

function Field({ label, children }: { label: string; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="grid gap-1">
      <label htmlFor={id} className={FIELD_LABEL}>
        {label}
      </label>
      {children(id)}
    </div>
  );
}

/**
 * The operator's sheet as a filterable table. One composed query string drives both the
 * fetch and the CSV export link, so the export always carries the filters on screen.
 * `fixedSymbol` pins the ticker (the drill-down page) and hides the back link, the heading and the
 * ticker filter.
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
  const select = clsx(FIELD, "w-full");

  return (
    <div className="grid gap-4" data-testid="trades-view">
      {!fixedSymbol && (
        <div className="grid gap-1">
          <BackToLedger />
          <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Ledger trades</h1>
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {!fixedSymbol && (
          <Field label="Ticker">
            {(id) => <input id={id} value={f.symbol} onChange={set("symbol")} autoComplete="off" autoCapitalize="characters" spellCheck={false} className={select} />}
          </Field>
        )}
        <Field label="Put/Call">
          {(id) => (
            <select id={id} value={f.right} onChange={set("right")} className={select}>
              <option value="">All</option>
              <option value="P">Put</option>
              <option value="C">Call</option>
            </select>
          )}
        </Field>
        <Field label="Outcome">
          {(id) => (
            <select id={id} value={f.outcome} onChange={set("outcome")} className={select}>
              <option value="">All</option>
              {OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Book">
          {(id) => (
            <select id={id} value={f.book} onChange={set("book")} className={select}>
              <option value="">All</option>
              <option value="system">System</option>
              <option value="manual">Manual</option>
              <option value="spreads">Spreads</option>
            </select>
          )}
        </Field>
        <Field label="Tag">{(id) => <input id={id} value={f.tag} onChange={set("tag")} autoComplete="off" className={select} />}</Field>
        <Field label="From">{(id) => <input id={id} type="date" value={f.since} onChange={set("since")} className={select} />}</Field>
        <Field label="To">{(id) => <input id={id} type="date" value={f.until} onChange={set("until")} className={select} />}</Field>
        <Field label="Sort">
          {(id) => (
            <select id={id} value={f.sort} onChange={set("sort")} className={select}>
              <option value="-order_date">Newest first</option>
              <option value="order_date">Oldest first</option>
              <option value="-pct_profit">% Profit high to low</option>
              <option value="-net_pnl">Net P&L high to low</option>
              <option value="net_pnl">Net P&L low to high</option>
              <option value="expiry">Expiry soonest</option>
            </select>
          )}
        </Field>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        {data ? <p className="text-[0.8125rem] text-muted">{data.n} trades</p> : <span />}
        <a
          href={`/api/ledger/trades.csv?${qs}`}
          className="inline-flex min-h-11 items-center text-[0.8125rem] font-semibold underline underline-offset-2 md:min-h-8"
        >
          Export CSV
        </a>
      </div>
      {isError && <p className="text-sm text-muted">Could not load trades.</p>}
      {data && <TradesTable trades={data.trades} onSelect={setSelected} />}
      {selected && <TradePanel key={selected} orderKey={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
