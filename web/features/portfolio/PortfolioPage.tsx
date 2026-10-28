"use client";

import { RefreshControl } from "@/components/portfolio/RefreshControl";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useViewParam } from "@/lib/useViewParam";
import { CalendarView } from "./CalendarView";
import { CampaignsView } from "./CampaignsView";
import { PositionsView } from "./PositionsView";
import { SummaryCard } from "./SummaryCard";
import { PORTFOLIO_VIEWS, VIEW_LABEL } from "./views";

const SHELL = "mx-auto max-w-[1200px] px-4 py-5 md:px-7 md:py-6";

/**
 * Portfolio: the Account card, then Positions, Campaigns or Calendar, the view kept in the URL.
 * The Account card sits outside the switched view, so changing view never refetches it. Refresh is
 * the page's one write (the `refresh` command), through the unchanged RefreshControl.
 */
export function PortfolioPage() {
  const [view, setView] = useViewParam(PORTFOLIO_VIEWS, "positions");
  const options = PORTFOLIO_VIEWS.map((v) => ({ value: v, label: VIEW_LABEL[v] }));
  return (
    <div className={SHELL}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Portfolio</h1>
        <RefreshControl />
      </div>
      <div className="mt-4">
        <SummaryCard />
      </div>
      <div className="mt-4">
        <SegmentedControl label="View" appearance="chips" options={options} value={view} onChange={setView} />
      </div>
      <div className="mt-5">
        {view === "positions" && <PositionsView />}
        {view === "campaigns" && <CampaignsView />}
        {view === "calendar" && <CalendarView />}
      </div>
    </div>
  );
}
