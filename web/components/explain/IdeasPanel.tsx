"use client";

import { Callout } from "./Callout";
import { FactCard } from "./FactCard";
import { PanelShell } from "./PanelShell";
import type { TabKey } from "./types";

export function IdeasPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
  return (
    <PanelShell
      tab="ideas"
      title="Finding trades"
      dek="Writing a fair price for itself first, then turning research into concrete, priced candidates, then ranking them."
      onNavigate={onNavigate}
      ties={[
        {
          tab: "data",
          reason: "every candidate here is built from the IV, technicals, and liquidity numbers gathered upstream.",
        },
        {
          tab: "gate",
          reason: "nothing decided here is binding - every ranked candidate still has to clear the rulebook next.",
        },
      ]}
      files={[
        { path: "src/analytics/fair_value.py", note: "the ideal strike band and the minimum-credit fair-value floor" },
        { path: "src/strategies/", note: "the covered-call, CSP, roll, and buy-to-own generators" },
        { path: "src/engine/scoring.py", note: "the blended 0-100 score and rank" },
      ]}
    >
      <Callout label="The price tag it writes for itself" tone="info">
        Before shopping: an expected move (spot price x implied volatility x the square root of
        time), an ideal strike band inside it, and a minimum credit - the option&apos;s fair value
        at realized volatility, plus a required edge on top. &quot;A put around here, for at least
        this much, is a fair deal - anything cheaper isn&apos;t worth the risk.&quot; Every contract
        actually offered gets compared against that tag.
      </Callout>

      <section>
        <h3 className="font-mono text-sm text-content">Four generators</h3>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FactCard tag="On stock you own" tone="positive" title="Covered calls">
            Find the best strike/expiry to sell against shares already held.
          </FactCard>
          <FactCard tag="On stock you'd own" tone="info" title="Cash-secured puts">
            Strikes that pay well without excessive assignment risk, sized to the room the account
            actually has left - never the theoretical max lot.
          </FactCard>
          <FactCard tag="On a challenged short" tone="caution" title="Rolls">
            For existing short options nearing expiry or drifting in-the-money, propose the best
            replacement trade.
          </FactCard>
          <FactCard tag="Before you own it" tone="neutral" title="Buy-to-own">
            Stocks worth buying specifically so calls can be written against them later, filtered
            to only the strongest handful.
          </FactCard>
        </div>
        <p className="mt-3 text-muted">
          Every generator keeps a record of contracts it considered and rejected, tagged with every
          reason it failed - a quiet scan still shows its work.
        </p>
      </section>

      <FactCard tag="Ranking" tone="neutral" title="Scoring, 0-100">
        Each candidate gets normalized scores across IV rank, technicals, fundamentals, liquidity,
        and sentiment, blended by configurable weights into one number. Anything below a minimum
        score floor, or that loses to a better strike on the same name, is dropped - and why is
        recorded rather than silently disappearing.
      </FactCard>

      <p className="text-xs text-muted">
        A separate, standalone backtester replays these same strategies over historical prices,
        isolated from everything live - it answers &quot;how would this have done historically,&quot;
        not &quot;should I trade now.&quot;
      </p>
    </PanelShell>
  );
}
