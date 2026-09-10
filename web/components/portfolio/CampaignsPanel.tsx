"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { EmptyState } from "@/components/options/EmptyState";
import { CampaignThread } from "./CampaignThread";
import type { CampaignsResponse } from "./types";

type StatusFilter = "" | "open" | "closed";

/**
 * Campaign threads - the wheel history, one thread per symbol. Self-fetches
 * `GET /portfolio/campaigns` and holds its own status/symbol filter state;
 * both flow into the fetch URL AND the query key, so a filter change is a
 * real refetch against the backend's own `status`/`symbol` query params
 * (`src/api/routers/portfolio.py::portfolio_campaigns`), never a client-side
 * `.filter()` over an already-fetched list - matching `AssessedBrowser`'s
 * stage/symbol filter pattern.
 *
 * No `FreshnessLabel`/`DegradedNotice` here, unlike `SummaryPanel`/
 * `PositionsPanel`: `CampaignsResponse` carries only `{ as_of, campaigns }`.
 * Campaigns come from a live SQL read (`src/storage/campaigns.py::
 * load_campaigns()`), not the portfolio-snapshot freshness spine those two
 * panels read from - there is nothing for either to bind to.
 */
export function CampaignsPanel() {
  const [status, setStatus] = useState<StatusFilter>("");
  const [symbol, setSymbol] = useState("");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["portfolio", "campaigns", status, symbol],
    queryFn: () => {
      const params = new URLSearchParams();
      if (status) params.set("status", status);
      if (symbol.trim()) params.set("symbol", symbol.trim().toUpperCase());
      const qs = params.toString();
      return apiFetch<CampaignsResponse>(`/portfolio/campaigns${qs ? `?${qs}` : ""}`);
    },
    placeholderData: (prev) => prev,
    // Design spec §9.4 / matches SummaryPanel and every other self-fetching
    // panel's 30s poll - the freshness label must not freeze at mount.
    refetchInterval: 30_000,
  });

  if (isError) {
    return <p className="text-sm text-muted">Could not load campaigns.</p>;
  }
  if (isLoading || !data) {
    return <p className="text-sm text-muted">Loading campaigns</p>;
  }

  return (
    <div className="space-y-4" data-testid="campaigns-panel">
      <Filters status={status} setStatus={setStatus} symbol={symbol} setSymbol={setSymbol} />
      {data.campaigns.length === 0 ? (
        <EmptyState text="No campaigns match the current filters." />
      ) : (
        <div className="space-y-3">
          {data.campaigns.map((c) => (
            <CampaignThread campaign={c} key={c.campaign_id} />
          ))}
        </div>
      )}
    </div>
  );
}

function Filters({
  status,
  setStatus,
  symbol,
  setSymbol,
}: {
  status: StatusFilter;
  setStatus: (s: StatusFilter) => void;
  symbol: string;
  setSymbol: (s: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label htmlFor="campaign-status-filter" className="text-xs text-muted">
        Status
      </label>
      <select
        id="campaign-status-filter"
        value={status}
        onChange={(e) => setStatus(e.target.value as StatusFilter)}
        className="rounded border border-border bg-surface px-2 py-1 text-xs text-content"
      >
        <option value="">all</option>
        <option value="open">open</option>
        <option value="closed">closed</option>
      </select>
      <label htmlFor="campaign-symbol-filter" className="text-xs text-muted">
        Symbol
      </label>
      <input
        id="campaign-symbol-filter"
        type="text"
        value={symbol}
        onChange={(e) => setSymbol(e.target.value)}
        placeholder="filter"
        className="w-24 rounded border border-border bg-surface px-2 py-1 text-xs text-content"
      />
    </div>
  );
}
