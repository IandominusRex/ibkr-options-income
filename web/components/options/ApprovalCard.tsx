import Link from "next/link";
import { UNKNOWN, relativeAge } from "@/lib/format";
import type { ApprovalSummary, ClaudeReviewPayload } from "./types";

export function ApprovalCard({ approval }: { approval: ApprovalSummary }) {
  const expiry = approval.expiry;
  const dte = expiry ? daysToExpiry(expiry) : null;
  const totalPremium =
    approval.premium != null ? approval.premium * approval.contracts * 100 : null;
  const review = (approval as ApprovalSummary & { review?: ClaudeReviewPayload | null })
    .review ?? null;

  return (
    <Link
      href={`/options/${approval.id}`}
      className="block rounded-md border border-border bg-surface px-4 py-3 hover:bg-elevated focus-visible:bg-elevated"
    >
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-sm text-content">
            {approval.underlying} {formatContract(approval)}
          </span>
          <span className="text-xs text-muted">{approval.source}</span>
        </div>
        <span className="text-xs text-muted">{relativeAge(approval.as_of)}</span>
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

      {review && (
        <div className="mt-3 space-y-1 text-xs text-muted">
          <ReviewLine label="Why" text={review.why_attractive} />
          {review.risks && <ReviewLine label="Risks" text={review.risks} />}
        </div>
      )}
    </Link>
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