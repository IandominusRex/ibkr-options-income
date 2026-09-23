"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { EmptyState } from "./EmptyState";
import type { OrderListResponse } from "./types";

type Filter = "working" | "all" | "rejected";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "working", label: "Working" },
  { key: "all", label: "All" },
  { key: "rejected", label: "Rejected" },
];

const EMPTY_TEXT: Record<Filter, string> = {
  working: "No working orders.",
  all: "No orders.",
  rejected: "No rejected orders.",
};

export function OrdersTable() {
  const [filter, setFilter] = useState<Filter>("working");
  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "orders", filter],
    queryFn: () => apiFetch<OrderListResponse>(`/options/orders?state=${filter}`),
    placeholderData: (prev) => prev,
  });

  const orders = data?.orders ?? [];

  return (
    <div>
      <div className="mb-3 flex gap-1" role="group" aria-label="Filter orders">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            onClick={() => setFilter(f.key)}
            aria-pressed={filter === f.key}
            className={
              "rounded-sm border px-2 py-1 text-xs transition-colors " +
              (filter === f.key
                ? "border-focus text-content"
                : "border-border text-muted hover:text-content")
            }
          >
            {f.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <p className="text-sm text-muted">Loading orders</p>
      ) : isError ? (
        <p className="text-sm text-muted">Could not load orders</p>
      ) : orders.length === 0 ? (
        <EmptyState text={EMPTY_TEXT[filter]} />
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="py-2 font-medium">Underlying</th>
              <th className="py-2 font-medium">Contract</th>
              <th className="py-2 font-medium">State</th>
              <th className="py-2 font-medium">Limit</th>
              <th className="py-2 font-medium">Filled</th>
              <th className="py-2 font-medium">Avg fill</th>
              <th className="py-2 font-medium">Mode</th>
              <th className="py-2 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {orders.map((o) => (
              <tr key={o.id}>
                <td className="py-2 font-mono text-content">{o.underlying}</td>
                <td className="py-2 tabular text-content">
                  {o.strike.toFixed(2)} {o.strategy}
                </td>
                <td className="py-2">
                  <StateBadge state={o.state} />
                </td>
                <td className="py-2 tabular">
                  {o.limit_price != null ? `$${o.limit_price.toFixed(2)}` : UNKNOWN}
                </td>
                <td className="py-2 tabular text-content">{o.filled_qty.toFixed(0)}</td>
                <td className="py-2 tabular">
                  {o.avg_fill_price != null ? `$${o.avg_fill_price.toFixed(2)}` : UNKNOWN}
                </td>
                <td className="py-2 text-xs text-muted">{o.is_live ? "live" : "paper"}</td>
                <td className="py-2 text-xs text-muted">{o.detail ?? UNKNOWN}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function StateBadge({ state }: { state: string }) {
  // State is never communicated by colour alone: a label plus a distinct fill.
  const LABEL: Record<string, string> = {
    queued: "Queued",
    submitted: "Submitted",
    filled: "Filled",
    partial: "Partial",
    cancelled: "Cancelled",
    rejected: "Rejected",
  };
  const cls =
    state === "filled"
      ? "bg-gain text-background"
      : state === "rejected" || state === "cancelled"
        ? "border border-loss text-loss"
        : "bg-elevated text-content";
  return (
    <span className={`inline-block rounded-sm px-2 py-0.5 text-xs ${cls}`}>
      {LABEL[state] ?? state}
    </span>
  );
}