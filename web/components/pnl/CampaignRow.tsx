"use client";

import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { Money } from "@/components/portfolio/Money";
import { StatusWord } from "@/components/ui/StatusWord";
import { LegRow } from "./LegRow";
import type { CampaignPnlData } from "./types";

const LEG_HEADERS = ["Leg", "Contract", "Expiry", "Qty", "Days", "Realized", "Unrealized", "Outcome"];
const RIGHT = new Set(["Qty", "Days", "Realized", "Unrealized"]);

/**
 * One campaign thread of the P&L ledger: symbol, status, net and leg count
 * collapsed; expanding shows the legs in order through a real
 * `<button aria-expanded>` (each thread owns its own expand/collapse state so
 * opening one never affects another). The legs are rendered only while open.
 *
 * The thread's net renders through `portfolio/Money` (kind "value": it mixes
 * realised and unrealised legs, so neither label would be accurate), with the
 * same null discipline the legs use: an unmarked open leg is not worth zero.
 */
export function CampaignRow({ campaign }: { campaign: CampaignPnlData }) {
  const [isOpen, setIsOpen] = useState(false);
  const legCount = campaign.legs?.length ?? 0;

  return (
    <div className="rounded-[18px] bg-surface" data-testid="campaign-row">
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((open) => !open)}
        className="flex min-h-11 w-full flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-[18px] px-4 py-3 text-left"
        aria-label={`${campaign.symbol} campaign`}
      >
        <span className="text-[1.0625rem] font-bold">{campaign.symbol}</span>
        <span data-testid="campaign-status">
          <StatusWord>{campaign.status === "open" ? "Open" : "Closed"}</StatusWord>
        </span>
        <span data-testid="campaign-net" className="font-mono">
          <Money value={campaign.total_net} kind="value" signed />
        </span>
        <span className="flex items-center gap-2 text-[0.8125rem] text-muted" data-testid="campaign-leg-count">
          {legCount} {legCount === 1 ? "leg" : "legs"}
          <ChevronDown
            size={16}
            aria-hidden="true"
            className={clsx("transition-transform duration-[180ms] ease-out motion-reduce:transition-none", isOpen && "rotate-180")}
          />
        </span>
      </button>

      {isOpen && (
        <div className="border-t border-border px-4 pb-3">
          <p className="pt-2 text-xs text-muted md:hidden">Scroll sideways to see every column.</p>
          <div className="overflow-x-auto" data-testid="campaign-legs">
            <table className="w-full">
              <thead>
                <tr className="text-left text-xs font-semibold tracking-[0.04em] text-muted">
                  {LEG_HEADERS.map((h) => (
                    <th key={h} className={clsx("py-2 pr-3 font-semibold", RIGHT.has(h) && "text-right")}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(campaign.legs ?? []).map((leg) => (
                  <LegRow key={leg.candidate_id} leg={leg} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
