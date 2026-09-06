"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { UNKNOWN, relativeAge } from "@/lib/format";
import { EmptyState } from "./EmptyState";
import type { FillListResponse } from "./types";

export function FillsTable() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "fills"],
    queryFn: () => apiFetch<FillListResponse>("/options/fills?days=7"),
    placeholderData: (prev) => prev,
  });

  if (isLoading) return <p className="text-sm text-muted">Loading fills</p>;
  if (isError) return <p className="text-sm text-muted">Could not load fills</p>;
  const fills = data?.fills ?? [];
  if (fills.length === 0) {
    return <EmptyState text="No fills in the last 7 days." />;
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-muted">
          <th className="py-2 font-medium">When</th>
          <th className="py-2 font-medium">Underlying</th>
          <th className="py-2 font-medium">Action</th>
          <th className="py-2 font-medium">Qty</th>
          <th className="py-2 font-medium">Price</th>
          <th className="py-2 font-medium">Mode</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {fills.map((f) => (
          <tr key={f.id}>
            <td className="py-2 text-xs text-muted">{relativeAge(f.filled_at)}</td>
            <td className="py-2 font-mono text-content">{f.candidate_id}</td>
            <td className="py-2 text-content">{f.action}</td>
            <td className="py-2 tabular text-content">{f.filled_qty.toFixed(0)}</td>
            <td className="py-2 tabular text-content">${f.avg_price.toFixed(2)}</td>
            <td className="py-2 text-xs text-muted">{f.is_live ? "live" : "paper"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}