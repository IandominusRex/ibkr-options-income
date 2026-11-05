"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { Suspense, type ReactNode } from "react";
import { Card } from "@/components/ui/Card";
import { StatusWord } from "@/components/ui/StatusWord";
import { Stub, formatStubValue } from "@/components/ui/Stub";
import { proposalTitle } from "@/features/home/ProposalCard";
import { tradesReturnQuery } from "@/features/trades/useTradesView";
import { decisionWords, proposalSentence, proposalStub, rollSentence, rollStub } from "@/features/home/proposal";
import { apiFetch } from "@/lib/api";
import { UNKNOWN, formatDateTime, relativeAge } from "@/lib/format";
import { STRATEGY_EYEBROW, kindOf } from "@/lib/strategy";
import { AlternativesTable } from "./AlternativesTable";
import { DecideControls } from "./DecideControls";
import { IdealZoneBar } from "./IdealZoneBar";
import { RationaleTags } from "./RationaleTags";
import { ReviewPanel, hasReviewContent } from "./ReviewPanel";
import type { ApprovalDetail, ControlsResponse } from "./types";

const STATUS_WORD: Record<string, string> = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
  expired: "Expired",
};

const BACK_CLASS =
  "inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-muted hover:text-content md:min-h-8";

function BackLink({ href }: { href: string }) {
  return (
    <Link href={href} aria-label="Back to Trades" className={BACK_CLASS}>
      <ChevronLeft size={16} aria-hidden="true" />
      Trades
    </Link>
  );
}

function BackFromParams() {
  // The Trades view, day and strategy this page was opened from; none (a bare URL, or Home) is plain Trades.
  const q = tradesReturnQuery(useSearchParams());
  return <BackLink href={q ? `/trades?${q}` : "/trades"} />;
}

/** Back to the Trades view you left. The Suspense keeps a prerender from waiting on the query string. */
export function BackToTrades() {
  return (
    <Suspense fallback={<BackLink href="/trades" />}>
      <BackFromParams />
    </Suspense>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-t border-border py-2 text-sm first:border-t-0">
      <dt className="text-muted">{label}</dt>
      <dd className="tabular text-right font-semibold">{children}</dd>
    </div>
  );
}

const Unknown = () => <span className="hatch text-unknown">{UNKNOWN}</span>;

/**
 * A price per share. A roll's is a net, credit positive and debit negative (the API reports the
 * fill in `premium`'s convention), so it is written signed: "+$0.45" or "−$0.30", never "$-0.30".
 * A single-leg price is always a credit taken and keeps the plain dollar figure.
 */
function perShare(value: number, net: boolean): string {
  return net ? formatStubValue(value, "signed-money") : `$${value.toFixed(2)}`;
}

const LEFT = "min-w-0 lg:col-start-1";

export function ApprovalDetailCard({ detail }: { detail: ApprovalDetail }) {
  // The drain's health drives the receipt's `stalled` state (spec §9.2 rule 3). `true` while the
  // query loads, so a not-yet-known drain is never falsely reported as dead.
  const controls = useQuery({
    queryKey: ["options", "controls"],
    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const drainHealthy = controls.data?.drain_healthy ?? true;
  const kind = kindOf(detail.strategy, detail.right);
  const isRoll = detail.source === "roll";
  const eyebrow = isRoll ? "Roll" : kind ? STRATEGY_EYEBROW[kind] : detail.strategy;
  const decision = decisionWords(detail.status, detail.decided_by ?? null);
  const roll = isRoll ? rollStub(detail) : [];

  return (
    <div className="space-y-4">
      <BackToTrades />
      <header>
        <p className="text-xs font-bold uppercase tracking-[0.04em] text-muted">
          {eyebrow} · raised {formatDateTime(detail.created_at)}
        </p>
        <h1 className="mt-1 text-2xl font-extrabold tracking-[-0.015em]">{proposalTitle(detail)}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm text-muted">
          <StatusWord>{STATUS_WORD[detail.status] ?? detail.status}</StatusWord>
          {decision && decision !== STATUS_WORD[detail.status] && <span>{decision}</span>}
          <span>{isRoll ? "A roll of a position you hold" : "From the scan"}</span>
          {detail.order_state && <span>order {detail.order_state}</span>}
        </p>
      </header>

      {/* One grid placed by CSS: the DOM order is the phone's (trade, review, decision, the rest);
          from 1024px the decision takes a 340px column on the right beside everything else. */}
      <div className="grid items-start gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <Card as="section" aria-labelledby="trade-title" className={LEFT}>
          <h2 id="trade-title" className="text-[1.0625rem] font-bold">
            The trade
          </h2>
          <p className="mt-1 text-sm">{isRoll ? rollSentence(detail) : proposalSentence(detail)}</p>
          {!isRoll && (
            <Stub label={`${detail.underlying} ${detail.right === "C" ? "call" : "put"} math`} lines={proposalStub(detail, new Date())} />
          )}
          {roll.length > 0 && <Stub label={`${detail.underlying} roll math`} lines={roll} />}
          <dl className="mt-3">
            <Fact label="Contracts">{detail.contracts}</Fact>
            <Fact label={isRoll ? "Net a share, as priced" : "Premium a share"}>
              {detail.premium != null ? perShare(detail.premium, isRoll) : <Unknown />}
            </Fact>
            {detail.order_state === "filled" || detail.order_state === "partial" ? (
              <Fact label={isRoll ? "Net filled, a share" : "Filled at"}>
                {detail.fill_price != null ? perShare(detail.fill_price, isRoll) : <Unknown />}
              </Fact>
            ) : null}
            <Fact label="Score">{detail.blended_score != null ? detail.blended_score.toFixed(1) : <Unknown />}</Fact>
            <Fact label="Expiry">{detail.expiry ?? <Unknown />}</Fact>
          </dl>
          <div className="mt-3">
            <RationaleTags tags={detail.rationale_tags} />
          </div>
        </Card>

        {hasReviewContent(detail.review) && (
          <Card as="section" aria-labelledby="review-title" className={LEFT}>
            <h2 id="review-title" className="text-[1.0625rem] font-bold">
              Claude&apos;s review
            </h2>
            <p className="mb-3 text-[0.8125rem] text-muted">Claude&apos;s view of this proposal. It decides nothing.</p>
            <ReviewPanel review={detail.review} />
          </Card>
        )}

        <Card as="section" aria-labelledby="decision-title" className="lg:sticky lg:top-4 lg:col-start-2 lg:row-span-6 lg:row-start-1">
          <h2 id="decision-title" className="text-[1.0625rem] font-bold">
            Decision
          </h2>
          <div className="mt-3">
            <DecideControls approval={detail} drainHealthy={drainHealthy} />
          </div>
        </Card>

        {detail.ideal && (
          <Card as="section" aria-labelledby="ideal-title" className={LEFT}>
            <h2 id="ideal-title" className="text-[1.0625rem] font-bold">
              Ideal zone
            </h2>
            <div className="mt-2">
              <IdealZoneBar ideal={detail.ideal} premium={detail.premium} strike={detail.strike} />
            </div>
          </Card>
        )}

        {detail.gate_reasons.length > 0 && (
          <Card as="section" aria-labelledby="gate-title" className={LEFT}>
            <h2 id="gate-title" className="text-[1.0625rem] font-bold">
              Gate reasons
            </h2>
            <ul className="mt-1 list-disc space-y-1 pl-[18px] text-sm">
              {detail.gate_reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </Card>
        )}

        {detail.alternatives.length > 0 && (
          <Card as="section" className={LEFT} aria-label="Other contracts assessed on this run">
            <AlternativesTable alternatives={detail.alternatives} />
          </Card>
        )}

        {detail.fills.length > 0 && (
          <Card as="section" aria-labelledby="fills-title" className={LEFT}>
            <h2 id="fills-title" className="text-[1.0625rem] font-bold">
              Fills
            </h2>
            <ul className="mt-1">
              {detail.fills.map((f) => (
                <li key={f.id} className="flex items-baseline justify-between gap-3 border-t border-border py-2.5 text-sm first:border-t-0">
                  <p>
                    <span className="font-bold">{f.action}</span> {f.filled_qty.toFixed(0)} at{" "}
                    <span className="tabular font-mono">${f.avg_price.toFixed(2)}</span>
                  </p>
                  <p className="flex-none text-right text-xs text-muted">
                    {relativeAge(f.filled_at)} · {f.is_live ? "live" : "paper"}
                  </p>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </div>
  );
}
