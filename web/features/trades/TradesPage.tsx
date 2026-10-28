"use client";

import { AssessedBrowser } from "@/components/options/AssessedBrowser";
import { DrainWarning } from "@/components/options/ControlsStrip";
import { useControls } from "@/components/shell/BotCard";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { RefreshButton } from "@/components/shell/RefreshButton";
import { usePendingApprovals } from "@/features/home/NeedsYou";
import { STRATEGY_FILTERS, STRATEGY_LABEL, kindOf } from "@/lib/strategy";
import { useHydrated } from "@/lib/useHydrated";
import { useStrategyFilter } from "@/lib/useStrategyFilter";
import { HistoryView, useInFlightCount } from "./HistoryView";
import { ProposalsView } from "./ProposalsView";
import { SpreadsView } from "./SpreadsView";
import { SubmittedWatcher } from "./SubmittedWatcher";
import { todayInNewYork } from "./time";
import { useSubmittedApprovals } from "./useSubmittedApprovals";
import { useTradesDay, useTradesView } from "./useTradesView";
import { VIEW_LABEL, viewsFor } from "./views";

const SHELL = "mx-auto max-w-[1200px] px-4 py-5 md:px-7 md:py-6";

export function TradesPage() {
  const hydrated = useHydrated();
  const [strategy, setStrategy] = useStrategyFilter();
  const { submitted, markSubmitted, clearSubmitted } = useSubmittedApprovals();
  const all = usePendingApprovals("all");
  const scoped = usePendingApprovals(strategy);
  // What waits on you: pending proposals, less any whose Approve is already in flight.
  const pendingCount = scoped.data ? scoped.visible.filter((a) => !submitted.has(a.id)).length : null;
  // The count never arrives when that request failed: the default view must not wait for it forever.
  const [view, setView] = useTradesView(strategy, pendingCount, scoped.isError && !scoped.data);
  const [dayParam, setDay] = useTradesDay();
  const inFlight = useInFlightCount(strategy, submitted);
  const controls = useControls();
  const today = todayInNewYork();

  const waiting = all.data ? all.visible.filter((a) => !submitted.has(a.id)) : null;
  const strategyOptions = STRATEGY_FILTERS.map((f) => ({
    value: f,
    label: STRATEGY_LABEL[f],
    count:
      waiting === null || f === "all" || f === "spread"
        ? null
        : waiting.filter((a) => kindOf(a.strategy, a.right) === f).length || null,
  }));
  const views = viewsFor(strategy);
  const viewOptions = views.map((v) => ({
    value: v,
    label: VIEW_LABEL[v],
    count: v === "proposals" ? pendingCount : v === "history" ? inFlight || null : null,
  }));

  const heading = <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Trades</h1>;
  if (!hydrated) return <div className={SHELL}>{heading}</div>;

  return (
    <div className={SHELL}>
      <div className="flex items-center justify-between gap-3">
        {heading}
        <RefreshButton label="Refresh trades" className="-mr-2" />
      </div>
      {/* One null-rendering watcher per Approve in flight, so a failed or expired one comes back
          from any view (hooks cannot be looped, hence a component per id). */}
      {[...submitted].map(([approvalId, command]) => (
        <SubmittedWatcher key={approvalId} approvalId={approvalId} commandId={command.id} onSettled={clearSubmitted} />
      ))}
      <SegmentedControl label="Strategy" options={strategyOptions} value={strategy} onChange={setStrategy} className="mt-4" />
      {views.length > 1 && view !== null && (
        <div className="mt-4">
          <SegmentedControl label="View" appearance="chips" options={viewOptions} value={view} onChange={setView} />
        </div>
      )}
      {controls.data && !controls.data.drain_healthy && view !== "spreads" && (
        <div className="mt-4">
          <DrainWarning lastSeen={controls.data.drain_last_seen} />
        </div>
      )}
      <div className="mt-5">
        {view === null && (
          <div className="h-40 rounded-[18px] bg-surface" role="status" aria-busy="true" aria-label="Loading trades" />
        )}
        {view === "proposals" && (
          <ProposalsView strategy={strategy} submitted={submitted} onSubmitted={markSubmitted} onSettled={clearSubmitted} />
        )}
        {view === "history" && (
          <HistoryView
            strategy={strategy}
            day={dayParam ?? today}
            today={today}
            onDay={setDay}
            submitted={submitted}
            onSettled={clearSubmitted}
          />
        )}
        {view === "assessed" && <AssessedBrowser strategy={strategy} />}
        {view === "spreads" && <SpreadsView />}
      </div>
    </div>
  );
}
