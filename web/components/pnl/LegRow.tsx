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
 * component (per web/CLAUDE.md's pnl/ note) — `complete` carries the gross
 * qualifier itself, so the row does not also hand-roll a "gross" span.
 */
export function LegRow({ leg }: { leg: PnlLegData }) {
  return (
    <tr data-testid="leg-row" className="text-xs">
      <td className="px-3 py-2 font-mono text-content">{leg.underlying}</td>
      <td className="px-3 py-2 text-muted">
        {leg.strategy === "covered_call" ? "CC" : leg.strategy === "roll" ? "roll" : "CSP"}{" "}
        {leg.right} {leg.strike != null ? leg.strike.toFixed(2) : "n/a"}
      </td>
      <td className="px-3 py-2 text-muted tabular">{leg.expiry ?? "n/a"}</td>
      <td className="px-3 py-2 text-content tabular">{leg.contracts}</td>
      <td className="px-3 py-2 text-muted tabular">{leg.days_held}</td>
      {/* Realised — null while open, never $0.00. */}
      <td data-testid="realized" className="px-3 py-2">
        <Money
          value={leg.net_pnl}
          kind="realized"
          signed
          complete={leg.commissions_complete}
        />
      </td>
      {/* Unrealised — filled by the parent from marks; null when no marks exist. */}
      <td data-testid="unrealized" className="px-3 py-2">
        <Money value={leg.unrealized_pnl} kind="unrealized" signed />
      </td>
      <td className="px-3 py-2 text-muted tabular">{leg.outcome.replace(/_/g, " ")}</td>
    </tr>
  );
}