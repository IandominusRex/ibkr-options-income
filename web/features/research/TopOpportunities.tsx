"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { apiFetch } from "@/lib/api";
import { OpportunityCard } from "./OpportunityCard";
import { listWords, readyFirst, sellPutAvailable } from "./format";
import type { AssessedResponse, TopList, TopResponse } from "./types";

const TABS: { value: TopList; label: string }[] = [
  { value: "deep_value", label: "Deep value" },
  { value: "quality_growth", label: "Quality growth" },
];

// The latest full scan's candidates that passed every stage: the same endpoint Trades, Assessed reads.
const PASSED = "/options/assessed?run=latest&stage=passed&limit=1000";

/**
 * Research's Top opportunities strip (value book Part 6, Task 18): up to ten names on the chosen
 * list, READY first, from `GET /value/top`. It reads and links; it sends no command and gates
 * nothing. Only the list on view is fetched.
 */
export function TopOpportunities() {
  const [list, setList] = useState<TopList>("deep_value");
  const top = useQuery({
    queryKey: ["value", "top", list],
    queryFn: () => apiFetch<TopResponse>(`/value/top?list=${list}`),
  });
  const items = top.data?.available ? readyFirst(top.data.items ?? []) : [];
  const wantsPut = items.some((i) => i.put_ceiling != null);
  const assessed = useQuery({
    queryKey: ["value", "top", "assessed-passed"],
    queryFn: () => apiFetch<AssessedResponse>(PASSED),
    enabled: wantsPut,
  });

  let body;
  if (top.isError) {
    body = <p className="text-sm text-muted">The top opportunities could not be loaded right now.</p>;
  } else if (!top.data) {
    body = (
      <div role="status" aria-busy="true" aria-label="Loading top opportunities" className="h-40 rounded-[18px] bg-surface" />
    );
  } else if (!top.data.available) {
    body = <p className="text-sm">The value book has not written anything yet.</p>;
  } else if (items.length === 0) {
    body = (
      <p className="text-sm">No name on the {listWords(list)} list is ready, on watch or waiting.</p>
    );
  } else {
    body = (
      <div className="grid gap-3 md:grid-cols-2">
        {items.map((it) => (
          <OpportunityCard
            key={`${it.list_name}:${it.symbol}`}
            item={it}
            canSellPut={sellPutAvailable(it, assessed.data)}
          />
        ))}
      </div>
    );
  }

  return (
    <div>
      <SegmentedControl label="Opportunity list" options={TABS} value={list} onChange={setList} />
      <div className="mt-3">{body}</div>
    </div>
  );
}
