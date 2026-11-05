"use client";

import Link from "next/link";
import { useId } from "react";
import { Card } from "@/components/ui/Card";
import { UNKNOWN } from "@/lib/format";
import { expiresWords, price, proposalTitle } from "@/components/value/format";
import type { ValueProposal } from "@/components/value/types";
import { useValueBook, waitingProposals } from "@/components/value/useValueBook";

function Row({ proposal: p }: { proposal: ValueProposal }) {
  const titleId = useId();
  return (
    <Card as="article" aria-labelledby={titleId}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-bold uppercase tracking-[0.04em] text-muted">Value book</span>
        <span className="text-[0.8125rem] text-muted">{expiresWords(p.expires_at)}</span>
      </div>
      <h3 id={titleId} className="mt-1 text-[1.0625rem] font-extrabold tracking-[-0.01em]">
        {proposalTitle(p)}
      </h3>
      <p className="tabular mt-1 text-[0.8125rem] text-muted">
        {p.kind === "buy" ? (
          p.cost_usd == null ? (
            <>
              cost <span className="hatch px-1 text-unknown">{UNKNOWN}</span>
            </>
          ) : (
            `cost ${price(p.cost_usd)}`
          )
        ) : (
          "sells at the next check"
        )}
      </p>
      {/* A jump, not a second Review: the decide flow lives on the Value card (one lime control there). */}
      <Link
        href="#value-title"
        aria-describedby={titleId}
        className="mt-3.5 inline-flex min-h-11 w-full items-center justify-center rounded-full bg-sunk px-[18px] text-[1.0625rem] font-bold text-content transition-transform duration-[90ms] hover:bg-sunk-deep motion-safe:active:scale-[0.98]"
      >
        Review in the Value book
      </Link>
    </Card>
  );
}

/**
 * The value book's proposals that wait on a tap, as rows in "Needs you" (web overhaul Part 4, ruling 15). Each row
 * jumps to the Value card, which keeps the one decide flow and its one lime Review: a second Review here would break
 * the lime rule and mount a second `ValueDecide` polling the same command. An unreadable book is said, never read
 * as none; a book that is off and never wrote says nothing. `emptyText` is the line for a read book with none
 * waiting, given only where the value rows are the whole column (Home under Value).
 */
export function ValueWaiting({ emptyText }: { emptyText?: string }) {
  const { data, isError } = useValueBook();
  const waiting = waitingProposals(data);
  if (!data) {
    if (isError) {
      return <p className="text-sm text-muted">The value book could not be read, so a value proposal may be waiting.</p>;
    }
    return emptyText ? (
      <div className="h-24 rounded-[18px] bg-surface" role="status" aria-busy="true" aria-label="Loading value proposals" />
    ) : null;
  }
  if (waiting === null) {
    // Read, but not available: a book that is on yet unreadable may hide a proposal; one that is off has none.
    if (data.enabled) {
      return <p className="text-sm text-muted">The value book could not be read, so a value proposal may be waiting.</p>;
    }
    return emptyText ? <p className="text-sm text-muted">{emptyText}</p> : null;
  }
  if (waiting.length === 0) return emptyText ? <p className="text-sm text-muted">{emptyText}</p> : null;
  return (
    <div className="grid gap-3">
      {waiting.map((p) => (
        <Row key={p.id} proposal={p} />
      ))}
    </div>
  );
}
