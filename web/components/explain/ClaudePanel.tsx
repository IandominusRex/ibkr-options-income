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
      dek="A second pair of eyes - a small language model running locally on this Mac - that writes a short, plain-English verdict on each gate survivor. Advisory only - it cannot open, resize, or block a trade."
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
        { path: "src/claude/ollama_runner.py", note: "calls the local Ollama model with a fixed JSON output schema and one overall deadline" },
        { path: "src/claude/prompts/strategist.py", note: "what the model is actually shown - the numbered FACTS, the NEWS block, the rubric, the portfolio" },
        { path: "src/claude/news_context.py", note: "builds the NEWS block from keyless Google News and Yahoo headlines" },
        { path: "src/claude/ollama_tools.py", note: "the bounded research turn: up to two news searches before judging" },
        { path: "src/claude/eval/", note: "the read-only outcome ledger and reconciler (see below)" },
      ]}
    >
      <p className="text-muted">
        The handful of top candidates that survive the rulebook get sent to a local language model
        (Ollama, <code className="font-mono">qwen3.5:4b</code> by default). It never works the
        numbers out itself: Python hands it a numbered list of FACTS for each candidate (how far
        the strike is from the price, whether earnings land inside the trade, the credit against
        its fair-value floor, the IV rank) plus a NEWS block of recent headlines, and it may run up
        to two extra news searches before it judges. A short rubric tells it to default to
        &quot;sell&quot; for a gate-passing trade unless a specific fact or headline argues
        otherwise, and to name the ones it relied on. If the model is unavailable, times out, or
        returns something unparseable, the system just proceeds without its commentary; nothing
        waits on it, and the whole review is capped by one deadline so it cannot stall a scan.
      </p>

      <section>
        <h3 className="font-mono text-sm text-content">What comes back, every time</h3>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <FactCard tag="Verdict" tone="neutral" title="Sell, wait, or skip">
            One of three calls, with a 2-3 sentence plain-English summary.
          </FactCard>
          <FactCard tag="Verdict" tone="neutral" title="Evidence">
            The fact (F#) and headline (N#) ids the call relied on.
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
        The model&apos;s only tool is a read-only news search. It cannot call back into the system,
        place an order, or change a config value, and none of the news or search code can be
        imported by the rulebook, the execution path, or the strategy screens. If the model goes
        down entirely, the pipeline ships the deterministic, gate-approved list on its own.
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
