"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { relativeAge } from "@/lib/format";
import { EmptyState } from "./EmptyState";
import { ShortsRow } from "./ShortsRow";
import type { ControlsResponse, ShortListResponse } from "./types";

export function ShortsTable() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "shorts"],
    queryFn: () => apiFetch<ShortListResponse>("/options/shorts"),
    placeholderData: (prev) => prev,
  });

  // The drain's health drives the roll receipt's "stalled" state (spec §9.2 rule 3):
  // a queued roll_request whose drain is dead must say so in words. Same pattern as
  // ApprovalsList/AssessedBrowser. Defaults to `true` while loading so a receipt
  // never flashes `stalled` on "no evidence yet".
  const controls = useQuery({
    queryKey: ["options", "controls"],
    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  if (isLoading) return <p className="text-sm text-muted">Loading shorts</p>;
  if (isError) return <p className="text-sm text-muted">Could not load shorts</p>;
  const shorts = data?.shorts ?? [];
  if (shorts.length === 0) {
    return <EmptyState text="No open short option positions." />;
  }
  const snapshotAge = data?.as_of ? relativeAge(data.as_of) : "";
  const drainHealthy = controls.data?.drain_healthy ?? true;

  return (
    <div className="space-y-2">
      {snapshotAge && (
        <p className="text-xs text-muted">Snapshot {snapshotAge} ago</p>
      )}
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted">
            <th className="py-2 font-medium">Position</th>
            <th className="py-2 font-medium">DTE</th>
            <th className="py-2 font-medium">Contracts</th>
            <th className="py-2 font-medium">Mark</th>
            <th className="py-2 font-medium">uPnL</th>
            <th className="py-2 font-medium">Delta</th>
            <th className="py-2 font-medium">Alerts</th>
            <th className="py-2 font-medium">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {shorts.map((s) => (
            <ShortsRow key={s.position_symbol} short={s} drainHealthy={drainHealthy} />
          ))}
        </tbody>
      </table>
    </div>
  );
}