"use client";

import Link from "next/link";
import { useId } from "react";
import { Card } from "@/components/ui/Card";
import { Disclosure } from "@/components/ui/Disclosure";
import { Stub } from "@/components/ui/Stub";
import { decisionWords } from "./proposal";
import { WhyDisclosure } from "./WhyDisclosure";
import { dateLabel, timeLabel, tradeEyebrow, tradeSentence, tradeStub, tradeTitle } from "./trades";
import type { DayFact, DayTrade } from "./types";

/**
 * The reasoning behind a close or a roll. Every line is worked out from stored facts (the close
 * reason, the roll policy's log, the fills); a line that is Claude's own view says so in its
 * label, so Claude's text never passes for the system's rule.
 */
function FactsDisclosure({ trade, facts }: { trade: DayTrade; facts: DayFact[] }) {
  if (facts.length === 0) return null;
  const hasClaude = facts.some((f) => f.source === "claude");
  return (
    <div className="mt-3">
      <Disclosure
        summary={
          <span className="text-[0.8125rem] font-bold">
            {trade.kind === "value"
              ? trade.action === "opened"
                ? "Why it was bought"
                : "Why it was sold"
              : trade.action === "rolled"
                ? "Why it was rolled"
                : "Why it closed"}{" "}
            <span className="font-medium text-muted">
              · {hasClaude ? "the system's rules and Claude's view" : "the system's rules"}
            </span>
          </span>
        }
      >
        <ul className="list-disc space-y-1 pl-[18px] text-[0.8125rem]">
          {facts.map((f) => (
            <li key={f.label}>
              <span className="font-bold">{f.label}:</span> {f.text}
            </li>
          ))}
        </ul>
      </Disclosure>
    </div>
  );
}

/**
 * An executed trade, in the proposal card's anatomy (DESIGN.md): the action and the kind of trade
 * in words, a title, one sentence, the reasoning collapsed above the stub, then the stub that sums
 * the whole trade. Nothing here decides anything, so there is no lime.
 */
export function TradeCard({
  trade,
  when = "time",
  heading = "title",
}: {
  trade: DayTrade;
  /** "time" for Done today (the fill's clock time); "date" where the card is not about today. */
  when?: "time" | "date";
  /** "title" gives the card its own title line; "none" is for a page that already names the contract. */
  heading?: "title" | "none";
}) {
  const titleId = useId();
  return (
    <Card as="article" aria-labelledby={titleId}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-bold uppercase tracking-[0.04em] text-muted">{tradeEyebrow(trade)}</span>
        <span className="text-[0.8125rem] text-muted">{when === "date" ? dateLabel(trade) : timeLabel(trade)}</span>
      </div>
      {heading === "none" ? (
        // The position page already names the contract in its h1, so the card's own title is
        // for screen readers only, one level down (h2) so the outline does not skip a level.
        <h2 id={titleId} className="sr-only">
          {tradeTitle(trade)}
        </h2>
      ) : (
        <h3 id={titleId} className="mt-1 text-[1.0625rem] font-extrabold tracking-[-0.01em]">
          {tradeTitle(trade)}
        </h3>
      )}
      <p className="mt-2 text-sm">{tradeSentence(trade)}</p>
      {trade.action !== "closed" && trade.decided_by && (
        <p className="mt-1 text-[0.8125rem] text-muted">{decisionWords("approved", trade.decided_by)}</p>
      )}
      {trade.action === "opened" && trade.kind !== "value" ? (
        <WhyDisclosure review={trade.review} />
      ) : (
        <FactsDisclosure trade={trade} facts={trade.facts} />
      )}
      <Stub label={`${trade.underlying} ${trade.action} math`} lines={tradeStub(trade)} />
      {trade.approval_id !== null && (
        <div className="mt-3.5">
          <Link
            href={`/trades/${trade.approval_id}`}
            aria-describedby={titleId}
            className="inline-flex min-h-11 w-full items-center justify-center rounded-full bg-sunk px-[18px] text-[1.0625rem] font-bold text-content transition-transform duration-[90ms] hover:bg-sunk-deep motion-safe:active:scale-[0.98]"
          >
            Details
          </Link>
        </div>
      )}
    </Card>
  );
}
