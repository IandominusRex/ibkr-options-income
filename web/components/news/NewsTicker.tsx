"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { NewsCard } from "./NewsCard";
import { NameNotes } from "@/features/market/NameNotes";
import { dayLabel } from "./format";
import type { NewsPostDetail, NewsTickerResponse } from "./types";

/**
 * The body of one name's news page (restyled in place, web overhaul Part 7; the frame, the title and the
 * brief request are `features/news/NewsTickerPage`): the next earnings, the latest brief, the market
 * picture's notes on the name and the grouped stories. Loading, failed, not yet written and no brief are
 * each a sentence.
 */
export function NewsTicker({ symbol }: { symbol: string }) {
  const sym = symbol.toUpperCase();
  const t = useQuery({
    queryKey: ["news", "ticker", sym], queryFn: () => apiFetch<NewsTickerResponse>(`/news/ticker/${encodeURIComponent(sym)}`),
    placeholderData: (prev) => prev,
    refetchInterval: (q) => (q.state.data?.request && ["pending", "running"].includes(q.state.data.request.status) ? 3_000 : 60_000),
  });
  const briefId = t.data?.latest_brief?.id;
  const detail = useQuery({ queryKey: ["news", "post", briefId], enabled: Boolean(briefId && t.data?.latest_brief?.has_chart),
                            queryFn: () => apiFetch<NewsPostDetail>(`/news/posts/${briefId}`) });

  return (
    <>
      {t.isPending && <div role="status" aria-busy="true" aria-label={`Loading ${sym} news`} className="h-28 rounded-[18px] bg-surface" />}
      {t.isError && !t.data && <p className="text-sm">The news for {sym} could not be loaded. It is asked for again every minute.</p>}
      {t.data?.next_earnings && (
        <p className="tabular text-sm">
          Next earnings {dayLabel(t.data.next_earnings.report_date)}
          {t.data.next_earnings.timing ? ` · ${t.data.next_earnings.timing.toUpperCase()}` : ""}
        </p>
      )}
      {t.data && !t.data.available && <p className="text-sm">The news service has not written anything yet.</p>}
      {t.data?.available && !t.data.latest_brief && <p className="text-sm">No brief yet. Request one above.</p>}
      {t.data?.latest_brief && <NewsCard post={t.data.latest_brief} chartUri={detail.data?.chart_data_uri ?? null} />}
      <NameNotes symbol={sym} />
      {t.data && t.data.clusters.length > 0 && (
        <Card aria-labelledby="stories-title">
          <h2 id="stories-title" className="text-[1.0625rem] font-bold">
            Recent stories
          </h2>
          <p className="mt-1 text-[0.8125rem] text-muted">Headlines the news service grouped as one story, with how many sources carried it.</p>
          <ul className="mt-2">
            {t.data.clusters.map((c) => (
              <li key={c.id} className="border-t border-border py-2 text-sm first:border-t-0 md:py-2.5">
                <p className="font-semibold">{c.headline}</p>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[0.8125rem] text-muted">
                  <span className="tabular">{c.source_count === 1 ? "1 source" : `${c.source_count} sources`}</span>
                  {c.links.slice(0, 2).map((l) => (
                    <a
                      key={l.url}
                      href={l.url}
                      target="_blank"
                      rel="noreferrer"
                      className="flex min-h-11 items-center font-semibold text-content underline-offset-2 hover:underline md:inline md:min-h-0"
                    >
                      {l.name}
                      <span className="sr-only"> (opens in a new tab)</span>
                    </a>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
