"use client";

import { Callout } from "./Callout";
import { FactCard } from "./FactCard";
import { PanelShell } from "./PanelShell";
import type { TabKey } from "./types";

export function ClaudePanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
  return (
    <PanelShell
      tab="claude"
      title="Claude's role"
      dek="A second pair of eyes that writes a short, plain-English note on each gate survivor. Advisory only - it cannot open, resize, or block a trade."
      onNavigate={onNavigate}
      ties={[
        {
          tab: "gate",
          reason: "only reviews candidates the gate already approved, and can never override its verdict.",
        },
        {
          tab: "execution",
          reason: "its note rides along to Telegram next to the Approve/Reject buttons - context for the human, not a vote.",
        },
        {
          tab: "watching",
          reason: "the outcome of every trade it reviewed is logged read-only, for a human to study later.",
        },
      ]}
      files={[
        { path: "src/claude/runner.py", note: "shells out to the model and parses a structured review back" },
        { path: "src/claude/prompts/strategist.py", note: "what the model is actually shown - candidates, portfolio, universe notes" },
        { path: "src/claude/eval/", note: "the read-only outcome ledger and reconciler (see below)" },
      ]}
    >
      <p className="text-muted">
        The handful of top candidates that survive the rulebook get sent to a language model with
        the candidate&apos;s numbers, the current portfolio, and reference notes on the ticker. If
        the model is unavailable, times out, or returns something unparseable, the system just
        proceeds without its commentary; nothing waits on it.
      </p>

      <section>
        <h3 className="font-mono text-sm text-content">What comes back, every time</h3>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <FactCard tag="Verdict" tone="neutral" title="Recommendation">
            A plain-English call, e.g. &quot;wait.&quot;
          </FactCard>
          <FactCard tag="Verdict" tone="neutral" title="Confidence">
            A 0-1 score attached to the call.
          </FactCard>
          <FactCard tag="Context" tone="caution" title="Key risks">
            What could go wrong, in words.
          </FactCard>
          <FactCard tag="Context" tone="caution" title="Assignment notes">
            How likely, and what it would mean.
          </FactCard>
        </div>
      </section>

      <Callout label="Invariant, enforced by a test" tone="positive">
        Claude is invoked without direct API/tool access - headless, via a CLI call that returns
        structured JSON. It cannot call back into the system, place an order, or change a config
        value. If it goes down entirely, the pipeline ships the deterministic, gate-approved list on
        its own.
      </Callout>

      <section>
        <h3 className="font-mono text-sm text-content">The fence around learning from outcomes</h3>
        <p className="mt-1 text-muted">
          Every candidate Claude reviews gets logged - its full signal set, Claude&apos;s verdict,
          and what the deterministic rulebook would have done on its own - in a read-only outcome
          ledger. When a trade closes, a reconciler fills in what actually happened. Periodically, a
          read-only report buckets scores against real outcomes, purely so a human can ask
          &quot;is this scoring approach actually predictive&quot; and, by hand, decide whether to
          adjust <code className="font-mono">scoring_weights.yaml</code>.
        </p>
      </section>

      <Callout label="What this loop can never do" tone="caution">
        None of it can touch the rulebook, the sizing, or the scoring config on its own - a
        dedicated test fails the build if any of that code ever becomes importable from the trading
        path. There used to be a feature that auto-drafted strategy changes from this history; it
        was removed, because the signal it measured never affects a live decision, so scoring its
        &quot;accuracy&quot; didn&apos;t mean much.
      </Callout>
    </PanelShell>
  );
}
