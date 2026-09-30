"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import { UNKNOWN, relativeAge } from "@/lib/format";
import { DecideControls } from "./DecideControls";
import { IdealZoneBar } from "./IdealZoneBar";
import { ReviewPanel } from "./ReviewPanel";
import { RationaleTags } from "./RationaleTags";
import { AlternativesTable } from "./AlternativesTable";
import type { ApprovalDetail, ControlsResponse } from "./types";

export function ApprovalDetailCard({ detail }: { detail: ApprovalDetail }) {
  // The drain's health drives the receipt's `stalled` state (spec §9.2 rule 3).
  // Fetching it here (same as <ApprovalsList/>) lets the detail page's receipt
  // state "the trading service is not draining commands" in words when the
  // worker is dead — a hardcoded `true` would hide that, violating rule 3 on
  // this surface. `true` is the placeholder while the query loads so a
  // not-yet-known drain is NOT falsely reported as dead.
  const controls = useQuery({
    queryKey: ["options", "controls"],
    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
    placeholderData: (prev) => prev,
    refetchInterval: 30_000,
  });
  const drainHealthy = controls.data?.drain_healthy ?? true;
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

      <RationaleTags tags={detail.rationale_tags} />

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

      {detail.fills.length > 0 && (
        <section>
          <h2 className="mb-2 text-xs font-medium tracking-wide text-muted">
            Fills
          </h2>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-muted">
                <th className="py-2 font-medium">When</th>
                <th className="py-2 font-medium">Action</th>
                <th className="py-2 font-medium">Qty</th>
                <th className="py-2 font-medium">Price</th>
                <th className="py-2 font-medium">Mode</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {detail.fills.map((f) => (
                <tr key={f.id}>
                  <td className="py-2 text-xs text-muted">{relativeAge(f.filled_at)}</td>
                  <td className="py-2 text-content">{f.action}</td>
                  <td className="py-2 tabular text-content">{f.filled_qty.toFixed(0)}</td>
                  <td className="py-2 tabular text-content">${f.avg_price.toFixed(2)}</td>
                  <td className="py-2 text-xs text-muted">{f.is_live ? "live" : "paper"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <DecideControls approval={detail} drainHealthy={drainHealthy} />
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