"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { AssessedRow } from "./AssessedRow";
import { EmptyState } from "./EmptyState";
import type { AssessedResponse, AssessedStage, ControlsResponse } from "./types";

const STAGES: AssessedStage[] = [
  "generator",
  "risk_gate",
  "score_floor",
  "dedupe",
  "top_n",
  "passed",
];

export function AssessedBrowser() {
  const [stageFilter, setStageFilter] = useState<AssessedStage | "all">("all");
  const [symbolFilter, setSymbolFilter] = useState("");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["options", "assessed", stageFilter, symbolFilter],
    queryFn: () => {
      const params = new URLSearchParams({ run: "latest" });
      if (stageFilter !== "all") params.set("stage", stageFilter);
      if (symbolFilter.trim()) params.set("symbol", symbolFilter.trim().toUpperCase());
      return apiFetch<AssessedResponse>(`/options/assessed?${params.toString()}`);
    },
    placeholderData: (prev) => prev,
  });

  // Same pattern as <ApprovalsList/>: the drain's health drives a promoted
  // command's receipt "stalled" state (spec §9.2 rule 3). Defaults to healthy
  // while loading so an unloaded drain never falsely reads as dead.
  const controls = useQuery({
    queryKey: ["options", "controls"],
    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const drainHealthy = controls.data?.drain_healthy ?? true;

  if (isLoading) {
    return <p className="text-sm text-muted">Loading assessed contracts</p>;
  }
  if (isError) {
    return <p className="text-sm text-muted">Could not load assessed contracts</p>;
  }

  const groups = data?.groups ?? [];
  if (groups.length === 0) {
    return (
      <div className="space-y-4">
        <Filters
          stageFilter={stageFilter}
          setStageFilter={setStageFilter}
          symbolFilter={symbolFilter}
          setSymbolFilter={setSymbolFilter}
        />
        <EmptyState text="No assessed contracts for this run." />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Filters
        stageFilter={stageFilter}
        setStageFilter={setStageFilter}
        symbolFilter={symbolFilter}
        setSymbolFilter={setSymbolFilter}
      />
      {data?.run_id && (
        <p className="text-xs text-muted">
          Run {data.run_id}
          {data.computed_at ? ` - computed ${data.computed_at.slice(0, 19)}Z` : ""}
        </p>
      )}
      {groups.map((g) => (
        <Group key={g.symbol} group={g} drainHealthy={drainHealthy} />
      ))}
    </div>
  );
}

function Filters({
  stageFilter,
  setStageFilter,
  symbolFilter,
  setSymbolFilter,
}: {
  stageFilter: AssessedStage | "all";
  setStageFilter: (s: AssessedStage | "all") => void;
  symbolFilter: string;
  setSymbolFilter: (s: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="text-xs text-muted">Stage</label>
      <select
        value={stageFilter}
        onChange={(e) => setStageFilter(e.target.value as AssessedStage | "all")}
        className="rounded border border-border bg-surface px-2 py-1 text-xs text-content"
      >
        <option value="all">all</option>
        {STAGES.map((s) => (
          <option key={s} value={s}>
            {s.replace(/_/g, " ")}
          </option>
        ))}
      </select>
      <label className="text-xs text-muted">Symbol</label>
      <input
        type="text"
        value={symbolFilter}
        onChange={(e) => setSymbolFilter(e.target.value)}
        placeholder="filter"
        className="w-24 rounded border border-border bg-surface px-2 py-1 text-xs text-content"
      />
    </div>
  );
}

function Group({
  group,
  drainHealthy,
}: {
  group: AssessedResponse["groups"][number];
  drainHealthy: boolean;
}) {
  const [open, setOpen] = useState(true);
  const counts = Object.entries(group.counts)
    .filter(([, n]) => n > 0)
    .map(([s, n]) => `${s.replace(/_/g, " ")}: ${n}`)
    .join(" - ");

  return (
    <div className="rounded-md border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-4 py-2 text-left"
      >
        <span className="font-mono text-sm text-content">{group.symbol}</span>
        <span className="text-xs text-muted">{counts}</span>
      </button>
      {open && (
        <ul className="divide-y divide-border border-t border-border">
          {group.contracts.map((c) => (
            <AssessedRow key={c.candidate_id} contract={c} drainHealthy={drainHealthy} />
          ))}
        </ul>
      )}
    </div>
  );
}