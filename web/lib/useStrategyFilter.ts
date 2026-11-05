"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import { STRATEGY_FILTERS, type StrategyFilter, parseStrategyFilter } from "./strategy";

/**
 * The strategy switcher's value, kept in `?strategy=` so a reload or a shared link keeps it.
 * A page using this must render inside <Suspense> (Next's useSearchParams rule). A page that does
 * not offer every filter (Trades has no Value) passes the ones it does; any other value reads All.
 */
export function useStrategyFilter(
  allowed: StrategyFilter[] = STRATEGY_FILTERS,
): [StrategyFilter, (f: StrategyFilter) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const value = parseStrategyFilter(params.get("strategy"), allowed);

  const set = useCallback(
    (f: StrategyFilter) => {
      const next = new URLSearchParams(params.toString());
      if (f === "all") next.delete("strategy");
      else next.set("strategy", f);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, router, pathname],
  );

  return [value, set];
}
