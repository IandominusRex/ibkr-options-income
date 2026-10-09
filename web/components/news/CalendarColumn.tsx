"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { dayLabel, whenLabel } from "./format";
import type { NewsCalendarResponse } from "./types";

export function CalendarColumn() {
  const q = useQuery({ queryKey: ["news", "calendar"], queryFn: () => apiFetch<NewsCalendarResponse>("/news/calendar?days=7"),
                       placeholderData: (prev) => prev, refetchInterval: 5 * 60_000 });
  if (!q.data?.available) return null;
  return (
    <aside className="space-y-4" data-testid="news-calendar">
      <section>
        <h2 className="pb-2 text-sm font-medium text-content">Economic calendar</h2>
        <ul className="space-y-1 text-xs">
          {q.data.econ.map((e) => (
            <li key={`${e.scheduled_at}-${e.title}`} className="flex justify-between gap-2">
              <span>{e.title}</span>
              <span className="font-mono text-muted tabular">
                {e.actual ? `${e.actual} vs ${e.forecast ?? "n/a"}` : whenLabel(e.scheduled_at)}
              </span>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h2 className="pb-2 text-sm font-medium text-content">Earnings</h2>
        <ul className="space-y-1 text-xs">
          {q.data.earnings.map((e) => (
            <li key={`${e.symbol}-${e.report_date}`} className="flex justify-between gap-2">
              <a href={`/news/${e.symbol}`} className="font-mono">{e.symbol}{e.held ? " · held" : ""}</a>
              <span className="text-muted">{dayLabel(e.report_date)} {e.timing.toUpperCase()}</span>
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
