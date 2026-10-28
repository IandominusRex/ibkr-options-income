"use client";

import type { ReactNode } from "react";
import { DatePicker } from "@/components/ui/DatePicker";
import { FIELD_LABEL } from "@/components/ui/field";
import { UNKNOWN } from "@/lib/format";
import { CorrelationTable } from "./CorrelationTable";
import { ScoreBucketTable } from "./ScoreBucketTable";
import type { SystemPerformanceResponse, VerdictAgreementData } from "./types";

/**
 * The since/until window: the only controls on the surface. No apply button, no suggested weight,
 * no editable field that could reach the scoring config.
 */
export function WindowControls({
  since,
  until,
  onSinceChange,
  onUntilChange,
}: {
  since?: string;
  until?: string;
  onSinceChange?: (value: string) => void;
  onUntilChange?: (value: string) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="grid gap-1">
        <span className={FIELD_LABEL}>Since</span>
        <DatePicker data-role="window-control" aria-label="since" value={since ?? ""} max={until || undefined} onChange={(v) => onSinceChange?.(v)} />
      </div>
      <div className="grid gap-1">
        <span className={FIELD_LABEL}>Until</span>
        <DatePicker data-role="window-control" aria-label="until" value={until ?? ""} min={since || undefined} onChange={(v) => onUntilChange?.(v)} />
      </div>
    </div>
  );
}

/**
 * The score-vs-outcome evidence's reader (P3-P4 M6 Task 6.2) - the human `CLAUDE.md` says must
 * re-derive scoring_weights.yaml by hand from this evidence. Every note score_outcome_report
 * produces renders here in full and in order (the read-only sentence is why this surface is
 * allowed to exist at all); the panel offers no control that could change a weight, only the
 * since/until window, which a page may place itself (`windowControls={false}`). Presentational:
 * the page owns the fetch and the window state.
 */
export function SystemPanel({
  data,
  since,
  until,
  onSinceChange,
  onUntilChange,
  windowControls = true,
}: {
  data: SystemPerformanceResponse;
  since?: string;
  until?: string;
  onSinceChange?: (value: string) => void;
  onUntilChange?: (value: string) => void;
  windowControls?: boolean;
}) {
  const { report, agreement } = data;
  const notes = report.notes ?? [];

  return (
    <div className="space-y-5" data-testid="system-panel">
      {windowControls && (
        <WindowControls since={since} until={until} onSinceChange={onSinceChange} onUntilChange={onUntilChange} />
      )}

      <ul className="space-y-1 text-[0.8125rem] text-muted">
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
        <span className="tabular font-mono text-content">{agreement.n_closed}</span>
      </Headline>
    </div>
  );
}

function Rate({ value }: { value: number | null | undefined }) {
  if (value == null) {
    return <span className="tabular hatch font-mono text-unknown">{UNKNOWN}</span>;
  }
  return <span className="tabular font-mono text-content">{Math.round(value * 100)}%</span>;
}

function Headline({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[0.8125rem] text-muted">{label}</span>
      {children}
    </div>
  );
}
