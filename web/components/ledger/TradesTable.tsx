"use client";

import clsx from "clsx";
import { money, pct, signClass } from "./format";
import { OutcomePill } from "./OutcomePill";
import type { LedgerTrade } from "./types";

const HEADERS = [
  "Sell/Buy", "Put/Call", "Order Date", "Expiry", "Ticker", "Lots", "Strike", "Premium",
  "Outcome", "Stock gain", "DTE", "% Profit", "Net P&L", "Closed", "Book", "Notes",
];
const RIGHT = new Set(["Lots", "Strike", "Premium", "Stock gain", "DTE", "% Profit", "Net P&L"]);
const NUM = "tabular py-2 pr-4 text-right font-mono";

/** The operator's sheet as a table. A row opens the trade from the mouse or the keyboard. */
export function TradesTable({ trades, onSelect }: { trades: LedgerTrade[]; onSelect: (key: string) => void }) {
  if (trades.length === 0) return <p className="text-sm text-muted">No trades match the current filters.</p>;
  return (
    <div data-testid="trades-table">
      <p className="mb-1 text-xs text-muted md:hidden">Scroll sideways to see every column.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-[0.8125rem]">
          <thead className="text-left text-xs font-semibold tracking-[0.04em] text-muted">
            <tr>
              {HEADERS.map((h) => (
                <th key={h} scope="col" className={clsx("whitespace-nowrap py-2 pr-4 font-semibold", RIGHT.has(h) && "text-right")}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr
                key={t.order_key}
                tabIndex={0}
                onClick={() => onSelect(t.order_key)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(t.order_key);
                  }
                }}
                className="cursor-pointer border-t border-border hover:bg-sunk focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus"
              >
                <td className="py-2 pr-4">{t.side}</td>
                <td className="py-2 pr-4">{t.right === "P" ? "Put" : "Call"}</td>
                <td className="tabular py-2 pr-4 font-mono">{t.order_date}</td>
                <td className="tabular py-2 pr-4 font-mono">{t.expiry}</td>
                <td className="py-2 pr-4 font-mono font-semibold">{t.underlying}</td>
                <td className={NUM}>{t.lots}</td>
                <td className={NUM}>{t.strike}</td>
                <td className={clsx(NUM, signClass(t.premium))}>{money(t.premium, t.currency)}</td>
                <td className="py-2 pr-4">
                  <OutcomePill outcome={t.outcome} overridden={t.outcome_overridden} />
                </td>
                <td className={NUM}>{t.stock_gain === null ? "" : money(t.stock_gain, t.currency)}</td>
                <td className={NUM}>{t.dte}</td>
                <td className={NUM}>{pct(t.pct_profit)}</td>
                <td className={clsx(NUM, signClass(t.net_pnl))}>{money(t.net_pnl, t.currency)}</td>
                <td className="tabular py-2 pr-4 font-mono">{t.close_date ?? ""}</td>
                <td className="py-2 pr-4 text-muted">{t.book}</td>
                <td className="max-w-[16rem] truncate py-2 pr-4 text-muted">{t.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
