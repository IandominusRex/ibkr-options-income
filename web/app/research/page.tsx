"use client";

import { SectorGrid } from "@/components/home/SectorGrid";
import { WatchlistTable } from "@/components/home/WatchlistTable";
import { TopOpportunities } from "@/features/research/TopOpportunities";
import { openSearch } from "@/lib/search";

export default function Home() {
  return (
    <div className="px-8 py-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="font-mono text-2xl text-content">Research</h1>
        <button
          type="button"
          onClick={openSearch}
          className="flex items-center gap-2 rounded border border-border bg-surface px-3 py-1.5 text-sm text-muted hover:text-content focus-visible:ring-focus"
        >
          <span>Search a ticker</span>
          <kbd className="rounded border border-border bg-elevated px-2 py-0.5 font-mono text-xs text-content">
            ⌘K
          </kbd>
        </button>
      </div>

      <section className="mt-10">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">Top opportunities</h2>
        <TopOpportunities />
      </section>

      <section className="mt-10">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">Watchlist</h2>
        <WatchlistTable />
      </section>

      <section className="mt-10">
        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">
          Sectors by IV rank
        </h2>
        <SectorGrid />
      </section>
    </div>
  );
}