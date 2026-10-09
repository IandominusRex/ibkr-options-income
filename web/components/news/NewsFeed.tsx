"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { CalendarColumn } from "./CalendarColumn";
import { NewsCard } from "./NewsCard";
import type { NewsFeedResponse } from "./types";

const GROUPS: { key: string | null; label: string }[] = [
  { key: null, label: "All" }, { key: "macro", label: "Macro" }, { key: "market", label: "Market" },
  { key: "tickers", label: "Tickers" }, { key: "earnings", label: "Earnings" }, { key: "briefs", label: "Briefs" },
];

export function NewsFeed() {
  const [group, setGroup] = useState<string | null>(null);
  const [symbol, setSymbol] = useState("");
  // The query follows the box 300ms after the last keystroke, not on every one.
  const [filter, setFilter] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setFilter(symbol.trim().toUpperCase()), 300);
    return () => clearTimeout(id);
  }, [symbol]);
  const params = new URLSearchParams();
  if (group) params.set("group", group);
  if (filter) params.set("symbol", filter);
  params.set("limit", "30");
  const path = `/news/feed?${params.toString()}`;
  const q = useQuery({ queryKey: ["news", "feed", path], queryFn: () => apiFetch<NewsFeedResponse>(path),
                       placeholderData: (prev) => prev, refetchInterval: 60_000 });

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_320px]" data-testid="news-feed">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {GROUPS.map((g) => (
            <button key={g.label} type="button" onClick={() => setGroup(g.key)} aria-pressed={group === g.key}
              className={`rounded-sm px-3 py-1 text-sm ${group === g.key ? "bg-elevated text-content" : "text-muted hover:text-content"} focus-visible:ring-focus`}>
              {g.label}
            </button>
          ))}
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="Symbol"
            className="ml-auto w-28 rounded-sm bg-background px-2 py-1 font-mono text-sm text-content" aria-label="Filter by symbol" />
        </div>
        {q.isError && <p className="text-sm text-muted">Could not load the news feed.</p>}
        {q.data && !q.data.available && <p className="text-sm text-muted">The news service has not written anything yet.</p>}
        {q.data?.available && q.data.posts.length === 0 && <p className="text-sm text-muted">No posts match.</p>}
        {q.data?.posts.map((p) => <NewsCard key={p.id} post={p} />)}
      </div>
      <CalendarColumn />
    </div>
  );
}
