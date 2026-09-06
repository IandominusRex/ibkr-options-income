"use client";

import { useState } from "react";
import { ApprovalsList } from "@/components/options/ApprovalsList";
import { ControlsStrip } from "@/components/options/ControlsStrip";
import { AssessedBrowser } from "@/components/options/AssessedBrowser";
import { OrdersTable } from "@/components/options/OrdersTable";
import { FillsTable } from "@/components/options/FillsTable";
import { ShortsTable } from "@/components/options/ShortsTable";

type Tab = "approvals" | "assessed" | "orders" | "fills" | "shorts";

export default function OptionsPage() {
  const [tab, setTab] = useState<Tab>("approvals");

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

      {tab === "approvals" && <ApprovalsList />}
      {tab === "assessed" && <AssessedBrowser />}
      {tab === "orders" && <OrdersTable />}
      {tab === "fills" && <FillsTable />}
      {tab === "shorts" && <ShortsTable />}
    </div>
  );
}

const TABS: { key: Tab; label: string }[] = [
  { key: "approvals", label: "Approvals" },
  { key: "assessed", label: "Assessed" },
  { key: "orders", label: "Orders" },
  { key: "fills", label: "Fills" },
  { key: "shorts", label: "Shorts" },
];