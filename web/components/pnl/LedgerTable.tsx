"use client";

import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { CampaignRow } from "./CampaignRow";
import { LedgerFilters } from "./LedgerFilters";
import type { LedgerResponseData } from "./types";

/**
 * The ledger table: campaigns grouped as collapsible threads, the marks age
 * stated in words beside the unrealised column, and the filter echo so the
 * client can prove what it is looking at. An empty ledger renders one line of
 * text — no icon circle, no empty table frame.
 *
 * `marks_as_of: null` renders "no marks available" and every unrealised cell
 * renders `n/a`: an unmarked position is not worth zero, and the page must not
 * pretend otherwise.
 */
export function LedgerTable({ data }: { data: LedgerResponseData }) {
  return (
    <div className="space-y-4" data-testid="ledger-table">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="text-xs text-muted" data-testid="ledger-filter-echo">
          {[data.filters.symbol, data.filters.book !== "all" ? `book: ${data.filters.book}` : null]
            .filter(Boolean)
            .join(" · ") || "all trades"}
        </span>
        {data.marks_as_of == null ? (
          <span className="text-xs text-unknown" data-testid="marks-note">
            no marks available
          </span>
        ) : (
          <span className="text-xs text-muted" data-testid="marks-note">
            marks {new Date(data.marks_as_of).toISOString().slice(0, 16).replace("T", " ")} UTC
          </span>
        )}
      </div>

      {data.campaigns.length === 0 ? (
        <p className="text-sm text-muted">No trades match the current filters.</p>
      ) : (
        <div className="space-y-3">
          {data.campaigns.map((c) => (
            <CampaignRow key={c.campaign_id} campaign={c} />
          ))}
        </div>
      )}
    </div>
  );
}