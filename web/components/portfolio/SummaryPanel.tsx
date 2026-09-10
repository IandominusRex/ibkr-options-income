"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { EmptyState } from "@/components/options/EmptyState";
import { DegradedNotice } from "./DegradedNotice";
import { FreshnessLabel } from "./FreshnessLabel";
import { Money } from "./Money";
import type { AccountBlock, ExposureBlock, PortfolioSummaryResponse, SourcedFloat } from "./types";

// src/api/routers/portfolio.py:67-69's `_fresh_for()` returns 2 * the configured
// portfolio_snapshot_interval_minutes (15 by default) = 30 minutes: one missed
// capture still reads fresh, two reads stale. Mirrored here as a constant, not
// read from config, because the web layer has no config access (ARCHITECTURE.md's
// web-layer fence) - if the backend interval ever changes, this needs a matching
// edit.
const FRESH_FOR_MINUTES = 30;

const ACCOUNT_FIELDS: { key: keyof Omit<AccountBlock, "as_of">; label: string }[] = [
  { key: "net_liquidation", label: "Net liquidation" },
  { key: "total_cash", label: "Total cash" },
  { key: "buying_power", label: "Buying power" },
  { key: "maintenance_margin", label: "Maintenance margin" },
  { key: "excess_liquidity", label: "Excess liquidity" },
];

/**
 * The portfolio summary: page-level freshness, a degraded-reading notice when the
 * backend names one, the five account values, and the exposure figures. Every
 * other portfolio panel (Tasks 3.3-3.5) reads its own `source`/`degraded`/`note`
 * from its own response rather than inheriting this panel's - this component sets
 * that convention, it does not centralise it.
 */
export function SummaryPanel() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["portfolio", "summary"],
    queryFn: () => apiFetch<PortfolioSummaryResponse>("/portfolio/summary"),
    placeholderData: (prev) => prev,
  });

  if (isError) {
    return <p className="text-sm text-muted">Could not load the portfolio summary.</p>;
  }
  if (isLoading || !data) {
    return <p className="text-sm text-muted">Loading portfolio summary</p>;
  }

  // Design point 3: the freshness label applies to the whole panel, so it is
  // driven by the envelope's own `as_of`, once, above everything else - never
  // reimplied per figure.
  const freshness = <FreshnessLabel asOf={data.as_of} freshForMinutes={FRESH_FOR_MINUTES} />;

  if (data.source === "none") {
    // Design point 1: the empty rung renders one line of text, not zeros - no
    // account figures, no exposure figures, no decorative icon circle.
    return (
      <div className="space-y-3" data-testid="summary-panel">
        {freshness}
        <EmptyState text={data.note ?? "No portfolio snapshot has been captured yet."} />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="summary-panel">
      {freshness}
      {data.degraded && data.note && <DegradedNotice note={data.note} />}
      {data.account && <AccountValues account={data.account} />}
      {data.exposure && <ExposureValues exposure={data.exposure} />}
    </div>
  );
}

function AccountValues({ account }: { account: AccountBlock }) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-5">
      {ACCOUNT_FIELDS.map(({ key, label }) => {
        const field = account[key] as SourcedFloat;
        return (
          <div key={key} className="flex flex-col gap-1">
            <span className="text-xs text-muted">{label}</span>
            <span className="flex items-baseline gap-1">
              {/* Design point 5: every Sourced value renders through Money, carrying
                  its own as_of (drives Money's hover tooltip) - not the block's. */}
              <Money value={field.value} kind="value" asOf={field.as_of} />
              {field.stale && (
                <span className="text-[10px] uppercase tracking-wide text-unknown">stale</span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ExposureValues({ exposure }: { exposure: ExposureBlock }) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      <Stat label="Open positions" value={String(exposure.open_positions)} />
      <Stat label="Open shorts" value={String(exposure.open_shorts)} />
      <Stat label="Open campaigns" value={String(exposure.open_campaigns)} />
      <Stat label="Shorts at assignment risk" value={String(exposure.shorts_at_assignment_risk)} />
      <Stat label="Net delta exposure" value={exposure.net_delta_exposure.toLocaleString()} />
      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted">Cash secured against puts</span>
        <Money value={exposure.cash_secured_against_puts} kind="value" asOf={exposure.as_of} />
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted">Buying power utilisation</span>
        {/* Not a Sourced value and not a dollar figure - a plain percentage, so it
            renders through its own n/a branch rather than being forced through Money. */}
        {exposure.buying_power_utilisation_pct == null ? (
          <span className="tabular hatch text-unknown">n/a</span>
        ) : (
          <span className="tabular text-content">
            {exposure.buying_power_utilisation_pct.toFixed(1)}%
          </span>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      <span className="tabular text-content">{value}</span>
    </div>
  );
}
