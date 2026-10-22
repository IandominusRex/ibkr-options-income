"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { BotCard } from "@/components/shell/BotCard";
import { SystemStatusCard } from "@/components/shell/SystemStatusCard";
import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { Card } from "@/components/ui/Card";
import { TargetCard } from "@/features/more/TargetCard";

const LINKS = [
  { href: "/research", label: "Research", sub: "Search, watchlist, sectors, universe" },
  { href: "/research/universe", label: "Universe", sub: "The names the scan covers; edit would-own and watchlist" },
  { href: "/news", label: "News", sub: "Feed, calendar and ticker briefs" },
  { href: "/ledger", label: "Ledger", sub: "Broker trades and per-ticker roll-ups" },
  { href: "/explain", label: "How it works", sub: "The pipeline in plain English" },
  { href: "/more/claude", label: "What Claude knows", sub: "The market picture and what each Claude call reads" },
  { href: "/ledger/import", label: "Import a statement", sub: "Upload an IBKR activity CSV" },
];

export default function MorePage() {
  return (
    <div className="mx-auto max-w-[720px] px-4 py-6 md:px-7">
      <h1 className="text-2xl font-extrabold tracking-[-0.015em]">More</h1>

      <section className="mt-6" aria-label="Bot">
        <BotCard />
      </section>

      <Card className="mt-6">
        <h2 className="text-[1.0625rem] font-bold">Theme</h2>
        <p className="mt-1 text-sm text-muted">Light is the default. Follow OS switches with your device.</p>
        <div className="mt-3">
          <ThemeToggle />
        </div>
      </Card>

      <TargetCard />

      <Card className="mt-4" as="div">
        <ul>
          {LINKS.map((l) => (
            <li key={l.href} className="border-t border-border first:border-t-0">
              <Link href={l.href} className="flex items-center justify-between gap-3 py-3">
                <span>
                  <span className="block font-bold">{l.label}</span>
                  <span className="block text-[0.8125rem] text-muted">{l.sub}</span>
                </span>
                <ChevronRight aria-hidden="true" size={18} className="text-muted" />
              </Link>
            </li>
          ))}
        </ul>
      </Card>

      <section className="mt-4" aria-label="System status">
        <SystemStatusCard />
      </section>

      {/* The chart library's licence asks for a link to tradingview.com somewhere users can reach;
          the chart's own logo is off so it never sits on the line. */}
      <Card className="mt-4" as="section" aria-labelledby="credits-title">
        <h2 id="credits-title" className="text-[1.0625rem] font-bold">
          Credits
        </h2>
        <p className="mt-1 text-sm text-muted">
          Charts are drawn with Lightweight Charts, made by{" "}
          <a
            href="https://www.tradingview.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="font-semibold text-content underline underline-offset-2"
          >
            TradingView<span className="sr-only"> (opens in a new tab)</span>
          </a>
          .
        </p>
      </Card>
    </div>
  );
}
