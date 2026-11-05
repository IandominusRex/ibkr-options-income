"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import type { ApprovalListResponse, ApprovalSummary } from "@/components/options/types";
import { apiFetch } from "@/lib/api";
import { type StrategyFilter, kindOf, matchesFilter } from "@/lib/strategy";
import { ProposalCard } from "./ProposalCard";
import { ReviewSheet } from "./ReviewSheet";

export function usePendingApprovals(strategy: StrategyFilter) {
  // Same key as <ApprovalsList status="pending"/>: one request, and DecideControls'
  // invalidation of ["options", "approvals"] refreshes this too.
  const q = useQuery({
    queryKey: ["options", "approvals", "pending"],
    queryFn: () => apiFetch<ApprovalListResponse>("/options/approvals?status=pending"),
    refetchInterval: 30_000,
  });
  const visible = (q.data?.approvals ?? []).filter(
    (a) => a.status === "pending" && matchesFilter(kindOf(a.strategy, a.right), strategy),
  );
  return { ...q, visible };
}

export function NeedsYou({ strategy }: { strategy: StrategyFilter }) {
  const { data, isError, visible } = usePendingApprovals(strategy);
  const [reviewing, setReviewing] = useState<ApprovalSummary | null>(null);

  let body: ReactNode;
  if (strategy === "spread") {
    body = <p className="text-sm text-muted">Credit spreads trade on their own in paper. Nothing here needs you.</p>;
  } else if (strategy === "value") {
    // The value book's proposals are not approvals; they are decided from its own card.
    body = <p className="text-sm text-muted">Value proposals wait in the Value book card.</p>;
  } else if (isError && !data) {
    body = <p className="text-sm text-muted">Proposals unavailable right now.</p>;
  } else if (!data) {
    body = <div className="h-24 rounded-[18px] bg-surface" role="status" aria-busy="true" aria-label="Loading proposals" />;
  } else if (visible.length === 0) {
    body = <p className="text-sm text-muted">Nothing needs you right now.</p>;
  } else {
    body = (
      <div className="grid gap-3">
        {visible.map((a) => (
          <ProposalCard key={a.id} approval={a} onReview={setReviewing} />
        ))}
      </div>
    );
  }

  return (
    <section aria-labelledby="needs-you-title">
      <h2 id="needs-you-title" className="mb-2.5 text-[0.8125rem] font-semibold text-muted">
        Needs you{strategy !== "spread" && strategy !== "value" && data ? ` · ${visible.length} proposal${visible.length === 1 ? "" : "s"}` : ""}
      </h2>
      {body}
      <ReviewSheet approval={reviewing} open={reviewing !== null} onClose={() => setReviewing(null)} />
    </section>
  );
}
