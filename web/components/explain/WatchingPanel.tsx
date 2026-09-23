"use client";

import { Callout } from "./Callout";
import { FactCard } from "./FactCard";
import { PanelShell } from "./PanelShell";
import type { TabKey } from "./types";

const TRIGGERS = [
  "Delta drift",
  "7-day DTE threshold",
  "21-DTE management point",
  "IV spike",
  "Ex-dividend assignment risk",
  "General assignment risk",
];

export function WatchingPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
  return (
    <PanelShell
      tab="watching"
      title="Watching & adjusting"
      dek="Separate from the 15-minute scan, an always-on lookout watches every open position live and can propose a rescue, or close one automatically, well before it becomes urgent."
      onNavigate={onNavigate}
      ties={[
        {
          tab: "execution",
          reason: "picks up every position the moment its order fills.",
        },
        {
          tab: "gate",
          reason: "a proposed roll is itself a new candidate - it must clear the rulebook again, under its own defensive-roll economics.",
        },
        {
          tab: "ideas",
          reason: "the wheel's adjusted cost basis feeds back into the covered-call strike gate.",
        },
      ]}
      files={[
        { path: "src/monitor/", note: "the event-driven intraday watcher (delta drift, DTE, IV spike, assignment risk)" },
        { path: "src/strategies/rolling.py", note: "income-roll vs defensive-roll economics" },
        { path: "src/execution/circuit_breakers.py", note: "daily-loss halt and drawdown halt" },
      ]}
    >
      <section>
        <h3 className="font-mono text-sm text-content">Six conditions, watched continuously</h3>
        <div className="mt-3 flex flex-wrap gap-2">
          {TRIGGERS.map((t) => (
            <span
              key={t}
              className="rounded-full border border-focus/40 px-3 py-1 font-mono text-xs text-focus"
            >
              {t}
            </span>
          ))}
        </div>
        <p className="mt-3 text-muted">
          Any trigger sends an alert explaining, in prose, what happened and why it matters - well
          before the next 15-minute scan would have noticed.
        </p>
      </section>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FactCard tag="Unchallenged" tone="positive" title="Income roll">
          Just harvesting more premium - still has to clear the normal return-on-capital and yield
          floors.
        </FactCard>
        <FactCard tag="Challenged" tone="caution" title="Defensive roll">
          Rescuing a position that moved against you - allowed a small, bounded cost, as long as it
          meaningfully reduces delta and improves the breakeven.
        </FactCard>
      </div>
      <p className="text-xs text-muted">
        Roll execution ships off by default; today rolls are alert-only until the mechanics are
        verified on a live paper account, though approving one manually still works end to end.
      </p>

      <Callout label="The seatbelt" tone="positive">
        A profit-take closes a short once 50% of its credit is captured; a loss-exit closes it once
        the cost to buy back reaches 2x the original credit, by default. A daily-loss halt and a
        drawdown halt can trip a persisted kill switch that stops all new order transmission -
        closing existing risk is still always allowed.
      </Callout>

      <FactCard tag="Wheel" tone="info" title="One thread per symbol">
        When a put gets assigned, the resulting stock position, any covered calls later sold against
        it, subsequent rolls, and the eventual close are all linked into one campaign - tracking
        cumulative premium collected and an adjusted cost basis (the assignment price minus premium
        already banked per share), so a wheel that has already collected real premium can write
        strikes below the raw assignment price without the system mistaking that for locking in a
        loss.
      </FactCard>

      <p className="text-xs text-muted">
        At 4:15pm ET, a scheduled job summarizes the day&apos;s premium cashflow, records
        today&apos;s volatility for tomorrow&apos;s IV rank, reconciles the outcome ledger, and
        snapshots positions so an overnight assignment is auto-detected the next morning.
      </p>
    </PanelShell>
  );
}
