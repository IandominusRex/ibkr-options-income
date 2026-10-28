"use client";

import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useId, useState } from "react";
import type { ShortListResponse } from "@/components/options/types";
import { Card } from "@/components/ui/Card";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusWord } from "@/components/ui/StatusWord";
import { FreshnessLabel } from "@/components/portfolio/FreshnessLabel";
import type { PositionsResponse } from "@/components/portfolio/types";
import { apiFetch } from "@/lib/api";
import { isStale } from "@/lib/money";
import { STRATEGY_LABEL, type StrategyFilter } from "@/lib/strategy";
import { PositionRowItem } from "./PositionRowItem";
import { FRESH_FOR_MINUTES, buildPositionRows, matchesQuery, type PositionRow } from "./positions";
import type { SpreadPositionsResponse } from "./types";

type PositionsFilter = StrategyFilter | "shares";

const FILTERS: PositionsFilter[] = ["all", "csp", "cc", "spread", "shares"];
const LABEL: Record<PositionsFilter, string> = { ...STRATEGY_LABEL, shares: "Shares" };
const EMPTY: Record<PositionsFilter, string> = {
  all: "No open positions.",
  csp: "No cash-secured puts open.",
  cc: "No covered calls open.",
  spread: "No credit spreads open.",
  shares: "No shares held.",
};

function matches(row: PositionRow, f: PositionsFilter): boolean {
  return f === "all" || row.kind === f;
}

function todayNewYork(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
}

export function PositionsCard({ strategy }: { strategy: StrategyFilter }) {
  const [filter, setFilter] = useState<PositionsFilter>(strategy);
  const [query, setQuery] = useState("");
  const searchId = useId();
  // The page's strategy switcher wins whenever it changes; the card's own chips narrow from there.
  const [seen, setSeen] = useState<StrategyFilter>(strategy);
  if (seen !== strategy) {
    setSeen(strategy);
    setFilter(strategy);
  }

  // Same key as <PositionsPanel/> on /portfolio: one request when both are mounted.
  const positions = useQuery({
    queryKey: ["portfolio", "positions"],
    queryFn: () => apiFetch<PositionsResponse>("/portfolio/positions"),
    refetchInterval: 60_000,
  });
  const spreads = useQuery({
    queryKey: ["spreads", "positions", "open"],
    queryFn: () => apiFetch<SpreadPositionsResponse>("/spreads/positions?status=open"),
    refetchInterval: 60_000,
  });
  // Roll alerts the monitor fired (same key as the position page's Roll card). Unreadable means
  // no flag is shown; the rows themselves never depend on it.
  const shorts = useQuery({
    queryKey: ["options", "shorts"],
    queryFn: () => apiFetch<ShortListResponse>("/options/shorts"),
    refetchInterval: 60_000,
  });
  const alerted = new Set((shorts.data?.shorts ?? []).filter((s) => s.alerts.length > 0).map((s) => s.position_symbol));

  // Unknown is never none: an unreadable spreads book is not an empty one.
  const spreadsKnown = spreads.data?.available === true;
  const spreadsOut = spreads.isError || spreads.data?.available === false;
  const spreadRows = spreadsKnown ? spreads.data!.positions : [];
  const rows = positions.data
    ? buildPositionRows(positions.data.groups, spreadRows, todayNewYork(), spreads.data?.underlying, alerted)
    : [];
  // The search narrows first, so every chip's count says what that chip would show right now.
  const searched = rows.filter((r) => matchesQuery(r, query));
  const visible = searched.filter((r) => matches(r, filter));
  const options = FILTERS.map((f) => ({
    value: f,
    label: LABEL[f],
    count: !positions.data || (f === "spread" && !spreadsKnown) ? null : searched.filter((r) => matches(r, f)).length,
  }));
  const searching = query.trim() !== "";

  let message: string | null = null;
  if (positions.isError && !positions.data) message = "Positions unavailable right now.";
  else if (positions.data && visible.length === 0) {
    if (searching) message = `No positions match "${query.trim()}".`;
    else if (filter === "spread" && spreadsOut) message = "Credit spreads are unavailable right now.";
    else if (filter === "spread" && spreads.isPending) message = "Loading credit spreads.";
    else if (positions.data.source === "none" && filter !== "spread") message = "No positions captured yet.";
    else message = EMPTY[filter];
  }
  const loading = !positions.data && !positions.isError;
  const delayed =
    positions.data !== undefined &&
    positions.data.source !== "none" &&
    (positions.data.degraded || isStale(positions.data.as_of, FRESH_FOR_MINUTES));

  return (
    <Card className="mt-4" aria-labelledby="positions-title">
      <div className="flex items-baseline justify-between">
        <h2 id="positions-title" className="text-[1.0625rem] font-bold">
          Positions
        </h2>
        <span className="text-[0.8125rem] text-muted">Sorted by expiry</span>
      </div>
      <form role="search" onSubmit={(e) => e.preventDefault()} className="relative mt-2">
        <label htmlFor={searchId} className="sr-only">
          Search positions
        </label>
        <Search size={16} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          id={searchId}
          type="text"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search a ticker, like AMZN"
          // 16px: below that, iOS zooms the page when the field takes focus.
          className="min-h-11 w-full rounded-xl border border-control bg-surface pl-9 pr-11 text-base placeholder:text-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
        />
        {searching && (
          <button
            type="button"
            aria-label="Clear search"
            onClick={() => setQuery("")}
            className="absolute right-0 top-1/2 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full text-muted hover:bg-sunk hover:text-content md:right-1 md:h-9 md:w-9"
          >
            <X size={16} aria-hidden="true" />
          </button>
        )}
      </form>
      <SegmentedControl
        label="Position type"
        appearance="chips"
        options={options}
        value={filter}
        onChange={setFilter}
        className="mb-1 mt-3"
      />
      {delayed && (
        <p className="mt-2 flex flex-wrap items-center gap-2">
          <StatusWord tone="flag">Delayed</StatusWord>
          <FreshnessLabel asOf={positions.data!.as_of} freshForMinutes={FRESH_FOR_MINUTES} />
        </p>
      )}
      {loading ? (
        <div role="status" aria-busy="true" aria-label="Loading positions" className="space-y-3 py-3">
          <div className="h-9 rounded-xl bg-sunk" />
          <div className="h-9 rounded-xl bg-sunk" />
        </div>
      ) : message !== null ? (
        <p className="py-3 text-sm text-muted">{message}</p>
      ) : (
        <ul>
          {visible.map((r) => (
            <PositionRowItem key={r.key} row={r} />
          ))}
        </ul>
      )}
      {filter === "all" && spreadsOut && positions.data && (
        <p className="border-t border-border pt-2.5 text-[0.8125rem] text-muted">
          Credit spreads are unavailable right now, so they are not listed.
        </p>
      )}
    </Card>
  );
}
