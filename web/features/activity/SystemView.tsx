"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { SystemPanel, WindowControls } from "@/components/pnl/SystemPanel";
import type { SystemPerformanceResponse } from "@/components/pnl/types";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";
import { SizingRecord } from "./SizingRecord";

/**
 * System: the sizing record, then the score against outcome, under one window. Both are read-only
 * evidence for a human (the fence in CLAUDE.md): nothing here can change a limit, a size or a
 * weight. Since narrows both (the day an action was taken, the day a trade closed); Until narrows
 * the score evidence only.
 */
export function SystemView() {
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const qs = new URLSearchParams();
  if (since) qs.set("since", since);
  if (until) qs.set("until", until);

  const system = useQuery({
    queryKey: ["pnl", "system", since, until],
    queryFn: () => apiFetch<SystemPerformanceResponse>(`/pnl/system?${qs.toString()}`),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  return (
    <div className="grid gap-4">
      <section aria-label="Window" className="grid gap-2">
        <WindowControls since={since} until={until} onSinceChange={setSince} onUntilChange={setUntil} />
        <p className="text-[0.8125rem] text-muted">
          Since narrows the sizing record and the score evidence. Until narrows the score evidence only.
        </p>
      </section>
      <SizingRecord since={since || undefined} />
      <Card aria-labelledby="score-title">
        <h2 id="score-title" className="text-[1.0625rem] font-bold">
          Score against outcome
        </h2>
        <div className="mt-3">
          {system.isError && !system.data ? (
            <>
              <p className="text-sm text-muted">Could not load the score-vs-outcome report.</p>
              <p className="mt-1 text-[0.8125rem] text-muted">It tries again every 30 seconds.</p>
            </>
          ) : !system.data ? (
            <div role="status" aria-busy="true" aria-label="Loading the score report" className="h-24 rounded-xl bg-sunk" />
          ) : (
            <SystemPanel data={system.data} windowControls={false} />
          )}
        </div>
      </Card>
    </div>
  );
}
