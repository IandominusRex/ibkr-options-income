"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { ApprovalCard } from "./ApprovalCard";
import { EmptyState } from "./EmptyState";
import type { ApprovalListResponse, ControlsResponse } from "./types";

export function ApprovalsList() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "approvals"],
    queryFn: () => apiFetch<ApprovalListResponse>("/options/approvals?status=pending"),
    placeholderData: (prev) => prev,
  });

  // The drain's health drives the receipt's "stalled" state (spec §9.2 rule 3):
  // a queued command whose drain is dead must say so in words.
  const controls = useQuery({
    queryKey: ["options", "controls"],
    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  if (isLoading) {
    return <p className="text-sm text-muted">Loading approvals</p>;
  }
  if (isError) {
    return <p className="text-sm text-muted">Could not load approvals</p>;
  }
  const approvals = data?.approvals ?? [];
  if (approvals.length === 0) {
    return <EmptyState text="No pending approvals." />;
  }
  return (
    <ul className="space-y-3">
      {approvals.map((a) => (
        <li key={a.id}>
          {/* `drain_healthy` defaults to `true` while controls are loading so a
           * receipt never flashes `stalled` ("the trading service is not
           * draining commands") on the basis of "no evidence yet" — only on
           * actual evidence the drain is dead. The spec's `stalled` state is
           * for a dead drain, not an unloaded one. */}
          <ApprovalCard approval={a} drainHealthy={controls.data?.drain_healthy ?? true} />
        </li>
      ))}
    </ul>
  );
}