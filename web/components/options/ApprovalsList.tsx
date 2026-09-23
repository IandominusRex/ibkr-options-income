"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { CommandStatus } from "@/lib/commands";
import { ApprovalCard } from "./ApprovalCard";
import { EmptyState } from "./EmptyState";
import type { ApprovalListResponse, ApprovalSummary, ControlsResponse } from "./types";

export function ApprovalsList({
  status = "pending",
  filter,
  emptyText = "No pending approvals.",
  initialCommands,
  onApprovalSubmitted,
  onApprovalSettled,
}: {
  /** `"pending"` (default) matches the original behaviour exactly; `"all"`
   * fetches every status (including rejected/expired) for the
   * Rejected/Expired tab, which then narrows further via `filter`. */
  status?: "pending" | "all";
  /** When given, only approvals passing this predicate render (M3b: lets the
   * Approvals/Submitted tabs share one query and partition it client-side). */
  filter?: (approval: ApprovalSummary) => boolean;
  emptyText?: string;
  /** Per-approval in-flight command, keyed by approval id (M3b) — passed
   * through to each card so a command survives the card moving between the
   * Approvals and Submitted tabs, which unmounts and remounts it. */
  initialCommands?: Map<number, CommandStatus>;
  /** Fired the moment Approve is confirmed (before the network call even
   * resolves) so a caller can move the card to a "Submitted" view. */
  onApprovalSubmitted?: (id: number, command: CommandStatus) => void;
  /** Fired if the command ends up failed/expired — the approval never left
   * "pending" server-side, so it belongs back in the Approvals view. */
  onApprovalSettled?: (id: number) => void;
} = {}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "approvals", status],
    queryFn: () => apiFetch<ApprovalListResponse>(`/options/approvals?status=${status}`),
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
  const all = data?.approvals ?? [];
  const approvals = filter ? all.filter(filter) : all;
  if (approvals.length === 0) {
    return <EmptyState text={emptyText} />;
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
          <ApprovalCard
            approval={a}
            drainHealthy={controls.data?.drain_healthy ?? true}
            initialCommand={initialCommands?.get(a.id) ?? null}
            onApprovalSubmitted={onApprovalSubmitted}
            onApprovalSettled={onApprovalSettled}
          />
        </li>
      ))}
    </ul>
  );
}