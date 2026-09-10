"use client";

import { useState } from "react";
import { Money } from "@/components/portfolio/Money";
import { LegRow } from "./LegRow";
import type { CampaignPnlData } from "./types";

const LEG_HEADERS = ["Leg", "Contract", "Expiry", "Qty", "Days", "Realized", "Unrealized", "Outcome"];

/**
 * One campaign thread of the P&L ledger: symbol, status, net and leg count
 * collapsed; expanding shows the legs in order through a real
 * `<button aria-expanded>` (the CampaignThread convention from M3 Task 3.4 —
 * each thread owns its own expand/collapse state so opening one never affects
 * another).
 *
 * The thread's net renders through `portfolio/Money` (kind "value" — it mixes
 * realised and unrealised legs, so neither label would be accurate), the same
 * null-discipline the legs use: a `null` `option_unrealized` is `n/a` with
 * texture, never `$0.00` — an unmarked open leg is not worth zero.
 */
export function CampaignRow({ campaign }: { campaign: CampaignPnlData }) {
  const [isOpen, setIsOpen] = useState(false);
  const legCount = campaign.legs?.length ?? 0;

  return (
    <div
      className="overflow-hidden rounded-md border border-border bg-surface"
      data-testid="campaign-row"
    >
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((open) => !open)}
        className="flex w-full flex-wrap items-center justify-between gap-4 px-4 py-3 text-left"
        aria-label={`${campaign.symbol} campaign`}
      >
        <span className="font-mono text-sm text-content">{campaign.symbol}</span>
        <span
          className="text-xs uppercase tracking-wide text-muted"
          data-testid="campaign-status"
        >
          {campaign.status}
        </span>
        <span data-testid="campaign-net">
          <Money value={campaign.total_net} kind="value" signed />
        </span>
        <span className="text-xs text-muted" data-testid="campaign-leg-count">
          {legCount} {legCount === 1 ? "leg" : "legs"}
        </span>
      </button>

      {isOpen && (
        <div className="border-t border-border" data-testid="campaign-legs">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border bg-elevated text-left">
                {LEG_HEADERS.map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2 text-[10px] font-normal uppercase tracking-wide text-muted"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {(campaign.legs ?? []).map((leg) => (
                <LegRow key={leg.candidate_id} leg={leg} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}