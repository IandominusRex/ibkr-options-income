"use client";

import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useValueOut } from "@/components/value/useValueBook";
import { apiFetch } from "@/lib/api";
import type { StrategyFilter } from "@/lib/strategy";
import { TradeCard } from "./TradeCard";
import { ACTION_LABEL, countByAction } from "./trades";
import type { DayTradeAction, DayTradesResponse } from "./types";

type Pick = "all" | DayTradeAction;

const PICKS: Pick[] = ["all", "opened", "closed", "rolled"];

/**
 * "Done today": what was opened, closed or rolled today (New York), as cards, under the same
 * strategy scope as everything below Home's hero. Filter pills narrow by what happened.
 */
export function TodayTrades({ strategy, className }: { strategy: StrategyFilter; className?: string }) {
  const [pick, setPick] = useState<Pick>("all");
  const { data, isError } = useQuery({
    queryKey: ["pnl", "day", strategy],
    queryFn: () => apiFetch<DayTradesResponse>(`/pnl/day?strategy=${strategy}`),
    refetchInterval: 60_000,
  });

  const trades = data?.trades ?? [];
  const counts = countByAction(trades);
  const visible = pick === "all" ? trades : trades.filter((t) => t.action === pick);
  const options = PICKS.map((p) => ({
    value: p,
    label: p === "all" ? "All" : ACTION_LABEL[p],
    count: p === "all" ? trades.length : counts[p],
  }));
  const spreadsOut = data?.spreads_available === false && (strategy === "all" || strategy === "spread");
  // An unread value book is not a day without value trades.
  const valueUnread = useValueOut(data?.value_available);
  const valueOut = valueUnread && (strategy === "all" || strategy === "value");

  let body: ReactNode;
  if (isError && !data) {
    body = <p className="text-sm text-muted">Today's trades are unavailable right now.</p>;
  } else if (!data) {
    body = <div className="h-24 rounded-[18px] bg-surface" role="status" aria-busy="true" aria-label="Loading today's trades" />;
  } else if (trades.length === 0 && valueOut && strategy === "value") {
    body = <p className="text-sm text-muted">The value book could not be read, so its trades are not listed.</p>;
  } else if (trades.length === 0) {
    body = <p className="text-sm text-muted">Nothing has traded yet today.</p>;
  } else {
    body = (
      <>
        <SegmentedControl label="Trade type" appearance="chips" options={options} value={pick} onChange={setPick} />
        {visible.length === 0 ? (
          <p className="mt-3 text-sm text-muted">Nothing {ACTION_LABEL[pick as DayTradeAction].toLowerCase()} today.</p>
        ) : (
          <div className="mt-3 grid gap-3">
            {visible.map((t) => (
              <TradeCard key={t.key} trade={t} />
            ))}
          </div>
        )}
      </>
    );
  }

  return (
    <section aria-labelledby="today-title" className={className}>
      <h2 id="today-title" className="mb-2.5 text-[0.8125rem] font-semibold text-muted">
        Done today{data && trades.length > 0 ? ` · ${trades.length} trade${trades.length === 1 ? "" : "s"}` : ""}
      </h2>
      {body}
      {valueOut && !(trades.length === 0 && strategy === "value") && (
        <p className="mt-3 text-[0.8125rem] text-muted">The value book could not be read, so its trades are not listed.</p>
      )}
      {spreadsOut && (
        <p className="mt-3 text-[0.8125rem] text-muted">Credit spreads are unavailable right now, so they are not listed.</p>
      )}
    </section>
  );
}
