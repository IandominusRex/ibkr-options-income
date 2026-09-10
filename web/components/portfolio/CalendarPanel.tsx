"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { EmptyState } from "@/components/options/EmptyState";
import { UNKNOWN } from "@/lib/format";
import { FreshnessLabel } from "./FreshnessLabel";
import type { CalendarDay, CalendarEntry, CalendarResponse } from "./types";

// Mirrors PositionsPanel.tsx's FRESH_FOR_MINUTES: CalendarResponse reads
// from the same portfolio-snapshot freshness spine as PositionsResponse
// (both come from src/api/routers/portfolio.py's `read_portfolio`), so the
// same 30-minute window (2x the default 15-minute snapshot interval)
// applies here too. Kept as a literal, not imported, for the same reason
// every other panel keeps its own copy: the web layer has no config access.
const FRESH_FOR_MINUTES = 30;

const HORIZON_OPTIONS = [14, 30, 45, 90, 180] as const;
const DEFAULT_HORIZON = 45; // matches the backend's own Query(default=45)

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/**
 * "2026-09-19" -> "Sep 19, 2026", parsed from the ISO date's own parts rather
 * than through a `Date` object - `new Date("2026-09-19")` is UTC midnight,
 * and formatting it through local getters can roll the day back for anyone
 * west of UTC. `expiry` is a date, not an instant; this never touches a
 * timezone.
 */
function formatExpiryDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/**
 * `consequence`'s four values, each with its own wording. `unknown` is a
 * real, named state - `src/api/routers/portfolio.py::portfolio_calendar`'s
 * own docstring says the backend was told never to default it to
 * `expires_worthless` - so it renders its own sentence here too, not folded
 * into `expires_worthless`'s.
 */
function consequenceText(c: CalendarEntry["consequence"]): string {
  switch (c) {
    case "assigned":
      return "Assigned - shares change hands";
    case "called_away":
      return "Called away - shares are sold";
    case "expires_worthless":
      return "Expires worthless";
    case "unknown":
      return "Consequence unknown";
  }
}

/**
 * The expiry calendar - the Calendar tab of the portfolio console (P3-P4 M3
 * Task 3.5). Self-fetches `GET /portfolio/calendar`, matching
 * `PositionsPanel`/`CampaignsPanel`'s self-fetch convention rather than a
 * `data` prop (the brief's own illustrative `<CalendarPanel data={...}/>`
 * snippet is a stale simplification - the response's `source`/`degraded`/
 * `as_of`/`horizon_days` only make sense for a component managing its own
 * fetch, the same situation Task 3.3 hit with `PositionsPanel`).
 *
 * `horizon` is component state, flowing into both the fetch URL
 * (`?horizon_days=N`) and the query key (`["portfolio","calendar",horizon]`)
 * - mirroring `CampaignsPanel.tsx`'s `status`/`symbol` filter pattern, so
 * changing it is a real refetch against the backend's own `horizon_days`
 * query param, never a client-side slice of an already-fetched response.
 *
 * `FreshnessLabel` renders unconditionally above the content, in both the
 * empty and non-empty branches, reading `data.as_of` - `CalendarResponse`
 * shares `PositionsResponse`'s `source`/`degraded`/`as_of` freshness spine
 * (both come from `read_portfolio`), and Task 3.3 was sent back for a fix
 * round for skipping exactly this: the `eod` fallback rung can return real,
 * non-empty `days` with `degraded=true` and a capture time up to a day old,
 * rendering pixel-identical to a live `monitor` read without it.
 * `DegradedNotice` stays unused here: `CalendarResponse` has
 * `degraded: boolean` but no `note` field (confirmed against the generated
 * schema), so there is nothing for it to render - an accepted pre-existing
 * backend gap, matching `PositionsPanel`.
 */
export function CalendarPanel() {
  const [horizon, setHorizon] = useState<number>(DEFAULT_HORIZON);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["portfolio", "calendar", horizon],
    queryFn: () => apiFetch<CalendarResponse>(`/portfolio/calendar?horizon_days=${horizon}`),
    placeholderData: (prev) => prev,
    // Design spec §9.4 / matches SummaryPanel and every other self-fetching
    // panel's 30s poll - the freshness label must not freeze at mount.
    refetchInterval: 30_000,
  });

  if (isError) {
    return <p className="text-sm text-muted">Could not load the calendar.</p>;
  }
  if (isLoading || !data) {
    return <p className="text-sm text-muted">Loading calendar</p>;
  }

  const freshness = <FreshnessLabel asOf={data.as_of} freshForMinutes={FRESH_FOR_MINUTES} />;
  const horizonControl = (
    <div className="flex items-center gap-2">
      <label htmlFor="calendar-horizon" className="text-xs text-muted">
        Horizon
      </label>
      <select
        id="calendar-horizon"
        value={horizon}
        onChange={(e) => setHorizon(Number(e.target.value))}
        className="rounded border border-border bg-surface px-2 py-1 text-xs text-content"
      >
        {HORIZON_OPTIONS.map((h) => (
          <option key={h} value={h}>
            {h} days
          </option>
        ))}
      </select>
    </div>
  );
  const header = (
    <div className="flex flex-wrap items-center justify-between gap-3">
      {freshness}
      {horizonControl}
    </div>
  );

  if (data.days.length === 0) {
    const text =
      data.source === "none"
        ? "No portfolio snapshot has been captured yet."
        : `No option expiries within the next ${data.horizon_days} days.`;
    return (
      <div role="status" data-testid="calendar-panel" className="space-y-3">
        {header}
        <EmptyState text={text} />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="calendar-panel">
      {header}
      <div className="space-y-3">
        {data.days.map((day) => (
          <CalendarDayCard day={day} key={day.expiry} />
        ))}
      </div>
    </div>
  );
}

function CalendarDayCard({ day }: { day: CalendarDay }) {
  return (
    <section
      className="rounded-md border border-border bg-surface p-4"
      data-testid="calendar-day"
    >
      <h3 className="font-mono text-sm text-content">
        {formatExpiryDate(day.expiry)}
        <span className="ml-2 tabular text-xs text-muted">{day.dte} DTE</span>
      </h3>
      <ul className="mt-3 divide-y divide-border">
        {day.entries.map((entry) => (
          <CalendarEntryRow entry={entry} key={entry.symbol} />
        ))}
      </ul>
    </section>
  );
}

function CalendarEntryRow({ entry }: { entry: CalendarEntry }) {
  return (
    <li
      className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2 text-xs"
      data-testid="calendar-entry"
    >
      <span className="font-mono text-content">
        {entry.underlying} {entry.strike.toFixed(2)} {entry.right}
      </span>
      <span className="text-muted">{entry.short ? "Short" : "Long"}</span>
      <span className="tabular text-content">
        {entry.contracts} contract{entry.contracts === 1 ? "" : "s"}
      </span>
      <span className={entry.moneyness == null ? "hatch text-unknown" : "text-content"}>
        {entry.moneyness ?? UNKNOWN}
      </span>
      <span
        data-testid="consequence"
        className={entry.consequence === "unknown" ? "hatch text-unknown" : "text-content"}
      >
        {consequenceText(entry.consequence)}
      </span>
      {entry.assignment_risk && <span className="text-unknown">Assignment risk</span>}
    </li>
  );
}
