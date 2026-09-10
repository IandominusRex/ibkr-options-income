"use client";

import { UNKNOWN } from "@/lib/format";
import type { PnlBucketData } from "./types";

/**
 * One breakdown grid — by strategy or by symbol — over the buckets
 * `build_summary` already ordered (realised descending, ties by label). A
 * bucket with nothing closed renders `n/a` in its rate columns, never `0%`:
 * an unknown win rate is not a zero win rate.
 */
export function BreakdownTable({
  buckets,
  label,
}: {
  buckets: PnlBucketData[];
  label: string;
}) {
  if (buckets.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2" data-testid="breakdown-table">
      <h3 className="text-xs uppercase tracking-wide text-muted">{label}</h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left text-[10px] uppercase tracking-wide text-muted">
            <th className="px-2 py-1 font-normal">Label</th>
            <th className="px-2 py-1 font-normal">Closed</th>
            <th className="px-2 py-1 font-normal">Realized</th>
            <th className="px-2 py-1 font-normal">Win rate</th>
            <th className="px-2 py-1 font-normal">Mean days held</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {buckets.map((b) => (
            <tr key={b.label}>
              <td className="px-2 py-1 font-mono text-content">{b.label}</td>
              <td className="px-2 py-1 text-content tabular">{b.n_closed}</td>
              <td className="px-2 py-1 tabular">
                <span className={b.realized < 0 ? "text-loss" : "text-content"}>
                  {b.realized < 0 ? "-" : ""}${Math.abs(b.realized).toFixed(2)}
                </span>
              </td>
              <td className="px-2 py-1 tabular">
                {b.win_rate == null ? (
                  <span className="hatch text-unknown">{UNKNOWN}</span>
                ) : (
                  `${Math.round(b.win_rate * 100)}%`
                )}
              </td>
              <td className="px-2 py-1 tabular">
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
  );
}