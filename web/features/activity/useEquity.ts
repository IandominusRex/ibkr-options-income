"use client";

import { useQuery } from "@tanstack/react-query";
import type { EquityResponse } from "@/components/pnl/types";
import { apiFetch } from "@/lib/api";

/** The equity curve under the shared filters. One query key, so the Pay month (for the month the
 *  system began) and the curve card ask once. */
export function useEquity(qsString: string) {
  return useQuery({
    queryKey: ["pnl", "equity", qsString],
    queryFn: () => apiFetch<EquityResponse>(`/pnl/equity?${qsString}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
}
