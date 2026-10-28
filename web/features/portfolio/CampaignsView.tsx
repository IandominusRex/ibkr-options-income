"use client";

import clsx from "clsx";
import { useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import type { CampaignLeg, CampaignSummary, CampaignsResponse } from "@/components/portfolio/types";
import { Card } from "@/components/ui/Card";
import { Disclosure } from "@/components/ui/Disclosure";
import { FIELD, FIELD_LABEL } from "@/components/ui/field";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { StatusWord } from "@/components/ui/StatusWord";
import { formatStubValue } from "@/components/ui/Stub";
import { FigureLines } from "@/features/claude-context/FigureLines";
import { apiFetch } from "@/lib/api";
import { UNKNOWN } from "@/lib/format";
import { formatMoneyCell } from "@/lib/money";
import { legTitle, threadSub } from "./campaigns";
import { shortDate } from "./format";

type StatusFilter = "all" | "open" | "closed";
const STATUS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
];

function Leg({ leg }: { leg: CampaignLeg }) {
  const row = "flex items-center justify-between gap-3 border-t border-border py-2 text-sm first:border-t-0";
  if (!leg.known) {
    // The scan's record of this leg was pruned: the leg stays, with its id, and says why it is bare.
    return (
      <li className={row}>
        <span className="text-muted">Leg unavailable</span>
        <span className="font-mono text-xs text-muted">{leg.candidate_id}</span>
      </li>
    );
  }
  return (
    <li className={row}>
      <span className="font-semibold">{legTitle(leg)}</span>
      <span className="text-[0.8125rem] text-muted">
        {leg.expiry ? shortDate(leg.expiry) : <span className="hatch text-unknown">{UNKNOWN}</span>}
      </span>
    </li>
  );
}

function Thread({ c }: { c: CampaignSummary }) {
  const titleId = `campaign-${c.campaign_id}`;
  const net = c.net_premium;
  const basis = c.adjusted_cost_basis;
  const stock = c.realized_stock_pnl;
  return (
    <Card as="article" aria-labelledby={titleId}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 id={titleId} className="inline text-[1.0625rem] font-bold">
            {c.symbol}
          </h3>
          <span className="ml-1.5 align-[1px]">
            <StatusWord>{c.status === "open" ? "Open" : "Closed"}</StatusWord>
          </span>
          <div className="text-[0.8125rem] text-muted">{threadSub(c)}</div>
        </div>
        <div className="tabular text-right font-mono font-semibold">
          <span className={clsx(net < 0 && "text-loss", net > 0 && "text-gain")}>
            {formatStubValue(net, "signed-money")}
          </span>
          <div className="font-sans text-[0.8125rem] font-normal text-muted">net premium, before commissions</div>
        </div>
      </div>
      {c.assigned && (
        <FigureLines
          label={`${c.symbol} assigned shares`}
          rows={[
            {
              label: "Adjusted cost basis",
              value: basis === null || basis === undefined ? UNKNOWN : formatMoneyCell(basis),
              unknown: basis === null || basis === undefined,
            },
            {
              label: "Realised stock P&L",
              value: stock === null || stock === undefined ? UNKNOWN : formatStubValue(stock, "signed-money"),
              unknown: stock === null || stock === undefined,
            },
          ]}
        />
      )}
      <div className="mt-3">
        <Disclosure summary={<span className="text-sm font-semibold">{c.legs.length} {c.legs.length === 1 ? "leg" : "legs"}</span>}>
          <ul>
            {c.legs.map((l) => (
              <Leg key={l.candidate_id} leg={l} />
            ))}
          </ul>
        </Disclosure>
      </div>
    </Card>
  );
}

/**
 * The wheel threads, one card per symbol. Status and symbol go to the API (a filter is a real
 * refetch, never a client-side narrowing of a list that may be partial). The money is the API's
 * campaign figures, which are before commissions, and the card says so.
 */
export function CampaignsView() {
  const [status, setStatus] = useState<StatusFilter>("all");
  const [symbol, setSymbol] = useState("");
  const symbolId = useId();
  const sym = symbol.trim().toUpperCase();

  const { data, isError } = useQuery({
    queryKey: ["portfolio", "campaigns", status === "all" ? "" : status, sym],
    queryFn: () => {
      const params = new URLSearchParams();
      if (status !== "all") params.set("status", status);
      if (sym) params.set("symbol", sym);
      const qs = params.toString();
      return apiFetch<CampaignsResponse>(`/portfolio/campaigns${qs ? `?${qs}` : ""}`);
    },
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-end gap-x-4 gap-y-3">
        <SegmentedControl label="Status" appearance="chips" options={STATUS} value={status} onChange={setStatus} />
        <div className="grid gap-1">
          <label htmlFor={symbolId} className={FIELD_LABEL}>
            Symbol
          </label>
          <input
            id={symbolId}
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="NVDA"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            className={clsx(FIELD, "w-32")}
          />
        </div>
      </div>
      {isError && !data ? (
        <div className="text-sm text-muted">
          <p>Could not load campaigns.</p>
          <p className="mt-1 text-[0.8125rem]">It tries again every 30 seconds.</p>
        </div>
      ) : !data ? (
        <div role="status" aria-busy="true" aria-label="Loading campaigns" className="h-24 rounded-[18px] bg-surface" />
      ) : data.campaigns.length === 0 ? (
        <p className="py-3 text-sm text-muted">No campaigns match the current filters.</p>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {data.campaigns.map((c) => (
            <Thread key={c.campaign_id} c={c} />
          ))}
        </div>
      )}
    </div>
  );
}
