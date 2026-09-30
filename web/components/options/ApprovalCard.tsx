"use client";

import Link from "next/link";
import { UNKNOWN, formatDateTime } from "@/lib/format";
import type { CommandStatus } from "@/lib/commands";
import type { ApprovalSummary } from "./types";
import { DecideControls } from "./DecideControls";
import { RationaleTags } from "./RationaleTags";

export function ApprovalCard({
  approval,
  drainHealthy = true,
  initialCommand = null,
  onApprovalSubmitted,
  onApprovalSettled,
}: {
  approval: ApprovalSummary;
  drainHealthy?: boolean;
  initialCommand?: CommandStatus | null;
  onApprovalSubmitted?: (id: number, command: CommandStatus) => void;
  onApprovalSettled?: (id: number) => void;
}) {
  const expiry = approval.expiry;
  const dte = expiry ? daysToExpiry(expiry) : null;
  const totalPremium =
    approval.premium != null ? approval.premium * approval.contracts * 100 : null;
  const review = approval.review;

  return (
    <div className="rounded-md border border-border bg-surface px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <Link
          href={`/options/${approval.id}`}
          className="flex items-baseline gap-2 rounded focus-visible:ring-focus hover:text-focus"
        >
          <span className="font-mono text-sm text-content">
            {approval.underlying} {formatContract(approval)}
          </span>
          <span className="text-xs text-muted">{approval.source}</span>
        </Link>
        <span className="text-xs text-muted">{formatDateTime(approval.created_at)}</span>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs">
        <Metric label="Contracts" value={String(approval.contracts)} />
        <Metric
          label="Premium"
          value={
            approval.premium != null ? `$${approval.premium.toFixed(2)}/sh` : UNKNOWN
          }
        />
        <Metric
          label="Total"
          value={totalPremium != null ? `$${totalPremium.toFixed(0)}` : UNKNOWN}
        />
        <Metric
          label="Score"
          value={
            approval.blended_score != null
              ? approval.blended_score.toFixed(1)
              : UNKNOWN
          }
        />
        <Metric label="DTE" value={dte != null ? String(dte) : UNKNOWN} />
        {approval.order_state && (
          <Metric label="Order" value={approval.order_state} />
        )}
      </div>

      {approval.rationale_tags && approval.rationale_tags.length > 0 && (
        <div className="mt-3">
          <RationaleTags tags={approval.rationale_tags} />
        </div>
      )}

      {review && (
        <div className="mt-3 space-y-1 text-xs text-muted">
          {review.summary ? (
            <ReviewLine label="Verdict" text={review.summary} />
          ) : (
            <ReviewLine label="Why" text={review.why_attractive} />
          )}
          {review.risks && <ReviewLine label="Risks" text={review.risks} />}
        </div>
      )}

      <DecideControls
        approval={approval}
        drainHealthy={drainHealthy}
        initialCommand={initialCommand}
        onApprovalSubmitted={onApprovalSubmitted}
        onApprovalSettled={onApprovalSettled}
      />
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <span className="tabular">
      <span className="text-muted">{label} </span>
      <span className="text-content">{value}</span>
    </span>
  );
}

function ReviewLine({ label, text }: { label: string; text: string }) {
  if (!text) return null;
  return (
    <p>
      <span className="text-muted">{label}: </span>
      <span className="text-content">{text}</span>
    </p>
  );
}

function formatContract(a: ApprovalSummary): string {
  const right = a.right === "C" ? "C" : "P";
  const strike = a.strike.toFixed(2);
  const expiry = a.expiry ? a.expiry.slice(2, 10).replace(/-/g, "") : "??";
  return `${strike} ${right} ${expiry}`;
}

function daysToExpiry(iso: string): number {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 0;
  const now = new Date();
  return Math.floor((d.getTime() - now.getTime()) / 86_400_000);
}