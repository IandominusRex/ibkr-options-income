"use client";

import { useQuery } from "@tanstack/react-query";
import { StatusWord } from "@/components/ui/StatusWord";
import { whenET } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { lastWindow, spreadOrderTitle } from "./fills";
import type { SpreadOrdersResponse } from "./types";

/**
 * The credit-spreads book's filled orders (the book records filled orders only). An unreadable
 * file is "unavailable", never "none": unknown is not empty.
 */
export function SpreadFills({ days }: { days: number }) {
  const { data, isError } = useQuery({
    queryKey: ["spreads", "orders", days],
    queryFn: () => apiFetch<SpreadOrdersResponse>(`/spreads/orders?days=${days}&limit=200`),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });

  if (isError && !data) return <p className="text-sm text-muted">Credit spread fills are unavailable right now.</p>;
  if (!data) {
    return <div role="status" aria-busy="true" aria-label="Loading credit spread fills" className="h-16 rounded-xl bg-sunk" />;
  }
  if (!data.available) return <p className="text-sm text-muted">Credit spread fills are unavailable right now.</p>;
  // The generated type makes a defaulted list optional.
  const orders = data.orders ?? [];
  if (orders.length === 0) {
    return <p className="text-sm text-muted">No credit spread orders in {lastWindow(days)}.</p>;
  }
  return (
    <ul>
      {orders.map((o, i) => (
        <li key={`${o.spread_id}:${o.kind}:${i}`} className="border-t border-border py-[11px] first:border-t-0">
          <div className="flex items-start justify-between gap-3 text-sm">
            <div className="min-w-0">
              <span className="font-bold">{spreadOrderTitle(o, data.underlying)}</span>
              <span className="ml-1.5 align-[1px]">
                <StatusWord>{o.kind === "open" ? "Opened" : "Closed"}</StatusWord>
              </span>
              {o.mode && (
                <span className="ml-1.5 align-[1px]">
                  <StatusWord>{o.mode}</StatusWord>
                </span>
              )}
              <div className="text-[0.8125rem] text-muted">{whenET(o.created_at)}</div>
              <div className="tabular font-mono text-xs text-muted">
                {o.filled_qty} {o.filled_qty === 1 ? "contract" : "contracts"} · commission ${o.commission.toFixed(2)}
              </div>
              {o.reason && <p className="text-[0.8125rem] text-muted">Reason: {o.reason.replace(/_/g, " ")}</p>}
            </div>
            <div className="tabular text-right font-mono font-semibold">
              {o.price === null ? <span className="hatch text-unknown">{UNKNOWN}</span> : `$${o.price.toFixed(2)}`}
              <div className="font-sans text-[0.8125rem] font-normal text-muted">a share</div>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
