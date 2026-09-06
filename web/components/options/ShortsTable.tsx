"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { UNKNOWN, relativeAge } from "@/lib/format";
import { EmptyState } from "./EmptyState";
import type { ShortListResponse } from "./types";

export function ShortsTable() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "shorts"],
    queryFn: () => apiFetch<ShortListResponse>("/options/shorts"),
    placeholderData: (prev) => prev,
  });

  if (isLoading) return <p className="text-sm text-muted">Loading shorts</p>;
  if (isError) return <p className="text-sm text-muted">Could not load shorts</p>;
  const shorts = data?.shorts ?? [];
  if (shorts.length === 0) {
    return <EmptyState text="No open short option positions." />;
  }
  const snapshotAge = data?.as_of ? relativeAge(data.as_of) : "";

  return (
    <div className="space-y-2">
      {snapshotAge && (
        <p className="text-xs text-muted">Snapshot {snapshotAge} ago</p>
      )}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="py-2 font-medium">Position</th>
            <th className="py-2 font-medium">DTE</th>
            <th className="py-2 font-medium">Contracts</th>
            <th className="py-2 font-medium">Mark</th>
            <th className="py-2 font-medium">uPnL</th>
            <th className="py-2 font-medium">Delta</th>
            <th className="py-2 font-medium">Alerts</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {shorts.map((s) => (
            <tr key={s.position_symbol}>
              <td className="py-2">
                <div className="font-mono text-xs text-content">
                  {s.underlying} {s.strike.toFixed(2)} {s.right}
                </div>
                <div className="text-xs text-muted">{s.position_symbol}</div>
              </td>
              <td className="py-2 tabular text-content">
                {s.dte != null ? s.dte : UNKNOWN}
              </td>
              <td className="py-2 tabular text-content">{s.contracts}</td>
              <td className="py-2 tabular">
                {s.mark != null ? `$${s.mark.toFixed(2)}` : UNKNOWN}
              </td>
              <td className="py-2 tabular">
                {s.unrealized_pnl != null
                  ? `$${s.unrealized_pnl.toFixed(0)}`
                  : UNKNOWN}
              </td>
              <td className="py-2 tabular text-xs">
                {s.delta != null ? (
                  <span className="text-content">
                    {s.delta.value != null ? s.delta.value.toFixed(2) : UNKNOWN}
                    <span className="ml-1 text-muted">{s.delta.source}</span>
                  </span>
                ) : (
                  UNKNOWN
                )}
              </td>
              <td className="py-2 text-xs text-muted">
                {s.alerts.length > 0
                  ? s.alerts.map((a) => a.detail).join(" - ")
                  : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}