"use client";

import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { STRATEGY_FILTERS, STRATEGY_LABEL, kindOf } from "@/lib/strategy";
import { useHydrated } from "@/lib/useHydrated";
import { useStrategyFilter } from "@/lib/useStrategyFilter";
import { MarketCard } from "@/features/market/MarketCard";
import { AccountHero } from "./AccountHero";
import { NeedsYou, usePendingApprovals } from "./NeedsYou";
import { PayCard } from "./PayCard";
import { PositionsCard } from "./PositionsCard";
import { ProposalsBanner } from "./ProposalsBanner";
import { TodayTrades } from "./TodayTrades";

export function HomePage() {
  const hydrated = useHydrated();
  const [strategy, setStrategy] = useStrategyFilter();
  const { data } = usePendingApprovals("all");
  // Counts on the switcher are pending proposals per kind: what each tab has waiting.
  const pending = data?.approvals.filter((a) => a.status === "pending") ?? null;
  const options = STRATEGY_FILTERS.map((f) => ({
    value: f,
    label: STRATEGY_LABEL[f],
    count:
      pending === null || f === "all" || f === "spread"
        ? null
        : pending.filter((a) => kindOf(a.strategy, a.right) === f).length || null,
  }));

  const heading = (
    // The page's name for heading navigation; the hero number is the visual title.
    <h1 className="sr-only">Home</h1>
  );
  if (!hydrated) return <div className="mx-auto max-w-[1200px] px-4 py-5 md:px-7 md:py-6">{heading}</div>;

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-5 md:px-7 md:py-6">
      {heading}
      <SegmentedControl label="Strategy" options={options} value={strategy} onChange={setStrategy} />
      {/* One grid, one copy of each card. From 1024px the left column spans every row and the
          right column stacks "Needs you" over "Done today"; below it the grid is a single column
          in DOM order, so Done today follows Positions and "Needs you" is the banner above. */}
      <div className="mt-5 grid items-start gap-x-6 gap-y-6 lg:grid-cols-[minmax(0,1fr)_340px] lg:grid-rows-[auto_auto_1fr]">
        <div className="min-w-0 lg:col-start-1 lg:row-span-3 lg:row-start-1">
          <AccountHero />
          <div className="lg:hidden">
            <ProposalsBanner strategy={strategy} />
          </div>
          <PayCard strategy={strategy} />
          <div className="mt-4">
            <MarketCard variant="home" />
          </div>
          <PositionsCard strategy={strategy} />
        </div>
        <div className="hidden lg:col-start-2 lg:row-start-1 lg:block">
          <NeedsYou strategy={strategy} />
        </div>
        <TodayTrades strategy={strategy} className="lg:col-start-2 lg:row-start-2" />
      </div>
    </div>
  );
}
