"use client";

import { Callout } from "./Callout";
import { PanelShell } from "./PanelShell";
import type { TabKey } from "./types";

const RUNGS: { name: string; pct: number; note: string }[] = [
  { name: "OBSERVE", pct: 25, note: "proposals only, no buttons - the default" },
  { name: "MANUAL", pct: 50, note: "every trade needs a tap" },
  { name: "WHITELIST", pct: 75, note: "trusted symbols auto-execute, the rest still need a tap" },
  { name: "FULL", pct: 100, note: "anything that clears the rulebook auto-executes" },
];

export function ExecutionPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
  return (
    <PanelShell
      tab="execution"
      title="Approval & execution"
      dek="How much happens automatically is a dial that only turns up once the account has earned it. Whatever the setting, the order that finally goes out is a limit order, re-checked one last time."
      onNavigate={onNavigate}
      ties={[
        {
          tab: "claude",
          reason: "its note is what you read alongside the Approve/Reject buttons.",
        },
        {
          tab: "gate",
          reason: "re-runs the exact same rulebook against a live quote right before transmitting.",
        },
        {
          tab: "watching",
          reason: "the moment an order fills, the intraday monitor picks the position up.",
        },
        {
          tab: "web",
          reason: "this dashboard's Approve/Reject controls drain through this identical code path, not a shortcut.",
        },
      ]}
      files={[
        { path: "src/notify/approval_service.py", note: "the Telegram daemon - buttons, commands, and the exec connection" },
        { path: "src/execution/executor.py", note: "limit-at-mid order building, qualification, and the live re-gate" },
        { path: "config/settings.yaml", note: "autonomy.rung, autonomy promotion thresholds, LIVE_TRADING" },
      ]}
    >
      <section>
        <h3 className="font-mono text-sm text-content">The autonomy ladder</h3>
        <p className="mt-1 text-muted">
          Approved candidates route to Telegram, split into topic threads so CSPs, covered calls,
          buy-to-own ideas, and account snapshots each stay readable. Four rungs decide how much is
          automatic - moving <em>up</em> requires the account to have actually demonstrated it
          works (a minimum number of real fills, a fill-rate floor, at least one automatic
          loss-reducing close having genuinely fired); moving down is instant, always.
        </p>
        <div className="mt-3 flex flex-col gap-2.5 rounded-md border border-border bg-surface p-4">
          {RUNGS.map((r) => (
            <div key={r.name} className="flex items-center gap-3">
              <div className="w-24 shrink-0 font-mono text-xs text-content">{r.name}</div>
              <div className="h-2.5 flex-1 rounded-full bg-elevated">
                <div
                  className="h-full rounded-full bg-focus"
                  style={{ width: `${r.pct}%` }}
                  aria-hidden="true"
                />
              </div>
              <div className="hidden w-72 shrink-0 text-xs text-muted sm:block">{r.note}</div>
            </div>
          ))}
          <p className="mt-1 text-xs text-muted sm:hidden">
            {RUNGS.map((r) => `${r.name}: ${r.note}`).join(". ")}
          </p>
        </div>
      </section>

      <Callout label="Paper-only shortcut, and the live backstop" tone="caution">
        On the paper account an operator can skip the evidence requirement
        (<code className="font-mono">automation.paper_skip_promotion_gate</code>) to watch the top
        rung work end to end. The switch is ignored whenever live trading is on, and only live
        fills count as evidence for a live account. When the trading service starts in live mode
        with a rung it has not earned with live fills, it drops itself back to manual and says so
        on Telegram.
      </Callout>

      <Callout label="A separate switch, not gated by the ladder" tone="positive">
        Automatically closing a losing or winning position is independent of the autonomy rung - it
        runs regardless of setting, because reducing risk should never have to wait for a human to
        be free to check their phone.
      </Callout>

      <section>
        <h3 className="font-mono text-sm text-content">Placing the order</h3>
        <p className="mt-1 text-muted">
          The executor builds a <strong className="text-focus">limit order at the mid-price</strong>{" "}
          - never a market order - rounds it to the correct tick, qualifies the contract with IBKR,
          and re-checks it against the rulebook one final time with a live quote before sending. In
          live mode a second, explicit confirmation tap is required per order. Rolls transmit as a
          single atomic two-leg combo (close the old option, open the new one, together), so there
          is never a moment of holding neither leg or both.
        </p>
      </section>

      <Callout label="Paper by default" tone="positive">
        Live orders are blocked unless <code className="font-mono">LIVE_TRADING=true</code> is
        explicitly set and the account is pointed at the live port, with a loud on-screen banner
        either way.
      </Callout>
    </PanelShell>
  );
}
