"use client";

import { useState } from "react";
import { CommandPalette } from "@/components/search/CommandPalette";
import { SectorGrid } from "@/components/home/SectorGrid";
import { WatchlistTable } from "@/components/home/WatchlistTable";

export default function Home() {
  const [searchOpen, setSearchOpen] = useState(false);

  return (
    <div className="px-8 py-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="font-mono text-2xl text-content">Research</h1>
        <button
          type="button"
          onClick={() => setSearchOpen(true)}
          className="flex items-center gap-2 rounded border border-border bg-surface px-3 py-1.5 text-sm text-muted hover:text-content focus-visible:ring-focus"
        >
          <span>Search a ticker</span>
          <kbd className="rounded border border-border bg-elevated px-2 py-0.5 font-mono text-xs text-content">
            ⌘K
          </kbd>
        </button>
      </div>
      <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} />

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