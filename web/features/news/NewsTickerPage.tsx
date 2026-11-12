"use client";

import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import { RefreshButton } from "@/components/shell/RefreshButton";
import { BriefRequest } from "@/components/news/BriefRequest";
import { NewsTicker } from "@/components/news/NewsTicker";

// A link to another page, drawn like the secondary button (Research's LINK). Never lime.
const LINK =
  "inline-flex min-h-11 items-center justify-center rounded-full bg-sunk px-[18px] text-[1.0625rem] font-bold text-content hover:bg-sunk-deep";

/**
 * One name's news (web overhaul Part 7): the Stock and Research frame with a back link to News, the
 * ticker as the title, then the brief request, a link to the name's stock page and Refresh. The body
 * (`components/news/NewsTicker`) reads; the brief request is the page's one write, a `news_brief`
 * command the news process drains (unchanged).
 */
export function NewsTickerPage({ symbol }: { symbol: string }) {
  const sym = symbol.toUpperCase();
  return (
    <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4">
      <Link
        href="/news"
        className="inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-muted hover:text-content md:min-h-8"
      >
        <ChevronLeft size={16} aria-hidden="true" />
        News
      </Link>
      <header className="mt-1 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-extrabold tracking-[-0.015em]">{sym}</h1>
          <p className="mt-1 text-sm text-muted">The latest brief on this name, its notes and the stories the news service grouped.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link href={`/stock/${encodeURIComponent(sym)}`} className={LINK}>
            Stock page
          </Link>
          <RefreshButton label={`Refresh ${sym} news`} />
        </div>
      </header>
      <div className="mt-4">
        <BriefRequest symbol={sym} />
      </div>
      <div className="mt-6 grid min-w-0 max-w-[820px] grid-cols-1 gap-4">
        <NewsTicker symbol={sym} />
      </div>
    </div>
  );
}
