"use client";

import { Callout } from "./Callout";
import { PanelShell } from "./PanelShell";
import type { TabKey } from "./types";

const PROPOSABLE = [
  "Approve / reject a pending trade",
  "Promote an assessed candidate",
  "Request a roll",
  "Halt / resume the system",
  "Change the autonomy rung",
  "Edit the watchlist / would-own universe",
];

export function WebLayerPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
  return (
    <PanelShell
      tab="web"
      title="This dashboard"
      dek="A second window onto the same system Telegram already runs - not a second system. It reads everything, and writes through exactly one narrow door."
      onNavigate={onNavigate}
      ties={[
        {
          tab: "execution",
          reason: "every Approve, Reject, Promote, or Roll button here queues a command that drains through the identical handler Telegram's buttons call.",
        },
        {
          tab: "gate",
          reason: "the Options console's Assessed tab shows the same pass/reject audit trail this tab describes in words.",
        },
      ]}
      files={[
        { path: "src/api/", note: "the FastAPI backend - its own process, no IBKR connection, no clientId" },
        { path: "src/api/commands.py", note: "the one table (app_commands) this whole app is allowed to write" },
        { path: "src/notify/command_drain.py", note: "reads pending commands and applies them via the same handlers Telegram uses" },
      ]}
    >
      <p className="text-muted">
        The web console you&apos;re looking at right now talks to a FastAPI backend (
        <code className="font-mono">src/api/</code>) that runs as its own process, with no IBKR
        connection and no clientId - it cannot reach the broker even if something in it were
        compromised. It exists to give you a second, richer surface onto the exact same system
        Telegram already runs, reachable over a private network rather than a phone.
      </p>

      <Callout label="Two database handles, on purpose" tone="positive">
        Every read in this app - portfolio, P&amp;L, the risk-gate audit trail, approvals, orders,
        fills - goes through a connection SQLite itself opens read-only; an accidental write raises
        an error at the database layer, not by convention. A second, separate handle can write, and
        only to one table: <code className="font-mono">app_commands</code>. Nothing else in this
        codebase is allowed to import that write handle - a test enforces it.
      </Callout>

      <section>
        <h3 className="font-mono text-sm text-content">Every click is a proposal, never a shortcut</h3>
        <p className="mt-1 text-muted">
          Clicking Approve here doesn&apos;t approve anything directly. It inserts a row into{" "}
          <code className="font-mono">app_commands</code> with status <em>pending</em>. A background
          loop inside the same process that holds the live IBKR connection - the Telegram bot&apos;s
          process - picks that row up, usually within a couple of seconds, and applies it by calling
          the exact same function Telegram&apos;s own Approve button calls.
        </p>
      </section>

      <section>
        <h3 className="font-mono text-sm text-content">What it can propose</h3>
        <div className="mt-3 flex flex-wrap gap-2">
          {PROPOSABLE.map((p) => (
            <span
              key={p}
              className="rounded-full border border-focus/40 px-3 py-1 font-mono text-xs text-focus"
            >
              {p}
            </span>
          ))}
        </div>
        <p className="mt-3 text-muted">
          Every one of those is a command the drain applies through the deterministic path described
          in the other tabs - this console has no code path that gates, sizes, or sends an order on
          its own.
        </p>
      </section>
    </PanelShell>
  );
}
