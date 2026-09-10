"use client";

import { useState } from "react";
import { CampaignsPanel } from "./CampaignsPanel";
import { PositionsPanel } from "./PositionsPanel";
import { SummaryPanel } from "./SummaryPanel";

type Tab = "positions" | "campaigns" | "calendar";

const TABS: { key: Tab; label: string }[] = [
  { key: "positions", label: "Positions" },
  { key: "campaigns", label: "Campaigns" },
  { key: "calendar", label: "Calendar" },
];

/**
 * The portfolio page frame. `SummaryPanel` mounts once, above the tab bar, and
 * stays mounted across tab changes - the tabs only swap which panel renders
 * below it, so switching tabs never remounts (and never refetches) the summary
 * query. Matches how `/options` does tabs (ControlsStrip above, tab bar below),
 * so the two consoles feel like one product.
 *
 * Positions/Campaigns/Calendar are Tasks 3.3-3.5. Since Task 3.3, the Positions
 * tab mounts the real `PositionsPanel` (self-fetching, same convention as
 * `SummaryPanel`); since Task 3.4, the Campaigns tab mounts the real
 * `CampaignsPanel`. Calendar (3.5) still renders placeholder text.
 */
export function PortfolioShell() {
  const [tab, setTab] = useState<Tab>("positions");

  return (
    <div className="px-8 py-6">
      <header className="mb-6">
        <h1 className="font-mono text-2xl text-content">Portfolio</h1>
        <p className="mt-1 text-sm text-muted">
          Positions, campaigns and the expiry calendar. Read-only.
        </p>
      </header>

      <section className="mb-6">
        <SummaryPanel />
      </section>

      <nav className="mb-6 flex gap-1 border-b border-border" aria-label="Portfolio sections">
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

      {tab === "positions" && <PositionsPanel />}
      {tab === "campaigns" && <CampaignsPanel />}
      {tab === "calendar" && (
        <p className="text-sm text-muted">Calendar - coming in Task 3.5.</p>
      )}
    </div>
  );
}
