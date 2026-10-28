"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import { parseMonth } from "./month";

/**
 * The Pay month, kept in `?month=YYYY-MM`. None, junk or a future month is `current`; choosing the
 * current month removes the parameter, so "This month" is the bare URL. Other parameters (the view)
 * are kept. A page using this must render inside <Suspense> (Next's useSearchParams rule).
 */
export function useMonthParam(current: string): [string, (month: string) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const value = parseMonth(params.get("month"), current);

  const set = useCallback(
    (month: string) => {
      const next = new URLSearchParams(params.toString());
      if (month === current) next.delete("month");
      else next.set("month", month);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, router, pathname, current],
  );

  return [value, set];
}
