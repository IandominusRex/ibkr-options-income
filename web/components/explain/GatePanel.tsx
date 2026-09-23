"use client";

import { Callout } from "./Callout";
import { FactCard } from "./FactCard";
import { PanelShell } from "./PanelShell";
import { RangeBar } from "./RangeBar";
import type { TabKey } from "./types";

export function GatePanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
  return (
    <PanelShell
      tab="gate"
      title="The risk gate"
      dek="The compliance officer that can't be talked out of anything - not even by Claude. Pure, deterministic Python, and the only path to an order."
      onNavigate={onNavigate}
      ties={[
        {
          tab: "ideas",
          reason: "every ranked candidate arrives here before anything else sees it.",
        },
        {
          tab: "claude",
          reason: "only what survives this gate is ever shown to the model - it never reviews a rejected candidate.",
        },
        {
          tab: "execution",
          reason: "the exact same checks run a second time, against a fresh live quote, right before the order is sent.",
        },
      ]}
      files={[
        { path: "src/engine/risk_engine.py", note: "the gate itself - two passes, zero LLM calls" },
        { path: "config/risk_limits.yaml", note: "every threshold below, tunable without a code change" },
        { path: "src/storage/risk_verdicts.py", note: "the audit trail of every contract assessed and why" },
      ]}
    >
      <Callout label="No AI involved, anywhere in this box" tone="positive">
        <code className="font-mono">src/engine/risk_engine.py</code> is plain deterministic Python.
        It has no code path that calls a language model, and nothing upstream of it - not Claude,
        not a hallucinated number - can reach an order without passing through it.
      </Callout>

      <section>
        <h3 className="font-mono text-sm text-content">Strike targeting, drawn to scale</h3>
        <div className="mt-3 flex flex-col gap-3 rounded-md border border-border bg-surface p-4">
          <RangeBar
            label="CSP delta target"
            lowPct={20}
            highPct={35}
            lowText="0.20"
            highText="0.35"
            scaleLeft="0.0 (deep OTM)"
            scaleRight="1.0 (deep ITM)"
          />
          <RangeBar
            label="CC delta target"
            lowPct={20}
            highPct={35}
            lowText="0.20"
            highText="0.35"
            scaleLeft="0.0 (deep OTM)"
            scaleRight="1.0 (deep ITM)"
          />
          <RangeBar
            label="DTE window"
            lowPct={12}
            highPct={47}
            lowText="7d"
            highText="28d"
            scaleLeft="0d"
            scaleRight="60d"
          />
        </div>
      </section>

      <section>
        <h3 className="font-mono text-sm text-content">What it checks, cumulatively across the whole account</h3>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <FactCard tag="Feasibility" tone="info" title="Cash reserve comes off first">
            20% of available cash, or a fixed floor, whichever is larger - puts may only use what
            remains.
          </FactCard>
          <FactCard tag="Concentration" tone="info" title="Measured in risk units, not dollars">
            collateral x IV x sqrt(days-to-expiry / 365) - a calm $65k position and a wild $15k one
            are compared fairly. Per-ticker and per-sector caps apply.
          </FactCard>
          <FactCard tag="Deliberateness" tone="info" title="Two large-position slots">
            At most two names at a time may exceed the standard per-ticker cap, so a deliberate
            big bet is possible without the whole book drifting oversized.
          </FactCard>
          <FactCard tag="The real floor" tone="positive" title="The income gate">
            The credit must beat the option&apos;s Black-Scholes fair value (at realized vol) by a
            required edge. Return-on-capital and annualized-yield minimums exist only as a noise
            filter underneath it.
          </FactCard>
          <FactCard tag="Timing" tone="caution" title="Earnings blackout">
            No new short premium within a configured number of days of the next earnings date.
          </FactCard>
          <FactCard tag="Richness" tone="info" title="IV-rank & IV/realized-vol floors">
            Sell only when implied volatility is high relative to its own history and rich versus
            what the stock has actually been doing.
          </FactCard>
        </div>
      </section>

      <Callout label="Checked twice" tone="info">
        Once when the candidate is ranked, and again immediately before the order transmits,
        against a fresh live quote - so a price that drifted between the scan and the send
        can&apos;t slip a trade through on a stale number.
      </Callout>

      <FactCard tag="Audit trail" tone="neutral" title="Nothing vanishes silently">
        Every contract this gate looks at - pass or reject, and why - is written to an audit table.
        A rejection is never just &quot;no&quot;; it&apos;s a specific reason (IV rank too low, delta
        outside the band, concentration cap hit, a better strike on the same name already took the
        shared budget, and so on), which is what makes it possible to answer &quot;why didn&apos;t
        this trade get proposed&quot; after the fact.
      </FactCard>
    </PanelShell>
  );
}
