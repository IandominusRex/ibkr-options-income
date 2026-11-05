"use client";

import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { useValueBook, waitingProposals } from "@/components/value/useValueBook";
import type { StrategyFilter } from "@/lib/strategy";
import { usePendingApprovals } from "./NeedsYou";

/** Below 1024px the needs-you column becomes this one line (DESIGN.md Layout). */
export function ProposalsBanner({ strategy }: { strategy: StrategyFilter }) {
  const { visible } = usePendingApprovals(strategy);
  const valueBook = useValueBook().data;
  if (strategy === "spread") return null;
  // The value book's waiting taps count under All and Value only (web overhaul Part 4, ruling 15).
  const value = strategy === "all" || strategy === "value" ? (waitingProposals(valueBook) ?? []) : [];
  const total = visible.length + value.length;
  if (total === 0) return null;
  const names = [
    ...visible.map((a) => `${a.underlying} ${a.right === "C" ? "call" : "put"}`),
    ...value.map((p) => `${p.symbol} ${p.kind}`),
  ]
    .slice(0, 3)
    .join(" · ");
  const valueOnly = visible.length === 0;
  const kindWord = valueOnly ? "value proposal" : "proposal";
  return (
    <Card as="div" className="mt-4 flex items-center justify-between gap-3">
      <div>
        <div className="font-bold">
          {total} {kindWord}
          {total === 1 ? "" : "s"} need{total === 1 ? "s" : ""} you
        </div>
        <div className="text-[0.8125rem] text-muted">{names}</div>
      </div>
      {valueOnly ? (
        // A jump to the Value card, which keeps the one decide flow: not the lime act (ruling 15).
        <Link
          href="#value-title"
          aria-label="Show in the Value book"
          className="inline-flex min-h-11 flex-none items-center rounded-full bg-sunk px-[18px] text-[1.0625rem] font-bold text-content transition-transform duration-[90ms] hover:bg-sunk-deep motion-safe:active:scale-[0.98]"
        >
          Show
        </Link>
      ) : (
        <Link
          href="/trades"
          aria-label="Open Trades"
          className="inline-flex min-h-11 flex-none items-center rounded-full bg-primary px-[18px] text-[1.0625rem] font-bold text-on-primary transition-transform duration-[90ms] hover:bg-primary-deep motion-safe:active:scale-[0.98]"
        >
          Open
        </Link>
      )}
    </Card>
  );
}
