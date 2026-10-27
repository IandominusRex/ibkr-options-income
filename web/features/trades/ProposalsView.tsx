"use client";

import { useState, type ReactNode } from "react";
import type { ApprovalSummary } from "@/components/options/types";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { MarketCard } from "@/features/market/MarketCard";
import { usePendingApprovals } from "@/features/home/NeedsYou";
import { ProposalCard } from "@/features/home/ProposalCard";
import { ReviewSheet } from "@/features/home/ReviewSheet";
import type { CommandStatus } from "@/lib/commands";
import type { StrategyFilter } from "@/lib/strategy";
import { tickerCounts } from "./views";

/**
 * Pending proposals at page width: Home's cards, Home's review sheet. A proposal whose Approve
 * is in flight is in `submitted` and shows under History's In flight instead.
 */
export function ProposalsView({
  strategy,
  submitted,
  onSubmitted,
  onSettled,
}: {
  strategy: StrategyFilter;
  submitted: Map<number, CommandStatus>;
  onSubmitted: (id: number, command: CommandStatus) => void;
  onSettled: (id: number) => void;
}) {
  const { data, isError, visible } = usePendingApprovals(strategy);
  const [ticker, setTicker] = useState("all");
  const [reviewing, setReviewing] = useState<ApprovalSummary | null>(null);

  const waiting = visible.filter((a) => !submitted.has(a.id));
  const tickers = tickerCounts(waiting);
  // A ticker whose last proposal was decided or sent loses its chip; the list then shows them all.
  const active = tickers.some((t) => t.ticker === ticker) ? ticker : "all";
  const shown = active === "all" ? waiting : waiting.filter((a) => a.underlying === active);

  let body: ReactNode;
  if (isError && !data) {
    body = (
      <p className="text-sm text-muted">
        Proposals could not be loaded. They are asked for again every 30 seconds.
      </p>
    );
  } else if (!data) {
    body = (
      <div className="h-40 rounded-[18px] bg-surface" role="status" aria-busy="true" aria-label="Loading proposals" />
    );
  } else if (waiting.length === 0) {
    body = <p className="text-sm text-muted">Nothing needs you right now.</p>;
  } else {
    body = (
      <>
        {tickers.length > 1 && (
          <SegmentedControl
            label="Ticker"
            appearance="quiet"
            className="mb-4"
            options={[
              { value: "all", label: "All tickers" },
              ...tickers.map((t) => ({ value: t.ticker, label: t.ticker, count: t.count })),
            ]}
            value={active}
            onChange={setTicker}
          />
        )}
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {shown.map((a) => (
            <ProposalCard key={a.id} approval={a} onReview={setReviewing} />
          ))}
        </div>
      </>
    );
  }

  return (
    <section aria-labelledby="proposals-title">
      <h2 id="proposals-title" className="sr-only">
        Proposals
      </h2>
      <div className="mb-4">
        <MarketCard variant="trades" />
      </div>
      {body}
      <ReviewSheet
        approval={reviewing}
        open={reviewing !== null}
        onClose={() => setReviewing(null)}
        onSubmitted={onSubmitted}
        onSettled={onSettled}
      />
    </section>
  );
}
