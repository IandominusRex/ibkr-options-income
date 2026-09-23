"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { ApprovalsList } from "@/components/options/ApprovalsList";
import { ControlsStrip } from "@/components/options/ControlsStrip";
import { TickerPillBar } from "@/components/options/TickerPillBar";
import { AssessedBrowser } from "@/components/options/AssessedBrowser";
import { OrdersTable } from "@/components/options/OrdersTable";
import { FillsTable } from "@/components/options/FillsTable";
import { ShortsTable } from "@/components/options/ShortsTable";
import { loadAllPersistedCommands, type CommandStatus } from "@/lib/commands";
import type { ApprovalListResponse } from "@/components/options/types";

type Tab = "approvals" | "submitted" | "decided" | "assessed" | "orders" | "fills" | "shorts";

export default function OptionsPage() {
  const [tab, setTab] = useState<Tab>("approvals");
  const [symbolFilter, setSymbolFilter] = useState<string | null>(null);
  // Approvals whose Approve command is in flight (or just failed/expired and
  // fell back). Tracked client-side, not server state: the approval's own
  // `status` doesn't leave "pending" until the drain actually processes the
  // command, so this is what lets the card visibly move to "Submitted" the
  // instant the user confirms, instead of lingering in the Approvals list.
  // Keyed by approval id, valued by the command itself (not just a flag) so
  // the freshly-mounted card in the other tab can restore the in-flight
  // receipt via <ApprovalCard initialCommand>, rather than starting blank.
  const [submitted, setSubmitted] = useState<Map<number, CommandStatus>>(new Map());
  const markSubmitted = (id: number, command: CommandStatus) =>
    setSubmitted((prev) => new Map(prev).set(id, command));
  const clearSubmitted = (id: number) =>
    setSubmitted((prev) => {
      const next = new Map(prev);
      next.delete(id);
      return next;
    });

  // Seed `submitted` from localStorage after mount (not a useState lazy
  // initializer — that would run during SSR too, where localStorage doesn't
  // exist, and would also render a different initial tree on the client than
  // the server sent, which React flags as a hydration mismatch). Without
  // this, a page reload while a command was mid-flight would drop the card's
  // tab placement back to Approvals even though <DecideControls/> itself
  // (lib/commands.ts) still remembers and disables it correctly.
  useEffect(() => {
    const persisted = loadAllPersistedCommands();
    if (persisted.size > 0) setSubmitted(persisted);
  }, []);

  // Same queryKey/queryFn <ApprovalsList status="pending"/> uses internally
  // (react-query dedupes — one network request, two subscribers), just so
  // this page also has the raw list to derive <TickerPillBar/>'s pills from.
  const approvalsQuery = useQuery({
    queryKey: ["options", "approvals", "pending"],
    queryFn: () => apiFetch<ApprovalListResponse>("/options/approvals?status=pending"),
    placeholderData: (prev) => prev,
  });
  const visibleApprovals = (approvalsQuery.data?.approvals ?? []).filter(
    (a) => !submitted.has(a.id),
  );

  return (
    <div className="px-8 py-6">
      <header className="mb-6">
        <h1 className="font-mono text-2xl text-content">Options</h1>
        <p className="mt-1 text-sm text-muted">
          Approvals, assessed contracts, orders and open shorts. Read-only.
        </p>
      </header>

      <section className="mb-6">
        <ControlsStrip />
      </section>

      <nav className="mb-6 flex gap-1 border-b border-border" aria-label="Options sections">
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

      {tab === "approvals" && (
        <div className="space-y-8">
          <ApprovalsList
            filter={(a) =>
              !submitted.has(a.id) && (symbolFilter === null || a.underlying === symbolFilter)
            }
            initialCommands={submitted}
            onApprovalSubmitted={markSubmitted}
            onApprovalSettled={clearSubmitted}
          />
          <TickerPillBar
            approvals={visibleApprovals}
            selected={symbolFilter}
            onSelect={setSymbolFilter}
          />
        </div>
      )}
      {tab === "submitted" && (
        <ApprovalsList
          filter={(a) => submitted.has(a.id)}
          emptyText="No approvals submitted yet."
          initialCommands={submitted}
          onApprovalSubmitted={markSubmitted}
          onApprovalSettled={clearSubmitted}
        />
      )}
      {tab === "decided" && (
        <ApprovalsList
          status="all"
          filter={(a) => a.status !== "pending"}
          emptyText="No decided approvals yet."
        />
      )}
      {tab === "assessed" && <AssessedBrowser />}
      {tab === "orders" && <OrdersTable />}
      {tab === "fills" && <FillsTable />}
      {tab === "shorts" && <ShortsTable />}
    </div>
  );
}

const TABS: { key: Tab; label: string }[] = [
  { key: "approvals", label: "Approvals" },
  { key: "submitted", label: "Submitted" },
  { key: "decided", label: "Decided" },
  { key: "assessed", label: "Assessed" },
  { key: "orders", label: "Orders" },
  { key: "fills", label: "Fills" },
  { key: "shorts", label: "Shorts" },
];