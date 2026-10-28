"use client";

import { Money } from "@/components/portfolio/Money";
import { UNKNOWN } from "@/lib/format";
import type { SignalCorrelationData } from "./types";

const na = <span className="hatch text-unknown">{UNKNOWN}</span>;

/**
 * How each signal relates to realized P&L. `pearson_r` and the low/high split render n/a
 * when undefined (n<2 or zero variance) - never a fabricated 0.
 */
export function CorrelationTable({ correlations }: { correlations: SignalCorrelationData[] }) {
  if (correlations.length === 0) {
    return null;
  }
  const head = "py-1.5 pr-3 text-right font-semibold";
  const cell = "tabular py-2 pr-3 text-right font-mono";
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">Signal correlations</h3>
      <p className="text-xs text-muted md:hidden">Scroll sideways to see every column.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-[0.8125rem]">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold tracking-[0.04em] text-muted">
              <th className="py-1.5 pr-3 font-semibold">Signal</th>
              <th className={head}>n</th>
              <th className={head}>Pearson r</th>
              <th className={head}>Low-half mean P&amp;L</th>
              <th className={head}>High-half mean P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {correlations.map((c) => (
              <tr key={c.signal} className="border-t border-border first:border-t-0">
                <td className="py-2 pr-3 font-mono text-content">{c.signal}</td>
                <td className={`${cell} text-content`}>{c.n}</td>
                <td className={cell}>{c.pearson_r == null ? na : c.pearson_r.toFixed(2)}</td>
                <td className={cell}>
                  {c.low_half_mean_pnl == null ? na : <Money value={c.low_half_mean_pnl} kind="realized" signed />}
                </td>
                <td className={cell}>
                  {c.high_half_mean_pnl == null ? na : <Money value={c.high_half_mean_pnl} kind="realized" signed />}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
