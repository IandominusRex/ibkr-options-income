"use client";

import { LedgerOverview } from "@/components/ledger/LedgerOverview";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useViewParam } from "@/lib/useViewParam";
import { FillsView } from "./FillsView";
import { PayView } from "./PayView";
import { SystemView } from "./SystemView";
import { ACTIVITY_VIEWS, VIEW_LABEL } from "./views";

const SHELL = "mx-auto max-w-[1200px] px-4 py-5 md:px-7 md:py-6";

/**
 * Activity: what the money did and whether the records agree, in four views kept in the URL. Only
 * the chosen view mounts, so the other views' lists are not asked for until they are opened.
 */
export function ActivityPage() {
  const [view, setView] = useViewParam(ACTIVITY_VIEWS, "pay");
  const options = ACTIVITY_VIEWS.map((v) => ({ value: v, label: VIEW_LABEL[v] }));
  return (
    <div className={SHELL}>
      <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Activity</h1>
      <div className="mt-4">
        <SegmentedControl label="View" appearance="chips" options={options} value={view} onChange={setView} />
      </div>
      <div className="mt-5">
        {view === "pay" && <PayView />}
        {view === "ledger" && <LedgerOverview />}
        {view === "fills" && <FillsView />}
        {view === "system" && <SystemView />}
      </div>
    </div>
  );
}
