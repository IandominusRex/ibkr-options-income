"use client";

import Link from "next/link";
import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { ApprovalDetailCard } from "@/components/options/ApprovalDetail";
import type { ApprovalDetail } from "@/components/options/types";

export default function ApprovalDetailPage({
  params,
}: {
  params: Promise<{ approvalId: string }>;
}) {
  const { approvalId } = use(params);
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["options", "approval", approvalId],
    queryFn: () =>
      apiFetch<ApprovalDetail>(`/options/approvals/${approvalId}`),
    retry: 1,
  });

  if (isLoading) {
    return (
      <div className="px-8 py-6">
        <p className="text-sm text-muted">Loading approval</p>
      </div>
    );
  }
  if (isError || !data) {
    // A 404 renders a real not-found state with a link back to the list.
    return (
      <div className="px-8 py-6 space-y-4">
        <h1 className="font-mono text-2xl text-content">Not found</h1>
        <p className="text-sm text-muted">
          This approval does not exist or has been pruned.
        </p>
        <Link href="/options" className="text-xs text-muted hover:text-content">
          Back to approvals
        </Link>
      </div>
    );
  }
  return (
    <div className="px-8 py-6">
      <ApprovalDetailCard detail={data} />
    </div>
  );
}