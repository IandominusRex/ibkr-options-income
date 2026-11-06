"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import type { ControlsResponse } from "@/components/options/types";
import { UniverseList } from "@/components/universe/UniverseList";
import type { UniverseResponse } from "@/components/universe/types";
import { apiFetch } from "@/lib/api";

/**
 * Universe (web overhaul Part 6): a back link to Research, the title and one line on what can be changed
 * here, then one card per list, two columns from 1024px. Would own and Watchlist take add and remove
 * through `components/universe` (a would-own add confirms first, naming the put and the assignment); the
 * other two lists are set in config/universe.yaml and say so. `sectors` stays file-only.
 */
export function UniversePage() {
  const { data, isError } = useQuery({
    queryKey: ["universe"],
    queryFn: () => apiFetch<UniverseResponse>("/universe"),
  });

  // Defaults to healthy while loading, so an unloaded drain is never reported as dead.
  const { data: controls } = useQuery({
    queryKey: ["options", "controls"],
    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const drainHealthy = controls?.drain_healthy ?? true;

  let body;
  if (!data && isError) {
    body = <p className="mt-4 text-sm">The universe could not be loaded right now.</p>;
  } else if (!data) {
    body = (
      <div role="status" aria-busy="true" aria-label="Loading the universe" className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="h-48 rounded-[18px] bg-surface" />
        <div className="h-48 rounded-[18px] bg-surface" />
      </div>
    );
  } else {
    // The names being wheeled now tell the two would-own tiers apart: Wheeling or Dip-watch.
    const activelyWheeling = new Set(
      (data.lists.find((list) => list.name === "actively_wheeling")?.entries ?? []).map((entry) => entry.symbol),
    );
    body = (
      <div className="mt-4 grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
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

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4">
      <Link
        href="/research"
        className="inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-muted hover:text-content md:min-h-8"
      >
        <ChevronLeft size={16} aria-hidden="true" />
        Research
      </Link>
      <header className="mt-1">
        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Universe</h1>
        <p className="mt-1 max-w-[65ch] text-sm text-muted">
          The names the scan covers. Would own and Watchlist take add and remove here; Indexes and Actively wheeling
          are set in config/universe.yaml.
        </p>
      </header>
      {body}
    </div>
  );
}
