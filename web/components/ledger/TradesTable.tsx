"use client";

import { money, pct, signClass } from "./format";
import { OutcomePill } from "./OutcomePill";
import type { LedgerTrade } from "./types";

const HEADERS = [
  "Sell/Buy", "Put/Call", "Order Date", "Expiry", "Ticker", "Lots", "Strike", "Premium",
  "Outcome", "Stock gain", "DTE", "% Profit", "Net P&L", "Closed", "Book", "Notes",
];

export function TradesTable({ trades, onSelect }: { trades: LedgerTrade[]; onSelect: (key: string) => void }) {
  if (trades.length === 0) return <p className="text-sm text-muted">No trades match the current filters.</p>;
  return (
    <div className="overflow-x-auto" data-testid="trades-table">
      <table className="w-full text-sm">
        <thead className="text-left text-muted">
          <tr>{HEADERS.map((h) => <th key={h} scope="col" className="whitespace-nowrap py-2 pr-4">{h}</th>)}</tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr
              key={t.order_key}
              onClick={() => onSelect(t.order_key)}
              className="cursor-pointer border-t border-border hover:bg-elevated"
            >
              <td className="py-2 pr-4">{t.side}</td>
              <td className="py-2 pr-4">{t.right === "P" ? "Put" : "Call"}</td>
              <td className="tabular py-2 pr-4">{t.order_date}</td>
              <td className="tabular py-2 pr-4">{t.expiry}</td>
              <td className="py-2 pr-4 font-mono">{t.underlying}</td>
              <td className="tabular py-2 pr-4 text-right">{t.lots}</td>
              <td className="tabular py-2 pr-4 text-right">{t.strike}</td>
              <td className={`tabular py-2 pr-4 text-right ${signClass(t.premium)}`}>{money(t.premium, t.currency)}</td>
              <td className="py-2 pr-4"><OutcomePill outcome={t.outcome} overridden={t.outcome_overridden} /></td>
              <td className="tabular py-2 pr-4 text-right">{t.stock_gain === null ? "" : money(t.stock_gain, t.currency)}</td>
              <td className="tabular py-2 pr-4 text-right">{t.dte}</td>
              <td className="tabular py-2 pr-4 text-right">{pct(t.pct_profit)}</td>
              <td className={`tabular py-2 pr-4 text-right ${signClass(t.net_pnl)}`}>{money(t.net_pnl, t.currency)}</td>
              <td className="tabular py-2 pr-4">{t.close_date ?? ""}</td>
              <td className="py-2 pr-4 text-muted">{t.book}</td>
              <td className="max-w-[16rem] truncate py-2 pr-4 text-muted">{t.notes}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
