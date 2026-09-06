"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { ApprovalCard } from "./ApprovalCard";
import { EmptyState } from "./EmptyState";
import type { ApprovalListResponse } from "./types";

export function ApprovalsList() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "approvals"],
    queryFn: () => apiFetch<ApprovalListResponse>("/options/approvals?status=pending"),
    placeholderData: (prev) => prev,
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
          <ApprovalCard approval={a} />
        </li>
      ))}
    </ul>
  );
}