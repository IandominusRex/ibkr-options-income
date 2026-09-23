"use client";

import { Callout } from "./Callout";
import { FactCard } from "./FactCard";
import { PanelShell } from "./PanelShell";
import type { TabKey } from "./types";

export function DataPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
  return (
    <PanelShell
      tab="data"
      title="Data in"
      dek="The shopping list, how often it gets checked, and the research done on every name before anyone proposes a trade."
      onNavigate={onNavigate}
      ties={[
        {
          tab: "ideas",
          reason: "every number gathered here - IV, technicals, fundamentals, sentiment - is what the generators price a trade against.",
        },
        {
          tab: "claude",
          reason: "the same research rides along, read-only, into the reasoning prompt as background context.",
        },
      ]}
      files={[
        { path: "config/universe.yaml", note: "the watchlist / would_own / actively_wheeling tiers" },
        { path: "src/orchestrator/scan.py", note: "the 15-minute loop and its materiality gate" },
        { path: "src/analytics/", note: "IV, technicals, fundamentals, liquidity, sentiment, macro" },
      ]}
    >
      <section>
        <h3 className="font-mono text-sm text-content">The shopping list - three tiers of eagerness</h3>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <FactCard tag="Tier 1" tone="caution" title="watchlist">
            Covered-call candidates only, and only for names already owned.
          </FactCard>
          <FactCard tag="Tier 2" tone="info" title="would_own">
            Names it&apos;s genuinely fine to get assigned via a cash-secured put.
          </FactCard>
          <FactCard tag="Tier 3" tone="positive" title="actively_wheeling">
            The core subset of would_own, checked on every single 15-minute cycle.
          </FactCard>
        </div>
        <p className="mt-3 text-muted">
          Everything else in would_own is &quot;dip-watch&quot;: only pulled in after a real price
          drop, so the system isn&apos;t re-checking option chains on names that haven&apos;t
          moved.
        </p>
      </section>

      <section>
        <h3 className="font-mono text-sm text-content">Refreshing, every 15 minutes</h3>
        <div className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-4">
          {[
            { n: "0.5%", l: "move re-fetches actively_wheeling" },
            { n: "2%", l: "rally re-fetches a held stock" },
            { n: "3%", l: "drop re-fetches dip-watch" },
            { n: "120m", l: "staleness safety-net refresh" },
          ].map((s) => (
            <div key={s.l} className="bg-surface p-3">
              <div className="font-mono text-lg text-focus">{s.n}</div>
              <div className="mt-1 text-[11px] leading-snug text-muted">{s.l}</div>
            </div>
          ))}
        </div>
        <p className="mt-3 text-muted">
          IBKR caps concurrent market-data lines at roughly 100, so fetching every chain every
          cycle simply isn&apos;t an option - each symbol is re-fetched only when something about
          it actually changed enough to matter.
        </p>
      </section>

      <Callout label="The research bench, in one pass" tone="info">
        For every name under consideration: is implied volatility rich right now relative to its
        own history (IV rank, and the IV-vs-realized-vol gap)? Is the stock trending or choppy
        (technicals)? Are the company&apos;s finances sound (fundamentals)? Can you actually get a
        fair fill (liquidity)? What&apos;s the crowd&apos;s mood, and what&apos;s the broad market
        doing (sentiment, macro)? None of this decides anything by itself - it&apos;s all read by
        the next stage.
      </Callout>
    </PanelShell>
  );
}
