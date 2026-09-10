"use client";

import { Money } from "@/components/portfolio/Money";
import { UNKNOWN } from "@/lib/format";
import type { SignalCorrelationData } from "./types";

/**
 * How each signal relates to realized P&L. `pearson_r` and the low/high split render n/a
 * when undefined (n<2 or zero variance) - never a fabricated 0.
 */
export function CorrelationTable({ correlations }: { correlations: SignalCorrelationData[] }) {
  if (correlations.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <h3 className="text-xs uppercase tracking-wide text-muted">Signal correlations</h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left text-[10px] uppercase tracking-wide text-muted">
            <th className="px-2 py-1 font-normal">Signal</th>
            <th className="px-2 py-1 font-normal">n</th>
            <th className="px-2 py-1 font-normal">Pearson r</th>
            <th className="px-2 py-1 font-normal">Low-half mean P&amp;L</th>
            <th className="px-2 py-1 font-normal">High-half mean P&amp;L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {correlations.map((c) => (
            <tr key={c.signal}>
              <td className="px-2 py-1 font-mono text-content">{c.signal}</td>
              <td className="px-2 py-1 tabular text-content">{c.n}</td>
              <td className="px-2 py-1 tabular">
                {c.pearson_r == null ? (
                  <span className="hatch text-unknown">{UNKNOWN}</span>
                ) : (
                  c.pearson_r.toFixed(2)
                )}
              </td>
              <td className="px-2 py-1 tabular">
                {c.low_half_mean_pnl == null ? (
                  <span className="hatch text-unknown">{UNKNOWN}</span>
                ) : (
                  <Money value={c.low_half_mean_pnl} kind="realized" signed />
                )}
              </td>
              <td className="px-2 py-1 tabular">
                {c.high_half_mean_pnl == null ? (
                  <span className="hatch text-unknown">{UNKNOWN}</span>
                ) : (
                  <Money value={c.high_half_mean_pnl} kind="realized" signed />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
