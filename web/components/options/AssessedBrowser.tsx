"use client";

import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useId, useState } from "react";
import { Card } from "@/components/ui/Card";
import { apiFetch } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { type StrategyFilter, kindOf, matchesFilter } from "@/lib/strategy";
import { AssessedRow } from "./AssessedRow";
import type { AssessedContract, AssessedResponse, AssessedStage, ControlsResponse } from "./types";

const STAGES: AssessedStage[] = ["generator", "risk_gate", "score_floor", "dedupe", "top_n", "passed"];

const FIELD =
  "min-h-11 rounded-xl border border-control bg-surface px-3 text-base text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus";

/** "passed: 1 · risk gate: 1", in pipeline order, from the contracts actually shown. */
export function stageCounts(contracts: AssessedContract[]): string {
  const counts = new Map<string, number>();
  for (const c of contracts) counts.set(c.stage, (counts.get(c.stage) ?? 0) + 1);
  return STAGES.filter((s) => counts.has(s))
    .map((s) => `${s.replace(/_/g, " ")}: ${counts.get(s)}`)
    .join(" · ");
}

/** `initialSymbol` seeds the Symbol filter once (a link such as Research's "Sell a put" carries `?symbol=`). */
export function AssessedBrowser({
  strategy = "all",
  initialSymbol = "",
}: { strategy?: StrategyFilter; initialSymbol?: string } = {}) {
  const [stageFilter, setStageFilter] = useState<AssessedStage | "all">("all");
  const [symbolFilter, setSymbolFilter] = useState(initialSymbol);
  const stageId = useId();
  const symbolId = useId();

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

  // The drain's health drives a promoted command's receipt "stalled" state (spec §9.2 rule 3).
  // Defaults to healthy while loading so an unloaded drain never falsely reads as dead.
  const controls = useQuery({
    queryKey: ["options", "controls"],
    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const drainHealthy = controls.data?.drain_healthy ?? true;

  const filters = (
    <div className="flex flex-wrap items-end gap-3">
      <div className="grid gap-1">
        <label htmlFor={stageId} className="text-xs font-semibold tracking-[0.04em] text-muted">
          Stage
        </label>
        <select
          id={stageId}
          value={stageFilter}
          onChange={(e) => setStageFilter(e.target.value as AssessedStage | "all")}
          className={FIELD}
        >
          <option value="all">all stages</option>
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>
      <div className="grid gap-1">
        <label htmlFor={symbolId} className="text-xs font-semibold tracking-[0.04em] text-muted">
          Symbol
        </label>
        <input
          id={symbolId}
          type="text"
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
          placeholder="NVDA"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          className={clsx(FIELD, "w-32 placeholder:text-muted")}
        />
      </div>
    </div>
  );

  if (isLoading) return <p className="text-sm text-muted">Loading assessed contracts</p>;
  if (isError) return <p className="text-sm text-muted">Assessed contracts could not be loaded right now.</p>;

  const groups = (data?.groups ?? [])
    .map((g) => ({
      symbol: g.symbol,
      contracts: g.contracts.filter((c) => matchesFilter(kindOf(c.strategy, null), strategy)),
    }))
    .filter((g) => g.contracts.length > 0);
  const computed = formatDateTime(data?.computed_at);

  return (
    <div className="grid gap-4">
      {filters}
      {data?.run_id && (
        <p className="text-[0.8125rem] text-muted">
          Run {data.run_id}
          {computed ? ` · computed ${computed}` : ""}
        </p>
      )}
      {groups.length === 0 ? (
        <p className="text-sm text-muted">No assessed contracts for this run.</p>
      ) : (
        groups.map((g) => <Group key={g.symbol} symbol={g.symbol} contracts={g.contracts} drainHealthy={drainHealthy} />)
      )}
    </div>
  );
}

function Group({
  symbol,
  contracts,
  drainHealthy,
}: {
  symbol: string;
  contracts: AssessedContract[];
  drainHealthy: boolean;
}) {
  const [open, setOpen] = useState(true);
  const panelId = useId();
  return (
    <Card as="section" aria-label={`${symbol} assessed contracts`}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-11 w-full items-center justify-between gap-3 text-left"
      >
        <span className="text-[1.0625rem] font-bold">{symbol}</span>
        <span className="flex items-center gap-2">
          <span className="text-[0.8125rem] text-muted">{stageCounts(contracts)}</span>
          <ChevronDown
            size={16}
            aria-hidden="true"
            className={clsx("text-muted transition-transform duration-[180ms] ease-out motion-reduce:transition-none", open && "rotate-180")}
          />
        </span>
      </button>
      <ul id={panelId} hidden={!open} className="mt-1">
        {contracts.map((c) => (
          <AssessedRow key={c.candidate_id} contract={c} drainHealthy={drainHealthy} />
        ))}
      </ul>
    </Card>
  );
}
