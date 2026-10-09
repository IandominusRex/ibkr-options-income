"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { BriefRequest } from "./BriefRequest";
import { NewsCard } from "./NewsCard";
import { dayLabel } from "./format";
import type { NewsPostDetail, NewsTickerResponse } from "./types";

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
    <div className="space-y-4" data-testid="news-ticker">
      <header className="flex items-center justify-between gap-4">
        <h1 className="font-mono text-lg text-content">{sym}</h1>
        <BriefRequest symbol={sym} />
      </header>
      {t.data?.next_earnings && (
        <p className="text-sm text-muted">Next earnings {dayLabel(t.data.next_earnings.report_date)} {t.data.next_earnings.timing.toUpperCase()}</p>
      )}
      {t.data && !t.data.available && <p className="text-sm text-muted">The news service has not written anything yet.</p>}
      {t.data?.available && !t.data.latest_brief && <p className="text-sm text-muted">No brief yet. Request one above.</p>}
      {t.data?.latest_brief && <NewsCard post={t.data.latest_brief} chartUri={detail.data?.chart_data_uri ?? null} />}
      {t.data && t.data.clusters.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-content">Recent stories</h2>
          <ul className="space-y-1 text-sm">
            {t.data.clusters.map((c) => (
              <li key={c.id}>
                {c.headline} <span className="text-muted">· {c.source_count} sources</span>
                {c.links.slice(0, 2).map((l) => (
                  <a key={l.url} href={l.url} target="_blank" rel="noreferrer" className="ml-2 text-xs underline decoration-border">{l.name}</a>
                ))}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
