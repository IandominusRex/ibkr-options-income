"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { type StrategyFilter, WHEEL_FILTERS } from "@/lib/strategy";
import { isCalendarDay } from "./time";
import { VIEW_LABEL, type TradesView, defaultView, explicitView } from "./views";

/**
 * The Trades view, kept in `?view=` beside `?strategy=` so a reload or a shared link keeps both.
 * With no view in the URL the default (ruling 2) is decided once per visit and strategy, when the
 * pending count first loads, so approving the last proposal never moves the page under you.
 * Null only while that count is still loading; when it failed to load (`pendingFailed`) the
 * default is History, decided once like any other, so a later recovery does not flip the view.
 * A page using this must render inside <Suspense> (Next's useSearchParams rule).
 */
export function useTradesView(
  strategy: StrategyFilter,
  pending: number | null,
  pendingFailed = false,
): [TradesView | null, (v: TradesView) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const explicit = explicitView(params.get("view"), strategy);
  const fresh = defaultView(strategy, pending, pendingFailed);
  const [decided, setDecided] = useState<Partial<Record<StrategyFilter, TradesView>>>({});

  useEffect(() => {
    if (fresh === null) return;
    setDecided((d) => (d[strategy] === undefined ? { ...d, [strategy]: fresh } : d));
  }, [fresh, strategy]);

  const set = useCallback(
    (v: TradesView) => {
      const next = new URLSearchParams(params.toString());
      next.set("view", v);
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [params, router, pathname],
  );

  return [explicit ?? decided[strategy] ?? fresh, set];
}

/**
 * History's day in `?day=YYYY-MM-DD`; null (the parameter left out, or not a real calendar date)
 * is today in New York.
 */
export function useTradesDay(): [string | null, (day: string | null) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("day");
  const value = raw !== null && isCalendarDay(raw) ? raw : null;

  const set = useCallback(
    (day: string | null) => {
      const next = new URLSearchParams(params.toString());
      if (day === null) next.delete("day");
      else next.set("day", day);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, router, pathname],
  );

  return [value, set];
}

/**
 * The three Trades parameters a proposal's page hands back to Back to Trades: `view`, `day` (a real
 * calendar day) and `strategy` (a filter Trades has), in that order, each validated and the rest
 * dropped. "" for nothing to carry. Takes a plain reader so a null `useSearchParams()` is just empty.
 */
export function tradesReturnQuery(params: { get(name: string): string | null } | null): string {
  if (params === null) return "";
  const out = new URLSearchParams();
  const view = params.get("view");
  if (view !== null && view in VIEW_LABEL) out.set("view", view);
  const day = params.get("day");
  if (day !== null && isCalendarDay(day)) out.set("day", day);
  const strategy = params.get("strategy");
  if (strategy !== null && (WHEEL_FILTERS as string[]).includes(strategy)) out.set("strategy", strategy);
  return out.toString();
}

/**
 * The return query for a card that knows which view it is in. `day` null (today) and strategy All are left
 * out: they are the defaults, and a pinned today would open yesterday tomorrow.
 */
export function viewReturnQuery(view: TradesView, strategy: StrategyFilter, day: string | null = null): string {
  const p = new URLSearchParams({ view });
  if (day !== null) p.set("day", day);
  if (strategy !== "all") p.set("strategy", strategy);
  return tradesReturnQuery(p);
}

/** A proposal's page, carrying the Trades view it was opened from (`query` is a `tradesReturnQuery`). */
export function detailHref(approvalId: number, query: string): string {
  return query ? `/trades/${approvalId}?${query}` : `/trades/${approvalId}`;
}
