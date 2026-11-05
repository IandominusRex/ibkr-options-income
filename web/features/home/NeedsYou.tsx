"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import type { ApprovalListResponse, ApprovalSummary } from "@/components/options/types";
import { apiFetch } from "@/lib/api";
import { useValueBook, waitingProposals } from "@/components/value/useValueBook";
import { type StrategyFilter, kindOf, matchesFilter } from "@/lib/strategy";
import { ProposalCard } from "./ProposalCard";
import { ReviewSheet } from "./ReviewSheet";
import { ValueWaiting } from "./ValueWaiting";

export function usePendingApprovals(strategy: StrategyFilter) {
  // Same key as the Rail's pending count: one request, and DecideControls'
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
  const valueBook = useValueBook().data;
  const waiting = waitingProposals(valueBook);
  const valueWaiting = waiting?.length ?? 0;
  const showsValue = strategy === "all" || strategy === "value";
  // Unknown is not none: with the value rows shown, "Nothing needs you" is said only once the book is read (an
  // empty list) or is off and never wrote. An errored, still-loading or on-but-unreadable book stays silent
  // here and <ValueWaiting/> speaks alone (whole-branch review fix).
  const valueSettled = !showsValue || (valueBook !== undefined && (waiting !== null || !valueBook.enabled));

  let body: ReactNode;
  if (strategy === "spread") {
    body = <p className="text-sm text-muted">Credit spreads trade on their own in paper. Nothing here needs you.</p>;
  } else if (strategy === "value") {
    // The value book's proposals are not approvals: each is a row that jumps to the Value card, where the one
    // decide flow lives (web overhaul Part 4, ruling 15).
    body = <ValueWaiting emptyText="No value proposal waits on you." />;
  } else if (isError && !data) {
    body = <p className="text-sm text-muted">Proposals unavailable right now.</p>;
  } else if (!data) {
    body = <div className="h-24 rounded-[18px] bg-surface" role="status" aria-busy="true" aria-label="Loading proposals" />;
  } else if (visible.length === 0) {
    // A value proposal listed below is something that needs you: the sentence would contradict the row.
    body = valueWaiting > 0 || !valueSettled ? null : <p className="text-sm text-muted">Nothing needs you right now.</p>;
  } else {
    body = (
      <div className="grid gap-3">
        {visible.map((a) => (
          <ProposalCard key={a.id} approval={a} onReview={setReviewing} />
        ))}
      </div>
    );
  }

  const heading =
    `Needs you${strategy !== "spread" && strategy !== "value" && data ? ` · ${visible.length} proposal${visible.length === 1 ? "" : "s"}` : ""}` +
    (showsValue && valueWaiting > 0 ? ` · ${valueWaiting} value` : "");

  return (
    <section aria-labelledby="needs-you-title">
      <h2 id="needs-you-title" className="mb-2.5 text-[0.8125rem] font-semibold text-muted">
        {heading}
      </h2>
      {body}
      {strategy === "all" && (
        <div className={visible.length > 0 || !data ? "mt-3 empty:hidden" : "empty:hidden"}>
          <ValueWaiting />
        </div>
      )}
      <ReviewSheet approval={reviewing} open={reviewing !== null} onClose={() => setReviewing(null)} />
    </section>
  );
}
