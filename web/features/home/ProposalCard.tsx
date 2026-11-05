"use client";

import Link from "next/link";
import { useId } from "react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Stub } from "@/components/ui/Stub";
import type { ApprovalSummary } from "@/components/options/types";
import { STRATEGY_EYEBROW, kindOf } from "@/lib/strategy";
import { daysToExpiry, proposalSentence, proposalStub, rollSentence, rollStub, rollTitle } from "./proposal";
import { detailHref } from "@/features/trades/useTradesView";
import { WhyDisclosure } from "./WhyDisclosure";

const DAY = new Intl.DateTimeFormat("en-US", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });

export function proposalTitle(a: ApprovalSummary): string {
  if (a.source === "roll") return rollTitle(a);
  const word = a.right === "P" ? "put" : a.right === "C" ? "call" : "option";
  return `${a.underlying} · Sell $${a.strike} ${word}`;
}

export function ProposalBody({ approval }: { approval: ApprovalSummary }) {
  const isRoll = approval.source === "roll";
  const roll = isRoll ? rollStub(approval) : [];
  return (
    <>
      <p className="mt-2 text-sm">{isRoll ? rollSentence(approval) : proposalSentence(approval)}</p>
      <WhyDisclosure review={approval.review} />
      {!isRoll && (
        <Stub label={`${approval.underlying} ${approval.right === "C" ? "call" : "put"} math`} lines={proposalStub(approval, new Date())} />
      )}
      {roll.length > 0 && <Stub label={`${approval.underlying} roll math`} lines={roll} />}
    </>
  );
}

export function ProposalCard({
  approval,
  onReview,
  detailQuery = "",
}: {
  approval: ApprovalSummary;
  onReview: (a: ApprovalSummary) => void;
  /** The Trades view this card sits in, as a `tradesReturnQuery`, so Back from Details returns to it. Home passes none. */
  detailQuery?: string;
}) {
  const titleId = useId();
  const kind = kindOf(approval.strategy, approval.right);
  const dte = daysToExpiry(approval.expiry, new Date());
  const eyebrow = approval.source === "roll" ? "Roll" : kind ? STRATEGY_EYEBROW[kind] : approval.strategy;
  return (
    <Card as="article" aria-labelledby={titleId}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-bold uppercase tracking-[0.04em] text-muted">{eyebrow}</span>
        <span className="text-[0.8125rem] text-muted">
          {approval.expiry ? DAY.format(new Date(`${approval.expiry}T00:00:00Z`)) : "expiry n/a"}
          {dte !== null && ` · ${dte}d`}
        </span>
      </div>
      <h3 id={titleId} className="mt-1 text-[1.0625rem] font-extrabold tracking-[-0.01em]">
        {proposalTitle(approval)}
      </h3>
      <ProposalBody approval={approval} />
      <div className="mt-3.5 flex gap-2">
        {/* aria-describedby gives a screen reader the trade without changing the button's name. */}
        <Button
          variant="primary"
          block
          aria-haspopup="dialog"
          aria-describedby={titleId}
          onClick={() => onReview(approval)}
        >
          Review
        </Button>
        <Link
          href={detailHref(approval.id, detailQuery)}
          aria-describedby={titleId}
          className="inline-flex min-h-11 w-full items-center justify-center rounded-full bg-sunk px-[18px] text-[1.0625rem] font-bold text-content transition-transform duration-[90ms] hover:bg-sunk-deep motion-safe:active:scale-[0.98]"
        >
          Details
        </Link>
      </div>
    </Card>
  );
}
