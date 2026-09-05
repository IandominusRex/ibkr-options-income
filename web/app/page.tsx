"use client";

import { CommandPalette } from "@/components/search/CommandPalette";
import { SectorGrid } from "@/components/home/SectorGrid";
import { WatchlistTable } from "@/components/home/WatchlistTable";

export default function Home() {
  return (
    <div className="px-8 py-6">
      <h1 className="font-mono text-2xl text-content">Research</h1>
      <p className="mt-4 text-sm text-muted">
        <span className="mr-2">Search a ticker</span>
        <kbd className="rounded border border-border bg-elevated px-2 py-0.5 font-mono text-xs text-content">
          ⌘K
        </kbd>
      </p>
      <CommandPalette />

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