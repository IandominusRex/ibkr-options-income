"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { Hatched } from "@/features/stock-value/parts";
import { dayLabel, whenLabel } from "./format";
import type { NewsCalendarResponse } from "./types";

const SUBHEAD = "mt-4 text-xs font-semibold tracking-[0.04em] text-muted";
const ROW = "flex items-baseline justify-between gap-3 border-t border-border py-2 text-sm first:border-t-0";

/**
 * The week's calendar (restyled in place, web overhaul Part 7): one white card, "This week", with the
 * economic releases and the earnings as quiet rows. Loading, failed and not yet written are each a
 * sentence, and an empty list says so, so the card never vanishes and never reads as "nothing due".
 */
export function CalendarColumn() {
  const q = useQuery({ queryKey: ["news", "calendar"], queryFn: () => apiFetch<NewsCalendarResponse>("/news/calendar?days=7"),
                       placeholderData: (prev) => prev, refetchInterval: 5 * 60_000 });
  return (
    <Card aria-labelledby="calendar-title" data-testid="news-calendar">
      <h2 id="calendar-title" className="text-[1.0625rem] font-bold">
        This week
      </h2>
      <p className="mt-1 text-[0.8125rem] text-muted">The next 7 days, in Singapore time with New York time beside it.</p>
      {q.isPending && <div role="status" aria-busy="true" aria-label="Loading the calendar" className="mt-3 h-20 rounded-xl bg-sunk" />}
      {q.isError && !q.data && <p className="mt-3 text-sm">The calendar could not be loaded.</p>}
      {q.data && !q.data.available && <p className="mt-3 text-sm">The news service has not written the calendar yet.</p>}
      {q.data?.available && (
        <>
          <h3 className={SUBHEAD}>Economic releases</h3>
          {q.data.econ.length === 0 ? (
            <p className="mt-1 text-sm text-muted">None in the next 7 days.</p>
          ) : (
            <ul className="mt-1">
              {q.data.econ.map((e) => (
                <li key={`${e.scheduled_at}-${e.title}`} className={ROW}>
                  <span className="min-w-0">{e.title}</span>
                  {e.actual ? (
                    <span className="shrink-0 text-right text-[0.8125rem]">
                      <span className="tabular font-semibold">{e.actual}</span>
                      <span className="text-muted"> vs </span>
                      {e.forecast ? <span className="tabular">{e.forecast}</span> : <Hatched />}
                      <span className="text-muted"> forecast</span>
                    </span>
                  ) : (
                    <span className="tabular shrink-0 text-right text-[0.8125rem] text-muted">{whenLabel(e.scheduled_at)}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <h3 className={SUBHEAD}>Earnings</h3>
          {q.data.earnings.length === 0 ? (
            <p className="mt-1 text-sm text-muted">None in the next 7 days.</p>
          ) : (
            <ul className="mt-1">
              {q.data.earnings.map((e) => (
                <li key={`${e.symbol}-${e.report_date}`} className={ROW}>
                  <span className="flex min-w-0 items-center gap-2">
                    <Link
                      href={`/news/${encodeURIComponent(e.symbol)}`}
                      className="flex min-h-11 items-center font-semibold underline-offset-2 hover:underline md:min-h-0"
                    >
                      {e.symbol}
                    </Link>
                    {e.held && <StatusWord>Held</StatusWord>}
                  </span>
                  <span className="tabular shrink-0 text-right text-[0.8125rem] text-muted">
                    {dayLabel(e.report_date)}
                    {e.timing ? ` · ${e.timing.toUpperCase()}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}
