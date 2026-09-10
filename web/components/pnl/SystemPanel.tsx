"use client";

import type { ReactNode } from "react";
import { UNKNOWN } from "@/lib/format";
import { CorrelationTable } from "./CorrelationTable";
import { ScoreBucketTable } from "./ScoreBucketTable";
import type { SystemPerformanceResponse, VerdictAgreementData } from "./types";

/**
 * The score-vs-outcome evidence's reader (P3-P4 M6 Task 6.2) - the human `CLAUDE.md` says
 * must re-derive scoring_weights.yaml by hand from this evidence. Every note
 * score_outcome_report produces renders here in full and in order (the read-only sentence is
 * why this surface is allowed to exist at all); the panel offers no control that could change
 * a weight - no apply button, no suggested weight, no editable field, only the since/until
 * window. Presentational, unlike SummaryPanel: PnlShell owns the fetch and the window state,
 * the same split EquityChart already uses.
 */
export function SystemPanel({
  data,
  since,
  until,
  onSinceChange,
  onUntilChange,
}: {
  data: SystemPerformanceResponse;
  since?: string;
  until?: string;
  onSinceChange?: (value: string) => void;
  onUntilChange?: (value: string) => void;
}) {
  const { report, agreement } = data;
  const notes = report.notes ?? [];

  return (
    <div className="space-y-5" data-testid="system-panel">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1 text-xs text-muted">
          Since
          <input
            type="date"
            data-role="window-control"
            aria-label="since"
            value={since ?? ""}
            onChange={(e) => onSinceChange?.(e.target.value)}
            className="rounded border border-border bg-surface px-2 py-1 text-xs text-content"
          />
        </label>
        <label className="flex items-center gap-1 text-xs text-muted">
          Until
          <input
            type="date"
            data-role="window-control"
            aria-label="until"
            value={until ?? ""}
            onChange={(e) => onUntilChange?.(e.target.value)}
            className="rounded border border-border bg-surface px-2 py-1 text-xs text-content"
          />
        </label>
      </div>

      <ul className="space-y-1 text-xs text-muted">
        {notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>

      <AgreementBlock agreement={agreement} />

      {report.n_closed > 0 && (
        <>
          <ScoreBucketTable buckets={report.blended_score_buckets ?? []} label="Blended score" />
          <ScoreBucketTable buckets={report.component_buckets ?? []} label="Score components" />
          <CorrelationTable correlations={report.signal_correlations ?? []} />
        </>
      )}
    </div>
  );
}

function AgreementBlock({ agreement }: { agreement: VerdictAgreementData }) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4" data-testid="agreement-block">
      <Headline label="Verdicts agreed">
        <Rate value={agreement.agreement_rate} />
      </Headline>
      <Headline label="Claude win rate">
        <Rate value={agreement.claude_win_rate} />
      </Headline>
      <Headline label="Baseline win rate">
        <Rate value={agreement.baseline_win_rate} />
      </Headline>
      <Headline label="Closed trades compared">
        <span className="tabular text-content">{agreement.n_closed}</span>
      </Headline>
    </div>
  );
}

function Rate({ value }: { value: number | null | undefined }) {
  if (value == null) {
    return <span className="tabular hatch text-unknown">{UNKNOWN}</span>;
  }
  return <span className="tabular text-content">{Math.round(value * 100)}%</span>;
}

function Headline({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      {children}
    </div>
  );
}
