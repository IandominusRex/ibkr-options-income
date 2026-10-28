"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { FreshnessLabel } from "@/components/portfolio/FreshnessLabel";
import type { CalendarDay, CalendarEntry, CalendarResponse } from "@/components/portfolio/types";
import { Card } from "@/components/ui/Card";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusWord } from "@/components/ui/StatusWord";
import { shortDay } from "@/features/claude-context/format";
import type { Dossier } from "@/features/claude-context/types";
import { useClaudeContext } from "@/features/claude-context/useClaudeContext";
import { FRESH_FOR_MINUTES, optionStatus } from "@/features/home/positions";
import { eventBefore } from "@/features/market/market";
import { todayInNewYork } from "@/features/trades/time";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { isStale } from "@/lib/money";
import {
  DEFAULT_HORIZON,
  HORIZONS,
  consequenceSentence,
  daysLeft,
  entryTitle,
  expiryLabel,
} from "./calendar";

function Entry({
  e,
  day,
  today,
  dossier,
}: {
  e: CalendarEntry;
  day: CalendarDay;
  today: string;
  dossier: Dossier | undefined;
}) {
  const status = optionStatus(
    { expiry: day.expiry, dte: day.dte, assignment_risk: e.assignment_risk, moneyness: e.moneyness },
    today,
  );
  // "Expires today" shadows the monitor's flag on the day itself, so the flag is said as well.
  const alsoAssignment = e.assignment_risk && status?.word !== "Assignment likely";
  // Only a short has a reason to care that news is due before it expires.
  const event = e.short ? eventBefore(dossier, today, day.expiry) : null;
  return (
    <li className="border-t border-border py-[11px] first:border-t-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 text-sm">
          <span className="font-bold">{entryTitle(e)}</span>
          {status && (
            <span className="ml-1.5 align-[1px]">
              <StatusWord tone={status.tone}>{status.word}</StatusWord>
            </span>
          )}
          {alsoAssignment && (
            <span className="ml-1.5 align-[1px]">
              <StatusWord tone="flag">Assignment likely</StatusWord>
            </span>
          )}
          {event && (
            <span className="ml-1.5 align-[1px]">
              <StatusWord>{`Event ${shortDay(event)} before expiry`}</StatusWord>
            </span>
          )}
          <div className="text-[0.8125rem] text-muted">
            {e.short ? "Short" : "Long"} · {e.contracts} contract{e.contracts === 1 ? "" : "s"}
          </div>
          {e.moneyness === null && (
            <div className="text-[0.8125rem] text-muted">
              Moneyness <span className="hatch text-unknown">{UNKNOWN}</span>
            </div>
          )}
        </div>
        <div className="text-right text-sm">{consequenceSentence(e.consequence)}</div>
      </div>
    </li>
  );
}

/**
 * The expiry calendar: what expires when, and what happens when it does. The horizon goes to the
 * API. A short whose name has a verified event date before its expiry carries that date as a word
 * (the news service's notes, read through the same request the rest of the app shares).
 */
export function CalendarView() {
  const [horizon, setHorizon] = useState<number>(DEFAULT_HORIZON);
  const { data, isError } = useQuery({
    queryKey: ["portfolio", "calendar", horizon],
    queryFn: () => apiFetch<CalendarResponse>(`/portfolio/calendar?horizon_days=${horizon}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const notes = useClaudeContext();
  const today = todayInNewYork();
  const dossierOf = (symbol: string) => notes.data?.dossiers?.find((d) => d.symbol === symbol.toUpperCase());

  const delayed =
    data !== undefined && data.source !== "none" && (data.degraded || isStale(data.as_of, FRESH_FOR_MINUTES));

  return (
    <div className="grid gap-3">
      <SegmentedControl
        label="Horizon"
        appearance="chips"
        options={HORIZONS.map((h) => ({ value: String(h), label: `${h} days` }))}
        value={String(horizon)}
        onChange={(v) => setHorizon(Number(v))}
      />
      {delayed && (
        <p className="flex flex-wrap items-center gap-2">
          <StatusWord tone="flag">Delayed</StatusWord>
          <FreshnessLabel asOf={data!.as_of} freshForMinutes={FRESH_FOR_MINUTES} />
        </p>
      )}
      {isError && !data ? (
        <div className="text-sm text-muted">
          <p>Could not load the calendar.</p>
          <p className="mt-1 text-[0.8125rem]">It tries again every 30 seconds.</p>
        </div>
      ) : !data ? (
        <div role="status" aria-busy="true" aria-label="Loading the calendar" className="h-24 rounded-[18px] bg-surface" />
      ) : data.days.length === 0 ? (
        <p className="py-3 text-sm text-muted">
          {data.source === "none"
            ? "No portfolio snapshot has been captured yet."
            : `No option expiries within the next ${data.horizon_days} days.`}
        </p>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {data.days.map((d) => {
            const label = expiryLabel(d.expiry);
            return (
              <Card as="section" key={d.expiry} aria-label={`Expiries on ${label}`}>
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="text-[1.0625rem] font-bold">{label}</h3>
                  <span className="text-[0.8125rem] text-muted">{daysLeft(d.dte)}</span>
                </div>
                <ul className="mt-1">
                  {d.entries.map((e) => (
                    <Entry key={e.symbol} e={e} day={d} today={today} dossier={dossierOf(e.underlying)} />
                  ))}
                </ul>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
