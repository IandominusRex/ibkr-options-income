"use client";

import { RefreshButton } from "@/components/shell/RefreshButton";
import { CalendarColumn } from "@/components/news/CalendarColumn";
import { NewsFeed } from "@/components/news/NewsFeed";
import { MarketCard } from "@/features/market/MarketCard";

/**
 * News (web overhaul Part 7): the Stock and Research frame. The title with Refresh at the right, the
 * Market card full width, then two columns from 1024px: the feed on the left and the week's calendar
 * in a 340px column on the right. The DOM order is the phone order. It reads only: the news service
 * writes every post, and nothing here trades.
 */
export function NewsPage() {
  return (
    <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4" data-testid="news-page">
      <header className="mt-1 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-extrabold tracking-[-0.015em]">News</h1>
          <p className="mt-1 text-sm text-muted">What moved, what is scheduled this week, and what the news service made of it. Nothing here trades.</p>
        </div>
        <RefreshButton label="Refresh the news" />
      </header>

      <div className="mt-6">
        <MarketCard variant="news" />
      </div>

      <div className="mt-6 grid items-start gap-x-6 gap-y-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid min-w-0 grid-cols-1">
          <NewsFeed />
        </div>
        <div className="grid min-w-0 grid-cols-1">
          <CalendarColumn />
        </div>
      </div>
    </div>
  );
}
