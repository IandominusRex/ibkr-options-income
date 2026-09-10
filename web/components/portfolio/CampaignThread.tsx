"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { UNKNOWN } from "@/lib/format";
import { Money } from "./Money";
import type { CampaignLeg, CampaignSummary } from "./types";

function Field({
  label,
  testId,
  children,
}: {
  label: string;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1" data-testid={testId}>
      <span className="text-xs text-muted">{label}</span>
      {children}
    </div>
  );
}

/**
 * One leg of a `CampaignThread`, known or not. A leg whose `CandidateRow` was
 * pruned still renders (`known: false`) - `right`/`strike`/`expiry` come back
 * null in that case, so this renders a distinct "leg unavailable" row keyed
 * on `candidate_id` rather than trying to format nulls as a contract label.
 */
function CampaignLegRow({ leg }: { leg: CampaignLeg }) {
  if (!leg.known) {
    return (
      <li
        className="flex items-center justify-between gap-4 px-4 py-2 text-xs"
        data-testid="campaign-leg"
      >
        <span className="hatch text-unknown">Leg unavailable</span>
        <span className="font-mono text-muted">{leg.candidate_id}</span>
      </li>
    );
  }

  return (
    <li
      className="flex items-center justify-between gap-4 px-4 py-2 text-xs"
      data-testid="campaign-leg"
    >
      <span className="font-mono text-content">
        {leg.strategy} {leg.right ?? UNKNOWN}{" "}
        {leg.strike != null ? leg.strike.toFixed(2) : UNKNOWN}
      </span>
      <span className="text-muted">{leg.expiry ?? UNKNOWN}</span>
    </li>
  );
}

/**
 * One campaign thread: the symbol and its rolled-up financials on one line
 * collapsed, expanding to its legs in order - the shape a Telegram message
 * cannot produce. Pure and prop-driven like `PositionGroup`; `CampaignsPanel`
 * fetches the list and renders one of these per campaign.
 *
 * Each thread owns its own expand/collapse state (`useState`, not lifted),
 * so opening one never affects another. This differs deliberately from
 * `ChecksSection`, which allows only one category open at a time - nothing
 * in the brief asks for mutual exclusion between campaigns, and a reader
 * comparing two threads needs both open at once.
 */
export function CampaignThread({ campaign }: { campaign: CampaignSummary }) {
  const [isOpen, setIsOpen] = useState(false);
  const legCount = campaign.legs.length;

  return (
    <div className="rounded-md border border-border bg-surface" data-testid="campaign-thread">
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((open) => !open)}
        className="flex w-full flex-wrap items-center justify-between gap-4 px-4 py-3 text-left"
      >
        <span className="font-mono text-sm text-content">{campaign.symbol}</span>
        <span
          className="text-xs uppercase tracking-wide text-muted"
          data-testid="campaign-status"
        >
          {campaign.status}
        </span>
        <Money value={campaign.net_premium} kind="realized" signed asOf={campaign.as_of} />
        <span className="text-xs text-muted" data-testid="campaign-leg-count">
          {legCount} {legCount === 1 ? "leg" : "legs"}
        </span>
      </button>

      {campaign.assigned && (
        <div className="flex flex-wrap gap-4 border-t border-border px-4 py-2">
          <Field label="Adjusted cost basis" testId="campaign-adjusted-basis">
            <Money value={campaign.adjusted_cost_basis} kind="basis" asOf={campaign.as_of} />
          </Field>
          <Field label="Realized stock P&L" testId="campaign-realized-pnl">
            <Money
              value={campaign.realized_stock_pnl}
              kind="realized"
              signed
              asOf={campaign.as_of}
            />
          </Field>
        </div>
      )}

      {isOpen && (
        <ul className="divide-y divide-border border-t border-border" data-testid="campaign-legs">
          {campaign.legs.map((leg) => (
            <CampaignLegRow leg={leg} key={leg.candidate_id} />
          ))}
        </ul>
      )}
    </div>
  );
}
