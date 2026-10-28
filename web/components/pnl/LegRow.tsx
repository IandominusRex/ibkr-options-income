"use client";

import { Money } from "@/components/portfolio/Money";
import type { PnlLegData } from "./types";

/**
 * One leg of a P&L campaign thread — the row an operator reconciles against a
 * broker statement. Every unknown renders `n/a` with texture, never a zero: an
 * open leg has a mark, not a result, so its realised column must not claim
 * `$0.00`. Realised and unrealised are separate columns with distinct headers
 * because they answer different questions ("what did it earn?" vs "what is it
 * worth now?").
 *
 * `commissions_complete: false` renders the gross qualifier — the figure
 * excludes commissions and says so, rather than silently overclaiming "net".
 * Both money columns render through `portfolio/Money`, not a second money
 * component — `complete` carries the gross qualifier itself.
 */
export function LegRow({ leg }: { leg: PnlLegData }) {
  const cell = "py-2 pr-3";
  return (
    <tr data-testid="leg-row" className="border-t border-border text-[0.8125rem] first:border-t-0">
      <td className={`${cell} font-mono text-content`}>{leg.underlying}</td>
      <td className={`${cell} text-muted`}>
        {leg.strategy === "covered_call" ? "CC" : leg.strategy === "roll" ? "roll" : "CSP"} {leg.right}{" "}
        {leg.strike != null ? leg.strike.toFixed(2) : "n/a"}
      </td>
      <td className={`${cell} tabular font-mono text-muted`}>{leg.expiry ?? "n/a"}</td>
      <td className={`${cell} tabular text-right font-mono text-content`}>{leg.contracts}</td>
      <td className={`${cell} tabular text-right font-mono text-muted`}>{leg.days_held}</td>
      {/* Realised — null while open, never $0.00. */}
      <td data-testid="realized" className={`${cell} text-right font-mono`}>
        <Money value={leg.net_pnl} kind="realized" signed complete={leg.commissions_complete} />
      </td>
      {/* Unrealised — filled by the parent from marks; null when no marks exist. */}
      <td data-testid="unrealized" className={`${cell} text-right font-mono`}>
        <Money value={leg.unrealized_pnl} kind="unrealized" signed />
      </td>
      <td className={`${cell} tabular text-muted`}>{leg.outcome.replace(/_/g, " ")}</td>
    </tr>
  );
}
