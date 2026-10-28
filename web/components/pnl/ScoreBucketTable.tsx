"use client";

import { Money } from "@/components/portfolio/Money";
import type { ScoreBucketData } from "./types";

const SMALL_SAMPLE_THRESHOLD = 5;

/**
 * One score-vs-outcome bucket table (blended-score bands or per-component high/low split).
 * A bucket with n below SMALL_SAMPLE_THRESHOLD is labelled in words - a win rate from a
 * handful of trades is not evidence and must not read as one.
 */
export function ScoreBucketTable({ buckets, label }: { buckets: ScoreBucketData[]; label: string }) {
  if (buckets.length === 0) {
    return null;
  }
  const head = "py-1.5 pr-3 text-right font-semibold";
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">{label}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-[0.8125rem]">
          <thead>
            <tr className="border-b border-border text-left text-xs font-semibold tracking-[0.04em] text-muted">
              <th className="py-1.5 pr-3 font-semibold">Band</th>
              <th className={head}>n</th>
              <th className={head}>Win rate</th>
              <th className={head}>Mean P&amp;L</th>
              <th className={head}>Total P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.label} className="border-t border-border first:border-t-0">
                <td className="py-2 pr-3 font-mono text-content">{b.label}</td>
                <td className="tabular py-2 pr-3 text-right font-mono text-content">
                  {b.n}
                  {b.n < SMALL_SAMPLE_THRESHOLD && <span className="ml-1 text-xs text-unknown">small sample</span>}
                </td>
                <td className="tabular py-2 pr-3 text-right font-mono text-content">{Math.round(b.win_rate * 100)}%</td>
                <td className="tabular py-2 pr-3 text-right font-mono">
                  <Money value={b.mean_pnl} kind="realized" signed />
                </td>
                <td className="tabular py-2 pr-3 text-right font-mono">
                  <Money value={b.total_pnl} kind="realized" signed />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
