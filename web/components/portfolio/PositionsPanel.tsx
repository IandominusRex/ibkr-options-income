"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { EmptyState } from "@/components/options/EmptyState";
import { PositionGroup } from "./PositionGroup";
import type { PositionsResponse } from "./types";

/**
 * Every open position, grouped by underlying - the Positions tab of the
 * portfolio console. Self-fetches `GET /portfolio/positions` and reads its
 * own `source`/`degraded` from that response, matching `SummaryPanel`'s
 * convention rather than inheriting a page-level assumption.
 *
 * An empty `groups` array is ambiguous on its own - the account could hold
 * nothing, or no snapshot has been captured at all - so `source` disambiguates
 * it into two distinct sentences (`source: "none"` vs everything else), both
 * wrapped in `role="status"` so a test (and a screen reader) can read the
 * distinction without depending on styling.
 */
export function PositionsPanel() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["portfolio", "positions"],
    queryFn: () => apiFetch<PositionsResponse>("/portfolio/positions"),
    placeholderData: (prev) => prev,
  });

  if (isError) {
    return <p className="text-sm text-muted">Could not load positions.</p>;
  }
  if (isLoading || !data) {
    return <p className="text-sm text-muted">Loading positions</p>;
  }

  if (data.groups.length === 0) {
    const text =
      data.source === "none"
        ? "No portfolio snapshot has been captured yet."
        : "No open positions.";
    return (
      <div role="status" data-testid="positions-panel">
        <EmptyState text={text} />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="positions-panel">
      {data.groups.map((group) => (
        <PositionGroup group={group} key={group.underlying} />
      ))}
    </div>
  );
}
