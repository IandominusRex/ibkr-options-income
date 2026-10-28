"use client";

import { useQuery } from "@tanstack/react-query";
import { StatusWord } from "@/components/ui/StatusWord";
import { whenET } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { EmptyState } from "./EmptyState";
import type { FillListResponse, FillSummary } from "./types";

const CAP = 500;
const usd = (v: number) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
const lastWindow = (days: number) => (days === 365 ? "the last year" : `the last ${days} days`);

function title(f: FillSummary): string {
  if (!f.underlying) return "Contract not on record";
  const strike = typeof f.strike === "number" ? usd(f.strike) : "strike n/a";
  const side = f.right === "P" ? "put" : f.right === "C" ? "call" : "option";
  return `${f.underlying} ${strike} ${side}`;
}

/**
 * The system's own fills: what it recorded as filled, with the contract named from the order's
 * frozen snapshot or its candidate. A fill whose order and candidate are both gone says so and
 * keeps its candidate id; a missing commission is n/a, never $0.
 */
export function FillsTable({ days = 7 }: { days?: number } = {}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "fills", days],
    queryFn: () => apiFetch<FillListResponse>(`/options/fills?days=${days}&limit=${CAP}`),
    placeholderData: (prev) => prev,
  });

  if (isLoading) return <p className="text-sm text-muted">Loading fills</p>;
  if (isError) return <p className="text-sm text-muted">Could not load fills</p>;
  const fills = data?.fills ?? [];
  if (fills.length === 0) {
    return <EmptyState text={`No fills in ${lastWindow(days)}.`} />;
  }
  return (
    <div className="grid gap-2">
      <ul>
        {fills.map((f) => (
          <li key={f.id} className="border-t border-border py-[11px] first:border-t-0">
            <div className="flex items-start justify-between gap-3 text-sm">
              <div className="min-w-0">
                <span className="font-bold">{title(f)}</span>
                {!f.underlying && <span className="ml-1.5 font-mono text-xs text-muted">{f.candidate_id}</span>}
                <span className="ml-1.5 align-[1px]">
                  <StatusWord>{f.is_live ? "live" : "paper"}</StatusWord>
                </span>
                <div className="text-[0.8125rem] text-muted">{whenET(f.filled_at)}</div>
                <div className="tabular font-mono text-xs text-muted">
                  <span>commission</span>{" "}
                  {f.commission === null || f.commission === undefined ? (
                    <span className="hatch text-unknown">{UNKNOWN}</span>
                  ) : (
                    `$${Math.abs(f.commission).toFixed(2)}`
                  )}
                </div>
              </div>
              <div className="tabular text-right font-mono font-semibold">
                <span>
                  {f.action} {f.filled_qty.toFixed(0)}
                </span>
                <div>{`$${f.avg_price.toFixed(2)}`}</div>
                <div className="font-sans text-[0.8125rem] font-normal text-muted">a share</div>
              </div>
            </div>
          </li>
        ))}
      </ul>
      {fills.length >= CAP && (
        <p className="text-[0.8125rem] text-muted">
          Showing the latest {CAP} fills. Choose a shorter window to see every fill in it.
        </p>
      )}
    </div>
  );
}
