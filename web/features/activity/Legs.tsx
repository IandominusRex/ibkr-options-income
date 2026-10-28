"use client";

import { useQuery } from "@tanstack/react-query";
import { LedgerFilters } from "@/components/pnl/LedgerFilters";
import { LedgerTable } from "@/components/pnl/LedgerTable";
import type { LedgerResponseData } from "@/components/pnl/types";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";

/**
 * The one row of filters. They narrow the totals, the curve and the legs under them (the page's
 * rule: one composed query string, so a total cannot disagree with the rows). A filter goes to the
 * API, never a client-side narrowing. `formKey` remounts the form when a leg the totals name sets
 * the symbol from outside, instead of syncing the inputs in an effect.
 */
export function LegsFilters({
  filters,
  formKey,
  onFilters,
}: {
  filters: Record<string, string>;
  formKey: number;
  onFilters: (next: Record<string, string>) => void;
}) {
  return (
    <section aria-label="Filters" className="grid gap-2">
      <LedgerFilters key={formKey} filters={filters} onChange={onFilters} />
      <p className="text-[0.8125rem] text-muted">These filters apply to the totals, the curve and the legs below.</p>
    </section>
  );
}

/** Every leg the system opened and closed, in campaign threads, and the CSV export of the same rows. */
export function LegsCard({ qsString }: { qsString: string }) {
  const { data, isError } = useQuery({
    queryKey: ["pnl", "ledger", qsString],
    queryFn: () => apiFetch<LedgerResponseData>(`/pnl/ledger?${qsString}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  return (
    <Card aria-labelledby="legs-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="legs-title" className="text-[1.0625rem] font-bold">
          Legs
        </h2>
        <a
          href={`/api/pnl/ledger.csv?${qsString}`}
          data-testid="ledger-export-link"
          className="inline-flex min-h-11 items-center text-[0.8125rem] font-semibold underline underline-offset-2 md:min-h-8"
        >
          Export CSV
        </a>
      </div>
      <div className="mt-3">
        {isError && !data ? (
          <div className="text-sm text-muted">
            <p>Could not load the ledger.</p>
            <p className="mt-1 text-[0.8125rem]">It tries again every 30 seconds.</p>
          </div>
        ) : !data ? (
          <div role="status" aria-busy="true" aria-label="Loading the ledger" className="h-24 rounded-xl bg-sunk" />
        ) : (
          <LedgerTable data={data} />
        )}
      </div>
    </Card>
  );
}
