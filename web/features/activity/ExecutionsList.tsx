"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusWord } from "@/components/ui/StatusWord";
import { whenET } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { bookWord, executionTitle, lastWindow, sourceWord } from "./fills";
import type { LedgerExecutionsResponse } from "./types";

type BookFilter = "all" | "system" | "spreads" | "manual";
const BOOKS: { value: BookFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "system", label: "System" },
  { value: "spreads", label: "Spreads" },
  { value: "manual", label: "Manual" },
];
const LIMIT = 200;

/**
 * IBKR's own executions, newest first, from the ledger: every book, whether or not the system
 * placed the order. A commission of 0 is said as "none recorded" (the feed cannot tell a free
 * execution, such as an assignment, from one whose commission has not arrived), never as $0.
 */
export function ExecutionsList({ days }: { days: number }) {
  const [book, setBook] = useState<BookFilter>("all");
  const { data, isError } = useQuery({
    queryKey: ["ledger", "executions", days, book],
    queryFn: () =>
      apiFetch<LedgerExecutionsResponse>(
        `/ledger/executions?days=${days}&limit=${LIMIT}${book === "all" ? "" : `&book=${book}`}`,
      ),
    placeholderData: (prev) => prev,
    refetchInterval: 60_000,
  });

  return (
    <div className="grid gap-3">
      <SegmentedControl label="Book" appearance="chips" options={BOOKS} value={book} onChange={setBook} />
      {isError && !data ? (
        <p className="text-sm text-muted">Could not load IBKR&apos;s executions.</p>
      ) : !data ? (
        <div role="status" aria-busy="true" aria-label="Loading IBKR's executions" className="h-24 rounded-xl bg-sunk" />
      ) : data.executions.length === 0 ? (
        <p className="text-sm text-muted">
          No executions at IBKR in {lastWindow(days)}. They arrive through the live feed, the Flex query or a
          statement import.
        </p>
      ) : (
        <ul>
          {data.executions.map((e) => (
            <li key={e.id} className="border-t border-border py-[11px] first:border-t-0">
              <div className="flex items-start justify-between gap-3 text-sm">
                <div className="min-w-0">
                  <span className="font-bold">{executionTitle(e)}</span>
                  <span className="ml-1.5 align-[1px]">
                    <StatusWord>{bookWord(e.book)}</StatusWord>
                  </span>
                  <div className="text-[0.8125rem] text-muted">
                    {whenET(e.trade_time)} · {sourceWord(e.source)}
                  </div>
                  <div className="tabular font-mono text-xs text-muted">
                    commission {e.commission === 0 ? "none recorded" : `$${Math.abs(e.commission).toFixed(2)}`}
                    {e.codes ? ` · codes ${e.codes}` : ""}
                    {e.exec_id ? ` · ${e.exec_id}` : ""}
                  </div>
                </div>
                <div className="tabular text-right font-mono font-semibold">
                  {`$${e.price.toFixed(2)}`}
                  <div className="font-sans text-[0.8125rem] font-normal text-muted">a share</div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {data?.truncated && (
        <p className="text-[0.8125rem] text-muted">
          Showing the latest {data.limit}. Choose a shorter window to see every execution in it.
        </p>
      )}
    </div>
  );
}
