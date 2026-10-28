export interface DegradedNoticeProps {
  note: string;
}

/**
 * States a degraded reading in the backend's own words. The UI composes no
 * explanation of its own here - `note` (src/api/models/portfolio.py's
 * `PortfolioSummaryResponse.note`) is rendered verbatim, nothing added, nothing
 * paraphrased. Styled to read as a notice, not an error: a pressed-sage
 * block and plain text, no loss colour, no alarm chrome - a degraded reading is expected
 * (an EOD fallback, for instance), not a failure.
 */
export function DegradedNotice({ note }: DegradedNoticeProps) {
  return (
    <div data-testid="degraded-notice" role="note" className="rounded-xl bg-sunk px-3 py-2.5 text-sm text-content">
      {note}
    </div>
  );
}
