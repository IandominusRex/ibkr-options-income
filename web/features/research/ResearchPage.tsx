"use client";

import Link from "next/link";
import { Search } from "lucide-react";
import { SectorGrid } from "@/components/home/SectorGrid";
import { WatchlistTable } from "@/components/home/WatchlistTable";
import { Button } from "@/components/ui/Button";
import { openSearch } from "@/lib/search";
import { TopOpportunities } from "./TopOpportunities";

// A link to another page, drawn like the secondary button (OpportunityCard's LINK). Never lime.
const LINK =
  "inline-flex min-h-11 items-center justify-center rounded-full bg-sunk px-[18px] text-[1.0625rem] font-bold text-content hover:bg-sunk-deep";

/**
 * Research (web overhaul Part 6): the title with Search (it opens the console's one palette) and a link to
 * Universe, then Top opportunities, then two columns from 1024px: Your watchlist on the left and the
 * Sectors card in a 340px column on the right. The DOM order is the phone order. It reads and links; its
 * only write is the per-user watchlist's add and remove (research.db, no order consequence).
 */
export function ResearchPage() {
  return (
    <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4">
      <header className="mt-1 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Research</h1>
          <p className="mt-1 text-sm text-muted">What the value book would buy, the names you follow, and how each sector is doing.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={openSearch} aria-keyshortcuts="Meta+K Control+K">
            <Search aria-hidden="true" size={18} />
            Search
          </Button>
          <Link href="/research/universe" className={LINK}>
            Universe
          </Link>
        </div>
      </header>

      <section aria-labelledby="top-title" className="mt-6">
        <h2 id="top-title" className="text-[1.0625rem] font-bold">
          Top opportunities
        </h2>
        <p className="mt-1 text-[0.8125rem] text-muted">The value book&apos;s names on each list, Ready first. Python&apos;s gates decide; nothing here trades.</p>
        <div className="mt-3">
          <TopOpportunities />
        </div>
      </section>

      <div className="mt-6 grid items-start gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid min-w-0 grid-cols-1">
          <WatchlistTable />
        </div>
        <div className="grid min-w-0 grid-cols-1">
          <SectorGrid />
        </div>
      </div>
    </div>
  );
}
