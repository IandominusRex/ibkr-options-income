import Link from "next/link";
import { UNKNOWN } from "@/lib/format";
import { IdealZoneBar } from "./IdealZoneBar";
import { ReviewPanel } from "./ReviewPanel";
import { AlternativesTable } from "./AlternativesTable";
import type { ApprovalDetail } from "./types";

export function ApprovalDetailCard({ detail }: { detail: ApprovalDetail }) {
  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/options"
          className="text-xs text-muted hover:text-content"
        >
          Back to approvals
        </Link>
      </div>

      <header className="flex items-baseline justify-between gap-3">
        <h1 className="font-mono text-2xl text-content">
          {detail.underlying} {detail.strike.toFixed(2)} {detail.right}
        </h1>
        <span className="text-sm text-muted">
          {detail.status} - {detail.source}
        </span>
      </header>

      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm tabular">
        <Field label="Contracts" value={String(detail.contracts)} />
        <Field
          label="Premium"
          value={detail.premium != null ? `$${detail.premium.toFixed(2)}/sh` : UNKNOWN}
        />
        <Field
          label="Total"
          value={
            detail.premium != null
              ? `$${(detail.premium * detail.contracts * 100).toFixed(0)}`
              : UNKNOWN
          }
        />
        <Field
          label="Score"
          value={detail.blended_score != null ? detail.blended_score.toFixed(1) : UNKNOWN}
        />
        <Field
          label="Expiry"
          value={detail.expiry ?? UNKNOWN}
        />
        {detail.order_state && (
          <Field label="Order" value={detail.order_state} />
        )}
      </div>

      {detail.ideal && (
        <section>
          <h2 className="mb-2 text-xs font-medium tracking-wide text-muted">
            Ideal zone
          </h2>
          <IdealZoneBar ideal={detail.ideal} premium={detail.premium} />
        </section>
      )}

      {detail.gate_reasons.length > 0 && (
        <section>
          <h2 className="mb-2 text-xs font-medium tracking-wide text-muted">
            Gate reasons
          </h2>
          <ul className="space-y-1 text-sm text-content">
            {detail.gate_reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </section>
      )}

      <ReviewPanel review={detail.review} />

      <AlternativesTable alternatives={detail.alternatives} />
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <span className="text-xs text-muted">{label} </span>
      <span className="text-content">{value}</span>
    </span>
  );
}