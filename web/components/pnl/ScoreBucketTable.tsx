"use client";

import { Money } from "@/components/portfolio/Money";
import type { ScoreBucketData } from "./types";

const SMALL_SAMPLE_THRESHOLD = 5;

/**
 * One score-vs-outcome bucket table (blended-score bands or per-component high/low split).
 * A bucket with n below SMALL_SAMPLE_THRESHOLD is labelled in words - a win rate from a
 * handful of trades is not evidence and must not read as one.
 */
export function ScoreBucketTable({
  buckets,
  label,
}: {
  buckets: ScoreBucketData[];
  label: string;
}) {
  if (buckets.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <h3 className="text-xs uppercase tracking-wide text-muted">{label}</h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left text-[10px] uppercase tracking-wide text-muted">
            <th className="px-2 py-1 font-normal">Band</th>
            <th className="px-2 py-1 font-normal">n</th>
            <th className="px-2 py-1 font-normal">Win rate</th>
            <th className="px-2 py-1 font-normal">Mean P&amp;L</th>
            <th className="px-2 py-1 font-normal">Total P&amp;L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {buckets.map((b) => (
            <tr key={b.label}>
              <td className="px-2 py-1 font-mono text-content">{b.label}</td>
              <td className="px-2 py-1 tabular text-content">
                {b.n}
                {b.n < SMALL_SAMPLE_THRESHOLD && (
                  <span className="ml-1 text-[10px] uppercase tracking-wide text-unknown">
                    small sample
                  </span>
                )}
              </td>
              <td className="px-2 py-1 tabular text-content">{Math.round(b.win_rate * 100)}%</td>
              <td className="px-2 py-1 tabular">
                <Money value={b.mean_pnl} kind="realized" signed />
              </td>
              <td className="px-2 py-1 tabular">
                <Money value={b.total_pnl} kind="realized" signed />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
