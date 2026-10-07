import clsx from "clsx";
import type { LedgerOutcome } from "./types";

// The label is always printed - colour is a second cue, never the only one.
const TONE: Record<LedgerOutcome, string> = {
  Expired: "bg-gain/15 text-gain",
  "Bought back": "bg-gain/10 text-gain",
  Sold: "bg-gain/10 text-gain",
  Assigned: "bg-loss/15 text-loss",
  "Called away": "bg-focus/15 text-focus",
  Rolled: "bg-focus/10 text-focus",
  Exercised: "bg-elevated text-content",
  Open: "bg-elevated text-muted",
  Pending: "bg-elevated text-unknown",
};

export function OutcomePill({ outcome, overridden = false }: { outcome: LedgerOutcome; overridden?: boolean }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs", TONE[outcome])}>
      {outcome}
      {overridden && <span title="Outcome set by you" aria-label="overridden">*</span>}
    </span>
  );
}
