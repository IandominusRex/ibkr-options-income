"use client";

import { PanelShell } from "./PanelShell";
import { Callout } from "./Callout";
import { Tag } from "./Tag";
import type { TabKey } from "./types";
import { TAB_META } from "./types";

const CARDS: { tab: TabKey; tag: string; tone: "info" | "positive" | "caution" | "neutral"; blurb: string }[] = [
  {
    tab: "data",
    tag: "Stage 1",
    tone: "info",
    blurb:
      "What the system watches, how often it refreshes, and the research (IV, technicals, fundamentals, sentiment) run on every name.",
  },
  {
    tab: "ideas",
    tag: "Stage 2",
    tone: "info",
    blurb:
      "Turning that research into priced, concrete trades - a fair price is computed first, then candidates are generated and ranked.",
  },
  {
    tab: "gate",
    tag: "Stage 3",
    tone: "positive",
    blurb:
      "The one part with zero AI. Deterministic Python checks every candidate against hard limits, twice, before a cent moves.",
  },
  {
    tab: "claude",
    tag: "Stage 4",
    tone: "info",
    blurb:
      "A language model writes a plain-English second opinion on gate survivors. Advisory only - it cannot open or block a trade.",
  },
  {
    tab: "execution",
    tag: "Stage 5",
    tone: "info",
    blurb:
      "Telegram (or this dashboard) collects your approval, an autonomy ladder decides how much is automatic, and orders go to IBKR.",
  },
  {
    tab: "watching",
    tag: "The loop",
    tone: "caution",
    blurb:
      "Once filled, an always-on monitor watches every position and can propose rolls or trigger automatic loss/profit exits.",
  },
  {
    tab: "web",
    tag: "Sits alongside",
    tone: "neutral",
    blurb:
      "This console. Read-only over the trading database, plus one narrow write path that queues the same actions Telegram sends.",
  },
];

export function OverviewPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
  return (
    <PanelShell
      tab="overview"
      title="The system, in one pass"
      dek="An options-income pipeline for one Interactive Brokers account: it watches a list of stocks, proposes covered calls and cash-secured puts, checks every one against a hard rulebook, gets a second opinion from a language model, and only ever trades once a human (or a rule-following autopilot) has said yes."
      onNavigate={onNavigate}
      ties={[]}
      files={[
        { path: "README.md", note: "the full plain-English walkthrough this tab is adapted from" },
        { path: "ARCHITECTURE.md", note: "the technical reference, folder by folder" },
        { path: "STATUS.md", note: "what's built, what's deliberately not, and known limitations" },
      ]}
    >
      <p>
        Read it as a straight line with one loop in it. Data comes in, ideas get generated and
        priced, a deterministic rulebook decides what&apos;s even allowed, a language model adds
        commentary, a human (or an earned autopilot) approves, and the order goes out. Once a
        position is open, a separate always-on watcher takes over and can feed new candidates -
        rolls, closes - back into that same rulebook. This dashboard sits beside the whole thing,
        reading its trail and offering the same approve/reject buttons Telegram does.
      </p>

      <Callout label="The one rule that matters most" tone="positive">
        The Rules Engine (deterministic Python, no AI) is the <em>only</em> path to an order. A
        language model can write a recommendation; it can never place, resize, or wave through a
        trade. If the model is down entirely, the system keeps trading the rule-approved list
        without it.
      </Callout>

      <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
        {CARDS.map((c) => (
          <button
            key={c.tab}
            type="button"
            onClick={() => onNavigate(c.tab)}
            className="rounded-md border border-border bg-surface p-4 text-left transition-colors hover:border-focus/60"
          >
            <Tag tone={c.tone}>{c.tag}</Tag>
            <div className="mt-1 font-mono text-sm text-content">{TAB_META[c.tab].label}</div>
            <p className="mt-1 text-xs leading-relaxed text-muted">{c.blurb}</p>
          </button>
        ))}
      </div>
    </PanelShell>
  );
}
