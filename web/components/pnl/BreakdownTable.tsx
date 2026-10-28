"use client";

import { UNKNOWN } from "@/lib/format";
import type { PnlBucketData } from "./types";

/**
 * One breakdown grid, by strategy or by symbol, over the buckets `build_summary` already ordered
 * (realised descending, ties by label). A bucket with nothing closed renders `n/a` in its rate
 * columns, never `0%`: an unknown win rate is not a zero win rate. Scrolls inside its own box on a
 * phone.
 */
export function BreakdownTable({ buckets, label }: { buckets: PnlBucketData[]; label: string }) {
  if (buckets.length === 0) {
    return null;
  }
  const head = "py-1.5 pr-3 text-right font-semibold";
  return (
    <div className="space-y-2" data-testid="breakdown-table">
      <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">{label}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-[0.8125rem]">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold tracking-[0.04em] text-muted">
              <th className="py-1.5 pr-3 font-semibold">Label</th>
              <th className={head}>Closed</th>
              <th className={head}>Realized</th>
              <th className={head}>Win rate</th>
              <th className={head}>Mean days held</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.label} className="border-t border-border first:border-t-0">
                <td className="py-2 pr-3 font-mono text-content">{b.label}</td>
                <td className="tabular py-2 pr-3 text-right font-mono text-content">{b.n_closed}</td>
                <td className="tabular py-2 pr-3 text-right font-mono">
                  <span className={b.realized < 0 ? "text-loss" : "text-content"}>
                    {b.realized < 0 ? "-" : ""}${Math.abs(b.realized).toFixed(2)}
                  </span>
                </td>
                <td className="tabular py-2 pr-3 text-right font-mono">
                  {b.win_rate == null ? (
                    <span className="hatch text-unknown">{UNKNOWN}</span>
                  ) : (
                    `${Math.round(b.win_rate * 100)}%`
                  )}
                </td>
                <td className="tabular py-2 pr-3 text-right font-mono">
                  {b.mean_days_held == null ? (
                    <span className="hatch text-unknown">{UNKNOWN}</span>
                  ) : (
                    b.mean_days_held.toFixed(1)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
