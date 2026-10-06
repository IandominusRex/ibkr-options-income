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
              <th key={c.key} className="py-2 pr-4 text-right" aria-sort={sortKey === c.key ? (desc ? "descending" : "ascending") : "none"}>
                <button type="button" onClick={() => sortBy(c.key)}>
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
