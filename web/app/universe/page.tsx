"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { ControlsResponse } from "@/components/options/types";
import { UniverseList } from "@/components/universe/UniverseList";
import type { UniverseResponse } from "@/components/universe/types";

export default function UniversePage() {
  const { data, isLoading } = useQuery({
    queryKey: ["universe"],
    queryFn: () => apiFetch<UniverseResponse>("/universe"),
  });

  // Same self-fetch pattern ApprovalDetailCard/AssessedBrowser use for
  // drainHealthy: defaults to true while loading so an unloaded drain is
  // never falsely reported as dead.
  const { data: controls } = useQuery({
    queryKey: ["options", "controls"],
    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const drainHealthy = controls?.drain_healthy ?? true;

  if (isLoading || !data) {
    return (
      <div className="px-8 py-6">
        <h1 className="font-mono text-2xl text-content">Universe</h1>
        <p className="mt-4 text-sm text-muted">Loading</p>
      </div>
    );
  }

  // The symbols currently being actively wheeled, used to tell the two
  // would_own tiers apart at a glance: "wheeling" vs "dip-watch" (pre-M7
  // behaviour, restored in UniverseList). Passed to every list instance;
  // UniverseList only uses it for the would_own section.
  const activelyWheeling = new Set(
    (data.lists.find((list) => list.name === "actively_wheeling")?.entries ?? []).map(
      (entry) => entry.symbol,
    ),
  );

  return (
    <div className="px-8 py-6">
      <header className="mb-8">
        <h1 className="font-mono text-2xl text-content">Universe</h1>
        <p className="mt-1 text-sm text-muted">
          The scan universe. Watchlist and would-own accept add and remove; indexes and
          actively wheeling are managed in config/universe.yaml.
        </p>
      </header>

      {data.lists.map((list) => (
        <UniverseList
          key={list.name}
          list={list}
          sectors={data.sectors}
          strikeBands={data.strike_bands}
          drainHealthy={drainHealthy}
          activelyWheeling={activelyWheeling}
        />
      ))}
    </div>
  );
}
