"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { EquityChart } from "./EquityChart";
import { LedgerFilters } from "./LedgerFilters";
import { LedgerTable } from "./LedgerTable";
import { SummaryPanel } from "./SummaryPanel";
import { SystemPanel } from "./SystemPanel";
import type { EquityResponse, LedgerResponseData, PnlLegData, SystemPerformanceResponse } from "./types";

/**
 * The /pnl page frame: `SummaryPanel` mounts once, above the tab bar, and
 * stays mounted across tab changes (`PortfolioShell`'s convention — switching
 * tabs never remounts or refetches the summary query). The tab bar swaps
 * which panel renders below it: Ledger (every trade the system has opened
 * and closed, so it is the default tab), the equity curve, or System (P3-P4
 * M6 Task 6.2) — the score-vs-outcome report and verdict agreement, the one
 * surface reading behind the src/claude/eval/ fence.
 *
 * The shell owns the filter state and composes it into ONE query string that
 * drives the ledger fetch, the summary fetch, the equity fetch, AND the CSV
 * export href — the export must carry the same filters the table renders,
 * and a second composition would let them drift. `book` starts as "all":
 * the ledger may list both, and the summary renders its own book-choice UI
 * when the backend refuses a mixed total (`422 mixed_book`), so the shell
 * never has to guess the operator's book for it. The System tab's since/until
 * window is a separate, independent piece of state — `GET /pnl/system` windows
 * by outcome_date, a different axis than the ledger/equity/summary filters.
 */
type Tab = "ledger" | "equity" | "system";

const TABS: { key: Tab; label: string }[] = [
  { key: "ledger", label: "Ledger" },
  { key: "equity", label: "Equity curve" },
  { key: "system", label: "System" },
];

export function PnlShell() {
  const [tab, setTab] = useState<Tab>("ledger");
  const [filters, setFilters] = useState<Record<string, string>>({});
  // `book` lives inside `filters`, not a second `useState` — it used to be a
  // separate state that `qs.set("book", book)` forced into every query
  // string, silently overwriting whatever `LedgerFilters`'s own Book dropdown
  // had just emitted into `filters.book`. That regression made the Ledger
  // tab's Book filter a no-op: the dropdown showed "paper", the request (and
  // the filter echo LedgerTable renders back) always said "all". One field,
  // read here with a default, keeps SummaryPanel's book-choice buttons (the
  // 422 mixed_book case) and the ledger's own dropdown agreeing by
  // construction — there is nothing left for them to disagree about.
  const book = filters.book || "all";
  function setBook(next: string) {
    setFilters((prev) => ({ ...prev, book: next }));
  }

  // Bumped only by viewLegInLedger, to force <LedgerFilters/> to remount with
  // the new symbol as its seed value — see that component's docstring for why
  // a remount, not a live-sync effect.
  const [filterFormKey, setFilterFormKey] = useState(0);

  // The summary's best/worst legs "link to their legs in the ledger" (Task
  // 5.6) by switching to the ledger tab and filtering to that leg's symbol —
  // the ledger has no per-candidate filter, so the symbol is the closest
  // real cross-reference the API exposes.
  function viewLegInLedger(leg: PnlLegData) {
    setTab("ledger");
    setFilters((prev) => ({ ...prev, symbol: leg.underlying }));
    setFilterFormKey((k) => k + 1);
  }

  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== "" && v != null)),
  );
  if (!qs.has("book")) qs.set("book", "all");
  const qsString = qs.toString();

  const ledger = useQuery({
    queryKey: ["pnl", "ledger", qsString],
    queryFn: () => apiFetch<LedgerResponseData>(`/pnl/ledger?${qsString}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  const equity = useQuery({
    queryKey: ["pnl", "equity", qsString],
    queryFn: () => apiFetch<EquityResponse>(`/pnl/equity?${qsString}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  const [systemWindow, setSystemWindow] = useState<{ since: string; until: string }>({
    since: "",
    until: "",
  });
  const systemQs = new URLSearchParams();
  if (systemWindow.since) systemQs.set("since", systemWindow.since);
  if (systemWindow.until) systemQs.set("until", systemWindow.until);

  const system = useQuery({
    queryKey: ["pnl", "system", systemWindow.since, systemWindow.until],
    queryFn: () => apiFetch<SystemPerformanceResponse>(`/pnl/system?${systemQs.toString()}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  return (
    <div className="px-8 py-6">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-mono text-2xl text-content">P&amp;L</h1>
          <p className="mt-1 text-sm text-muted">
            Every trade the system has opened and closed, what it earned, and the
            equity curve. Read-only; the CSV export carries the same filters.
          </p>
        </div>
        <a
          href={`/api/pnl/ledger.csv?${qsString}`}
          className="rounded border border-border bg-surface px-3 py-1.5 text-xs text-content hover:bg-elevated"
          data-testid="ledger-export-link"
        >
          Export CSV
        </a>
      </header>

      <section className="mb-6" data-testid="pnl-summary-section">
        <SummaryPanel
          book={book}
          qsString={qsString}
          onBookChange={setBook}
          onSelectLeg={viewLegInLedger}
        />
      </section>

      <nav className="mb-4 flex gap-1 border-b border-border" aria-label="P&L sections">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={
              "border-b-2 px-3 py-2 text-sm transition-colors " +
              (tab === t.key
                ? "border-focus text-content"
                : "border-transparent text-muted hover:text-content")
            }
            aria-current={tab === t.key ? "page" : undefined}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "ledger" && (
        <section className="space-y-4">
          <LedgerFilters key={filterFormKey} filters={filters} onChange={setFilters} />
          {ledger.isLoading ? (
            <p className="text-sm text-muted">Loading the ledger</p>
          ) : ledger.isError ? (
            <p className="text-sm text-muted">Could not load the ledger.</p>
          ) : ledger.data ? (
            <LedgerTable data={ledger.data} />
          ) : null}
        </section>
      )}

      {tab === "equity" && (
        <section data-testid="pnl-equity-section">
          {equity.isLoading ? (
            <p className="text-sm text-muted">Loading the equity curve</p>
          ) : equity.isError ? (
            <p className="text-sm text-muted">Could not load the equity curve.</p>
          ) : (
            <EquityChart curve={equity.data?.curve ?? { points: [], gaps: [], starts_at: null }} />
          )}
        </section>
      )}

      {tab === "system" && (
        <section data-testid="pnl-system-section">
          {system.isLoading ? (
            <p className="text-sm text-muted">Loading the system performance report</p>
          ) : system.isError ? (
            <p className="text-sm text-muted">Could not load the system performance report.</p>
          ) : system.data ? (
            <SystemPanel
              data={system.data}
              since={systemWindow.since}
              until={systemWindow.until}
              onSinceChange={(v) => setSystemWindow((w) => ({ ...w, since: v }))}
              onUntilChange={(v) => setSystemWindow((w) => ({ ...w, until: v }))}
            />
          ) : null}
        </section>
      )}
    </div>
  );
}