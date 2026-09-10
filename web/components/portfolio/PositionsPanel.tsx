"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { EmptyState } from "@/components/options/EmptyState";
import { FreshnessLabel } from "./FreshnessLabel";
import { PositionGroup } from "./PositionGroup";
import type { PositionsResponse } from "./types";

// Mirrors SummaryPanel.tsx's FRESH_FOR_MINUTES: src/api/routers/portfolio.py:67-69's
// `_fresh_for()` returns 2 * the configured portfolio_snapshot_interval_minutes
// (15 by default) = 30 minutes. Kept as a literal constant here too (not imported
// from SummaryPanel) for the same reason SummaryPanel documents its own copy: the
// web layer has no config access, so if the backend interval ever changes, both
// copies need a matching edit.
const FRESH_FOR_MINUTES = 30;

/**
 * Every open position, grouped by underlying - the Positions tab of the
 * portfolio console. Self-fetches `GET /portfolio/positions` and reads its
 * own `source`/`degraded` from that response, matching `SummaryPanel`'s
 * convention rather than inheriting a page-level assumption.
 *
 * `data.as_of` renders through `FreshnessLabel`, unconditionally, above the
 * content - mirroring `SummaryPanel.tsx:48-61` exactly (computed once, shown
 * in both the empty and non-empty branches). This matters here specifically:
 * `read_portfolio`'s `eod` fallback rung can return real, non-empty `groups`
 * with `degraded=True` and a capture time up to a day old, and without a
 * visible freshness label that renders pixel-identical to a live `monitor`
 * read - the only other place `as_of` reaches is `Money`'s invisible hover
 * tooltip on each figure, not a visible page-level indicator.
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

  const freshness = <FreshnessLabel asOf={data.as_of} freshForMinutes={FRESH_FOR_MINUTES} />;

  if (data.groups.length === 0) {
    const text =
      data.source === "none"
        ? "No portfolio snapshot has been captured yet."
        : "No open positions.";
    return (
      <div role="status" data-testid="positions-panel" className="space-y-3">
        {freshness}
        <EmptyState text={text} />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="positions-panel">
      {freshness}
      {data.groups.map((group) => (
        <PositionGroup group={group} key={group.underlying} />
      ))}
    </div>
  );
}
