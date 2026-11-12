"use client";

import { useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";
import { NewsCard } from "./NewsCard";
import type { NewsFeedResponse } from "./types";

type Group = "all" | "macro" | "market" | "tickers" | "earnings" | "briefs";

const GROUPS: { value: Group; label: string }[] = [
  { value: "all", label: "All" }, { value: "macro", label: "Macro" }, { value: "market", label: "Market" },
  { value: "tickers", label: "Tickers" }, { value: "earnings", label: "Earnings" }, { value: "briefs", label: "Briefs" },
];

/**
 * The news feed (restyled in place, web overhaul Part 7): a titled section with the group chips and a
 * labelled symbol field, then the posts newest first. Loading, failed, not yet written and no match
 * are each a sentence, so an empty list never reads as "no news".
 */
export function NewsFeed() {
  const [group, setGroup] = useState<Group>("all");
  const [symbol, setSymbol] = useState("");
  const fieldId = useId();
  // The query follows the box 300ms after the last keystroke, not on every one.
  const [filter, setFilter] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setFilter(symbol.trim().toUpperCase()), 300);
    return () => clearTimeout(id);
  }, [symbol]);
  const params = new URLSearchParams();
  if (group !== "all") params.set("group", group);
  if (filter) params.set("symbol", filter);
  params.set("limit", "30");
  const path = `/news/feed?${params.toString()}`;
  const q = useQuery({ queryKey: ["news", "feed", path], queryFn: () => apiFetch<NewsFeedResponse>(path),
                       placeholderData: (prev) => prev, refetchInterval: 60_000 });

  return (
    <section aria-labelledby="feed-title" data-testid="news-feed">
      <h2 id="feed-title" className="text-[1.0625rem] font-bold">
        Latest
      </h2>
      <p className="mt-1 text-[0.8125rem] text-muted">The news service&apos;s posts, newest first, 30 at most.</p>
      <div className="mt-3 flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
        <SegmentedControl label="Show" appearance="chips" options={GROUPS} value={group} onChange={setGroup} />
        <div className="flex flex-col gap-1">
          <label htmlFor={fieldId} className={FIELD_LABEL}>
            Filter by symbol
          </label>
          <input
            id={fieldId}
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="Ticker"
            autoCapitalize="characters"
            autoComplete="off"
            spellCheck={false}
            className={`${FIELD} w-36 uppercase`}
          />
        </div>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3">
        {q.isPending && (
          <div role="status" aria-busy="true" aria-label="Loading the news" className="h-28 rounded-[18px] bg-surface" />
        )}
        {q.isError && !q.data && <p className="text-sm">The news feed could not be loaded. It is asked for again every minute.</p>}
        {q.data && !q.data.available && <p className="text-sm">The news service has not written anything yet.</p>}
        {q.data?.available && q.data.posts.length === 0 && (
          <p className="text-sm">{filter ? `No posts match ${filter} in this group.` : "No posts in this group yet."}</p>
        )}
        {q.data?.posts.map((p) => <NewsCard key={p.id} post={p} />)}
      </div>
    </section>
  );
}
