"use client";

import clsx from "clsx";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/Card";
import { sentimentLabel, sentimentTint } from "@/components/stock/NewsPanel";
import { apiFetch } from "@/lib/api";
import { relativeAge } from "@/lib/format";
import type { HeadlinesResponse } from "./types";

const SHOWN = 6;

/**
 * The top headlines for the underlying, newest first, each with its sentiment as a word (never
 * colour alone). Links open in a new tab; nothing here reaches a gate or a size.
 */
export function Headlines({ symbol }: { symbol: string }) {
  const { data, isError } = useQuery({
    queryKey: ["headlines", symbol],
    queryFn: () => apiFetch<HeadlinesResponse>(`/research/${symbol}/headlines?limit=${SHOWN}`),
    staleTime: 5 * 60_000,
  });
  const items = data?.items ?? [];

  return (
    <Card as="section" aria-labelledby="headlines-title">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="headlines-title" className="text-[1.0625rem] font-bold">
          {symbol} headlines
        </h2>
        <Link href={`/news/${symbol}`} className="inline-flex min-h-6 items-center text-[0.8125rem] text-muted underline-offset-2 hover:underline">
          Ticker news
        </Link>
      </div>
      {isError && !data ? (
        <p className="mt-2 text-sm text-muted">Headlines are unavailable right now.</p>
      ) : !data ? (
        <div role="status" aria-busy="true" aria-label="Loading headlines" className="mt-3 space-y-3">
          <div className="h-10 rounded-xl bg-sunk" />
          <div className="h-10 rounded-xl bg-sunk" />
        </div>
      ) : items.length === 0 ? (
        <p className="mt-2 text-sm text-muted">No recent headlines for {symbol}.</p>
      ) : (
        <ul className="mt-1">
          {items.map((h, i) => {
            const age = relativeAge(h.published_at);
            return (
              <li key={`${h.url ?? h.title}-${i}`} className="border-t border-border py-3 text-sm first:border-t-0">
                {h.url ? (
                  <a
                    href={h.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex min-h-11 items-center font-semibold underline-offset-2 hover:underline md:inline md:min-h-0"
                  >
                    {h.title}
                    <span className="sr-only"> (opens in a new tab)</span>
                  </a>
                ) : (
                  <span className="font-semibold">{h.title}</span>
                )}
                <div className="mt-0.5 flex flex-wrap gap-x-2 text-[0.8125rem] text-muted">
                  {h.source && <span>{h.source}</span>}
                  {age && <span>{age}</span>}
                  <span className={clsx("font-semibold", sentimentTint(h.sentiment), h.sentiment === null && "hatch")}>{sentimentLabel(h.sentiment)}</span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
